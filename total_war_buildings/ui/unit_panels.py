import bpy

from extraction.unit_extract import armature_of, find_unit_armature, skeleton_name_for, unit_kind
from props.properties import NO_BONE_TYPE
from .animation_panels import draw_clip_picker
from .collection_utils import get_object_collection_role
from .panels import WorkflowGatedPanel, _draw_wrapped_text, active_role_collection, object_section_visible


def unit_object_box(context: bpy.types.Context, on_object: bool) -> bpy.types.Object | None:
    # Which object, if any, the per-object box should describe. Gated on object_section_visible's
    # recency answer rather than on context.object alone: clicking a collection leaves the previously
    # active object in place, so an ungated box stays behind describing something the artist is no
    # longer looking at. Same rule, and the same reasoning, as the Building panel's own object boxes.
    obj = context.object
    if not on_object or obj is None:
        return None
    if obj.type == "MESH" and get_object_collection_role(obj) == "UNIT_MESH":
        return obj
    if obj.tw_attachment_point_name:
        return obj
    return None


def draw_weighting_summary(layout: bpy.types.UILayout, obj: bpy.types.Object) -> None:
    armature = armature_of(obj)
    if armature is None:
        layout.label(text="No Armature modifier - not skinned yet", icon="INFO")
    else:
        layout.label(text=f"Armature: {armature.name}", icon="ARMATURE_DATA")
    if not obj.vertex_groups:
        layout.label(text="No vertex groups - nothing to weight from", icon="INFO")
    else:
        layout.label(text=f"Vertex groups: {len(obj.vertex_groups)}", icon="GROUP_VERTEX")


class TW_PT_unit_setup(WorkflowGatedPanel, bpy.types.Panel):
    bl_label = "Unit Setup"
    bl_idname = "TW_PT_unit_setup"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "Total War"
    bl_order = 1
    workflows = frozenset({"UNIT"})

    def draw(self, context: bpy.types.Context) -> None:
        layout = self.layout
        layout.operator("tw_buildings.new_unit", icon="ADD")

        # Each Add button appears only where it can act, so the panel shows the step the artist is
        # actually on rather than every step at once. Importing is Blender's own File > Import.
        on_object = object_section_visible(context)
        unit = active_role_collection(context, on_object, "UNIT")
        model = active_role_collection(context, on_object, "UNIT_MESH")

        if unit is None:
            _draw_wrapped_text(
                layout,
                "Start with New Unit Asset - one asset is one exported model file. Bring an existing "
                "one in with File > Import instead.",
            )

        if unit is not None:
            row = layout.row(align=True)
            row.operator("tw_buildings.new_unit_mesh", icon="ADD")
            if unit_kind(unit) == "WEIGHTED":
                row.operator("tw_buildings.new_attachment_point", icon="EMPTY_ARROWS")

            box = layout.box()
            box.label(text=unit.name, icon="OUTLINER_COLLECTION")
            # The skeleton is a property of the asset, not of each model: every model in one asset
            # is weighted to the same one.
            draw_asset_skeleton_summary(box, context, unit)

        if model is not None:
            box = layout.box()
            box.label(text=model.name, icon="OUTLINER_COLLECTION")
            box.prop(model, "tw_unit_part_kind")


        obj = unit_object_box(context, on_object)
        if obj is None:
            return
        if obj.type == "MESH":
            box = layout.box()
            box.label(text=obj.name, icon="MESH_DATA")
            box.prop(obj, "tw_lod_index")
            draw_weighting_summary(box, obj)
        elif obj.tw_attachment_point_name:
            box = layout.box()
            box.label(text=obj.name, icon="EMPTY_ARROWS")
            box.prop(obj, "tw_attachment_point_name")
            if obj.parent_type == "BONE" and obj.parent_bone:
                box.label(text=f"On bone: {obj.parent_bone}", icon="BONE_DATA")
            else:
                box.label(text="Not parented to a bone yet", icon="ERROR")


def draw_asset_skeleton_summary(
    layout: bpy.types.UILayout, context: bpy.types.Context, unit: bpy.types.Collection
) -> None:
    if unit_kind(unit) != "WEIGHTED":
        layout.label(text="Attaches to a bone named by a .variantmeshdefinition", icon="INFO")
        return
    armature_object = find_unit_armature(unit)
    if armature_object is None:
        layout.label(text="No skeleton bound", icon="ERROR")
    else:
        layout.label(text=f"Skeleton: {skeleton_name_for(armature_object)}", icon="ARMATURE_DATA")
    layout.operator("tw_buildings.bind_to_skeleton", icon="ARMATURE_DATA")
    # The clip picker is drawn here on the user's request: an artist assembling a soldier wants to
    # watch him move on the skeleton he just bound, without switching workflows to do it.
    if armature_object is not None:
        draw_clip_picker(layout, context, armature_object)


def draw_bone_table_summary(layout: bpy.types.UILayout, armature: bpy.types.Armature) -> None:
    listed = sum(1 for bone in armature.bones if bone.tw_bone_type != NO_BONE_TYPE)
    layout.label(text=f"Bones: {len(armature.bones)} ({listed} in the bone table)")


class TW_PT_skeleton_setup(WorkflowGatedPanel, bpy.types.Panel):
    bl_label = "Skeleton Setup"
    bl_idname = "TW_PT_skeleton_setup"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "Total War"
    bl_order = 1
    workflows = frozenset({"SKELETON"})

    def draw(self, context: bpy.types.Context) -> None:
        layout = self.layout
        row = layout.row(align=True)
        row.operator("tw_buildings.new_skeleton", icon="ADD")
        row.operator("tw_buildings.import_file", text="Import", icon="IMPORT")

        on_object = object_section_visible(context)
        skeleton = active_role_collection(context, on_object, "SKELETON")
        if skeleton is None:
            _draw_wrapped_text(
                layout,
                "Make an empty skeleton with New Skeleton, or bring one in with Import. Its bones are "
                "added and shaped in Blender's own Edit Mode.",
            )
            return
        armature_object = _skeleton_armature(context, skeleton)
        if armature_object is None:
            layout.label(text=f"'{skeleton.name}' holds no Armature yet", icon="INFO")
            return

        armature = armature_object.data
        box = layout.box()
        box.label(text=skeleton.name, icon="OUTLINER_COLLECTION")
        box.label(text=f"Exports as {skeleton.name}.CS2 + .bone_table", icon="EXPORT")
        draw_bone_table_summary(box, armature)
        box.prop(armature, "tw_reference_skeleton")
        box.prop(armature, "tw_cinematic")
        box.prop(armature, "tw_bone_table_version")

        # Custom properties live on Bone, not on EditBone, so the per-bone box has nothing to draw
        # while the artist is actually adding bones in Edit Mode.
        if armature_object.mode == "EDIT":
            layout.label(text="Bone settings are editable outside Edit Mode", icon="INFO")
            return
        bone = armature.bones.active
        if bone is None:
            return
        bone_box = layout.box()
        bone_box.label(text=bone.name, icon="BONE_DATA")
        bone_box.prop(bone, "tw_bone_type")
        if bone.tw_bone_type != NO_BONE_TYPE:
            bone_box.prop(bone, "tw_bone_sort_order")
            bone_box.prop(bone, "tw_bone_flags")
        bone_box.prop(bone, "tw_is_limb")


def _skeleton_armature(context: bpy.types.Context, skeleton: bpy.types.Collection) -> bpy.types.Object | None:
    obj = context.object
    if obj is not None and obj.type == "ARMATURE" and obj.name in skeleton.all_objects:
        return obj
    return next((candidate for candidate in skeleton.all_objects if candidate.type == "ARMATURE"), None)


CLASSES = (
    TW_PT_unit_setup,
    TW_PT_skeleton_setup,
)


def register() -> None:
    for cls in CLASSES:
        bpy.utils.register_class(cls)


def unregister() -> None:
    for cls in reversed(CLASSES):
        bpy.utils.unregister_class(cls)
