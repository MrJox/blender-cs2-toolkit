import sys
import tempfile
from pathlib import Path

import addon_utils
import bpy

ADDON_DIR = Path(__file__).resolve().parent.parent
if str(ADDON_DIR) not in sys.path:
    sys.path.insert(0, str(ADDON_DIR))

from importer import import_cs2
from export.exporter import export_building
from binary.cs2_reader import read_cs2
from props import properties

RAW = ADDON_DIR.parent / "Input/examples/raw_data/gondor_fort_gateway_e/gondor_fort_gateway_oil_e.CS2"
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


def test_cs2_import_and_reexport() -> None:
    print("=== boiling oil: .CS2 import + re-export ===")
    reset()
    building_coll, warnings = import_cs2(str(RAW), bpy.context)

    for w in warnings:
        assert "oil" not in w.lower() and "boiling" not in w.lower(), f"a boiling oil node was skipped: {w}"

    display_colls = find_role(building_coll, "BOILING_OIL_DISPLAY")
    print(f"  {len(display_colls)} Boiling Oil Display sub-collection(s)")
    assert len(display_colls) == 2, f"expected one Boiling Oil Display collection per destruct level (2), got {len(display_colls)}"
    for coll in display_colls:
        parent = next(c for c in all_collections(building_coll) if coll.name in [x.name for x in c.children])
        assert parent.tw_role == "DISPLAY", f"'{coll.name}' is not inside a Display collection"
        assert coll.name.startswith("Boiling Oil"), f"expected collection named 'Boiling Oil', got '{coll.name}'"

    display_objs = [obj for coll in display_colls for obj in coll.objects]
    print(f"  display objects: {[o.name for o in display_objs]}")
    assert len(display_objs) == 2, f"expected 2 boiling oil display meshes, got {len(display_objs)}"
    assert all(o.type == "MESH" for o in display_objs)
    assert all(o.data.materials for o in display_objs), "boiling oil display meshes lost their material"
    assert all(o.tw_lod_index == "LOD01" for o in display_objs)

    collision_objs = [
        obj for coll in find_role(building_coll, "COLLISION") for obj in coll.objects if obj.tw_collision_type == "BOILING_OIL"
    ]
    print(f"  collision objects: {[o.name for o in collision_objs]}")
    assert len(collision_objs) == 2, f"expected 2 boiling oil collision meshes, got {len(collision_objs)}"
    assert all(o.type == "MESH" and len(o.data.vertices) > 0 for o in collision_objs)

    # piece05 has no plain collision3d or plain lod01 of its own - same shape as a gate piece - so
    # no placeholder may have been invented for it under the plain roles.
    piece05_plain_lods = [o for c in find_role(building_coll, "DISPLAY") for o in c.objects if "piece05" in o.name]
    piece05_plain_collisions = [
        o for c in find_role(building_coll, "COLLISION") for o in c.objects
        if "piece05" in o.name and o.tw_collision_type == "COLLISION"
    ]
    assert not piece05_plain_lods, f"piece05 should have no plain Display mesh, found {[o.name for o in piece05_plain_lods]}"
    assert not piece05_plain_collisions, f"piece05 should have no plain collision, found {[o.name for o in piece05_plain_collisions]}"

    with tempfile.TemporaryDirectory() as tmp_dir:
        result = export_building(building_coll, tmp_dir, ASSEMBLY_KIT_ROOT, bpy.context)
        assert result.success, f"export failed: {result.message}"
        doc = read_cs2((Path(tmp_dir) / f"{building_coll.name}.CS2").read_bytes())

    exported = {}
    for node in doc.rigid_models:
        attrs = {a.name: a.value for a in node.attributes.strings}
        cri = attrs.get("class_rigidINFO", "")
        if "boiling_oil" in cri:
            exported.setdefault(cri, []).append((node.node_name, attrs))
    print(f"  re-exported class_rigidINFO values: {sorted(exported)}")
    for expected in ("boiling_oil_lod01", "collision3d_boiling_oil"):
        assert expected in exported, f"'{expected}' was not re-exported"
        assert len(exported[expected]) == 2, f"expected 2 destruct levels' worth of '{expected}', got {len(exported[expected])}"

    for cri, entries in exported.items():
        is_display = cri.startswith("boiling_oil_lod")
        for node_name, attrs in entries:
            assert node_name.endswith(cri), f"'{node_name}' does not end with its class_rigidINFO '{cri}'"
            assert attrs["class_TYPE"] == ("DISPLAY" if is_display else "TECH"), f"{cri} has the wrong class_TYPE"
            assert attrs["graphics_OPTION"] == ("GRAPHICS_HIGH" if is_display else "NOT_GRAPHICS")

    coll_node = next(n for n in doc.rigid_models if n.node_name.endswith("collision3d_boiling_oil") and "destruct01" in n.node_name)
    assert coll_node.geometry_chunks[0].submeshes[0].material_id == -1, "boiling oil collision should export with material -1"
    lod_node = next(n for n in doc.rigid_models if n.node_name.endswith("boiling_oil_lod01") and "destruct01" in n.node_name)
    assert lod_node.geometry_chunks[0].submeshes[0].material_id >= 0, "boiling oil display should reference a real material"

    # Confirmed sentinel bounding box (see cs2_builder._rigid_geometry_chunk's comment) for both.
    from binary import cs2_templates as t
    for node in (coll_node, lod_node):
        assert node.geometry_chunks[0].bounding_boxes[0] == t.GEOMETRY_CHUNK_BOUNDING_BOX_SENTINEL, (
            f"'{node.node_name}' should export the sentinel bounding box"
        )


def test_authoring() -> None:
    print("=== boiling oil: authoring from scratch ===")
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

    add_cube(collision_coll, "BoilingOilCollision", location=(0.0, 0.0, 3.0)).tw_collision_type = "BOILING_OIL"

    bpy.context.view_layer.active_layer_collection = destruct_layer.children[display_coll.name]
    bpy.ops.tw_buildings.add_display_collection(role="BOILING_OIL_DISPLAY")
    boiling_oil_coll = next(c for c in display_coll.children if c.tw_role == "BOILING_OIL_DISPLAY")
    add_cube(boiling_oil_coll, "BoilingOilDisplay", location=(0.0, 0.0, 3.0), material=True)

    print(f"  authored boiling oil across Collision ({len(collision_coll.objects)} objs), "
          f"Display ({len(boiling_oil_coll.objects)})")

    with tempfile.TemporaryDirectory() as tmp_dir:
        result = export_building(building_coll, tmp_dir, ASSEMBLY_KIT_ROOT, bpy.context)
        assert result.success, f"export failed: {result.message}"
        doc = read_cs2((Path(tmp_dir) / f"{building_coll.name}.CS2").read_bytes())

    by_cri = {}
    for node in doc.rigid_models:
        attrs = {a.name: a.value for a in node.attributes.strings}
        by_cri[attrs.get("class_rigidINFO", "")] = (node, attrs)

    expected = {
        "boiling_oil_lod01": "piece01_destruct01_boiling_oil_lod01",
        "collision3d_boiling_oil": "piece01_destruct01_collision3d_boiling_oil",
    }
    for cri, node_name in expected.items():
        assert cri in by_cri, f"'{cri}' missing from the export"
        assert by_cri[cri][0].node_name == node_name, f"{cri} exported as '{by_cri[cri][0].node_name}', expected '{node_name}'"
        print(f"  {node_name}")

    assert by_cri["collision3d_boiling_oil"][0].geometry_chunks[0].submeshes[0].material_id == -1
    assert by_cri["boiling_oil_lod01"][0].geometry_chunks[0].submeshes[0].material_id >= 0


def main() -> None:
    print("=== enabling add-on ===")
    if addon_utils.enable("total_war_cs2_addon", default_set=True, persistent=False) is None:
        raise RuntimeError("addon_utils.enable returned failure")
    properties.register()

    test_cs2_import_and_reexport()
    test_authoring()

    print("=== ALL BOILING OIL TESTS PASSED ===")


if __name__ == "__main__":
    main()
