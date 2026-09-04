import sys
from pathlib import Path
import bpy

ADDON_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ADDON_DIR))

import addon_utils
from props import properties
from importer.cs2_importer import import_cs2
from export.exporter import export_building
from binary.cs2_reader import read_cs2

def test_height_map_export():
    print("=== Testing Height Map Mesh Export ===")
    bpy.ops.wm.read_factory_settings(use_empty=True)
    properties.register()

    # Import bridge_stone_1 which contains height_map_mesh
    sample_path = ADDON_DIR.parent / "Input/examples/raw_data/bridge_stone_1/bridge_stone_1.CS2"
    building_coll, warnings = import_cs2(str(sample_path), bpy.context)
    
    # Check that Height Map Mesh collection exists and has 1 object
    destruct_coll = building_coll.children[0].children[0]
    height_map_colls = [c for c in destruct_coll.children if c.tw_role == "HEIGHT_MAP_MESH"]
    assert len(height_map_colls) == 1, "HEIGHT_MAP_MESH collection missing after import!"
    assert len(height_map_colls[0].objects) == 1, "Height map mesh object missing after import!"
    print(f"Imported Height Map Mesh object: {height_map_colls[0].objects[0].name}")

    # Export building
    import tempfile
    out_dir = Path(tempfile.mkdtemp())
    res = export_building(building_coll, str(out_dir), "", bpy.context)
    assert res.success, f"Export failed: {res.message}"
    print(f"Export successful: {res.cs2_path}")

    # Re-read exported CS2 file and verify node
    doc = read_cs2(res.cs2_path.read_bytes())
    height_nodes = [rm for rm in doc.rigid_models if "height" in rm.node_name.lower()]
    assert len(height_nodes) == 1, f"Expected 1 height_map_mesh node in exported CS2, got {len(height_nodes)}"
    
    node = height_nodes[0]
    print(f"Exported CS2 Node Name: {node.node_name}")
    attr_dict = {a.name: a.value for a in node.attributes.strings}
    print(f"Attributes: {attr_dict}")
    assert attr_dict.get("class_TYPE") == "IGNORE", f"Expected class_TYPE 'IGNORE', got {attr_dict.get('class_TYPE')}"
    assert attr_dict.get("graphics_OPTION") == "NOT_GRAPHICS", f"Expected graphics_OPTION 'NOT_GRAPHICS', got {attr_dict.get('graphics_OPTION')}"
    assert attr_dict.get("class_rigidINFO") == "height_map_mesh01", f"Expected class_rigidINFO 'height_map_mesh01', got {attr_dict.get('class_rigidINFO')}"
    assert len(node.geometry_chunks) == 1, "Expected 1 geometry chunk"
    print("=== HEIGHT MAP MESH EXPORT TEST PASSED ===")

if __name__ == "__main__":
    addon_utils.enable("total_war_cs2_addon", default_set=True, persistent=False)
    properties.register()
    test_height_map_export()
