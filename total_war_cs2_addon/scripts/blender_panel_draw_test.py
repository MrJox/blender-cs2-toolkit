"""Draw every Total War panel, in every workflow, against real scenes.

Nothing else in the suite executes a panel's draw() - the focus test calls the helper functions the
panels use, but never the panels themselves. That gap let a duplicated block ship in unit_panels.py:
the file defined TW_PT_unit_setup twice, Python kept the stale second one, and every check still
passed while the sidebar raised AttributeError on every redraw.
"""
import sys
import traceback

import addon_utils
import bpy

REPO_ROOT = r"C:\Users\Khaiali\source\repos\blender_buildings_plugin"

if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

WORKFLOWS = ("BUILDING", "UNIT", "SKELETON", "SKELETAL_ANIMATION", "VEGETATION")

failures = []


def check(label: str, condition: bool) -> None:
    print(("  OK   " if condition else "  FAIL ") + label)
    if not condition:
        failures.append(label)


def total_war_panels():
    return [
        getattr(bpy.types, name)
        for name in dir(bpy.types)
        if name.startswith("TW_PT_") and getattr(getattr(bpy.types, name), "bl_category", "") == "Total War"
    ]


def new_collection(name, role, parent):
    collection = bpy.data.collections.new(name)
    collection.tw_role = role
    parent.children.link(collection)
    return collection


def add_mesh(name, collection):
    obj = bpy.data.objects.new(name, bpy.data.meshes.new(name))
    collection.objects.link(obj)
    return obj


def layer_collection_for(collection):
    def find(layer_collection):
        if layer_collection.collection == collection:
            return layer_collection
        for child in layer_collection.children:
            found = find(child)
            if found is not None:
                return found
        return None

    return find(bpy.context.view_layer.layer_collection)


def activate(collection=None, obj=None):
    if collection is not None:
        bpy.context.view_layer.active_layer_collection = layer_collection_for(collection)
    for existing in bpy.context.view_layer.objects:
        existing.select_set(False)
    if obj is not None:
        bpy.context.view_layer.objects.active = obj
        obj.select_set(True)


class StubLayout:
    # Background Blender has no region to build a real UILayout in, and a real one would not check
    # much anyway. This stands in for it and validates what panel bugs are actually made of: an
    # operator or menu that is not registered, and a prop() naming something the data does not have.
    # Every panel here uses nothing but self.layout, so this is the whole surface.
    def __init__(self, problems: list[str]) -> None:
        self._problems = problems

    def _sub(self, *args, **kwargs):
        return self

    row = column = box = split = _sub

    def label(self, *args, **kwargs):
        return None

    def separator(self, *args, **kwargs):
        return None

    def operator(self, idname: str, **kwargs):
        # dir(), not hasattr(): bpy.ops.<module> resolves any attribute name and only fails when the
        # operator is actually called, so hasattr always says yes and checks nothing.
        module, _, name = idname.partition(".")
        if name not in dir(getattr(bpy.ops, module, None)):
            self._problems.append(f"operator '{idname}' is not registered")
        # Real layout.operator returns the operator's settable properties; callers assign to them.
        return type("OperatorProperties", (), {})()

    def menu(self, idname: str, **kwargs):
        if not hasattr(bpy.types, idname):
            self._problems.append(f"menu '{idname}' is not registered")
        return None

    def prop(self, data, name: str, **kwargs):
        if data is None or name not in data.bl_rna.properties:
            self._problems.append(f"prop '{name}' does not exist on {type(data).__name__}")
        return None


def draw_everything(label: str) -> None:
    for panel in total_war_panels():
        for workflow in WORKFLOWS:
            bpy.context.scene.tw_workflow = workflow
            poll = getattr(panel, "poll", None)
            if poll is not None and not poll(bpy.context):
                continue
            problems: list[str] = []
            panel_self = type("PanelStub", (), {"layout": StubLayout(problems)})()
            try:
                panel.draw(panel_self, bpy.context)
            except Exception as error:  # noqa: BLE001 - the whole point of the test
                traceback.print_exc()
                problems.append(f"raised {type(error).__name__}: {error}")
            for problem in problems:
                check(f"{label}: {panel.bl_idname} in {workflow} - {problem}", False)
    check(f"{label}: every panel drew cleanly", not failures)


def main() -> None:
    module = addon_utils.enable("total_war_cs2_addon", default_set=True, persistent=False)
    if module is None:
        raise RuntimeError("addon_utils.enable returned failure")

    scene = bpy.context.scene.collection
    check("the Total War category has panels", bool(total_war_panels()))

    print("=== an empty scene ===")
    draw_everything("empty scene")

    print("=== a building ===")
    building = new_collection("TestBuilding", "BUILDING", scene)
    piece = new_collection("Piece 1", "PIECE", building)
    destruct = new_collection("Destruct 1", "DESTRUCT", piece)
    display = new_collection("Display", "DISPLAY", destruct)
    lod = add_mesh("piece01_destruct01_lod01", display)
    for target in (building, piece, destruct, display):
        activate(collection=target)
        draw_everything(f"building, {target.name} active")
    activate(collection=display, obj=lod)
    draw_everything("building, a LOD mesh active")

    print("=== a unit asset ===")
    unit = new_collection("test_asset", "UNIT", scene)
    model = new_collection("test_model", "UNIT_MESH", unit)
    unit_lod = add_mesh("test_model_lod1", model)
    point = bpy.data.objects.new("weapon_01", None)
    point.tw_attachment_point_name = "weapon_01"
    unit.objects.link(point)
    for kind in ("WEIGHTED", "RIGID_ATTACHMENT"):
        model.tw_unit_part_kind = kind
        for target in (unit, model):
            activate(collection=target)
            draw_everything(f"unit ({kind}), {target.name} active")
        activate(collection=model, obj=unit_lod)
        draw_everything(f"unit ({kind}), a LOD mesh active")
        activate(collection=unit, obj=point)
        draw_everything(f"unit ({kind}), an attachment point active")

    print("=== a skeleton ===")
    skeleton = new_collection("test_skeleton", "SKELETON", scene)
    armature = bpy.data.armatures.new("test_skeleton")
    armature_object = bpy.data.objects.new("test_skeleton", armature)
    skeleton.objects.link(armature_object)
    activate(collection=skeleton)
    draw_everything("skeleton, no bones yet")
    bpy.context.view_layer.objects.active = armature_object
    bpy.ops.object.mode_set(mode="EDIT")
    bone = armature.edit_bones.new("bn_root")
    bone.head, bone.tail = (0.0, 0.0, 0.0), (0.0, 0.0, 0.5)
    bpy.ops.object.mode_set(mode="OBJECT")
    armature.bones.active = armature.bones["bn_root"]
    activate(collection=skeleton, obj=armature_object)
    draw_everything("skeleton, a bone active")

    print("=== an animation clip ===")
    draw_everything("a skeleton but no clip on it")
    clip = bpy.data.actions.new("test_clip")
    clip.tw_skeleton_name = "test_skeleton"
    clip.tw_frame_rate = 20.0
    armature_object.animation_data_create().action = clip
    draw_everything("a clip assigned to the skeleton")

    # The clip picker is drawn by the Unit panel too, but only once the asset is bound to a skeleton.
    model.tw_unit_part_kind = "WEIGHTED"
    unit_lod.modifiers.new(name="Armature", type="ARMATURE").object = armature_object
    for target in (unit, model):
        activate(collection=target)
        draw_everything(f"unit bound to a skeleton, {target.name} active")

    print()
    if failures:
        print(f"FAILED {len(failures)} check(s):")
        for failure in failures:
            print("   ", failure)
        raise SystemExit(1)
    print("all checks passed")


try:
    main()
except SystemExit:
    raise
except Exception:
    traceback.print_exc()
    sys.exit(1)
