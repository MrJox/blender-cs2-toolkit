import re
import shutil
from dataclasses import dataclass
from pathlib import Path

RULES_FILENAME = "rules.bob"
BUILDING_SECTION = "[building]"
SKELETON_SECTION = "[animation]"
RELEASE_PACK_TYPE = "release"
MOD_PACK_TYPE = "mod"
DEFAULT_PACK_TYPE = RELEASE_PACK_TYPE

# The two db tables BOB writes per building, as (working_data/db subfolder, filename suffix).
DB_TABLES = (
    ("models_building_tables", "models_building"),
    ("battlefield_buildings_tables", "battlefield_buildings"),
)


def _flag(value: bool) -> str:
    return "true" if value else "false"


def _decimal(value: float) -> str:
    # BOB's own files write 9.0 and 2.0, not 9 and 2, so a whole number keeps its decimal point.
    text = f"{value:g}"
    return text if "." in text else text + ".0"


def _line(key: str, value, separator: str = " = ") -> str:
    return f"\t{key}{separator}{_flag(value) if isinstance(value, bool) else value}\r\n"


def _optional(key: str, value, separator: str = " = ") -> str:
    # Every key BOB documents as having its own default is left out of the file entirely until the
    # artist sets it. That is what keeps a defaulted export byte-identical to the file CA ships,
    # while still letting every supported key be reached.
    if value is None or value == "":
        return ""
    return _line(key, value, separator)


def _is_customised(settings) -> bool:
    return settings is not None and settings != type(settings)()


# raw_data/db/battlefield_building_categories.xml - the game's own enum table, all nine rows. BOB's
# documentation string lists Empire's categories instead (armoury, barracks, command_HQ, ...) and is
# stale: `generic`, which CA's own rules.bob files use, is not in it.
BUILDING_CATEGORIES = (
    "bridge",
    "fort_tower",
    "fort_wall",
    "gate",
    "generic",
    "ground_platform",
    "incidental",
    "unbreachable_fort_wall",
    "vaultable",
)

# raw_data/db/audio_materials_enums.xml, all twenty-eight rows. BOB documents only "brick, stone,
# wood" - stale in the same way.
AUDIO_MATERIALS = (
    "axe",
    "body",
    "brick",
    "bronze",
    "chainmail",
    "cloth",
    "club",
    "deep_water",
    "falx",
    "forest",
    "glass",
    "grass",
    "leather",
    "metal",
    "mud",
    "road",
    "rock",
    "sand",
    "scrub",
    "segmented",
    "shallow_water",
    "snow",
    "spear",
    "stone",
    "sword",
    "sword_long",
    "wicker",
    "wood",
)


@dataclass(frozen=True)
class BuildingRules:
    texture_path: str = "RigidModels\\Buildings\\Textures\\"
    animation_fps: int = 20
    animation_type: str = "building"
    audio_material: str = "wood"
    capacity: int = 500
    category: str = "generic"
    hit_points: int = 500
    multiple_buildings: bool = True
    incendiary_radius: float = 9.0
    can_burn: bool | None = None
    auxiliary: bool | None = None
    joiner: bool | None = None
    collision_3d: bool | None = None
    gun_type: str = ""


UNIT_TARGET_PATH = "VariantMeshes\\_VariantModels\\"

# What BOB writes into a compiled model's LOD chain when the rule names no LODDistance at all.
# Measured: a four-LOD part built against a rules.bob carrying none came out 100/200/400/500, which
# is also what 23 of the 28 unit models in the corpus carry and what CA's own tree rules.bob spells
# out by hand.
DEFAULT_LOD_DISTANCES = (100, 200, 400, 500)


@dataclass(frozen=True)
class UnitRules:
    target_path: str = UNIT_TARGET_PATH
    texture_folder: str = UNIT_TARGET_PATH
    texture_subfolder: str = "tex"
    animation_type: str = ""
    save_agf: bool = True
    target_filename: str = ""
    target_extension: str = ""
    rigid_category: str = ""
    update_database: bool | None = None
    single_lod: bool | None = None
    variable_bones_per_vert: bool | None = None
    disable_alpha_test: bool | None = None
    lod_distance_1: int | None = None
    lod_distance_2: int | None = None
    lod_distance_3: int | None = None
    lod_distance_4: int | None = None


@dataclass(frozen=True)
class AnimationRules:
    core_translations: bool = False
    face_translations: bool = False
    face_rotations: bool = False
    left_hand_translations: bool = False
    left_hand_rotations: bool = False
    right_hand_translations: bool = False
    right_hand_rotations: bool = False
    ignore_metadata: bool = True
    animation_type: str = ""
    target_path: str = ""
    cinematic_animation_type: str = ""
    cinematic_core_translations: bool | None = None
    cinematic_face_translations: bool | None = None
    cinematic_face_rotations: bool | None = None
    cinematic_left_hand_translations: bool | None = None
    cinematic_left_hand_rotations: bool | None = None
    cinematic_right_hand_translations: bool | None = None
    cinematic_right_hand_rotations: bool | None = None


@dataclass(frozen=True)
class SkeletonRules:
    target_path: str = ""


@dataclass(frozen=True)
class VegetationRules:
    animation_type: str = "tree"
    create_description_file: bool = True
    incendiary_radius: float = 2.0
    lod_distance_1: int = DEFAULT_LOD_DISTANCES[0]
    lod_distance_2: int = DEFAULT_LOD_DISTANCES[1]
    lod_distance_3: int = DEFAULT_LOD_DISTANCES[2]
    lod_distance_4: int = DEFAULT_LOD_DISTANCES[3]
    target_path: str = ""
    texture_folder: str = ""
    texture_subfolder: str = ""
    target_filename: str = ""
    target_extension: str = ""
    rigid_category: str = ""
    update_database: bool | None = None
    single_lod: bool | None = None
    variable_bones_per_vert: bool | None = None
    disable_alpha_test: bool | None = None


# The keys every [RigidModelV2] section shares, in BOB's own documented order. Units and vegetation
# differ only in what they put above them.
def _rigid_model_extras(settings) -> str:
    return (
        _optional("TargetFilename", settings.target_filename)
        + _optional("TargetExtension", settings.target_extension)
        + _optional("RigidCategory", settings.rigid_category)
        + _optional("UpdateDatabase", settings.update_database)
        + _optional("SingleLOD", settings.single_lod)
        + _optional("VariableBonesPerVert", settings.variable_bones_per_vert)
        + _optional("DisableAlphaTest", settings.disable_alpha_test)
    )


# With every field left at its default this is byte-identical to the rules.bob CA ships beside their
# own buildings - raw_data's `eastern` and `gondorean` architecture folders both carry exactly this
# file. BOB parses rules.bob as CRLF INI. The five keys BOB refuses to run without are TexturePath,
# Capacity, HitPoints, AudioMaterial and Category ("Rule not found defining '<key>'" in
# BOB_Building.AssemblyKit.dll); the rest carry BOB's own defaults and are written only once set.
def building_rules_text(settings: BuildingRules | None = None) -> str:
    settings = settings or BuildingRules()
    return (
        "[Building]\r\n"
        + _line("TexturePath", settings.texture_path)
        + _line("AnimationFPS", settings.animation_fps)
        + _line("animation_type", settings.animation_type)
        + _line("AudioMaterial", settings.audio_material)
        + _line("Capacity", settings.capacity)
        + _line("Category", settings.category)
        + _line("HitPoints", settings.hit_points)
        + _line("MultipleBuildings", settings.multiple_buildings)
        + _line("IncendiaryRadius", _decimal(settings.incendiary_radius))
        + _optional("CanBurn", settings.can_burn)
        + _optional("Auxiliary", settings.auxiliary)
        + _optional("Joiner", settings.joiner)
        + _optional("Collision3D", settings.collision_3d)
        + _optional("GunType", settings.gun_type)
    )


# Byte-identical to the rules.bob CA ships beside rome_man_game, the Assembly Kit's only skeleton.
# ExportAsReferencePose is what makes BOB compile the .cs2 as a rest pose rather than a clip, and
# AnimationType is deliberately the literal "not_used" here - a skeleton has no skeleton of its own.
# Both are what a skeleton *is*, so neither is a setting; TargetPath is the one key left to choose.
def skeleton_rules_text(settings: SkeletonRules | None = None) -> str:
    settings = settings or SkeletonRules()
    return (
        "[Animation]\r\n"
        "\t<FILES> = ....cs2\r\n"
        "\tAnimationType = not_used\r\n"
        "\tExportAsReferencePose = true\r\n"
        + _optional("TargetPath", settings.target_path)
        + "\r\n"
    )


# Modelled on the rules.bob CA ships at raw_data/variantmeshes/VariantModels/, the folder every
# authored unit part lives under. AnimationType here is the folder's default - the skeleton BOB
# stamps into the compiled header's m_bone_table_name (PLAN_units.md 1.8) for any file no
# [+RigidModelV2] override names. Each exported part still gets its own override from the skeleton
# it is bound to in Blender, and an override wins over this.
def unit_rules_base(settings: UnitRules | None = None) -> str:
    settings = settings or UnitRules()
    return (
        "[RigidModelV2]\r\n"
        + _line("TargetPath", settings.target_path)
        + _line("TextureFolder", settings.texture_folder)
        + _line("TextureSubFolder", settings.texture_subfolder, separator="=")
        + _line("AnimationType", settings.animation_type)
        + _line("SaveAGF", settings.save_agf)
        + _rigid_model_extras(settings)
        + _optional("LODDistance1", settings.lod_distance_1)
        + _optional("LODDistance2", settings.lod_distance_2)
        + _optional("LODDistance3", settings.lod_distance_3)
        + _optional("LODDistance4", settings.lod_distance_4)
    )

# One override section per part whose skeleton differs from the folder default, in CA's own
# [+RigidModelV2] <Files> form - a folder can hold a weighted body and a rigid weapon at once, and
# they need different AnimationTypes.
_UNIT_RULES_OVERRIDE = (
    "\r\n"
    "[+RigidModelV2]\r\n"
    "\t<Files> = {files}\r\n"
    "\tAnimationType = {animation_type}\r\n"
)

# Modelled on the rules.bob CA ships at raw_data/animations/ROME2/human/, which every authored clip
# under it inherits. AnimationType is the skeleton BOB resolves the .bone_table by, and the seven
# channel flags are what make a compiled clip rotation-only except on the root and floating bones -
# CA sets all seven false on every animation folder in the kit, and the compiled output matches
# (sws_run_443_cm keeps 6 translation tracks out of 50 bones).
def animation_rules_base(settings: AnimationRules | None = None) -> str:
    settings = settings or AnimationRules()
    return (
        "[Animation]\r\n"
        + _line("CoreTranslations", settings.core_translations)
        + _line("FaceTranslations", settings.face_translations)
        + _line("FaceRotations", settings.face_rotations)
        + _line("LeftHandTranslations", settings.left_hand_translations)
        + _line("LeftHandRotations", settings.left_hand_rotations)
        + _line("RightHandTranslations", settings.right_hand_translations)
        + _line("RightHandRotations", settings.right_hand_rotations)
        + _line("IgnoreMetadata", settings.ignore_metadata)
        + _optional("AnimationType", settings.animation_type)
        + _optional("TargetPath", settings.target_path)
        + _optional("CinematicAnimationType", settings.cinematic_animation_type)
        + _optional("CinematicCoreTranslations", settings.cinematic_core_translations)
        + _optional("CinematicFaceTranslations", settings.cinematic_face_translations)
        + _optional("CinematicFaceRotations", settings.cinematic_face_rotations)
        + _optional("CinematicLeftHandTranslations", settings.cinematic_left_hand_translations)
        + _optional("CinematicLeftHandRotations", settings.cinematic_left_hand_rotations)
        + _optional("CinematicRightHandTranslations", settings.cinematic_right_hand_translations)
        + _optional("CinematicRightHandRotations", settings.cinematic_right_hand_rotations)
    )

# One override per clip, in the same [+Section] <Files> form CA uses for unit parts: a folder fills
# up over several exports, and each clip carries its own skeleton and its own sampling rate.
_ANIMATION_RULES_OVERRIDE = (
    "\r\n"
    "[+Animation]\r\n"
    "\t<Files> = {files}\r\n"
    "\tAnimationType = {animation_type}\r\n"
    "\tFPS={fps:g}\r\n"
)

ANIMATION_SECTION = SKELETON_SECTION

UNIT_SECTION = "[rigidmodelv2]"
BACKSLASH = "\\"


def building_name_for(cs2_path: Path) -> str:
    return Path(cs2_path).stem.lower()


def pack_path(assembly_kit_root: str, building_name: str) -> Path:
    return Path(assembly_kit_root) / "retail" / "data" / f"{building_name}.pack"


def installed_pack_path(assembly_kit_root: str, building_name: str) -> Path:
    return Path(assembly_kit_root).parent / "data" / f"{building_name}.pack"


def building_rule_in_scope(assembly_kit_root: str, cs2_path: Path) -> bool:
    return _rule_in_scope(assembly_kit_root, cs2_path, BUILDING_SECTION)


def skeleton_rule_in_scope(assembly_kit_root: str, cs2_path: Path) -> bool:
    return _rule_in_scope(assembly_kit_root, cs2_path, SKELETON_SECTION)


def ensure_building_rules(
    assembly_kit_root: str,
    cs2_path: Path,
    settings: BuildingRules | None = None,
    overwrite: bool = False,
) -> Path | None:
    return _ensure_rules(
        assembly_kit_root,
        cs2_path,
        BUILDING_SECTION,
        building_rules_text(settings),
        _is_customised(settings),
        overwrite,
    )


def ensure_skeleton_rules(
    assembly_kit_root: str,
    cs2_path: Path,
    settings: SkeletonRules | None = None,
    overwrite: bool = False,
) -> Path | None:
    return _ensure_rules(
        assembly_kit_root,
        cs2_path,
        SKELETON_SECTION,
        skeleton_rules_text(settings),
        _is_customised(settings),
        overwrite,
    )


def unit_rule_in_scope(assembly_kit_root: str, cs2_path: Path) -> bool:
    return _rule_in_scope(assembly_kit_root, cs2_path, UNIT_SECTION)


def _unit_override(stem: str, animation_type: str) -> str:
    return _UNIT_RULES_OVERRIDE.format(files=f"...{stem}.cs2", animation_type=animation_type)


def _unit_override_pattern(stem: str) -> re.Pattern:
    return re.compile(
        r"\[\+RigidModelV2\]\r\n\t<Files> = "
        + re.escape(f"...{stem}.cs2")
        + r"\r\n\tAnimationType = [^\r\n]*\r\n"
    )


def _update_unit_overrides(text: str, parts: list[tuple[str, str]]) -> str | None:
    # A re-export after the bound skeleton was renamed in Blender carries the same file stem but a
    # new AnimationType - the existing override has to be replaced, not skipped as "already there",
    # or rules.bob keeps stamping the .rigid_model_v2 with the skeleton's old name forever.
    changed = False
    for stem, animation_type in parts:
        override = _unit_override(stem, animation_type)
        if override in text:
            continue
        replaced, count = _unit_override_pattern(stem).subn(override[2:], text, count=1)
        text = replaced if count else text.rstrip("\r\n") + "\r\n" + override
        changed = True
    return text if changed else None


def unit_rules_text(parts: list[tuple[str, str]], settings: UnitRules | None = None) -> str:
    # parts is (file stem, animation type). Every asset gets its own [+RigidModelV2] override rather
    # than sharing a section default: assets are exported one at a time, so a folder fills up over
    # several exports and each file has to carry its own skeleton name. The base section holds only
    # what they all share, with an empty AnimationType - which is also the right answer for a
    # weapon or a prop that no override names.
    text = unit_rules_base(settings)
    for stem, animation_type in parts:
        text += _unit_override(stem, animation_type)
    return text


# Key presence, not the shipped values: a customised TextureSubFolder or an unticked SaveAGF still
# has to read as ours. SaveAGF is also what tells a unit's [RigidModelV2] from a tree's.
def _is_addon_unit_rules(text: str) -> bool:
    return _section_has_keys(text, UNIT_SECTION, ("TextureSubFolder", "SaveAGF"))


def inside_raw_data(assembly_kit_root: str, cs2_path: Path) -> bool:
    try:
        Path(cs2_path).resolve().relative_to((Path(assembly_kit_root) / "raw_data").resolve())
    except (ValueError, OSError):
        return False
    return True


def unit_rules_written_by_addon(cs2_path: Path) -> bool:
    # A rules.bob this add-on wrote declares [RigidModelV2] like any other, so _rule_in_scope alone
    # cannot tell "already ours and up to date" from "someone else's".
    try:
        text = (Path(cs2_path).parent / RULES_FILENAME).read_bytes().decode("ascii", errors="replace")
    except OSError:
        return False
    return _is_addon_unit_rules(text)


def ensure_unit_rules(
    assembly_kit_root: str,
    cs2_path: Path,
    parts: list[tuple[str, str]],
    settings: UnitRules | None = None,
    overwrite: bool = False,
) -> Path | None:
    if not inside_raw_data(assembly_kit_root, cs2_path):
        return None

    base = unit_rules_base(settings)
    rules_path = Path(cs2_path).parent / RULES_FILENAME
    if rules_path.exists():
        # Bytes, not read_text: universal newlines would turn the file's CRLF into LF and appending
        # to it would leave a rules.bob with mixed line endings.
        text = _read_rules(rules_path)
        if base_section_changes(text, UNIT_SECTION, base):
            # The base section is not what this export asks for - someone else's file, or ours from
            # before the settings changed. Replacing it keeps every [+RigidModelV2] override already
            # there, so the other parts sharing the folder keep their skeletons.
            if not (_is_customised(settings) and overwrite):
                return None
            kept = base + _overrides_of(text)
            rules_path.write_bytes((_update_unit_overrides(kept, parts) or kept).encode("ascii"))
            return rules_path
        if not _is_addon_unit_rules(text):
            # Someone else's rules.bob - the caller warns rather than this overwriting it.
            return None
        updated = _update_unit_overrides(text, parts)
        if updated is None:
            return None
        rules_path.write_bytes(updated.encode("ascii"))
        return rules_path

    if _rule_in_scope(assembly_kit_root, cs2_path, UNIT_SECTION) and not _is_customised(settings):
        return None
    rules_path.write_bytes(unit_rules_text(parts, settings).encode("ascii"))
    return rules_path


# Every key here was settled by real BOB runs against a hand-built tree, not by analogy:
#   - the section is [RigidModelV2] and the processor is Cs2. A [Tree] or [RigidMesh] section
#     registers no action for a .CS2 at all - BOB exits 0 having done nothing.
#   - AnimationType = tree is what stamps `tree` into the compiled m_bone_table_name, exactly as
#     `building` does for buildings. There is no tree.bone_table anywhere in the kit and BOB does
#     not want one: it writes the .CS2's own bone indices straight through.
#   - CreateRigidModelDescriptionFile is misleadingly documented. It is what makes BOB emit the
#     <name>_tech.cs2.parsed sidecar - the burn hull plus the fire emitters spread over it - and
#     without it only the .rigid_model_v2 appears.
#   - IncendiaryRadius sets how densely those emitters are spread ("2 incendiary points have been
#     generated" for a small oak at 2.0, matching what the shipped trees carry).
#   - LODDistance1..4 are the fixed ladder; which rung a mesh lands on comes from its node's
#     _lodNN postfix, not from the order the nodes appear in.
# `Tree = true`, the billboard switch, is deliberately absent - see the note below it.
# The three paths default to empty and are derived by vegetation_paths_for from where the .CS2 sits
# inside raw_data, so a batch exporting into one folder still lands each model where the game's own
# trees live. A setting fills in only when the artist overrides one.
def vegetation_rules_base(
    target_path: str, texture_folder: str, texture_subfolder: str, settings: "VegetationRules | None" = None
) -> str:
    settings = settings or VegetationRules()
    return (
        "[RigidModelV2]\r\n"
        + _line("TargetPath", settings.target_path or target_path)
        + _line("TextureFolder", settings.texture_folder or texture_folder)
        + _line("TextureSubFolder", settings.texture_subfolder or texture_subfolder, separator="=")
        + _line("AnimationType", settings.animation_type)
        + _line("CreateRigidModelDescriptionFile", settings.create_description_file)
        + _line("IncendiaryRadius", _decimal(settings.incendiary_radius))
        + _line("LODDistance1", settings.lod_distance_1)
        + _line("LODDistance2", settings.lod_distance_2)
        + _line("LODDistance3", settings.lod_distance_3)
        + _line("LODDistance4", settings.lod_distance_4)
        + _rigid_model_extras(settings)
    )

# Setting `Tree = true` - the key whose own documentation string is "True if tree billboard
# processing is required" - makes BOB dereference a null pointer inside
# Warscape.AssemblyKit.dll+0x12a71 and abort with 0xC0000005 before it builds anything. Measured
# under a debugger, reproducibly, on a plain default-material .CS2 as well as on a tree, so it is
# the switch itself and not the model. Leaving it out costs the generated billboard LOD and nothing
# else. Deliberately not surfaced to the artist: there is nothing they can do about it, and a
# warning on every correct export is noise.

# BOB does not copy the gloss map's filename through the way it does the diffuse and the normal: it
# rebuilds the compiled GLOSS_MAP name as <everything before the source's last underscore>_gloss_map.
# The source is the Gloss slot (t_smoothness), measured by compiling five distinguishable texture
# names and seeing "aaa_gloss" come back as "aaa_gloss_map.dds". So the game's own test_gloss_map.dds
# was authored as test_gloss.tga, and re-exporting a model whose Gloss slot still points at the
# compiled name gets test_gloss_gloss_map.dds instead.
GLOSS_MAP_SUFFIX = "_gloss_map"


def compiled_gloss_map_name(source_stem: str) -> str:
    return source_stem.rpartition("_")[0] + GLOSS_MAP_SUFFIX


VEGETATION_SECTION = UNIT_SECTION
VEGETATION_TARGET_PATH = "BattleTerrain" + BACKSLASH + "vegetation" + BACKSLASH + "trees" + BACKSLASH
VEGETATION_TEXTURE_SUBFOLDER = "textures"


def _is_addon_vegetation_rules(text: str) -> bool:
    return _section_has_keys(text, VEGETATION_SECTION, ("CreateRigidModelDescriptionFile",))


def vegetation_rules_text(
    target_path: str,
    texture_folder: str,
    texture_subfolder: str,
    settings: VegetationRules | None = None,
) -> str:
    return vegetation_rules_base(target_path, texture_folder, texture_subfolder, settings)


def vegetation_paths_for(assembly_kit_root: str, cs2_path: Path) -> tuple[str, str, str]:
    # BOB writes the compiled model under working_data at TargetPath and stamps
    # TextureFolder + TextureSubFolder into every mesh's texture directory, so mirroring the .CS2's
    # own place inside raw_data is what puts an exported tree where the game's own trees live.
    directory = Path(cs2_path).resolve().parent
    try:
        relative = directory.relative_to((Path(assembly_kit_root) / "raw_data").resolve())
    except (ValueError, OSError):
        return VEGETATION_TARGET_PATH, VEGETATION_TARGET_PATH, VEGETATION_TEXTURE_SUBFOLDER
    target = str(relative).replace("/", BACKSLASH) + BACKSLASH
    textures = str(relative.parent).replace("/", BACKSLASH) + BACKSLASH + VEGETATION_TEXTURE_SUBFOLDER + BACKSLASH
    return target, textures, relative.name


def vegetation_rules_written_by_addon(cs2_path: Path) -> bool:
    try:
        text = (Path(cs2_path).parent / RULES_FILENAME).read_bytes().decode("ascii", errors="replace")
    except OSError:
        return False
    return _is_addon_vegetation_rules(text)


def ensure_vegetation_rules(
    assembly_kit_root: str,
    cs2_path: Path,
    settings: VegetationRules | None = None,
    overwrite: bool = False,
) -> Path | None:
    paths = vegetation_paths_for(assembly_kit_root, cs2_path)
    return _ensure_rules(
        assembly_kit_root,
        cs2_path,
        VEGETATION_SECTION,
        vegetation_rules_text(*paths, settings),
        _is_customised(settings),
        overwrite,
    )


def _animation_override(stem: str, animation_type: str, fps: float) -> str:
    return _ANIMATION_RULES_OVERRIDE.format(files=f"...{stem}.cs2", animation_type=animation_type, fps=fps)


def _animation_override_pattern(stem: str) -> re.Pattern:
    return re.compile(
        r"\[\+Animation\]\r\n\t<Files> = "
        + re.escape(f"...{stem}.cs2")
        + r"\r\n\tAnimationType = [^\r\n]*\r\n\tFPS=[^\r\n]*\r\n"
    )


def _update_animation_overrides(text: str, clips: list[tuple[str, str, float]]) -> str | None:
    # Same staleness problem as _update_unit_overrides: re-exporting a clip after its skeleton was
    # renamed must replace the existing override, not leave the old AnimationType standing because
    # the file stem already appears somewhere in the text.
    changed = False
    for stem, animation_type, fps in clips:
        override = _animation_override(stem, animation_type, fps)
        if override in text:
            continue
        replaced, count = _animation_override_pattern(stem).subn(override[2:], text, count=1)
        text = replaced if count else text.rstrip("\r\n") + "\r\n" + override
        changed = True
    return text if changed else None


def animation_rules_text(clips: list[tuple[str, str, float]], settings: AnimationRules | None = None) -> str:
    # clips is (file stem, skeleton name, fps).
    return animation_rules_base(settings) + "".join(_animation_override(*clip) for clip in clips)


def _is_addon_animation_rules(text: str) -> bool:
    return (
        _section_has_keys(text, ANIMATION_SECTION, ("IgnoreMetadata",))
        and "ExportAsReferencePose" not in text
    )


def ensure_animation_rules(
    assembly_kit_root: str,
    cs2_path: Path,
    clips: list[tuple[str, str, float]],
    settings: AnimationRules | None = None,
    overwrite: bool = False,
) -> Path | None:
    if not inside_raw_data(assembly_kit_root, cs2_path):
        return None

    base = animation_rules_base(settings)
    rules_path = Path(cs2_path).parent / RULES_FILENAME
    if rules_path.exists():
        text = _read_rules(rules_path)
        if base_section_changes(text, ANIMATION_SECTION, base):
            if not (_is_customised(settings) and overwrite):
                return None
            kept = base + _overrides_of(text)
            rules_path.write_bytes((_update_animation_overrides(kept, clips) or kept).encode("ascii"))
            return rules_path
        if not _is_addon_animation_rules(text):
            return None
        updated = _update_animation_overrides(text, clips)
        if updated is None:
            return None
        rules_path.write_bytes(updated.encode("ascii"))
        return rules_path

    rules_path.write_bytes(animation_rules_text(clips, settings).encode("ascii"))
    return rules_path


# rules.bob is CRLF INI, and BOB reads the nearest one as a whole: replacing the section this
# add-on owns must leave every other section in the file standing, including the [+Section]
# <Files> overrides that bind each part or clip to its own skeleton.
def _read_rules(rules_path: Path) -> str:
    # Bytes, not read_text: universal newlines would turn the file's CRLF into LF, and everything
    # downstream matches on CRLF.
    return rules_path.read_bytes().decode("ascii", errors="replace")


def _split_blocks(text: str) -> list[list[str]]:
    blocks: list[list[str]] = []
    for line in text.split("\r\n"):
        if line.strip().startswith("["):
            blocks.append([line])
        elif blocks:
            blocks[-1].append(line)
    return blocks


def _block_entries(block: list[str]) -> list[tuple[str, str]]:
    entries = []
    for line in block[1:]:
        stripped = line.strip()
        if not stripped:
            continue
        key, separator, value = stripped.partition("=")
        if separator:
            entries.append((key.strip(), value.strip()))
    return entries


def _find_block(text: str, section: str) -> list[str] | None:
    for block in _split_blocks(text):
        if block[0].strip().lower() == section:
            return block
    return None


def _section_has_keys(text: str, section: str, keys: tuple[str, ...]) -> bool:
    block = _find_block(text, section)
    if block is None:
        return False
    present = {key.lower() for key, _ in _block_entries(block)}
    return all(key.lower() in present for key in keys)


def _without_section(text: str, section: str) -> str:
    kept = []
    dropped = False
    for block in _split_blocks(text):
        if not dropped and block[0].strip().lower() == section:
            dropped = True
            continue
        kept.append(block)
    return "".join("\r\n" + "\r\n".join(block).rstrip("\r\n") + "\r\n" for block in kept)


def _overrides_of(text: str) -> str:
    return "".join(
        "\r\n" + "\r\n".join(block).rstrip("\r\n") + "\r\n"
        for block in _split_blocks(text)
        if block[0].strip().startswith("[+")
    )


def base_section_changes(text: str, section: str, base_text: str) -> list[str]:
    header = base_text.split("\r\n", 1)[0].strip()
    theirs = _find_block(text, section)
    if theirs is None:
        return [f"it declares no {header} section at all"]
    ours = _block_entries(_split_blocks(base_text)[0])
    existing = {key.lower(): value for key, value in _block_entries(theirs)}
    changes = [
        f"{key}: {existing[key.lower()]} -> {value}" if key.lower() in existing else f"{key}: -> {value}"
        for key, value in ours
        if existing.get(key.lower()) != value
    ]
    mine = {key.lower() for key, _ in ours}
    changes.extend(
        f"{key}: {value} -> dropped" for key, value in _block_entries(theirs) if key.lower() not in mine
    )
    return changes


def rules_conflict(
    assembly_kit_root: str, directory: Path, section: str, base_text: str, settings
) -> list[str]:
    # What the export dialog asks before it writes: nothing to confirm unless the artist changed a
    # setting away from its default AND a rules.bob is already sitting where BOB would read it.
    if not _is_customised(settings):
        return []
    directory = Path(directory)
    if not inside_raw_data(assembly_kit_root, directory / "x.CS2"):
        return []
    rules_path = directory / RULES_FILENAME
    if not rules_path.exists():
        return []
    return base_section_changes(_read_rules(rules_path), section, base_text)


def unwritten_settings_warning(
    assembly_kit_root: str, directory: Path, section: str, base_text: str, settings
) -> str | None:
    # Only reachable when the artist declined the overwrite, or when a background Blender had
    # nobody to ask: either way what is on disk is not what the export dialog said it would build.
    if not rules_conflict(assembly_kit_root, directory, section, base_text, settings):
        return None
    return (
        f"A rules.bob already covers {directory} and it was left alone, so the export settings you "
        "changed did not reach BOB - the values in that file are what it will build against."
    )


def _rule_in_scope(assembly_kit_root: str, cs2_path: Path, section: str) -> bool:
    raw_data = Path(assembly_kit_root) / "raw_data"
    try:
        raw_data = raw_data.resolve()
        directory = Path(cs2_path).resolve().parent
        directory.relative_to(raw_data)
    except (ValueError, OSError):
        return False
    # BOB rules cascade down the tree and the nearest one wins, so a matching section anywhere
    # between the export folder and raw_data already covers this file - writing another would
    # override whatever that one says with our defaults.
    for folder in [directory, *directory.parents]:
        if _declares_rule(folder / RULES_FILENAME, section):
            return True
        if folder == raw_data:
            break
    return False


def _ensure_rules(
    assembly_kit_root: str,
    cs2_path: Path,
    section: str,
    contents: str,
    customised: bool = False,
    overwrite: bool = False,
) -> Path | None:
    if not inside_raw_data(assembly_kit_root, cs2_path):
        return None
    rules_path = Path(cs2_path).parent / RULES_FILENAME
    if rules_path.exists():
        # Left alone unless the artist asked for values this file does not carry and confirmed the
        # overwrite - the [+Section] overrides in it are kept either way.
        if not customised or not overwrite:
            return None
        text = _read_rules(rules_path)
        if not base_section_changes(text, section, contents):
            return None
        rules_path.write_bytes((contents + _without_section(text, section)).encode("ascii"))
        return rules_path
    if _rule_in_scope(assembly_kit_root, cs2_path, section) and not customised:
        return None
    rules_path.write_bytes(contents.encode("ascii"))
    return rules_path


def _declares_rule(rules_path: Path, section: str) -> bool:
    try:
        text = rules_path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return False
    return any(line.strip().lower() == section for line in text.splitlines())


def write_pack_rules(
    assembly_kit_root: str, building_names: list[str], pack_type: str = DEFAULT_PACK_TYPE
) -> None:
    for building_name in building_names:
        _write_rules(
            _building_pack_dir(assembly_kit_root, building_name),
            _pack_section(building_name, pack_type, files=""),
        )
    # Every building of a run shares the one db folder, so its rules.bob carries a <Files>-scoped
    # section per pack rather than one file per building. Measured with two buildings packed in a
    # single BOB run: each pack came out holding only its own two tables and its own model.
    _write_rules(
        _db_pack_dir(assembly_kit_root),
        "".join(
            _pack_section(building_name, pack_type, files=_db_pack_files(building_name))
            for building_name in building_names
        ),
    )


def remove_pack_rules(assembly_kit_root: str, building_names: list[str]) -> None:
    directories = [_building_pack_dir(assembly_kit_root, name) for name in building_names]
    directories.append(_db_pack_dir(assembly_kit_root))
    for directory in directories:
        try:
            (directory / RULES_FILENAME).unlink(missing_ok=True)
        except OSError:
            pass


def install_pack(assembly_kit_root: str, building_name: str) -> Path:
    destination = installed_pack_path(assembly_kit_root, building_name)
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        destination.unlink()
    shutil.move(str(pack_path(assembly_kit_root, building_name)), str(destination))
    return destination


# A rules.bob only ever covers files inside its own folder, and a building's compiled output and its
# two db tables live in different trees - hence one section per tree, both naming the same PackFile
# so BOB merges them into a single pack. A nearer rules.bob overrides the one above it, which is what
# keeps these files out of working_data/rules.bob's catch-all mod.pack.
def _building_pack_dir(assembly_kit_root: str, building_name: str) -> Path:
    return Path(assembly_kit_root) / "working_data" / "RigidModels" / "Buildings" / building_name


def _db_pack_dir(assembly_kit_root: str) -> Path:
    return Path(assembly_kit_root) / "working_data" / "db"


def _db_pack_files(building_name: str) -> str:
    return ", ".join(
        f"{folder}/bob_building_{building_name}_{suffix}" for folder, suffix in DB_TABLES
    )


def _pack_section(building_name: str, pack_type: str, files: str) -> str:
    lines = ["[Pack]"]
    if files:
        lines.append(f"\t<Files> = {files}")
    lines.extend(
        [
            "\tBasePath = /",
            f"\tPackFile = <retail>/data/{building_name}.pack",
            f"\tPackType = {pack_type}",
        ]
    )
    return "\r\n".join(lines) + "\r\n"


def _write_rules(directory: Path, contents: str) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    (directory / RULES_FILENAME).write_bytes(contents.encode("ascii"))
