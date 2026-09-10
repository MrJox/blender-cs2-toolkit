import bpy

from bob.cli import start_skeleton_batch, start_unit_build
from export.skeleton_exporter import export_skeleton
from export.unit_exporter import export_unit
from extraction.animation_extract import sample_bone_matrices
from extraction.unit_extract import find_unit_armature, skeleton_name_for, unit_model_collections
from props.properties import (
    get_assembly_kit_root,
    NO_BONE_TYPE,
    TW_ROLE_LABELS,
    UNIT_PART_KIND_ITEMS,
)
from validation.rules import validate_skeleton, validate_unit
from .animation_operators import clips_for
from .collection_utils import find_skeleton_collection, find_unit_collection
from .rules_options import SkeletonRulesOptions, UnitRulesOptions
from .operators import (
    BobWaitMixin,
    draw_export_targets,
    export_blocked_headline,
    export_failure_message,
    ExportTargetsMixin,
    report_export_warnings,
)


def _new_child_collection(parent: bpy.types.Collection, role: str) -> bpy.types.Collection:
    collection = bpy.data.collections.new(TW_ROLE_LABELS[role])
    collection.tw_role = role
    parent.children.link(collection)
    return collection


class TW_OT_new_unit(bpy.types.Operator):
    bl_idname = "tw_buildings.new_unit"
    bl_label = "New Unit Asset"
    bl_description = (
        "Create a unit asset - one exported model file, holding the models it is built from. A soldier's "
        "body and his sword are two assets, joined in game by a .variantmeshdefinition"
    )
    bl_options = {"REGISTER", "UNDO"}

    asset_name: bpy.props.StringProperty(
        name="Asset Name",
        default="new_unit_asset",
        description="What this asset exports as - the .CS2 and the .rigid_model_v2 take this name",
    )

    def invoke(self, context: bpy.types.Context, event: bpy.types.Event):
        return context.window_manager.invoke_props_dialog(self)

    def execute(self, context: bpy.types.Context):
        if not self.asset_name.strip():
            self.report({"ERROR"}, "A unit asset needs a name - it is what the exported file is called.")
            return {"CANCELLED"}
        try:
            collection = bpy.data.collections.new(self.asset_name.strip())
            collection.tw_role = "UNIT"
            context.scene.collection.children.link(collection)
        except Exception as error:  # noqa: BLE001
            self.report({"ERROR"}, f"Could not create unit asset: {error}")
            return {"CANCELLED"}
        if collection.name != self.asset_name.strip():
            self.report(
                {"WARNING"},
                f"'{self.asset_name.strip()}' was already taken, so this one is '{collection.name}' - "
                "which is the name it will export under.",
            )
        self.report({"INFO"}, f"Created '{collection.name}'. Add a Unit Model next.")
        return {"FINISHED"}


class TW_OT_new_unit_mesh(bpy.types.Operator):
    bl_idname = "tw_buildings.new_unit_mesh"
    bl_label = "New Unit Model"
    bl_description = (
        "Add a model to the selected unit asset - one named mesh in the exported file, holding its own "
        "LOD meshes. A head asset carries one for the head and another for the eyes and tongue"
    )
    bl_options = {"REGISTER", "UNDO"}

    model_name: bpy.props.StringProperty(
        name="Model Name",
        default="new_model",
        description="The mesh's own name inside the exported file",
    )
    kind: bpy.props.EnumProperty(items=UNIT_PART_KIND_ITEMS, name="Model Type", default="WEIGHTED")

    def invoke(self, context: bpy.types.Context, event: bpy.types.Event):
        unit = find_unit_collection(context)
        if unit is None:
            self.report({"ERROR"}, "Select a Unit Asset collection in the Outliner first.")
            return {"CANCELLED"}
        # Every model in an asset has to be the same type, so a second one follows the first.
        existing = unit_model_collections(unit)
        if existing:
            self.kind = existing[0].tw_unit_part_kind
        return context.window_manager.invoke_props_dialog(self)

    def execute(self, context: bpy.types.Context):
        unit = find_unit_collection(context)
        if unit is None:
            self.report({"ERROR"}, "Select a Unit Asset collection in the Outliner first.")
            return {"CANCELLED"}
        if not self.model_name.strip():
            self.report({"ERROR"}, "A model needs a name - it becomes the mesh's name in the file.")
            return {"CANCELLED"}
        try:
            model = bpy.data.collections.new(self.model_name.strip())
            model.tw_role = "UNIT_MESH"
            model.tw_unit_part_kind = self.kind
            unit.children.link(model)
        except Exception as error:  # noqa: BLE001
            self.report({"ERROR"}, f"Could not create model: {error}")
            return {"CANCELLED"}
        self.report({"INFO"}, f"Created '{model.name}'. Add its LOD meshes and set each one's LOD Level.")
        return {"FINISHED"}


class TW_OT_new_skeleton(bpy.types.Operator):
    bl_idname = "tw_buildings.new_skeleton"
    bl_label = "New Skeleton"
    bl_description = (
        "Create a skeleton holding a new, empty Blender Armature, named after the files it exports as. "
        "Add its bones in Blender's own Edit Mode"
    )
    bl_options = {"REGISTER", "UNDO"}

    asset_name: bpy.props.StringProperty(
        name="Skeleton Name",
        default="new_skeleton",
        description=(
            "What this skeleton exports as - the .CS2 and .bone_table take this name, and it is the "
            "name a weighted model's rules.bob quotes for BOB to resolve"
        ),
    )

    def invoke(self, context: bpy.types.Context, event: bpy.types.Event):
        return context.window_manager.invoke_props_dialog(self)

    def execute(self, context: bpy.types.Context):
        if not self.asset_name.strip():
            self.report({"ERROR"}, "A skeleton needs a name - it is what the exported files are called.")
            return {"CANCELLED"}
        try:
            # Its own root collection, not nested under a unit: one skeleton is shared by every
            # model weighted to it, so it does not belong to any single unit asset.
            collection = bpy.data.collections.new(self.asset_name.strip())
            collection.tw_role = "SKELETON"
            context.scene.collection.children.link(collection)

            armature = bpy.data.armatures.new(collection.name)
            armature_object = bpy.data.objects.new(collection.name, armature)
            collection.objects.link(armature_object)
        except Exception as error:  # noqa: BLE001
            self.report({"ERROR"}, f"Could not create skeleton: {error}")
            return {"CANCELLED"}
        if collection.name != self.asset_name.strip():
            self.report(
                {"WARNING"},
                f"'{self.asset_name.strip()}' was already taken, so this one is '{collection.name}' - "
                "which is the name it will export under.",
            )
        self.report({"INFO"}, f"Created '{collection.name}'. Add bones to '{armature_object.name}' in Edit Mode.")
        return {"FINISHED"}


def _restamp_clips(old_name: str, new_name: str) -> int:
    # An unstamped clip carries no name to correct - it belongs to whatever Armature it is on until
    # an export stamps it - and one stamped for another skeleton genuinely belongs there, so only an
    # exact (case-insensitive) match moves.
    wanted = old_name.lower()
    restamped = 0
    for action in bpy.data.actions:
        if action.tw_skeleton_name.lower() == wanted:
            action.tw_skeleton_name = new_name
            restamped += 1
    return restamped


class TW_OT_rename_skeleton(bpy.types.Operator):
    bl_idname = "tw_buildings.rename_skeleton"
    bl_label = "Rename Skeleton"
    bl_description = (
        "Rename this skeleton everywhere at once - its collection, its Armature, and the skeleton "
        "stamp on every clip authored against it. Renaming the collection by hand in the Outliner "
        "leaves those stamps naming the old skeleton"
    )
    bl_options = {"REGISTER", "UNDO"}

    new_name: bpy.props.StringProperty(
        name="New Name",
        description=(
            "What this skeleton exports as from now on - the .CS2 and .bone_table take this name, and "
            "it is the name a weighted model's rules.bob quotes for BOB to resolve"
        ),
    )

    def invoke(self, context: bpy.types.Context, event: bpy.types.Event):
        skeleton = find_skeleton_collection(context)
        if skeleton is None:
            self.report({"ERROR"}, "Select something inside a Skeleton collection first.")
            return {"CANCELLED"}
        self.new_name = skeleton.name
        return context.window_manager.invoke_props_dialog(self)

    def execute(self, context: bpy.types.Context):
        skeleton = find_skeleton_collection(context)
        if skeleton is None:
            self.report({"ERROR"}, "Select something inside a Skeleton collection first.")
            return {"CANCELLED"}
        wanted = self.new_name.strip()
        if not wanted:
            self.report({"ERROR"}, "A skeleton needs a name - it is what the exported files are called.")
            return {"CANCELLED"}

        old_name = skeleton.name
        if wanted == old_name:
            self.report({"INFO"}, f"'{old_name}' is already called that.")
            return {"FINISHED"}

        try:
            # The collection's name is the one that counts - extraction.skeleton_name_for reads it,
            # and it is what reaches BOB as the rules.bob AnimationType. The Armature object and its
            # data follow so the Outliner and the panels do not disagree with the exported file.
            skeleton.name = wanted
            armatures = [obj for obj in skeleton.all_objects if obj.type == "ARMATURE"]
            for armature_object in armatures:
                armature_object.name = skeleton.name
                armature_object.data.name = skeleton.name
            restamped = _restamp_clips(old_name, skeleton.name)
        except Exception as error:  # noqa: BLE001
            self.report({"ERROR"}, f"Could not rename skeleton: {error}")
            return {"CANCELLED"}

        if skeleton.name != wanted:
            self.report(
                {"WARNING"},
                f"'{wanted}' was already taken, so this skeleton is '{skeleton.name}' - which is the "
                "name it will export under.",
            )
        # Models keep up on their own: an Armature modifier holds a pointer, not a name, and vertex
        # groups are named after bones rather than the skeleton.
        self.report(
            {"INFO"},
            f"Renamed '{old_name}' to '{skeleton.name}' - {len(armatures)} Armature(s) and "
            f"{restamped} clip(s) followed.",
        )
        return {"FINISHED"}


def _action_channelbags(action: bpy.types.Action):
    # Slotted actions (Blender 4.4+) hold their curves per channelbag rather than on the Action, and
    # the add-on still opens files authored before that - same walk validation.action_data_paths does.
    if hasattr(action, "fcurves"):
        yield action
        return
    for layer in action.layers:
        for strip in layer.strips:
            if strip.type != "KEYFRAME":
                continue
            for slot in action.slots:
                channelbag = strip.channelbag(slot)
                if channelbag is not None:
                    yield channelbag


def _bone_path_prefix(bone_name: str) -> str:
    return f'pose.bones["{bone_name}"]'


def _animates_bone(action: bpy.types.Action, bone_name: str) -> bool:
    prefix = _bone_path_prefix(bone_name)
    return any(
        fcurve.data_path.startswith(prefix)
        for channelbag in _action_channelbags(action)
        for fcurve in channelbag.fcurves
    )


def _drop_bone_curves(action: bpy.types.Action, bone_name: str) -> None:
    prefix = _bone_path_prefix(bone_name)
    for channelbag in _action_channelbags(action):
        for fcurve in [fc for fc in channelbag.fcurves if fc.data_path.startswith(prefix)]:
            channelbag.fcurves.remove(fcurve)


class TW_OT_remove_bone_keep_motion(bpy.types.Operator):
    bl_idname = "tw_buildings.remove_bone_keep_motion"
    bl_label = "Remove Bone, Keep Its Motion"
    bl_description = (
        "Delete the active bone from the skeleton and fold the motion it carried into its children, "
        "in every clip of this skeleton at once. Deleting it by hand in Edit Mode instead leaves the "
        "children standing still, because what moved them was their parent"
    )
    bl_options = {"REGISTER", "UNDO"}

    inherit_bone_type: bpy.props.BoolProperty(
        name="Give Its Bone Type To The Child",
        description=(
            "Pass the deleted bone's Bone Type, sort order and flags to its one child. The rules.bob "
            "written beside a clip keeps translation only on Root and Floating bones, so a root bone's "
            "travel is dropped at compile time if the bone that inherits it is neither"
        ),
        default=True,
    )

    def invoke(self, context: bpy.types.Context, event: bpy.types.Event):
        if self._target(context)[0] is None:
            return {"CANCELLED"}
        return context.window_manager.invoke_props_dialog(self)

    def draw(self, context: bpy.types.Context) -> None:
        armature_object, bone = self._target(context)
        layout = self.layout
        if bone is None:
            return
        children = [child.name for child in bone.children]
        clips = [
            action for action in clips_for(armature_object) if _animates_bone(action, bone.name)
        ]
        layout.label(text=f"Delete '{bone.name}'", icon="BONE_DATA")
        if children:
            layout.label(text=f"Its motion moves to: {', '.join(children)}", icon="FORWARD")
        else:
            layout.label(text="It has no children - its motion is lost", icon="ERROR")
        layout.label(text=f"{len(clips)} clip(s) will be rewritten", icon="ANIM")
        if len(children) == 1 and bone.tw_bone_type != NO_BONE_TYPE:
            layout.prop(self, "inherit_bone_type")

    def _target(self, context: bpy.types.Context):
        skeleton = find_skeleton_collection(context)
        if skeleton is None:
            self.report({"ERROR"}, "Select something inside a Skeleton collection first.")
            return None, None
        armature_object = next(
            (obj for obj in skeleton.all_objects if obj.type == "ARMATURE"), None
        )
        if armature_object is None:
            self.report({"ERROR"}, f"'{skeleton.name}' holds no Armature.")
            return None, None
        bone = armature_object.data.bones.active
        if bone is None:
            self.report({"ERROR"}, "Pick the bone to remove in the Armature first.")
            return armature_object, None
        return armature_object, bone

    def execute(self, context: bpy.types.Context):
        armature_object, bone = self._target(context)
        if armature_object is None or bone is None:
            return {"CANCELLED"}
        if armature_object.mode == "EDIT":
            self.report({"ERROR"}, "Leave Edit Mode first - the clips are rewritten in Pose space.")
            return {"CANCELLED"}

        bone_name = bone.name
        child_names = [child.name for child in bone.children]
        parent_name = bone.parent.name if bone.parent else ""
        inherited = self._bone_type_of(bone) if len(child_names) == 1 and self.inherit_bone_type else None
        scene = context.scene
        depsgraph = context.evaluated_depsgraph_get()
        clips = [action for action in clips_for(armature_object) if _animates_bone(action, bone_name)]

        try:
            # Every clip is sampled before the bone goes, because once it is deleted the motion it
            # carried cannot be recovered from anywhere.
            recorded = {
                action.name: sample_bone_matrices(
                    armature_object, action, child_names, scene, depsgraph
                )
                for action in clips
            }
            self._delete_bone(context, armature_object, bone_name)
            for action in clips:
                self._rewrite(armature_object, action, recorded[action.name], parent_name, scene, depsgraph)
                _drop_bone_curves(action, bone_name)
            if inherited is not None:
                self._apply_bone_type(armature_object.data.bones[child_names[0]], inherited)
        except Exception as error:  # noqa: BLE001
            self.report({"ERROR"}, f"Could not remove '{bone_name}': {error}")
            return {"CANCELLED"}

        if not child_names:
            self.report(
                {"WARNING"},
                f"Removed '{bone_name}' from {len(clips)} clip(s). It had no children, so the motion it "
                "carried is gone rather than inherited.",
            )
            return {"FINISHED"}
        self.report(
            {"INFO"},
            f"Removed '{bone_name}'. Its motion is now carried by {', '.join(child_names)} "
            f"across {len(clips)} clip(s).",
        )
        return {"FINISHED"}

    def _bone_type_of(self, bone) -> tuple[str, int, int]:
        return bone.tw_bone_type, bone.tw_bone_sort_order, bone.tw_bone_flags

    def _apply_bone_type(self, bone, inherited: tuple[str, int, int]) -> None:
        bone.tw_bone_type, bone.tw_bone_sort_order, bone.tw_bone_flags = inherited

    def _delete_bone(self, context: bpy.types.Context, armature_object, bone_name: str) -> None:
        previous_active = context.view_layer.objects.active
        context.view_layer.objects.active = armature_object
        previous_mode = armature_object.mode
        bpy.ops.object.mode_set(mode="EDIT")
        try:
            edit_bones = armature_object.data.edit_bones
            target = edit_bones[bone_name]
            for child in list(target.children):
                # A connected child is glued to its parent's tail, so re-parenting it without
                # breaking that would drag it onto the grandparent's tail instead.
                child.use_connect = False
                child.parent = target.parent
            edit_bones.remove(target)
        finally:
            bpy.ops.object.mode_set(mode="OBJECT")
            if previous_mode != "OBJECT":
                bpy.ops.object.mode_set(mode=previous_mode)
            context.view_layer.objects.active = previous_active

    def _rewrite(self, armature_object, action, recorded, parent_name, scene, depsgraph) -> None:
        bones = armature_object.data.bones
        parent_frames = (
            sample_bone_matrices(armature_object, action, [parent_name], scene, depsgraph)
            if parent_name
            else {}
        )
        original_frame = scene.frame_current
        animation_data = armature_object.animation_data_create()
        previous_action = animation_data.action
        animation_data.action = action
        try:
            for frame, matrices in sorted(recorded.items()):
                scene.frame_set(frame)
                for name, world in matrices.items():
                    # The same composition importer.anim_importer.bake_clip inverts, which was
                    # measured against a real armature: a bone's pose is its parent's pose carried
                    # through both rest matrices, then its own basis.
                    reference = bones[name].matrix_local
                    if parent_name:
                        parent_world = parent_frames[frame][parent_name]
                        reference = parent_world @ bones[parent_name].matrix_local.inverted() @ reference
                    pose_bone = armature_object.pose.bones[name]
                    pose_bone.rotation_mode = "QUATERNION"
                    pose_bone.matrix_basis = reference.inverted() @ world
                    pose_bone.keyframe_insert(data_path="location", frame=frame)
                    pose_bone.keyframe_insert(data_path="rotation_quaternion", frame=frame)
        finally:
            animation_data.action = previous_action
            scene.frame_set(original_frame)


class TW_OT_validate_skeleton(bpy.types.Operator):
    bl_idname = "tw_buildings.validate_skeleton"
    bl_label = "Validate"
    bl_description = "Check the selected skeleton for problems and list them in the status bar, before exporting it"
    bl_options = {"REGISTER"}

    def execute(self, context: bpy.types.Context):
        skeleton = find_skeleton_collection(context)
        if skeleton is None:
            self.report({"ERROR"}, "Select something inside a Skeleton collection first.")
            return {"CANCELLED"}
        try:
            issues = validate_skeleton(skeleton)
        except Exception as error:  # noqa: BLE001
            self.report({"ERROR"}, f"Validation could not complete: {error}")
            return {"CANCELLED"}
        if not issues:
            self.report({"INFO"}, f"'{skeleton.name}' looks good - no problems found.")
            return {"FINISHED"}
        for issue in issues:
            self.report({issue.severity}, issue.message)
        return {"FINISHED"}


class TW_OT_export_skeleton(ExportTargetsMixin, BobWaitMixin, SkeletonRulesOptions, bpy.types.Operator):
    bl_idname = "tw_buildings.export_skeleton"
    bl_label = "Export Skeleton"
    bl_description = (
        "Validate every selected skeleton, write each out as a .CS2 with its .bone_table, and build "
        "them into the game-ready skeleton files. Select several skeletons to build them all in one go"
    )
    bl_options = {"REGISTER"}
    bob_subject = "skeleton"
    asset_role = "SKELETON"
    asset_noun = "skeleton"

    def find_one(self, context: bpy.types.Context) -> bpy.types.Collection | None:
        return find_skeleton_collection(context)

    directory: bpy.props.StringProperty(subtype="DIR_PATH")
    compile_with_bob: bpy.props.BoolProperty(
        name="Compile With BOB",
        description=(
            "Build the exported skeleton into its game-ready files straight away, instead of opening BOB "
            "and setting the build up by hand. Only possible when exporting into the Assembly Kit's "
            "raw_data folder"
        ),
        default=True,
    )

    def invoke(self, context: bpy.types.Context, event: bpy.types.Event):
        if self.collect_targets(context) is None:
            return {"CANCELLED"}
        context.window_manager.fileselect_add(self)
        return {"RUNNING_MODAL"}

    def draw(self, context: bpy.types.Context) -> None:
        draw_export_targets(self.layout, self.targets, "Skeleton", "skeletons")
        self.layout.prop(self, "compile_with_bob")
        self.draw_rules_options(self.layout)

    def execute(self, context: bpy.types.Context):
        skeletons = self.resolve_targets(context)
        if skeletons is None:
            return {"CANCELLED"}
        if not self.directory:
            self.report({"ERROR"}, "Choose an output folder first.")
            return {"CANCELLED"}
        try:
            assembly_kit_root = get_assembly_kit_root(context)
        except Exception:  # noqa: BLE001
            self.report({"ERROR"}, "Set the Assembly Kit folder in the add-on preferences first.")
            return {"CANCELLED"}

        blocked_on_rules = self.blocked_on_rules_overwrite(context, assembly_kit_root)
        if blocked_on_rules is not None:
            return blocked_on_rules

        names = [skeleton.name for skeleton in skeletons]
        rules_settings = self.rules_settings_or_none()
        results = [
            export_skeleton(
                skeleton,
                self.directory,
                assembly_kit_root,
                rules_settings,
                self.rules_overwrite_confirmed,
            )
            for skeleton in skeletons
        ]
        report_export_warnings(self, names, results)
        blocked = export_failure_message(names, results)
        if blocked is not None:
            self.report({"ERROR"}, blocked)
            if not bpy.app.background:
                bpy.ops.tw_buildings.export_blocked(
                    "INVOKE_DEFAULT",
                    message=blocked,
                    headline=export_blocked_headline(len(skeletons), "skeleton"),
                )
            return {"CANCELLED"}

        message = "\n".join(result.message for result in results)
        cs2_paths = [result.cs2_path for result in results]
        if not self.compile_with_bob:
            self.report({"INFO"}, message)
            return {"FINISHED"}
        return self.wait_for_bob(
            context, lambda: start_skeleton_batch(assembly_kit_root, cs2_paths), message
        )


# Blender frees a dynamic enum's strings unless something else holds them, so the last list built
# stays referenced here.
_bone_items: list[tuple[str, str, str]] = []


def _attachment_bone_items(self, context):
    global _bone_items
    unit = find_unit_collection(context)
    armature_object = find_unit_armature(unit) if unit is not None else None
    _bone_items = (
        [(bone.name, bone.name, "") for bone in armature_object.data.bones]
        if armature_object is not None
        else []
    )
    return _bone_items


class TW_OT_new_attachment_point(bpy.types.Operator):
    bl_idname = "tw_buildings.new_attachment_point"
    bl_label = "New Attachment Point"
    bl_description = (
        "Add an attachment point to this asset - the named socket a weapon, shield or crest is hung from "
        "in game. Pick the bone it rides on, then move it to where the item should sit"
    )
    bl_options = {"REGISTER", "UNDO"}

    point_name: bpy.props.StringProperty(
        name="Name",
        default="weapon_01",
        description="The name the game looks this socket up by - 'weapon_01', 'crest_centre'. A .variantmeshdefinition binds an item to it by this name",
    )
    bone: bpy.props.EnumProperty(
        items=_attachment_bone_items,
        name="Bone",
        description="The skeleton bone this point rides on - whatever is attached here follows it",
    )

    def invoke(self, context: bpy.types.Context, event: bpy.types.Event):
        unit = find_unit_collection(context)
        if unit is None:
            self.report({"ERROR"}, "Select a Unit Asset collection in the Outliner first.")
            return {"CANCELLED"}
        armature_object = find_unit_armature(unit)
        if armature_object is None:
            self.report(
                {"ERROR"},
                "An attachment point rides on a skeleton bone, and this asset is not bound to a "
                "skeleton yet - give its models an Armature modifier first.",
            )
            return {"CANCELLED"}
        active_bone = armature_object.data.bones.active
        if active_bone is not None:
            self.bone = active_bone.name
        return context.window_manager.invoke_props_dialog(self)

    def execute(self, context: bpy.types.Context):
        unit = find_unit_collection(context)
        if unit is None:
            self.report({"ERROR"}, "Select a Unit Asset collection in the Outliner first.")
            return {"CANCELLED"}
        armature_object = find_unit_armature(unit)
        if armature_object is None:
            self.report({"ERROR"}, "This asset is not bound to a skeleton yet.")
            return {"CANCELLED"}
        if not self.point_name:
            self.report({"ERROR"}, "An attachment point needs a name.")
            return {"CANCELLED"}
        if self.bone not in armature_object.data.bones:
            self.report({"ERROR"}, "Pick the bone this attachment point rides on.")
            return {"CANCELLED"}
        try:
            empty = bpy.data.objects.new(self.point_name, None)
            empty.empty_display_type = "ARROWS"
            empty.empty_display_size = 0.05
            empty.tw_attachment_point_name = self.point_name
            unit.objects.link(empty)
            empty.parent = armature_object
            empty.parent_type = "BONE"
            empty.parent_bone = self.bone
        except Exception as error:  # noqa: BLE001
            self.report({"ERROR"}, f"Could not create attachment point: {error}")
            return {"CANCELLED"}
        self.report({"INFO"}, f"Created '{empty.name}' on bone '{self.bone}'. Move it into place.")
        return {"FINISHED"}


# Blender frees a dynamic enum's strings unless something else holds them, so the last list built
# stays referenced here.
_skeleton_items: list[tuple[str, str, str]] = []


def _skeleton_collection_items(self, context):
    global _skeleton_items
    _skeleton_items = [
        (collection.name, collection.name, "")
        for collection in bpy.data.collections
        if collection.tw_role == "SKELETON" and any(obj.type == "ARMATURE" for obj in collection.all_objects)
    ]
    return _skeleton_items


class TW_OT_bind_to_skeleton(bpy.types.Operator):
    bl_idname = "tw_buildings.bind_to_skeleton"
    bl_label = "Bind To Skeleton"
    bl_description = (
        "Skin every mesh in this asset to the chosen skeleton, adding the Armature modifier each one "
        "needs. Paint the weights with Blender's own tools, onto vertex groups named after the bones"
    )
    bl_options = {"REGISTER", "UNDO"}

    skeleton: bpy.props.EnumProperty(
        items=_skeleton_collection_items,
        name="Skeleton",
        description="Which skeleton in the scene this asset's models are weighted to",
    )

    def invoke(self, context: bpy.types.Context, event: bpy.types.Event):
        unit = find_unit_collection(context)
        if unit is None:
            self.report({"ERROR"}, "Select a Unit Asset collection in the Outliner first.")
            return {"CANCELLED"}
        if not _skeleton_collection_items(self, context):
            self.report(
                {"ERROR"},
                "There is no skeleton in the scene to bind to - import one through File > Import, or "
                "make one in the Skeleton workflow.",
            )
            return {"CANCELLED"}
        return context.window_manager.invoke_props_dialog(self)

    def execute(self, context: bpy.types.Context):
        unit = find_unit_collection(context)
        if unit is None:
            self.report({"ERROR"}, "Select a Unit Asset collection in the Outliner first.")
            return {"CANCELLED"}
        collection = bpy.data.collections.get(self.skeleton)
        armature_object = next(
            (obj for obj in collection.all_objects if obj.type == "ARMATURE"), None
        ) if collection is not None else None
        if armature_object is None:
            self.report({"ERROR"}, f"'{self.skeleton}' holds no Armature.")
            return {"CANCELLED"}

        bound = 0
        for model in unit_model_collections(unit):
            if model.tw_unit_part_kind != "WEIGHTED":
                continue
            for obj in model.objects:
                if obj.type != "MESH":
                    continue
                modifier = next((m for m in obj.modifiers if m.type == "ARMATURE"), None)
                if modifier is None:
                    modifier = obj.modifiers.new(name="Armature", type="ARMATURE")
                modifier.object = armature_object
                # A vertex group per *game* bone, so weight painting has something to paint into -
                # Blender makes none when the modifier is added rather than parented. Only the bones
                # the bone table lists: rome_man_game has 228 nodes but 50 game bones, and the other
                # 178 are ref_/end_/drive_ helpers the engine never indexes, so offering them would
                # bury the real ones. A skeleton imported without a bone table lists none, and then
                # every bone is offered rather than nothing.
                paintable = [bone for bone in armature_object.data.bones if bone.tw_bone_type != NO_BONE_TYPE]
                for bone in paintable or armature_object.data.bones:
                    if bone.name not in obj.vertex_groups:
                        obj.vertex_groups.new(name=bone.name)
                bound += 1

        if not bound:
            self.report(
                {"WARNING"},
                f"'{unit.name}' has no Weighted Model meshes to bind - a Rigid Model is attached by a "
                ".variantmeshdefinition instead, and needs no skeleton.",
            )
            return {"FINISHED"}
        self.report(
            {"INFO"},
            f"Bound {bound} mesh(es) in '{unit.name}' to '{armature_object.name}'. Weight paint them "
            "against its bones next.",
        )
        return {"FINISHED"}


class TW_OT_validate_unit(bpy.types.Operator):
    bl_idname = "tw_buildings.validate_unit"
    bl_label = "Validate"
    bl_description = "Check the selected unit asset's models for problems and list them in the status bar, before exporting them"
    bl_options = {"REGISTER"}

    def execute(self, context: bpy.types.Context):
        unit = find_unit_collection(context)
        if unit is None:
            self.report({"ERROR"}, "Select something inside a Unit Asset collection first.")
            return {"CANCELLED"}
        try:
            issues = validate_unit(unit)
        except Exception as error:  # noqa: BLE001
            self.report({"ERROR"}, f"Validation could not complete: {error}")
            return {"CANCELLED"}
        subject = unit
        if not issues:
            self.report({"INFO"}, f"'{subject.name}' looks good - no problems found.")
            return {"FINISHED"}
        for issue in issues:
            self.report({issue.severity}, issue.message)
        return {"FINISHED"}


# The folder default only means anything when the whole batch agrees on one skeleton. Two different
# ones, or none at all, leaves it empty - which is what a folder of weapons and shields wants anyway,
# and every asset still carries its own line.
def _bound_skeleton_name(units: list[bpy.types.Collection]) -> str:
    armatures = [find_unit_armature(unit) for unit in units]
    names = {skeleton_name_for(armature) for armature in armatures if armature is not None}
    return names.pop() if len(names) == 1 else ""


class TW_OT_export_units(ExportTargetsMixin, BobWaitMixin, UnitRulesOptions, bpy.types.Operator):
    bl_idname = "tw_buildings.export_units"
    bl_label = "Export Unit Models"
    bl_description = (
        "Validate every selected unit asset, write its models out as .CS2 files, and build them all "
        "into game-ready models in one go. Select several assets to build them together"
    )
    bl_options = {"REGISTER"}
    bob_subject = "unit"
    asset_role = "UNIT"
    asset_noun = "unit asset"

    def find_one(self, context: bpy.types.Context) -> bpy.types.Collection | None:
        return find_unit_collection(context)

    directory: bpy.props.StringProperty(subtype="DIR_PATH")
    compile_with_bob: bpy.props.BoolProperty(
        name="Compile With BOB",
        description=(
            "Build the exported models into game-ready .rigid_model_v2 files straight away, instead of "
            "opening BOB and setting the build up by hand. Only possible when exporting into the "
            "Assembly Kit's raw_data folder"
        ),
        default=True,
    )

    def invoke(self, context: bpy.types.Context, event: bpy.types.Event):
        units = self.collect_targets(context)
        if units is None:
            return {"CANCELLED"}
        self.rules_animation_type = _bound_skeleton_name(units)
        context.window_manager.fileselect_add(self)
        return {"RUNNING_MODAL"}

    def draw(self, context: bpy.types.Context) -> None:
        draw_export_targets(self.layout, self.targets, "Unit asset", "unit assets")
        self.layout.prop(self, "compile_with_bob")
        self.draw_rules_options(self.layout)

    def execute(self, context: bpy.types.Context):
        units = self.resolve_targets(context)
        if units is None:
            return {"CANCELLED"}
        if not self.directory:
            self.report({"ERROR"}, "Choose an output folder first.")
            return {"CANCELLED"}
        try:
            assembly_kit_root = get_assembly_kit_root(context)
        except Exception:  # noqa: BLE001
            self.report({"ERROR"}, "Set the Assembly Kit folder in the add-on preferences first.")
            return {"CANCELLED"}

        blocked_on_rules = self.blocked_on_rules_overwrite(context, assembly_kit_root)
        if blocked_on_rules is not None:
            return blocked_on_rules

        names = [unit.name for unit in units]
        rules_settings = self.rules_settings_or_none()
        results = [
            export_unit(
                unit,
                self.directory,
                assembly_kit_root,
                context,
                rules_settings,
                self.rules_overwrite_confirmed,
            )
            for unit in units
        ]
        report_export_warnings(self, names, results)
        blocked = export_failure_message(names, results)
        if blocked is not None:
            self.report({"ERROR"}, blocked)
            if not bpy.app.background:
                bpy.ops.tw_buildings.export_blocked(
                    "INVOKE_DEFAULT", message=blocked, headline=export_blocked_headline(len(units), "unit asset")
                )
            return {"CANCELLED"}

        # Every asset's .CS2 files go into one BOB run: PLAN_units.md Phase 5 measured that the Cs2
        # configuration takes one <entry> per file and builds them together, and a batch shares the
        # one export folder the dialog asked for, which is the constraint start_unit_build checks.
        cs2_paths = [path for result in results for path in result.cs2_paths]
        message = "\n".join(result.message for result in results)
        if not self.compile_with_bob:
            self.report({"INFO"}, message)
            return {"FINISHED"}
        target_path = self.rules_settings().target_path
        return self.wait_for_bob(
            context, lambda: start_unit_build(assembly_kit_root, cs2_paths, target_path), message
        )


CLASSES = (
    TW_OT_new_unit,
    TW_OT_new_unit_mesh,
    TW_OT_new_attachment_point,
    TW_OT_bind_to_skeleton,
    TW_OT_new_skeleton,
    TW_OT_rename_skeleton,
    TW_OT_remove_bone_keep_motion,
    TW_OT_validate_skeleton,
    TW_OT_export_skeleton,
    TW_OT_validate_unit,
    TW_OT_export_units,
)


def register() -> None:
    for cls in CLASSES:
        bpy.utils.register_class(cls)


def unregister() -> None:
    for cls in reversed(CLASSES):
        bpy.utils.unregister_class(cls)
