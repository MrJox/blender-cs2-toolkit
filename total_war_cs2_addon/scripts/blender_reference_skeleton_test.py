import sys
import traceback
from pathlib import Path

import addon_utils
import bpy

REPO_ROOT = r"C:\Users\Khaiali\source\repos\blender_buildings_plugin"
ASSEMBLY_KIT_ROOT = r"D:\SteamLibrary\steamapps\common\Total War Attila\assembly_kit"
SKELETON_CS2 = Path(ASSEMBLY_KIT_ROOT) / "raw_data" / "animations" / "skeletons" / "rome_man_game.cs2"
SKELETON_ANIM = Path(ASSEMBLY_KIT_ROOT) / "working_data" / "animations" / "skeletons" / "rome_man_game.anim"

if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

failures = []


def check(label: str, condition: bool) -> None:
    print(("  OK   " if condition else "  FAIL ") + label)
    if not condition:
        failures.append(label)


def bound_asset(name: str, armature_object: bpy.types.Object) -> bpy.types.Collection:
    from materials.material_builder import create_total_war_material

    unit = bpy.data.collections.new(name)
    unit.tw_role = "UNIT"
    bpy.context.scene.collection.children.link(unit)
    model = bpy.data.collections.new(f"{name}_mesh")
    model.tw_role = "UNIT_MESH"
    model.tw_unit_part_kind = "WEIGHTED"
    unit.children.link(model)
    material = bpy.data.materials.new(f"{name}_material")
    material.tw_shader_type = "weighted"
    create_total_war_material(material)
    mesh = bpy.data.meshes.new(f"{name}_lod1")
    mesh.from_pydata([(0, 0, 1), (0.1, 0, 1), (0, 0.1, 1)], [], [(0, 1, 2)])
    mesh.uv_layers.new(name="UVMap")
    mesh.materials.append(material)
    obj = bpy.data.objects.new(f"{name}_lod1", mesh)
    model.objects.link(obj)
    obj.vertex_groups.new(name="bn_spine1").add([0, 1, 2], 1.0, "REPLACE")
    obj.modifiers.new(name="Armature", type="ARMATURE").object = armature_object
    return unit


def reference_issues(unit: bpy.types.Collection, assembly_kit_root: str = ASSEMBLY_KIT_ROOT):
    from validation.rules import validate_unit

    return [issue for issue in validate_unit(unit, assembly_kit_root) if "reference skeleton" in issue.message]


def move_edit_bone(armature_object: bpy.types.Object, bone_name: str, offset) -> None:
    bpy.context.view_layer.objects.active = armature_object
    bpy.ops.object.mode_set(mode="EDIT")
    bone = armature_object.data.edit_bones[bone_name]
    bone.head.x += offset
    bone.tail.x += offset
    bpy.ops.object.mode_set(mode="OBJECT")


def main() -> None:
    module = addon_utils.enable("total_war_cs2_addon", default_set=True, persistent=False)
    if module is None:
        raise RuntimeError("addon_utils.enable returned failure")

    from importer import import_file
    from importer.skeleton_importer import import_skeleton_source
    from importer.skeleton_lookup import ANIM_SOURCE, SkeletonSource

    skeleton_collection, _warnings, _kind = import_file(str(SKELETON_CS2), bpy.context)
    armature_object = next(obj for obj in skeleton_collection.all_objects if obj.type == "ARMATURE")
    bpy.context.scene.tw_workflow = "UNIT"
    unit = bound_asset("reference_skeleton_probe", armature_object)

    print("=== the untouched reference skeleton passes ===")
    check("no reference-skeleton issue", not reference_issues(unit))
    check("no check at all without an Assembly Kit", not reference_issues(unit, ""))

    print("=== a bone moved under BOB's 2 cm passes ===")
    move_edit_bone(armature_object, "ref_hips", 0.015)
    check("1.5 cm is accepted, as BOB accepts it", not reference_issues(unit))
    move_edit_bone(armature_object, "ref_hips", -0.015)

    print("=== a bone moved past it is an error naming the bone ===")
    move_edit_bone(armature_object, "ref_hips", 0.05)
    issues = reference_issues(unit)
    print("       ", [issue.message for issue in issues])
    check("one blocking error", len(issues) == 1 and issues[0].severity == "ERROR")
    check("it names ref_hips first, 5.0 cm off", bool(issues) and "(ref_hips 5.0 cm" in issues[0].message)
    move_edit_bone(armature_object, "ref_hips", -0.05)
    check("moving it back clears it", not reference_issues(unit))

    print("=== applied scale changes every offset, and ref_hips is the first BOB reaches ===")
    bpy.ops.object.select_all(action="DESELECT")
    armature_object.select_set(True)
    bpy.context.view_layer.objects.active = armature_object
    armature_object.scale = (1.1, 1.1, 1.1)
    check("an unapplied object scale is not a rest-pose change", not reference_issues(unit))
    bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)
    issues = reference_issues(unit)
    print("       ", [issue.message for issue in issues])
    check("an applied scale is an error led by ref_hips",
          len(issues) == 1 and issues[0].severity == "ERROR" and "(ref_hips " in issues[0].message)

    print("=== a skeleton rebuilt from the compiled .anim lacks the helper nodes ===")
    skeleton_collection.name = "rome_man_game_scaled"
    anim_armature, anim_collection, _warnings = import_skeleton_source(
        SkeletonSource(path=SKELETON_ANIM, kind=ANIM_SOURCE), bpy.context
    )
    check("the .anim skeleton took the reference name", anim_collection.name == "rome_man_game")
    anim_unit = bound_asset("reference_skeleton_anim_probe", anim_armature)
    issues = reference_issues(anim_unit)
    print("       ", [issue.message for issue in issues])
    check("missing bones are the one error, led by ref_skeleton",
          len(issues) == 1 and issues[0].severity == "ERROR" and "(ref_skeleton, " in issues[0].message)

    print("=== a skeleton with no reference file is not checked ===")
    check("a renamed skeleton has nothing to compare against", not reference_issues(unit))

    print()
    if failures:
        print(f"FAILED {len(failures)} check(s):")
        for failure in failures:
            print("   ", failure)
        raise SystemExit(1)
    print("all checks passed")


try:
    main()
except SystemExit:
    raise
except Exception:
    traceback.print_exc()
    sys.exit(1)
