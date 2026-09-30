#!/usr/bin/env python3
"""Drive the running Ngine editor over its live MCP JSON-RPC socket.

The editor (agent door on by default; NGINE_MCP=0 closes it) serves newline-delimited JSON-RPC over TCP on
127.0.0.1:8731 (one request line -> one response line). This is the agent's hands.

Every subcommand is safe to run repeatedly. Read-only ops (status/catalog/describe/
recipe) never mutate the scene. See SKILL.md for the workflow.

WHICH PORT: `NGINE_MCP_PORT` if set (verbatim, and the only thing that ISOLATES two agents in one
checkout), else the port the last `launch` recorded here if an editor is still listening on it,
else 8731. Every subcommand prints the port and where the number came from on stderr.

Usage:
    driver.py launch [--release] [--wait N] [--auto-port] [--port N]
                                              start the editor with MCP on, wait for the port
    driver.py port                            which port would this driver use, and why
    driver.py ping                            is an editor listening? (exit 0/1, no handshake noise)
    driver.py status                          editor.context -- ALWAYS run this first
    driver.py manifest                        editor.skills_manifest -- do my skills match this engine?
    driver.py call <op> [json-args]           ngine.call {op, args}
    driver.py catalog [domain]                list domains, or one domain's ops
    driver.py describe <op>                   one op's arg schema
    driver.py find <query>                    ngine.search across ops/nodes
    driver.py recipe [name] [--part ID]       list/fetch the engine's own agent skills
    driver.py shot <out.png> [--ui] [--max N] screenshot to a file (viewport, or --ui for full window)
    driver.py batch <file.jsonl>              many ngine.call specs, one JSON object per line

Exit codes: 0 ok, 1 op-level error, 2 could not reach the editor.
"""

import argparse
import json
import os
import tempfile
import shutil
import socket
import subprocess
import sys
import time

HOST = "127.0.0.1"
DEFAULT_PORT = 8731
# Resolved for real by `resolve_port()` at the top of `main()`, which also sets PORT_SOURCE. The
# module-level value is only the env/default rung, so an import-time reader still gets something
# sane.
PORT = int(os.environ.get("NGINE_MCP_PORT", str(DEFAULT_PORT)))
PORT_SOURCE = "NGINE_MCP_PORT" if os.environ.get("NGINE_MCP_PORT") else "default"

# Default PINNED capture size for `shot` (scene.screenshot's offscreen viewport). See
# cmd_shot for why a size-less capture is not comparable across calls.
PIN_W, PIN_H = 1280, 720

# How to spell THIS script in advice the driver prints. Computed from where the script actually is,
# so the same file is right in a customer's `~/.agents/skills/apeiron-editor/scripts/` and in a
# developer checkout, and no path of either home is baked into a string (AXR-47).
SELF_CMD = f'python "{os.path.abspath(__file__)}"'

# The engine's replies contain box-drawing chars, arrows and middots. On Windows the
# default console codepage (cp1252) raises UnicodeEncodeError mid-print and the call
# LOOKS like it failed when it actually succeeded. Fix it here so no caller has to
# remember PYTHONIOENCODING=utf-8.
for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass


def token_search_path(port=None):
    """The files `session_token` looks in, in order — for error messages.

    Named separately so a refusal can say where it ACTUALLY looked. Order:

    1. `mcp.<port>.token` — the PORT-KEYED file, written by the editor that owns that port;
    2. the token file a live editor's instance record names (`<config>/instances/<pid>.json`,
       AXR-7) — the registry answer, exact even when the port is not the default;
    3. the legacy shared `mcp.token` — ONE slot every older editor overwrites at launch, so with
       two editors live it holds whichever started last. Read last, and only for an editor too
       old to publish the keyed file; current editors no longer write it.
    """
    base = config_dir()
    out = []
    if port:
        out.append(os.path.join(base, f"mcp.{port}.token"))
        out.extend(instance_token_files(port))
    out.append(os.path.join(base, "mcp.token"))
    return out


def config_dir():
    """The per-user config directory — EXACTLY `settings::user_config_dir` in the engine.

    ONE definition: the MCP token path and the installed-SDK log directory both need it. The rule
    (the engine's `settings::user_config_dir`): `$NGINE_CONFIG_DIR` verbatim (the engine does NOT append a
    product folder to it), else `%APPDATA%/Ngine` on Windows, else `$XDG_CONFIG_HOME/ngine`, else
    `~/.config/ngine`. The driver used to join `Ngine` onto `$NGINE_CONFIG_DIR` while the engine did
    not, so with the variable set the token was looked for one directory too deep and never found.
    `self_test_config_dir` pins the rule.
    """
    env = os.environ
    nonempty = lambda k: (env.get(k) or "").strip() and env.get(k)  # noqa: E731
    if nonempty("NGINE_CONFIG_DIR"):
        return env["NGINE_CONFIG_DIR"]
    if os.name == "nt" and nonempty("APPDATA"):
        return os.path.join(env["APPDATA"], "Ngine")
    if nonempty("XDG_CONFIG_HOME"):
        return os.path.join(env["XDG_CONFIG_HOME"], "ngine")
    home = env.get("HOME") or os.path.expanduser("~")
    return os.path.join(home, ".config", "ngine")


def instance_records():
    """Live editor instance records (`<config>/instances/<pid>.json`, AXR-7), newest first.

    A record whose port no longer answers is ignored (a crashed editor leaves its file behind, and
    the engine's own sweep only runs when something reads the registry through it) — the same
    liveness rule as `install_layout::instances`.
    """
    found = []
    try:
        names = os.listdir(os.path.join(config_dir(), "instances"))
    except OSError:
        return found
    for name in names:
        if not name.endswith(".json"):
            continue
        try:
            with open(os.path.join(config_dir(), "instances", name), encoding="utf-8") as fh:
                rec = json.load(fh)
        except (OSError, ValueError):
            continue
        if isinstance(rec, dict) and isinstance(rec.get("port"), int) and port_open(port=rec["port"], timeout=0.3):
            found.append(rec)
    found.sort(key=lambda r: r.get("started_at", 0), reverse=True)
    return found


def instance_token_files(port):
    return [r["token_file"] for r in instance_records() if r.get("port") == port and r.get("token_file")]


def self_test_config_dir():
    """`python driver.py selftest` — the config-dir rule against `settings::user_config_dir`."""
    saved = dict(os.environ)
    try:
        for k in ("NGINE_CONFIG_DIR", "APPDATA", "XDG_CONFIG_HOME"):
            os.environ.pop(k, None)
        os.environ["NGINE_CONFIG_DIR"] = os.path.join("x", "cfg")
        assert config_dir() == os.path.join("x", "cfg"), "NGINE_CONFIG_DIR is used verbatim"
        del os.environ["NGINE_CONFIG_DIR"]
        os.environ["XDG_CONFIG_HOME"] = os.path.join("x", "xdg")
        os.environ["HOME"] = os.path.join("x", "home")
        if os.name == "nt":
            os.environ["APPDATA"] = os.path.join("x", "appdata")
            assert config_dir() == os.path.join("x", "appdata", "Ngine")
            del os.environ["APPDATA"]
        assert config_dir() == os.path.join("x", "xdg", "ngine")
        del os.environ["XDG_CONFIG_HOME"]
        assert config_dir() == os.path.join("x", "home", ".config", "ngine")
    finally:
        os.environ.clear()
        os.environ.update(saved)
    print("ok: config_dir matches settings::user_config_dir")
    self_test_registry()


def self_test_registry():
    """Registry selection and version ordering (the Python mirrors of install_layout)."""
    a = {"port": 8731, "project": os.path.join("w", "a")}
    b = {"port": 8732, "project": os.path.join("w", "b")}
    cwd_b = os.path.join("w", "b", "src")
    assert select_instance([a, b], cwd_b, "b")["port"] == 8732, "project contains cwd"
    assert select_instance([a, b], "elsewhere", None) is None, "two editors, no match: do not guess"
    assert select_instance([a], "elsewhere", None)["port"] == 8731, "one editor, cwd in no project"
    assert select_instance([a], cwd_b, os.path.join("w", "b")) is None, "one editor on ANOTHER project must not serve project b"
    assert select_instance([{"port": 1, "project": None}], cwd_b, "b")["port"] == 1, "an editor with no project serves anyone"
    assert path_within("/w/a/x", "/w/a") and not path_within("/w/ab", "/w/a"), "component, not text prefix"
    if os.name == "nt":
        assert path_within("C:\\Work\\A\\src", "c:/work/a"), "case-insensitive on Windows"
    assert version_key("0.2.0-preview.1") < version_key("0.2.0") < version_key("0.10.0")
    assert version_key("0.2.0-preview.2") < version_key("0.2.0-preview.10")
    print("ok: registry selection and version ordering")


def session_token(port=None):
    """The per-run MCP token the editor publishes, or None if it hasn't.

    The door is loopback-only but that is not an authorization story (every user session and
    every host-networked container shares loopback), so the editor mints a token per run and
    writes it to the user config dir. Reading it proves we can already read this user's files,
    which is the only claim it is meant to establish. Absent file = an older editor, or one that
    could not write the config dir; we simply omit the field and let the server decide.
    """
    for p in token_search_path(port):
        try:
            with open(p, encoding="utf-8") as fh:
                tok = fh.read().strip()
            if tok:
                return tok
        except OSError:
            continue
    return None


class Editor:
    """One connected JSON-RPC session against the live editor."""

    # Read-timeout default, overridable with NGINE_MCP_TIMEOUT (seconds).
    #
    # 180 s was hard-coded and is SHORTER THAN SOME LEGITIMATE OPS. Measured 2026-09-10:
    # `scene.bind_skin` on a 1,561,453-vertex character ran past it and surfaced as
    # `TimeoutError: timed out` — but the bind had SUCCEEDED (`scene.rig_query` showed 51 joints
    # right after). A client timeout that reports a COMPLETED WRITE as a failure is the worst
    # shape a timeout can have: the honest response to it is to re-run, and re-running a write
    # is how you get two of something. Raise it for heavy work rather than guessing:
    #
    #     NGINE_MCP_TIMEOUT=1800 python driver.py call scene.bind_skin '{...}'
    #
    # If you DO hit it, read the state back before re-issuing anything — the op may well be done.
    DEFAULT_TIMEOUT = float(os.environ.get("NGINE_MCP_TIMEOUT") or 180)

    def __init__(self, host=None, port=None, timeout=None):
        timeout = self.DEFAULT_TIMEOUT if timeout is None else timeout
        # NOT `port=PORT`: a default binds at DEF time, so --auto-port's later reassignment of the
        # global never reached it and every probe kept asking about 8731.
        host = HOST if host is None else host
        port = PORT if port is None else port
        try:
            self.sock = socket.create_connection((host, port), timeout=20)
        except OSError as e:
            die(
                f"no editor listening on {host}:{port} ({e}).\n"
                f"Launch one:  {SELF_CMD} launch",
                code=2,
            )
        self.sock.settimeout(timeout)
        self.timeout = timeout
        self._id = 0
        params = {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {"name": "run-ngine-driver", "version": "1"},
        }
        tok = session_token(port)
        if tok:
            # Both spellings the server accepts, so this works either way.
            params["token"] = tok
            params["clientInfo"]["token"] = tok
        reply = self._rpc("initialize", params)
        # AXR-45: `serverInfo.version` is the engine the skills are talking to. Kept on the object and
        # named once on stderr, so a transcript records WHICH engine every call went to.
        info = (reply.get("result") or {}).get("serverInfo") or {}
        self.engine_version = info.get("version")
        if self.engine_version:
            print(f"driver: engine {self.engine_version}", file=sys.stderr)
        err = reply.get("error") or {}
        msg = err.get("message", "") if isinstance(err, dict) else str(err)
        if "unauthorized" in msg.lower() or "token" in msg.lower():
            where = "\n  ".join(token_search_path(port))
            # NOT "relaunch the editor". That was the old advice and it is precisely wrong in the
            # case that actually happens: the token is not stale, it belongs to a DIFFERENT live
            # editor that overwrote the shared slot, and relaunching mints a third token — moving
            # the lockout to whichever instance you were not trying to fix. An agent session
            # followed that advice three times in an hour and rebuilt a scene each time.
            hint = (
                "a token was found and refused. If another editor is running on a DIFFERENT port,"
                f" this is the shared-slot collision: read mcp.{port}.token (the port-keyed file"
                " for THIS editor) rather than the shared mcp.token, and do NOT relaunch to"
                " 'refresh' it — that mints a third token and locks out the other instance."
                " Otherwise the editor on this port has restarted since the token was written;"
                " re-read the file."
                if tok
                else "no token file found — is an editor actually running on this port with"
                " the agent door open (NGINE_MCP=0 or the status bar closes it)?"
            )
            die(
                f"the editor refused this connection: {msg}\n{hint}\nlooked in:\n  {where}",
                code=2,
            )

    def _rpc(self, method, params=None):
        self._id += 1
        req = {"jsonrpc": "2.0", "id": self._id, "method": method}
        if params is not None:
            req["params"] = params
        self.sock.sendall((json.dumps(req) + "\n").encode("utf-8"))
        # One response line. Screenshot replies carry a base64 image and run to
        # several MB, so accumulate until the newline rather than a single recv.
        chunks = []
        while True:
            try:
                chunk = self.sock.recv(1 << 20)
            except socket.timeout:
                # NOT "the op failed". The editor is single-threaded over this socket, so a read
                # timeout means it is STILL BUSY — the write may well land. Measured 2026-09-10:
                # a bind_skin that timed out here had completed. Say that, rather than letting a
                # raw TimeoutError traceback imply a failure and invite a destructive re-run.
                die(
                    f"no reply from '{method}' within {self.timeout:g}s — this is a CLIENT "
                    f"timeout, NOT a failure. The editor is still working and the op may "
                    f"already have SUCCEEDED.\n"
                    f"  1. read the state back before re-issuing anything "
                    f"(scene.rig_query / scene.describe / <the op's own status read>)\n"
                    f"  2. re-run with a longer budget: NGINE_MCP_TIMEOUT=1800\n"
                    f"Heavy ops that legitimately exceed 180s: scene.bind_skin and the rig "
                    f"checks on a multi-million-vertex mesh, loom cooks, sequence.render.",
                    code=3,
                )
            if not chunk:
                break
            chunks.append(chunk)
            if chunk.endswith(b"\n"):
                break
        raw = b"".join(chunks)
        if not raw.strip():
            die("editor closed the connection mid-call (did it exit?)", code=2)
        return json.loads(raw.decode("utf-8"))

    def tool(self, name, arguments=None):
        return self._rpc("tools/call", {"name": name, "arguments": arguments or {}})

    def text(self, resp):
        """Flatten a tools/call reply to text, dropping inline image blobs.

        Screenshot ops return the PNG inline as base64. Printing that floods the
        context window with megabytes of noise, so it is replaced by a marker --
        pass an explicit path and Read the file instead.
        """
        if "error" in resp:
            return "ERROR: " + json.dumps(resp["error"])
        content = resp.get("result", {}).get("content", [])
        out = []
        for c in content:
            if c.get("type") == "image" or "data" in c:
                out.append("[inline image omitted -- Read the .png path above]")
            else:
                out.append(c.get("text", ""))
        return "\n".join(out).strip()


def die(msg, code=1):
    print(msg, file=sys.stderr)
    sys.exit(code)


# The engine reports most failures as ordinary reply TEXT, not as a JSON-RPC error,
# so a bad call still looks like a successful RPC.
#
# THE STRUCTURAL SIGNAL COMES FIRST, and the wording list below is only the fallback.
# `MpServer::exec_tool` returns `Err(text)` for every refusal and the reply carries
# `result.isError: true` (lib.rs, `tool_result(&text, true)`); the mcp suite asserts that
# flag directly. Reading the flag catches EVERY refusal; reading the prose catches only the
# refusals someone remembered to enumerate here. Measured 2026-08-31: the five argument
# coercions fixed in `2ef12b596` now refuse with messages like "argument 'kind' must be a
# string (noise | constant | river), got a number" and "'path' only applies to a RECORD
# session" -- correct `isError: true` replies, and not one of them matches a marker below.
# A script driving the editor therefore read every one of those refusals as a success.
#
# That is this tool's own failure mode, not the engine's: an instrument that reports a
# refusal as success is worse than no instrument. Keep the markers as a belt for a reply
# that somehow lacks the flag, but never let them be the primary test again.
FAILURE_MARKERS = (
    "unknown tool",
    "no tool '",
    "unknown arg key",
    "unknown op",
    "is not a registered",
    "refused",
    "error:",
    "[cook failed]",
    "empty cook",
)


def looks_failed(text):
    # ADVISORIES ARE NOT VERDICTS. The engine appends guidance to SUCCESSFUL replies after a
    # " · " separator, and that guidance routinely talks about refusals -- every write during
    # a Play session carries "...level.save is then refused until you reload the level from disk".
    # Matching the markers against the whole reply therefore reported every one of those
    # successful writes as a failure, which is this function's own stated failure mode in the
    # other direction: measured 2026-09-20, an authoring script died on its first
    # `scene.set_component_field` of a paused session, having written the value correctly.
    #
    # A genuine refusal says so in its opening clause, so that is the only part the prose belt
    # reads. The `isError` flag above is still the primary test and is unaffected.
    low = text.lower().lstrip().split(" · ", 1)[0]
    return any(m in low for m in FAILURE_MARKERS)


def call_failed(resp, text):
    """Did this `tools/call` fail? The reply's own flag first, prose only as a fallback.

    `resp` is the raw JSON-RPC reply, `text` its flattened content. A JSON-RPC-level
    `error` is unambiguous; `result.isError` is the MCP tool-error flag the engine sets on
    every `Err` return; the wording list is what is left for a reply carrying neither.
    """
    if "error" in resp:
        return True
    if resp.get("result", {}).get("isError") is True:
        return True
    return looks_failed(text)


def repo_root(required=True):
    """The engine SOURCE CHECKOUT, or None when this driver is running against an installed SDK.

    Only a developer copy of this file can find one: the customer copy
    (`sdk/agent-skills/.../driver.py`, generated by `scripts/gen_sdk_skills.py`) has the marked
    block below stripped, so it has no notion of a checkout at all — a customer has a binary and
    must not be told to find a source tree (AXR-47).
    """
    return None


# The editor executable's name on this platform. One definition — the `.exe` suffix was spelled
# inline in three places and each had to remember to strip it on non-Windows.
EDITOR_EXE = "app-native.exe" if os.name == "nt" else "app-native"


def cli_command():
    """The `ngine` CLI as an argv prefix, or None. Asked for `where --json` (AXR-3)."""
    explicit = os.environ.get("NGINE_CLI")
    if explicit and os.path.isfile(explicit):
        return [explicit]
    on_path = shutil.which("ngine")
    if on_path:
        return [on_path]
    return None


def ask_cli_where():
    """`ngine where --json` — the engine's own resolver (the `install-layout` crate), or None.

    The CLI knows the installed layout better than any second copy of the ladder in Python, so it is
    asked FIRST; the search below is only the fallback for a machine where the CLI is not on PATH.
    """
    cmd = cli_command()
    if not cmd:
        return None
    try:
        out = subprocess.run(cmd + ["where", "--json"], capture_output=True, text=True, timeout=20)
        doc = json.loads(out.stdout)
    except (OSError, ValueError, subprocess.SubprocessError):
        return None
    return doc if isinstance(doc, dict) else None


def version_key(v):
    """Sort key for engine directory names (`0.2.0-preview.1`): a pre-release sorts before its release."""
    core, _, pre = v.partition("-")
    nums = [int(p) if p.isdigit() else -1 for p in core.split(".")]
    ident = [(0, int(p), "") if p.isdigit() else (1, 0, p) for p in (pre.split(".") if pre else [])]
    return (nums, 1 if not pre else 0, ident)


def installed_editors():
    """Every installed editor, newest version first: `[(path, how)]`.

    Mirrors `install_layout::installed_in`: `$NGINE_ENGINES` entries and the
    default install roots' `Engines/<version>/`. `$NGINE_HOME` is honoured as an engine directory
    (or one holding `bin/`).
    """
    found = []
    seen = set()

    def add(version, directory, how):
        exe = os.path.join(directory, EDITOR_EXE)
        if os.path.isfile(exe) and exe not in seen:
            seen.add(exe)
            found.append((version, exe, how))

    home = os.environ.get("NGINE_HOME")
    if home:
        for d in (home, os.path.join(home, "bin")):
            add(os.path.basename(os.path.normpath(home)), d, "$NGINE_HOME")
    for entry in (os.environ.get("NGINE_ENGINES") or "").split(os.pathsep):
        entry = entry.strip()
        if not entry:
            continue
        version, sep, path = entry.partition("=")
        if not sep or not version.strip() or not path.strip():
            path = entry
            version = os.path.basename(os.path.normpath(entry))
        path = path.strip()
        add(version.strip(), path if os.path.isdir(path) else os.path.dirname(path), "$NGINE_ENGINES")
    roots = []
    if os.name == "nt":
        if os.environ.get("LOCALAPPDATA"):
            roots.append(os.path.join(os.environ["LOCALAPPDATA"], "Programs", "Ngine"))
    else:
        h = os.environ.get("HOME") or os.path.expanduser("~")
        if sys.platform == "darwin":
            roots.append(os.path.join(h, "Library", "Application Support", "Ngine"))
        xdg = os.environ.get("XDG_DATA_HOME") or os.path.join(h, ".local", "share")
        roots.append(os.path.join(xdg, "ngine"))
    for root in roots:
        try:
            names = os.listdir(os.path.join(root, "Engines"))
        except OSError:
            continue
        for name in names:
            add(name, os.path.join(root, "Engines", name), "default install root")
    found.sort(key=lambda t: version_key(t[0]), reverse=True)
    return [(exe, how) for _v, exe, how in found]


def resolve_editor(release=True):
    """Locate the Ngine editor executable. Returns `(path, how)` or `(None, tried)`.

    ONE resolution ladder, most explicit first:

      1. `$NGINE_EDITOR`            — an explicit path to the executable. Always wins.
      2. `ngine where --json`       — the engine's own resolver, via the CLI (`$NGINE_CLI` or PATH).
      3. an installed engine        — `$NGINE_HOME`, `$NGINE_ENGINES`, the default install root
                                       (`<root>/Engines/<version>/app-native`), newest first.
      4. `app-native` on `$PATH`.
      5. (developer copy only) a source-checkout build, found by a block the customer copy omits.

    The installed layout puts `app-native` at the VERSION ROOT (`Engines/<version>/`), not in a
    `bin/` — so `$NGINE_HOME/bin` and PATH alone, the rungs this ladder used to stop at, never
    matched a real install (AXR-3).
    """
    tried = []

    explicit = os.environ.get("NGINE_EDITOR")
    if explicit:
        if os.path.isfile(explicit):
            return explicit, "$NGINE_EDITOR"
        tried.append(f"$NGINE_EDITOR={explicit} (no such file)")

    where = ask_cli_where()
    if where and where.get("editor") and os.path.isfile(where["editor"]):
        return where["editor"], f"ngine where ({where.get('rung', '?')}, {where.get('version', '?')})"
    tried.append("`ngine where --json` (the CLI is not on PATH, or found no editor)")

    editors = installed_editors()
    if editors:
        return editors[0]
    tried.append("an installed engine ($NGINE_HOME, $NGINE_ENGINES, the default install root)")

    on_path = shutil.which("app-native")
    if on_path:
        return on_path, "$PATH"
    tried.append(f"{EDITOR_EXE} on $PATH (not found)")


    return None, tried


def port_open(host=None, port=None, timeout=1.0):
    host = HOST if host is None else host
    port = PORT if port is None else port
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


# One newline — the MCP framing is newline-delimited JSON, one request per line.
NL = chr(10)


def editor_ready(host=None, port=None):
    """Is the editor ANSWERING, not merely LISTENING?

    THE PORT IS NOT THE READINESS SIGNAL. The MCP server binds in the first ~30 ms of boot,
    long before the editor can do anything: measured on this machine, `[mcp] live MCP server on
    127.0.0.1:8877` is logged at 0.028 s and the first frame does not land until ~40 s later
    (GPU adapter at 14.6 s, then two more multi-second boot phases). A launcher that polls the
    TCP accept therefore prints "MCP up after ~1s" and hands back an editor with most of its
    startup still ahead of it — which is exactly what every session that reported "the agent
    launched it and then it froze for minutes" was actually seeing.

    `editor.context` is the right probe because it is the op every session runs first anyway
    and it needs the live editor state to answer at all.
    """
    host = HOST if host is None else host
    port = PORT if port is None else port
    try:
        with socket.create_connection((host, port), timeout=2.0) as sock:
            sock.settimeout(5.0)
            tok = session_token(port)
            init = {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {},
                    "clientInfo": {"name": "run-ngine-driver-probe", "version": "1"},
                },
            }
            if tok:
                init["params"]["token"] = tok
                init["params"]["clientInfo"]["token"] = tok
            call = {
                "jsonrpc": "2.0",
                "id": 2,
                "method": "tools/call",
                "params": {"name": "ngine.call", "arguments": {"op": "editor.context", "args": {}}},
            }
            sock.sendall((json.dumps(init) + NL + json.dumps(call) + NL).encode("utf-8"))
            buf = b""
            lines = 0
            while lines < 2:
                chunk = sock.recv(65536)
                if not chunk:
                    return False
                buf += chunk
                lines = buf.count(NL.encode())
            return b"editor.context" in buf or b"location" in buf or b"result" in buf
    except (OSError, ValueError):
        return False


def log_dir():
    """Where this driver writes per-port launch logs and the sticky-port record.

    A source checkout keeps them under `<root>/logs` (gitignored); an installed SDK has no
    checkout, so the per-user state dir is the only correct home.
    """
    root = repo_root(required=False)
    return os.path.join(root, "logs") if root else os.path.join(config_dir(), "logs")


def sticky_path():
    """The file `launch` records its chosen port in, so the NEXT invocation finds it.

    THE BUG THIS EXISTS FOR (measured 2026-09-06, cost two lanes a session each). `PORT` was read
    from `NGINE_MCP_PORT` at import time and `--auto-port` reassigned only the in-process global.
    A driver invocation is one process per subcommand, so the allocated port died with the
    `launch` process and every following `status` / `call` / `shot` silently fell back to 8731 —
    i.e. straight into whatever editor happened to be there. Two agents did exactly that: one had
    a whole measurement set read an EMPTY project belonging to somebody else, and nothing in the
    output said so, because connecting to the wrong editor looks identical to connecting to yours.
    """
    return os.path.join(log_dir(), "driver.port")


def write_sticky(port):
    """Record `port` as this checkout's current editor. Best-effort: a read-only tree is not
    a reason for `launch` to fail."""
    try:
        os.makedirs(log_dir(), exist_ok=True)
        with open(sticky_path(), "w", encoding="utf-8") as fh:
            json.dump({"port": int(port), "written": int(time.time())}, fh)
    except OSError:
        pass


def read_sticky():
    """The recorded port, or None. Stale records are ignored rather than trusted.

    "Stale" is decided by probing: if nothing is listening on the recorded port the editor is
    gone, and silently addressing a dead port is how a run reports "no editor" when the real
    answer is "your editor exited an hour ago". A LIVE listener on the recorded port is still not
    proof it is *yours* — see `--auto-port` in SKILL.md — which is why every subcommand prints
    which port it resolved and where the number came from.
    """
    try:
        with open(sticky_path(), encoding="utf-8") as fh:
            port = int(json.load(fh)["port"])
    except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError):
        return None
    return port if port_open(port=port) else None


def resolve_port():
    """Settle PORT/PORT_SOURCE for this invocation. Called once, at the top of `main()`.

    Precedence, highest first:
      1. `NGINE_MCP_PORT` — explicit, verbatim, and the ONLY thing that isolates two agents
         working in one checkout (they share the sticky file below).
      2. the sticky record from the last `launch` in this checkout, if something is listening.
      3. the running-editor registry: the editor whose project contains the current directory, or
         the only editor running (AXR-7).
      4. 8731.
    """
    global PORT, PORT_SOURCE
    if os.environ.get("NGINE_MCP_PORT"):
        PORT, PORT_SOURCE = int(os.environ["NGINE_MCP_PORT"]), "NGINE_MCP_PORT"
        return
    sticky = read_sticky()
    if sticky is not None:
        PORT, PORT_SOURCE = sticky, "sticky (" + sticky_path() + ")"
        return
    reg = registry_port()
    if reg is not None:
        PORT, PORT_SOURCE = reg, "editor registry (" + os.path.join(config_dir(), "instances") + ")"
        return
    PORT, PORT_SOURCE = DEFAULT_PORT, "default"


def _components(path):
    """Path components for comparison: separators unified, a Windows verbatim prefix dropped and, on
    Windows (case-insensitive filesystem), lowercased. Mirrors `install_layout::instances::components`."""
    p = path.replace("\\", "/")
    if p.startswith("//?/"):
        p = p[4:]
    parts = [c for c in p.split("/") if c and c != "."]
    return [c.lower() for c in parts] if os.name == "nt" else parts


def path_within(child, parent):
    """Is `child` the same directory as `parent`, or inside it? By component, not by text prefix."""
    c, p = _components(child), _components(parent)
    return bool(p) and c[: len(p)] == p


def cwd_project(cwd):
    """The nearest ancestor of `cwd` holding a `project.ngine`, or None."""
    d = os.path.abspath(cwd)
    while True:
        if os.path.isfile(os.path.join(d, "project.ngine")):
            return d
        parent = os.path.dirname(d)
        if parent == d:
            return None
        d = parent


def select_instance(recs, cwd, cwd_proj):
    """`install_layout::instances::select`, mirrored: the instance whose open project contains `cwd`
    (deepest wins); else the ONE running editor — but only when attaching cannot land in someone
    else's scene (the editor has no project open, or `cwd` is in no project); else None."""
    best = None
    for r in recs:
        proj = r.get("project")
        if proj and path_within(cwd, proj):
            depth = len(_components(proj))
            if best is None or depth > best[0]:
                best = (depth, r)
    if best:
        return best[1]
    if len(recs) == 1 and (not recs[0].get("project") or cwd_proj is None):
        return recs[0]
    return None


def registry_port():
    """The port of the running editor this working directory belongs to (AXR-7), or None."""
    cwd = os.getcwd()
    chosen = select_instance(instance_records(), cwd, cwd_project(cwd))
    return chosen["port"] if chosen else None


def announce_port():
    """One line on STDERR naming the port and where the number came from.

    Deliberately not optional and deliberately not on stdout: the whole failure mode being
    repaired was SILENT — an op sent to the wrong editor prints a perfectly normal reply. A
    transcript that names the port on every call is what makes "you drove lane B's editor"
    visible at the moment it happens instead of an hour later.
    """
    print(f"driver: {HOST}:{PORT}  [{PORT_SOURCE}]", file=sys.stderr)


def cmd_port(_args):
    print(f"{PORT}")
    print(f"source: {PORT_SOURCE}", file=sys.stderr)


def cmd_ping(_args):
    ok = port_open()
    print(f"editor MCP {'UP' if ok else 'DOWN'} on {HOST}:{PORT}")
    sys.exit(0 if ok else 1)


def free_port(start=8731, tries=64):
    """The first port from `start` that nothing is listening on.

    A collision the caller has to prevent by hand is a collision that will happen. Before this,
    launching a second session meant remembering to set NGINE_MCP_PORT; forgetting it produced
    either "reusing it" (silently driving the OTHER agent's editor) or a bind failure. Probed by
    connect, not by bind, so we do not race a listener into existence and then hand the port over.
    """
    for p in range(start, start + tries):
        if not port_open(port=p):
            return p
    die(f"no free port in {start}..{start + tries} -- how many editors are running?")


def pin_port(reused):
    """Make this launch's port STICK for the rest of the session, and say so unmissably.

    Two mechanisms, because neither alone is enough:

    * the sticky record (`sticky_path`) is what makes the next `driver.py status` in this
      checkout address the editor that was just launched instead of silently reverting to 8731.
      It is what repairs the measured cross-talk;
    * the printed `export` line is what gives the caller ISOLATION, which the sticky record
      cannot: it lives in the checkout, so a second agent's `launch` moves it under the first
      agent's feet. `--auto-port` allocates a port; it does not reserve one. Two agents sharing
      a tree must each export `NGINE_MCP_PORT`, and SKILL.md says so in the same words.
    """
    write_sticky(PORT)
    verb = "reusing" if reused else "launched"
    print("")
    print(f"==> NGINE_MCP_PORT={PORT}   ({verb}; recorded in {sticky_path()})")
    print("    EXPORT IT if another agent shares this checkout -- the sticky record is per-tree,")
    print("    so the next `launch` here moves it. --auto-port allocates, it does not reserve.")


def cmd_launch(args):
    global PORT, PORT_SOURCE
    if args.port is not None:
        # The hard-isolation door: the caller named a port, so nothing else may move it.
        PORT, PORT_SOURCE = args.port, "--port"
    elif args.auto_port and PORT_SOURCE != "NGINE_MCP_PORT":
        # ALWAYS move off the default, even when nothing is listening on it right now.
        #
        # This used to be `elif args.auto_port and port_open():` -- allocate only if the current
        # port is ALREADY busy. So a lane that ran `launch --auto-port` at a moment when 8731
        # happened to be free was handed 8731: the shared default that every other agent in the
        # checkout also lands on, from the one flag whose entire job is isolation. Measured
        # 2026-09-08; the lane noticed, quit the editor and relaunched with `--port 8778`, which
        # is work the flag exists to remove. "Free right now" is not "mine" -- the next agent's
        # launch is a second later and the race is invisible on both sides.
        #
        # An explicit NGINE_MCP_PORT is still honoured verbatim: naming a port IS the isolation,
        # and silently moving off it would break the one contract this file promises.
        was, PORT = PORT, free_port(DEFAULT_PORT + 1)
        PORT_SOURCE = "--auto-port"
        print(f"--auto-port: allocated {PORT} (never the shared default {was})")
    if port_open():
        print(f"editor already listening on {HOST}:{PORT} -- reusing it")
        print("(a second editor would fight the first over this port; not launching)")
        print("(want your OWN editor? re-run with --auto-port, or set NGINE_MCP_PORT)")
        pin_port(reused=True)
        return
    exe, how = resolve_editor(release=args.release)
    if exe is None:
        tried = chr(10).join("  " + t for t in how)
        hint = "Install the engine, or point the driver at your editor:  NGINE_EDITOR=/path/to/" + EDITOR_EXE
        die("could not locate the Ngine editor. Tried:" + chr(10) + tried + chr(10) + hint)
    env = dict(os.environ, NGINE_MCP="1", NGINE_MCP_PORT=str(PORT))
    if getattr(args, "headless", False):
        env["NGINE_HEADLESS"] = "1"
    # PORT-KEYED, and opened for APPEND rather than truncate. One shared `ngine_editor.log` opened
    # "wb" meant the second editor to launch erased the first's diagnostic trail — exactly when it
    # was most needed, since the reason to run two editors is usually that something is wrong.
    #
    # Under `logs/`, which is gitignored. This writer was the source of roughly seventy of the
    # eighty-five log files that had accumulated in the repo root; moving the files without moving
    # the writer just means the root refills, which is what happened. The editor's own cwd is
    # unchanged — only this redirect target moves — so nothing that reads the process's working
    # directory is affected. In particular the editor's log buffer writes `3dtools.log` and is
    # DELIBERATELY not moved with it: `resolve_log_dir()` selects the cwd only when a `3dtools.log`
    # is already there, so relocating that file silently redirects the engine's own log to the
    # per-user state dir and breaks `./run.sh`, `tail -f 3dtools.log`, and a cwd probe in
    # scripts/audio_blueprint_mcp_test.py. That writer and that file move together or not at all.
    # A source checkout keeps its logs in `<root>/logs`; an installed SDK has no checkout, so the
    # per-user state dir is the only correct home. Same file NAME either way, so every
    # troubleshooting instruction reads identically for a developer and a customer.
    root = repo_root(required=False)
    logs = log_dir()
    os.makedirs(logs, exist_ok=True)
    log = os.path.join(logs, f"ngine_editor.{PORT}.log")
    print(f"launching {exe}  [{how}]" + chr(10) + f"  port -> {PORT}" + chr(10) + f"  log -> {log}")
    with open(log, "ab") as fh:
        subprocess.Popen(
            [exe], env=env, stdout=fh, stderr=subprocess.STDOUT, cwd=root or os.path.dirname(exe)
        )
    # Wait for the editor to ANSWER, not merely to LISTEN — see `editor_ready`. The port opens
    # in the first ~30 ms and the editor is not usable for tens of seconds after that, so the old
    # `port_open` poll returned a handle to something still booting.
    listening_at = None
    for i in range(args.wait):
        time.sleep(1)
        if listening_at is None and port_open():
            listening_at = i + 1
            print(f"port {PORT} listening after ~{listening_at}s -- waiting for the editor to answer")
        if listening_at is not None and editor_ready():
            print(f"editor READY after ~{i + 1}s on {HOST}:{PORT} (port opened at ~{listening_at}s)")
            if (i + 1) - listening_at > 5:
                print(
                    f"  ({(i + 1) - listening_at}s of that was boot AFTER the socket opened -- "
                    f"read {log} for the phase breakdown)"
                )
            pin_port(reused=False)
            print(f"Next:  {SELF_CMD} status")
            return
    die(
        f"editor did not open {HOST}:{PORT} within {args.wait}s -- check {log}",
        code=2,
    )


def cmd_status(_args):
    ed = Editor()
    print(ed.text(ed.tool("ngine.call", {"op": "editor.context", "args": {}})))


def cmd_manifest(_args):
    """`editor.skills_manifest` — is the skill text I carry the text this engine ships? (AXR-45)"""
    ed = Editor()
    print(ed.text(ed.tool("ngine.call", {"op": "editor.skills_manifest", "args": {}})))


def cmd_call(args):
    try:
        op_args = json.loads(args.args) if args.args else {}
    except json.JSONDecodeError as e:
        die(f"args must be valid JSON: {e}")
    ed = Editor()
    resp = ed.tool("ngine.call", {"op": args.op, "args": op_args})
    out = ed.text(resp)
    print(out)
    if call_failed(resp, out):
        sys.exit(1)


def cmd_catalog(args):
    ed = Editor()
    a = {"domain": args.domain} if args.domain else {}
    print(ed.text(ed.tool("ngine.catalog", a)))


def cmd_describe(args):
    ed = Editor()
    print(ed.text(ed.tool("ngine.describe", {"op": args.op})))


def cmd_find(args):
    ed = Editor()
    print(ed.text(ed.tool("ngine.search", {"query": args.query})))


def cmd_recipe(args):
    ed = Editor()
    a = {"name": args.name} if args.name else {}
    if args.name and args.part:
        a["part"] = args.part
    print(ed.text(ed.tool("ngine.recipes", a)))


def cmd_measure(args):
    """Pin (or release) every source of drift that makes two captures incomparable.

    Four separate ops had to be remembered in the right order before any A/B: lock the camera,
    pin the capture size, strip the overlays, freeze the clock. In practice two of them get
    forgotten, and the resulting mismatch does not announce itself as operator error — it looks
    exactly like the rendering change you were trying to measure. A whole session's water
    investigation was derailed by precisely that. One command, one habit.

    The viewport camera is SHARED state: a human at the mouse and every other connected client
    move the same one, so this is as much about the human next to you as about your own calls.
    """
    ed = Editor()
    on = not args.off
    steps = [
        ("camera.lock", {"on": on}),
        ("ui.overlays", {"preset": "clean" if on else "default"}),
        # `day_length_sec: 0` pins the sun; without it the clock drifts between plates and every
        # lighting comparison is void.
        ("env.set_time", {"hours": 13, "day_length_sec": 0} if on else {"day_length_sec": 120}),
        # EXPOSURE. The fifth source of drift, and the one that cost the most: auto-exposure
        # RENORMALISES the frame after every change, so removing a bright term makes the image
        # brighter and a dimmer-in-scatter sweep reads as a near-no-op. Every magnitude
        # comparison in the underwater investigation was confounded by this before it was pinned
        # here. Manual EV means two plates are on the same scale; without it they are not
        # comparable at all, however careful the rest of the setup was.
        #
        # EV100 12 is a viewing exposure, not a measurement one — bright enough to JUDGE a look.
        # (EV100 13 is the measurement setting; it renders near-black and is useless for looking.)
        ("render.exposure", {"ev100": args.ev100} if on else {"auto": True}),
    ]
    for op, a in steps:
        print(f"{op}: ", end="")
        print(ed.text(ed.tool("ngine.call", {"op": op, "args": a})).splitlines()[0][:120])
    if on:
        # Pin the offscreen target size through one throwaway capture; the pin STICKS for later
        # size-less captures, which is what makes a whole series comparable.
        tmp = os.path.join(tempfile.gettempdir(), "ngine_measure_pin.png")
        ed.tool(
            "ngine.call",
            {
                "op": "scene.screenshot",
                "args": {
                    "width": args.width,
                    "height": args.height,
                    "path": tmp.replace("\\", "/"),
                },
            },
        )
        print(f"capture size PINNED at {args.width}x{args.height}")
        print(f"exposure PINNED at EV100 {args.ev100} (manual)")
        print("MEASURE MODE ON -- camera locked, overlays clean, clock frozen, size + exposure pinned.")
        print("Release with:  driver.py measure --off")
    else:
        print("measure mode OFF -- interactive navigation restored.")


def cmd_shot(args):
    out = os.path.abspath(args.out)
    os.makedirs(os.path.dirname(out) or ".", exist_ok=True)
    ed = Editor()
    op = "ui.screenshot" if args.ui else "scene.screenshot"
    # PIN THE CAPTURE SIZE BY DEFAULT.
    #
    # Without width/height the capture is whatever size the Viewport tab happens to be that frame,
    # and a human opening a panel or dragging a dock splitter silently changes BOTH the pixel size
    # and the camera aspect. Two such plates are not comparable, and — worse — pixel/region
    # coordinates taken from one do not address the same subject in the other.
    #
    # That is not hypothetical. One session measured a region at 652x1012, the viewport became
    # 1058x508 between calls, and the resulting mismatch was misdiagnosed as a RENDERING BUG in the
    # water for several rounds of investigation. `scene.screenshot`'s own description warns about
    # this; the warning did not help, because remembering it is the failure mode. So the default
    # pins it and `--no-pin` opts out, rather than the other way around.
    #
    # ...but only `scene.screenshot` HAS a size to pin. `ui.screenshot` captures the live OS
    # window, so there is no offscreen target: it takes `width` alone (aspect from the window),
    # rejects `height` outright, and rejects a `width` above the current window size rather than
    # upscaling. It also refuses `width` and `max_dim` together. Sending the viewport pin at it —
    # which this did — made `shot --ui` fail 100% of the time ("unknown arg key 'height'"), so the
    # two ops get the two arg shapes they actually accept.
    shot_args = {"path": out.replace("\\", "/")}
    if args.ui:
        # Window capture: pin only when the caller named an explicit --width (and then `width`
        # must travel alone). Otherwise cap the longest side and take the window as it is.
        if args.width is not None and not args.no_pin:
            shot_args["width"] = args.width
        else:
            shot_args["max_dim"] = args.max
    else:
        shot_args["max_dim"] = args.max
        if not args.no_pin:
            shot_args["width"] = args.width if args.width is not None else PIN_W
            shot_args["height"] = args.height if args.height is not None else PIN_H
    # Forward slashes: the engine parses this path itself and backslashes in JSON
    # are escape characters.
    resp = ed.tool("ngine.call", {"op": op, "args": shot_args})
    print(ed.text(resp))
    if os.path.exists(out):
        print(f"\nwrote {out} ({os.path.getsize(out):,} bytes) -- Read that path to view it")
    else:
        die("the op replied but no PNG appeared on disk", code=1)


def cmd_batch(args):
    ed = Editor()
    failed = 0
    with open(args.file, encoding="utf-8") as fh:
        for n, line in enumerate(fh, 1):
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            spec = json.loads(line)
            op = spec["op"]
            resp = ed.tool("ngine.call", {"op": op, "args": spec.get("args", {})})
            out = ed.text(resp)
            print(f"=== [{n}] {op}\n{out}\n")
            if call_failed(resp, out):
                failed += 1
    if failed:
        die(f"{failed} call(s) failed", code=1)


def main():
    p = argparse.ArgumentParser(
        description="Drive the running Ngine editor over MCP.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    sub = p.add_subparsers(dest="cmd", required=True)

    q = sub.add_parser("launch", help="start the editor with MCP on")
    q.add_argument("--release", action="store_true")
    q.add_argument(
        "--headless",
        action="store_true",
        help="run the editor with NO window (NGINE_HEADLESS=1): real captures on a GPU box with no "
        "display server. Viewport captures work; ui.screenshot (the composited window) does not",
    )
    q.add_argument("--wait", type=int, default=90, help="seconds to wait for the port")
    q.add_argument(
        "--auto-port",
        action="store_true",
        help="if the port is busy, take the next free one instead of reusing another agent's "
        "editor. Allocates a port; does NOT reserve one -- export NGINE_MCP_PORT for isolation",
    )
    q.add_argument(
        "--port",
        type=int,
        default=None,
        help="launch on exactly this port (hard isolation; beats --auto-port and the sticky record)",
    )
    q.set_defaults(fn=cmd_launch)

    sub.add_parser(
        "port", help="the port this driver would use, and where the number came from"
    ).set_defaults(fn=cmd_port)
    sub.add_parser("ping", help="is an editor listening?").set_defaults(fn=cmd_ping)
    sub.add_parser(
        "selftest", help="check the driver's config-dir rule against the engine's (no editor needed)"
    ).set_defaults(fn=lambda _a: self_test_config_dir())
    sub.add_parser("status", help="editor.context -- run this FIRST").set_defaults(fn=cmd_status)
    sub.add_parser(
        "manifest", help="editor.skills_manifest -- digests of the recipes/guides this engine ships"
    ).set_defaults(fn=cmd_manifest)

    q = sub.add_parser("call", help="run one op")
    q.add_argument("op")
    q.add_argument("args", nargs="?", help="JSON object, e.g. '{\"name\":\"Foo\"}'")
    q.set_defaults(fn=cmd_call)

    q = sub.add_parser("catalog", help="list domains or a domain's ops")
    q.add_argument("domain", nargs="?")
    q.set_defaults(fn=cmd_catalog)

    q = sub.add_parser("describe", help="one op's arg schema")
    q.add_argument("op")
    q.set_defaults(fn=cmd_describe)

    q = sub.add_parser("find", help="search ops and graph nodes")
    q.add_argument("query")
    q.set_defaults(fn=cmd_find)

    q = sub.add_parser("recipe", help="the engine's own agent skills")
    q.add_argument("name", nargs="?")
    q.add_argument("--part", help="a long skill is served core-first: one section id, or 'all'")
    q.set_defaults(fn=cmd_recipe)

    q = sub.add_parser("shot", help="screenshot to a file (capture size PINNED by default)")
    q.add_argument("out")
    q.add_argument("--ui", action="store_true", help="full editor window, not just the viewport")
    q.add_argument("--max", type=int, default=1600, help="longest side in px")
    # Default None so cmd_shot can tell "caller named a width" from "took the default": the
    # viewport pin below applies to scene.screenshot, while --ui pins only when asked (the
    # window is the capture source there, and a width above it is an error, not an upscale).
    q.add_argument(
        "--width",
        type=int,
        default=None,
        help=f"capture width (viewport pin, default {PIN_W}; with --ui, exact output width, "
        "max = the live window width)",
    )
    q.add_argument(
        "--height", type=int, default=None, help=f"pinned viewport height (default {PIN_H}; ignored with --ui)"
    )
    q.add_argument(
        "--no-pin",
        action="store_true",
        help="capture at whatever size the Viewport tab is (NOT reproducible; see cmd_shot)",
    )
    q.set_defaults(fn=cmd_shot)

    q = sub.add_parser(
        "measure",
        help="pin EVERYTHING for a comparable capture series: camera lock + capture size + clean "
        "overlays + frozen clock. Use before any A/B; `measure --off` releases it.",
    )
    q.add_argument("--off", action="store_true", help="release the locks")
    q.add_argument("--width", type=int, default=1280)
    q.add_argument("--height", type=int, default=720)
    # `cmd_measure` has always read this; the parser never defined it, so EVERY `measure` run
    # died with AttributeError before touching the editor. 12 is the value cmd_measure's own
    # comment documents: a VIEWING exposure (13 is the measurement one and renders near-black).
    q.add_argument(
        "--ev100",
        type=float,
        default=12,
        help="manual EV100 to pin (default 12 — a viewing exposure; 13 is the measurement one)",
    )
    q.set_defaults(fn=cmd_measure)

    q = sub.add_parser("batch", help="run many ops from a .jsonl file")
    q.add_argument("file")
    q.set_defaults(fn=cmd_batch)

    args = p.parse_args()
    # BEFORE dispatch: every subcommand shares one resolution, and every subcommand says which
    # port it settled on. `launch` may still move it (--port / --auto-port) and re-announces.
    resolve_port()
    announce_port()
    args.fn(args)


if __name__ == "__main__":
    main()
