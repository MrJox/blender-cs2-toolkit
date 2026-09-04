import sys

import addon_utils
import bpy

REPO_ROOT = r"C:\Users\Khaiali\source\repos\blender_buildings_plugin"
OUTPUT_BLEND = r"C:\Users\Khaiali\source\repos\blender_buildings_plugin\total_war_buildings\scripts\example_building.blend"
OUTPUT_DIR = r"C:\Users\Khaiali\source\repos\blender_buildings_plugin\total_war_buildings\scripts"
ASSEMBLY_KIT_ROOT = r"D:\SteamLibrary\steamapps\common\Total War Attila\assembly_kit"

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


def add_box(collection: bpy.types.Collection, size: float = 1.0, location=(0.0, 0.0, 0.0)) -> bpy.types.Object:
    bpy.ops.mesh.primitive_cube_add(size=size, location=location)
    obj = bpy.context.active_object
    for coll in list(obj.users_collection):
        coll.objects.unlink(obj)
    collection.objects.link(obj)
    return obj


def add_plane(collection: bpy.types.Collection, size: float = 2.0, location=(0.0, 0.0, 0.0)) -> bpy.types.Object:
    bpy.ops.mesh.primitive_plane_add(size=size, location=location)
    obj = bpy.context.active_object
    for coll in list(obj.users_collection):
        coll.objects.unlink(obj)
    collection.objects.link(obj)
    return obj


def add_uv(obj: bpy.types.Object) -> None:
    bpy.context.view_layer.objects.active = obj
    obj.select_set(True)
    bpy.ops.object.mode_set(mode="EDIT")
    bpy.ops.mesh.select_all(action="SELECT")
    bpy.ops.uv.smart_project()
    bpy.ops.object.mode_set(mode="OBJECT")


def add_poly_curve(collection: bpy.types.Collection, points, cyclic: bool, name: str) -> bpy.types.Object:
    curve_data = bpy.data.curves.new(name, type="CURVE")
    curve_data.dimensions = "3D"
    spline = curve_data.splines.new("POLY")
    spline.points.add(len(points) - 1)
    for i, (x, y, z) in enumerate(points):
        spline.points[i].co = (x, y, z, 1.0)
    spline.use_cyclic_u = cyclic
    obj = bpy.data.objects.new(name, curve_data)
    collection.objects.link(obj)
    return obj


def add_edge(collection: bpy.types.Collection, start, end, name: str) -> bpy.types.Object:
    mesh = bpy.data.meshes.new(name)
    mesh.from_pydata([start, end], [(0, 1)], [])
    mesh.update()
    obj = bpy.data.objects.new(name, mesh)
    collection.objects.link(obj)
    return obj


def main() -> None:
    module = addon_utils.enable("total_war_buildings", default_set=True, persistent=False)
    if module is None:
        raise RuntimeError("addon_utils.enable returned failure")

    prefs = bpy.context.preferences.addons["total_war_buildings"].preferences
    prefs.assembly_kit_root = ASSEMBLY_KIT_ROOT

    for obj in list(bpy.data.objects):
        bpy.data.objects.remove(obj, do_unlink=True)

    print("=== Building / Piece / Destruct ===")
    bpy.ops.tw_buildings.new_building()
    building = [c for c in bpy.data.collections if c.tw_role == "BUILDING"][-1]
    building.name = "example_display_building"

    bpy.context.view_layer.active_layer_collection = active_layer_collection_for(building)
    bpy.ops.tw_buildings.new_piece()
    piece = building.children[-1]

    bpy.context.view_layer.active_layer_collection = active_layer_collection_for(piece)
    bpy.ops.tw_buildings.new_destruct_level()
    destruct = piece.children[-1]

    display = [c for c in destruct.children if c.tw_role == "DISPLAY"][0]
    collision = [c for c in destruct.children if c.tw_role == "COLLISION"][0]

    print("=== LODs (Display) ===")
    lod1 = add_box(display, size=2.0)
    lod1.name = "lod01"
    lod1.tw_lod_index = "LOD01"
    add_uv(lod1)
    bpy.ops.tw_buildings.make_material()
    lod1.active_material.name = "example_display_building_material"

    lod2 = add_box(display, size=1.8)
    lod2.name = "lod02"
    lod2.tw_lod_index = "LOD02"
    add_uv(lod2)
    lod2.data.materials.append(lod1.active_material)

    print("=== Collision ===")
    collision_obj = add_box(collision, size=2.1)
    collision_obj.name = "collision3d"
    collision_obj.tw_collision_type = "COLLISION"

    print("=== Platform ===")
    bpy.context.view_layer.active_layer_collection = active_layer_collection_for(destruct)
    bpy.ops.tw_buildings.add_destruct_collection(role="PLATFORM")
    platform_collection = [c for c in destruct.children if c.tw_role == "PLATFORM"][0]
    platform_obj = add_plane(platform_collection, size=8.0)
    platform_obj.name = "platform01"

    print("=== Referenced Props (File Reference) ===")
    bpy.context.view_layer.active_layer_collection = active_layer_collection_for(destruct)
    bpy.ops.tw_buildings.add_destruct_collection(role="FILE_REFERENCE")
    file_reference_collection = [c for c in destruct.children if c.tw_role == "FILE_REFERENCE"][0]
    file_reference_obj = add_box(file_reference_collection, size=0.3, location=(1.2, 0.0, 1.0))
    file_reference_obj.name = "torch_sconce"
    add_uv(file_reference_obj)
    bpy.context.view_layer.objects.active = file_reference_obj
    bpy.ops.tw_buildings.make_material()
    file_reference_obj.active_material.name = "torch_sconce_material"
    file_reference_obj.tw_file_reference_name = "torch_sconce"

    print("=== Lines: Outline / Ground AD / Pipe ===")
    bpy.context.view_layer.active_layer_collection = active_layer_collection_for(destruct)
    bpy.ops.tw_buildings.add_destruct_collection(role="LINES")
    lines_collection = [c for c in destruct.children if c.tw_role == "LINES"][0]

    outline_obj = add_poly_curve(
        lines_collection, [(-2, -2, 0), (2, -2, 0), (2, 2, 0), (-2, 2, 0)], cyclic=True, name="outline01"
    )
    outline_obj.tw_line_type = "OUTLINE"

    ground_ad_obj = add_poly_curve(lines_collection, [(-1, 0, 0), (1, 0, 0)], cyclic=False, name="ground_ad")
    ground_ad_obj.tw_line_type = "GROUND_AD"

    pipe_obj = add_poly_curve(lines_collection, [(0, 0, 0), (0, 0, 3)], cyclic=False, name="pipe_ladder01")
    pipe_obj.tw_line_type = "PIPE_LADDER"

    print("=== EFLines (separate tech/collection from Docking Lines) ===")
    bpy.context.view_layer.active_layer_collection = active_layer_collection_for(destruct)
    bpy.ops.tw_buildings.add_destruct_collection(role="EF_LINES")
    ef_lines_collection = [c for c in destruct.children if c.tw_role == "EF_LINES"][0]

    ef_line_obj = add_edge(ef_lines_collection, (-1, 0, 0), (1, 0, 0), "efline01")
    ef_line_obj.tw_efline_action = "LOW_WALL"

    print("=== Docking Lines (separate tech/collection from EFLines) ===")
    bpy.context.view_layer.active_layer_collection = active_layer_collection_for(destruct)
    bpy.ops.tw_buildings.add_destruct_collection(role="DOCKING_LINES")
    docking_lines_collection = [c for c in destruct.children if c.tw_role == "DOCKING_LINES"][0]

    add_edge(docking_lines_collection, (-1, 2, 0), (1, 2, 0), "dockingline01")

    print("=== Region Zones (building-global) ===")
    bpy.context.view_layer.active_layer_collection = active_layer_collection_for(building)
    bpy.ops.tw_buildings.add_building_collection(role="REGION_ZONES")
    region_zones_collection = [c for c in building.children if c.tw_role == "REGION_ZONES"][0]
    add_poly_curve(
        region_zones_collection, [(-6, -6, 0), (6, -6, 0), (6, 6, 0), (-6, 6, 0)], cyclic=True, name="region_zone01"
    )

    print("=== Validate ===")
    bpy.context.view_layer.active_layer_collection = active_layer_collection_for(building)
    bpy.ops.tw_buildings.validate()

    print("=== Export (sanity check only, not the primary deliverable) ===")
    result = bpy.ops.tw_buildings.export_building(directory=OUTPUT_DIR)
    print("export operator result:", result)

    from binary.cs2_reader import read_cs2

    with open(f"{OUTPUT_DIR}\\{building.name}.CS2", "rb") as f:
        data = f.read()
    doc = read_cs2(data)
    print(
        "re-parsed OK:",
        doc.scene_block.rigid_models_count, "rigid,",
        doc.scene_block.lines_count, "lines,",
        doc.scene_block.materials_count, "materials",
    )

    print("=== Save .blend ===")
    bpy.ops.wm.save_as_mainfile(filepath=OUTPUT_BLEND)
    print("Saved to", OUTPUT_BLEND)


main()
