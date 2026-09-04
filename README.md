# Blender CS2 Toolkit

A Blender add-on for authoring **Total War** battlefield assets — buildings, units, skeletons, and
skeletal animation, with ships, artillery, siege vehicles, and vegetation in progress — as `.CS2`
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
| Vegetation | Research only; compiled formats validated against real game files, but authoring/export is unconfirmed pending a first BOB run. See `PLAN_vegetation.md`. |

The `PLAN_*.md` files referenced above are working documents kept alongside the addon in the
project's development directory rather than in this repository (see [Repository scope](#repository-scope)).

## Requirements

- Blender 4.0+
- A Total War title's Assembly Kit installed, with BOB (the game's own asset compiler, which this
  add-on hands off to; it is not distributed here) — validated against Total War: Attila

## Installation

1. Download `total_war_buildings` from the latest [release](../../releases) (or clone this repo).
2. Copy the `total_war_buildings/` folder into Blender's addons directory, e.g.
   `%APPDATA%\Blender Foundation\Blender\<version>\scripts\addons\total_war_buildings\`.
3. In Blender, enable **Edit > Preferences > Add-ons > Blender CS2 All-in-One Kit**.
4. The add-on's panel appears under **View3D > Sidebar > Total War**.

## Repository layout

```
total_war_buildings/   the add-on itself (this is what gets installed into Blender)
file_format_specs/     original reverse-engineered write-ups of the binary formats involved
                        (.CS2, .rigid_model_v2, .cs2.parsed, .anim, .bone_inv_trans_mats)
CLAUDE.md, AGENTS.md   instructions for AI coding sessions working in this codebase
```

`total_war_buildings/docs/user_guide.html` is the artist-facing handbook; the published, browsable
copy is deployed to [GitHub Pages](../../deployments/github-pages).

## Repository scope

This repository tracks the add-on's source only. The broader development directory it's developed
in also contains large reverse-engineering research materials (game disassembly, extracted game
headers, and real game/mod asset samples used as test fixtures) that are not this project's to
redistribute, plus scratch files and per-session planning docs — none of that is part of this repo.

## Contributing

`main` is protected — changes land via pull request. Tagging a release (`vX.Y.Z`) on `main`
triggers CI to package `total_war_buildings/` and publish it as a GitHub Release.

## License

[GPL-3.0](LICENSE).
