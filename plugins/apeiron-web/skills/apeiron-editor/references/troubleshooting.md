# Troubleshooting, and sharing an editor

## Symptom → cause

| Symptom | Cause / fix |
|---|---|
| `no editor listening on 127.0.0.1:8731` | not running, or launched without the agent door. → `driver.py launch` |
| Ops "succeed" but nothing renders | the **launcher** is open, not a project. `status` says so. → `project.open` / `project.start_empty` |
| `unknown arg key 'X' — accepted keys: …` | strict keys. → `describe <op>` |
| A screenshot shows a scene you did not build | you are driving someone else's editor. `launch` REUSES whatever is on the port. `status` prints a `CONCURRENT DRIVERS` line. → `launch --auto-port` for your own |
| Screenshot is a stale or foreign framing | another client moved the shared viewport camera. Re-set the camera and re-shoot **in one connection** |
| Every query returns nothing, plausibly | **check the editor is alive.** A dead door returns empty-looking results that read exactly like "no such feature". Pair any negative with `ping` and one control query that must hit (`find "screenshot"`) |
| `the GPU DEVICE IS LOST` | real and terminal. Every capture from here is the same stale frame while other ops keep answering normally. → save, quit, `launch` again, reopen the project. Do not keep driving it |
| Editor vanished, no error | read the log path `launch` printed. An orderly shutdown ends with a pipeline-cache save line; anything else is a crash worth reporting |

## Concurrency

There is no single-driver lock. Every connection can mutate the same undo stack, and the viewport
camera is **shared global state**. `status` prints a `CONCURRENT DRIVERS` line when another client
is connected, and stays silent when you are alone. If you are sharing:

- batch `camera.set` + screenshot **in one connection**, or
- skip visuals and verify numerically (`scene.bounds`, `scene.raycast`).

Assume a human with the editor open is another driver.
