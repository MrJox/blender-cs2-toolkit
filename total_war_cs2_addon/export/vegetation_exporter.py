from pathlib import Path

import bpy

from binary.cs2_writer import write_cs2
from bob.rules import (
    GLOSS_MAP_SUFFIX,
    compiled_gloss_map_name,
    ensure_vegetation_rules,
    inside_raw_data,
    vegetation_rules_written_by_addon,
)
from extraction.extract import ExtractionError
from extraction.vegetation_extract import extract_vegetation
from scene_model.vegetation_builder import VegetationBuildError, build_vegetation_cs2_document
from validation.rules import has_blocking_issues, validate_vegetation
from .exporter import ExportResult, _evaluated_transforms, _write_bytes_atomically, blocking_export_result, export_boundary


def _gloss_naming_warnings(model) -> list[str]:
    # An imported tree's gloss slot points at the compiled name BOB already built once, so exporting
    # it as-is sends that name through BOB's rule a second time. Worth saying before the artist finds
    # a texture the game cannot load.
    renamed = sorted(
        {
            f"{Path(material.gloss_texture_path).stem} -> {compiled_gloss_map_name(Path(material.gloss_texture_path).stem)}"
            for lod in model.lods
            for material in lod.materials
            if material.gloss_texture_path
            and Path(material.gloss_texture_path).stem.endswith(GLOSS_MAP_SUFFIX)
        }
    )
    if not renamed:
        return []
    return [
        "BOB names a tree's gloss map after its source, and these already carry the name it gives "
        f"them, so it will build {', '.join(renamed)}. Point the Gloss slot at the authored texture "
        "(the one without the '_map') to get the name the game expects."
    ]


def _rules_warnings(assembly_kit_root: str, output_path: Path, created_rules: Path | None) -> list[str]:
    if created_rules is not None:
        return [
            f"BOB needs a rules.bob beside a tree to know it is one - wrote {created_rules}"
        ]
    if vegetation_rules_written_by_addon(output_path):
        return []
    if inside_raw_data(assembly_kit_root, output_path):
        return [
            f"A rules.bob already covers {output_path.parent} and this add-on did not write it, so its "
            "own keys are what BOB will build against - check it says 'AnimationType = tree' and "
            "'CreateRigidModelDescriptionFile = true', or the model compiles without its skeleton or "
            "without its burn hull."
        ]
    return []


@export_boundary(ExtractionError, VegetationBuildError)
def export_vegetation(
    model_collection: bpy.types.Collection,
    output_dir: str,
    assembly_kit_root: str,
    context: bpy.types.Context,
) -> ExportResult:
    with _evaluated_transforms(model_collection, context.view_layer):
        blocked = blocking_export_result(validate_vegetation(model_collection))
        if blocked is not None:
            return blocked

        model, warnings = extract_vegetation(model_collection, context.evaluated_depsgraph_get())

        output_path = Path(bpy.path.abspath(output_dir)) / f"{model.name}.CS2"
        output_path.parent.mkdir(parents=True, exist_ok=True)

        document = build_vegetation_cs2_document(model, assembly_kit_root, output_path=str(output_path))
        _write_bytes_atomically(output_path, write_cs2(document))

        warnings.extend(_gloss_naming_warnings(model))
        warnings.extend(_rules_warnings(assembly_kit_root, output_path, ensure_vegetation_rules(assembly_kit_root, output_path)))

        return ExportResult(
            success=True,
            message=f"Exported '{output_path.name}' to {output_path.parent}.",
            warnings=warnings,
            cs2_path=output_path,
        )


__all__ = ["export_vegetation"]
