import sys
import tempfile
from collections import Counter
from pathlib import Path

import addon_utils
import bpy

ADDON_DIR = Path(__file__).resolve().parent.parent
if str(ADDON_DIR) not in sys.path:
    sys.path.insert(0, str(ADDON_DIR))

from importer import import_cs2, import_cs2_parsed
from export.exporter import export_building
from binary.cs2_reader import read_cs2
from props import properties

RAW_ROOT = ADDON_DIR.parent / "Input/examples/raw_data"
WORKING_ROOT = ADDON_DIR.parent / "Input/examples/working_data"
ASSEMBLY_KIT_ROOT = r"D:\SteamLibrary\steamapps\common\Total War Attila\assembly_kit"

SENTINEL = 2.5399998984385163e28


def reset() -> None:
    # read_factory_settings unregisters the add-on, so the operators have to come back with it.
    bpy.ops.wm.read_factory_settings(use_empty=True)
    addon_utils.enable("total_war_cs2_addon", default_set=True, persistent=False)
    properties.register()


def curve_point_count(collections, name_fragment) -> int:
    for collection in collections:
        for obj in collection.objects:
            if obj.type == "CURVE" and name_fragment in obj.name:
                return len(obj.data.splines[0].points)
    raise AssertionError(f"no curve matching '{name_fragment}' found")


def all_collections(root):
    yield root
    for child in root.children:
        yield from all_collections(child)


def find_role(root, role):
    return [c for c in all_collections(root) if c.tw_role == role]


def reexport(building_coll, tmp_dir):
    result = export_building(building_coll, tmp_dir, ASSEMBLY_KIT_ROOT, bpy.context)
    assert result.success, f"export failed: {result.message}"
    return read_cs2((Path(tmp_dir) / f"{building_coll.name}.CS2").read_bytes())


def test_vertex_colours() -> None:
    print("=== vertex colours ===")
    reset()
    sample = RAW_ROOT / "gondor_building_5/gondor_building_5.CS2"
    building_coll, _ = import_cs2(str(sample), bpy.context)

    display = find_role(building_coll, "DISPLAY")[0]
    mesh = next(obj for obj in display.objects if obj.type == "MESH").data
    assert mesh.color_attributes, "display mesh imported with no colour attribute"
    imported = [tuple(d.color) for d in mesh.color_attributes[0].data]
    assert any(c != (1.0, 1.0, 1.0, 1.0) for c in imported), "colour attribute is entirely white"
    print(f"  imported {len(imported)} vertex colours, e.g. {tuple(round(v, 3) for v in imported[0])}")

    def position_colour_pairs(doc):
        pairs = Counter()
        for node in doc.rigid_models:
            for chunk in node.geometry_chunks:
                for v in chunk.vertices:
                    pairs[(tuple(round(c, 3) for c in v.position), tuple(round(c, 3) for c in v.color))] += 1
        return pairs

    original = read_cs2(sample.read_bytes())
    with tempfile.TemporaryDirectory() as tmp_dir:
        reexported = reexport(building_coll, tmp_dir)

    source_pairs = position_colour_pairs(original)
    reexported_pairs = position_colour_pairs(reexported)
    colours = {colour for _position, colour in source_pairs}
    print(f"  {len(source_pairs)} distinct (position, colour) pairs, {len(colours)} distinct colours")
    assert colours - {(1.0, 1.0, 1.0, 1.0)}, "this sample has no non-white colours to test with"
    assert reexported_pairs == source_pairs, "vertex colours did not survive the round trip per vertex"


def test_line_tessellation_and_flag() -> None:
    print("=== line de-tessellation, chunk bounds, flag ===")
    reset()
    sample = RAW_ROOT / "gondor_fort_gateway_e/gondor_fort_gateway_e.CS2"
    building_coll, warnings = import_cs2(str(sample), bpy.context)

    assert not any("unrecognized rigid node 'flag'" in w for w in warnings), "flag still skipped"

    lines_colls = find_role(building_coll, "LINES")
    outline_points = curve_point_count(lines_colls, "outline01_hard")
    ground_ad_points = curve_point_count(lines_colls, "ground_ad")
    region_points = curve_point_count(find_role(building_coll, "REGION_ZONES"), "region_zone01")
    print(f"  outline01_hard {outline_points} pts, ground_ad {ground_ad_points} pts, region_zone01 {region_points} pts")
    assert outline_points == 6, f"outline should de-tessellate to 6 authored corners, got {outline_points}"
    assert ground_ad_points == 2, f"ground_ad should de-tessellate to 2 endpoints, got {ground_ad_points}"
    assert region_points == 4, f"region zone should de-tessellate to 4 corners, got {region_points}"

    flag_colls = find_role(building_coll, "FLAG")
    assert len(flag_colls) == 1, f"expected one Flag collection, got {len(flag_colls)}"
    flag_obj = flag_colls[0].objects[0]
    print(f"  flag '{flag_obj.name}' at {tuple(round(v, 3) for v in flag_obj.location)}")
    assert tuple(round(v, 3) for v in flag_obj.location) == (0.0, 3.25, 18.0)

    original = read_cs2(sample.read_bytes())

    def vert_counts(doc, fragment):
        return sorted(
            len(node.geometry_chunks[0].lines[0].vertices)
            for node in doc.lines
            if fragment in node.node_name
        )

    with tempfile.TemporaryDirectory() as tmp_dir:
        reexported = reexport(building_coll, tmp_dir)

    # Node names are renumbered on export, so compare the multiset of vertex counts per family
    # rather than pairing them up by name.
    for fragment in ("outline", "ground_ad", "region_zone"):
        source_counts = vert_counts(original, fragment)
        reexported_counts = vert_counts(reexported, fragment)
        print(f"  {fragment}: source {source_counts} -> re-exported {reexported_counts}")
        assert reexported_counts == source_counts, (
            f"{fragment} re-exported as {reexported_counts}, source had {source_counts}"
        )

    flag_nodes = [n for n in reexported.rigid_models if n.node_name == "flag"]
    assert len(flag_nodes) == 1, "flag node was not re-exported"
    flag_attrs = {a.name: a.value for a in flag_nodes[0].attributes.strings}
    assert flag_attrs["class_rigidINFO"] == "flag"
    assert flag_attrs["class_TYPE"] == "TECH"
    assert flag_attrs["graphics_OPTION"] == "NOT_GRAPHICS"
    flag_scene_node = next(n for n in reexported.scene_root.scene_nodes if n.name == "flag")
    translation = tuple(round(v, 3) for v in flag_scene_node.anim.translations[0])
    print(f"  re-exported flag translation {translation}, {len(flag_nodes[0].geometry_chunks[0].vertices)} verts")
    assert translation == (0.0, 18.0, 3.25), f"flag translation round-tripped as {translation}"

    # Checked directly against 122 real cas2_exporter files (see cs2_builder._rigid_geometry_chunk's
    # comment): only EFLine markers and destruction-debris animation meshes carry real per-vertex
    # bounds in real output at this add-on's own exporter tool version; every other rigid/line node
    # type - including flag and the outline/ground_ad/region_zone lines checked above - carries the
    # sentinel. "_anim" alone would also match gate anim nodes, which are sentinel, so exclude those.
    checked_real = 0
    checked_sentinel = 0
    for node in reexported.rigid_models + reexported.lines:
        real_bounds_expected = node.node_name.lower().startswith("efline_") or (
            "_anim" in node.node_name.lower() and "gate" not in node.node_name.lower()
        )
        for chunk in node.geometry_chunks:
            positions = [v.position for v in getattr(chunk, "vertices", [])]
            positions += [v for line in chunk.lines for v in line.vertices]
            if not positions:
                continue
            lower, upper = chunk.bounding_boxes[0]
            is_sentinel = abs(lower[0]) > SENTINEL / 2
            if real_bounds_expected:
                assert not is_sentinel, f"{node.node_name} should export real bounds, got the sentinel"
                for axis in range(3):
                    assert abs(lower[axis] - min(p[axis] for p in positions)) < 1e-4, f"{node.node_name} bbox min wrong"
                    assert abs(upper[axis] - max(p[axis] for p in positions)) < 1e-4, f"{node.node_name} bbox max wrong"
                checked_real += 1
            else:
                assert is_sentinel, f"{node.node_name} should export the sentinel bounding box, got real bounds"
                checked_sentinel += 1
    print(f"  {checked_real} chunks export real bounds, {checked_sentinel} export the sentinel, matching real cas2_exporter output")


def test_collision_hierarchy_placement() -> None:
    # SceneNode.ParentIndex (the hierarchy-tree parent field, distinct from the damage-link
    # ParentNodeIndex/TargetLinkageName fields it sits next to) is almost always 0 in real samples,
    # but gondor_fort_gateway_e's two flanking-tower collision3d nodes are genuinely authored
    # relative to the main gatehouse collision's transform. A single node's own keyframe in
    # isolation places it 5 units off on one axis; the correct placement requires composing the
    # full ancestor chain. Expected bounds below were independently verified against BOB's own real
    # compiled output (gondor_fort_gateway_e_tech.cs2.parsed) for this exact building.
    print("=== collision hierarchy placement (SceneNode.ParentIndex composition) ===")
    reset()
    sample = RAW_ROOT / "gondor_fort_gateway_e/gondor_fort_gateway_e.CS2"
    building_coll, _warnings = import_cs2(str(sample), bpy.context)

    def world_bounds(obj):
        world = [obj.matrix_world @ v.co for v in obj.data.vertices]
        return tuple((round(min(v[axis] for v in world), 2), round(max(v[axis] for v in world), 2)) for axis in range(3))

    objects_by_name = {obj.name: obj for coll in all_collections(building_coll) for obj in coll.objects}
    piece04 = objects_by_name["piece04_destruct01_collision3d"]
    piece03 = objects_by_name["piece03_destruct01_collision3d"]

    piece04_bounds = world_bounds(piece04)
    piece03_bounds = world_bounds(piece03)
    print(f"  piece04_destruct01_collision3d world bounds: {piece04_bounds}")
    print(f"  piece03_destruct01_collision3d world bounds: {piece03_bounds}")

    # Blender axis order (X, Y, Z); Y is the axis the ancestor composition fixes (engine Z).
    expected = ((9.12, 10.5), (1.03, 3.75), (11.85, 16.76))
    assert piece04_bounds == expected, f"piece04's collision landed at {piece04_bounds}, expected {expected}"
    expected_piece03 = ((-10.5, -9.12), (1.03, 3.75), (11.85, 16.76))
    assert piece03_bounds == expected_piece03, f"piece03's collision landed at {piece03_bounds}, expected {expected_piece03}"


def test_parsed_import() -> None:
    print("=== .cs2.parsed import ===")
    reset()
    sample = WORKING_ROOT / "gondor_fort_tower_c_straight/gondor_fort_tower_c_straight_tech.cs2.parsed"
    building_coll, warnings = import_cs2_parsed(str(sample), bpy.context)
    for w in warnings:
        print(f"  Warning: {w}")
    assert not any("VFX" in w for w in warnings), "VFX nodes should be ignored silently"
    assert not any("Soft collision" in w for w in warnings), "soft collision is supported now"

    flag_colls = find_role(building_coll, "FLAG")
    assert len(flag_colls) == 1, "flag from the .cs2.parsed header was not imported"
    print(f"  flag '{flag_colls[0].objects[0].name}' imported from header")

    pieces = find_role(building_coll, "PIECE")
    parented = [p for p in pieces if p.tw_damage_parent is not None]
    print(f"  {len(parented)} of {len(pieces)} pieces have a Damage Parent")
    assert len(parented) == 2, f"expected 2 damage-parented pieces, got {len(parented)}"

    lines_coll = find_role(building_coll, "LINES")
    line_types = {obj.name: obj.tw_line_type for c in lines_coll for obj in c.objects}
    print(f"  line types: {line_types}")
    assert all(v == "PIPE_WALL_DOOR" for k, v in line_types.items() if "pipe_wall_door" in k)
    assert all(v == "HARD" for k, v in line_types.items() if k.endswith("hard01"))

    for c in lines_coll:
        for obj in c.objects:
            spline = obj.data.splines[0]
            assert not spline.use_cyclic_u, f"'{obj.name}' is an open line but was imported cyclic"
    print("  no open line was forced closed")

    destructs = find_role(building_coll, "DESTRUCT")
    assert any("tw_destruct_index" in d for d in destructs), "destruct index not preserved"
    assert "tw_source_bounding_box" in building_coll, "header bounding box not preserved"


def test_parsed_soft_collision() -> None:
    print("=== .cs2.parsed soft collision ===")
    reset()
    sample = WORKING_ROOT / "gondorean_marchingcamp_table/gondorean_marchingcamp_table_tech.cs2.parsed"
    building_coll, _ = import_cs2_parsed(str(sample), bpy.context)

    soft_objects = [
        obj
        for c in find_role(building_coll, "COLLISION")
        for obj in c.objects
        if obj.tw_collision_type == "SOFT_COLLISION"
    ]
    assert len(soft_objects) == 1, f"expected 1 soft collision cylinder, got {len(soft_objects)}"
    obj = soft_objects[0]
    verts = [tuple(v.co) for v in obj.data.vertices]
    assert len(verts) == 10, f"a 5-sided cylinder needs 10 vertices, got {len(verts)}"
    assert len(obj.data.polygons) == 7, f"a 5-sided cylinder needs 7 faces, got {len(obj.data.polygons)}"
    radius = max((x ** 2 + y ** 2) ** 0.5 for x, y, _ in verts)
    height = max(z for _, _, z in verts) - min(z for _, _, z in verts)
    print(f"  '{obj.name}' radius {radius:.3f}, height {height:.3f}, {len(verts)} verts")
    assert abs(radius - 1.5) < 1e-4, f"radius {radius} does not match the file's 1.5"
    assert abs(height - 2.0) < 1e-4, f"height {height} does not match the file's 2.0"


def test_flag_authoring() -> None:
    print("=== authoring a flag from scratch ===")
    reset()

    bpy.ops.tw_buildings.new_building(asset_name="Building")
    building_coll = bpy.data.collections["Building"]
    layer_children = bpy.context.view_layer.layer_collection.children
    bpy.context.view_layer.active_layer_collection = layer_children[building_coll.name]

    bpy.ops.tw_buildings.new_piece()
    piece_coll = next(c for c in building_coll.children if c.tw_role == "PIECE")
    bpy.context.view_layer.active_layer_collection = layer_children[building_coll.name].children[piece_coll.name]
    bpy.ops.tw_buildings.new_destruct_level()

    destruct_coll = next(c for c in piece_coll.children if c.tw_role == "DESTRUCT")
    display_coll = next(c for c in destruct_coll.children if c.tw_role == "DISPLAY")
    collision_coll = next(c for c in destruct_coll.children if c.tw_role == "COLLISION")

    bpy.ops.mesh.primitive_cube_add(size=2.0)
    cube = bpy.context.object
    for coll in list(cube.users_collection):
        coll.objects.unlink(cube)
    display_coll.objects.link(cube)
    cube.data.uv_layers.new(name="UVMap")
    cube.active_material = bpy.data.materials.new(name="FlagTestMaterial")
    bpy.context.view_layer.objects.active = cube
    bpy.ops.tw_buildings.make_material()

    bpy.ops.mesh.primitive_cube_add(size=2.0)
    collider = bpy.context.object
    for coll in list(collider.users_collection):
        coll.objects.unlink(collider)
    collision_coll.objects.link(collider)
    collider.tw_collision_type = "COLLISION"

    bpy.context.view_layer.active_layer_collection = layer_children[building_coll.name]
    bpy.ops.tw_buildings.add_building_collection(role="FLAG")
    flag_coll = next(c for c in building_coll.children if c.tw_role == "FLAG")
    bpy.context.view_layer.active_layer_collection = layer_children[building_coll.name].children[flag_coll.name]

    bpy.ops.tw_buildings.new_flag()
    flag_obj = flag_coll.objects[0]
    flag_obj.location = (1.0, 2.0, 7.0)
    print(f"  authored '{flag_obj.name}' at {tuple(flag_obj.location)}")

    result = bpy.ops.tw_buildings.new_flag()
    assert result == {"CANCELLED"}, "a second flag should be refused"

    with tempfile.TemporaryDirectory() as tmp_dir:
        doc = reexport(building_coll, tmp_dir)

    flag_nodes = [n for n in doc.rigid_models if n.node_name == "flag"]
    assert len(flag_nodes) == 1, f"expected one exported flag node, got {len(flag_nodes)}"
    chunk = flag_nodes[0].geometry_chunks[0]
    assert chunk.submeshes[0].material_id == -1, "flag should export with material -1, like collision/platform"
    scene_node = next(n for n in doc.scene_root.scene_nodes if n.name == "flag")
    translation = tuple(round(v, 3) for v in scene_node.anim.translations[0])
    print(f"  exported flag translation {translation}, {len(chunk.vertices)} verts")
    assert translation == (1.0, 7.0, 2.0), f"flag translation exported as {translation}"
    local_bounds = [
        (round(min(v.position[axis] for v in chunk.vertices), 3), round(max(v.position[axis] for v in chunk.vertices), 3))
        for axis in range(3)
    ]
    print(f"  flag local bounds {local_bounds}")
    assert local_bounds == [(-0.25, 0.25), (0.0, 1.0), (-0.25, 0.25)], "flag geometry is not the real 0.5x0.5x1.0 box"


def main() -> None:
    print("=== enabling add-on ===")
    if addon_utils.enable("total_war_cs2_addon", default_set=True, persistent=False) is None:
        raise RuntimeError("addon_utils.enable returned failure")
    properties.register()

    test_vertex_colours()
    test_line_tessellation_and_flag()
    test_collision_hierarchy_placement()
    test_parsed_import()
    test_parsed_soft_collision()
    test_flag_authoring()

    print("=== ALL IMPORT FIDELITY TESTS PASSED ===")


if __name__ == "__main__":
    main()
