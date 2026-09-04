import sys
import traceback
from pathlib import Path

import addon_utils
import bpy

REPO_ROOT = r"C:\Users\Khaiali\source\repos\blender_buildings_plugin"
ASSEMBLY_KIT_ROOT = r"D:\SteamLibrary\steamapps\common\Total War Attila\assembly_kit"
SKELETON_DIR = Path(ASSEMBLY_KIT_ROOT) / "raw_data" / "animations" / "skeletons"
COMPILED_DIR = Path(ASSEMBLY_KIT_ROOT) / "working_data" / "animations" / "skeletons"
SOURCE_CS2 = SKELETON_DIR / "rome_man_game.cs2"

# Exported beside CA's own rome_man_game rather than into a subfolder, because that is the only
# place BOB resolves the .bone_table from. Everything this writes is removed again in the finally
# block, whether the run passes or not.
TEST_NAME = "blender_skeleton_test"

if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

failures = []


def check(label: str, condition: bool) -> None:
    print(("  OK   " if condition else "  FAIL ") + label)
    if not condition:
        failures.append(label)


def main() -> None:
    if not SOURCE_CS2.exists():
        raise RuntimeError(f"Skeleton sample not found: {SOURCE_CS2}")

    module = addon_utils.enable("total_war_cs2_addon", default_set=True, persistent=False)
    if module is None:
        raise RuntimeError("addon_utils.enable returned failure")

    from binary.anim_reader import bone_local_transform, read_anim
    from bob.cli import compile_skeleton, is_bob_running, working_data_output_dir
    from export.skeleton_exporter import export_skeleton
    from importer import import_file

    if is_bob_running():
        raise RuntimeError("BOB is already open - close it before running this test.")

    collection, _warnings, _kind = import_file(str(SOURCE_CS2), bpy.context)
    collection.name = TEST_NAME

    exported = [SKELETON_DIR / f"{TEST_NAME}.CS2", SKELETON_DIR / f"{TEST_NAME}.bone_table"]
    anim_path = COMPILED_DIR / f"{TEST_NAME}.anim"
    inverse_path = anim_path.with_suffix(".bone_inv_trans_mats")
    reference_anim = COMPILED_DIR / "rome_man_game.anim"
    reference_inverse = COMPILED_DIR / "rome_man_game.bone_inv_trans_mats"
    # Snapshotted before anything is written, so the cleanup can put the Assembly Kit back exactly
    # as it found it instead of emptying a folder the artist's own builds live in.
    created_compiled_dir = not COMPILED_DIR.is_dir()
    pre_existing = {
        path for path in (anim_path, inverse_path, reference_anim, reference_inverse) if path.is_file()
    }
    try:
        print("=== export into the Assembly Kit ===")
        result = export_skeleton(collection, str(SKELETON_DIR), ASSEMBLY_KIT_ROOT)
        check("export succeeded", result.success)
        check("no bone-definition-lookup warning in the canonical folder",
              not any("bone definition" in warning for warning in result.warnings))
        check("both files landed in the skeletons folder", all(path.is_file() for path in exported))

        print("=== BOB compiles it ===")
        bob_result = compile_skeleton(ASSEMBLY_KIT_ROOT, result.cs2_path)
        print("  BOB said:", bob_result.message.replace("\n", " | "))
        check("BOB reported success", bob_result.success)

        check("the skeleton output folder is where BOB puts it",
              working_data_output_dir(ASSEMBLY_KIT_ROOT, result.cs2_path) == COMPILED_DIR)
        check("BOB produced a .anim", anim_path.is_file())
        check("BOB produced a .bone_inv_trans_mats", inverse_path.is_file())

        if anim_path.is_file():
            animation = read_anim(anim_path.read_bytes())
            check("the compiled .anim parses as version 5", animation.version == 5)
            check("it carries the 50 bone-table bones", len(animation.bones) == 50)
            check("it is named after the skeleton", animation.skeleton_name == TEST_NAME)
            # Bone 0 is the root and 1..5 are the floating weapon bones - the ordering PLAN_units.md
            # 1.3 derived from three unrelated directions, here straight out of BOB.
            expected = ["bn_hips"] + [f"bn_weapon_{index:02d}" for index in range(1, 6)]
            check("bone order matches the derived index space",
                  [bone.name for bone in animation.bones[:6]] == expected)

        print("=== it compiles to the same pose as CA's own file ===")
        # The reference compile of the untouched original. Comparing per bone through the remap
        # tables rather than byte for byte: the .anim indexes its frames by track, and a float32
        # round trip through Blender's head/tail/roll moves every value a little.
        compile_skeleton(ASSEMBLY_KIT_ROOT, SOURCE_CS2)
        reference = read_anim(reference_anim.read_bytes())
        ours = read_anim(anim_path.read_bytes())

        check("bone names match CA's compile", [b.name for b in reference.bones] == [b.name for b in ours.bones])
        check("parent ids match CA's compile",
              [b.parent_id for b in reference.bones] == [b.parent_id for b in ours.bones])
        check("channel remap tables match CA's compile",
              (reference.translation_mappings, reference.rotation_mappings)
              == (ours.translation_mappings, ours.rotation_mappings))

        worst_translation = 0.0
        worst_rotation = 0.0
        for index in range(len(reference.bones)):
            reference_t, reference_r = bone_local_transform(reference, index, 0)
            our_t, our_r = bone_local_transform(ours, index, 0)
            worst_translation = max(worst_translation, max(abs(a - b) for a, b in zip(reference_t, our_t)))
            worst_rotation = max(
                worst_rotation,
                min(
                    max(abs(a - b) for a, b in zip(reference_r, our_r)),
                    max(abs(a + b) for a, b in zip(reference_r, our_r)),
                ),
            )
        print(f"  worst per-bone translation {worst_translation:.3e}, rotation {worst_rotation:.3e}")
        # Anything structurally wrong shows up as whole degrees or centimetres here: writing the
        # building scene-root block instead of the skeleton's put six bones out by 90 degrees and 5cm.
        check("every bone's translation matches CA's compile", worst_translation < 1e-3)
        check("every bone's rotation matches CA's compile", worst_rotation < 1e-3)

        print("=== the compiled log is clean ===")
        log_path = Path(ASSEMBLY_KIT_ROOT) / "binaries" / "bob.log"
        log = log_path.read_text(errors="replace") if log_path.is_file() else ""
        check("BOB logged no error line", "Error :" not in log)
    finally:
        # Only what this run created comes back out. The previous version removed the whole
        # working_data/animations/skeletons folder, which took CA's own compiled rome_man_game.anim
        # and .bone_inv_trans_mats with it - the very files a weighted .rigid_model_v2 import looks
        # there for. Anything that was on disk before is left exactly as it was; the reference
        # compile overwrites rome_man_game's pair with byte-identical output of the same source.
        for path in exported:
            path.unlink(missing_ok=True)
        for path in (anim_path, inverse_path, reference_anim, reference_inverse):
            if path not in pre_existing:
                path.unlink(missing_ok=True)
        if created_compiled_dir and COMPILED_DIR.is_dir() and not any(COMPILED_DIR.iterdir()):
            COMPILED_DIR.rmdir()
            parent = COMPILED_DIR.parent
            if parent.is_dir() and not any(parent.iterdir()):
                parent.rmdir()
        print("cleaned up the Assembly Kit")

    print()
    if failures:
        print(f"FAILED {len(failures)} check(s):")
        for failure in failures:
            print("   ", failure)
        raise SystemExit(1)
    print("all checks passed")


try:
    main()
except Exception:
    traceback.print_exc()
    sys.exit(1)
