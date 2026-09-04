import sys
import tempfile
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

RAW = ADDON_DIR.parent / "Input/examples/raw_data/gondor_fort_gateway_e/gondor_fort_gateway_e.CS2"
PARSED = ADDON_DIR.parent / "Input/examples/working_data/gondor_fort_gateway_e/gondor_fort_gateway_e_tech.cs2.parsed"
ASSEMBLY_KIT_ROOT = r"D:\SteamLibrary\steamapps\common\Total War Attila\assembly_kit"


def reset() -> None:
    bpy.ops.wm.read_factory_settings(use_empty=True)
    addon_utils.enable("total_war_cs2_addon", default_set=True, persistent=False)
    properties.register()


def all_collections(root):
    yield root
    for child in root.children:
        yield from all_collections(child)


def find_role(root, role):
    return [c for c in all_collections(root) if c.tw_role == role]


def gate_parts(root):
    # Gate objects now live with their own kind: collision volumes in Collision, pathfinding lines
    # in Lines, and the visible meshes in Gate Closed / Gate Open inside Display.
    parts = {}
    for coll in find_role(root, "COLLISION"):
        for obj in coll.objects:
            if obj.tw_collision_type in ("GATE_CLOSED", "GATE_AJAR"):
                parts.setdefault(obj.tw_collision_type, []).append(obj)
    for coll in find_role(root, "LINES"):
        for obj in coll.objects:
            if obj.tw_line_type in ("GATE_CLOSED_HARD", "GATE_AJAR_HARD"):
                parts.setdefault(obj.tw_line_type, []).append(obj)
    for role in ("GATE_CLOSED_DISPLAY", "GATE_OPEN_DISPLAY"):
        for coll in find_role(root, role):
            for obj in coll.objects:
                parts.setdefault(role, []).append(obj)
    return parts


ALL_PARTS = (
    "GATE_CLOSED_DISPLAY",
    "GATE_OPEN_DISPLAY",
    "GATE_CLOSED",
    "GATE_AJAR",
    "GATE_CLOSED_HARD",
    "GATE_AJAR_HARD",
)


def test_cs2_import_and_reexport() -> None:
    print("=== gates: .CS2 import + re-export ===")
    reset()
    building_coll, warnings = import_cs2(str(RAW), bpy.context)

    for w in warnings:
        assert "gate" not in w.lower() or "anim" in w.lower(), f"a non-animation gate node was skipped: {w}"

    gate_display_colls = find_role(building_coll, "GATE_CLOSED_DISPLAY") + find_role(building_coll, "GATE_OPEN_DISPLAY")
    print(f"  {len(gate_display_colls)} gate Display sub-collection(s)")
    assert len(gate_display_colls) == 4, f"expected Gate Closed + Gate Open per destruct level, got {len(gate_display_colls)}"
    for coll in gate_display_colls:
        parent = next(c for c in all_collections(building_coll) if coll.name in [x.name for x in c.children])
        assert parent.tw_role == "DISPLAY", f"'{coll.name}' is not inside a Display collection"

    parts = gate_parts(building_coll)
    for part in ALL_PARTS:
        assert part in parts, f"no imported object for gate part {part}"
        print(f"  {part:20s} {[o.name for o in parts[part]]}")

    assert all(o.type == "MESH" for p in ("GATE_CLOSED_DISPLAY", "GATE_OPEN_DISPLAY", "GATE_CLOSED", "GATE_AJAR") for o in parts[p])
    assert all(o.type == "CURVE" for p in ("GATE_CLOSED_HARD", "GATE_AJAR_HARD") for o in parts[p])
    assert all(o.data.materials for o in parts["GATE_CLOSED_DISPLAY"] + parts["GATE_OPEN_DISPLAY"]), "gate display meshes lost their material"
    assert all(o.data.splines[0].use_cyclic_u for p in ("GATE_CLOSED_HARD", "GATE_AJAR_HARD") for o in parts[p]), "gate lines must be closed loops"

    # The gate piece has no plain collision or LOD mesh of its own, so no placeholder may be invented.
    for coll in find_role(building_coll, "COLLISION"):
        for obj in coll.objects:
            if obj.tw_collision_type == "COLLISION":
                assert "gate" not in obj.name.lower(), f"'{obj.name}' was imported as a plain collision volume"

    # Imported gate geometry is local + a scene-node transform; the placed world position is what
    # has to survive, so compare world-space bounds against the source's full transform.
    source = read_cs2(RAW.read_bytes())
    scene_nodes = {n.name: n for n in source.scene_root.scene_nodes}
    closed = next(o for o in parts["GATE_CLOSED"] if "destruct01" in o.name)
    world = [closed.matrix_world @ v.co for v in closed.data.vertices]
    engine_bounds = [
        (round(min(v[axis] for v in world), 2), round(max(v[axis] for v in world), 2)) for axis in (0, 2, 1)
    ]
    print(f"  destruct01 closed collision world bounds (engine order) {engine_bounds}")
    assert engine_bounds == [(-4.5, 4.5), (0.0, 8.1), (1.75, 2.35)], "gate collision landed in the wrong place"

    with tempfile.TemporaryDirectory() as tmp_dir:
        result = export_building(building_coll, tmp_dir, ASSEMBLY_KIT_ROOT, bpy.context)
        assert result.success, f"export failed: {result.message}"
        doc = read_cs2((Path(tmp_dir) / f"{building_coll.name}.CS2").read_bytes())

    exported = {}
    for node in doc.rigid_models + doc.lines:
        attrs = {a.name: a.value for a in node.attributes.strings}
        cri = attrs.get("class_rigidINFO", "")
        if "gate" in cri:
            exported.setdefault(cri, []).append((node.node_name, attrs))
    print(f"  re-exported gate class_rigidINFO values: {sorted(exported)}")
    for expected in ("gate_closed_lod01", "gate_open_lod01", "collision3d_gate_closed", "collision3d_gate_ajar",
                     "gate_closed_hard01", "gate_ajar_hard01"):
        assert expected in exported, f"gate node '{expected}' was not re-exported"

    for cri, entries in exported.items():
        for node_name, attrs in entries:
            assert node_name.endswith(cri), f"'{node_name}' does not end with its class_rigidINFO '{cri}'"
            is_display = cri.startswith("gate_closed_lod") or cri.startswith("gate_open_lod") or cri.endswith("_anim")
            assert attrs["class_TYPE"] == ("DISPLAY" if is_display else "TECH"), f"{cri} has the wrong class_TYPE"
            assert attrs["graphics_OPTION"] == ("GRAPHICS_HIGH" if is_display else "NOT_GRAPHICS")

    # World placement has to survive the round trip even though the CS2 representation changes
    # from local-geometry-plus-transform to baked-geometry-plus-identity.
    node = next(n for n in doc.rigid_models if n.node_name.endswith("destruct01_collision3d_gate_closed"))
    ps = [v.position for v in node.geometry_chunks[0].vertices]
    baked = [(round(min(p[i] for p in ps), 2), round(max(p[i] for p in ps), 2)) for i in range(3)]
    scene_node = next(n for n in doc.scene_root.scene_nodes if n.name == node.node_name)
    print(f"  re-exported closed collision baked bounds {baked}, translation {[round(v, 3) for v in scene_node.anim.translations[0]]}")
    assert baked == [(-4.5, 4.5), (0.0, 8.1), (1.75, 2.35)], "baked gate geometry is not in world space"
    assert tuple(round(v, 4) for v in scene_node.anim.translations[0]) == (0.0, 0.0, 0.0)
    assert scene_nodes["piece02_destruct01_collision3d_gate_closed"] is not None


def test_parsed_import() -> None:
    print("=== gates: .cs2.parsed import ===")
    reset()
    building_coll, _ = import_cs2_parsed(str(PARSED), bpy.context)

    parts = gate_parts(building_coll)
    for part in ("GATE_CLOSED", "GATE_AJAR", "GATE_CLOSED_HARD", "GATE_AJAR_HARD"):
        assert part in parts, f"no imported object for gate part {part} in the compiled file"
        print(f"  {part:20s} {[o.name for o in parts[part]]}")

    assert all("gate_closed" in o.name for o in parts["GATE_CLOSED"])
    assert all("gate_ajar" in o.name for o in parts["GATE_AJAR"])

    # Compiled bounds are already world space, and BOB derives them from the full node transform.
    closed = next(o for o in parts["GATE_CLOSED"] if "destruct01" in o.name)
    verts = [tuple(v.co) for v in closed.data.vertices]
    engine_bounds = [
        (round(min(v[axis] for v in verts), 2), round(max(v[axis] for v in verts), 2)) for axis in (0, 2, 1)
    ]
    print(f"  destruct01 closed collision bounds (engine order) {engine_bounds}")
    assert engine_bounds == [(-4.5, 4.5), (0.0, 8.1), (1.75, 2.35)]

    for coll in find_role(building_coll, "LINES"):
        for obj in coll.objects:
            if "gate" in obj.name.lower():
                assert obj.tw_line_type in ("GATE_CLOSED_HARD", "GATE_AJAR_HARD"), (
                    f"gate line '{obj.name}' imported as line type '{obj.tw_line_type}'"
                )


def test_authoring() -> None:
    print("=== gates: authoring from scratch ===")
    reset()

    bpy.ops.tw_buildings.new_building(asset_name="Building")
    building_coll = bpy.data.collections["Building"]
    layer = bpy.context.view_layer.layer_collection.children
    bpy.context.view_layer.active_layer_collection = layer[building_coll.name]
    bpy.ops.tw_buildings.new_piece()
    piece_coll = next(c for c in building_coll.children if c.tw_role == "PIECE")
    bpy.context.view_layer.active_layer_collection = layer[building_coll.name].children[piece_coll.name]
    bpy.ops.tw_buildings.new_destruct_level()

    destruct_coll = next(c for c in piece_coll.children if c.tw_role == "DESTRUCT")
    display_coll = next(c for c in destruct_coll.children if c.tw_role == "DISPLAY")
    collision_coll = next(c for c in destruct_coll.children if c.tw_role == "COLLISION")

    def add_cube(target_coll, name, location=(0.0, 0.0, 0.0), material=False):
        bpy.ops.mesh.primitive_cube_add(size=2.0, location=location)
        obj = bpy.context.object
        for c in list(obj.users_collection):
            c.objects.unlink(obj)
        target_coll.objects.link(obj)
        obj.name = name
        obj.data.uv_layers.new(name="UVMap")
        if material:
            obj.active_material = bpy.data.materials.new(name=f"{name}_Material")
            bpy.context.view_layer.objects.active = obj
            bpy.ops.tw_buildings.make_material()
        return obj

    add_cube(display_coll, "Body", material=True)
    add_cube(collision_coll, "BodyCollision").tw_collision_type = "COLLISION"

    destruct_layer = layer[building_coll.name].children[piece_coll.name].children[destruct_coll.name]

    # Gate collision goes in Collision, alongside the ordinary one.
    add_cube(collision_coll, "GateClosedCollision", location=(0.0, 0.0, 3.0)).tw_collision_type = "GATE_CLOSED"
    add_cube(collision_coll, "GateAjarCollision", location=(4.0, 0.0, 3.0)).tw_collision_type = "GATE_AJAR"

    # Gate display meshes go in Gate Closed / Gate Open inside Display.
    bpy.context.view_layer.active_layer_collection = destruct_layer.children[display_coll.name]
    bpy.ops.tw_buildings.add_display_collection(role="GATE_CLOSED_DISPLAY")
    bpy.ops.tw_buildings.add_display_collection(role="GATE_OPEN_DISPLAY")
    gate_closed_coll = next(c for c in display_coll.children if c.tw_role == "GATE_CLOSED_DISPLAY")
    gate_open_coll = next(c for c in display_coll.children if c.tw_role == "GATE_OPEN_DISPLAY")
    add_cube(gate_closed_coll, "GateClosed", location=(0.0, 0.0, 3.0), material=True)
    add_cube(gate_open_coll, "GateOpen", location=(4.0, 0.0, 3.0), material=True)

    # Gate pathfinding lines go in Lines, with their own Line Types.
    bpy.context.view_layer.active_layer_collection = destruct_layer
    bpy.ops.tw_buildings.add_destruct_collection(role="LINES")
    lines_coll = next(c for c in destruct_coll.children if c.tw_role == "LINES")
    for name, line_type, offset in (
        ("GateClosedLine", "GATE_CLOSED_HARD", 0.0),
        ("GateAjarLine", "GATE_AJAR_HARD", 4.0),
    ):
        curve = bpy.data.curves.new(name, type="CURVE")
        curve.dimensions = "3D"
        spline = curve.splines.new("POLY")
        spline.use_cyclic_u = True
        spline.points.add(3)
        for index, (x, y) in enumerate(((-1, -1), (1, -1), (1, 1), (-1, 1))):
            spline.points[index].co = (x + offset, y, 0.0, 1.0)
        obj = bpy.data.objects.new(name, curve)
        obj.tw_line_type = line_type
        lines_coll.objects.link(obj)

    print(f"  authored gate across Collision ({len(collision_coll.objects)} objs), "
          f"Display ({len(gate_closed_coll.objects)}+{len(gate_open_coll.objects)}), "
          f"Lines ({len(lines_coll.objects)})")

    with tempfile.TemporaryDirectory() as tmp_dir:
        result = export_building(building_coll, tmp_dir, ASSEMBLY_KIT_ROOT, bpy.context)
        assert result.success, f"export failed: {result.message}"
        doc = read_cs2((Path(tmp_dir) / f"{building_coll.name}.CS2").read_bytes())

    by_cri = {}
    for node in doc.rigid_models + doc.lines:
        attrs = {a.name: a.value for a in node.attributes.strings}
        by_cri[attrs.get("class_rigidINFO", "")] = (node, attrs)

    expected = {
        "gate_closed_lod01": "piece01_destruct01_gate_closed_lod01",
        "gate_open_lod01": "piece01_destruct01_gate_open_lod01",
        "collision3d_gate_closed": "piece01_destruct01_collision3d_gate_closed",
        "collision3d_gate_ajar": "piece01_destruct01_collision3d_gate_ajar",
        "gate_closed_hard01": "piece01_destruct01_gate_closed_hard01",
        "gate_ajar_hard01": "piece01_destruct01_gate_ajar_hard01",
    }
    for cri, node_name in expected.items():
        assert cri in by_cri, f"'{cri}' missing from the export"
        assert by_cri[cri][0].node_name == node_name, f"{cri} exported as '{by_cri[cri][0].node_name}', expected '{node_name}'"
        print(f"  {node_name}")

    for cri in ("collision3d_gate_closed", "collision3d_gate_ajar"):
        chunk = by_cri[cri][0].geometry_chunks[0]
        assert chunk.submeshes[0].material_id == -1, f"{cri} should export with material -1"
    for cri in ("gate_closed_lod01", "gate_open_lod01"):
        chunk = by_cri[cri][0].geometry_chunks[0]
        assert chunk.submeshes[0].material_id >= 0, f"{cri} should reference a real material"

    for cri in ("gate_closed_hard01", "gate_ajar_hard01"):
        verts = by_cri[cri][0].geometry_chunks[0].lines[0].vertices
        assert len(verts) == 13, f"{cri} should be a 4-corner closed loop tessellated to 13 verts, got {len(verts)}"


def main() -> None:
    print("=== enabling add-on ===")
    if addon_utils.enable("total_war_cs2_addon", default_set=True, persistent=False) is None:
        raise RuntimeError("addon_utils.enable returned failure")
    properties.register()

    test_cs2_import_and_reexport()
    test_parsed_import()
    test_authoring()

    print("=== ALL GATE TESTS PASSED ===")


if __name__ == "__main__":
    main()
