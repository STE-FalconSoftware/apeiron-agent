# Which recipe for which task

The editor carries its workflows compiled in, exactly in sync with the build you are driving. List
them with `ngine.recipes {}` (or `python scripts/driver.py recipe`) and read one with
`ngine.recipes {name:"<id>"}` (`python scripts/driver.py recipe <id>`). Read the matching one
BEFORE you author anything. This table is generated from the recipes' own frontmatter; the
recipe you load is the source of truth, and it wins over this page.

In the Claude Code plugin every authoring and gameplay recipe also appears as a `recipe-<name>`
skill, a pointer that tells you to load the real recipe.

## Session discipline (read these first)

| Recipe | Read it when |
|---|---|
| `ngine/00-orientation` | first session driving the Ngine editor over MCP; connected to ngine and unsure where to start |
| `ngine/01-run-headless` | running the editor headless in a container; launching ngine without a display or gpu |
| `ngine/02-discovery-budget` | starting a session and deciding what to read first; looking for which op does something |
| `ngine/03-verify-everything` | verifying a mutation actually landed; an op returned ok but the change is not visible |
| `ngine/04-conventions` | unsure what an op argument is called; an arg key was rejected as unknown |

## Authoring

| Recipe | Read it when |
|---|---|
| `authoring/character-rig` | importing a character, FPS arms, or any rigged mesh; putting a weapon, tool or prop in a character's hand |
| `authoring/cinematic-sequence` | asked for a video, a movie, a clip, an mp4, or 'render the animation'; shooting a cinematic, a cutscene, a trailer beat or a turntable |
| `authoring/lighting` | light a scene, or relight one that reads flat; a light you placed appears to do nothing |
| `authoring/lookdev` | the render is technically correct but looks flat, muddy or amateur; asked to make a scene look good, cinematic or hero-worthy |
| `authoring/loom-kitbash-architecture` | building architecture in the editor with no shipped generator for it; need an arch, tower, column, plinth, stair or battlement |
| `authoring/loom-subassets` | a world.script node has grown past the point where a human could tune it; the same part appears more than once in a model (a window, a wheel, a hull panel) |
| `authoring/material-graph` | author a PBR material as a node graph on an entity; the material renders flat near-white, or black, and nothing you wire changes it |
| `authoring/motion-generation` | asked to generate, invent or author an animation from a description; the clip library lacks a move (strafe, backpedal, turn, idle variant) and nobody is buying content |
| `authoring/pose-by-text` | posing a character or creature for a still, a key, or a shot; a hand must hold a prop, touch something, or reach a point |
| `authoring/post-process` | tuning bloom, exposure, tone mapping, vignette, sharpen or the colour grade; an effect toggle or a preset 'did not apply' |
| `authoring/procedural-cliffs` | making cliffs, rock faces or escarpments from a terrain; converting a terrain mask into geometry instead of a splat texture |
| `authoring/rig-verify-fix` | a bind is done and you need to know whether it is any good; the skin tears, stretches, collapses or passes through itself |
| `authoring/scene-recreation` | recreate a reference image or concept frame as a 3D scene; handed a photo or screenshot and asked to build it in the editor |
| `authoring/terrain-erosion` | making terrain look eroded or weathered; adding rivers, valleys, gullies or talus to a landscape |
| `authoring/terrain-slab-lookdev` | recreate a terrain reference image in the Loom graph; make a heightfield a solid block with visible cut sides |
| `authoring/terrain-worldgraph` | authoring terrain through the world graph; surface layers or masks not showing on terrain |
| `authoring/texture-graph` | author a procedural texture or material from a reference photograph; build a tiling surface — stone, brick, cobble, plaster, wood, metal — in the texture graph |

## Gameplay

| Recipe | Read it when |
|---|---|
| `gameplay/blueprints` | building or editing a blueprint graph over mcp; the blueprint is attached and the entity does nothing |
| `gameplay/multiplayer` | making a multiplayer game; testing a game with several players |
| `gameplay/play-step-verify` | play testing a game deterministically over mcp; stepping the simulation an exact number of ticks |
| `gameplay/rhai-scripting` | attaching a rhai script to an entity over mcp; the script compiles and nothing happens |
