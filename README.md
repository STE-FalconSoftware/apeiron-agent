# Apeiron for Claude Code

The official Claude Code plugin and marketplace for the Apeiron Engine. Two slash commands connect
your Claude Code to the engine you installed; from the first prompt your agent knows the editor,
follows the engine's own workflows, and drives the scene with measured evidence.

## Install

This plugin lives in the public `STE-FalconSoftware/apeiron-agent` repository. Without the plugin,
`ngine mcp install --client claude-code --scope user --skills` registers the same MCP server and skills
from the installed engine.

You need the Apeiron Engine installed first (the installer puts the `ngine` command on your PATH).
In Claude Code:

```
/plugin marketplace add STE-FalconSoftware/apeiron-agent
/plugin install apeiron@apeiron
```

Restart Claude Code. The first time your agent calls an `ngine.*` tool, the editor opens on the
project in the folder you started Claude Code in — and closes again when the session ends. Nothing
to configure: no ports, no tokens, no config files.

From an engine source checkout (developers): `/plugin marketplace add ./` then
`/plugin install apeiron@apeiron-dev`.

## What is in it

| Piece | What it does |
|---|---|
| **MCP server `ngine`** (`.mcp.json`) | `ngine mcp bridge --stdio --autolaunch`: the version-agnostic launcher. It picks the engine version your project is pinned to (else the newest installed), attaches to the editor already open on this folder's project (or starts one) and closes an editor it started when your session ends. It keeps working after an engine upgrade. |
| **Skills** `apeiron-editor`, `apeiron-game-code` | The engine's agent skills, copied verbatim from the package the engine ships. They route into the engine's own live recipes and guides (`ngine.recipes`, `ngine.guide`), which always match the installed version. |
| **Commands** | `/apeiron:status` (diagnose every link, with fixes), `/apeiron:launch`, `/apeiron:new-project`, `/apeiron:lookdev`, `/apeiron:report-issue`. |
| **Agents** | `verifier` (read-only checks with measurements), `lookdev-judge`, `docs-scout`. |
| **SessionStart hook** | Runs `ngine mcp bridge --context` and tells the session which editor, if any, belongs to this folder (at most 40 lines). |

## Version handshake

`plugins/apeiron/.claude-plugin/plugin.json` records the engine range its skills were written for
(`metadata.engine`). The server entry hands the same range to the bridge; when the running engine is
outside it, the bridge adds a SKILL MISMATCH warning to the session's instructions — once — and the
skills tell the agent to prefer the live surface. `editor.skills_manifest` returns digests of the
recipes and guides the running engine ships.

## Permissions

A plugin cannot ship a permission allowlist, so nothing here is pre-approved. Claude Code will ask
before an `ngine.*` tool runs the first time. The engine's discovery tools (`ngine.guide`,
`ngine.catalog`, `ngine.describe`, `ngine.find`, `ngine.search`, `ngine.recipes`) only read;
destructive ops carry the MCP `destructiveHint`, so Claude Code keeps prompting for them. Approve
the discovery tools once in your own settings if you want fewer prompts.

## Not covered here

- The Stop-hook ledger of unverified writes is not shipped yet.
- On Windows the plugin's server entry names `ngine` directly, and Claude Code spawns it without a
  shell. The installer therefore puts a REAL `ngine.exe` (a copy of the CLI) in `<root>\bin\`, on your
  PATH — not a `.cmd` forwarder, which a no-shell spawner cannot run. **UNVERIFIED:** this has not been
  run on a real Windows install with a real Claude Code; if `ngine` does not start, run
  `ngine mcp install --client claude-code --scope user` from a terminal (it writes whichever spelling
  your PATH resolves) and `ngine doctor` to see which link is broken.
- The `verifier` and `lookdev-judge` agents are ADVISORY about being read-only: their instructions say
  to call only read ops, but Claude Code cannot restrict an agent to the engine's `readOnlyHint` ops
  (the engine's tools are the meta tools `ngine.call` / `ngine.batch`, which carry write ops too).
  Do not treat them as a safety boundary.

## Generated, not hand-edited

The files under `plugins/apeiron/skills/`, `plugins/apeiron/.claude-plugin/plugin.json`,
`plugins/apeiron/.mcp.json` and both `marketplace.json` files are generated from the engine
repository by `python scripts/gen_sdk_skills.py`; `--check` (run by the pre-push hook) byte-compares
them. The commands, agents, hook and this README are edited in place. To publish, run
`python scripts/gen_sdk_skills.py --plugin <checkout of the public repo>` and commit there.
