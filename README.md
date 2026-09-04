# Blender CS2 Toolkit

A Blender add-on for authoring **Total War: Attila** battlefield assets — buildings, units, and
(in progress) ships, artillery, vehicles, and vegetation — as `.CS2` files, replacing the original
3ds Max pipeline (3ds Max → MaxScripts → `cas2_exporter.dle` → `.CS2` → BOB → game files) with an
artist-first Blender workflow that hands off to the same BOB compiler at the same point.

## Status

| Workflow | Maturity |
|---|---|
| Buildings | Locked architecture; most features confirmed working end-to-end via real BOB compilation. See `PLAN_buildings.md`. |
| Units | Newer, less mature; several areas still explicitly unconfirmed. See `PLAN_units.md`. |
| Ships | Research only — no code yet. See `PLAN_ships.md`. |
| Artillery & siege engines | Research only. See `PLAN_artillery.md`. |
| Vehicles | Research only; a vehicle turns out to be an ordinary building plus a `[SiegeVehicle]` rule. See `PLAN_vehicles.md`. |
| Vegetation | Research only; compiled formats validated against real game files, but authoring/export is unconfirmed pending a first BOB run. See `PLAN_vegetation.md`. |

The `PLAN_*.md` files referenced above are working documents kept alongside the addon in the
project's development directory rather than in this repository (see [Repository scope](#repository-scope)).

## Requirements

- Blender 4.0+
- Total War: Attila with the Assembly Kit installed (for BOB — the game's own asset compiler,
  which this add-on hands off to; it is not distributed here)

## Installation

1. Download `total_war_buildings` from the latest [release](../../releases) (or clone this repo).
2. Copy the `total_war_buildings/` folder into Blender's addons directory, e.g.
   `%APPDATA%\Blender Foundation\Blender\<version>\scripts\addons\total_war_buildings\`.
3. In Blender, enable **Edit > Preferences > Add-ons > Blender CS2 All-in-One Kit**.
4. The add-on's panel appears under **View3D > Sidebar > Total War**.

## Repository layout

```
total_war_buildings/   the add-on itself (this is what gets installed into Blender)
CLAUDE.md, AGENTS.md   instructions for AI coding sessions working in this codebase
```

`total_war_buildings/docs/user_guide.html` is the artist-facing handbook; the published, browsable
copy lives on this repo's [Wiki](../../wiki).

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
