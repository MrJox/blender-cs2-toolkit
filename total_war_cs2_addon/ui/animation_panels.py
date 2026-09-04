import bpy

from .animation_operators import animation_armature, clips_for
from .panels import WorkflowGatedPanel


class TW_MT_animation_clips(bpy.types.Menu):
    bl_label = "Animation Clip"
    bl_idname = "TW_MT_animation_clips"

    def draw(self, context: bpy.types.Context) -> None:
        layout = self.layout
        clips = clips_for(animation_armature(context))
        if not clips:
            layout.label(text="No clips in this file yet", icon="INFO")
            return
        for action in clips:
            layout.operator("tw_buildings.set_animation_clip", text=action.name).clip = action.name


def draw_clip_picker(layout: bpy.types.UILayout, context: bpy.types.Context, armature_object: bpy.types.Object) -> None:
    # The one place a clip is chosen, drawn by both the Skeletal Animation panel and the Unit one -
    # an artist assembling a soldier wants to see him move without leaving the workflow he is in.
    action = armature_object.animation_data.action if armature_object.animation_data else None
    row = layout.row(align=True)
    row.menu("TW_MT_animation_clips", text=action.name if action else "Rest Pose", icon="ARMATURE_DATA")
    # Both act on the clip, so both are drawn only while one is picked: X puts the skeleton back in
    # its rest pose and keeps the clip, the bin removes the clip from the file altogether.
    if action is not None:
        row.operator("tw_buildings.clear_animation_clip", text="", icon="X")
        row.operator("tw_buildings.delete_animation_clip", text="", icon="TRASH").clip = action.name

    if action is None:
        layout.label(text=f"'{armature_object.name}' is in its rest pose", icon="INFO")
        return
    start, end = action.frame_range
    rate = action.tw_frame_rate or context.scene.render.fps
    layout.label(text=f"{round(end) - round(start) + 1} frames at {rate:g} fps", icon="ANIM")
    layout.prop(action, "tw_frame_rate")
    row = layout.row(align=True)
    row.operator("screen.animation_play", text="Play", icon="PLAY")
    row.operator("screen.frame_jump", text="", icon="REW").end = False


class TW_PT_animation_setup(WorkflowGatedPanel, bpy.types.Panel):
    bl_label = "Animation Setup"
    bl_idname = "TW_PT_animation_setup"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "Total War"
    bl_order = 1
    workflows = frozenset({"SKELETAL_ANIMATION"})

    def draw(self, context: bpy.types.Context) -> None:
        layout = self.layout
        row = layout.row(align=True)
        row.operator("tw_buildings.new_animation_clip", icon="ADD")
        row.operator("tw_buildings.import_file", text="Import", icon="IMPORT")

        armature_object = animation_armature(context)
        if armature_object is None:
            layout.label(text="No skeleton in the scene - import or make one first", icon="ERROR")
            return

        box = layout.box()
        box.label(text=armature_object.name, icon="ARMATURE_DATA")
        draw_clip_picker(box, context, armature_object)


CLASSES = (
    TW_MT_animation_clips,
    TW_PT_animation_setup,
)


def register() -> None:
    for cls in CLASSES:
        bpy.utils.register_class(cls)


def unregister() -> None:
    for cls in reversed(CLASSES):
        bpy.utils.unregister_class(cls)
