import sys
import traceback

import addon_utils
import bpy

REPO_ROOT = r"C:\Users\Khaiali\source\repos\blender_buildings_plugin"
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)


def main() -> None:
    module = addon_utils.enable("total_war_buildings", default_set=True, persistent=False)
    if module is None:
        raise RuntimeError("addon_utils.enable returned failure")

    bpy.ops.tw_buildings.new_building()
    building = [c for c in bpy.data.collections if c.tw_role == "BUILDING"][-1]
    building.name = "ShouldNotExport"

    def active_layer_collection_for(collection):
        def find(layer_collection):
            if layer_collection.collection == collection:
                return layer_collection
            for child in layer_collection.children:
                found = find(child)
                if found is not None:
                    return found
            return None

        return find(bpy.context.view_layer.layer_collection)

    bpy.context.view_layer.active_layer_collection = active_layer_collection_for(building)

    import os

    out_dir = os.path.dirname(bpy.data.filepath) or r"C:\Users\Khaiali\source\repos\blender_buildings_plugin\total_war_buildings\scripts"
    expected_path = os.path.join(out_dir, "ShouldNotExport.CS2")
    if os.path.exists(expected_path):
        os.remove(expected_path)

    try:
        result = bpy.ops.tw_buildings.export_building(directory=out_dir)
    except RuntimeError as error:
        print("operator raised (expected for a blocked/cancelled operator):", error)
        result = {"CANCELLED"}

    print("operator result:", result)
    print("file exists after blocked export:", os.path.exists(expected_path))

    if result != {"CANCELLED"}:
        raise RuntimeError(f"Expected CANCELLED, got {result}")
    if os.path.exists(expected_path):
        raise RuntimeError("A file was written despite validation blocking the export!")

    print("=== EXPORT BLOCK TEST PASSED ===")


try:
    main()
except Exception:
    print("=== EXPORT BLOCK TEST FAILED ===")
    traceback.print_exc()
    sys.exit(1)
