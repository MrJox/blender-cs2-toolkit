import sys
import traceback

import addon_utils
import bpy

REPO_ROOT = r"C:\Users\Khaiali\source\repos\blender_buildings_plugin"
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


def add_box(collection: bpy.types.Collection, size: float = 1.0) -> bpy.types.Object:
    bpy.ops.mesh.primitive_cube_add(size=size)
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


def add_poly_curve(collection: bpy.types.Collection, points: list[tuple[float, float, float]], cyclic: bool, name: str) -> bpy.types.Object:
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


def main() -> None:
    module = addon_utils.enable("total_war_buildings", default_set=True, persistent=False)
    if module is None:
        raise RuntimeError("addon_utils.enable returned failure")

    prefs = bpy.context.preferences.addons["total_war_buildings"].preferences
    prefs.assembly_kit_root = ASSEMBLY_KIT_ROOT

    print("=== building / piece / destruct ===")
    bpy.ops.tw_buildings.new_building()
    building = [c for c in bpy.data.collections if c.tw_role == "BUILDING"][-1]
    building.name = "BobTestLinesArrows"

    bpy.context.view_layer.active_layer_collection = active_layer_collection_for(building)
    bpy.ops.tw_buildings.new_piece()
    piece = building.children[-1]

    bpy.context.view_layer.active_layer_collection = active_layer_collection_for(piece)
    bpy.ops.tw_buildings.new_destruct_level()
    destruct = piece.children[-1]

    display = [c for c in destruct.children if c.tw_role == "DISPLAY"][0]
    collision = [c for c in destruct.children if c.tw_role == "COLLISION"][0]

    lod_obj = add_box(display, size=3.0)
    add_uv(lod_obj)
    _mat_obj = bpy.context.active_object
    _material = bpy.data.materials.new(name=f"{_mat_obj.name}_Material")
    _mat_obj.data.materials.append(_material)
    _mat_obj.active_material = _material
    bpy.ops.tw_buildings.make_material()

    collision_obj = add_box(collision, size=3.1)
    collision_obj.tw_collision_type = "COLLISION"

    print("=== Lines: Outline (closed square) + Hard (closed square) + Ground AD (closed square) ===")
    bpy.context.view_layer.active_layer_collection = active_layer_collection_for(destruct)
    bpy.ops.tw_buildings.add_destruct_collection(role="LINES")
    lines_collection = [c for c in destruct.children if c.tw_role == "LINES"][0]

    outline_obj = add_poly_curve(
        lines_collection, [(-2, -2, 0), (2, -2, 0), (2, 2, 0), (-2, 2, 0)], cyclic=True, name="Outline"
    )
    outline_obj.tw_line_type = "OUTLINE"

    hard_obj = add_poly_curve(
        lines_collection, [(-2.5, -2.5, 0.5), (2.5, -2.5, 0.5), (2.5, 2.5, 0.5), (-2.5, 2.5, 0.5)], cyclic=True, name="Hard"
    )
    hard_obj.tw_line_type = "HARD"

    ground_ad_obj = add_poly_curve(
        lines_collection, [(-3, -3, 0), (3, -3, 0), (3, 3, 0), (-3, 3, 0)], cyclic=True, name="GroundAD"
    )
    ground_ad_obj.tw_line_type = "GROUND_AD"

    print("=== Arrow Emitters: two, one moved/rotated ===")
    bpy.context.view_layer.active_layer_collection = active_layer_collection_for(destruct)
    bpy.ops.tw_buildings.add_destruct_collection(role="ARROW_EMITTERS")
    arrow_collection = [c for c in destruct.children if c.tw_role == "ARROW_EMITTERS"][0]

    bpy.context.view_layer.active_layer_collection = active_layer_collection_for(arrow_collection)
    bpy.ops.tw_buildings.new_arrow_emitter()
    emitter1 = bpy.context.active_object
    emitter1.location = (0.0, -2.0, 1.5)
    print("emitter1:", emitter1.name, "verts:", len(emitter1.data.vertices))

    bpy.ops.tw_buildings.new_arrow_emitter()
    emitter2 = bpy.context.active_object
    emitter2.location = (2.0, 0.0, 1.5)
    emitter2.rotation_euler = (0.0, 0.0, 1.5708)
    print("emitter2:", emitter2.name, "moved/rotated")

    print("=== validate ===")
    bpy.context.view_layer.active_layer_collection = active_layer_collection_for(building)
    bpy.ops.tw_buildings.validate()

    print("=== export ===")
    result = bpy.ops.tw_buildings.export_building(directory=OUTPUT_DIR)
    print("export operator result:", result)

    from binary.cs2_reader import read_cs2

    exported_path = f"{OUTPUT_DIR}\\{building.name}.CS2"
    with open(exported_path, "rb") as f:
        data = f.read()
    doc = read_cs2(data)
    print("re-parsed OK:", doc.scene_block.rigid_models_count, "rigid,", doc.scene_block.lines_count, "lines")

    line_names = [ln.node_name for ln in doc.lines]
    print("line nodes:", line_names)
    for ln in doc.lines:
        line_data = ln.geometry_chunks[0].lines[0]
        print(
            " ",
            ln.node_name,
            "verts:",
            len(line_data.vertices),
            "segments:",
            [(seg.start_vertex_index, seg.end_vertex_index) for seg in line_data.segments],
        )
        vertex_count = len(line_data.vertices)
        if (vertex_count - 1) % 3 != 0:
            raise RuntimeError(f"{ln.node_name}: vertex count {vertex_count} is not 3*edges+1 (real-sample convention)")
        edge_count = (vertex_count - 1) // 3
        expected_segments = [(3, 0)] * edge_count
        actual = [(seg.start_vertex_index, seg.end_vertex_index) for seg in line_data.segments]
        if actual != expected_segments:
            raise RuntimeError(f"{ln.node_name}: expected {expected_segments}, got {actual}")
        if line_data.vertices[0] != line_data.vertices[-1]:
            raise RuntimeError(f"{ln.node_name}: expected a closed loop (first vertex == last vertex)")

    arrow_names = sorted(rm.node_name for rm in doc.rigid_models if "arrow_emitter" in rm.node_name)
    print("arrow emitter nodes:", arrow_names)
    if arrow_names != ["piece01_destruct01_arrow_emitter01", "piece01_destruct01_arrow_emitter02"]:
        raise RuntimeError(f"Unexpected arrow emitter names: {arrow_names}")

    print("=== BOB TEST FILE BUILT OK ===")


try:
    main()
except Exception:
    print("=== BOB TEST FILE BUILD FAILED ===")
    traceback.print_exc()
    sys.exit(1)
