import re
import sys
import traceback

import addon_utils
import bpy

REPO_ROOT = r"C:\Users\Khaiali\source\repos\blender_buildings_plugin"
OUTPUT_DIR = r"C:\Users\Khaiali\source\repos\blender_buildings_plugin\total_war_cs2_addon\scripts"
ASSEMBLY_KIT_ROOT = r"D:\SteamLibrary\steamapps\common\Total War Attila\assembly_kit"

if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)


def active_layer_collection_for(collection):
    def find(layer_collection):
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


def add_box(collection, size=1.0):
    bpy.ops.mesh.primitive_cube_add(size=size)
    obj = bpy.context.active_object
    for coll in list(obj.users_collection):
        coll.objects.unlink(obj)
    collection.objects.link(obj)
    return obj


def add_uv(obj):
    bpy.context.view_layer.objects.active = obj
    obj.select_set(True)
    bpy.ops.object.mode_set(mode="EDIT")
    bpy.ops.mesh.select_all(action="SELECT")
    bpy.ops.uv.smart_project()
    bpy.ops.object.mode_set(mode="OBJECT")


def add_plane(collection, size=2.0):
    bpy.ops.mesh.primitive_plane_add(size=size)
    obj = bpy.context.active_object
    for coll in list(obj.users_collection):
        coll.objects.unlink(obj)
    collection.objects.link(obj)
    return obj


def add_edge(collection, start, end, name):
    mesh = bpy.data.meshes.new(name)
    mesh.from_pydata([start, end], [(0, 1)], [])
    mesh.update()
    obj = bpy.data.objects.new(name, mesh)
    collection.objects.link(obj)
    return obj


def cross(a, b):
    return (a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0])


def sub(a, b):
    return tuple(x - y for x, y in zip(a, b))


def dot(a, b):
    return sum(x * y for x, y in zip(a, b))


def parse_udp_vec(text):
    return tuple(float(v) for v in re.findall(r'"([-0-9.eE+]+)"', text))


# BOB's own axis swap, applied to the Max-space vectors in a node's user_defined_properties text.
def bob_swap(vector):
    x, y, z = vector
    return (x, z, y)


def main() -> None:
    module = addon_utils.enable("total_war_cs2_addon", default_set=True, persistent=False)
    if module is None:
        raise RuntimeError("addon_utils.enable returned failure")

    bpy.context.preferences.addons["total_war_cs2_addon"].preferences.assembly_kit_root = ASSEMBLY_KIT_ROOT

    bpy.ops.tw_buildings.new_building()
    building = [c for c in bpy.data.collections if c.tw_role == "BUILDING"][-1]
    building.name = "EngineSpaceTest"

    bpy.context.view_layer.active_layer_collection = active_layer_collection_for(building)
    bpy.ops.tw_buildings.new_piece()
    piece = building.children[-1]
    bpy.context.view_layer.active_layer_collection = active_layer_collection_for(piece)
    bpy.ops.tw_buildings.new_destruct_level()
    destruct = piece.children[-1]

    display = [c for c in destruct.children if c.tw_role == "DISPLAY"][0]
    collision = [c for c in destruct.children if c.tw_role == "COLLISION"][0]

    lod_obj = add_box(display)
    # Deliberately asymmetric on every axis, so a mirrored or transposed export cannot pass.
    lod_obj.location = (3.0, 7.0, 11.0)
    add_uv(lod_obj)
    material = bpy.data.materials.new(name="EngineSpaceTest_Material")
    lod_obj.data.materials.append(material)
    lod_obj.active_material = material
    bpy.ops.tw_buildings.make_material()

    collision_obj = add_box(collision, size=1.1)
    collision_obj.location = (3.0, 7.0, 11.0)
    collision_obj.tw_collision_type = "COLLISION"

    # A platform the EFLine has to sit inside, offset on Blender Y - the axis whose sign was wrong.
    bpy.context.view_layer.active_layer_collection = active_layer_collection_for(destruct)
    bpy.ops.tw_buildings.add_destruct_collection(role="PLATFORM")
    platform_collection = [c for c in destruct.children if c.tw_role == "PLATFORM"][0]
    platform_obj = add_plane(platform_collection, size=4.0)
    platform_obj.location = (0.0, 6.0, 2.0)

    bpy.context.view_layer.active_layer_collection = active_layer_collection_for(destruct)
    bpy.ops.tw_buildings.add_destruct_collection(role="EF_LINES")
    ef_collection = [c for c in destruct.children if c.tw_role == "EF_LINES"][0]
    ef_start = (-1.0, 6.0, 2.0)
    ef_end = (1.0, 6.0, 2.0)
    add_edge(ef_collection, ef_start, ef_end, "EFLine")

    bpy.context.view_layer.active_layer_collection = active_layer_collection_for(building)
    bpy.ops.tw_buildings.export_building(directory=OUTPUT_DIR)

    from binary.cs2_reader import read_cs2

    with open(rf"{OUTPUT_DIR}\{building.name}.CS2", "rb") as f:
        doc = read_cs2(f.read())

    nodes = {n.node_name: n for n in doc.rigid_models}
    scene_nodes = {n.name: n for n in doc.scene_root.scene_nodes}

    print("=== display geometry lands at the Max-convention engine position ===")
    lod = nodes["piece01_destruct01_lod01"]
    positions = [v.position for c in lod.geometry_chunks for v in c.vertices]
    centre = tuple(sum(p[k] for p in positions) / len(positions) for k in range(3))
    expected_centre = (3.0, 11.0, 7.0)
    print("  lod centre:", [round(v, 4) for v in centre], "expected:", expected_centre)
    for got, want in zip(centre, expected_centre):
        if abs(got - want) > 0.01:
            raise RuntimeError(f"Blender (3, 7, 11) should export as engine {expected_centre}, got {centre}")

    print("=== exported triangles wind CCW against their own normals, as real samples do ===")
    agree = disagree = 0
    for chunk in lod.geometry_chunks:
        for submesh in chunk.submeshes:
            for tri in submesh.triangles:
                v = [chunk.vertices[i] for i in tri]
                geometric = cross(sub(v[1].position, v[0].position), sub(v[2].position, v[0].position))
                averaged = tuple(sum(x.normal[k] for x in v) / 3 for k in range(3))
                if dot(geometric, averaged) > 0.0:
                    agree += 1
                else:
                    disagree += 1
    print(f"  CCW-consistent: {agree}, inverted: {disagree}")
    if disagree or not agree:
        raise RuntimeError(f"{disagree} exported triangles are wound against their normals")

    print("=== EFLine UDP carries raw Blender coordinates, not engine ones ===")
    ef_node = nodes["EFline_piece01_destruct01_line01"]
    udp = dict(line.split(" = ", 1) for line in ef_node.user_defined_properties.split(chr(13) + chr(10)) if line)
    udp_start = parse_udp_vec(udp["EFLine_Info"])
    udp_end = parse_udp_vec(udp["EFLine_Info_End"])
    print("  EFLine_Info:", udp_start, "expected:", ef_start)
    for got, want in zip(udp_start, ef_start):
        if abs(got - want) > 0.001:
            raise RuntimeError(f"EFLine_Info should hold Blender-space {ef_start}, got {udp_start}")
    for got, want in zip(udp_end, ef_end):
        if abs(got - want) > 0.001:
            raise RuntimeError(f"EFLine_Info_End should hold Blender-space {ef_end}, got {udp_end}")

    print("=== BOB's reading of that text lands inside the exported platform ===")
    platform = nodes["piece01_destruct01_platform01"]
    platform_positions = [v.position for c in platform.geometry_chunks for v in c.vertices]
    bounds = [(min(p[k] for p in platform_positions), max(p[k] for p in platform_positions)) for k in range(3)]
    print("  platform engine bounds:", [(round(lo, 3), round(hi, 3)) for lo, hi in bounds])
    for label, point in (("start", udp_start), ("end", udp_end)):
        engine_point = bob_swap(point)
        print(f"  EFLine {label} as BOB sees it:", [round(v, 3) for v in engine_point])
        for axis, (lo, hi) in enumerate(bounds):
            if not (lo - 0.001 <= engine_point[axis] <= hi + 0.001):
                raise RuntimeError(
                    f"EFLine {label} {engine_point} falls outside the platform on axis {axis} ({lo}..{hi}) - "
                    "this is the mismatch BOB reports as \"couldn't find platform for efline\""
                )

    print("=== EFLine node shape matches real samples ===")
    chunk = ef_node.geometry_chunks[0]
    if chunk.submeshes:
        raise RuntimeError("EFLine chunks carry no submeshes in real samples")
    if chunk.vertex_color_channel_flags != 0:
        raise RuntimeError("EFLine chunks carry vertex_color_channel_flags 0 in real samples")
    lower, upper = chunk.bounding_boxes[0]
    if abs(upper[0] - 1.0) > 0.001 or abs(lower[0] + 1.0) > 0.001:
        raise RuntimeError(f"EFLine bounding box should be the line's own half-extent, got {lower} {upper}")
    ef_scene_node = scene_nodes["EFline_piece01_destruct01_line01"]
    translation = ef_scene_node.anim.translations[0]
    expected_translation = (0.0, 2.0, 6.0)
    print("  scene node translation:", [round(v, 3) for v in translation], "expected:", expected_translation)
    for got, want in zip(translation, expected_translation):
        if abs(got - want) > 0.001:
            raise RuntimeError(f"EFLine scene node should sit at the line midpoint {expected_translation}, got {translation}")
    if ef_scene_node.target_linkage_name != ef_node.user_defined_properties:
        raise RuntimeError("EFLine scene node should repeat the node's user_defined_properties, as real samples do")

    print("=== ENGINE SPACE TEST PASSED ===")


try:
    main()
except Exception:
    print("=== ENGINE SPACE TEST FAILED ===")
    traceback.print_exc()
    sys.exit(1)
