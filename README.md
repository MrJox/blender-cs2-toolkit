# Blender CS2 Toolkit

A Blender add-on for authoring **Total War** battlefield assets — buildings, units, skeletons,
skeletal animation and vegetation, with ships, artillery and siege vehicles in progress — as `.CS2`
files, replacing the original 3ds Max pipeline (3ds Max → MaxScripts → `cas2_exporter.dle` → `.CS2`
→ BOB → game files) with an artist-first Blender workflow that hands off to the same BOB compiler at
the same point.

`.CS2` and BOB are Creative Assembly's own asset-authoring format and compiler, shared across
several Total War titles built on the same engine lineage (Attila, Rome II, Thrones of Britannia,
Pharaoh, Three Kingdoms, ...) rather than being unique to any one game. Development and all
BOB-confirmed testing so far have been done against **Total War: Attila**'s Assembly Kit; some
details are known to vary by title (e.g. `.bone_table` formatting differs between Attila/Rome
II/Thrones of Britannia and Pharaoh/Three Kingdoms), so treat other titles as untested rather than
assumed-compatible until someone verifies them.

## Status

| Workflow | Maturity |
|---|---|
| Buildings (structure, materials, collision, platforms, lines, destruction & gate animation) | Confirmed working end-to-end via real BOB compilation. See `PLAN_buildings.md`. |
| Units (weighted & rigid unit parts, `.variantmeshdefinition` import) | Confirmed working, BOB-confirmed. See `PLAN_units.md`. |
| Skeletons (import/export) | Confirmed working, BOB-confirmed. See `PLAN_units.md`. |
| Skeletal animation (`.anim` import/export, debris bundle import) | Confirmed working, BOB-confirmed. See `PLAN_units.md`. |
| Ships | Research only — no code yet. See `PLAN_ships.md`. |
| Artillery & siege engines | Research only. See `PLAN_artillery.md`. |
| Vehicles | Research only; a vehicle turns out to be an ordinary building plus a `[SiegeVehicle]` rule. See `PLAN_vehicles.md`. |
| Vegetation (trees, shrubs, stones - import & export) | Confirmed working, BOB-confirmed: an imported game tree re-exports, compiles, and matches the shipped model. Only authored LODs are imported - the burn hull, its fire emitters and the far-distance billboard are BOB's own output, rebuilt from the model on every build. BOB's tree-billboard step crashes on the Attila kit, so a built model has no billboard. See `PLAN_vegetation.md`. |

The `PLAN_*.md` files referenced above are working documents kept alongside the addon in the
project's development directory rather than in this repository (see [Repository scope](#repository-scope)).

## Requirements

- Blender 4.2+
- A Total War title's Assembly Kit installed, with BOB (the game's own asset compiler, which this
  add-on hands off to; it is not distributed here) — validated against Total War: Attila

## Installation

The add-on is a Blender extension served from its own repository, so Blender installs it and keeps
it up to date for you.

1. In Blender, open **Edit > Preferences > Get Extensions**, open the **Repositories** drop-down
   (top right), click **+ > Add Remote Repository**, and paste
   `https://mrjox.github.io/blender-cs2-toolkit/extensions/index.json`.
   Leave **Check for Updates on Startup** ticked.
2. Find **Blender CS2 All-in-One Kit** in the extension list and click **Install**.
3. The add-on's panel appears under **View3D > Sidebar > Total War**.

When a new release is published, Blender shows an **Update** button on the extension (and a badge on
the Preferences icon). One click installs it; no manual download or reinstall.

To install without the repository, download `total_war_cs2_addon-<version>.zip` from the latest
[release](../../releases) and use **Get Extensions > Install from Disk**. That copy will not update
itself.

If you installed an older release by copying the `total_war_cs2_addon/` folder into Blender's
`scripts/addons` directory, delete that folder first.

## Repository layout

```
total_war_cs2_addon/   the add-on itself (this is what gets installed into Blender)
file_format_specs/     original reverse-engineered write-ups of the binary formats involved
                        (.CS2, .rigid_model_v2, .cs2.parsed, .anim, .bone_inv_trans_mats)
CLAUDE.md, AGENTS.md   instructions for AI coding sessions working in this codebase
```

`total_war_cs2_addon/docs/user_guide.html` is the artist-facing handbook; the published, browsable
copy is deployed to [GitHub Pages](../../deployments/github-pages).

## Repository scope

This repository tracks the add-on's source only. The broader development directory it's developed
in also contains large reverse-engineering research materials (game disassembly, extracted game
headers, and real game/mod asset samples used as test fixtures) that are not this project's to
redistribute, plus scratch files and per-session planning docs — none of that is part of this repo.

## Contributing

`main` is protected — changes land via pull request. Tagging a release (`vX.Y.Z`) on `main`
triggers CI to package `total_war_cs2_addon/` and publish it as a GitHub Release.

## License

[GPL-3.0](LICENSE).
