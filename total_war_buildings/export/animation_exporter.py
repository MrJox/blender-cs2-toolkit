from pathlib import Path

import bpy

from binary.cs2_writer import write_cs2
from bob.rules import ensure_animation_rules
from export.skeleton_exporter import SKELETON_RAW_DATA_FOLDER, bone_table_folder
from extraction.animation_extract import extract_animation
from extraction.extract import ExtractionError
from scene_model.animation_builder import AnimationBuildError, build_animation_cs2_document
from scene_model.skeleton_builder import SkeletonBuildError
from validation.rules import validate_animation
from .exporter import ExportResult, _write_bytes_atomically, blocking_export_result, export_boundary


def _bone_table_findable(assembly_kit_root: str, skeleton_name: str) -> bool:
    # BOB resolves the clip's AnimationType to a .bone_table out of raw_data/animations/skeletons/
    # by name, the same lookup a skeleton compile does - and fails with "Unrecognised animation type
    # or missing bone definition file" long after the export looked fine.
    folder = bone_table_folder(assembly_kit_root)
    return folder is not None and (folder / f"{skeleton_name}.bone_table").is_file()


@export_boundary(ExtractionError, SkeletonBuildError, AnimationBuildError)
def export_animation(
    armature_object: bpy.types.Object,
    action: bpy.types.Action,
    output_dir: str,
    assembly_kit_root: str,
    context: bpy.types.Context,
) -> ExportResult:
    issues = validate_animation(armature_object, action, context.scene)
    blocked = blocking_export_result(issues)
    if blocked is not None:
        return blocked

    skeleton, clip, warnings = extract_animation(
        armature_object, action, context.scene, context.evaluated_depsgraph_get()
    )
    warnings.extend(issue.message for issue in issues)

    output_path = Path(bpy.path.abspath(output_dir)) / f"{clip.name}.CS2"
    output_path.parent.mkdir(parents=True, exist_ok=True)

    document = build_animation_cs2_document(skeleton, clip, output_path=str(output_path))
    _write_bytes_atomically(output_path, write_cs2(document))

    if not _bone_table_findable(assembly_kit_root, skeleton.name):
        folder = "/".join(SKELETON_RAW_DATA_FOLDER)
        warnings.append(
            f"BOB resolves this clip's skeleton by name out of raw_data/{folder}, and there is no "
            f"{skeleton.name}.bone_table there - export the skeleton first, or BOB reports "
            "'Unrecognised animation type or missing bone definition file'."
        )

    created_rules = ensure_animation_rules(
        assembly_kit_root, output_path, [(output_path.stem, skeleton.name, clip.frame_rate)]
    )
    if created_rules is None and (output_path.parent / "rules.bob").exists():
        warnings.append(
            f"A rules.bob this add-on did not write already covers {output_path.parent} - its "
            "AnimationType and FPS are what BOB will use for this clip, not the skeleton and "
            "rate shown here."
        )

    return ExportResult(
        success=True,
        message=(
            f"Exported '{output_path.name}' ({clip.frame_count} frames at {clip.frame_rate:g} fps, "
            f"{len(clip.tracks)} animated bone(s)) to {output_path.parent}."
        ),
        warnings=warnings,
        cs2_path=output_path,
    )


__all__ = ["export_animation"]
