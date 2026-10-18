import sys
import traceback
from pathlib import Path

import addon_utils
import bpy

REPO_ROOT = r"C:\Users\Khaiali\source\repos\blender_buildings_plugin"
ASSEMBLY_KIT_ROOT = r"D:\SteamLibrary\steamapps\common\Total War Attila\assembly_kit"
SKELETON_CS2 = Path(ASSEMBLY_KIT_ROOT) / "raw_data" / "animations" / "skeletons" / "rome_man_game.cs2"

if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

failures = []


def check(label: str, condition: bool) -> None:
    print(("  OK   " if condition else "  FAIL ") + label)
    if not condition:
        failures.append(label)


def main() -> None:
    module = addon_utils.enable("total_war_cs2_addon", default_set=True, persistent=False)
    if module is None:
        raise RuntimeError("addon_utils.enable returned failure")

    from extraction.unit_extract import armature_of, evaluated_bone_weights, extract_unit
    from importer import import_file
    from materials.material_builder import create_total_war_material
    from validation.rules import validate_unit

    skeleton_collection, _warnings, _kind = import_file(str(SKELETON_CS2), bpy.context)
    armature_object = next(obj for obj in skeleton_collection.all_objects if obj.type == "ARMATURE")
    bpy.context.scene.tw_workflow = "UNIT"

    unit = bpy.data.collections.new("decimate_weights")
    unit.tw_role = "UNIT"
    bpy.context.scene.collection.children.link(unit)
    model = bpy.data.collections.new("decimate_weights_mesh")
    model.tw_role = "UNIT_MESH"
    model.tw_unit_part_kind = "WEIGHTED"
    unit.children.link(model)

    material = bpy.data.materials.new("decimate_weights_material")
    material.tw_shader_type = "weighted"
    create_total_war_material(material)

    mesh = bpy.data.meshes.new("decimate_weights_lod1")
    mesh.from_pydata([(x * 0.1, y * 0.1, 0.0) for x in range(8) for y in range(8)], [],
                     [(x * 8 + y, (x + 1) * 8 + y, (x + 1) * 8 + y + 1, x * 8 + y + 1) for x in range(7) for y in range(7)])
    mesh.uv_layers.new(name="UVMap")
    mesh.materials.append(material)
    mesh.update()
    obj = bpy.data.objects.new("decimate_weights_lod1", mesh)
    model.objects.link(obj)

    bones = [armature_object.data.bones[name] for name in ("bn_spine", "bn_spine1", "bn_spine2")]
    groups = [obj.vertex_groups.new(name=bone.name) for bone in bones]
    for vertex in mesh.vertices:
        for position, group in enumerate(groups):
            group.add([vertex.index], 0.2 + 0.2 * ((vertex.index + position) % 3), "REPLACE")
    armature = obj.modifiers.new(name="Armature", type="ARMATURE")
    armature.object = armature_object
    check("the armature modifier resolves", armature_of(obj) is armature_object)

    decimate = obj.modifiers.new(name="Decimate", type="DECIMATE")
    decimate.ratio = 0.3
    bpy.context.view_layer.update()
    depsgraph = bpy.context.evaluated_depsgraph_get()

    bone_names = {bone.name for bone in armature_object.data.bones}
    evaluated = evaluated_bone_weights(obj, depsgraph, bone_names)
    check("the decimate modifier removed vertices", len(evaluated) < len(mesh.vertices))
    check("every evaluated vertex is weighted", all(entry for entry in evaluated))

    part, warnings = extract_unit(unit, depsgraph, bpy.context.view_layer)
    lod = part.meshes[0].lods[0]
    check("one weight list per exported vertex", len(lod.weights) == len(lod.mesh.vertices))
    check("exported weights are not truncated to two", any(len(entry) > 2 for entry in lod.weights))
    check("each vertex's weights sum to one", all(abs(sum(w for _n, w in entry) - 1.0) < 1e-6 for entry in lod.weights))
    check("a warning says BOB redistributes", any("BOB keeps" in warning for warning in warnings))

    issues = validate_unit(unit, ASSEMBLY_KIT_ROOT)
    check("validation warns about the evaluated mesh",
          any("once its modifiers are applied" in issue.message for issue in issues))

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
