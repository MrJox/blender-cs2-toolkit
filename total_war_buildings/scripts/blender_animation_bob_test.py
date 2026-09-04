import shutil
import sys
import traceback
from pathlib import Path

import addon_utils
import bpy

REPO_ROOT = r"C:\Users\Khaiali\source\repos\blender_buildings_plugin"
ASSEMBLY_KIT_ROOT = r"D:\SteamLibrary\steamapps\common\Total War Attila\assembly_kit"
SKELETON_CS2 = Path(ASSEMBLY_KIT_ROOT) / "raw_data" / "animations" / "skeletons" / "rome_man_game.cs2"
SOURCE_CLIP = (
    Path(ASSEMBLY_KIT_ROOT)
    / "raw_data"
    / "animations"
    / "ROME2"
    / "human"
    / "battle"
    / "sword_and_shield"
    / "locomotion"
    / "sws_run_443_cm.cs2"
)
# Its own folder under the tree BOB scans for animations, removed again in the finally block. The
# .bone_table BOB resolves AnimationType against stays where CA put it and is never touched.
EXPORT_DIR = Path(ASSEMBLY_KIT_ROOT) / "raw_data" / "animations" / "blender_animation_test"
COMPILED_DIR = Path(ASSEMBLY_KIT_ROOT) / "working_data" / "animations" / "blender_animation_test"

# Both files compile at the rate the clip was authored at, so the two are comparable frame by frame.
# CA sampled sword_and_shield at 60; changing this instead of re-timing the Action would stretch the
# clip, since one Blender frame is one clip frame by construction.
COMPILE_FPS = 60.0

# A compiled quaternion is 16-bit, so 1/32767 is the floor on any rotation comparison.
POSITION_TOLERANCE = 1e-3
ROTATION_TOLERANCE = 2e-3

if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

failures = []


def check(label: str, condition: bool) -> None:
    print(("  OK   " if condition else "  FAIL ") + label)
    if not condition:
        failures.append(label)


def quaternion_distance(a, b) -> float:
    same = max(abs(x - y) for x, y in zip(a, b))
    flipped = max(abs(x + y) for x, y in zip(a, b))
    return min(same, flipped)


def main() -> None:
    for path in (SKELETON_CS2, SOURCE_CLIP):
        if not path.exists():
            raise RuntimeError(f"Sample not found: {path}")

    module = addon_utils.enable("total_war_buildings", default_set=True, persistent=False)
    if module is None:
        raise RuntimeError("addon_utils.enable returned failure")

    from binary.anim_reader import bone_local_transform, read_anim
    from binary.cs2_reader import read_cs2
    from binary.cs2_writer import write_cs2
    from bob import rules
    from bob.cli import compile_animation, is_bob_running, working_data_output_dir
    from export.animation_exporter import export_animation
    from importer import import_file

    bpy.context.preferences.addons["total_war_buildings"].preferences.assembly_kit_root = ASSEMBLY_KIT_ROOT
    if is_bob_running():
        raise RuntimeError("BOB is already running - close it before running this test.")

    created_export_dir = not EXPORT_DIR.exists()
    created_compiled_dir = not COMPILED_DIR.exists()
    written: list[Path] = []
    try:
        EXPORT_DIR.mkdir(parents=True, exist_ok=True)

        print("\n== export ==")
        collection, _warnings, _kind = import_file(str(SKELETON_CS2), bpy.context)
        armature_object = next(obj for obj in collection.all_objects if obj.type == "ARMATURE")
        import_file(str(SOURCE_CLIP), bpy.context)
        action = armature_object.animation_data.action
        check("CA's clip is on the skeleton", action is not None)
        check("the clip kept the rate CA sampled it at", action.tw_frame_rate == COMPILE_FPS)

        result = export_animation(armature_object, action, str(EXPORT_DIR), ASSEMBLY_KIT_ROOT, bpy.context)
        for warning in result.warnings:
            print(f"       warning: {warning}")
        check("export succeeded", result.success)
        if not result.success:
            print(result.message)
            raise SystemExit(1)
        written.append(result.cs2_path)
        written.append(EXPORT_DIR / rules.RULES_FILENAME)
        check("a rules.bob was written beside the clip", (EXPORT_DIR / rules.RULES_FILENAME).is_file())

        # CA's own file declares a timeline one frame longer than its last key (7.30 - 7.9333 against
        # keys ending at 7.9167), and BOB maps the keys onto the declared range - so compiled
        # untouched it plays 2.7% slower than the same keys do. The reference is therefore CA's file
        # with its declared end pulled back to its own last key, which is the span this add-on
        # writes; nothing else about it is touched.
        reference_document = read_cs2(SOURCE_CLIP.read_bytes())
        last_key = max(
            time
            for node in reference_document.scene_root.scene_nodes
            for time in node.anim.translation_frame_times + node.anim.rotation_frame_times
        )
        reference_document.timeline_block.end_frame_time = last_key
        reference_cs2 = EXPORT_DIR / "reference_clip.CS2"
        reference_cs2.write_bytes(write_cs2(reference_document))
        written.append(reference_cs2)
        rules.ensure_animation_rules(
            ASSEMBLY_KIT_ROOT, reference_cs2, [(reference_cs2.stem, "rome_man_game", COMPILE_FPS)]
        )

        print("\n== BOB ==")
        check("the output folder is the working_data mirror", working_data_output_dir(ASSEMBLY_KIT_ROOT, result.cs2_path) == COMPILED_DIR)
        bob_result = compile_animation(ASSEMBLY_KIT_ROOT, result.cs2_path)
        print(f"       {bob_result.message}")
        check("BOB compiled our clip", bob_result.success)
        bob_result = compile_animation(ASSEMBLY_KIT_ROOT, reference_cs2)
        check("BOB compiled CA's own clip as a reference", bob_result.success)

        ours_path = COMPILED_DIR / f"{result.cs2_path.stem}.anim"
        reference_path = COMPILED_DIR / f"{reference_cs2.stem}.anim"
        check("a real .anim came out", ours_path.is_file())
        if not ours_path.is_file():
            raise SystemExit(1)

        ours = read_anim(ours_path.read_bytes())
        reference = read_anim(reference_path.read_bytes())
        print(
            f"       ours: {len(ours.bones)} bones, {len(ours.frames)} frames at {ours.frame_rate:g} fps; "
            f"reference: {len(reference.frames)} frames"
        )
        check("version 5", ours.version == 5)
        check("the skeleton name comes from the rules.bob AnimationType", ours.skeleton_name == "rome_man_game")
        check("50 game bones, not the 228 scene nodes", len(ours.bones) == 50)
        check(
            "the compiled bone order is the one PLAN_units.md 1.3 derived",
            [bone.name for bone in ours.bones[:6]]
            == ["bn_hips", "bn_weapon_01", "bn_weapon_02", "bn_weapon_03", "bn_weapon_04", "bn_weapon_05"],
        )
        check("BOB resampled at the rate the rules.bob asked for", ours.frame_rate == COMPILE_FPS)
        check(
            "translation survives only on the root and floating bones, as the rules.bob asks",
            sum(1 for value in ours.translation_mappings if value >= 0) == 6,
        )
        rotated = {bone.name for bone, value in zip(ours.bones, ours.rotation_mappings) if value >= 0}
        reference_rotated = {
            bone.name for bone, value in zip(reference.bones, reference.rotation_mappings) if value >= 0
        }
        check("the same bones are rotated as in CA's own compile", rotated == reference_rotated)
        check(
            "the two compiles agree on length to within a frame",
            abs(len(ours.frames) - len(reference.frames)) <= 1,
        )

        print("\n== ours against BOB's compile of CA's own file ==")
        # Compared per bone through the remap tables, never by track index: the .anim indexes frames
        # by track, so comparing by track number silently compares different bones.
        reference_index = {bone.name: index for index, bone in enumerate(reference.bones)}
        worst_position = 0.0
        worst_rotation = 0.0
        worst_bone = ""
        frames = min(len(ours.frames), len(reference.frames))
        for index, bone in enumerate(ours.bones):
            other = reference_index.get(bone.name)
            if other is None:
                continue
            for frame in range(frames):
                ours_translation, ours_rotation = bone_local_transform(ours, index, frame)
                their_translation, their_rotation = bone_local_transform(reference, other, frame)
                position = max(abs(a - b) for a, b in zip(ours_translation, their_translation))
                rotation = quaternion_distance(ours_rotation, their_rotation)
                if position > worst_position:
                    worst_position, worst_bone = position, bone.name
                worst_rotation = max(worst_rotation, rotation)
        print(f"       worst translation {worst_position:.3e} on '{worst_bone}', worst rotation {worst_rotation:.3e}")
        check("every bone lands where CA's own compile puts it", worst_position < POSITION_TOLERANCE)
        check("every bone is rotated as CA's own compile has it", worst_rotation < ROTATION_TOLERANCE)
        print("\n== the compiled clip imports back onto the same skeleton ==")
        # The order that used to break it: the .cs2 clip poses ref_skeleton a quarter turn about X,
        # the compiled .anim carries only the 50 game bones and cannot say anything about it, so
        # loading the .anim second used to inherit that turn and tip the whole figure face-down.
        rest_of = {bone.name: bone.matrix_local.copy() for bone in armature_object.data.bones}
        game_bones = {bone.name for bone in ours.bones}
        import_file(str(ours_path), bpy.context)
        check("the compiled clip came back as an Action", armature_object.animation_data.action is not None)

        bpy.context.scene.frame_set(1)
        bpy.context.view_layer.update()
        # A helper under an animated bone follows it, which is correct - end_head moves with bn_head.
        # What must not move is a bone with no animated ancestor either, which is the chain above
        # bn_hips the previous clip used to leave turned: Root, ref_skeleton, ref_hips.
        def follows_animation(bone) -> bool:
            while bone is not None:
                if bone.name in game_bones:
                    return True
                bone = bone.parent
            return False

        anchored = [bone.name for bone in armature_object.data.bones if not follows_animation(bone)]
        helper_drift = max(
            (armature_object.pose.bones[name].matrix.translation - rest_of[name].translation).length
            for name in anchored
        )
        print(f"       {len(anchored)} node(s) have no animated ancestor")
        print(f"       helper nodes sit {helper_drift:.2e} m from rest")
        check("nothing the compiled clip cannot animate is left posed", helper_drift < 1e-6)

        hips = armature_object.pose.bones["bn_hips"].matrix.translation
        print(f"       bn_hips at {[round(v, 4) for v in hips]}")
        check("the figure is upright, not tipped onto its face", hips.z > 0.5 and abs(hips.y) < 0.5)

    finally:
        for path in written:
            if path is not None and path.exists():
                path.unlink()
        for path in (EXPORT_DIR, COMPILED_DIR):
            created = created_export_dir if path is EXPORT_DIR else created_compiled_dir
            if created and path.exists():
                shutil.rmtree(path, ignore_errors=True)
        print("\n       cleaned up")

    print()
    if failures:
        print(f"{len(failures)} CHECK(S) FAILED:")
        for failure in failures:
            print(f"  - {failure}")
        raise SystemExit(1)
    print("ALL ANIMATION BOB CHECKS PASSED")


try:
    main()
except SystemExit:
    raise
except Exception:
    traceback.print_exc()
    raise SystemExit(1)
