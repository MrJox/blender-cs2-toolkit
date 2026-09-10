from pathlib import Path

import bpy

from binary.bone_table import write_bone_table
from binary.cs2_writer import write_cs2
from bob.rules import (
    SKELETON_SECTION,
    SkeletonRules,
    ensure_skeleton_rules,
    skeleton_rules_text,
    unwritten_settings_warning,
)
from extraction.extract import ExtractionError
from extraction.skeleton_extract import extract_skeleton
from scene_model.skeleton_builder import (
    SkeletonBuildError,
    build_bone_table,
    build_skeleton_cs2_document,
)
from validation.rules import validate_skeleton
from .exporter import ExportResult, _write_bytes_atomically, blocking_export_result, export_boundary

# BOB resolves a skeleton's bone definition by name out of this one folder, not from beside the
# .cs2: compiling an identical pair from raw_data/animations/skeletons/<subfolder>/ fails with
# "Unrecognised animation type or missing bone definition file", while the same pair directly in
# raw_data/animations/skeletons/ compiles clean to a .anim plus a .bone_inv_trans_mats.
SKELETON_RAW_DATA_FOLDER = ("animations", "skeletons")


def bone_table_folder(assembly_kit_root: str) -> Path | None:
    try:
        folder = Path(assembly_kit_root).resolve() / "raw_data"
    except OSError:
        return None
    for part in SKELETON_RAW_DATA_FOLDER:
        folder = folder / part
    return folder


def _bone_table_is_findable(assembly_kit_root: str, output_path: Path) -> bool:
    expected = bone_table_folder(assembly_kit_root)
    if expected is None:
        return False
    try:
        return output_path.parent.resolve() == expected
    except OSError:
        return False


@export_boundary(ExtractionError, SkeletonBuildError)
def export_skeleton(
    skeleton_collection: bpy.types.Collection,
    output_dir: str,
    assembly_kit_root: str,
    rules_settings: SkeletonRules | None = SkeletonRules(),
    overwrite_rules: bool = False,
) -> ExportResult:
    blocked = blocking_export_result(validate_skeleton(skeleton_collection))
    if blocked is not None:
        return blocked

    skeleton, warnings = extract_skeleton(skeleton_collection)

    output_path = Path(bpy.path.abspath(output_dir)) / f"{skeleton.name}.CS2"
    output_path.parent.mkdir(parents=True, exist_ok=True)

    document = build_skeleton_cs2_document(skeleton, output_path=str(output_path))
    _write_bytes_atomically(output_path, write_cs2(document))

    bone_table_path = output_path.with_suffix(".bone_table")
    _write_bytes_atomically(bone_table_path, write_bone_table(build_bone_table(skeleton)))

    if not _bone_table_is_findable(assembly_kit_root, output_path):
        folder = "/".join(SKELETON_RAW_DATA_FOLDER)
        warnings.append(
            f"BOB looks a skeleton's bone definition up in raw_data/{folder} by name, so it will "
            f"not find {bone_table_path.name} where this was exported - move both files there "
            "before building, or BOB reports 'Unrecognised animation type or missing bone "
            "definition file'."
        )

    if rules_settings is not None:
        created_rules = ensure_skeleton_rules(
            assembly_kit_root, output_path, rules_settings, overwrite_rules
        )
        if created_rules is not None:
            warnings.append(
                f"BOB needs a rules.bob beside a skeleton to process it, and this folder had none - "
                f"created {created_rules}"
            )
        else:
            declined = unwritten_settings_warning(
                assembly_kit_root,
                output_path.parent,
                SKELETON_SECTION,
                skeleton_rules_text(rules_settings),
                rules_settings,
            )
            if declined is not None:
                warnings.append(declined)

    return ExportResult(
        success=True,
        message=f"Exported '{output_path.name}' and '{bone_table_path.name}' to {output_path.parent}.",
        warnings=warnings,
        cs2_path=output_path,
    )
