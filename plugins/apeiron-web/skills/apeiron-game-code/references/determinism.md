# Determinism is a hard requirement

The simulation is hashed and replayed. Multiplayer, replays, the golden tests and crash
reproduction all depend on two runs over the same inputs producing the same bytes. A system that
breaks this does not fail loudly — it desyncs a playtest days later, on someone else's machine.

## The four rules

| Do | Never |
|---|---|
| key on `Time::dt` / `Time::tick` | read the wall clock |
| use the engine's seeded RNG | use a random source of your own |
| iterate a sorted or query-ordered collection | iterate a `HashMap`/`HashSet` |
| do position maths in `f64` (positions are `DVec3` for large worlds) | accumulate in `f32` |

Each one has the same shape: something that varies between two runs of identical inputs. The wall
clock varies with when you ran it, an unseeded RNG with the process, hash iteration with the
allocator and the insertion history, and `f32` accumulation with the order the additions happened
to occur in.

## Why `f64` for positions

Positions are `DVec3` because Apeiron targets large worlds. Accumulating a position in `f32` loses
precision as you move away from the origin, and — the part that breaks determinism rather than
just looking bad — it loses a *different* amount depending on the order the contributions were
summed in. Do the maths in `f64` and convert once at the end if you need `f32`.

## The test you already have

The scaffold ships a determinism test. Keep it green — it is the cheapest possible guard against a
desync you would otherwise find in a playtest, and it runs with your own crate's suite:

```bash
cargo test -p my-game
```
