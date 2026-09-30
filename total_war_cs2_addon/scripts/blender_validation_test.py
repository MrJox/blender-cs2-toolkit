import sys
import traceback

import addon_utils
import bpy

REPO_ROOT = r"C:\Users\Khaiali\source\repos\blender_buildings_plugin"
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)


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


def reset_scene() -> None:
    for coll in list(bpy.data.collections):
        bpy.data.collections.remove(coll)
    for obj in list(bpy.data.objects):
        bpy.data.objects.remove(obj)
    for mat in list(bpy.data.materials):
        bpy.data.materials.remove(mat)


def new_building() -> bpy.types.Collection:
    bpy.ops.tw_buildings.new_building()
    return [c for c in bpy.data.collections if c.tw_role == "BUILDING"][-1]


def new_piece(building: bpy.types.Collection) -> bpy.types.Collection:
    bpy.context.view_layer.active_layer_collection = active_layer_collection_for(building)
    bpy.ops.tw_buildings.new_piece()
    return building.children[-1]


def new_destruct(piece: bpy.types.Collection) -> bpy.types.Collection:
    bpy.context.view_layer.active_layer_collection = active_layer_collection_for(piece)
    bpy.ops.tw_buildings.new_destruct_level()
    return piece.children[-1]


def add_box(collection: bpy.types.Collection) -> bpy.types.Object:
    bpy.ops.mesh.primitive_cube_add()
    obj = bpy.context.active_object
    for coll in list(obj.users_collection):
        coll.objects.unlink(obj)
    collection.objects.link(obj)
    return obj


def report(label: str, building: bpy.types.Collection) -> None:
    from validation.rules import validate_building, has_blocking_issues

    issues = validate_building(building)
    print(f"--- {label} ---")
    for issue in issues:
        print(f"  [{issue.severity}] {issue.message}")
    print("  blocking:", has_blocking_issues(issues))
    print()


def case_empty_building() -> None:
    reset_scene()
    building = new_building()
    report("empty building (no pieces)", building)


def case_missing_collision() -> None:
    reset_scene()
    building = new_building()
    piece = new_piece(building)
    destruct = new_destruct(piece)
    display = [c for c in destruct.children if c.tw_role == "DISPLAY"][0]
    obj = add_box(display)
    bpy.context.view_layer.objects.active = obj
    obj.select_set(True)
    bpy.ops.object.mode_set(mode="EDIT")
    bpy.ops.mesh.select_all(action="SELECT")
    bpy.ops.uv.smart_project()
    bpy.ops.object.mode_set(mode="OBJECT")
    _mat_obj = bpy.context.active_object
    _material = bpy.data.materials.new(name=f"{_mat_obj.name}_Material")
    _mat_obj.data.materials.append(_material)
    _mat_obj.active_material = _material
    bpy.ops.tw_buildings.make_material()
    report("missing collision mesh", building)


def case_missing_uv_and_material() -> None:
    reset_scene()
    building = new_building()
    piece = new_piece(building)
    destruct = new_destruct(piece)
    display = [c for c in destruct.children if c.tw_role == "DISPLAY"][0]
    add_box(display)  # no UV, no material, no collision either
    report("no UV, no material, no collision", building)


def case_empty_display_collection() -> None:
    reset_scene()
    building = new_building()
    piece = new_piece(building)
    new_destruct(piece)
    report("destruct level with nothing in Display", building)


def case_no_uv_map() -> None:
    reset_scene()
    building = new_building()
    piece = new_piece(building)
    destruct = new_destruct(piece)
    display = [c for c in destruct.children if c.tw_role == "DISPLAY"][0]
    collision = [c for c in destruct.children if c.tw_role == "COLLISION"][0]
    obj = add_box(display)
    while obj.data.uv_layers:
        obj.data.uv_layers.remove(obj.data.uv_layers[0])
    _mat_obj = bpy.context.active_object
    _material = bpy.data.materials.new(name=f"{_mat_obj.name}_Material")
    _mat_obj.data.materials.append(_material)
    _mat_obj.active_material = _material
    bpy.ops.tw_buildings.make_material()
    coll_obj = add_box(collision)
    coll_obj.tw_collision_type = "COLLISION"
    report("mesh with UV map explicitly removed", building)


def case_valid_minimal() -> None:
    reset_scene()
    building = new_building()
    piece = new_piece(building)
    destruct = new_destruct(piece)
    display = [c for c in destruct.children if c.tw_role == "DISPLAY"][0]
    collision = [c for c in destruct.children if c.tw_role == "COLLISION"][0]
    obj = add_box(display)
    bpy.context.view_layer.objects.active = obj
    obj.select_set(True)
    bpy.ops.object.mode_set(mode="EDIT")
    bpy.ops.mesh.select_all(action="SELECT")
    bpy.ops.uv.smart_project()
    bpy.ops.object.mode_set(mode="OBJECT")
    _mat_obj = bpy.context.active_object
    _material = bpy.data.materials.new(name=f"{_mat_obj.name}_Material")
    _mat_obj.data.materials.append(_material)
    _mat_obj.active_material = _material
    bpy.ops.tw_buildings.make_material()
    obj.active_material.node_tree.nodes.get("Diffuse").image = None
    coll_obj = add_box(collision)
    coll_obj.tw_collision_type = "COLLISION"
    report("fully valid minimal building (expect zero ERROR, one WARNING for no diffuse)", building)


def messages(building: bpy.types.Collection) -> list[str]:
    from validation.rules import validate_building

    return [issue.message for issue in validate_building(building)]


def case_meshes_in_an_unroled_subcollection() -> None:
    reset_scene()
    building = new_building()
    piece = new_piece(building)
    destruct = new_destruct(piece)
    display = [c for c in destruct.children if c.tw_role == "DISPLAY"][0]
    group = bpy.data.collections.new("Main_Walls")
    display.children.link(group)
    add_box(group)
    report("meshes parked in a plain sub-collection inside Display", building)
    assert any("Main_Walls" in m and "left out of the export" in m for m in messages(building))


def case_scaled_flag() -> None:
    reset_scene()
    building = new_building()
    piece = new_piece(building)
    new_destruct(piece)
    flag = bpy.data.collections.new("Flag")
    flag.tw_role = "FLAG"
    building.children.link(flag)
    obj = add_box(flag)
    obj.scale = (2.0, 2.0, 2.0)
    bpy.context.view_layer.update()
    report("flag scaled in Object Mode", building)
    assert any("the scale is dropped" in m for m in messages(building))
    obj.scale = (1.0, 1.0, 1.0)
    bpy.context.view_layer.update()
    assert not any("the scale is dropped" in m for m in messages(building))


def case_tint_masks() -> None:
    case_valid_minimal()
    building = [c for c in bpy.data.collections if c.tw_role == "BUILDING"][-1]
    material = next(o for o in bpy.data.objects if o.active_material is not None).active_material
    nodes = material.node_tree.nodes

    def assign(*names: str) -> list[str]:
        for index, name in enumerate(names, 1):
            image = bpy.data.images.new(f"tint_{index}_{name or 'none'}", 4, 4)
            image.filepath = rf"C:\masks\{name}.tga"
            nodes.get(f"Tint Mask {index}").image = image if name else None
        return [m for m in messages(building) if "tint mask" in m.lower()]

    assert assign("", "", "") == []
    partial = assign("wall_mask1", "", "")
    print("partial:", partial)
    assert len(partial) == 1 and "Tint Mask 2, Tint Mask 3 empty" in partial[0]
    assert assign("wall_mask1", "wall_mask2", "wall_mask3") == []
    assert assign("Wall_Mask1", "wall_mask2", "WALL_MASK3") == []
    arbitrary = assign("wall_red", "wall_green", "wall_blue")
    print("arbitrary:", arbitrary)
    assert len(arbitrary) == 1 and "'wall_mask.dds'" in arbitrary[0]
    assert len(assign("a_mask1", "b_mask2", "a_mask3")) == 1
    assert len(assign("mask1", "mask2", "mask3")) == 1


def case_unit_tint_masks() -> None:
    from materials.material_builder import create_total_war_material
    from validation.rules import _validate_unit_shader

    reset_scene()
    mesh = bpy.data.meshes.new("unit probe")
    obj = bpy.data.objects.new("unit probe", mesh)
    bpy.context.scene.collection.objects.link(obj)

    def tint_issues(shader_type: str, weighted: bool, *names: str) -> list[str]:
        material = bpy.data.materials.new(shader_type)
        material.tw_shader_type = shader_type
        create_total_war_material(material)
        for index, name in enumerate(names, 1):
            image = bpy.data.images.new(f"{shader_type}_{index}_{name}", 4, 4)
            image.filepath = rf"C:\masks\{name}.tga"
            material.node_tree.nodes[f"Tint Mask {index}"].image = image
        mesh.materials.clear()
        mesh.materials.append(material)
        return [i.message for i in _validate_unit_shader(obj, weighted) if "tint mask" in i.message.lower()]

    for shader_type, weighted in (("default", False), ("weighted", True), ("weighted_dirtmap", True)):
        partial = tint_issues(shader_type, weighted, "armour_mask1")
        print(f"{shader_type} partial:", partial)
        assert len(partial) == 1 and "Tint Mask 2, Tint Mask 3 empty" in partial[0]
        assert tint_issues(shader_type, weighted, "armour_mask1", "armour_mask2", "armour_mask3") == []
        assert len(tint_issues(shader_type, weighted, "armour_red", "armour_green", "armour_blue")) == 1
    for shader_type in ("weighted_skin", "weighted_skin_dirtmap"):
        assert tint_issues(shader_type, True) == []
        partial = tint_issues(shader_type, True, "head_mask1")
        print(f"{shader_type} partial:", partial)
        assert len(partial) == 1 and "refuses the mesh" in partial[0]
        assert tint_issues(shader_type, True, "head_mask1", "head_mask2", "head_mask3") == []
        assert tint_issues(shader_type, True, "test_black", "test_black", "test_black") == []
        assert len(tint_issues(shader_type, True, "head_rim", "head_sss", "head_back")) == 1
    assert tint_issues("weighted", True) == []


def main() -> None:
    module = addon_utils.enable("total_war_cs2_addon", default_set=True, persistent=False)
    if module is None:
        raise RuntimeError("addon_utils.enable returned failure")

    case_empty_building()
    case_empty_display_collection()
    case_missing_uv_and_material()
    case_missing_collision()
    case_no_uv_map()
    case_valid_minimal()
    case_meshes_in_an_unroled_subcollection()
    case_scaled_flag()
    case_tint_masks()
    case_unit_tint_masks()

    print("=== VALIDATION TEST PASSED (no crashes) ===")


try:
    main()
except Exception:
    print("=== VALIDATION TEST FAILED ===")
    traceback.print_exc()
    sys.exit(1)
