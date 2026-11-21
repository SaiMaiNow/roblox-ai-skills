---
name: roblox-code
description: Write the Luau for a Roblox game the way it survives contact with a real playtest - server-authoritative, plain ModuleScript systems on a small Loader (no framework), plain RemoteEvents through one Net module, every tunable in Config, every rule that can be pure written as a pure Core module with a headless spec - and PROVE it on disk before Studio ever sees it, through four gates (rojo build, lune run test, selene, stylua) that run in about a second and need no Studio, then a fifth gate that playtests over the Studio MCP. Scaffolds a complete project that is green on the four disk gates before a line of game code exists. Use whenever the user wants Roblox game code written, a game project set up, Rojo/Rokit/Wally wired up, an existing Studio place moved onto disk, gameplay systems built, code reviewed for exploitability or replication bugs, or asks why their remote fires but nothing happens, why a script edit had no effect, why duplicate modules appeared, or why the character fights their own movement code.
---

# Roblox code that is proven before Studio sees it

> **First time on this machine?** Read `LOCAL.md` in this folder. If it does not exist, run the
> `roblox-skills-setup` skill (or copy `LOCAL.template.md` to `LOCAL.md` and fill it in).
> `LOCAL.md` holds your paths and tool locations; it is yours and is never shared.

The hard constraint on this platform is not the language, it is **feedback**.
Roblox Studio's built-in MCP server can now start and stop a playtest, run Luau
in the Client or Server DataModel while it plays, read the console and capture
the screen. That is real, and it is used below. But it is slow, it observes a
running game only narrowly, and an automated "pass" from it can be wrong.

So the rule is unchanged: **as much of the game as possible must be decidable
while it sits still**, on disk, in a second. Studio is the last step, not the
debugger.

```
write code on disk
  -> rojo build      does it parse and assemble?         ~1s
  -> lune run test    does the pure logic still hold?     no engine, no Studio
  -> selene           lint
  -> stylua --check   format
  -> rojo serve       Studio sees it     <- the FIRST time Studio is involved
  -> gate 5           scripted playtest over MCP: build stamp, no errors
  -> playtest         a human, for anything only a player can judge
```

`scripts/check.py` runs gates 1-4 in that order and stops at the first build
failure, because a project that will not build makes every later message noise
rather than signal. Gate 5 is described under "When Studio is finally involved".

---

## The five standing rules

These came out of a v1 post-mortem on a real game that had to be rebuilt. They
are not style preferences.

**1. Disk is the only source of truth.** Studio connects via `rojo serve`. Never
edit a script inside Studio, and never write script source over MCP (no
`multi_edit` on a script, no `execute_luau` that sets `.Source`). MCP is for
geometry, inspection, playtests and screenshots. (v1 died of Studio-to-disk
drift.)

**2. Pure logic lives in `src/shared/Core/`, Instances live at the edges.** If a
function can be written without touching an Instance, it must be. That is the
only reason any of this is testable at all.

**3. Gameplay and cross-client paths go through one `Net.luau`** of plain
RemoteEvents, every name declared in one place. The Loader is lifecycle only and
never transport. When you can only watch the game through a keyhole, the most
primitive debuggable transport wins.

**4. Cosmetics can never break gameplay.** Effects resolve async, fail inert,
every one pcall-isolated. (v1's grapple was killed by a tracer.)

**5. Every tunable lives in `src/shared/Config/`.** A balance pass must be a data
edit, never a code edit.

---

## No framework: ModuleScripts and a Loader

Earlier versions of this skill used Knit. **Knit is archived** - its author
explains in `Sleitnick/Knit/ARCHIVAL.md` that its name-keyed registry
(`Knit.GetService("X")`) carries no types, so editors cannot autocomplete it,
and that a ModuleScript returning a table is already a singleton. Do not add
Knit to new projects.

What replaces it is about a hundred lines, shipped by the scaffold as
`src/shared/Loader.luau`:

```lua
-- src/server/Systems/Damage.luau - every direct child of Systems/ is a system
local Damage = {}

function Damage.Init()  -- own setup only (create remotes, tables). Never call other systems.
end

function Damage.Start() -- runs after EVERY system's Init. Other systems are ready.
	local Combat = require(script.Parent.Combat) -- typed, autocompletes
end

return Damage
```

`Loader.load(script.Systems)` requires every system (sorted by name), runs every
`Init` in order, then each `Start` in its own thread. Any system that fails to
require, Init or Start is warned **by name** and skipped; the rest of the game
keeps running. It refuses duplicate names loudly (see the Rojo trap below) and
warns when a require takes more than five seconds, which means something yields
at the top level.

Rules that make it work:

- Require another system **inside `Start`** (or a function it calls), not at the
  top of the file. That removes require-order and circular-require problems.
- Talk to another system through its **functions and signals**, never by
  reaching into its tables. A system holding lots of public data is being used
  as hidden global state; that is the anti-pattern that sank Knit codebases.
- Internal state stays file-local (`local states = {}`), not on the returned
  table.

Full shapes: `references/patterns.md`.

---

## Server authority

> The server owns the game. Clients own the display.

| Responsibility | Lives on |
|---|---|
| Game state: health, inventory, score, ownership | **Server** |
| Game logic: damage, purchases, spawning, scoring | **Server** |
| Validation and anti-cheat | **Server** |
| Input, camera, local UI, visual feedback | Client |

Every value that arrives from a client is a **request**. Validate type, then
range, then ownership, before it changes anything:

```lua
remote.OnServerEvent:Connect(function(player: Player, target: unknown)
	if typeof(target) ~= "Vector3" then return end
	local char = player.Character
	if not char or not char.PrimaryPart then return end
	if (target - char.PrimaryPart.Position).Magnitude > MAX_REACH then return end
	-- only now is it a fact
end)
```

The exception worth naming: movement in a fast first-person game is usually
client-authoritative because server-authoritative movement feels awful. That is
a deliberate, documented trade, not an oversight - but it means the *consequences*
of movement (scoring, elimination, rewards) must stay on the server.

---

## Start a project

```bash
python ~/.claude/skills/roblox-code/scripts/new_project.py "Coin Dash" \
    --dir ~/Projects/CoinDash
cd ~/Projects/CoinDash
rokit install && wally install
python ~/.claude/skills/roblox-code/scripts/check.py
```

That last command must print **all gates green** before any game code is written.
A scaffold that cannot clear its own gates hides the first real failure behind
noise, so step 0 of every build order is "the gates are green with nothing in
the game yet".

What the scaffold gives you: a Rokit-pinned toolchain (rojo 7.7.1, wally 0.3.2,
selene 0.32.0, stylua 2.6.0, lune 0.11.1), Signal + Trove from Wally, the Loader
and boot pair, one example system per side, `Net.luau`, a frozen `GameConfig`,
one worked Core module with its spec, the headless runner, and a build stamp in
both boot scripts.

Rokit replaced Aftman (whose maintainer has moved on from Roblox tooling). It reads `aftman.toml`
and `foreman.toml` too, so an older project needs no changes beyond installing
Rokit.

---

## Move an existing Studio place onto disk

A place whose scripts live only in Studio has no files yet. **Connecting Rojo
first is how scripts get lost**: Rojo owns every subtree it maps, and anything
in a mapped subtree that is not on disk is removed on sync.

1. **Back up.** File > Save to File, a `.rbxl` that is never synced to.
2. **Get the code onto disk.** `rojo syncback` (Rojo 7.7+) turns an existing
   place into project files; read `rojo syncback --help` for the flags of the
   installed version. Copying scripts out by hand works for a small place.
3. **Map only code folders.** Point `$path` at the folders that hold scripts,
   not at all of `ReplicatedStorage` or `Workspace`, unless every instance in
   them is also on disk. Keep the place's existing folder names if it already
   has a clean layout; nothing here requires `Shared`/`Server`/`Client`.
4. **`rojo build` until green**, then `rojo serve` and connect once.
5. Retrofit the rules in order of payoff: one `Net.luau` (remotes created in
   systems move there), hardcoded numbers into `Config`, then Core modules with
   specs for the rules that decide outcomes. Run `check.py --fix` once so StyLua
   formats the whole tree in one commit.

Studio's own **Script Sync** (beta) also syncs scripts with files both ways and
needs no plugin. It is a fine way to edit in VS Code, but it has no project file,
so gate 1 (`rojo build`) cannot run against it. This skill stays on Rojo.

---

## Check it

```bash
python ~/.claude/skills/roblox-code/scripts/check.py            # gates 1-4
python ~/.claude/skills/roblox-code/scripts/check.py --fix      # let stylua rewrite
python ~/.claude/skills/roblox-code/scripts/check.py --skip-lint  # build + tests only
```

`rojo build` is the single highest-value command in Roblox development and it is
under-used: it parses every file and assembles the whole tree in about a second,
so it catches a syntax error, a bad `$path`, a file Rojo will not accept, and a
malformed instance file, all without Studio open.

---

## Writing a Core module and its spec

This is the shape that makes the gates worth having. Rules go in, Instances stay
out, and the spec pins the *intent*, not the implementation:

```lua
-- src/shared/Core/Flock.luau
-- Positions come in as flat x/z scalars, NOT Vector3. See the rule below.
function Flock.strays(xs: { number }, zs: { number }, cx: number, cz: number, radius: number): { number }
```

```lua
-- tests/Flock.spec.luau
local Flock = require("../src/shared/Core/Flock")

return {
	["a sheep exactly on the radius is not a stray"] = function()
		-- The boundary is the whole question: off by one here means the wolf
		-- takes a sheep the player was told was safe.
		assert(#Flock.strays({ 10 }, { 0 }, 0, 0, 10) == 0)
	end,
}
```

**Core modules take plain numbers, not Roblox datatypes.** `Vector3` and `CFrame`
are not globals in Lune, so a Core module that uses them cannot be required by a
spec at all. `require("@lune/roblox")` does provide them, but importing it into
the module under test defeats the point of Core being pure. Pass `(x, y, z)`
scalars across the boundary and build the `Vector3` at the edge, in the system.

**Requires are relative to the requiring file** and must start with `./` or
`../` (Luau require-by-string; current Lune and Roblox Studio both follow it). An
unprefixed string is read as an alias. Inside Core, require siblings as
`require("./Other")`: the same line then works under Lune and in Studio.

A spec that restates the implementation is worth nothing. A spec that pins the
boundary a designer argued about is worth the whole suite.

More patterns: `references/patterns.md`.

---

## The traps that cost real days

Full detail with symptoms in `references/traps.md`. The short list, because
knowing these exist is most of the value:

**A remote payload has THREE ends.** Sender, server relay, receiver. Change the
arguments at one and the untouched middle silently drops every packet - no error
anywhere. Grep the arity across all three before believing a fix.

**Two Rojo connections duplicate every new file.** Each new ModuleScript appears
twice. The Loader refuses the second copy with a `DUPLICATE system` warning; a
loader that did not would connect every handler twice. One server, one connect.

**ROJO OWNS ITS SUBTREE. A RUNTIME CHILD OF ONE IS DELETED ON THE NEXT CONNECT.**
Anything that must survive a sync has to live in the SOURCE Rojo serves - not in
code that creates it at runtime. This is not intermittent; it is what
reconciliation *is*. Measured 2026-09-09: a service dressed the map at runtime,
replacing 897 prop boxes with MeshParts. It worked - correct kinds, correct
placement, the map finally looked like a map. Then Rojo reconnected and every
tree vanished, because `Workspace.Map` is sourced from a file, and 897 instances
that are in the game and in no source file are, correctly, stale instances to
remove. It reads exactly like "Rojo is broken" and it is the opposite.

The trap underneath it: **`MeshId` is not settable from a Rojo `.model.json`
property table**, which is what pushes people to a runtime step in the first
place. The way out is not runtime - it is `.rbxmx`, Roblox's own XML model
format, where `MeshId` and `TextureID` are ordinary `<Content>` properties:

```xml
<Item class="MeshPart" referent="RBX1"><Properties>
  <Vector3 name="InitialSize"><X>5</X><Y>8.2</Y><Z>5</Z></Vector3>
  <Vector3 name="size"><X>10</X><Y>16.4</Y><Z>10</Z></Vector3>
  <Content name="MeshId"><url>rbxassetid://MESH_ID</url></Content>
  <Content name="TextureID"><url>rbxassetid://IMAGE_ID</url></Content>
</Properties></Item>
```

`InitialSize` is the mesh's NATURAL size and is what Roblox scales `size`
against; omit it and the mesh is stretched by whatever the importer guessed.
And **edit an rbxmx with an XML parser, never a regex** - a part carrying a
PointLight has a nested `<Item>`, so a flat scan produces unbalanced XML.
`rojo build` catches that, and is the reason to run it after any file rewrite.

**`ScaleTo` is a `Model` method, not a `MeshPart` one.** A MeshPart scales by
setting `.Size`. `clone:ScaleTo(n)` on a MeshPart throws on the first one it
touches - and no static check sees it, because it is a runtime member lookup.

**An established TCP connection is not a synced session.** An unaccepted "Would
you like to connect?" prompt blocked syncing for an entire session while
everything looked connected. That is what the build stamp in the boot scripts is
for: if that exact line is not in Output, Studio is not running your code and no
edit you make can possibly matter.

**A module field named like a function returns the function.** A field
`Thing.foo` and a function `Thing.foo` are the same key on the same table; the
caller gets a function where it expected data. Keep state file-local.

**A bare `pcall` hides the throw.** Always capture and warn the error, or the
failure becomes invisible and you debug the wrong layer for an hour.

**A grounded Humanoid brakes scripted velocity to a stop.** Setting WalkSpeed to
0 is itself a brake, and `ChangeState(Freefall)` loses to the 240Hz state
machine. `SetStateEnabled(Running, false)` with a guaranteed restore is the only
thing that holds.

**`execute_luau` drops all output if the script yields.** Split it into two
calls, or schedule with `task.delay` and return immediately.

**An automated playtest "pass" is a claim, not a fact.** Roblox's own playtest
agent can report a pass that other evidence contradicts. Gate 5 proves the build
booted cleanly; it does not prove the feature feels right.

**A verifier that cannot find its target must FAIL, not pass.** A check scoped to
the wrong name reported green while 361 defects shipped underneath it. "Not
found" is a failure result.

---

## Anti-patterns

| Anti-pattern | Why it bites | Instead |
|---|---|---|
| `wait()`, `spawn()`, `delay()` | Deprecated scheduler, imprecise | `task.wait/spawn/delay/defer` |
| A number hardcoded in a system | Balance passes become code changes | `src/shared/Config/` |
| Remote names as bare strings | Typos fail silently | Declared in `Net.luau` |
| Framework auto-remotes or a string-keyed service locator | Untyped, undebuggable through a keyhole | `Net.luau`, plain `require` |
| Knit in a new project | Archived, no types | ModuleScripts + `Loader` |
| Client-stored state | Exploitable by definition | Server |
| A system used as a bag of public data | Hidden global state | Functions and signals |
| `require` of another system at top level | Order and circular-require failures | Require inside `Start` |
| `require` inside a loop | Repeated resolution | Cache the reference |
| Unbounded `RunService.Heartbeat` work | Frame cost scales with players | Budget it, or use tags |

---

## When Studio is finally involved

`rojo serve`, connect once, then check the build stamp in Output.

The MCP tools below are the names in Roblox Studio's **built-in** MCP server
(late 2026). Third-party servers use other names; map them, do not guess.

- Inspect: `script_read` to confirm what Studio actually holds, `script_grep` /
  `script_search` to find call sites, `search_game_tree` and `inspect_instance`
  for the DataModel.
- Run: `execute_luau` takes a `datamodel_type` - `Edit` outside a playtest,
  `Client` or `Server` during one (`Edit` is rejected while playing). Call
  `get_studio_state` first to see which are available.
- Play: `start_stop_play`, `get_console_output`, `screen_capture`.

**Gate 5 - the scripted playtest.** After gates 1-4 are green and Studio is
synced:

1. `start_stop_play` to start.
2. `get_console_output`: the build stamp for **both** server and client must be
   there, and there must be no `[Loader]` warnings and no errors. A missing stamp
   means Studio is not running the code on disk - stop and fix the sync.
3. Optional, for the feature just built: `execute_luau` with
   `datamodel_type: "Server"` to read the state it should have produced. Keep the
   snippet non-yielding.
4. `start_stop_play` to stop. Always stop, even after a failure.

Two things to know about the boundary:

- `execute_luau`'s `require` is **cached**, so a changed module keeps running the
  old code. Verify via `.Source`, not by re-requiring.
- Gate 5 checks that the game boots and the systems start. Whether it is fun,
  readable or fair still needs a human, and the finding they bring back is real
  data - on one build, the only defect that mattered came from a playtest, not
  from any automated verification, because the test stage was not a faithful
  stand-in for a live player character.
