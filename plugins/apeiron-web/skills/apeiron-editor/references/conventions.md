# Conventions that bite, and how to take a clean plate

`recipe ngine/04-conventions` is the full table, fenced against the code and always in sync with
the build you are running. These are the entries that cost the most time.

## Arguments and identity

- **Unknown argument keys are hard errors.** `describe <op>` is the per-op truth. Common synonyms
  are cross-aliased (`at` / `position`), but do not guess.
- **Entity ids like `e5v0` are ephemeral.** They renumber across save/load and churn on undo.
  Address anything durable **by name**, and re-query ids after any reload.

## Units and space

- **Colours are LINEAR RGB**, not sRGB. An sRGB 0.5 mid-grey is ~0.22 linear.
- **Ground coordinates are XZ**, Y is up. Angles are degrees unless a schema says otherwise.
- **Primitive sizes are not uniform.** `plane` is 2×2 m; the others are 1×1×1. `place.catalog`
  prints each kind's real bounds — read it instead of placing one to measure.

## Clean captures

Before any screenshot meant for judging a scene:

```bash
python scripts/driver.py call ui.overlays '{"preset":"clean"}'
python scripts/driver.py call scene.select '{"mode":"replace","entities":[]}'
python scripts/driver.py call env.set_time '{"hours":13,"day_length_sec":0}'
```

`day_length_sec:0` pins the sun. Without it the sun drifts between captures and any A/B
comparison is void. Restore chrome with `ui.overlays '{"preset":"default"}'`.

### A plate that must be reproducible: pass the viewpoint

`camera.set` writes the **shared** viewport camera, and anyone else looking at the editor — another
agent, or a human at the mouse — shares it. A plate framed that way can be stolen between the
`camera.set` and the capture, and nothing in either reply says so: you get a normal-looking
screenshot of the wrong thing.

Pass the viewpoint to the capture instead. It borrows the camera for one frame and puts it back, so
there is no window to lose and nobody else's view moves:

```bash
python scripts/driver.py call scene.screenshot '{
  "path":"/tmp/plate.png",
  "viewpoint":{"position":[-0.6,1.2,0.9],"target":[-0.2,1.0,0.4],"fov":40},
  "width":1100,"height":900,"overlays":"clean"}'
```

The fields are `position` / `target` / `fov`. Pinning `width`+`height` makes the size hold
regardless of the dock layout, which is what makes two plates comparable at all.

The same op takes `isolate` + `background`, and that pair is the **control plate** for any "is the
asset broken or is the renderer broken?" question: render the subject alone, at its bind/rest state,
on a flat backdrop. A defect that survives isolation is in the geometry; one that vanishes was
lighting, shadowing, or a neighbouring object.

The two capture ops take different size arguments because they capture different things.
`shot` renders an **offscreen** target and pins width+height, so two plates are directly
comparable. `shot --ui` captures the live **OS window**: it takes `width` alone (aspect comes from
the window) and will not upscale past the current window size. Want a bigger `--ui` source?
Enlarge the window.
