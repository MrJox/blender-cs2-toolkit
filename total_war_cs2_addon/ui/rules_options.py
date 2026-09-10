import functools
from pathlib import Path

import bpy

from bob import rules
from props.properties import get_always_overwrite_rules

# The export dialog is a file browser, and a file browser cannot host a second modal dialog and wait
# for its answer. So a conflicting export stashes what it was about to do, asks, and the confirm
# operator re-dispatches the same export with the answer folded in. One export runs at a time, so
# one slot is enough.
_pending: tuple[str, dict] | None = None


def _stash(idname: str, properties: dict) -> None:
    global _pending
    _pending = (idname, properties)


def _take() -> tuple[str, dict] | None:
    global _pending
    pending, _pending = _pending, None
    return pending


def _restartable_properties(operator: bpy.types.Operator) -> dict:
    # operator.properties.rna_type is the same introspection Operator.as_keywords uses; the class's
    # own bl_rna carries only what bpy.types.Operator declares.
    return {
        identifier: getattr(operator, identifier)
        for identifier, prop in operator.properties.rna_type.properties.items()
        if identifier != "rna_type" and not prop.is_readonly and prop.type != "COLLECTION"
    }


def _dispatch(idname: str, properties: dict) -> None:
    operator = bpy.ops
    for part in idname.split("."):
        operator = getattr(operator, part)
    operator("EXEC_DEFAULT", **properties)


class TW_OT_confirm_rules_overwrite(bpy.types.Operator):
    bl_idname = "tw_buildings.confirm_rules_overwrite"
    bl_label = "Overwrite rules.bob?"
    bl_options = {"REGISTER", "INTERNAL"}

    directory: bpy.props.StringProperty(default="")
    changes: bpy.props.StringProperty(default="")

    def invoke(self, context: bpy.types.Context, event: bpy.types.Event):
        if context.window:
            context.window.cursor_warp(context.window.width // 2, context.window.height // 2)
        return context.window_manager.invoke_props_dialog(
            self, width=620, title="Overwrite rules.bob?", confirm_text="Overwrite"
        )

    def draw(self, context: bpy.types.Context) -> None:
        layout = self.layout
        layout.label(text=f"A rules.bob already sits in {self.directory}.", icon="ERROR")
        layout.label(text="Your export settings would change it like this:")
        box = layout.box()
        for line in self.changes.splitlines():
            box.label(text=line)
        layout.label(text="Overwrite keeps every other section in that file, including per-file overrides.")
        layout.label(text="Cancel exports nothing and leaves the file alone.")

    def execute(self, context: bpy.types.Context):
        pending = _take()
        if pending is None:
            return {"CANCELLED"}
        # Deferred by a timer rather than called here: this runs while the popup is being torn down,
        # and the export it restarts goes modal for the length of the BOB run.
        bpy.app.timers.register(functools.partial(_dispatch, *pending), first_interval=0.0)
        return {"FINISHED"}


# Every key BOB documents as carrying its own default is a three-way choice, not a checkbox: leaving
# it alone has to keep the key out of rules.bob entirely, or a defaulted export would stop matching
# the file CA ships.
OPTIONAL_FLAG_ITEMS = [
    ("DEFAULT", "BOB Default", "Leave this out of rules.bob and let BOB use its own default"),
    ("TRUE", "Yes", "Write 'true'"),
    ("FALSE", "No", "Write 'false'"),
]


def _optional_flag(value: str) -> bool | None:
    return {"TRUE": True, "FALSE": False}.get(value)


# BOB writes 100/200/400/500 into the compiled model when the rule names no LODDistance at all, so
# the boxes show that ladder and the keys stay out of the file until a rung actually moves. All four
# go in together: a ladder with one rung named and three missing is not a ladder.
def _lod_ladder(values: tuple[int, int, int, int]) -> tuple[int | None, ...]:
    return (None, None, None, None) if values == rules.DEFAULT_LOD_DISTANCES else values


def _enum_items(values: tuple[str, ...]) -> list[tuple[str, str, str]]:
    return [(value, value.replace("_", " ").title(), value) for value in values]


def _optional_flag_property(name: str, description: str):
    return bpy.props.EnumProperty(
        name=name, description=description, items=OPTIONAL_FLAG_ITEMS, default="DEFAULT"
    )


class RulesOptionsMixin:
    rules_section: str

    rules_overwrite_confirmed: bpy.props.BoolProperty(default=False, options={"HIDDEN"})
    rules_show_advanced: bpy.props.BoolProperty(
        name="Show All Options",
        description=(
            "Also show the rules.bob keys BOB carries its own default for. Left alone they are not "
            "written to the file at all"
        ),
        default=False,
    )

    def rules_settings(self):
        raise NotImplementedError

    def rules_base_text(self, assembly_kit_root: str, directory: Path) -> str:
        raise NotImplementedError

    def draw_rules_options(self, layout: bpy.types.UILayout) -> None:
        raise NotImplementedError

    def rules_box(self, layout: bpy.types.UILayout) -> bpy.types.UILayout:
        box = layout.box()
        box.enabled = self.compile_with_bob
        box.label(text="rules.bob - what BOB builds this as", icon="TOOL_SETTINGS")
        return box

    def rules_advanced_box(self, box: bpy.types.UILayout) -> bpy.types.UILayout | None:
        box.prop(self, "rules_show_advanced")
        return box.box() if self.rules_show_advanced else None

    # None means "write no rules.bob at all", which is what an export that is not being compiled
    # asks for: BOB is the only reader of the file, so nothing is left behind when it is not run.
    def rules_settings_or_none(self):
        return self.rules_settings() if self.compile_with_bob else None

    def blocked_on_rules_overwrite(self, context: bpy.types.Context, assembly_kit_root: str):
        settings = self.rules_settings_or_none()
        if settings is None or self.rules_overwrite_confirmed:
            return None
        directory = Path(bpy.path.abspath(self.directory))
        changes = rules.rules_conflict(
            assembly_kit_root,
            directory,
            self.rules_section,
            self.rules_base_text(assembly_kit_root, directory),
            settings,
        )
        if not changes:
            return None
        if get_always_overwrite_rules(context):
            self.rules_overwrite_confirmed = True
            return None
        # A background Blender has nobody to ask, so the existing file stands and the exporter says
        # so in its warnings rather than silently building against values nobody chose.
        if bpy.app.background or context.window is None:
            return None
        properties = _restartable_properties(self)
        properties["rules_overwrite_confirmed"] = True
        _stash(self.bl_idname, properties)
        bpy.ops.tw_buildings.confirm_rules_overwrite(
            "INVOKE_DEFAULT", directory=str(directory), changes="\n".join(changes)
        )
        return {"CANCELLED"}


class BuildingRulesOptions(RulesOptionsMixin):
    rules_section = rules.BUILDING_SECTION

    rules_hit_points: bpy.props.IntProperty(
        name="Hit Points",
        description="How much damage the building takes before it is destroyed",
        default=rules.BuildingRules.hit_points,
        min=0,
    )
    rules_capacity: bpy.props.IntProperty(
        name="Capacity",
        description="How many men can be inside the building at the same time",
        default=rules.BuildingRules.capacity,
        min=0,
    )
    rules_category: bpy.props.EnumProperty(
        name="Category",
        description="What kind of battlefield building this is, as the game's own category table lists them",
        items=_enum_items(rules.BUILDING_CATEGORIES),
        default=rules.BuildingRules.category,
    )
    rules_audio_material: bpy.props.EnumProperty(
        name="Audio Material",
        description="What the building sounds like when it is struck",
        items=_enum_items(rules.AUDIO_MATERIALS),
        default=rules.BuildingRules.audio_material,
    )
    rules_incendiary_radius: bpy.props.FloatProperty(
        name="Incendiary Radius",
        description="How far the fire spreads over the building once it is set alight",
        default=rules.BuildingRules.incendiary_radius,
        min=0.0,
    )
    rules_animation_fps: bpy.props.IntProperty(
        name="Animation FPS",
        description=(
            "The rate BOB resamples the destruction and gate animations onto. A clip's frame count "
            "comes out as its duration times this rate, plus one"
        ),
        default=rules.BuildingRules.animation_fps,
        min=1,
        max=120,
    )
    rules_multiple_buildings: bpy.props.BoolProperty(
        name="Multiple Buildings",
        description="Whether several buildings may share one folder - the naming convention BOB expects",
        default=rules.BuildingRules.multiple_buildings,
    )
    rules_texture_path: bpy.props.StringProperty(
        name="Texture Path",
        description="Where BOB looks for this building's textures, relative to working_data",
        default=rules.BuildingRules.texture_path,
    )
    rules_animation_type: bpy.props.StringProperty(
        name="Animation Type",
        description=(
            "The kind of thing BOB builds this as. Anything but 'building' and BOB registers no "
            "action for the file, so the export finishes having built nothing"
        ),
        default=rules.BuildingRules.animation_type,
    )
    rules_can_burn: _optional_flag_property("Can Burn", "Whether the building can catch fire. BOB's default is yes")
    rules_auxiliary: _optional_flag_property(
        "Auxiliary", "Flags it as an auxiliary building. BOB's default is no"
    )
    rules_joiner: _optional_flag_property(
        "Joiner", "Flags it as a building joiner - the piece that links two wall segments. BOB's default is no"
    )
    rules_collision_3d: _optional_flag_property(
        "Collision 3D", "Whether the building has 3d collision. BOB's default is yes"
    )
    rules_gun_type: bpy.props.StringProperty(
        name="Gun Type",
        description=(
            "The engine a shooting tower fires with - Attila's own fort towers use 'att_tower_stone' "
            "and 'att_tower_wooden'. Leave empty for a building that does not shoot"
        ),
        default=rules.BuildingRules.gun_type,
    )

    def rules_settings(self) -> rules.BuildingRules:
        return rules.BuildingRules(
            texture_path=self.rules_texture_path,
            animation_fps=self.rules_animation_fps,
            animation_type=self.rules_animation_type,
            audio_material=self.rules_audio_material,
            capacity=self.rules_capacity,
            category=self.rules_category,
            hit_points=self.rules_hit_points,
            multiple_buildings=self.rules_multiple_buildings,
            incendiary_radius=self.rules_incendiary_radius,
            can_burn=_optional_flag(self.rules_can_burn),
            auxiliary=_optional_flag(self.rules_auxiliary),
            joiner=_optional_flag(self.rules_joiner),
            collision_3d=_optional_flag(self.rules_collision_3d),
            gun_type=self.rules_gun_type,
        )

    def rules_base_text(self, assembly_kit_root: str, directory: Path) -> str:
        return rules.building_rules_text(self.rules_settings())

    def draw_rules_options(self, layout: bpy.types.UILayout) -> None:
        box = self.rules_box(layout)
        box.prop(self, "rules_hit_points")
        box.prop(self, "rules_capacity")
        box.prop(self, "rules_category")
        box.prop(self, "rules_audio_material")
        box.prop(self, "rules_incendiary_radius")
        box.prop(self, "rules_animation_fps")
        box.prop(self, "rules_multiple_buildings")
        box.prop(self, "rules_texture_path")
        advanced = self.rules_advanced_box(box)
        if advanced is None:
            return
        advanced.prop(self, "rules_can_burn")
        advanced.prop(self, "rules_auxiliary")
        advanced.prop(self, "rules_joiner")
        advanced.prop(self, "rules_collision_3d")
        advanced.prop(self, "rules_gun_type")
        advanced.prop(self, "rules_animation_type")


class RigidModelRulesOptions(RulesOptionsMixin):
    # [RigidModelV2] is one rule type, so a unit part and a tree share this whole tail of keys.
    rules_target_filename: bpy.props.StringProperty(
        name="Target Filename",
        description="Rename the compiled file. Leave empty to keep the .CS2's own name",
        default="",
    )
    rules_target_extension: bpy.props.StringProperty(
        name="Target Extension",
        description="The compiled file's extension. Leave empty for BOB's own 'rigid_model_v2'",
        default="",
    )
    rules_rigid_category: bpy.props.StringProperty(
        name="Rigid Category",
        description=(
            "The category written into the warscape_rigid or warscape_animated table, and only used "
            "when Update Database is on"
        ),
        default="",
    )
    rules_update_database: _optional_flag_property(
        "Update Database", "Whether BOB adds this model to the warscape_rigid database table"
    )
    rules_single_lod: _optional_flag_property(
        "Single LOD",
        "The model has no levels of detail and its meshes need no _lod postfix. BOB's default is no",
    )
    rules_variable_bones_per_vert: _optional_flag_property(
        "Variable Bones Per Vert", "Let each vertex carry a different number of bone weights"
    )
    rules_disable_alpha_test: _optional_flag_property(
        "Disable Alpha Test", "Turn off alpha testing for this model's materials"
    )

    def rigid_model_settings(self) -> dict:
        return {
            "target_filename": self.rules_target_filename,
            "target_extension": self.rules_target_extension,
            "rigid_category": self.rules_rigid_category,
            "update_database": _optional_flag(self.rules_update_database),
            "single_lod": _optional_flag(self.rules_single_lod),
            "variable_bones_per_vert": _optional_flag(self.rules_variable_bones_per_vert),
            "disable_alpha_test": _optional_flag(self.rules_disable_alpha_test),
        }

    def draw_rigid_model_options(self, advanced: bpy.types.UILayout) -> None:
        advanced.prop(self, "rules_target_filename")
        advanced.prop(self, "rules_target_extension")
        advanced.prop(self, "rules_rigid_category")
        advanced.prop(self, "rules_update_database")
        advanced.prop(self, "rules_single_lod")
        advanced.prop(self, "rules_variable_bones_per_vert")
        advanced.prop(self, "rules_disable_alpha_test")


class UnitRulesOptions(RigidModelRulesOptions):
    rules_section = rules.UNIT_SECTION

    rules_animation_type: bpy.props.StringProperty(
        name="Skeleton (Animation Type)",
        description=(
            "The skeleton BOB stamps into every compiled model in this folder that it has no better "
            "answer for. Filled in from the skeleton the selected assets are bound to in Blender. "
            "Each asset you export is also given its own line, and that line wins over this one - so "
            "this covers what you build here by hand. Empty is correct for a folder of weapons, "
            "shields and props"
        ),
        default=rules.UnitRules.animation_type,
    )
    rules_target_path: bpy.props.StringProperty(
        name="Target Path",
        description=(
            "Where under working_data BOB writes the compiled .rigid_model_v2. It is this, not the "
            "folder you export the .CS2 into, that decides where the built model lands"
        ),
        default=rules.UnitRules.target_path,
    )
    rules_texture_folder: bpy.props.StringProperty(
        name="Texture Folder",
        description="Where BOB looks for this asset's textures, relative to working_data",
        default=rules.UnitRules.texture_folder,
    )
    rules_texture_subfolder: bpy.props.StringProperty(
        name="Texture Sub-folder",
        description="The folder inside Texture Folder the .tga files sit in",
        default=rules.UnitRules.texture_subfolder,
    )
    rules_save_agf: bpy.props.BoolProperty(
        name="Save AGF",
        description="Also write BOB's intermediate .agf beside the compiled model. It is not packed either way",
        default=rules.UnitRules.save_agf,
    )
    rules_lod_distance_1: bpy.props.IntProperty(
        name="LOD 1 Distance",
        description="How far from the camera the LOD01 mesh takes over. This is BOB's own default",
        default=rules.DEFAULT_LOD_DISTANCES[0],
        min=0,
    )
    rules_lod_distance_2: bpy.props.IntProperty(
        name="LOD 2 Distance",
        description="How far from the camera the LOD02 mesh takes over. This is BOB's own default",
        default=rules.DEFAULT_LOD_DISTANCES[1],
        min=0,
    )
    rules_lod_distance_3: bpy.props.IntProperty(
        name="LOD 3 Distance",
        description="How far from the camera the LOD03 mesh takes over. This is BOB's own default",
        default=rules.DEFAULT_LOD_DISTANCES[2],
        min=0,
    )
    rules_lod_distance_4: bpy.props.IntProperty(
        name="LOD 4 Distance",
        description="How far from the camera the LOD04 mesh takes over. This is BOB's own default",
        default=rules.DEFAULT_LOD_DISTANCES[3],
        min=0,
    )

    def rules_settings(self) -> rules.UnitRules:
        lod1, lod2, lod3, lod4 = _lod_ladder(
            (
                self.rules_lod_distance_1,
                self.rules_lod_distance_2,
                self.rules_lod_distance_3,
                self.rules_lod_distance_4,
            )
        )
        return rules.UnitRules(
            target_path=self.rules_target_path,
            texture_folder=self.rules_texture_folder,
            texture_subfolder=self.rules_texture_subfolder,
            animation_type=self.rules_animation_type,
            save_agf=self.rules_save_agf,
            lod_distance_1=lod1,
            lod_distance_2=lod2,
            lod_distance_3=lod3,
            lod_distance_4=lod4,
            **self.rigid_model_settings(),
        )

    def rules_base_text(self, assembly_kit_root: str, directory: Path) -> str:
        return rules.unit_rules_base(self.rules_settings())

    def draw_rules_options(self, layout: bpy.types.UILayout) -> None:
        box = self.rules_box(layout)
        box.prop(self, "rules_animation_type")
        box.prop(self, "rules_target_path")
        box.prop(self, "rules_texture_folder")
        box.prop(self, "rules_texture_subfolder")
        box.prop(self, "rules_save_agf")
        advanced = self.rules_advanced_box(box)
        if advanced is None:
            return
        self.draw_rigid_model_options(advanced)
        advanced.label(text="Level of detail switch distances")
        advanced.prop(self, "rules_lod_distance_1")
        advanced.prop(self, "rules_lod_distance_2")
        advanced.prop(self, "rules_lod_distance_3")
        advanced.prop(self, "rules_lod_distance_4")


class AnimationRulesOptions(RulesOptionsMixin):
    rules_section = rules.ANIMATION_SECTION

    rules_core_translations: bpy.props.BoolProperty(
        name="Core Translations",
        description=(
            "Keep the movement of the core body bones, not just their rotation. CA leaves this off "
            "on every animation folder in the kit - a compiled clip is rotation-only except on the "
            "root and the floating weapon bones"
        ),
        default=rules.AnimationRules.core_translations,
    )
    rules_face_translations: bpy.props.BoolProperty(
        name="Face Translations",
        description="Keep the movement of the face bones",
        default=rules.AnimationRules.face_translations,
    )
    rules_face_rotations: bpy.props.BoolProperty(
        name="Face Rotations",
        description="Keep the rotation of the face bones",
        default=rules.AnimationRules.face_rotations,
    )
    rules_left_hand_translations: bpy.props.BoolProperty(
        name="Left Hand Translations",
        description="Keep the movement of the left hand's finger bones",
        default=rules.AnimationRules.left_hand_translations,
    )
    rules_left_hand_rotations: bpy.props.BoolProperty(
        name="Left Hand Rotations",
        description="Keep the rotation of the left hand's finger bones",
        default=rules.AnimationRules.left_hand_rotations,
    )
    rules_right_hand_translations: bpy.props.BoolProperty(
        name="Right Hand Translations",
        description="Keep the movement of the right hand's finger bones",
        default=rules.AnimationRules.right_hand_translations,
    )
    rules_right_hand_rotations: bpy.props.BoolProperty(
        name="Right Hand Rotations",
        description="Keep the rotation of the right hand's finger bones",
        default=rules.AnimationRules.right_hand_rotations,
    )
    rules_ignore_metadata: bpy.props.BoolProperty(
        name="Ignore Metadata",
        description="Skip the metadata sidecar - this add-on authors none, so leave it on",
        default=rules.AnimationRules.ignore_metadata,
    )
    rules_animation_type: bpy.props.StringProperty(
        name="Skeleton (Animation Type)",
        description=(
            "The skeleton BOB resolves the .bone_table by for any clip in this folder it has no "
            "better answer for. Filled in from the skeleton whose clips are being exported. Every "
            "clip you export is also given its own line, and that line wins over this one"
        ),
        default=rules.AnimationRules.animation_type,
    )
    rules_target_path: bpy.props.StringProperty(
        name="Target Path",
        description="Where under working_data BOB writes the compiled .anim. Leave empty to keep BOB's own choice",
        default=rules.AnimationRules.target_path,
    )
    rules_cinematic_animation_type: bpy.props.StringProperty(
        name="Cinematic Skeleton",
        description="The skeleton to resolve against when this clip is built for a cinematic",
        default="",
    )
    rules_cinematic_core_translations: _optional_flag_property(
        "Cinematic Core Translations", "Keep the core bones' movement in the cinematic build"
    )
    rules_cinematic_face_translations: _optional_flag_property(
        "Cinematic Face Translations", "Keep the face bones' movement in the cinematic build"
    )
    rules_cinematic_face_rotations: _optional_flag_property(
        "Cinematic Face Rotations", "Keep the face bones' rotation in the cinematic build"
    )
    rules_cinematic_left_hand_translations: _optional_flag_property(
        "Cinematic Left Hand Translations", "Keep the left hand's movement in the cinematic build"
    )
    rules_cinematic_left_hand_rotations: _optional_flag_property(
        "Cinematic Left Hand Rotations", "Keep the left hand's rotation in the cinematic build"
    )
    rules_cinematic_right_hand_translations: _optional_flag_property(
        "Cinematic Right Hand Translations", "Keep the right hand's movement in the cinematic build"
    )
    rules_cinematic_right_hand_rotations: _optional_flag_property(
        "Cinematic Right Hand Rotations", "Keep the right hand's rotation in the cinematic build"
    )

    def rules_settings(self) -> rules.AnimationRules:
        return rules.AnimationRules(
            core_translations=self.rules_core_translations,
            face_translations=self.rules_face_translations,
            face_rotations=self.rules_face_rotations,
            left_hand_translations=self.rules_left_hand_translations,
            left_hand_rotations=self.rules_left_hand_rotations,
            right_hand_translations=self.rules_right_hand_translations,
            right_hand_rotations=self.rules_right_hand_rotations,
            ignore_metadata=self.rules_ignore_metadata,
            animation_type=self.rules_animation_type,
            target_path=self.rules_target_path,
            cinematic_animation_type=self.rules_cinematic_animation_type,
            cinematic_core_translations=_optional_flag(self.rules_cinematic_core_translations),
            cinematic_face_translations=_optional_flag(self.rules_cinematic_face_translations),
            cinematic_face_rotations=_optional_flag(self.rules_cinematic_face_rotations),
            cinematic_left_hand_translations=_optional_flag(self.rules_cinematic_left_hand_translations),
            cinematic_left_hand_rotations=_optional_flag(self.rules_cinematic_left_hand_rotations),
            cinematic_right_hand_translations=_optional_flag(self.rules_cinematic_right_hand_translations),
            cinematic_right_hand_rotations=_optional_flag(self.rules_cinematic_right_hand_rotations),
        )

    def rules_base_text(self, assembly_kit_root: str, directory: Path) -> str:
        return rules.animation_rules_base(self.rules_settings())

    def draw_rules_options(self, layout: bpy.types.UILayout) -> None:
        box = self.rules_box(layout)
        box.prop(self, "rules_animation_type")
        box.label(text="Channels to keep in the compiled clip")
        box.prop(self, "rules_core_translations")
        box.prop(self, "rules_face_translations")
        box.prop(self, "rules_face_rotations")
        box.prop(self, "rules_left_hand_translations")
        box.prop(self, "rules_left_hand_rotations")
        box.prop(self, "rules_right_hand_translations")
        box.prop(self, "rules_right_hand_rotations")
        box.prop(self, "rules_ignore_metadata")
        advanced = self.rules_advanced_box(box)
        if advanced is None:
            return
        advanced.prop(self, "rules_target_path")
        advanced.label(text="Cinematic build")
        advanced.prop(self, "rules_cinematic_animation_type")
        advanced.prop(self, "rules_cinematic_core_translations")
        advanced.prop(self, "rules_cinematic_face_translations")
        advanced.prop(self, "rules_cinematic_face_rotations")
        advanced.prop(self, "rules_cinematic_left_hand_translations")
        advanced.prop(self, "rules_cinematic_left_hand_rotations")
        advanced.prop(self, "rules_cinematic_right_hand_translations")
        advanced.prop(self, "rules_cinematic_right_hand_rotations")


class SkeletonRulesOptions(RulesOptionsMixin):
    rules_section = rules.SKELETON_SECTION

    rules_target_path: bpy.props.StringProperty(
        name="Target Path",
        description=(
            "Where under working_data BOB writes the compiled skeleton. Leave empty to keep BOB's "
            "own choice. A skeleton's other two rule keys are what a skeleton is, so there is "
            "nothing else to set"
        ),
        default=rules.SkeletonRules.target_path,
    )

    def rules_settings(self) -> rules.SkeletonRules:
        return rules.SkeletonRules(target_path=self.rules_target_path)

    def rules_base_text(self, assembly_kit_root: str, directory: Path) -> str:
        return rules.skeleton_rules_text(self.rules_settings())

    def draw_rules_options(self, layout: bpy.types.UILayout) -> None:
        self.rules_box(layout).prop(self, "rules_target_path")


class VegetationRulesOptions(RigidModelRulesOptions):
    rules_section = rules.VEGETATION_SECTION

    rules_create_description_file: bpy.props.BoolProperty(
        name="Build the Fire Hull",
        description=(
            "Write the _tech.cs2.parsed sidecar - the burn hull and the fire emitters spread over "
            "it. Without it BOB builds the model alone and the tree cannot catch fire"
        ),
        default=rules.VegetationRules.create_description_file,
    )
    rules_incendiary_radius: bpy.props.FloatProperty(
        name="Incendiary Radius",
        description=(
            "How densely BOB spreads the fire emitters over the burn hull it generates. A small oak "
            "at 2.0 gets two, which is what the shipped trees carry"
        ),
        default=rules.VegetationRules.incendiary_radius,
        min=0.0,
    )
    rules_lod_distance_1: bpy.props.IntProperty(
        name="LOD 1 Distance",
        description="How far from the camera the LOD01 mesh takes over. This is BOB's own default",
        default=rules.VegetationRules.lod_distance_1,
        min=0,
    )
    rules_lod_distance_2: bpy.props.IntProperty(
        name="LOD 2 Distance",
        description="How far from the camera the LOD02 mesh takes over. This is BOB's own default",
        default=rules.VegetationRules.lod_distance_2,
        min=0,
    )
    rules_lod_distance_3: bpy.props.IntProperty(
        name="LOD 3 Distance",
        description="How far from the camera the LOD03 mesh takes over. This is BOB's own default",
        default=rules.VegetationRules.lod_distance_3,
        min=0,
    )
    rules_lod_distance_4: bpy.props.IntProperty(
        name="LOD 4 Distance",
        description="How far from the camera the LOD04 mesh takes over. This is BOB's own default",
        default=rules.VegetationRules.lod_distance_4,
        min=0,
    )
    rules_animation_type: bpy.props.StringProperty(
        name="Animation Type",
        description=(
            "The kind of thing BOB builds this as. Anything but 'tree' and BOB registers no action "
            "for the file, so the export finishes having built nothing"
        ),
        default=rules.VegetationRules.animation_type,
    )
    rules_target_path: bpy.props.StringProperty(
        name="Target Path",
        description=(
            "Where under working_data BOB writes the compiled model. Leave empty and each model "
            "mirrors its own place inside raw_data, which is what puts a batch of trees where the "
            "game's own vegetation lives"
        ),
        default=rules.VegetationRules.target_path,
    )
    rules_texture_folder: bpy.props.StringProperty(
        name="Texture Folder",
        description="Where BOB looks for the textures. Leave empty to mirror the .CS2's own place inside raw_data",
        default=rules.VegetationRules.texture_folder,
    )
    rules_texture_subfolder: bpy.props.StringProperty(
        name="Texture Sub-folder",
        description="The folder inside Texture Folder the textures sit in. Leave empty to derive it",
        default=rules.VegetationRules.texture_subfolder,
    )

    def rules_settings(self) -> rules.VegetationRules:
        return rules.VegetationRules(
            animation_type=self.rules_animation_type,
            create_description_file=self.rules_create_description_file,
            incendiary_radius=self.rules_incendiary_radius,
            lod_distance_1=self.rules_lod_distance_1,
            lod_distance_2=self.rules_lod_distance_2,
            lod_distance_3=self.rules_lod_distance_3,
            lod_distance_4=self.rules_lod_distance_4,
            target_path=self.rules_target_path,
            texture_folder=self.rules_texture_folder,
            texture_subfolder=self.rules_texture_subfolder,
            **self.rigid_model_settings(),
        )

    def rules_base_text(self, assembly_kit_root: str, directory: Path) -> str:
        paths = rules.vegetation_paths_for(assembly_kit_root, directory / "x.CS2")
        return rules.vegetation_rules_text(*paths, self.rules_settings())

    def draw_rules_options(self, layout: bpy.types.UILayout) -> None:
        box = self.rules_box(layout)
        box.prop(self, "rules_create_description_file")
        box.prop(self, "rules_incendiary_radius")
        box.label(text="Level of detail switch distances")
        box.prop(self, "rules_lod_distance_1")
        box.prop(self, "rules_lod_distance_2")
        box.prop(self, "rules_lod_distance_3")
        box.prop(self, "rules_lod_distance_4")
        advanced = self.rules_advanced_box(box)
        if advanced is None:
            return
        # `Tree = true`, the generated-billboard switch, is the one documented key with no setting:
        # it dereferences a null pointer inside Warscape.AssemblyKit.dll and aborts the build
        # (PLAN_vegetation.md 11.3), so there is nothing an artist could do with it.
        advanced.prop(self, "rules_target_path")
        advanced.prop(self, "rules_texture_folder")
        advanced.prop(self, "rules_texture_subfolder")
        self.draw_rigid_model_options(advanced)
        advanced.prop(self, "rules_animation_type")


CLASSES = (TW_OT_confirm_rules_overwrite,)


def register() -> None:
    for cls in CLASSES:
        bpy.utils.register_class(cls)


def unregister() -> None:
    for cls in reversed(CLASSES):
        bpy.utils.unregister_class(cls)
