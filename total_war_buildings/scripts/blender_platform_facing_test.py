import sys
import traceback

import addon_utils
import bpy

REPO_ROOT = r"C:\Users\Khaiali\source\repos\blender_buildings_plugin"
OUTPUT_DIR = r"C:\Users\Khaiali\source\repos\blender_buildings_plugin\total_war_buildings\scripts"
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


def add_flipped_plane(collection, name, location):
    # A quad wound clockwise seen from above, i.e. its face normal points down - the state the
    # reported building was in.
    mesh = bpy.data.meshes.new(name)
    mesh.from_pydata(
        [(-2.0, -2.0, 0.0), (-2.0, 2.0, 0.0), (2.0, 2.0, 0.0), (2.0, -2.0, 0.0)],
        [],
        [(0, 1, 2, 3)],
    )
    mesh.update()
    obj = bpy.data.objects.new(name, mesh)
    obj.location = location
    collection.objects.link(obj)
    return obj


def face_normal_z(obj):
    return [polygon.normal.z for polygon in obj.data.polygons]


def main() -> None:
    module = addon_utils.enable("total_war_buildings", default_set=True, persistent=False)
    if module is None:
        raise RuntimeError("addon_utils.enable returned failure")
    bpy.context.preferences.addons["total_war_buildings"].preferences.assembly_kit_root = ASSEMBLY_KIT_ROOT

    bpy.ops.tw_buildings.new_building()
    building = [c for c in bpy.data.collections if c.tw_role == "BUILDING"][-1]
    building.name = "PlatformFacingTest"

    bpy.context.view_layer.active_layer_collection = active_layer_collection_for(building)
    bpy.ops.tw_buildings.new_piece()
    piece = building.children[-1]
    bpy.context.view_layer.active_layer_collection = active_layer_collection_for(piece)
    bpy.ops.tw_buildings.new_destruct_level()
    destruct = piece.children[-1]

    display = [c for c in destruct.children if c.tw_role == "DISPLAY"][0]
    collision = [c for c in destruct.children if c.tw_role == "COLLISION"][0]
    lod_obj = add_box(display)
    add_uv(lod_obj)
    material = bpy.data.materials.new(name="PlatformFacingTest_Material")
    lod_obj.data.materials.append(material)
    lod_obj.active_material = material
    bpy.ops.tw_buildings.make_material()
    collision_obj = add_box(collision, size=1.1)
    collision_obj.tw_collision_type = "COLLISION"

    bpy.context.view_layer.active_layer_collection = active_layer_collection_for(destruct)
    bpy.ops.tw_buildings.add_destruct_collection(role="PLATFORM")
    platform_collection = [c for c in destruct.children if c.tw_role == "PLATFORM"][0]
    flipped = add_flipped_plane(platform_collection, "FlippedPlatform", (0.0, 0.0, 2.0))
    print("platform face normals in Blender (z):", face_normal_z(flipped))
    if any(z >= 0.0 for z in face_normal_z(flipped)):
        raise RuntimeError("test setup should start with a downward-facing platform")

    print("=== validation warns about the downward-facing platform ===")
    from validation.rules import validate_building

    issues = validate_building(building)
    warnings = [i for i in issues if i.severity == "WARNING" and "pointing downwards" in i.message]
    if not warnings:
        raise RuntimeError("expected a warning about downward-facing platform faces")
    print("  ", warnings[0].message)

    bpy.context.view_layer.active_layer_collection = active_layer_collection_for(building)
    bpy.ops.tw_buildings.export_building(directory=OUTPUT_DIR)

    from binary.cs2_reader import read_cs2

    with open(rf"{OUTPUT_DIR}\{building.name}.CS2", "rb") as f:
        doc = read_cs2(f.read())

    print("=== the exported platform faces up regardless ===")
    up = down = 0
    normals_up = normals_down = 0
    for node in doc.rigid_models:
        class_rigid_info = next((a.value for a in node.attributes.strings if a.name == "class_rigidINFO"), "")
        if not class_rigid_info.startswith("platform"):
            continue
        for chunk in node.geometry_chunks:
            for submesh in chunk.submeshes:
                for tri in submesh.triangles:
                    p = [chunk.vertices[i].position for i in tri]
                    edge1 = [p[1][k] - p[0][k] for k in range(3)]
                    edge2 = [p[2][k] - p[0][k] for k in range(3)]
                    if edge1[2] * edge2[0] - edge1[0] * edge2[2] > 0:
                        up += 1
                    else:
                        down += 1
            for vertex in chunk.vertices:
                if vertex.normal[1] > 0:
                    normals_up += 1
                elif vertex.normal[1] < 0:
                    normals_down += 1
    print(f"  winding-implied normal: UP={up} DOWN={down}")
    print(f"  stored vertex normals:  UP={normals_up} DOWN={normals_down}")
    if down or not up:
        raise RuntimeError(f"exported platform still has {down} downward-facing triangle(s)")
    if normals_down or not normals_up:
        raise RuntimeError(f"exported platform still has {normals_down} downward vertex normal(s)")

    print("=== an already-correct platform is left alone ===")
    bpy.ops.object.select_all(action="DESELECT")
    flipped.select_set(True)
    bpy.context.view_layer.objects.active = flipped
    bpy.ops.object.mode_set(mode="EDIT")
    bpy.ops.mesh.select_all(action="SELECT")
    bpy.ops.mesh.flip_normals()
    bpy.ops.object.mode_set(mode="OBJECT")
    if any(z <= 0.0 for z in face_normal_z(flipped)):
        raise RuntimeError("flipping the test platform should have made it face up")
    issues = validate_building(building)
    if [i for i in issues if "pointing downwards" in i.message]:
        raise RuntimeError("an upward-facing platform should not warn")
    bpy.context.view_layer.active_layer_collection = active_layer_collection_for(building)
    bpy.ops.tw_buildings.export_building(directory=OUTPUT_DIR)
    with open(rf"{OUTPUT_DIR}\{building.name}.CS2", "rb") as f:
        doc2 = read_cs2(f.read())
    for node in doc2.rigid_models:
        class_rigid_info = next((a.value for a in node.attributes.strings if a.name == "class_rigidINFO"), "")
        if not class_rigid_info.startswith("platform"):
            continue
        for chunk in node.geometry_chunks:
            for submesh in chunk.submeshes:
                for tri in submesh.triangles:
                    p = [chunk.vertices[i].position for i in tri]
                    edge1 = [p[1][k] - p[0][k] for k in range(3)]
                    edge2 = [p[2][k] - p[0][k] for k in range(3)]
                    if edge1[2] * edge2[0] - edge1[0] * edge2[2] <= 0:
                        raise RuntimeError("an already-correct platform came out downward-facing")
    print("  still up-facing, no warning")

    print("=== the .CS2 importer flips a platform that faces down in the file ===")
    from binary.cs2_writer import write_cs2

    with open(rf"{OUTPUT_DIR}\{building.name}.CS2", "rb") as f:
        downward_doc = read_cs2(f.read())
    for node in downward_doc.rigid_models:
        class_rigid_info = next((a.value for a in node.attributes.strings if a.name == "class_rigidINFO"), "")
        if not class_rigid_info.startswith("platform"):
            continue
        for chunk in node.geometry_chunks:
            for submesh in chunk.submeshes:
                submesh.triangles = [(c, b, a) for a, b, c in submesh.triangles]
            for vertex in chunk.vertices:
                vertex.normal = tuple(-component for component in vertex.normal)
    downward_path = rf"{OUTPUT_DIR}\PlatformFacingDownward.CS2"
    with open(downward_path, "wb") as f:
        f.write(write_cs2(downward_doc))

    before_cs2 = set(bpy.data.collections)
    bpy.ops.tw_buildings.import_file(filepath=downward_path)
    cs2_up = cs2_down = 0
    for coll in bpy.data.collections:
        if coll in before_cs2 or coll.tw_role != "PLATFORM":
            continue
        for platform_obj in coll.objects:
            for polygon in platform_obj.data.polygons:
                if polygon.normal.z > 0:
                    cs2_up += 1
                else:
                    cs2_down += 1
    print(f"  imported into Blender: UP={cs2_up} DOWN={cs2_down}")
    if cs2_down or not cs2_up:
        raise RuntimeError(f".CS2 import produced {cs2_down} downward-facing platform face(s)")

    print("=== a real platform turned upright by its scene node is left alone ===")
    # gondor_fort_gateway_e's piece04 platform is wound downwards in its own geometry and stood up
    # by a 180-degree scene-node rotation, so an import-side flip judged on local geometry alone
    # would break a file that was already correct.
    real_path = rf"{REPO_ROOT}\Input\examples\raw_data\gondor_fort_gateway_e\gondor_fort_gateway_e.CS2"
    before_real = set(bpy.data.collections)
    bpy.ops.tw_buildings.import_file(filepath=real_path)
    real_building = [c for c in bpy.data.collections if c.tw_role == "BUILDING" and c not in before_real][-1]
    for coll in bpy.data.collections:
        if coll in before_real or coll.tw_role != "PLATFORM":
            continue
        for platform_obj in coll.objects:
            for polygon in platform_obj.data.polygons:
                world_normal = platform_obj.matrix_world.to_3x3() @ polygon.normal
                if world_normal.z <= 0.0:
                    raise RuntimeError(f"'{platform_obj.name}' imported facing down in world space")
    if [i for i in validate_building(real_building) if "pointing downwards" in i.message]:
        raise RuntimeError("a real building's platforms should need no flipping after import")
    print("  all real platforms face up in world space, with nothing flipped")

    print("=== the cs2.parsed importer builds platforms the right way up ===")
    # This is where the reported building's downward platforms actually came from: _to_blender_space
    # is a reflection, so keeping the file's vertex order built every platform face upside down.
    from binary.cs2_parsed_reader import CS2ParsedReader

    parsed_path = rf"{REPO_ROOT}\Input\examples\working_data\gondor_fort_tower_c_straight\gondor_fort_tower_c_straight_tech.cs2.parsed"
    with open(parsed_path, "rb") as f:
        parsed_doc = CS2ParsedReader.read_bytes(f.read())
    source_up = 0
    for parsed_piece in parsed_doc.pieces:
        for parsed_destruct in parsed_piece.destructs:
            for poly in (parsed_destruct.platform.polygons if parsed_destruct.platform else []):
                v = poly.vertices
                area = sum(v[i][0] * v[(i + 1) % len(v)][2] - v[(i + 1) % len(v)][0] * v[i][2] for i in range(len(v)))
                if area < 0:
                    source_up += 1
    print(f"  source file has {source_up} up-facing platform polygons")

    before = set(bpy.data.collections)
    bpy.ops.tw_buildings.import_file(filepath=parsed_path)
    imported_up = imported_down = 0
    for coll in bpy.data.collections:
        if coll in before or coll.tw_role != "PLATFORM":
            continue
        for platform_obj in coll.objects:
            if platform_obj.type != "MESH":
                continue
            for polygon in platform_obj.data.polygons:
                if polygon.normal.z > 0:
                    imported_up += 1
                else:
                    imported_down += 1
    print(f"  imported into Blender: UP={imported_up} DOWN={imported_down}")
    if imported_down or not imported_up:
        raise RuntimeError(f"cs2.parsed import produced {imported_down} downward-facing platform face(s)")

    imported_building = [c for c in bpy.data.collections if c.tw_role == "BUILDING" and c not in before][-1]
    if [i for i in validate_building(imported_building) if "pointing downwards" in i.message]:
        raise RuntimeError("a freshly cs2.parsed-imported building should need no platform flipping")
    print("  no downward-platform warning, so the export-side flip never has to fire")

    print("=== the cs2.parsed importer flips a polygon that faces down in the file ===")
    from importer.cs2_parsed_importer import _build_combined_platform_mesh

    class _Polygon:
        def __init__(self, vertices):
            self.vertices = vertices

    # Engine space, wound so the compiled polygon's normal points down - the state the .cs2.parsed
    # importer used to carry straight through into Blender as an upside-down platform.
    downward_polygon = _Polygon([(0.0, 0.0, 0.0), (2.0, 0.0, 0.0), (2.0, 0.0, 2.0), (0.0, 0.0, 2.0)])
    mesh_data, downward_count = _build_combined_platform_mesh("DownwardParsedPlatform", [downward_polygon])
    if downward_count != 1:
        raise RuntimeError("the downward polygon should have been reported as facing down in the file")
    if any(polygon.normal.z <= 0.0 for polygon in mesh_data.polygons):
        raise RuntimeError("a downward .cs2.parsed platform polygon should import facing up")
    print("  imported facing up and reported once")

    print("=== PLATFORM FACING TEST PASSED ===")


try:
    main()
except Exception:
    print("=== PLATFORM FACING TEST FAILED ===")
    traceback.print_exc()
    sys.exit(1)
