#!/usr/bin/env python3
"""Scaffold a Roblox game project that is green on the first commit.

Emits the layout, the pinned toolchain (Rokit), the Loader and its boot pair,
the Net transport, a Config module, one pure Core module with a passing spec,
and the headless test runner. `check.py` passes on a freshly scaffolded project, which is the point:
step 0 of any build order is "the gates are green with nothing in the game yet",
and a scaffold that cannot clear its own gates hides the first real failure.

    new_project.py "Coin Dash" --dir ~/Projects/CoinDash
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

ROKIT = """# {title} - pinned toolchain (run `rokit install`)
# Rokit also reads aftman.toml / foreman.toml, so older projects keep working.
[tools]
rojo = "rojo-rbx/rojo@7.7.1"
wally = "UpliftGames/wally@0.3.2"
selene = "Kampfkarren/selene@0.32.0"
stylua = "JohnnyMorganz/StyLua@2.6.0"
lune = "lune-org/lune@0.11.1"
"""

WALLY = """[package]
name = "{scope}/{pkg}"
version = "0.1.0"
registry = "https://github.com/UpliftGames/wally-index"
realm = "shared"

[dependencies]
# No framework. Knit is archived (see Sleitnick/Knit ARCHIVAL.md); lifecycle is
# the scaffold's own Loader and transport is Net.luau. These two are utilities.
Signal = "sleitnick/signal@2.0.3"
Trove = "sleitnick/trove@1.8.0"
"""

SELENE = """std = "roblox"

[rules]
unused_variable = "warn"
deprecated = "deny"
shadowing = "warn"
"""

STYLUA = """column_width = 100
indent_type = "Tabs"
quote_style = "AutoPreferDouble"
"""

LUAURC = """{
  "languageMode": "strict"
}
"""

GITIGNORE = """Packages/
ServerPackages/
DevPackages/
*.rbxlx.lock
sourcemap.json
"""

PROJECT = {
    "name": "",
    "tree": {
        "$className": "DataModel",
        "ReplicatedStorage": {
            "Packages": {"$path": "Packages"},
            "Shared": {"$path": "src/shared"},
        },
        "ServerScriptService": {"Server": {"$path": "src/server"}},
        "StarterPlayer": {
            "StarterPlayerScripts": {"Client": {"$path": "src/client"}}
        },
        "Workspace": {"$properties": {"FilteringEnabled": True}},
        "Lighting": {"$properties": {"Technology": "Future"}},
    },
}

SERVER_BOOT = '''--!strict
-- {title} - server entry point. Boot only; logic lives in Systems/.

local ReplicatedStorage = game:GetService("ReplicatedStorage")

local Loader = require(ReplicatedStorage.Shared.Loader)

Loader.load(script.Systems)

-- BUILD STAMP. If this exact line is not in Output on Play, Studio is NOT
-- running the code on disk. Check the Rojo plugin is actually CONNECTED and
-- syncing before debugging anything else - an established connection is not
-- the same as an accepted one.
print("[{title}] Server started - BUILD scaffold-1")
'''

CLIENT_BOOT = '''--!strict
-- {title} - client entry point. Boot only; logic lives in Systems/.

local ReplicatedStorage = game:GetService("ReplicatedStorage")

local Loader = require(ReplicatedStorage.Shared.Loader)

Loader.load(script.Systems)

-- BUILD STAMP - see the note in the server boot.
print("[{title}] Client started - BUILD scaffold-1")
'''

LOADER = '''--!strict
-- Loader - the whole lifecycle, in one small module. No framework.
--
-- Every direct ModuleScript child of a Systems folder is a system:
--
--   local MySystem = {{}}
--   function MySystem.Init()  end -- own setup only. Do NOT call other systems.
--   function MySystem.Start() end -- runs after EVERY Init. Other systems are ready.
--   return MySystem
--
-- Both functions are optional. Systems reach each other with a plain
-- require(script.Parent.Other), which keeps full types and autocomplete - the
-- thing a name-keyed service registry (Knit.GetService("X")) cannot give you.
--
-- Order: require all (sorted by name) -> Init all, in order -> Start each in its
-- own thread. A system that fails to require, Init or Start is warned BY NAME
-- and skipped; the rest of the game keeps running.

local SLOW_REQUIRE_SECONDS = 5

type System = {{ Init: (() -> ())?, Start: (() -> ())? }}

local Loader = {{}}

function Loader.load(folder: Instance): {{ [string]: System }}
\tlocal modules: {{ ModuleScript }} = {{}}
\tlocal seen: {{ [string]: boolean }} = {{}}
\tfor _, child in folder:GetChildren() do
\t\tif not child:IsA("ModuleScript") then
\t\t\tcontinue
\t\tend
\t\tif seen[child.Name] then
\t\t\t-- Two Rojo connections create every new file twice. Loading both
\t\t\t-- would connect every handler twice, so refuse loudly instead.
\t\t\tlocal where = folder:GetFullName()
\t\t\twarn(`[Loader] DUPLICATE system {{child.Name}} in {{where}} skipped. Rojo connected twice?`)
\t\t\tcontinue
\t\tend
\t\tseen[child.Name] = true
\t\ttable.insert(modules, child)
\tend
\ttable.sort(modules, function(a, b)
\t\treturn a.Name < b.Name
\tend)

\tlocal loaded: {{ {{ name: string, system: System }} }} = {{}}
\tfor _, module in modules do
\t\tlocal done = false
\t\ttask.delay(SLOW_REQUIRE_SECONDS, function()
\t\t\tif not done then
\t\t\t\tlocal secs = SLOW_REQUIRE_SECONDS
\t\t\t\twarn(`[Loader] {{module.Name}} still requiring after {{secs}}s - yield in Init/Start`)
\t\t\tend
\t\tend)
\t\tlocal ok, result = pcall(require, module)
\t\tdone = true
\t\tif ok and type(result) == "table" then
\t\t\ttable.insert(loaded, {{ name = module.Name, system = result :: System }})
\t\telseif ok then
\t\t\twarn(`[Loader] {{module.Name}} did not return a table - skipped`)
\t\telse
\t\t\twarn(`[Loader] require failed: {{module.Name}}: {{result}}`)
\t\tend
\tend

\tlocal ready: {{ [string]: System }} = {{}}
\tlocal order: {{ string }} = {{}}
\tfor _, entry in loaded do
\t\tlocal init = entry.system.Init
\t\tif init then
\t\t\tlocal ok, err = pcall(init)
\t\t\tif not ok then
\t\t\t\twarn(`[Loader] Init failed: {{entry.name}}: {{err}}`)
\t\t\t\tcontinue
\t\t\tend
\t\tend
\t\tready[entry.name] = entry.system
\t\ttable.insert(order, entry.name)
\tend

\tfor _, name in order do
\t\tlocal start = ready[name].Start
\t\tif start then
\t\t\ttask.spawn(function()
\t\t\t\tlocal ok, err = pcall(start)
\t\t\t\tif not ok then
\t\t\t\t\twarn(`[Loader] Start failed: {{name}}: {{err}}`)
\t\t\t\tend
\t\t\tend)
\t\tend
\tend

\treturn ready
end

return Loader
'''

NET = '''--!strict
-- Net - the ONLY networking transport for gameplay and cross-client paths.
--
-- No framework-generated remotes. Play mode can be observed only narrowly (the
-- console, a screenshot), so the most primitive debuggable transport wins: one
-- folder of plain RemoteEvents, created server-side, awaited client-side, every
-- name declared in this file and nowhere else.
--
-- Server: Net.server("EventName") -> RemoteEvent (creates on first use)
-- Client: Net.client("EventName") -> RemoteEvent? (nil on timeout - callers
--         must fail inert, never error)

local ReplicatedStorage = game:GetService("ReplicatedStorage")
local RunService = game:GetService("RunService")

local FOLDER_NAME = "{slug}Net"
local CLIENT_WAIT_TIMEOUT = 10

-- Every remote in the game is declared here. A name not on this list is a bug.
export type EventName = "Ping" -- replace: one entry per remote, each commented

local Net = {{}}

local function serverFolder(): Folder
\tassert(RunService:IsServer(), "Net.server is server-only")
\tlocal folder = ReplicatedStorage:FindFirstChild(FOLDER_NAME)
\tif not folder then
\t\tfolder = Instance.new("Folder")
\t\tfolder.Name = FOLDER_NAME
\t\tfolder.Parent = ReplicatedStorage
\tend
\treturn folder :: Folder
end

--- Server side: get (or create) the RemoteEvent for `name`.
function Net.server(name: EventName): RemoteEvent
\tlocal folder = serverFolder()
\tlocal existing = folder:FindFirstChild(name)
\tif existing and existing:IsA("RemoteEvent") then
\t\treturn existing
\tend
\tlocal remote = Instance.new("RemoteEvent")
\tremote.Name = name
\tremote.Parent = folder
\treturn remote
end

--- Client side: wait for the RemoteEvent for `name`. Returns nil rather than
--- erroring, so a missing remote degrades one feature instead of the client.
function Net.client(name: EventName): RemoteEvent?
\tlocal folder = ReplicatedStorage:WaitForChild(FOLDER_NAME, CLIENT_WAIT_TIMEOUT)
\tif not folder then
\t\twarn(`[Net] no {{FOLDER_NAME}} folder after {{CLIENT_WAIT_TIMEOUT}}s`)
\t\treturn nil
\tend
\tlocal remote = folder:WaitForChild(name, CLIENT_WAIT_TIMEOUT)
\tif not remote or not remote:IsA("RemoteEvent") then
\t\twarn(`[Net] remote {{name}} never arrived`)
\t\treturn nil
\tend
\treturn remote
end

return Net
'''

CONFIG = '''--!strict
-- GameConfig - every tunable in the game, in one place.
--
-- A number that a designer might want to change must live here, never inline in
-- a System. This is what makes a balance pass a data edit. Data only: return a
-- frozen table so nothing can mutate a tunable at runtime.

export type Config = {{
\tRespawnSeconds: number,
\tMaxPlayers: number,
}}

local GameConfig: Config = table.freeze({{
\tRespawnSeconds = 3,
\tMaxPlayers = 4,
}})

return GameConfig
'''

CORE = '''--!strict
-- Health - a worked example of what belongs in Core: pure functions over
-- numbers and tables, no Instances, no services, no yielding.
--
-- If a rule can be written without touching an Instance, it MUST be, because
-- that is what makes it testable in a second, with no Studio and no playtest.
-- Delete this module once the game has real ones - but keep the shape.

local Health = {{}}

--- Clamp a damage application. Returns the new health, never below zero.
function Health.applyDamage(current: number, amount: number, max: number): number
\tif amount <= 0 then
\t\treturn math.clamp(current, 0, max)
\tend
\treturn math.clamp(current - amount, 0, max)
end

--- Fraction of maximum, for a health bar. Guards a zero max rather than
--- returning inf, because a UI reading inf is a crash and a UI reading 0 is a
--- visible bug.
function Health.fraction(current: number, max: number): number
\tif max <= 0 then
\t\treturn 0
\tend
\treturn math.clamp(current / max, 0, 1)
end

return Health
'''

SPEC = '''--!strict
-- Requires are relative to THIS file (Luau require-by-string: ./ or ../).
local Health = require("../src/shared/Core/Health")

return {{
\t["damage never drops below zero"] = function()
\t\tassert(Health.applyDamage(10, 999, 100) == 0, "expected a floor at 0")
\tend,

\t["negative damage cannot heal"] = function()
\t\tassert(Health.applyDamage(50, -25, 100) == 50, "negative damage must be inert")
\tend,

\t["fraction guards a zero maximum"] = function()
\t\t-- The interesting case: 0/0 is nan and nan silently poisons every UI it
\t\t-- reaches, so this must be 0 and not merely "not an error".
\t\tassert(Health.fraction(0, 0) == 0, "expected 0, not nan")
\tend,
}}
'''

SERVER_SYSTEM = '''--!strict
-- Example - the shape every server System takes. Loaded by Shared/Loader.
--
-- The server owns game state. Anything a client sends is a REQUEST, validated
-- here before it changes anything.

local ReplicatedStorage = game:GetService("ReplicatedStorage")

local Net = require(ReplicatedStorage.Shared.Net)

local Example = {{}}

local ping: RemoteEvent

function Example.Init()
\t-- Own setup only. Create remotes here so they exist before any client asks.
\tping = Net.server("Ping")
end

function Example.Start()
\t-- Every Init has run. Another system is reached with a plain require:
\t--   local Other = require(script.Parent.Other)
\tping.OnServerEvent:Connect(function(player: Player, payload: unknown)
\t\t-- Validate every client input. Type first, then range, then ownership.
\t\tif typeof(payload) ~= "string" or #payload > 64 then
\t\t\treturn
\t\tend
\t\tprint(`[Example] {{player.Name}} says {{payload}}`)
\tend)
end

return Example
'''

CLIENT_SYSTEM = '''--!strict
-- Example - the shape every client System takes. Loaded by Shared/Loader.
--
-- Clients own input and display. They ask; they never decide.

local ReplicatedStorage = game:GetService("ReplicatedStorage")

local Net = require(ReplicatedStorage.Shared.Net)

local Example = {{}}

function Example.Start()
\tlocal ping = Net.client("Ping")
\tif not ping then
\t\t-- Fail inert: one dead feature, not a dead client.
\t\treturn
\tend
\tping:FireServer("hello")
end

return Example
'''

RUNNER = '''--!strict
-- Headless test runner: `lune run test`
--
-- Runs every tests/*.spec.luau as a plain Luau module returning
-- {{ [testName]: () -> () }}. A test passes unless it errors (use assert).
-- Pure modules in src/shared/Core are required directly - no Roblox engine, no
-- Studio, no play mode.

local fs = require("@lune/fs")
local process = require("@lune/process")

local TESTS_DIR = "tests"

local passed, failed = 0, 0

if not fs.isDir(TESTS_DIR) then
\tprint("No tests/ directory - nothing to run.")
\tprocess.exit(0)
end

for _, fileName in fs.readDir(TESTS_DIR) do
\tif not fileName:match("%.spec%.luau$") then
\t\tcontinue
\tend
\tlocal specPath = `{{TESTS_DIR}}/{{fileName}}`
\t-- fs paths are relative to the CWD (run from the project root), but require
\t-- is relative to THIS file (Luau require-by-string), and an
\t-- unprefixed path is read as an alias. This file lives in lune/, hence ../
\tlocal requirePath = `../{{TESTS_DIR}}/{{fileName:gsub("%.luau$", "")}}`
\tlocal ok, specOrErr = pcall(require, requirePath)
\tif not ok then
\t\tfailed += 1
\t\tprint(`FAIL {{specPath}} (could not load): {{specOrErr}}`)
\t\tcontinue
\tend
\tfor testName, testFn in specOrErr :: {{ [string]: () -> () }} do
\t\tlocal testOk, err = pcall(testFn)
\t\tif testOk then
\t\t\tpassed += 1
\t\t\tprint(`PASS {{fileName}} :: {{testName}}`)
\t\telse
\t\t\tfailed += 1
\t\t\tprint(`FAIL {{fileName}} :: {{testName}}\\n     {{err}}`)
\t\tend
\tend
end

print(`\\n{{passed}} passed, {{failed}} failed`)
process.exit(if failed > 0 then 1 else 0)
'''

README = """# {title}

## The five standing rules

1. **Disk is the only source of truth.** Studio connects via `rojo serve`. Never
   edit scripts inside Studio, never write script source over MCP. MCP is for
   geometry, inspection, playtests and screenshots.
2. **Pure logic lives in `src/shared/Core/`, Instances live at the edges.** If a
   function can be written without touching an Instance, it must be. That is
   what makes it testable in a second, without Studio.
3. **Gameplay and cross-client paths use `src/shared/Net.luau`** (plain
   RemoteEvents). `Loader` is lifecycle only; it is never transport.
4. **Cosmetics can never break gameplay.** Effects resolve async, fail inert,
   and every one is pcall-isolated.
5. **Every tunable lives in `src/shared/Config/`.** Never hardcode a number in a
   System.

## Layout

```
src/shared/Core/        pure Luau, headless-tested   - no Instances
src/shared/Config/      every design tunable         - data only
src/shared/Net.luau     the one networking module    - plain RemoteEvents
src/shared/Loader.luau  require -> Init -> Start     - the whole lifecycle
src/server/Systems/     server-authoritative logic   - plain ModuleScripts
src/client/Systems/     input, camera, rendering     - plain ModuleScripts
tests/                  *.spec.luau, headless        - `lune run test`
```

## Commands

```sh
rokit install                  # pinned tools
wally install                  # Signal, Trove -> Packages/
rojo serve                     # live-sync to Studio (the ONLY sync path)
lune run test                  # headless test suite
selene src                     # lint
stylua src lune                # format
python check.py                # all gates in order
```
"""


def slugify(name: str) -> str:
    """PascalCase, for Luau identifiers and instance names."""
    return re.sub(r"[^A-Za-z0-9]", "", name.title()) or "Game"


def packagename(name: str) -> str:
    """Wally is strict: lowercase, digits and hyphens only."""
    kebab = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    return kebab or "game"


def write(path: Path, text: str) -> None:
    # newline="" stops Python translating line endings on Windows. StyLua
    # normalises to LF, so without this every generated file comes back as
    # entirely unformatted - a confusing thing for a first gate to report.
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="") as fh:
        fh.write(text)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("title", help='game name, e.g. "Coin Dash"')
    ap.add_argument("--dir", required=True, help="target directory (created if absent)")
    ap.add_argument("--scope", default="joncodea", help="wally package scope")
    ap.add_argument("--force", action="store_true", help="write into a non-empty directory")
    a = ap.parse_args()

    root = Path(a.dir).expanduser()
    if root.exists() and any(root.iterdir()) and not a.force:
        raise SystemExit(f"{root} is not empty. Pass --force if you meant to write into it.")

    title = a.title
    slug = slugify(title)
    fmt = {"title": title, "slug": slug, "pkg": packagename(title), "scope": a.scope}

    project = json.loads(json.dumps(PROJECT))
    project["name"] = title

    write(root / "rokit.toml", ROKIT.format(**fmt))
    write(root / "wally.toml", WALLY.format(**fmt))
    write(root / "selene.toml", SELENE)
    write(root / "stylua.toml", STYLUA)
    write(root / ".luaurc", LUAURC)
    write(root / ".gitignore", GITIGNORE)
    write(root / "README.md", README.format(**fmt))
    write(root / "default.project.json", json.dumps(project, indent=2) + "\n")

    write(root / "lune" / "test.luau", RUNNER.format(**fmt))
    write(root / "src" / "shared" / "Net.luau", NET.format(**fmt))
    write(root / "src" / "shared" / "Loader.luau", LOADER.format(**fmt))
    write(root / "src" / "shared" / "Config" / "GameConfig.luau", CONFIG.format(**fmt))
    write(root / "src" / "shared" / "Core" / "Health.luau", CORE.format(**fmt))
    write(root / "tests" / "Health.spec.luau", SPEC.format(**fmt))
    write(root / "src" / "server" / "init.server.luau", SERVER_BOOT.format(**fmt))
    write(root / "src" / "server" / "Systems" / "Example.luau", SERVER_SYSTEM.format(**fmt))
    write(root / "src" / "client" / "init.client.luau", CLIENT_BOOT.format(**fmt))
    write(root / "src" / "client" / "Systems" / "Example.luau", CLIENT_SYSTEM.format(**fmt))

    print(f"scaffolded {title} -> {root}")
    print("\nnext, from that directory:")
    print("  rokit install")
    print("  wally install")
    print("  python ~/.claude/skills/roblox-code/scripts/check.py")
    print("\nthe scaffold is green on all gates before you write a line of game code.")
    print("if it is not, the toolchain is broken and nothing after this is trustworthy.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
