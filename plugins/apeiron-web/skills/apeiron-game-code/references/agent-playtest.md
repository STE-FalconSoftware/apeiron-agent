# Playtest your game with an agent (the agent door)

An agent can play, inspect and operate a running Apeiron game with no screen pixels, no window
focus and no game-side code. This is the loop that was proven on a real multiplayer shooter
(2026-09-29): start the game from the menu, get a bot into the crosshair, fire, and read the
kill off the scoreboard — all through MCP.

## 1. Build with the door, launch at a tier

```bash
# a project's own executable (the game crate from `ngine new-game --project`):
cargo build --no-default-features --features player,server,agent-door
# then launch the player beside its pack (it boots the .ngpkg next to it by itself),
# opening the door at a tier:
NGINE_AGENT_DOOR=drive ./<game-exe>
```

`ngine export --agent-door=drive` (or `project.export {agent_door}`, or the Export dialog's
**Agent door** row) does both for you: a door is compiled in by a SOURCE build only (the installed
player templates carry none), and the bundle then carries a `run.bat`/`run.sh` that sets the tier —
the only exported bundle that still has a launcher script. Tiers:
`observe` (read-only; QA), `drive` (input, camera, travel, commands). **Shipping refuses any door**;
Test allows `observe` (compiled in as the ceiling: the build cannot be relaunched as Drive);
Development allows all. Off is not in the game at all.

## 2. Attach

`ngine mcp connect --game` (a dedicated server: add `--server`) speaks MCP on stdio, so register it
once: `claude mcp add game -- ngine mcp connect --game`. Loopback only, a per-run token, found
automatically. No MCP client? `python scripts/dev/gamedoor.py call game.info` does the same.

### A web build (the game in a browser tab)

A tab cannot listen, so a web dev/QA build reaches the SAME ops through the hosted relay (or a
same-origin `postMessage` port for in-page test drivers):

```bash
scripts/build-web-player.sh --agent-door=drive     # dist-player-door/ (observe: read-only ceiling)
# serve it, open the game with ?agent_door=drive — the tab prints a token for THIS page load in
# the browser console and the in-game console (~), plus the two commands below with it filled in:
claude mcp remove apeiron-game -s user
claude mcp add --transport http --scope user apeiron-game https://relay.apeironengine.com/mcp --header "X-Apeiron-Key: <token>"
# or, with no MCP client:
python scripts/dev/gamedoor.py --relay https://relay.apeironengine.com --key <token> call game.info
```

The token changes on every reload (re-run the `add`). A published web game has no door at all; a
`?agent_door=` on it does nothing. `screenshot` is not served on the web door yet — use
`ui.tree`, `world.query` and `events.tail` to see the game.

## 3. The loop

| Want | Op |
|---|---|
| What is this? | `game.info`, `agent.commands` (lists every op, its tier, its args) |
| Get past the menu | `game.menu {press:"Play Solo"}` (or Host / Join / `fields`) — read the buttons back from the reply |
| Match + scoreboard | `game.match`, `game.players` (name, team, kills, deaths, has_pawn) |
| Look at it | `screenshot` (an image the model can see) |
| Move / fire | `input.action {action:"MoveForward", hold_frames:120}`, `Primary`, `Jump`, …; an axis action takes `{action:"Move", value:[x,y]}` |
| Deterministic window | `time.pause`, then `time.step {ticks:60}` (replies with the tick and the sim hash); `time.scale {scale:0.5}` for slow motion |
| Menus by widget, not pixels | `ui.tree` (every widget's id, name, text, activatable), then `ui.activate {widget:"Play"}` |
| Find things | `world.query {component, name, tag, position:[x,y,z], radius}` |
| What just happened? | `events.tail {since, category}` — the gameplay event stream (AI decisions, hits, script lines); page with `next` |
| Aim | `input.aim_at {player:"Bot 1"}` (name or player_id), `input.look {yaw_deg,pitch_deg}` |
| Read any component | `world.entity {name}` → `world.field {index, component, path}` |
| Why did that happen? | `logs.tail {lines, contains:"nav"}` |
| Bots stand still / walk into walls | `ai.brains` (per bot: behavior, active waypoint, goal, ROUTE outcome/blocked/stuck, next corners), then `nav.query {point}` / `{from,to}` (is it walkable? what route would it take?) |
| Cheats / debug | `console.list`, `console.run {command:"refill"}` — the game's own commands and console variables (`bot_count 8`); `debug.overlay {on:true}` shows the gameplay debugger |
| Game-specific facts | the game's registered commands, e.g. `arena.stats` |
| Trigger scripted behaviour | `game.event {name, args}` → your Blueprint `Event/OnNetEvent` / Rhai `on_net_event(name, args)`; read the answer back with `game.vars` |

Aim, then fire in **short bursts** and re-aim every time: targets move, and one `aim_at` is a
snapshot. A bounded loop (aim → 6-frame `Primary` → `game.players`) killed a bot in seconds.

## 4. Give your game its own ops

```rust
// from your game's setup(world):
gameplay::register_agent_command(world, "mygame.stats", "Shots and hits so far",
    serde_json::json!({"type":"object","properties":{}}),
    gameplay::AgentHandler::Observe(|w, _| Ok(serde_json::json!({ "shots": /* read w */ 0 }))))?;
gameplay::register_console_command(world, "refill", "refill — full health and ammo", |w, _args| {
    /* mutate w */ Ok("refilled".into())
})?;
```

An `Observe` handler receives `&World` and cannot mutate; a `Drive` handler receives `&mut World` and
is refused unless the door was launched at `drive`. Names are `namespace.verb`; `game.`, `world.`,
`input.`, `logs.`, `agent.`, `server.`, `console.` and `screenshot` are the engine's.

## Pitfalls that cost time

- The game redraws on demand: the door wakes the loop for you, but the **first** call after launch
  can take a few seconds while the game boots (the door opens on frame 1).
- `input.*` is the local player. On a dedicated server use `server.*` ops (`server.health`,
  `server.metrics`, `server.players`, `server.kick`) — the server has no local player.
- If bots or AI stand still, read `ai.brains` first (a plan outcome of `GoalOffMesh` on an open floor
  means the navmesh is wrong, not the bot), then `nav.query` to check a point or a route, then
  `logs.tail {contains:"nav"}`. This found three real defects in one session (see ADR 0040).
- The door reports what the world says; a green `game.players` row is evidence the game logic ran,
  not that it *looks* right — take a `screenshot` for that.

## 5. Turn a session into a test

The same ops are a scenario file's `steps` (`tests/<name>.ngtest`): `{ "op": "input.action", "args": {...} }`,
`{ "op": "time.step", "args": { "ticks": 60 } }`, inline `{ "assert": {...} }`, and final `asserts` — a
`door` assert reads any op's reply by JSON pointer (`{ "kind": "door", "call": "game.vars", "path": "/vars/won",
"equals": true }`), which is how a Rust command, a Blueprint or a Rhai script asserts. Run it headless
(`ngine-test tests/`, JUnit with `--junit`), in the editor (`qa.run_tests {host:"pie"}` or the Test Runner
window), or in a development build (`NGINE_SCENARIO=tests/walk.ngtest`, exit code = verdict). A failure
writes a repro bundle (scenario, per-step sim-hash trail, events, logs, `.ngreplay`);
`ngine-test --replay <bundle>` proves it fails the same way again.
