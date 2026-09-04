import addon_utils
import bpy

module = addon_utils.enable("total_war_cs2_addon", default_set=True, persistent=False)
print("module found by Blender's own addon discovery:", module)
if module is None:
    raise SystemExit(1)
print("operators registered:", hasattr(bpy.ops.tw_buildings, "new_building"))
bpy.ops.tw_buildings.new_building()
print("building created:", [c.name for c in bpy.data.collections if c.tw_role == "BUILDING"])
print("INSTALL VERIFIED")
