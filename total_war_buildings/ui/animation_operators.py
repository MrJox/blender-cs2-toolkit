import bpy

from bob.cli import start_animation_batch
from export.animation_exporter import export_animation
from extraction.unit_extract import find_unit_armature, skeleton_name_for
from importer.anim_importer import FIRST_FRAME, apply_action, rest_pose
from props.properties import get_assembly_kit_root
from validation.rules import action_data_paths, validate_animation
from .collection_utils import find_unit_collection
from .operators import BobWaitMixin, export_blocked_headline, export_failure_message, report_export_warnings
from .panels import active_role_collection, object_section_visible


def clips_for(armature_object: bpy.types.Object | None) -> list[bpy.types.Action]:
    # An imported clip is stamped with the skeleton the file named; one authored in Blender carries
    # no stamp until it is exported. Both belong to whatever Armature is in front of the artist, so
    # the filter is "not stamped for a different skeleton" rather than an exact match - which is also
    # what keeps a renamed skeleton's own clips visible.
    if armature_object is None:
        return []
    skeleton = skeleton_name_for(armature_object).lower()
    bones = {bone.name for bone in armature_object.data.bones}
    clips = []
    for action in bpy.data.actions:
        stamp = action.tw_skeleton_name.lower()
        if stamp and stamp != skeleton and not _covers(action, bones):
            continue
        clips.append(action)
    return sorted(clips, key=lambda action: action.name.lower())


def _covers(action: bpy.types.Action, bones: set[str]) -> bool:
    names = {
        path[len('pose.bones["') : path.index('"]')]
        for path in action_data_paths(action)
        if path.startswith('pose.bones["')
    }
    return bool(names) and not (names - bones)


def animation_armature(context: bpy.types.Context) -> bpy.types.Object | None:
    # The Unit workflow plays a clip on whatever skeleton the selected asset is bound to; the
    # Skeletal Animation workflow authors against the selected Skeleton collection directly.
    if context.scene.tw_workflow == "UNIT":
        unit = find_unit_collection(context)
        return find_unit_armature(unit) if unit is not None else None

    obj = context.object
    if obj is not None and obj.type == "ARMATURE" and obj.select_get():
        return obj
    skeleton = active_role_collection(context, object_section_visible(context), "SKELETON")
    if skeleton is not None:
        return next((candidate for candidate in skeleton.all_objects if candidate.type == "ARMATURE"), None)
    return next((candidate for candidate in bpy.data.objects if candidate.type == "ARMATURE"), None)


class TW_OT_set_animation_clip(bpy.types.Operator):
    bl_idname = "tw_buildings.set_animation_clip"
    bl_label = "Set Animation Clip"
    bl_description = "Put this clip on the skeleton and set the scene's frame range and playback rate to match it"
    bl_options = {"REGISTER", "UNDO"}

    clip: bpy.props.StringProperty()

    @classmethod
    def description(cls, context: bpy.types.Context, properties) -> str:
        # Every row of the clip menu runs this one operator, so without this they would all share a
        # single tooltip that names no clip.
        action = bpy.data.actions.get(properties.clip)
        if action is None:
            return cls.bl_description
        start, end = action.frame_range
        rate = action.tw_frame_rate or context.scene.render.fps
        return (
            f"Put '{action.name}' on the skeleton - {round(end) - round(start) + 1} frames at {rate:g} fps. "
            "The scene's frame range and playback rate follow it"
        )

    def execute(self, context: bpy.types.Context):
        armature_object = animation_armature(context)
        if armature_object is None:
            self.report({"ERROR"}, "There is no skeleton here to play a clip on.")
            return {"CANCELLED"}
        action = bpy.data.actions.get(self.clip)
        if action is None:
            self.report({"ERROR"}, f"There is no clip called '{self.clip}' any more.")
            return {"CANCELLED"}
        apply_action(armature_object, action, context.scene)
        self.report({"INFO"}, f"'{action.name}' is on '{armature_object.name}'.")
        return {"FINISHED"}


def stop_playback(context: bpy.types.Context) -> None:
    # Taking the clip off while the timeline is running leaves the playhead sweeping a skeleton that
    # nothing animates any more. is_animation_playing is the real guard - background Blender does
    # carry a screen, with the flag false - and the getattr covers a context that has none at all.
    screen = getattr(context, "screen", None)
    if screen is None or not screen.is_animation_playing:
        return
    try:
        bpy.ops.screen.animation_cancel(restore_frame=False)
    except RuntimeError:
        pass


class TW_OT_clear_animation_clip(bpy.types.Operator):
    bl_idname = "tw_buildings.clear_animation_clip"
    bl_label = "Rest Pose"
    bl_description = "Take the clip off this skeleton and stand it back in its rest pose. The clip itself is kept"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context: bpy.types.Context):
        armature_object = animation_armature(context)
        if armature_object is None:
            self.report({"ERROR"}, "There is no skeleton here.")
            return {"CANCELLED"}
        stop_playback(context)
        rest_pose(armature_object)
        self.report({"INFO"}, f"'{armature_object.name}' is back in its rest pose.")
        return {"FINISHED"}


class TW_OT_delete_animation_clip(bpy.types.Operator):
    bl_idname = "tw_buildings.delete_animation_clip"
    bl_label = "Delete Animation Clip"
    bl_description = (
        "Remove this clip from the .blend for good and put the skeleton back in its rest pose. An "
        "imported clip can be imported again; one authored here cannot be recovered"
    )
    bl_options = {"REGISTER", "UNDO"}

    clip: bpy.props.StringProperty()

    def invoke(self, context: bpy.types.Context, event: bpy.types.Event):
        if not self.clip:
            armature_object = animation_armature(context)
            action = armature_object.animation_data.action if armature_object and armature_object.animation_data else None
            if action is None:
                self.report({"ERROR"}, "No clip is picked, so there is nothing to delete.")
                return {"CANCELLED"}
            self.clip = action.name
        return context.window_manager.invoke_confirm(self, event)

    def execute(self, context: bpy.types.Context):
        action = bpy.data.actions.get(self.clip)
        if action is None:
            self.report({"ERROR"}, f"There is no clip called '{self.clip}' any more.")
            return {"CANCELLED"}
        stop_playback(context)
        # Every Armature it is on, not only the one in front of the artist: an Action can be shared,
        # and removing it while another object still plays it leaves that one frozen mid-pose.
        for obj in bpy.data.objects:
            if obj.type == "ARMATURE" and obj.animation_data is not None and obj.animation_data.action is action:
                rest_pose(obj)
        name = action.name
        bpy.data.actions.remove(action)
        self.report({"INFO"}, f"Deleted '{name}'.")
        return {"FINISHED"}


class TW_OT_new_animation_clip(bpy.types.Operator):
    bl_idname = "tw_buildings.new_animation_clip"
    bl_label = "New Animation Clip"
    bl_description = (
        "Start an empty clip on this skeleton, named after the file it exports as. Pose the bones and key "
        "them with Blender's own I (Insert Keyframe)"
    )
    bl_options = {"REGISTER", "UNDO"}

    clip_name: bpy.props.StringProperty(
        name="Clip Name",
        default="new_clip",
        description="What this clip exports as - the .CS2 and the compiled .anim take this name",
    )
    frame_count: bpy.props.IntProperty(
        name="Frames",
        default=41,
        min=2,
        description="How many frames long the clip is. One Blender frame is one clip frame, so this is the scene frame range it gets",
    )
    frame_rate: bpy.props.IntProperty(
        name="Clip FPS",
        default=20,
        min=1,
        description=(
            "How many frames a second the clip plays and is compiled at. Every game clip measured here "
            "runs at 20, though those are building debris rather than soldier animation - match a "
            "reference clip if you have one"
        ),
    )

    def invoke(self, context: bpy.types.Context, event: bpy.types.Event):
        return context.window_manager.invoke_props_dialog(self)

    def execute(self, context: bpy.types.Context):
        armature_object = animation_armature(context)
        if armature_object is None:
            self.report({"ERROR"}, "Select a Skeleton collection, or a unit asset bound to one, first.")
            return {"CANCELLED"}
        if not self.clip_name.strip():
            self.report({"ERROR"}, "A clip needs a name - it is what the exported file is called.")
            return {"CANCELLED"}

        action = bpy.data.actions.new(self.clip_name.strip())
        action.use_fake_user = True
        action.tw_skeleton_name = skeleton_name_for(armature_object)
        action.tw_frame_rate = float(self.frame_rate)
        armature_object.animation_data_create().action = action
        context.scene.frame_start = FIRST_FRAME
        context.scene.frame_end = FIRST_FRAME + self.frame_count - 1
        context.scene.render.fps = self.frame_rate
        context.scene.render.fps_base = 1.0
        context.scene.frame_set(FIRST_FRAME)

        if action.name != self.clip_name.strip():
            self.report(
                {"WARNING"},
                f"'{self.clip_name.strip()}' was already taken, so this one is '{action.name}' - which "
                "is the name it will export under.",
            )
        self.report({"INFO"}, f"Created '{action.name}'. Pose the bones and key them with I.")
        return {"FINISHED"}


class TW_OT_validate_animation(bpy.types.Operator):
    bl_idname = "tw_buildings.validate_animation"
    bl_label = "Validate"
    bl_description = "Check the selected clip for problems and list them in the status bar, before exporting it"
    bl_options = {"REGISTER"}

    def execute(self, context: bpy.types.Context):
        armature_object = animation_armature(context)
        action = armature_object.animation_data.action if armature_object and armature_object.animation_data else None
        try:
            issues = validate_animation(armature_object, action, context.scene)
        except Exception as error:  # noqa: BLE001
            self.report({"ERROR"}, f"Validation could not complete: {error}")
            return {"CANCELLED"}
        if not issues:
            self.report({"INFO"}, f"'{action.name}' looks good - no problems found.")
            return {"FINISHED"}
        for issue in issues:
            self.report({issue.severity}, issue.message)
        return {"FINISHED"}


class TW_PG_animation_clip_choice(bpy.types.PropertyGroup):
    export: bpy.props.BoolProperty(name="Export", default=False)


class TW_OT_export_animation(BobWaitMixin, bpy.types.Operator):
    bl_idname = "tw_buildings.export_animation"
    bl_label = "Export Animation"
    bl_description = (
        "Validate the ticked clips of this skeleton, write each out as a .CS2, and build them into "
        "game-ready .anim files. A batch is several clips of one skeleton - a clip poses the skeleton "
        "it was authored against, so two skeletons cannot share one export"
    )
    bl_options = {"REGISTER"}
    bob_subject = "animation"

    directory: bpy.props.StringProperty(subtype="DIR_PATH")
    compile_with_bob: bpy.props.BoolProperty(
        name="Compile With BOB",
        description=(
            "Build the exported clips into the game-ready .anim files straight away, instead of opening "
            "BOB and setting the build up by hand. Only possible when exporting into the Assembly Kit's "
            "raw_data folder"
        ),
        default=True,
    )
    clips: bpy.props.CollectionProperty(type=TW_PG_animation_clip_choice, options={"HIDDEN"})

    def invoke(self, context: bpy.types.Context, event: bpy.types.Event):
        armature_object = self._armature(context)
        if armature_object is None:
            return {"CANCELLED"}
        available = clips_for(armature_object)
        if not available:
            self.report({"ERROR"}, f"There is no clip in this file that belongs to '{armature_object.name}'.")
            return {"CANCELLED"}
        assigned = armature_object.animation_data.action if armature_object.animation_data else None
        self.clips.clear()
        for action in available:
            choice = self.clips.add()
            choice.name = action.name
            choice.export = action == assigned
        context.window_manager.fileselect_add(self)
        return {"RUNNING_MODAL"}

    def draw(self, context: bpy.types.Context) -> None:
        layout = self.layout
        layout.prop(self, "compile_with_bob")
        box = layout.box()
        box.label(text="Clips to export", icon="ANIM")
        for choice in self.clips:
            box.prop(choice, "export", text=choice.name)

    # Two selected skeletons are refused rather than silently resolved: animation_armature would pick
    # whichever happens to be active, and the artist would get one skeleton's clips exported under the
    # impression that both were.
    def _armature(self, context: bpy.types.Context) -> bpy.types.Object | None:
        selected = [obj for obj in (context.selected_objects or []) if obj.type == "ARMATURE"]
        if len(selected) > 1:
            names = ", ".join(obj.name for obj in selected)
            self.report(
                {"ERROR"},
                f"One export builds clips of one skeleton, and {len(selected)} are selected ({names}). "
                "Select just the one whose clips you want built.",
            )
            return None
        armature_object = animation_armature(context)
        if armature_object is None:
            self.report({"ERROR"}, "A clip animates a skeleton, and there is none in the scene.")
        return armature_object

    def execute(self, context: bpy.types.Context):
        armature_object = self._armature(context)
        if armature_object is None:
            return {"CANCELLED"}
        actions = self._chosen_actions(armature_object)
        if not actions:
            self.report({"ERROR"}, "Tick at least one clip to export.")
            return {"CANCELLED"}
        if not self.directory:
            self.report({"ERROR"}, "Choose an output folder first.")
            return {"CANCELLED"}
        try:
            assembly_kit_root = get_assembly_kit_root(context)
        except Exception:  # noqa: BLE001
            self.report({"ERROR"}, "Set the Assembly Kit folder in the add-on preferences first.")
            return {"CANCELLED"}

        names = [action.name for action in actions]
        results = [
            export_animation(armature_object, action, self.directory, assembly_kit_root, context)
            for action in actions
        ]
        report_export_warnings(self, names, results)
        blocked = export_failure_message(names, results)
        if blocked is not None:
            self.report({"ERROR"}, blocked)
            if not bpy.app.background:
                bpy.ops.tw_buildings.export_blocked(
                    "INVOKE_DEFAULT", message=blocked, headline=export_blocked_headline(len(actions), "clip")
                )
            return {"CANCELLED"}

        message = "\n".join(result.message for result in results)
        cs2_paths = [result.cs2_path for result in results]
        if not self.compile_with_bob:
            self.report({"INFO"}, message)
            return {"FINISHED"}
        return self.wait_for_bob(
            context, lambda: start_animation_batch(assembly_kit_root, cs2_paths), message
        )

    # Called from a script, invoke() never ran and self.clips is empty - the clip the skeleton is
    # holding is then the one to export, which is exactly what the button did before batching.
    def _chosen_actions(self, armature_object: bpy.types.Object) -> list[bpy.types.Action]:
        if not self.clips:
            assigned = armature_object.animation_data.action if armature_object.animation_data else None
            return [assigned] if assigned is not None else []
        chosen = [bpy.data.actions.get(choice.name) for choice in self.clips if choice.export]
        return [action for action in chosen if action is not None]


CLASSES = (
    TW_PG_animation_clip_choice,
    TW_OT_set_animation_clip,
    TW_OT_clear_animation_clip,
    TW_OT_delete_animation_clip,
    TW_OT_new_animation_clip,
    TW_OT_validate_animation,
    TW_OT_export_animation,
)


def register() -> None:
    for cls in CLASSES:
        bpy.utils.register_class(cls)


def unregister() -> None:
    for cls in reversed(CLASSES):
        bpy.utils.unregister_class(cls)
