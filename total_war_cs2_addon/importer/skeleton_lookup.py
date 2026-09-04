from dataclasses import dataclass
from pathlib import Path

from binary.anim_reader import read_anim
from binary.cs2_reader import read_cs2
from scene_model.skeleton_builder import is_animation_document, is_skeleton_document

CS2_SOURCE = "CS2"
ANIM_SOURCE = "ANIM"

RAW_DATA_SKELETONS = ("raw_data", "animations", "skeletons")
WORKING_DATA_SKELETONS = ("working_data", "animations", "skeletons")


@dataclass
class SkeletonSource:
    path: Path
    kind: str
    bone_table_path: Path | None = None
    # Which step of the cascade produced it, for the artist-facing message.
    where: str = ""


def _skeleton_folder(assembly_kit_root: str, parts: tuple[str, ...]) -> Path | None:
    if not assembly_kit_root:
        return None
    return Path(assembly_kit_root).joinpath(*parts)


def _files(folder: Path | None, suffix: str) -> list[Path]:
    if folder is None:
        return []
    try:
        return sorted(path for path in folder.iterdir() if path.suffix.lower() == suffix)
    except OSError:
        return []


def _is_skeleton_cs2(path: Path) -> bool:
    try:
        document = read_cs2(path.read_bytes())
    except Exception:  # noqa: BLE001 - a file that will not parse is simply not a candidate
        return False
    return is_skeleton_document(document) and not is_animation_document(document)


def _anim_skeleton_name(path: Path) -> str | None:
    try:
        return read_anim(path.read_bytes()).skeleton_name
    except Exception:  # noqa: BLE001
        return None


def _bone_table_for(skeleton_name: str, beside: Path, assembly_kit_root: str) -> Path | None:
    # The bone types live in the authored .bone_table, which sits beside the .cs2 in raw_data and
    # never beside a compiled .anim - so a .anim found in working_data still gets its bone types
    # when the authored folder is there.
    raw_data = _skeleton_folder(assembly_kit_root, RAW_DATA_SKELETONS)
    candidates = [beside.with_suffix(".bone_table"), beside.parent / f"{skeleton_name}.bone_table"]
    if raw_data is not None:
        candidates.append(raw_data / f"{skeleton_name}.bone_table")
    return next((candidate for candidate in candidates if candidate.is_file()), None)


def _find_anim(folder: Path | None, skeleton_name: str, assembly_kit_root: str, where: str):
    wanted = skeleton_name.lower()
    for path in _files(folder, ".anim"):
        # A .anim names its skeleton inside the file, so it is matched on that rather than on
        # whatever the file happens to be called. The .bone_inv_trans_mats BOB writes alongside is
        # deliberately not read: it holds the inverse bind matrices, which is the same rest pose the
        # .anim's own first frame already carries.
        if (_anim_skeleton_name(path) or "").lower() == wanted:
            return SkeletonSource(path, ANIM_SOURCE, _bone_table_for(skeleton_name, path, assembly_kit_root), where)
    return None


def _find_cs2(folder: Path | None, skeleton_name: str, assembly_kit_root: str, where: str):
    wanted = skeleton_name.lower()
    for path in _files(folder, ".cs2"):
        # A skeleton .cs2 carries no name of its own, so this one is matched by filename.
        if path.stem.lower() == wanted and _is_skeleton_cs2(path):
            return SkeletonSource(path, CS2_SOURCE, _bone_table_for(skeleton_name, path, assembly_kit_root), where)
    return None


# The cascade, in the order an artist would look themselves. It runs only for a model that both
# holds weighted meshes and names a skeleton - a weapon or a building names none, and has nothing
# to look up.
def find_skeleton_source(
    skeleton_name: str, model_path: Path, assembly_kit_root: str
) -> SkeletonSource | None:
    if not skeleton_name:
        return None

    model_folder = Path(model_path).parent
    raw_data = _skeleton_folder(assembly_kit_root, RAW_DATA_SKELETONS)
    working_data = _skeleton_folder(assembly_kit_root, WORKING_DATA_SKELETONS)

    return (
        _find_anim(model_folder, skeleton_name, assembly_kit_root, "beside the model")
        or _find_cs2(raw_data, skeleton_name, assembly_kit_root, "the Assembly Kit's raw_data skeletons")
        or _find_anim(working_data, skeleton_name, assembly_kit_root, "the Assembly Kit's working_data skeletons")
    )


def searched_locations(model_path: Path, assembly_kit_root: str) -> list[str]:
    folders = [Path(model_path).parent]
    for parts in (RAW_DATA_SKELETONS, WORKING_DATA_SKELETONS):
        folder = _skeleton_folder(assembly_kit_root, parts)
        if folder is not None:
            folders.append(folder)
    return [str(folder) for folder in folders]


__all__ = [
    "ANIM_SOURCE",
    "CS2_SOURCE",
    "SkeletonSource",
    "find_skeleton_source",
    "searched_locations",
]
