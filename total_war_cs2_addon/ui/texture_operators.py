from pathlib import Path

import bpy

from bob import rules
from bob.cli import BobError, raw_data_logical_path, start_texture_build
from props.properties import get_assembly_kit_root
from textures import channels
from textures.decompile import decompile_many
from .operators import BobWaitMixin


class TW_OT_decompile_textures(bpy.types.Operator):
    bl_idname = "tw_buildings.decompile_textures"
    bl_label = "Decompile Textures"
    bl_description = (
        "Turn compiled working-data .dds textures back into editable raw-data .tga channels - "
        "gloss_map splits into gloss/level, mask splits into mask1/2/3, normal and parallax are "
        "un-shuffled, and diffuse/specular convert straight through. Select several files, or a "
        "whole folder, to batch"
    )
    bl_options = {"REGISTER"}

    directory: bpy.props.StringProperty(subtype="DIR_PATH", options={"HIDDEN", "SKIP_SAVE"})
    files: bpy.props.CollectionProperty(type=bpy.types.OperatorFileListElement, options={"HIDDEN", "SKIP_SAVE"})
    filter_glob: bpy.props.StringProperty(default="*.dds", options={"HIDDEN"})

    output_directory: bpy.props.StringProperty(
        name="Output Folder",
        subtype="DIR_PATH",
        description="Where to write the .tga files. Left empty, each one is written beside its source .dds",
    )
    overwrite: bpy.props.BoolProperty(
        name="Overwrite Existing",
        description="Replace a .tga that is already there. Off by default so a re-run never clobbers hand edits",
        default=False,
    )
    reconstruct_normal_z: bpy.props.BoolProperty(
        name="Reconstruct Normal Z",
        description=(
            "A compiled normal map's blue channel is destroyed by BOB. Off fills it with 255, matching most of "
            "the real corpus and round-tripping byte-exactly through BOB. On reconstructs it from the recovered "
            "X/Y instead, which looks better outside the pipeline but is discarded by the next compile either way"
        ),
        default=False,
    )

    def invoke(self, context: bpy.types.Context, event: bpy.types.Event):
        context.window_manager.fileselect_add(self)
        return {"RUNNING_MODAL"}

    def draw(self, context: bpy.types.Context) -> None:
        layout = self.layout
        layout.prop(self, "output_directory")
        layout.prop(self, "overwrite")
        layout.prop(self, "reconstruct_normal_z")

    def execute(self, context: bpy.types.Context):
        if not self.directory:
            self.report({"ERROR"}, "No folder selected.")
            return {"CANCELLED"}
        directory = Path(self.directory)
        selected = [directory / entry.name for entry in self.files if entry.name]
        # 3.4: pointing the browser at a folder with nothing individually selected processes every
        # .dds already there - the working data corpus is one flat folder of hundreds of files.
        paths = selected if selected else sorted(directory.glob("*.dds"))
        if not paths:
            self.report({"ERROR"}, f"No .dds files found in:\n{directory}")
            return {"CANCELLED"}

        output_dir = self.output_directory or None
        written, warnings = decompile_many(paths, output_dir, self.overwrite, self.reconstruct_normal_z)
        for warning in warnings:
            self.report({"WARNING"}, warning)
        if not written:
            self.report(
                {"WARNING"},
                "Nothing was written - every output already existed. Enable Overwrite Existing to replace them.",
            )
            return {"CANCELLED"}
        self.report({"INFO"}, f"Wrote {len(written)} .tga file(s) from {len(paths)} .dds file(s).")
        return {"FINISHED"}


def _expand_combiner_groups(paths: list[Path]) -> tuple[list[Path], list[str]]:
    # 3.3 step 3: selecting one half of a combiner (gloss/level, mask1/2/3) pulls in the rest, since
    # BOB errors with "Couldn't find <base>_mask1.tga!" rather than compiling a partial group. A
    # missing partner is reported, not fatal - BOB is the authority on whether it can proceed without it.
    expanded = dict.fromkeys(Path(path) for path in paths)
    warnings: list[str] = []
    for path in list(expanded):
        group = channels.combiner_group(path.stem)
        if group is None:
            continue
        base, suffixes = group
        for suffix in suffixes:
            sibling = path.with_name(f"{base}{suffix}{path.suffix}")
            if sibling in expanded:
                continue
            if sibling.is_file():
                expanded[sibling] = None
            else:
                warnings.append(f"'{sibling.name}' is missing - '{path.name}' needs it to compile correctly.")
    return list(expanded.keys()), warnings


class TW_OT_compile_textures(BobWaitMixin, bpy.types.Operator):
    bl_idname = "tw_buildings.compile_textures"
    bl_label = "Compile Textures"
    bl_description = (
        "Build selected raw-data .tga textures into working-data .dds files through BOB. Selecting "
        "one half of a gloss/level or mask1/2/3 group pulls in the rest automatically. Select several "
        "files, or a whole folder, to batch - even across more than one folder, in a single BOB run"
    )
    bl_options = {"REGISTER"}
    bob_subject = "texture"

    directory: bpy.props.StringProperty(subtype="DIR_PATH", options={"HIDDEN", "SKIP_SAVE"})
    files: bpy.props.CollectionProperty(type=bpy.types.OperatorFileListElement, options={"HIDDEN", "SKIP_SAVE"})
    filter_glob: bpy.props.StringProperty(default="*.tga", options={"HIDDEN"})

    target_path: bpy.props.StringProperty(
        name="Target Path",
        description=(
            "Where BOB writes the compiled .dds, relative to working_data (e.g. RigidModels\\Buildings\\Textures). "
            "Left empty, each folder gets the default for where it sits in raw_data - buildings vs. units"
        ),
    )

    def invoke(self, context: bpy.types.Context, event: bpy.types.Event):
        context.window_manager.fileselect_add(self)
        return {"RUNNING_MODAL"}

    def draw(self, context: bpy.types.Context) -> None:
        self.layout.prop(self, "target_path")

    def execute(self, context: bpy.types.Context):
        if not self.directory:
            self.report({"ERROR"}, "No folder selected.")
            return {"CANCELLED"}
        directory = Path(self.directory)
        selected = [directory / entry.name for entry in self.files if entry.name]
        paths = selected if selected else sorted(directory.glob("*.tga"))
        if not paths:
            self.report({"ERROR"}, f"No .tga files found in:\n{directory}")
            return {"CANCELLED"}

        try:
            assembly_kit_root = get_assembly_kit_root(context)
        except Exception:  # noqa: BLE001
            self.report({"ERROR"}, "Set the Assembly Kit folder in the add-on preferences first.")
            return {"CANCELLED"}

        raw_paths, warnings = _expand_combiner_groups(paths)
        for warning in warnings:
            self.report({"WARNING"}, warning)

        try:
            for path in raw_paths:
                raw_data_logical_path(assembly_kit_root, path)
        except BobError as error:
            self.report({"ERROR"}, str(error))
            return {"CANCELLED"}

        override = self.target_path.strip()
        folders = sorted({path.parent for path in raw_paths}, key=str)
        target_paths: dict[Path, str] = {}
        for folder in folders:
            default_target = rules.default_texture_target_path(assembly_kit_root, folder)
            settings = rules.TextureRules(target_path=override) if override else None
            written = rules.ensure_texture_rules(assembly_kit_root, folder, default_target, settings, overwrite=True)
            if written is not None:
                target_paths[folder] = override or default_target
                continue
            existing = rules.existing_texture_target_path(assembly_kit_root, folder)
            if existing is None:
                self.report(
                    {"ERROR"},
                    f"Could not write a rules.bob TargetPath for:\n{folder}\n"
                    "A rules.bob there may already cover something else - check it by hand.",
                )
                return {"CANCELLED"}
            target_paths[folder] = existing
            if override and existing != override:
                self.report(
                    {"WARNING"},
                    f"'{folder}' already has a rules.bob TargetPath of '{existing}' - "
                    f"the Target Path you set was not written there.",
                )

        message = f"Compiling {len(raw_paths)} texture file(s)."
        return self.wait_for_bob(
            context, lambda: start_texture_build(assembly_kit_root, raw_paths, target_paths), message
        )


CLASSES = (TW_OT_decompile_textures, TW_OT_compile_textures)


def register() -> None:
    for cls in CLASSES:
        bpy.utils.register_class(cls)


def unregister() -> None:
    for cls in reversed(CLASSES):
        bpy.utils.unregister_class(cls)
