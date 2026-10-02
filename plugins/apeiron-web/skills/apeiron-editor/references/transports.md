# The driver, and how it reaches the editor

The editor serves **newline-delimited JSON-RPC over TCP on 127.0.0.1:8731** (the door the editor
opens at launch: on by default, `NGINE_MCP=0` vetoes it). `scripts/driver.py` is the supported client for that socket.

## Why use the driver rather than your own client

Four things are easy to get wrong, and each one fails in a way that looks like a different bug:

- **The session token.** The door is loopback-only, which is not an authorization story, so the
  editor mints a token per run into your user config dir and refuses clients that omit it. It is
  published **per port**, and the driver reads the one for the port it is talking to. Which port:
  `$NGINE_MCP_PORT`, else the running-editor registry (`<config>/instances/<pid>.json`) — the
  editor whose project contains your working directory, or the only editor running.
- **UTF-8 output.** Engine replies contain `—`, `→`, `·`. On a Windows cp1252 console a
  hand-rolled client raises `UnicodeEncodeError` *mid-print*, so a call that **succeeded** looks
  like it crashed. The driver reconfigures its own streams.
- **Failures that are not JSON-RPC errors.** Most refusals come back as ordinary reply *text*
  (`unknown tool …`, `unknown arg key …`), so a bad call is still a successful RPC. `driver.py
  call` exits **1** on them and **0** on success, decided by the reply's own `isError` flag.
- **Image blobs.** Captures return a path, not pixels, so a screenshot costs ~300 bytes of context
  instead of ~600 KB.

## Commands

```bash
python scripts/driver.py --help
```

| Command | Does |
|---|---|
| `launch [--release] [--auto-port] [--wait N]` | start the editor with the agent door on, wait until it *answers* (reuses a live one) |
| `ping` | is an editor listening? exit 0/1 |
| `status` | the editor's whole context — **always run this first** |
| `call <op> ['<json>']` | run one op |
| `catalog [domain]` | list op domains, or one domain's ops |
| `describe <op>` | one op's argument schema — **the per-op source of truth** |
| `find <query>` | search ops, graph nodes and playbooks together |
| `recipe [name]` | the editor's built-in task playbooks |
| `manifest` | `editor.skills_manifest` — digests of the recipes and guides THIS engine ships; compare before trusting cached skill text |
| `shot <out.png> [--ui] [--width N]` | screenshot to a file (`--ui` = the whole window incl. panels) |
| `batch <file.jsonl>` | many ops over one connection (`{"op":…,"args":…}` per line) |
| `measure [--off] [--width N] [--height N] [--ev100 N]` | pin capture size and exposure so two plates are comparable; `--off` releases the locks |

## Finding the editor

`driver.py launch` resolves the executable in this order, most explicit first:

| Rung | Where |
|---|---|
| 1 | `$NGINE_EDITOR` — an explicit path to the executable. Always wins. |
| 2 | `ngine where --json` — the engine's own resolver (the `ngine` CLI on `$PATH`, or `$NGINE_CLI`) |
| 3 | An installed engine: `$NGINE_HOME`, each `$NGINE_ENGINES` entry, then the default install root's `Engines/<version>/`, newest version first |
| 4 | `app-native` on `$PATH` |

The installed editor sits at the root of a version-named directory (`Engines/<version>/app-native`),
not in a `bin/` folder. Token files are looked up in the per-user config directory
(`$NGINE_CONFIG_DIR` verbatim if set, else `%APPDATA%/Ngine` on Windows, else
`$XDG_CONFIG_HOME/ngine` or `~/.config/ngine`).

If none hit, the driver prints every rung it tried and what it expected to find. Set
`$NGINE_EDITOR` and re-run.

## The log

Launch appends the editor's stdout to `ngine_editor.<port>.log` under `logs/` in your user config dir. The path is printed on every launch; read it whenever the editor
misbehaves. An orderly shutdown ends with a pipeline-cache save line; anything else is a crash
worth reporting.
