import bpy

from bob.cli import start_skeleton_batch, start_unit_build
from export.skeleton_exporter import export_skeleton
from export.unit_exporter import export_unit
from extraction.unit_extract import find_unit_armature, unit_model_collections
from props.properties import (
    get_assembly_kit_root,
    NO_BONE_TYPE,
    TW_ROLE_LABELS,
    UNIT_PART_KIND_ITEMS,
)
from validation.rules import validate_skeleton, validate_unit
from .collection_utils import find_skeleton_collection, find_unit_collection
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


class TW_OT_export_skeleton(ExportTargetsMixin, BobWaitMixin, bpy.types.Operator):
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

        names = [skeleton.name for skeleton in skeletons]
        results = [export_skeleton(skeleton, self.directory, assembly_kit_root) for skeleton in skeletons]
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


class TW_OT_export_units(ExportTargetsMixin, BobWaitMixin, bpy.types.Operator):
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
        if self.collect_targets(context) is None:
            return {"CANCELLED"}
        context.window_manager.fileselect_add(self)
        return {"RUNNING_MODAL"}

    def draw(self, context: bpy.types.Context) -> None:
        draw_export_targets(self.layout, self.targets, "Unit asset", "unit assets")
        self.layout.prop(self, "compile_with_bob")

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

        names = [unit.name for unit in units]
        results = [export_unit(unit, self.directory, assembly_kit_root, context) for unit in units]
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
        return self.wait_for_bob(context, lambda: start_unit_build(assembly_kit_root, cs2_paths), message)


CLASSES = (
    TW_OT_new_unit,
    TW_OT_new_unit_mesh,
    TW_OT_new_attachment_point,
    TW_OT_bind_to_skeleton,
    TW_OT_new_skeleton,
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
