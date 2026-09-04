import sys
import traceback
from pathlib import Path

import addon_utils
import bpy

REPO_ROOT = r"C:\Users\Khaiali\source\repos\blender_buildings_plugin"
SAMPLES = Path(REPO_ROOT) / "Input" / "examples" / "working_data" / "gondor_fort_gateway_e"
DEBRIS_ANIM = SAMPLES / "gondor_fort_gateway_e_piece01_destruct01_anim.anim"
GATE_ANIM = SAMPLES / "gondor_fort_gateway_e_piece02_destruct01_gate_opening_anim.anim"

if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

POSITION_TOLERANCE = 1e-4

failures = []


def check(label: str, condition: bool) -> None:
    print(("  OK   " if condition else "  FAIL ") + label)
    if not condition:
        failures.append(label)


def reset_scene() -> None:
    for collection in list(bpy.data.collections):
        bpy.data.collections.remove(collection)
    for obj in list(bpy.data.objects):
        bpy.data.objects.remove(obj)
    for mesh in list(bpy.data.meshes):
        bpy.data.meshes.remove(mesh)
    for action in list(bpy.data.actions):
        bpy.data.actions.remove(action)


def main() -> None:
    for path in (DEBRIS_ANIM, GATE_ANIM):
        if not path.exists():
            raise RuntimeError(f"Sample not found: {path}")

    module = addon_utils.enable("total_war_buildings", default_set=True, persistent=False)
    if module is None:
        raise RuntimeError("addon_utils.enable returned failure")

    from binary.anim_reader import bone_local_transform, read_anim
    from importer import import_file
    from importer.anim_importer import FIRST_FRAME

    print("\n== a debris clip brings its pieces with it ==")
    reset_scene()
    animation = read_anim(DEBRIS_ANIM.read_bytes())
    check("the sample is recognised as building debris", animation.is_building_debris())
    collection, warnings, kind = import_file(str(DEBRIS_ANIM), bpy.context)
    for warning in warnings:
        print(f"       {warning}")
    check("routed as a debris bundle", kind == "DEBRIS ANIMATION")
    check("the Building workflow is what a debris bundle belongs to", bpy.context.scene.tw_workflow == "BUILDING")

    objects = [obj for obj in collection.all_objects if obj.type == "MESH"]
    check("the paired model's meshes came in", len(objects) == 20)
    check(
        "a reference import is not presented as an authorable asset",
        collection.tw_role == "NONE" and all(child.tw_role == "NONE" for child in collection.children_recursive),
    )
    check(
        "every mesh knows which debris track drives it",
        all(0 <= obj.tw_debris_track_index < len(animation.bones) for obj in objects),
    )
    check(
        "the tracks used are the 14 the clip carries",
        {obj.tw_debris_track_index for obj in objects} == set(range(len(animation.bones))),
    )
    check(
        "several meshes legitimately share one piece's track",
        len({obj.tw_debris_track_index for obj in objects}) < len(objects),
    )

    print("\n== the pieces move where the clip says ==")
    check(
        "the scene plays the clip's own range",
        (bpy.context.scene.frame_start, bpy.context.scene.frame_end)
        == (FIRST_FRAME, FIRST_FRAME + len(animation.frames) - 1),
    )
    check("the scene plays at the clip's own rate", bpy.context.scene.render.fps == round(animation.frame_rate))

    worst = 0.0
    for frame_index in (0, len(animation.frames) // 2, len(animation.frames) - 1):
        bpy.context.scene.frame_set(FIRST_FRAME + frame_index)
        for obj in objects:
            translation, _rotation = bone_local_transform(animation, obj.tw_debris_track_index, frame_index)
            # Engine Y-up to Blender Z-up, the same swap extraction._to_engine_space is the inverse of.
            expected = (translation[0], translation[2], translation[1])
            worst = max(worst, max(abs(a - b) for a, b in zip(obj.matrix_world.translation, expected)))
    print(f"       worst placement drift {worst:.3e} m")
    check("every piece is placed where its track puts it", worst < POSITION_TOLERANCE)

    moved = set()
    for frame_index in (0, len(animation.frames) - 1):
        bpy.context.scene.frame_set(FIRST_FRAME + frame_index)
        for obj in objects:
            moved.add((obj.name, tuple(round(v, 4) for v in obj.matrix_world.translation)))
    check("the pieces are not all sitting at the origin", len(moved) > len(objects))

    print("\n== a gate clip is the same mechanism with two pieces ==")
    reset_scene()
    gate = read_anim(GATE_ANIM.read_bytes())
    collection, warnings, kind = import_file(str(GATE_ANIM), bpy.context)
    check("routed as a debris bundle", kind == "DEBRIS ANIMATION")
    objects = [obj for obj in collection.all_objects if obj.type == "MESH"]
    check("both gate leaves came in", len(objects) == 2)
    check("each leaf has its own track", {obj.tw_debris_track_index for obj in objects} == {0, 1})

    bpy.context.scene.frame_set(FIRST_FRAME)
    closed = [obj.rotation_quaternion.copy() for obj in objects]
    bpy.context.scene.frame_set(FIRST_FRAME + len(gate.frames) - 1)
    opened = [obj.rotation_quaternion.copy() for obj in objects]
    swings = [first.rotation_difference(second).angle for first, second in zip(closed, opened)]
    print(f"       leaves swing {[round(angle * 57.2958, 1) for angle in swings]} degrees")
    check("both leaves swing open", all(angle > 1.5 for angle in swings))

    print("\n== a debris clip with no model beside it says so ==")
    reset_scene()
    import shutil
    import tempfile

    with tempfile.TemporaryDirectory() as directory:
        lonely = Path(directory) / DEBRIS_ANIM.name
        shutil.copy2(DEBRIS_ANIM, lonely)
        try:
            import_file(str(lonely), bpy.context)
            check("an unpaired debris clip is refused", False)
        except Exception as error:
            check("an unpaired debris clip is refused", "same folder" in str(error))

    print()
    if failures:
        print(f"{len(failures)} CHECK(S) FAILED:")
        for failure in failures:
            print(f"  - {failure}")
        raise SystemExit(1)
    print("ALL DEBRIS BUNDLE CHECKS PASSED")


try:
    main()
except SystemExit:
    raise
except Exception:
    traceback.print_exc()
    raise SystemExit(1)
