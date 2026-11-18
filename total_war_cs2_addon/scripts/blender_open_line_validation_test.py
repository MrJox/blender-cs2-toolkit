import sys
import traceback

import addon_utils
import bpy

REPO_ROOT = r"C:\Users\Khaiali\source\repos\blender_buildings_plugin"
SCRIPTS_DIR = REPO_ROOT + r"\total_war_cs2_addon\scripts"
ASSEMBLY_KIT_ROOT = r"D:\SteamLibrary\steamapps\common\Total War Attila\assembly_kit"

for path in (REPO_ROOT, SCRIPTS_DIR):
    if path not in sys.path:
        sys.path.insert(0, path)


def check(condition, description):
    if not condition:
        raise AssertionError(description)
    print("  OK:", description)


def add_curve(collection, kind, name, line_type):
    if kind == "bezier":
        bpy.ops.curve.primitive_bezier_curve_add()
    else:
        bpy.ops.curve.primitive_bezier_circle_add()
    obj = bpy.context.active_object
    for coll in list(obj.users_collection):
        coll.objects.unlink(obj)
    collection.objects.link(obj)
    obj.name = name
    obj.tw_line_type = line_type
    return obj


def main() -> None:
    module = addon_utils.enable("total_war_cs2_addon", default_set=True, persistent=False)
    if module is None:
        raise RuntimeError("addon_utils.enable returned failure")
    bpy.context.preferences.addons["total_war_cs2_addon"].preferences.assembly_kit_root = ASSEMBLY_KIT_ROOT

    from blender_efline_platform_validation_test import active_layer_collection_for, add_child_collection, add_destruct
    from validation.rules import validate_building

    bpy.ops.tw_buildings.new_building()
    building = [c for c in bpy.data.collections if c.tw_role == "BUILDING"][-1]
    bpy.context.view_layer.active_layer_collection = active_layer_collection_for(building)
    bpy.ops.tw_buildings.new_piece()
    destruct = add_destruct(building, building.children[-1])
    lines = add_child_collection(destruct, "LINES")

    add_curve(lines, "bezier", "OpenOutline", "OUTLINE")
    add_curve(lines, "bezier", "OpenGroundAD", "GROUND_AD")
    add_curve(lines, "bezier", "OpenPipe", "PIPE_DOOR")
    add_curve(lines, "circle", "ClosedOutline", "OUTLINE")
    bpy.context.view_layer.update()

    issues = {issue.object_name: issue for issue in validate_building(building) if issue.object_name}
    print("  OpenOutline:", issues["OpenOutline"].message)

    check("OpenOutline" in issues and issues["OpenOutline"].severity == "WARNING", "an open Outline curve is warned about, not blocked")
    check("Line Type" in issues["OpenOutline"].message, "the warning points at the Line Type setting")
    check("Outline Collision" in issues["OpenOutline"].message, "the warning names the type the curve currently has")
    check("OpenGroundAD" not in issues, "an open Bezier curve typed Ground AD validates cleanly")
    check("OpenPipe" not in issues, "an open Bezier curve typed as a Pipe validates cleanly")
    check("ClosedOutline" not in issues, "a closed Bezier circle typed Outline validates cleanly")


if __name__ == "__main__":
    try:
        main()
    except Exception:
        traceback.print_exc()
        sys.exit(1)
