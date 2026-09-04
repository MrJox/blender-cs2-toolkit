import sys
import traceback

import addon_utils
import bpy

REPO_ROOT = r"C:\Users\Khaiali\source\repos\blender_buildings_plugin"

if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

# panel -> the workflows it must be visible in; it must be hidden in every other one.
PANEL_WORKFLOWS = {
    "TW_PT_workflow": {"BUILDING", "UNIT", "SKELETON", "SKELETAL_ANIMATION", "VEGETATION"},
    "TW_PT_building_setup": {"BUILDING"},
    "TW_PT_unit_setup": {"UNIT"},
    "TW_PT_skeleton_setup": {"SKELETON"},
    "TW_PT_animation_setup": {"SKELETAL_ANIMATION"},
    "TW_PT_vegetation_setup": {"VEGETATION"},
    "TW_PT_materials": {"BUILDING", "UNIT", "VEGETATION"},
    "TW_PT_validation": {"BUILDING", "UNIT", "SKELETON", "SKELETAL_ANIMATION"},
    "TW_PT_export": {"BUILDING", "UNIT", "SKELETON", "SKELETAL_ANIMATION"},
}
ALL_WORKFLOWS = ("BUILDING", "UNIT", "SKELETON", "SKELETAL_ANIMATION", "VEGETATION")

failures = []


def check(label: str, condition: bool) -> None:
    print(("  OK   " if condition else "  FAIL ") + label)
    if not condition:
        failures.append(label)


def active_layer_collection_for(collection: bpy.types.Collection) -> bpy.types.LayerCollection:
    def find(layer_collection: bpy.types.LayerCollection):
        if layer_collection.collection == collection:
            return layer_collection
        for child in layer_collection.children:
            found = find(child)
            if found is not None:
                return found
        return None

    result = find(bpy.context.view_layer.layer_collection)
    if result is None:
        raise RuntimeError(f"Could not find layer collection for {collection.name}")
    return result


def panel_visible(idname: str) -> bool:
    panel = getattr(bpy.types, idname)
    poll = getattr(panel, "poll", None)
    return True if poll is None else poll(bpy.context)


def check_gating(workflow: str) -> None:
    bpy.context.scene.tw_workflow = workflow
    print(f"=== workflow {workflow} ===")
    for idname, workflows in PANEL_WORKFLOWS.items():
        expected = workflow in workflows
        check(f"{workflow}: {idname} {'shown' if expected else 'hidden'}", panel_visible(idname) == expected)


def main() -> None:
    module = addon_utils.enable("total_war_buildings", default_set=True, persistent=False)
    if module is None:
        raise RuntimeError("addon_utils.enable returned failure")

    print("=== defaults ===")
    check("default workflow is BUILDING", bpy.context.scene.tw_workflow == "BUILDING")

    for workflow in ALL_WORKFLOWS:
        check_gating(workflow)

    print("=== sidebar ordering ===")
    # bl_order decides the sidebar order; the per-workflow setup panel must sit directly under the
    # workflow switch in every workflow, not below Export.
    expected_order = {
        "TW_PT_workflow": 0,
        "TW_PT_building_setup": 1,
        "TW_PT_unit_setup": 1,
        "TW_PT_skeleton_setup": 1,
        "TW_PT_animation_setup": 1,
        "TW_PT_vegetation_setup": 1,
        "TW_PT_materials": 2,
        "TW_PT_validation": 3,
        "TW_PT_export": 4,
    }
    for idname, order in expected_order.items():
        check(f"{idname} sits at sidebar position {order}",
              getattr(bpy.types, idname).bl_order == order)
    for workflow in ALL_WORKFLOWS:
        bpy.context.scene.tw_workflow = workflow
        visible = [name for name in expected_order if panel_visible(name)]
        visible.sort(key=lambda name: (expected_order[name], name))
        check(f"{workflow}: workflow switch is first", visible[0] == "TW_PT_workflow")
        if len(visible) > 1:
            check(f"{workflow}: the setup panel follows it", expected_order[visible[1]] == 1)

    print("=== shader types are filtered per workflow ===")
    from materials.shader_types import SHADER_TYPES, SHADER_TYPE_WORKFLOWS, shader_types_for_workflow

    check("every shader type is mapped to workflows",
          {entry[0] for entry in SHADER_TYPES} == set(SHADER_TYPE_WORKFLOWS))
    building_types = [entry[0] for entry in shader_types_for_workflow("BUILDING")]
    unit_types = [entry[0] for entry in shader_types_for_workflow("UNIT")]
    check("building keeps exactly its own four shader types",
          building_types == ["default", "tiled_dirtmap", "ship_ambientmap", "terrain_blend"])
    check("the weighted shaders are not offered to the building workflow",
          not [name for name in building_types if name.startswith("weighted")])
    check("unit offers default", "default" in unit_types)
    check("unit does not offer tiled_dirtmap", "tiled_dirtmap" not in unit_types)
    check("skeleton offers no shader types", shader_types_for_workflow("SKELETON") == [])
    vegetation_types = [entry[0] for entry in shader_types_for_workflow("VEGETATION")]
    check("vegetation offers exactly the two tree shaders", vegetation_types == ["tree", "tree_leaf"])
    check("the tree shaders are offered to no other workflow",
          not [name for name in building_types + unit_types if name.startswith("tree")])

    material = bpy.data.materials.new("shader type probe")
    cube_for_material = bpy.ops.mesh.primitive_cube_add()
    probe = bpy.context.object
    probe.data.materials.append(material)
    bpy.context.scene.tw_workflow = "UNIT"
    bpy.ops.tw_buildings.set_shader_type(shader_type="default")
    check("set_shader_type assigns", material.tw_shader_type == "default")
    bpy.ops.tw_buildings.set_shader_type(shader_type="tiled_dirtmap")
    check("a building shader is still assignable while in the unit workflow",
          material.tw_shader_type == "tiled_dirtmap")
    bpy.data.objects.remove(probe, do_unlink=True)

    print("=== building workflow is unchanged ===")
    bpy.context.scene.tw_workflow = "BUILDING"
    bpy.ops.tw_buildings.new_building()
    building = [c for c in bpy.data.collections if c.tw_role == "BUILDING"][-1]
    bpy.context.view_layer.active_layer_collection = active_layer_collection_for(building)
    bpy.ops.tw_buildings.new_piece()
    piece = [c for c in bpy.data.collections if c.tw_role == "PIECE"][-1]
    bpy.context.view_layer.active_layer_collection = active_layer_collection_for(piece)
    bpy.ops.tw_buildings.new_destruct_level()
    destruct = [c for c in bpy.data.collections if c.tw_role == "DESTRUCT"][-1]
    check("building tree still builds", piece.name in {c.name for c in building.children})
    check("destruct level still gets Display + Collision",
          {c.tw_role for c in destruct.children} == {"DISPLAY", "COLLISION"})

    print("=== unit workflow ===")
    bpy.context.scene.tw_workflow = "UNIT"
    bpy.ops.tw_buildings.new_unit()
    unit = [c for c in bpy.data.collections if c.tw_role == "UNIT"][-1]
    bpy.context.view_layer.active_layer_collection = active_layer_collection_for(unit)

    # Two levels: the asset holds its models directly, and the Model Type is the model's.
    bpy.ops.tw_buildings.new_unit_mesh(model_name="body", kind="WEIGHTED")
    body = [c for c in bpy.data.collections if c.tw_role == "UNIT_MESH"][-1]
    check("the model nests directly under the asset", body.name in {c.name for c in unit.children})
    check("the model carries the Model Type", body.tw_unit_part_kind == "WEIGHTED")
    check("the model holds no further collections", not body.children)

    bpy.ops.tw_buildings.new_unit_mesh(model_name="eyes", kind="WEIGHTED")
    check("an asset can hold several models",
          len([c for c in unit.children if c.tw_role == "UNIT_MESH"]) == 2)

    print("=== skeleton workflow ===")
    bpy.context.scene.tw_workflow = "SKELETON"
    bpy.context.view_layer.active_layer_collection = active_layer_collection_for(unit)
    bpy.ops.tw_buildings.new_skeleton()
    skeleton = [c for c in bpy.data.collections if c.tw_role == "SKELETON"][-1]
    # A skeleton is a root collection of its own: one skeleton is shared by every model weighted
    # to it, so it belongs to no single unit asset.
    check("skeleton is a root collection, not nested in the unit",
          skeleton.name in bpy.context.scene.collection.children
          and skeleton.name not in unit.children)
    armatures = [o for o in skeleton.objects if o.type == "ARMATURE"]
    check("skeleton holds one Armature", len(armatures) == 1)

    print("=== native weighting surface ===")
    armature_object = armatures[0]
    armature = armature_object.data
    bpy.context.view_layer.objects.active = armature_object
    bpy.ops.object.mode_set(mode="EDIT")
    for name, head, tail in (("bn_hips", (0.0, 0.0, 0.0), (0.0, 0.0, 0.5)),
                             ("bn_spine", (0.0, 0.0, 0.5), (0.0, 0.0, 1.0))):
        bone = armature.edit_bones.new(name)
        bone.head = head
        bone.tail = tail
    bpy.ops.object.mode_set(mode="OBJECT")
    check("armature carries the two bones", len(armature.bones) == 2)

    bpy.ops.mesh.primitive_cube_add()
    part_mesh = bpy.context.object
    for collection in list(part_mesh.users_collection):
        collection.objects.unlink(part_mesh)
    body.objects.link(part_mesh)
    part_mesh.tw_lod_index = "LOD01"

    for bone in armature.bones:
        group = part_mesh.vertex_groups.new(name=bone.name)
        group.add([v.index for v in part_mesh.data.vertices], 0.5, "REPLACE")
    modifier = part_mesh.modifiers.new(name="Armature", type="ARMATURE")
    modifier.object = armature_object

    from ui.collection_utils import get_object_collection_role
    from extraction.unit_extract import armature_of

    check("mesh resolves to its UNIT_MESH role", get_object_collection_role(part_mesh) == "UNIT_MESH")
    check("vertex groups are named after bones",
          {g.name for g in part_mesh.vertex_groups} == {b.name for b in armature.bones})
    check("armature modifier resolves back to the skeleton", armature_of(part_mesh) is armature_object)
    check("every vertex carries both bone weights",
          all(len(v.groups) == 2 for v in part_mesh.data.vertices))
    check("LOD level round-trips", part_mesh.tw_lod_index == "LOD01")

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
