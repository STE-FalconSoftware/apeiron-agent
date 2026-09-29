# Playtest your game with an agent (the agent door)

An agent can play, inspect and operate a running Apeiron game with no screen pixels, no window
focus and no game-side code. This is the loop that was proven on a real multiplayer shooter
(2026-09-29): start the game from the menu, get a bot into the crosshair, fire, and read the
kill off the scoreboard — all through MCP.

## 1. Build with the door, launch at a tier

```bash
# a project's own executable (the game crate from `ngine new-game --project`):
cargo build --no-default-features --features player,server,agent-door
# then launch the shipped player against your pack, opening the door at a tier:
NGINE_PLAYER=1 NGINE_PLAY_BUNDLE=<Game>.ngpkg NGINE_AGENT_DOOR=drive ./<game-exe>
```

`ngine export --agent-door=drive` (or `project.export {agent_door}`, or the Export dialog's
**Agent door** row) does both for you and writes the tier into the launcher. Tiers:
`observe` (read-only; QA), `drive` (input, camera, travel, commands). **Shipping refuses any door**;
Test allows `observe` (compiled in as the ceiling: the build cannot be relaunched as Drive);
Development allows all. Off is not in the game at all.

## 2. Attach

`ngine mcp connect --game` (a dedicated server: add `--server`) speaks MCP on stdio, so register it
once: `claude mcp add game -- ngine mcp connect --game`. Loopback only, a per-run token, found
automatically. No MCP client? `python scripts/dev/gamedoor.py call game.info` does the same.

## 3. The loop

| Want | Op |
|---|---|
| What is this? | `game.info`, `agent.commands` (lists every op, its tier, its args) |
| Get past the menu | `game.menu {press:"Play Solo"}` (or Host / Join / `fields`) — read the buttons back from the reply |
| Match + scoreboard | `game.match`, `game.players` (name, team, kills, deaths, has_pawn) |
| Look at it | `screenshot` (an image the model can see) |
| Move / fire | `input.button {button:"MoveForward", hold_frames:120}`, `Primary`, `Jump`, … |
| Aim | `input.aim_at {player:"Bot 1"}` (name or player_id), `input.look {yaw_deg,pitch_deg}` |
| Read any component | `world.entity {name}` → `world.field {index, component, path}` |
| Why did that happen? | `logs.tail {lines, contains:"nav"}` |
| Bots stand still / walk into walls | `ai.brains` (per bot: behavior, active waypoint, goal, ROUTE outcome/blocked/stuck, next corners), then `nav.query {point}` / `{from,to}` (is it walkable? what route would it take?) |
| Cheats / debug | `console.list`, `console.run {command:"refill"}` — the game's own commands |
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
