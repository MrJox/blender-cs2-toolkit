import bpy

from bob.cli import start_vegetation_build
from export.vegetation_exporter import export_vegetation
from props.properties import TW_ROLE_LABELS, get_assembly_kit_root
from validation.rules import validate_vegetation
from .collection_utils import find_vegetation_collection
from .rules_options import VegetationRulesOptions
from .operators import (
    BobWaitMixin,
    draw_export_targets,
    export_blocked_headline,
    export_failure_message,
    ExportTargetsMixin,
    report_export_warnings,
)


class TW_OT_new_vegetation(bpy.types.Operator):
    bl_idname = "tw_buildings.new_vegetation"
    bl_label = "New Vegetation Model"
    bl_description = (
        "Create a tree, shrub or stone - one exported file, with a Display collection to put its level "
        "of detail meshes in. The .CS2 and the .rigid_model_v2 both take this name"
    )
    bl_options = {"REGISTER", "UNDO"}

    model_name: bpy.props.StringProperty(
        name="Model Name",
        default="new_tree",
        description="What this model exports as - the .CS2, the .rigid_model_v2 and its _tech.cs2.parsed all take this name",
    )

    def invoke(self, context: bpy.types.Context, event: bpy.types.Event):
        return context.window_manager.invoke_props_dialog(self)

    def execute(self, context: bpy.types.Context):
        name = self.model_name.strip()
        if not name:
            self.report({"ERROR"}, "A vegetation model needs a name - it is what the exported file is called.")
            return {"CANCELLED"}
        try:
            collection = bpy.data.collections.new(name)
            collection.tw_role = "VEGETATION"
            context.scene.collection.children.link(collection)
            display = bpy.data.collections.new(TW_ROLE_LABELS["VEGETATION_DISPLAY"])
            display.tw_role = "VEGETATION_DISPLAY"
            collection.children.link(display)
        except Exception as error:  # noqa: BLE001
            self.report({"ERROR"}, f"Could not create vegetation model: {error}")
            return {"CANCELLED"}
        if collection.name != name:
            self.report(
                {"WARNING"},
                f"'{name}' was already taken, so this one is '{collection.name}' - which is the name it "
                "will export under.",
            )
        self.report(
            {"INFO"},
            f"Created '{collection.name}'. Put its meshes in '{display.name}' and give each one a LOD Level.",
        )
        return {"FINISHED"}


class TW_OT_validate_vegetation(bpy.types.Operator):
    bl_idname = "tw_buildings.validate_vegetation"
    bl_label = "Validate"
    bl_description = "Check the selected vegetation model for problems and list them in the status bar, before exporting it"
    bl_options = {"REGISTER"}

    def execute(self, context: bpy.types.Context):
        model = find_vegetation_collection(context)
        if model is None:
            self.report({"ERROR"}, "Select something inside a Vegetation Model collection first.")
            return {"CANCELLED"}
        try:
            issues = validate_vegetation(model)
        except Exception as error:  # noqa: BLE001
            self.report({"ERROR"}, f"Validation could not complete: {error}")
            return {"CANCELLED"}
        if not issues:
            self.report({"INFO"}, f"'{model.name}' looks good - no problems found.")
            return {"FINISHED"}
        for issue in issues:
            self.report({issue.severity}, issue.message)
        return {"FINISHED"}


class TW_OT_export_vegetation(ExportTargetsMixin, BobWaitMixin, VegetationRulesOptions, bpy.types.Operator):
    bl_idname = "tw_buildings.export_vegetation"
    bl_label = "Export Vegetation"
    bl_description = (
        "Validate every selected vegetation model, write it out as a .CS2, and build them all into "
        "game-ready models in one go. Select several models to build them together"
    )
    bl_options = {"REGISTER"}
    bob_subject = "vegetation model"
    asset_role = "VEGETATION"
    asset_noun = "vegetation model"

    def find_one(self, context: bpy.types.Context) -> bpy.types.Collection | None:
        return find_vegetation_collection(context)

    directory: bpy.props.StringProperty(subtype="DIR_PATH")
    compile_with_bob: bpy.props.BoolProperty(
        name="Compile With BOB",
        description=(
            "Build the exported models into game-ready .rigid_model_v2 files and their _tech.cs2.parsed "
            "sidecars straight away. Only possible when exporting into the Assembly Kit's raw_data folder"
        ),
        default=True,
    )

    def invoke(self, context: bpy.types.Context, event: bpy.types.Event):
        if self.collect_targets(context) is None:
            return {"CANCELLED"}
        context.window_manager.fileselect_add(self)
        return {"RUNNING_MODAL"}

    def draw(self, context: bpy.types.Context) -> None:
        draw_export_targets(self.layout, self.targets, "Vegetation model", "vegetation models")
        self.layout.prop(self, "compile_with_bob")
        self.draw_rules_options(self.layout)

    def execute(self, context: bpy.types.Context):
        models = self.resolve_targets(context)
        if models is None:
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

        names = [model.name for model in models]
        rules_settings = self.rules_settings_or_none()
        results = [
            export_vegetation(
                model,
                self.directory,
                assembly_kit_root,
                context,
                rules_settings,
                self.rules_overwrite_confirmed,
            )
            for model in models
        ]
        report_export_warnings(self, names, results)
        blocked = export_failure_message(names, results)
        if blocked is not None:
            self.report({"ERROR"}, blocked)
            if not bpy.app.background:
                bpy.ops.tw_buildings.export_blocked(
                    "INVOKE_DEFAULT",
                    message=blocked,
                    headline=export_blocked_headline(len(models), "vegetation model"),
                )
            return {"CANCELLED"}

        cs2_paths = [result.cs2_path for result in results if result.cs2_path is not None]
        message = "\n".join(result.message for result in results)
        if not self.compile_with_bob:
            self.report({"INFO"}, message)
            return {"FINISHED"}
        return self.wait_for_bob(
            context, lambda: start_vegetation_build(assembly_kit_root, cs2_paths), message
        )


CLASSES = (
    TW_OT_new_vegetation,
    TW_OT_validate_vegetation,
    TW_OT_export_vegetation,
)


def register() -> None:
    for cls in CLASSES:
        bpy.utils.register_class(cls)


def unregister() -> None:
    for cls in reversed(CLASSES):
        bpy.utils.unregister_class(cls)
