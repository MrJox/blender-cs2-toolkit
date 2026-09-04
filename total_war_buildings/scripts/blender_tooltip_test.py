"""Every dropdown item, property and operator the artist can hover has to explain itself.

A menu row takes its tooltip from the operator it runs, not from the enum item it sets, so the
"Add..." rows, the shader menu and the clip menu all showed one generic description until each of
those operators grew a description() of its own - that is what the dynamic half of this checks.
"""
import sys

import addon_utils
import bpy

REPO_ROOT = r"C:\Users\Khaiali\source\repos\blender_buildings_plugin"

if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

failures = []


def check(label: str, condition: bool) -> None:
    print(("  OK   " if condition else "  FAIL ") + label)
    if not condition:
        failures.append(label)


if addon_utils.enable("total_war_buildings", default_set=True, persistent=False) is None:
    raise RuntimeError("addon_utils.enable returned failure")

from materials.shader_types import SHADER_TYPES, ALPHA_MODE_ITEMS
from props import properties
from ui import animation_operators, operators, unit_operators

print("=== every dropdown item explains itself ===")
ITEM_LISTS = {
    "collection role": [item for item in properties.TW_ROLE_ITEMS if item[0] != "NONE"],
    "workflow": properties.TW_WORKFLOW_ITEMS,
    "model type": properties.UNIT_PART_KIND_ITEMS,
    "LOD level": properties.LOD_ITEMS,
    "platform type": properties.PLATFORM_TYPE_ITEMS,
    "collision type": properties.COLLISION_TYPE_ITEMS,
    "line type": properties.LINE_TYPE_ITEMS,
    "EFLine action": properties.EFLINE_ACTION_ITEMS,
    "gate animation kind": properties.GATE_ANIM_KIND_ITEMS,
    "bone type": properties.BONE_TYPE_ITEMS,
    "asset type": properties.ASSET_TYPE_ITEMS,
    "shader type": SHADER_TYPES,
    "alpha mode": ALPHA_MODE_ITEMS,
}
for label, items in ITEM_LISTS.items():
    missing = [identifier for identifier, _label, description in items if not description.strip()]
    check(f"{label}: all {len(items)} items described", not missing)
    if missing:
        print("        missing:", ", ".join(missing))

print("=== no internal vocabulary leaks into a tooltip ===")
# Names of things the artist never sees: engine enums, compiled struct fields, the MaxScript tool
# this add-on replaces, and the evidence phrasing that belongs in the plan files.
BANNED = (
    "RDT_",
    "MeshHeaderV5",
    "TWBuildingsTech",
    "class_rigidINFO",
    "node name",
    "tech name",
    "confirmed from a real sample",
    "PLAN_",
)
for label, items in ITEM_LISTS.items():
    leaks = [
        f"{identifier} ({term})"
        for identifier, _label, description in items
        for term in BANNED
        if term.lower() in description.lower()
    ]
    check(f"{label}: no internal vocabulary", not leaks)
    if leaks:
        print("        leaked:", ", ".join(leaks))

print("=== every operator the artist can click has a description ===")
for module in (operators, unit_operators, animation_operators):
    for operator in module.CLASSES:
        # CLASSES also carries the PropertyGroups the operators' own properties are typed against.
        if not issubclass(operator, bpy.types.Operator):
            continue
        if "INTERNAL" in getattr(operator, "bl_options", set()):
            continue
        check(f"{operator.bl_idname} has one", bool(getattr(operator, "bl_description", "").strip()))


def row_description(operator, **properties_dict) -> str:
    return operator.description(bpy.context, type("Properties", (), properties_dict))


print("=== menu rows describe the thing they add, not the operator ===")
ROLE_MENUS = (
    (operators.TW_OT_add_destruct_collection, operators.DESTRUCT_COLLECTION_ROLES),
    (operators.TW_OT_add_building_collection, operators.BUILDING_COLLECTION_ROLES),
    (operators.TW_OT_add_display_collection, operators.DISPLAY_COLLECTION_ROLES),
)
for operator, roles in ROLE_MENUS:
    for role in roles:
        check(
            f"{operator.bl_idname} row '{role}'",
            row_description(operator, role=role) == properties.TW_ROLE_DESCRIPTIONS[role],
        )

for identifier, _label, description in SHADER_TYPES:
    check(
        f"shader row '{identifier}'",
        row_description(operators.TW_OT_set_shader_type, shader_type=identifier) == description,
    )

armature = bpy.data.objects.new("rig", bpy.data.armatures.new("rig"))
bpy.context.scene.collection.objects.link(armature)
armature.animation_data_create()
action = bpy.data.actions.new("test_clip")
action.tw_frame_rate = 20.0
armature.animation_data.action = action
armature.keyframe_insert("location", frame=1)
armature.keyframe_insert("location", frame=21)
clip_operator = animation_operators.TW_OT_set_animation_clip
clip_text = row_description(clip_operator, clip="test_clip")
check("clip row names its clip", "test_clip" in clip_text and "21 frames at 20 fps" in clip_text)
check(
    "clip row falls back when the clip is gone",
    row_description(clip_operator, clip="gone") == clip_operator.bl_description,
)

print()
if failures:
    print(f"{len(failures)} check(s) failed")
    for failure in failures:
        print("  -", failure)
    sys.exit(1)
print("all checks passed")
