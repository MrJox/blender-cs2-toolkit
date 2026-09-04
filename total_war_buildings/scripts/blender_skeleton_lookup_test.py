import shutil
import sys
import tempfile
import traceback
from pathlib import Path

import addon_utils
import bpy

REPO_ROOT = r"C:\Users\Khaiali\source\repos\blender_buildings_plugin"
ASSEMBLY_KIT_ROOT = r"D:\SteamLibrary\steamapps\common\Total War Attila\assembly_kit"
SKELETON_NAME = "rome_man_game"
RAW_SKELETON = Path(ASSEMBLY_KIT_ROOT) / "raw_data" / "animations" / "skeletons" / f"{SKELETON_NAME}.cs2"
BONE_TABLE = RAW_SKELETON.with_suffix(".bone_table")
COMPILED_SKELETON = (
    Path(ASSEMBLY_KIT_ROOT) / "working_data" / "animations" / "skeletons" / f"{SKELETON_NAME}.anim"
)
WEIGHTED_MODEL = Path(REPO_ROOT) / "Input/examples/working_data/variantmeshes/_variantmodels/gondor/armour/gondor_infantry_armour.rigid_model_v2"
RIGID_MODEL = Path(REPO_ROOT) / "Input/examples/working_data/variantmeshes/_variantmodels/gondor/weapons/gondor_sword_01.rigid_model_v2"

if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

failures = []


def check(label: str, condition: bool) -> None:
    print(("  OK   " if condition else "  FAIL ") + label)
    if not condition:
        failures.append(label)


def set_assembly_kit_root(path: str) -> None:
    bpy.context.preferences.addons["total_war_buildings"].preferences.assembly_kit_root = path


def reset_scene() -> None:
    for collection in list(bpy.data.collections):
        bpy.data.collections.remove(collection)
    for obj in list(bpy.data.objects):
        bpy.data.objects.remove(obj)
    for armature in list(bpy.data.armatures):
        bpy.data.armatures.remove(armature)


def armatures_in_scene() -> list[bpy.types.Object]:
    return [obj for obj in bpy.data.objects if obj.type == "ARMATURE"]


def part_of(collection: bpy.types.Collection) -> bpy.types.Collection:
    # The importer hands back the unit asset; its models are the UNIT_MESH collections under it.
    if collection.tw_role == "UNIT_MESH":
        return collection
    return next(child for child in collection.children if child.tw_role == "UNIT_MESH")


def unit_of(part: bpy.types.Collection) -> bpy.types.Collection | None:
    # The importer hands back the model itself, which is the useful thing to name in a report; the
    # unit it was put under is found by looking for whoever holds it.
    def holds(collection):
        return part.name in collection.children or any(holds(child) for child in collection.children)

    return next((c for c in bpy.data.collections if c.tw_role == "UNIT" and holds(c)), None)


def mesh_objects(model: bpy.types.Collection) -> list[bpy.types.Object]:
    return [obj for obj in model.objects if obj.type == "MESH"]


def bounds(obj: bpy.types.Object):
    points = [obj.matrix_world @ vertex.co for vertex in obj.data.vertices]
    return tuple((min(p[a] for p in points), max(p[a] for p in points)) for a in range(3))


def main() -> None:
    for required in (RAW_SKELETON, BONE_TABLE, WEIGHTED_MODEL, RIGID_MODEL):
        if not required.is_file():
            raise RuntimeError(f"Sample not found: {required}")

    module = addon_utils.enable("total_war_buildings", default_set=True, persistent=False)
    if module is None:
        raise RuntimeError("addon_utils.enable returned failure")

    from extraction.unit_extract import unit_model_collections
    from importer import import_file
    from importer.messages import severity_of
    from importer.rigid_model_v2_importer import (
        bone_names_by_compiled_index,
        models_needing_a_skeleton,
    )
    from importer.skeleton_lookup import ANIM_SOURCE, CS2_SOURCE, find_skeleton_source

    with tempfile.TemporaryDirectory() as scratch:
        scratch = Path(scratch)
        empty_folder = scratch / "empty"
        empty_folder.mkdir()
        beside_folder = scratch / "beside"
        beside_folder.mkdir()
        model_beside = beside_folder / WEIGHTED_MODEL.name
        shutil.copyfile(WEIGHTED_MODEL, model_beside)
        if COMPILED_SKELETON.is_file():
            shutil.copyfile(COMPILED_SKELETON, beside_folder / COMPILED_SKELETON.name)

        # A kit with only the compiled half, to reach step 4 without step 3 answering first.
        working_only_kit = scratch / "working_only_kit"
        working_skeletons = working_only_kit / "working_data" / "animations" / "skeletons"
        working_skeletons.mkdir(parents=True)
        if COMPILED_SKELETON.is_file():
            shutil.copyfile(COMPILED_SKELETON, working_skeletons / COMPILED_SKELETON.name)

        print("=== the cascade picks the right source, in order ===")
        beside = find_skeleton_source(SKELETON_NAME, model_beside, ASSEMBLY_KIT_ROOT)
        check("a .anim beside the model wins over the Assembly Kit",
              beside is not None and beside.kind == ANIM_SOURCE and beside.path.parent == beside_folder)

        raw = find_skeleton_source(SKELETON_NAME, empty_folder / "x.rigid_model_v2", ASSEMBLY_KIT_ROOT)
        check("raw_data's .cs2 is next", raw is not None and raw.kind == CS2_SOURCE and raw.path == RAW_SKELETON)
        check("it finds the .bone_table beside it", raw is not None and raw.bone_table_path == BONE_TABLE)

        working = find_skeleton_source(SKELETON_NAME, empty_folder / "x.rigid_model_v2", str(working_only_kit))
        check("working_data's .anim is the last resort",
              working is not None and working.kind == ANIM_SOURCE and working.path.parent == working_skeletons)

        check("nothing is found with no Assembly Kit set",
              find_skeleton_source(SKELETON_NAME, empty_folder / "x.rigid_model_v2", "") is None)
        check("a model that names no skeleton is never looked up",
              find_skeleton_source("", model_beside, ASSEMBLY_KIT_ROOT) is None)

        print("=== 1. a skeleton already in the scene is used silently ===")
        reset_scene()
        set_assembly_kit_root(ASSEMBLY_KIT_ROOT)
        import_file(str(RAW_SKELETON), bpy.context)
        before = len(armatures_in_scene())
        collection, warnings, _kind = import_file(str(WEIGHTED_MODEL), bpy.context)
        check("no second skeleton was imported", len(armatures_in_scene()) == before)
        check("nothing was reported about a missing skeleton",
              not any("No skeleton named" in warning for warning in warnings))
        check("nothing was reported about importing one either",
              not any("was imported from" in warning for warning in warnings))
        part = part_of(collection)
        check("the part is bound", not models_needing_a_skeleton(collection))
        groups = {group.name for obj in mesh_objects(part) for group in obj.vertex_groups}
        check("its vertex groups are real bone names", groups and not any(g.startswith("bone_") for g in groups))
        from_cs2_bounds = bounds(mesh_objects(part)[0])

        print("=== 2. a .anim beside the model is imported with it ===")
        reset_scene()
        set_assembly_kit_root(ASSEMBLY_KIT_ROOT)
        collection, warnings, _kind = import_file(str(model_beside), bpy.context)
        check("a skeleton was imported alongside", len(armatures_in_scene()) == 1)
        check("it says where it came from",
              any("beside the model" in warning for warning in warnings))
        part = part_of(collection)
        check("the part is bound", not models_needing_a_skeleton(collection))
        check("finding a skeleton is reported as information, not as a warning",
              all(severity_of(warning) == "INFO" for warning in warnings))

        unit = unit_of(part)
        check("the import lands in a UNIT collection", unit is not None)
        check("its models are UNIT_MESH collections directly under it",
              unit is not None and [c.tw_role for c in unit.children].count("UNIT_MESH") == 1)
        # A skeleton is a root collection of its own, never nested in a unit: one skeleton is shared
        # by every model weighted to it, so it belongs to no single asset.
        check("the skeleton is not nested inside the unit",
              unit is not None and "SKELETON" not in [c.tw_role for c in unit.children])
        check("the skeleton is a root collection",
              any(c.tw_role == "SKELETON" for c in bpy.context.scene.collection.children))
        check("the LOD objects sit in the model itself", bool(mesh_objects(part)))
        check("the exporter finds the imported model", [p.name for p in unit_model_collections(unit)] == [part.name])

        armature_object = armatures_in_scene()[0]
        # File order decided bone length before: bn_righthand's first child is the thumb root and
        # bn_lefthand's is a finger root, so one hand came out a third the size of the other.
        left = armature_object.data.bones["bn_lefthand"].length
        right = armature_object.data.bones["bn_righthand"].length
        check(f"both hands are drawn the same size (left {left * 100:.2f}cm, right {right * 100:.2f}cm)",
              abs(left - right) < 5e-3)
        check("the .anim reproduces the compiled bone order",
              bone_names_by_compiled_index(armature_object)[:6]
              == ["bn_hips"] + [f"bn_weapon_0{index}" for index in range(1, 6)])
        # The .anim is in compiled space and the .cs2 in authoring space; both have to end up in the
        # same Blender space, or a mesh bound through one would not line up with the other.
        from_anim_bounds = bounds(mesh_objects(part)[0])
        check("the mesh lands in the same place as with the .cs2 skeleton",
              all(abs(a - b) < 1e-4 for pair_a, pair_b in zip(from_cs2_bounds, from_anim_bounds)
                  for a, b in zip(pair_a, pair_b)))

        print("=== 5. nothing found - it still imports, and says so ===")
        reset_scene()
        set_assembly_kit_root("")
        collection, warnings, _kind = import_file(str(WEIGHTED_MODEL), bpy.context)
        check("no skeleton was invented", not armatures_in_scene())
        check("the missing skeleton is reported",
              any("No skeleton named 'rome_man_game'" in warning for warning in warnings))
        check("the part is flagged as needing one", len(models_needing_a_skeleton(collection)) == 1)
        groups = {group.name for obj in mesh_objects(part_of(collection)) for group in obj.vertex_groups}
        check("its groups fall back to bone_<index>", all(g.startswith("bone_") for g in groups))

        print("=== a model that names no skeleton never triggers any of this ===")
        reset_scene()
        set_assembly_kit_root("")
        collection, warnings, _kind = import_file(str(RIGID_MODEL), bpy.context)
        check("no skeleton lookup happened",
              not any("No skeleton named" in warning for warning in warnings))
        check("it is not flagged as needing a skeleton", not models_needing_a_skeleton(collection))
        check("it imported as a Rigid Model", part_of(collection).tw_unit_part_kind == "RIGID_ATTACHMENT")

    set_assembly_kit_root(ASSEMBLY_KIT_ROOT)
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
