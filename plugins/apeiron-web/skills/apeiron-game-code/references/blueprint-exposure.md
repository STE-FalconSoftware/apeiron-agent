# Exposing Rust to Blueprint, and scaffolding code from the editor

## A free function becomes a node

This is the designer-facing half of the code tier: you write the capability once in Rust, and
Blueprint assembles the game out of it.

```rust
/// Pins are derived from the signature; `#[param]` fields become node parameters.
#[ngine::node(blueprint, display = "Bob Offset", category = "My Game")]
fn bob_offset(time: BpTime, amplitude: Option<f32>, #[param] phase: f32) -> f32 {
    /* ... */
}

// One list per crate. A node missing from it never reaches the palette.
ngine::export_nodes! {
    blueprint: [bob_offset],
}
```

Your node then appears in the editor's Blueprint palette under its category, is loadable from
saved graphs, and is visible to agents through the same registry — one registration, every door.

`#[ngine::node(world, ...)]` is the same mechanism for procedural-geometry (Loom/world-graph)
nodes.

The `export_nodes!` list is the part people forget. A `#[ngine::node]` function that is not in it
compiles cleanly and never appears anywhere — there is no warning, because an unexported node is a
legitimate thing to have mid-refactor.

## Scaffolding from inside a running editor

You do not have to leave the editor to add code. These write into your game or plugin crate and
declare it in `lib.rs`, undoably:

| Op | Writes |
|---|---|
| `project.new_component {name, target}` | `<target>/src/<name>.rs` — a `#[derive(Reflect)]` struct + `Default` |
| `project.new_node {name, target}` | a `#[ngine::node(blueprint)]` fn (then add it to `export_nodes!`) |
| `project.new_script {name, target}` | a Rhai gameplay script — content, not code |

`target` is the crate directory, e.g. `Source/my-game`. Undo deletes an untouched file and moves an
edited one to `.ngine/scaffold-trash/` rather than destroying your work.
