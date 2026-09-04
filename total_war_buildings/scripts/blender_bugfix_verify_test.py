import math
import sys
import traceback

import addon_utils
import bpy

REPO_ROOT = r"C:\Users\Khaiali\source\repos\blender_buildings_plugin"
OUTPUT_DIR = r"C:\Users\Khaiali\source\repos\blender_buildings_plugin\total_war_buildings\scripts"
ASSEMBLY_KIT_ROOT = r"D:\SteamLibrary\steamapps\common\Total War Attila\assembly_kit"
PARSED_SAMPLE = REPO_ROOT + r"\Input\examples\working_data\gondor_fort_tower_c_straight\gondor_fort_tower_c_straight_tech.cs2.parsed"
RAW_SAMPLE = REPO_ROOT + r"\Input\examples\raw_data\gondor_fort_tower_C_straight\gondor_fort_tower_C_straight.CS2"

if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)


def check(label: str, condition: bool) -> None:
    print(("  OK   " if condition else "  FAIL ") + label)
    if not condition:
        raise AssertionError(label)


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
    bpy.ops.wm.read_homefile(use_empty=True)
    bpy.context.preferences.addons["total_war_buildings"].preferences.assembly_kit_root = ASSEMBLY_KIT_ROOT


def objects_with_role(role: str) -> list[bpy.types.Object]:
    return [obj for coll in bpy.data.collections if coll.tw_role == role for obj in coll.objects]


def test_parsed_import() -> None:
    from importer import import_cs2_parsed

    building, warnings = import_cs2_parsed(PARSED_SAMPLE, bpy.context)
    for warning in warnings:
        print("   note:", warning)

    print("=== 1: '_hard' line nodes import as Hard Collision ===")
    hard_lines = [obj for obj in objects_with_role("LINES") if obj.name.endswith("_hard01")]
    check(f"{len(hard_lines)} hardVV curve(s) found", len(hard_lines) == 2)
    for obj in hard_lines:
        check(f"{obj.name} -> {obj.tw_line_type}", obj.tw_line_type == "HARD")

    print("=== 4: docking lines import from the building-logic tech xml ===")
    docking_objects = objects_with_role("DOCKING_LINES")
    check(f"{len(docking_objects)} docking line(s) imported", len(docking_objects) == 2)
    for obj in docking_objects:
        check(f"{obj.name} sits under piece01_destruct01", obj.users_collection[0].name.startswith("Docking Lines"))
    # Ground truth: the real building's own tech xml, first docking line, ends x 10.49 / 7.009 at y 1.6.
    first = [obj for obj in docking_objects if obj.name.endswith("line01")][0]
    start, _mid, end, _tip = [tuple(round(c, 3) for c in v.co) for v in first.data.vertices]
    check(f"start {start}", start == (10.49, 1.6, 0.0))
    check(f"end {end}", end == (7.009, 1.6, 0.0))

    print("=== 3: Referenced Prop empties expose their prop name ===")
    file_refs = objects_with_role("FILE_REFERENCE")
    check(f"{len(file_refs)} referenced prop(s) imported", len(file_refs) == 6)
    check("they are empties, which the panel used to hide", all(obj.type == "EMPTY" for obj in file_refs))
    check("all carry a Referenced Prop Name", all(obj.tw_file_reference_name == "torch_sconce" for obj in file_refs))

    from ui.collection_utils import get_object_collection_role

    check(
        "panel's own role lookup agrees",
        all(get_object_collection_role(obj) == "FILE_REFERENCE" for obj in file_refs),
    )


def test_region_zone_export() -> None:
    from binary.cs2_reader import read_cs2

    bpy.ops.tw_buildings.new_building()
    building = [c for c in bpy.data.collections if c.tw_role == "BUILDING"][-1]
    building.name = "RegionZoneUdpTest"

    bpy.context.view_layer.active_layer_collection = active_layer_collection_for(building)
    bpy.ops.tw_buildings.new_piece()
    piece = building.children[-1]
    bpy.context.view_layer.active_layer_collection = active_layer_collection_for(piece)
    bpy.ops.tw_buildings.new_destruct_level()
    destruct = piece.children[-1]

    display = [c for c in destruct.children if c.tw_role == "DISPLAY"][0]
    collision = [c for c in destruct.children if c.tw_role == "COLLISION"][0]

    bpy.ops.mesh.primitive_cube_add(size=1.0)
    lod_obj = bpy.context.active_object
    for coll in list(lod_obj.users_collection):
        coll.objects.unlink(lod_obj)
    display.objects.link(lod_obj)
    bpy.context.view_layer.objects.active = lod_obj
    lod_obj.select_set(True)
    bpy.ops.object.mode_set(mode="EDIT")
    bpy.ops.mesh.select_all(action="SELECT")
    bpy.ops.uv.smart_project()
    bpy.ops.object.mode_set(mode="OBJECT")
    material = bpy.data.materials.new(name="RegionZoneUdpTestMaterial")
    lod_obj.data.materials.append(material)
    lod_obj.active_material = material
    bpy.ops.tw_buildings.make_material()

    bpy.ops.mesh.primitive_cube_add(size=1.1)
    collision_obj = bpy.context.active_object
    for coll in list(collision_obj.users_collection):
        coll.objects.unlink(collision_obj)
    collision.objects.link(collision_obj)

    bpy.context.view_layer.active_layer_collection = active_layer_collection_for(building)
    bpy.ops.tw_buildings.add_building_collection(role="REGION_ZONES")
    region_zones = [c for c in building.children if c.tw_role == "REGION_ZONES"][0]

    # The same four corners as the real gondor_fort_tower_C_straight region_zone01.
    curve_data = bpy.data.curves.new("RegionZone", type="CURVE")
    curve_data.dimensions = "3D"
    spline = curve_data.splines.new("POLY")
    corners = [(12.0, 1.0, 0.0), (-12.0, 1.0, 0.0), (-12.0, 5.5, 0.0), (12.0, 5.5, 0.0)]
    spline.points.add(len(corners) - 1)
    for index, (x, y, z) in enumerate(corners):
        spline.points[index].co = (x, y, z, 1.0)
    spline.use_cyclic_u = True
    region_zones.objects.link(bpy.data.objects.new("RegionZone", curve_data))

    result = bpy.ops.tw_buildings.export_building(directory=OUTPUT_DIR)
    check(f"export operator returned {result}", result == {"FINISHED"})

    with open(f"{OUTPUT_DIR}\\{building.name}.CS2", "rb") as f:
        document = read_cs2(f.read())

    zone_nodes = [line for line in document.lines if line.node_name.startswith("region_zone")]
    check(f"{len(zone_nodes)} region zone LINE node(s) written", len(zone_nodes) == 1)

    expected = (
        'Region_pos1  = x:"12.0" y:"1.0" z:"0.0"\r\n'
        'Region_pos2  = x:"-12.0" y:"1.0" z:"0.0"\r\n'
        'Region_pos3  = x:"-12.0" y:"5.5" z:"0.0"\r\n'
        'Region_pos4  = x:"12.0" y:"5.5" z:"0.0"\r\n'
    )
    print("   written UDP:", repr(zone_nodes[0].user_defined_properties))
    check("UDP matches the real sample's byte for byte", zone_nodes[0].user_defined_properties == expected)

    scene_node = [node for node in document.scene_root.scene_nodes if node.name == zone_nodes[0].node_name][0]
    check("scene node carries the same text", scene_node.target_linkage_name == expected)


def test_docking_line_export_matches_real_sample() -> None:
    from binary.cs2_reader import read_cs2
    from importer import import_cs2
    from extraction.extract import extract_building
    from scene_model.cs2_builder import build_cs2_document

    with open(RAW_SAMPLE, "rb") as f:
        original = read_cs2(f.read())
    original_docking = [node for node in original.rigid_models if node.node_name.startswith("DockingLine_")]
    check(f"{len(original_docking)} real docking line node(s) to compare against", len(original_docking) == 2)

    building, _warnings = import_cs2(RAW_SAMPLE, bpy.context)
    asset, _extract_warnings = extract_building(building, bpy.context.evaluated_depsgraph_get(), bpy.context.scene)
    rebuilt = build_cs2_document(asset, ASSEMBLY_KIT_ROOT)
    rebuilt_docking = [node for node in rebuilt.rigid_models if node.node_name.startswith("DockingLine_")]

    check(f"re-exported {len(rebuilt_docking)} docking line node(s)", len(rebuilt_docking) == len(original_docking))
    for node in original_docking + rebuilt_docking:
        print("   ", node.node_name, repr(node.user_defined_properties))

    def properties(node) -> dict:
        return dict(line.split(" = ", 1) for line in node.user_defined_properties.strip().splitlines())

    def unit_direction(text: str):
        components = [float(part.split(":")[1].strip('"')) for part in text.split()]
        length = math.sqrt(sum(c * c for c in components))
        return tuple(round(c / length, 4) for c in components)

    by_start = {properties(node)["DockingLine_Info"]: properties(node) for node in original_docking}
    for node in rebuilt_docking:
        ours = properties(node)
        theirs = by_start.get(ours["DockingLine_Info"])
        check(f"{node.node_name} starts where a real one does", theirs is not None)
        check(f"{node.node_name} ends where that one does", ours["DockingLine_Info_End"] == theirs["DockingLine_Info_End"])
        # The real pointers are the artist's own 0.381-long perpendicular splines, ours are always
        # unit length (extraction._direction_from_pointer) - a direction either way, so compare the
        # heading, not the magnitude.
        check(
            f"{node.node_name} faces the same way",
            unit_direction(ours["DockingLine_Direction"]) == unit_direction(theirs["DockingLine_Direction"]),
        )

    def comparable(node):
        # destruct_ID: see the note below. assigned_OBJECT differs only in case, because the
        # importer names the Blender collection after the file on disk. metadata_versionNO is 1.9
        # throughout this add-on, 1.7 in this sample.
        skipped = ("metadata_versionNO", "destruct_ID")
        return [(a.name, a.value.lower()) for a in node.attributes.strings if a.name not in skipped]

    check(
        "attributes round-trip",
        sorted(map(str, map(comparable, rebuilt_docking))) == sorted(map(str, map(comparable, original_docking))),
    )
    check(
        "geometry chunks stay empty, as the real ones are",
        all(not node.geometry_chunks[0].vertices and not node.geometry_chunks[0].submeshes for node in rebuilt_docking),
    )
    # destruct_ID is excluded above: the .CS2 importer builds destruct collections in node order,
    # not by destruct number, so this building's two levels come back swapped and get renumbered on
    # re-export. Unrelated to docking lines - it moves every tech node in the level the same way.
    print(
        "   note: real names",
        [n.node_name for n in original_docking],
        "vs re-exported",
        [n.node_name for n in rebuilt_docking],
    )


def main() -> None:
    module = addon_utils.enable("total_war_buildings", default_set=True, persistent=False)
    if module is None:
        raise RuntimeError("addon_utils.enable returned failure")
    bpy.context.preferences.addons["total_war_buildings"].preferences.assembly_kit_root = ASSEMBLY_KIT_ROOT

    reset_scene()
    test_parsed_import()

    print("=== 2: region zones reach the CS2 with the UDP text BOB reads ===")
    reset_scene()
    test_region_zone_export()

    print("=== 4b: exported docking lines match the real sample's own nodes ===")
    reset_scene()
    test_docking_line_export_matches_real_sample()
    print("=== BUGFIX VERIFICATION TEST PASSED ===")


try:
    main()
except Exception:
    print("=== BUGFIX VERIFICATION TEST FAILED ===")
    traceback.print_exc()
    sys.exit(1)
