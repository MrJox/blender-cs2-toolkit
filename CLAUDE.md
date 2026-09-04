# Project instructions for Claude Code sessions in this repository

Read this before doing any work here. It applies regardless of which session or model is running.

## 1. The plan files are the source of truth — read the relevant one first, every session

There is one plan file per workflow, all at the repo root next to this file:

- `PLAN_buildings.md` — the building-authoring workflow (Blender → `.CS2` → BOB →
  `.rigid_model_v2`/`.cs2.parsed`). Locked architecture decision, every bug found and fixed with
  the evidence behind each fix, what's confirmed working via real BOB compilation vs. still
  unconfirmed, and the current scope boundary for buildings.
- `PLAN_units.md` — the unit production workflow (soldiers, unit parts, skeletons, skeletal
  animation, VMD). Newer and less mature than the buildings plan; treat anything in it marked
  unconfirmed as genuinely open, not settled.
- `PLAN_ships.md` — the ship workflow (hull damage models, sails, cloth/rope simulation, buoyancy
  and `logic.xml`). Research only so far — no ship code exists yet, and every phase in it is a
  proposal awaiting sign-off, not a decision already taken.
- `PLAN_artillery.md` — the artillery & siege-engine workflow (onagers, ballistae, chariots:
  a weighted `.CS2` plus its skeleton as DUMMY nodes, a rigid destroyed model, and a building-style
  destruction animation — three BOB builds per machine). Research only so far; the authoring corpus
  is 5 modder-made `.CS2` files whose known defects are catalogued in its §1.9.
- `PLAN_vehicles.md` — the battlefield/siege vehicle workflow (battering rams, siege towers, siege
  ladders). Research only so far, and written entirely from compiled output plus BOB disassembly
  because **no authored vehicle `.CS2` exists anywhere**. Its central finding is that a vehicle is
  an ordinary building with a `[SiegeVehicle]` rule and eleven extra `class_rigidINFO` kinds, so
  read `PLAN_buildings.md` alongside it.
- `PLAN_vegetation.md` — the vegetation workflow (trees, shrubs, stones: `RS_TREE_V5`/`RS_LEAF_V5`,
  the generated billboard LOD, and the version-0 `_tech.cs2.parsed` fire-hull sidecar). Research
  only so far — the compiled formats are validated against 315 real game files, but no vegetation
  `.CS2` exists anywhere to check the authoring side against, so everything about export is
  explicitly unconfirmed and gated on a first BOB run.

Read whichever one governs the area you're touching (all of them, if the session spans several
workflows) fully before touching code. If a plan file is ever missing or looks stale, say so and
ask before proceeding — don't silently re-derive decisions from scratch or guess.

These files live in the repo (not an external per-session plan-mode file) specifically so they're
portable across sessions/machines and don't depend on any one session's local state. Keep it that
way — don't let a future edit move any of them back out of the repo, and don't collapse them into
a single file (they were deliberately split one-per-workflow so each stays scannable as the
project grows).

Update the relevant file when you find something genuinely new (a bug, a confirmed/refuted
hypothesis, a scope change) — but updating a plan is not a substitute for asking the user before
changing scope (see §3). If a new workflow is started in the future (ship, tree, etc.), give it its
own `PLAN_<workflow>.md` following this same pattern rather than growing an existing file to cover
it.

## 2. Code style — this has been violated before, do not repeat it

- **Minimize comments.** Default to none. Only comment a genuinely non-obvious *why* (a byte-layout
  quirk copied from a real sample file, a workaround for a specific BOB crash). Never comment what
  the code already says. Never write multi-line comment blocks, changelog-style comments inside
  source files, or comments narrating what you just did.
- No docstrings. Self-explanatory names + type hints carry that information instead.
- If you catch yourself writing a paragraph of comment explaining a decision, that content belongs
  in the plan file or in your response to the user — not in the source file.

## 3. Scope discipline — implement what was asked, not what seems logically adjacent

This project was explicitly built feature-by-feature with user sign-off at each step (low-effort
items implemented and confirmed before medium-effort items were even scoped). Do not:
- Implement items from `PLAN_buildings.md`'s §14 (or `PLAN_units.md`'s equivalent) non-goals list
  (or invent new features) unless the user asked for that specific item in this session.
- Refactor or "improve" unrelated working code while implementing something else.
- Treat "keep going" as an invitation to expand scope beyond the specific thing being worked on —
  ask if unsure what "keep going" should cover next.

## 4. Validation discipline — every change must be re-verified the same way prior ones were

- After any change to `binary/`, `naming/`, or `scene_model/cs2_builder.py`, re-run
  `total_war_buildings/scripts/validate_roundtrip.py` — it must stay byte-exact against all four
  real samples in `Input/examples/raw_data/`.
- After any change affecting the Blender-facing layers, sync the changed files to the installed
  addon copy at
  `%APPDATA%\Blender Foundation\Blender\5.2\scripts\addons\total_war_buildings\` and re-run the
  relevant `total_war_buildings/scripts/blender_*_test.py` script via
  `blender.exe --background --python <script>`. Editing only the repo copy without syncing means
  the installed addon silently keeps running old code.
- Crashes must be diagnosed with real evidence (Windows Event Log for BOB's fault module/offset,
  bisecting against a known-good real file) — never guessed-and-checked blind. See
  `PLAN_buildings.md` for the bisection methodology that found every real bug so far.
- New raw position/vector data (new geometry, curve points, line endpoints) must go through
  `extraction._to_engine_space()` (Z-up → Y-up). Forgetting this is a real bug that has already
  happened once and was silently invisible for symmetric test geometry.
- **The one exception: vectors written into a node's `user_defined_properties` text.** That block is
  3ds Max's own UDP buffer, so BOB applies the axis swap to it itself — converting first makes it
  swap twice. `naming._to_authoring_space` exists to undo the conversion at that boundary. This
  applied `_to_engine_space` wrongly for EFLines/DockingLines and broke them in BOB; see
  `PLAN_buildings.md`'s status update for the ground truth that settles it.

## 5. When something doesn't match a real sample, that's not optional to skip

If a validation error, a crash, or a discrepancy against a real ground-truth file comes up, root
cause it before moving on — don't work around it with an unverified guess presented as fact. Flag
genuinely unconfirmed hypotheses as unconfirmed (the handover doc's "not yet confirmed" sections are
the model to follow), rather than stating them as settled.
