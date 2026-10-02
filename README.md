# Apeiron for Claude Code

The official Claude Code marketplace for the Apeiron Engine. It carries **two plugins** with the same
skills, recipes and agents; they differ only in which editor they reach:

| Plugin | Reaches | MCP server | You need |
|---|---|---|---|
| **`apeiron`** | the editor installed on this PC | `ngine mcp bridge` (local, starts the editor for your project) | the Apeiron Engine installed |
| **`apeiron-web`** | the web editor at [engine.apeironengine.com](https://engine.apeironengine.com), in your browser | the hosted relay, `https://relay.apeironengine.com/mcp` (signed in with your Apeiron account) | nothing else |

From the first prompt your agent knows the editor, follows the engine's own workflows, and drives the
scene with measured evidence.

## Install — the installed editor (`apeiron`)

You need the Apeiron Engine installed first (the installer puts the `ngine` command on your PATH; the
launcher's **Connect your AI agent** card runs these two commands for you). In a terminal:

```
claude plugin marketplace add STE-FalconSoftware/apeiron-agent
claude plugin install apeiron@apeiron
```

(or `/plugin marketplace add …` and `/plugin install …` inside Claude Code). Restart Claude Code. The
first time your agent calls an `ngine.*` tool, the editor opens on the project in the folder you
started Claude Code in — and closes again when the session ends. Nothing to configure: no ports, no
tokens, no config files. The launcher keeps the plugin current after each engine update
(`claude plugin marketplace update apeiron`). Without the plugin,
`ngine mcp install --client claude-code --scope user --skills` registers the same MCP server and skills
from the installed engine; Codex, Cursor, Gemini CLI and VS Code use `ngine mcp install --client <name>`.

## Install — the web editor (`apeiron-web`)

Nothing to install but the plugin:

```
claude plugin marketplace add STE-FalconSoftware/apeiron-agent
claude plugin install apeiron-web@apeiron
```

Then in Claude Code run `/mcp`, choose **apeiron-web**, choose **Authenticate**, and sign in with your
Apeiron account in the page that opens. Open [engine.apeironengine.com](https://engine.apeironengine.com)
and sign in there with the same account: every signed-in tab is reachable by your agent with nothing
pasted (`tab.list` lists them, `tab.attach` picks one). `/apeiron-web:connect-web` walks through it;
`/apeiron-web:status` diagnoses it. Agents other than Claude Code use the tab's **Help > Connect AI
Agent** (a key-paired command) instead.

From an engine source checkout (developers): `/plugin marketplace add ./` then
`/plugin install apeiron@apeiron-dev` (or `apeiron-web@apeiron-dev`).

## What is in it

| Piece | What it does |
|---|---|
| **MCP server `ngine`** (`.mcp.json`) | `ngine mcp bridge --stdio --autolaunch`: the version-agnostic launcher. It picks the engine version your project is pinned to (else the newest installed), attaches to the editor already open on this folder's project (or starts one) and closes an editor it started when your session ends. It keeps working after an engine upgrade. |
| **Skills** `apeiron-editor`, `apeiron-game-code` | The engine's agent skills, copied verbatim from the package the engine ships. They route into the engine's own live recipes and guides (`ngine.recipes`, `ngine.guide`), which always match the installed version. |
| **Recipe skills** `recipe-<name>` | One generated stub per authoring and gameplay recipe the engine carries (table below), so Claude Code's own skill matching can pick the right workflow. A stub is a pointer: it tells the agent to load the real recipe from the running editor. |
| **Slash commands** (skills, user-invoked) | `/apeiron:status` (diagnose every link, with fixes), `/apeiron:launch`, `/apeiron:new-project`, `/apeiron:lookdev`, `/apeiron:report-issue` (files the report with the Apeiron team from the editor — never on GitHub), `/apeiron:connect-web` (pair a browser tab through the `apeiron-web` plugin). |
| **Agents** | `verifier` (read-only checks with measurements), `lookdev-judge`, `docs-scout`. |
| **SessionStart hook** | Runs `ngine mcp bridge --context` and tells the session which editor, if any, belongs to this folder (at most 40 lines). |

`apeiron-web` carries the same skills, recipe stubs and agents (generated from the same sources), its own
three commands (`/apeiron-web:connect-web`, `/apeiron-web:status`, `/apeiron-web:report-issue`), the relay as
an HTTP MCP server with MCP OAuth, and no SessionStart hook (there is no local editor to look for).

## Recipe skills

The engine compiles its task playbooks (`ngine.recipes`) into the editor. Each authoring and gameplay
recipe has a generated skill here, named `recipe-<name>`, whose description is the recipe's own and
whose body says to run `ngine.recipes {name: "<id>"}`. The recipe text is never copied, so a stub
cannot go stale against your engine; only its one-line description can. The session-discipline
recipes (`ngine/00-orientation` to `ngine/04-conventions`) have no stub of their own: `apeiron-editor`
routes to them, and its `references/recipes.md` says which recipe answers which task.

<!-- recipes:begin (generated by scripts/gen_sdk_skills.py) -->

| Domain | Stub skill | Recipe it points at | Ops it names |
|---|---|---|---|
| authoring | `recipe-character-rig` | `authoring/character-rig` | 85 |
| authoring | `recipe-cinematic-sequence` | `authoring/cinematic-sequence` | 25 |
| authoring | `recipe-lighting` | `authoring/lighting` | 28 |
| authoring | `recipe-lookdev` | `authoring/lookdev` | 21 |
| authoring | `recipe-loom-kitbash-architecture` | `authoring/loom-kitbash-architecture` | 25 |
| authoring | `recipe-loom-subassets` | `authoring/loom-subassets` | 12 |
| authoring | `recipe-material-graph` | `authoring/material-graph` | 22 |
| authoring | `recipe-motion-generation` | `authoring/motion-generation` | 20 |
| authoring | `recipe-pose-by-text` | `authoring/pose-by-text` | 18 |
| authoring | `recipe-post-process` | `authoring/post-process` | 23 |
| authoring | `recipe-procedural-cliffs` | `authoring/procedural-cliffs` | 14 |
| authoring | `recipe-rig-verify-fix` | `authoring/rig-verify-fix` | 22 |
| authoring | `recipe-scene-recreation` | `authoring/scene-recreation` | 20 |
| authoring | `recipe-source-control` | `authoring/source-control` | 12 |
| authoring | `recipe-terrain-erosion` | `authoring/terrain-erosion` | 6 |
| authoring | `recipe-terrain-slab-lookdev` | `authoring/terrain-slab-lookdev` | 0 |
| authoring | `recipe-terrain-worldgraph` | `authoring/terrain-worldgraph` | 10 |
| authoring | `recipe-texture-graph` | `authoring/texture-graph` | 15 |
| authoring | `recipe-vfx-from-reference` | `authoring/vfx-from-reference` | 20 |
| gameplay | `recipe-blueprints` | `gameplay/blueprints` | 17 |
| gameplay | `recipe-multiplayer` | `gameplay/multiplayer` | 33 |
| gameplay | `recipe-play-step-verify` | `gameplay/play-step-verify` | 9 |
| gameplay | `recipe-rhai-scripting` | `gameplay/rhai-scripting` | 11 |

<!-- recipes:end -->

The engine developer's own skills (`.claude/skills/ngine-*`: building, verifying and landing engine
changes) are deliberately NOT part of this plugin. They describe the engine's source checkout, which a
customer does not have.

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
- No background monitor (`experimental.monitors`) is declared. Claude Code marks that field experimental, and a
  monitor is only worth its context cost if something streams a line worth interrupting for; the editor
  has no such stream (`ngine mcp status` and `/apeiron:status` answer on demand), so a monitor would be
  noise, not a capability.
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
them. The command skills (`skills/status`, `launch`, `new-project`, `lookdev`, `report-issue`), agents, hook and this README are edited in place. To publish, run
`python scripts/gen_sdk_skills.py --plugin <checkout of the public repo>` and commit there.
