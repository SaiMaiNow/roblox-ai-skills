# Patterns

The shapes to copy. Each one exists because the alternative broke something.

---

## Layout

```
src/shared/Core/        pure Luau, headless-tested   - no Instances, no yielding
src/shared/Config/      every design tunable         - data only, frozen
src/shared/Net.luau     the one networking module    - plain RemoteEvents
src/shared/Loader.luau  require -> Init -> Start     - the whole lifecycle
src/server/Systems/     server-authoritative logic   - plain ModuleScripts
src/client/Systems/     input, camera, rendering     - plain ModuleScripts
tests/                  *.spec.luau                  - `lune run test`
lune/test.luau          the runner
```

Rojo maps `src/shared` to `ReplicatedStorage.Shared`, `src/server` to
`ServerScriptService.Server`, `src/client` to `StarterPlayerScripts.Client`.
`init.server.luau` and `init.client.luau` turn their folder into the Script
itself, which is why the boot files sit at the top of each folder and why
`script.Systems` is the folder next to them.

**ServerScriptService is never replicated to clients. ReplicatedStorage always
is.** A secret in `Shared/` is not a secret. Server-only data (loot tables, drop
rates, anti-cheat thresholds) belongs in `ServerStorage` or
`ServerScriptService`. If a category has both public and secret values, use the
same module name in both places.

An existing project with its own clean layout (say `Config/`, `Lib/`, `Shared/`,
`Systems/`) does not need renaming. The rules care about what lives where - pure
logic, tunables, transport, lifecycle - not about folder names.

---

## Server system

```lua
--!strict
-- src/server/Systems/Flock.luau
local ReplicatedStorage = game:GetService("ReplicatedStorage")

local Net = require(ReplicatedStorage.Shared.Net)
local Config = require(ReplicatedStorage.Shared.Config.GameConfig)
local Signal = require(ReplicatedStorage.Packages.Signal)

local Flock = {}

-- Public surface: functions and signals. Other systems use these.
Flock.SheepLost = Signal.new()

-- Private state stays file-local. Nothing outside this file can reach it,
-- which is the whole point.
local sheep: { [number]: Sheep } = {}
local lostRemote: RemoteEvent

function Flock.Init()
	-- Own setup only: create things other code will look for. Remotes go
	-- here so they exist before any client asks.
	lostRemote = Net.server("SheepLost")
end

function Flock.Start()
	-- Every Init has run; other systems are usable now. Require them HERE,
	-- not at the top of the file - no load order or circular-require trouble.
	local Wolf = require(script.Parent.Wolf)
	Wolf.Killed:Connect(function(sheepId: number)
		Flock.remove(sheepId)
	end)
end

function Flock.remove(sheepId: number)
	sheep[sheepId] = nil
	lostRemote:FireAllClients(sheepId)
	Flock.SheepLost:Fire(sheepId)
end

return Flock
```

The Loader runs every system's `Init` before any `Start`. That ordering is the
whole reason the two exist: reach for another system in `Start`, never in
`Init`, or you will get a half-built one.

`require(script.Parent.Wolf)` is fully typed - the editor autocompletes
`Wolf.Killed`. That is what a string-keyed registry such as
`Knit.GetService("WolfService")` cannot do, and why this skill no longer uses
one.

---

## Client system

```lua
--!strict
-- src/client/Systems/Flock.luau
local ReplicatedStorage = game:GetService("ReplicatedStorage")

local Net = require(ReplicatedStorage.Shared.Net)

local Flock = {}

local function playLossFeedback(sheepId: number)
	-- Display only, and pcall-isolated: cosmetics never break gameplay.
end

function Flock.Start()
	local lost = Net.client("SheepLost")
	if not lost then
		-- Fail inert. One dead feature, not a dead client.
		return
	end
	lost.OnClientEvent:Connect(function(sheepId: number)
		-- The sheep is already gone on the server; this just makes it look like it.
		local ok, err = pcall(playLossFeedback, sheepId)
		if not ok then
			warn(`[Flock] loss feedback failed inert: {err}`)
		end
	end)
end

return Flock
```

`Net.client` waits (with a timeout), so it belongs in `Start`, never at the top
level of the file: a top-level yield holds up every system the Loader has not
reached yet, and the Loader warns after five seconds.

---

## The Loader

The scaffold ships it; this is what it guarantees, so a hand-written one in an
existing project should too:

- Loads direct `ModuleScript` children of the folder only, sorted by name, so
  order is deterministic.
- **Refuses duplicate names with a warning** instead of loading both (two Rojo
  connections create each new file twice).
- `require`, `Init` and `Start` are each `pcall`-wrapped and a failure is warned
  with the system's name. One broken system never takes the others down.
- A system whose `Init` failed is not started.
- Each `Start` runs in its own `task.spawn`, so one long-running `Start` cannot
  block the rest.
- Warns when a `require` takes longer than five seconds.

---

## Net

One module, every remote name declared as a union type, created on the server
and awaited on the client with a timeout that returns nil rather than erroring.
The scaffold ships a working copy; add one line per remote with a comment saying
**who sends it, who receives it, and why it is separate from its neighbours**.

That comment is not decoration. On a real project, "server to the killer only"
and "server to all clients" ended up as two remotes precisely because writing
the comment surfaced that they were different audiences with different payloads.

```lua
export type EventName =
	-- client -> server: "I pulled the trigger", origin + direction. The server
	-- decides what was hit; this is a request, not a result.
	"Fire"
	-- server -> ONE client: apply this knockback to your own character.
	| "Impulse"
```

### RemoteEvent or RemoteFunction

Default to RemoteEvent. A RemoteFunction yields the caller until the other side
returns, and if it never returns the thread hangs forever.

| Case | Use |
|---|---|
| Player acts (fires, clicks, jumps) | RemoteEvent |
| Server tells everyone something happened | RemoteEvent, `FireAllClients` |
| Server tells one player something private | RemoteEvent, `FireClient` |
| Client genuinely needs an answer before continuing | RemoteFunction, with a timeout |

Never let a client invoke a RemoteFunction the server implements without
rate-limiting it: one client in a loop stalls the thread for everyone.

---

## Core module and spec

**Core takes plain numbers.** `Vector3` and `CFrame` are not globals in Lune
(measured: `attempt to index nil with 'new'`), so a Core module that uses them
cannot be required by a spec. Pass `(x, y, z)` scalars and construct the
datatype at the edge, in the system that owns the Instance.

Requires are relative to the requiring file and must start with `./` or `../`.
Inside Core, require siblings as `require("./Other")` - the same line resolves
under Lune and in Studio.

```lua
--!strict
-- src/shared/Core/Stamina.luau
local Stamina = {}

--- Drain per second while sprinting, refill per second otherwise. Returns the
--- new value, clamped. Pure: no Instances, no services, no yielding.
function Stamina.step(current: number, dt: number, sprinting: boolean, cfg: Cfg): number
	local delta = if sprinting then -cfg.DrainPerSecond else cfg.RefillPerSecond
	return math.clamp(current + delta * dt, 0, cfg.Max)
end

return Stamina
```

```lua
--!strict
-- tests/Stamina.spec.luau
local Stamina = require("../src/shared/Core/Stamina")

local CFG = { Max = 100, DrainPerSecond = 25, RefillPerSecond = 10 }

return {
	["sprinting cannot drive stamina negative"] = function()
		assert(Stamina.step(5, 1, true, CFG) == 0, "expected a floor at 0")
	end,

	["a full bar does not overfill"] = function()
		assert(Stamina.step(100, 1, false, CFG) == 100)
	end,

	["the shipped numbers give roughly four seconds of sprint"] = function()
		-- Pinning the DESIGN, not the code: if someone retunes DrainPerSecond
		-- this test fails and forces the conversation.
		local t, v = 0, CFG.Max
		while v > 0 and t < 60 do
			v = Stamina.step(v, 1 / 60, true, CFG)
			t += 1 / 60
		end
		assert(math.abs(t - 4) < 0.2, `expected ~4s of sprint, got {t}`)
	end,
}
```

Tests return a table of named functions and pass unless they error. Names are
read as prose in the output, so write them as claims.

---

## Cleanup with Trove

Every connection made must be destroyable, or a rejoining player leaks one of
everything.

```lua
local Trove = require(ReplicatedStorage.Packages.Trove)

local function spawnWolf(cfg)
	local trove = Trove.new()
	local wolf = trove:Add(WOLF_TEMPLATE:Clone())
	trove:Connect(RunService.Heartbeat, function(dt) hunt(wolf, dt) end)
	trove:Add(function() active[wolf] = nil end)
	return trove -- caller calls :Destroy() and everything above unwinds
end
```

---

## Performance

- Per-frame work goes on `RunService.Heartbeat`, never a `task.wait(0)` loop.
- `CollectionService` tags instead of walking the whole tree looking for things.
- `Debris:AddItem` for temporary instances in hot paths.
- Batch replication: one remote carrying twenty sheep positions beats twenty
  remotes, by a lot.
- Profile with the MicroProfiler (Ctrl+F6) before optimising. Every guess about
  Roblox performance made without it has a good chance of being backwards.
