import sys
import traceback

ADDON_ROOT = r"C:\Users\Khaiali\source\repos\blender_buildings_plugin\total_war_cs2_addon"
if ADDON_ROOT not in sys.path:
    sys.path.insert(0, ADDON_ROOT)

failures = []


def check(label: str, condition: bool) -> None:
    print(("  OK   " if condition else "  FAIL ") + label)
    if not condition:
        failures.append(label)


def main() -> None:
    from binary import anim_structures as a
    from importer.anim_skeleton import skeleton_from_anim
    from scene_model.skeleton_models import compiled_bone_order

    # Breadth-first with a within-depth order that is not alphabetical, which is how a skeleton CA
    # compiled itself is laid out - and not what BOB's own (depth, name) sort produces.
    names = ["animroot", "root", "spine_0", "upperleg_left", "upperleg_right", "lowerleg_left", "lowerleg_right", "spine_1"]
    parents = [-1, 0, 1, 1, 1, 3, 4, 2]
    animation = a.Animation(
        version=a.FILE_VERSION_ATTILA,
        bone_name_table_version=1,
        frame_rate=20.0,
        skeleton_name="order_test",
        duration=0.0,
        bones=[a.AnimBone(name, parent) for name, parent in zip(names, parents)],
        translation_mappings=[a.STATIC_TRACK_BASE] * len(names),
        rotation_mappings=[a.STATIC_TRACK_BASE] * len(names),
        frames=[a.AnimFrame(), a.AnimFrame()],
    )

    skeleton = skeleton_from_anim(animation, "order_test")
    check("an .anim with no bone table gives every bone its .anim position as sort order",
          [bone.sort_order for bone in skeleton.bones] == list(range(len(names))))
    check("the root is still the only sort order 0", [bone.name for bone in skeleton.bones if bone.sort_order == 0] == ["animroot"])
    check("BOB's compiled bone order is the .anim's own order", compiled_bone_order(skeleton) == names)

    skeleton.bones[names.index("spine_1")].sort_order = 1
    skeleton.bones[names.index("spine_0")].sort_order = 2
    reordered = compiled_bone_order(skeleton)
    check("sort order outranks depth and name", reordered.index("spine_1") < reordered.index("spine_0") < reordered.index("upperleg_left"))


try:
    main()
except Exception:
    traceback.print_exc()
    failures.append("exception")

print("FAILED" if failures else "ALL PASSED")
sys.exit(1 if failures else 0)
