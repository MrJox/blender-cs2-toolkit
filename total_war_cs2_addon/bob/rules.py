import shutil
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

# Byte-identical to the rules.bob CA ships beside their own buildings - raw_data's `eastern` and
# `gondorean` architecture folders both carry exactly this file. BOB parses rules.bob as CRLF INI.
_BUILDING_RULES = (
    "[Building]\r\n"
    "\tTexturePath = RigidModels\\Buildings\\Textures\\\r\n"
    "\tAnimationFPS = 20\r\n"
    "\tanimation_type = building\r\n"
    "\tAudioMaterial = wood\r\n"
    "\tCapacity = 500\r\n"
    "\tCategory = generic\r\n"
    "\tHitPoints = 500\r\n"
    "\tMultipleBuildings = true\r\n"
    "\tIncendiaryRadius = 9.0\r\n"
)

# Byte-identical to the rules.bob CA ships beside rome_man_game, the Assembly Kit's only skeleton.
# ExportAsReferencePose is what makes BOB compile the .cs2 as a rest pose rather than a clip, and
# AnimationType is deliberately the literal "not_used" here - a skeleton has no skeleton of its own.
_SKELETON_RULES = (
    "[Animation]\r\n"
    "\t<FILES> = ....cs2\r\n"
    "\tAnimationType = not_used\r\n"
    "\tExportAsReferencePose = true\r\n"
    "\r\n"
)


# Modelled on the rules.bob CA ships at raw_data/variantmeshes/VariantModels/, the folder every
# authored unit part lives under. AnimationType is the whole point: PLAN_units.md 1.8 established
# that it, not any CS2 field, is what BOB stamps into the compiled header's m_bone_table_name - the
# skeleton name for a weighted part, and deliberately empty for a weapon, shield or prop.
_UNIT_RULES_TEMPLATE = (
    "[RigidModelV2]\r\n"
    "\tTargetPath = {target_path}\r\n"
    "\tTextureFolder = {target_path}\r\n"
    "\tTextureSubFolder=tex\r\n"
    "\tAnimationType = {animation_type}\r\n"
    "\tSaveAGF = true\r\n"
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
_ANIMATION_RULES_TEMPLATE = (
    "[Animation]\r\n"
    "\tCoreTranslations = false\r\n"
    "\tFaceTranslations = false\r\n"
    "\tFaceRotations = false\r\n"
    "\tLeftHandTranslations = false\r\n"
    "\tLeftHandRotations = false\r\n"
    "\tRightHandTranslations = false\r\n"
    "\tRightHandRotations = false\r\n"
    "\tIgnoreMetadata = true\r\n"
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
UNIT_TARGET_PATH = "VariantMeshes\\_VariantModels\\"


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


def ensure_building_rules(assembly_kit_root: str, cs2_path: Path) -> Path | None:
    return _ensure_rules(assembly_kit_root, cs2_path, BUILDING_SECTION, _BUILDING_RULES)


def ensure_skeleton_rules(assembly_kit_root: str, cs2_path: Path) -> Path | None:
    return _ensure_rules(assembly_kit_root, cs2_path, SKELETON_SECTION, _SKELETON_RULES)


def unit_rule_in_scope(assembly_kit_root: str, cs2_path: Path) -> bool:
    return _rule_in_scope(assembly_kit_root, cs2_path, UNIT_SECTION)


def _unit_override(stem: str, animation_type: str) -> str:
    return _UNIT_RULES_OVERRIDE.format(files=f"...{stem}.cs2", animation_type=animation_type)


def unit_rules_text(parts: list[tuple[str, str]], target_path: str = UNIT_TARGET_PATH) -> str:
    # parts is (file stem, animation type). Every asset gets its own [+RigidModelV2] override rather
    # than sharing a section default: assets are exported one at a time, so a folder fills up over
    # several exports and each file has to carry its own skeleton name. The base section holds only
    # what they all share, with an empty AnimationType - which is also the right answer for a
    # weapon or a prop that no override names.
    text = _UNIT_RULES_TEMPLATE.format(target_path=target_path, animation_type="")
    for stem, animation_type in parts:
        text += _unit_override(stem, animation_type)
    return text


def _is_addon_unit_rules(text: str) -> bool:
    return "TextureSubFolder=tex" in text and "SaveAGF = true" in text


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


def ensure_unit_rules(assembly_kit_root: str, cs2_path: Path, parts: list[tuple[str, str]]) -> Path | None:
    if not inside_raw_data(assembly_kit_root, cs2_path):
        return None

    rules_path = Path(cs2_path).parent / RULES_FILENAME
    if rules_path.exists():
        # Bytes, not read_text: universal newlines would turn the file's CRLF into LF and appending
        # to it would leave a rules.bob with mixed line endings.
        text = rules_path.read_bytes().decode("ascii", errors="replace")
        if not _is_addon_unit_rules(text):
            # Someone else's rules.bob - the caller warns rather than this overwriting it.
            return None
        missing = [entry for entry in parts if f"...{entry[0]}.cs2" not in text]
        if not missing:
            return None
        appended = text.rstrip("\r\n") + "\r\n" + "".join(_unit_override(*entry) for entry in missing)
        rules_path.write_bytes(appended.encode("ascii"))
        return rules_path

    if _rule_in_scope(assembly_kit_root, cs2_path, UNIT_SECTION):
        return None
    rules_path.write_bytes(unit_rules_text(parts).encode("ascii"))
    return rules_path


def _animation_override(stem: str, animation_type: str, fps: float) -> str:
    return _ANIMATION_RULES_OVERRIDE.format(files=f"...{stem}.cs2", animation_type=animation_type, fps=fps)


def animation_rules_text(clips: list[tuple[str, str, float]]) -> str:
    # clips is (file stem, skeleton name, fps).
    return _ANIMATION_RULES_TEMPLATE + "".join(_animation_override(*clip) for clip in clips)


def _is_addon_animation_rules(text: str) -> bool:
    return "IgnoreMetadata = true" in text and "ExportAsReferencePose" not in text


def ensure_animation_rules(assembly_kit_root: str, cs2_path: Path, clips: list[tuple[str, str, float]]) -> Path | None:
    raw_data = Path(assembly_kit_root) / "raw_data"
    try:
        Path(cs2_path).resolve().relative_to(raw_data.resolve())
    except (ValueError, OSError):
        return None

    rules_path = Path(cs2_path).parent / RULES_FILENAME
    if rules_path.exists():
        text = rules_path.read_bytes().decode("ascii", errors="replace")
        if not _is_addon_animation_rules(text):
            return None
        missing = [clip for clip in clips if f"...{clip[0]}.cs2" not in text]
        if not missing:
            return None
        appended = text.rstrip("\r\n") + "\r\n" + "".join(_animation_override(*clip) for clip in missing)
        rules_path.write_bytes(appended.encode("ascii"))
        return rules_path

    rules_path.write_bytes(animation_rules_text(clips).encode("ascii"))
    return rules_path


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


def _ensure_rules(assembly_kit_root: str, cs2_path: Path, section: str, contents: str) -> Path | None:
    raw_data = Path(assembly_kit_root) / "raw_data"
    try:
        Path(cs2_path).resolve().relative_to(raw_data.resolve())
    except (ValueError, OSError):
        return None
    rules_path = Path(cs2_path).parent / RULES_FILENAME
    if rules_path.exists() or _rule_in_scope(assembly_kit_root, cs2_path, section):
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
