import sys
import traceback

import addon_utils
import bpy

REPO_ROOT = r"C:\Users\Khaiali\source\repos\blender_buildings_plugin"

if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

FAILURES = []


def check(label, actual, expected):
    if actual != expected:
        FAILURES.append(f"{label}: expected {expected}, got {actual}")
    print(f"{'PASS' if actual == expected else 'FAIL'} {label}: {actual}")


def name_of(collection):
    return collection.name if collection is not None else None


def layer_collection_for(collection):
    def find(layer_collection):
        if layer_collection.collection == collection:
            return layer_collection
        for child in layer_collection.children:
            found = find(child)
            if found is not None:
                return found
        return None

    found = find(bpy.context.view_layer.layer_collection)
    if found is None:
        raise RuntimeError(f"no layer collection for {collection.name}")
    return found


def new_collection(name, role, parent):
    collection = bpy.data.collections.new(name)
    collection.tw_role = role
    parent.children.link(collection)
    return collection


def add_mesh(name, collection):
    mesh = bpy.data.meshes.new(name)
    obj = bpy.data.objects.new(name, mesh)
    collection.objects.link(obj)
    return obj


def deselect_all():
    for obj in bpy.context.view_layer.objects:
        obj.select_set(False)


def click_collection(collection):
    # A real Outliner collection click deselects the objects (confirmed in a running Blender) and
    # makes that collection active. Modelling the deselect is what makes these checks mean anything:
    # the rule under test reads selection, so a helper that only moved the active collection would
    # pass whatever the rule did.
    bpy.context.view_layer.active_layer_collection = layer_collection_for(collection)
    deselect_all()


def click_object_in_outliner(obj, collection):
    # A real Outliner object click selects it and syncs the active collection to the object's own
    # collection; a viewport click (click_object_in_viewport) does not touch the collection at all.
    bpy.context.view_layer.active_layer_collection = layer_collection_for(collection)
    deselect_all()
    bpy.context.view_layer.objects.active = obj
    obj.select_set(True)


def click_object_in_viewport(obj):
    deselect_all()
    bpy.context.view_layer.objects.active = obj
    obj.select_set(True)


def main():
    addon_utils.enable("total_war_cs2_addon", default_set=True, persistent=True)
    from total_war_cs2_addon.ui import panels

    for obj in list(bpy.data.objects):
        bpy.data.objects.remove(obj)

    scene_collection = bpy.context.scene.collection
    building = new_collection("Building", "BUILDING", scene_collection)
    piece = new_collection("Piece 1", "PIECE", building)
    destruct = new_collection("Destruct 1", "DESTRUCT", piece)
    display = new_collection("Display", "DISPLAY", destruct)
    collision = new_collection("Collision", "COLLISION", destruct)
    ef_lines = new_collection("EF Lines", "EF_LINES", destruct)

    piece_2 = new_collection("Piece 2", "PIECE", building)
    destruct_2 = new_collection("Destruct 2", "DESTRUCT", piece_2)
    collision_2 = new_collection("Collision 2", "COLLISION", destruct_2)

    lod = add_mesh("LOD01", display)
    hull = add_mesh("Hull", collision)
    hull_2 = add_mesh("Hull 2", collision_2)
    line_a = add_mesh("Line A", ef_lines)
    line_b = add_mesh("Line B", ef_lines)

    context = bpy.context

    # The reported bug.
    click_object_in_outliner(lod, display)
    check("outliner click on Display mesh shows its box", panels.object_section_visible(context), True)
    click_collection(piece)
    check("clicking Piece 1 next hides the stale box", panels.object_section_visible(context), False)
    click_collection(building)
    check("clicking Building keeps it hidden", panels.object_section_visible(context), False)
    click_collection(destruct)
    check("clicking Destruct keeps it hidden", panels.object_section_visible(context), False)

    # No regression: every way of activating an object brings its own box back.
    click_collection(display)
    # Changed 2026-08-30 on the user's report: clicking any collection deselects, so the object's own
    # collection is no longer a special case that keeps the box. It used to be, under the recency rule.
    check("clicking the object's own collection hides it too", panels.object_section_visible(context), False)
    click_collection(piece)
    click_object_in_viewport(hull)
    check("viewport click with an unrelated collection active shows the box", panels.object_section_visible(context), True)
    click_object_in_outliner(hull, collision)
    check("outliner click on the Collision mesh shows its box", panels.object_section_visible(context), True)

    # Several objects in one collection each keep their own box.
    click_object_in_outliner(line_a, ef_lines)
    check("first EF line shows", panels.object_section_visible(context), True)
    click_object_in_outliner(line_b, ef_lines)
    check("second EF line in the same collection still shows", panels.object_section_visible(context), True)
    click_object_in_viewport(line_a)
    check("switching back by viewport click still shows", panels.object_section_visible(context), True)

    # Collection clicks that do not move away from the active object leave it alone.
    click_collection(ef_lines)
    check("clicking the shared EF Lines collection hides the box", panels.object_section_visible(context), False)
    click_collection(destruct)
    check("stepping up to Destruct hides it", panels.object_section_visible(context), False)
    click_object_in_viewport(line_b)
    check("reactivating any object restores it", panels.object_section_visible(context), True)

    # No active object at all.
    bpy.context.view_layer.objects.active = None
    check("no active object hides the box", panels.object_section_visible(context), False)
    click_object_in_outliner(lod, display)
    check("activating an object again shows the box", panels.object_section_visible(context), True)

    # Collection-owned sections must stay driven by the active collection alone.
    from total_war_cs2_addon.ui.collection_utils import get_active_collection

    click_collection(piece)
    check("collection sections follow the active collection", get_active_collection(context).tw_role, "PIECE")
    click_object_in_viewport(hull)
    check("a viewport object click does not move the collection sections", get_active_collection(context).tw_role, "PIECE")

    # Damage Parent must stay reachable from anywhere inside a piece, without going stale.
    from total_war_cs2_addon.ui.collection_utils import find_piece_collection

    def piece_box(context):
        # Same order the panel draws in: the recency rule is updated once, then reused.
        return panels.active_piece_collection(context, panels.object_section_visible(context))

    click_object_in_outliner(hull, collision)
    check("the reported bug: a collision mesh shows its piece", name_of(piece_box(context)), "Piece 1")
    click_object_in_outliner(lod, display)
    check("a display mesh shows its piece too", name_of(piece_box(context)), "Piece 1")
    click_collection(building)
    click_object_in_viewport(hull_2)
    check("a viewport click reaches the object's own piece", name_of(piece_box(context)), "Piece 2")
    click_collection(piece)
    check("clicking another piece next does not leave a stale one", name_of(piece_box(context)), "Piece 1")
    click_collection(destruct)
    check("a destruct level shows its parent piece", name_of(piece_box(context)), "Piece 1")
    click_collection(building)
    bpy.context.view_layer.objects.active = None
    check("outside any piece there is no box", name_of(piece_box(context)), None)

    # --- the same rule in the Unit workflow ---------------------------------------------------
    # It regressed there once: the unit panel computed object_section_visible and then drew its
    # per-object boxes off context.object anyway, so clicking a collection left the LOD box behind.
    print("=== unit workflow object boxes ===")
    from ui.unit_panels import unit_object_box

    unit = new_collection("Unit A", "UNIT", bpy.context.scene.collection)
    unit_mesh = new_collection("body", "UNIT_MESH", unit)
    lod = add_mesh("body_lod1", unit_mesh)
    # A second mesh, because re-activating the object that is already active changes no state at
    # all - a "viewport click" on it would not exercise the rule.
    lod2 = add_mesh("body_lod2", unit_mesh)
    point = bpy.data.objects.new("weapon_01", None)
    point.tw_attachment_point_name = "weapon_01"
    unit.objects.link(point)

    def unit_box(context):
        return unit_object_box(context, panels.object_section_visible(context))

    click_object_in_outliner(lod, unit_mesh)
    check("outliner click on a LOD mesh shows its box", name_of(unit_box(context)), "body_lod1")
    click_collection(unit_mesh)
    check("clicking the mesh's OWN collection hides the LOD box", name_of(unit_box(context)), None)
    click_object_in_outliner(lod, unit_mesh)
    click_collection(unit)
    check("clicking the asset collection hides the stale LOD box", name_of(unit_box(context)), None)
    click_collection(unit)
    check("clicking the unit asset keeps it hidden", name_of(unit_box(context)), None)
    click_object_in_viewport(lod2)
    check("a viewport click with an unrelated collection active shows it", name_of(unit_box(context)), "body_lod2")

    click_object_in_outliner(point, unit)
    check("an attachment point shows its own box", name_of(unit_box(context)), "weapon_01")
    click_collection(unit)
    check("clicking away hides the attachment point box too", name_of(unit_box(context)), None)

    click_collection(building)

    # The Collection Properties panel is collection-only - it must not follow the active object.
    click_object_in_viewport(hull)
    check("collection panel on Collision shows its piece", name_of(find_piece_collection(context, collision)), "Piece 1")
    check("collection panel on Piece 1 shows itself", name_of(find_piece_collection(context, piece)), "Piece 1")
    check("collection panel on Building shows nothing", name_of(find_piece_collection(context, building)), None)


try:
    main()
except Exception:
    traceback.print_exc()
    FAILURES.append("exception")

print("=" * 60)
if FAILURES:
    print("FAILURES:")
    for failure in FAILURES:
        print(" -", failure)
    sys.exit(1)
print("ALL PANEL FOCUS CHECKS PASSED")
