from dataclasses import dataclass
from pathlib import Path

import bpy

from binary.cs2_writer import write_cs2
from bob.rules import (
    ensure_unit_rules,
    inside_raw_data,
    unit_rule_in_scope,
    unit_rules_written_by_addon,
)
from extraction.extract import ExtractionError
from extraction.unit_extract import extract_unit
from scene_model.unit_builder import UnitBuildError, build_unit_cs2_document
from validation.rules import has_blocking_issues, validate_unit
from .exporter import ExportResult, _evaluated_transforms, _write_bytes_atomically


@dataclass
class UnitExportResult:
    success: bool
    message: str
    warnings: list[str]
    parts: list[ExportResult]

    @property
    def cs2_paths(self) -> list[Path]:
        return [part.cs2_path for part in self.parts if part.cs2_path is not None]

    # ui.operators.BobWaitMixin names the file it is waiting on; a batch is named after its first
    # part, the same one bob.cli reports the run against.
    @property
    def cs2_path(self) -> Path | None:
        paths = self.cs2_paths
        return paths[0] if paths else None


def _animation_type(part) -> str:
    # PLAN_units.md 1.8: BOB stamps rules.bob's AnimationType into the compiled m_bone_table_name.
    # A rigid weapon, shield or prop gets the empty string, exactly as CA's own shield and crest
    # rules.bob files do.
    return part.skeleton.name if part.is_weighted and part.skeleton is not None else ""


def _rules_warnings(
    assembly_kit_root: str, output_path: Path, animation_type: str, created_rules: Path | None
) -> list[str]:
    if created_rules is not None:
        return [
            f"BOB needs a rules.bob beside a unit asset to know which skeleton it belongs to - "
            f"wrote {created_rules}"
        ]
    if unit_rules_written_by_addon(output_path):
        return []
    if unit_rule_in_scope(assembly_kit_root, output_path):
        return [
            "A rules.bob covering this folder already exists and this add-on did not write it, so its "
            f"AnimationType is what BOB will stamp into the compiled file - check it names "
            f"'{animation_type or '(none)'}', or the asset compiles against the wrong skeleton."
        ]
    if inside_raw_data(assembly_kit_root, output_path):
        return [
            f"A rules.bob already sits in {output_path.parent} but declares no [RigidModelV2] section, "
            "so it was left alone - BOB will not compile this asset until one is added."
        ]
    return []


def export_unit(
    unit_collection: bpy.types.Collection,
    output_dir: str,
    assembly_kit_root: str,
    context: bpy.types.Context,
) -> UnitExportResult:
    issues = validate_unit(unit_collection)
    if has_blocking_issues(issues):
        blocking = [issue.message for issue in issues if issue.severity == "ERROR"]
        return UnitExportResult(
            success=False,
            message=f"Cannot export '{unit_collection.name}':\n"
            + "\n".join(f"- {message}" for message in blocking),
            warnings=[],
            parts=[],
        )

    try:
        resolved_dir = Path(bpy.path.abspath(output_dir))
        resolved_dir.mkdir(parents=True, exist_ok=True)

        with _evaluated_transforms(unit_collection, context.view_layer):
            part, warnings = extract_unit(
                unit_collection, context.evaluated_depsgraph_get(), context.view_layer
            )
        output_path = resolved_dir / f"{part.name}.CS2"
        document = build_unit_cs2_document(part, assembly_kit_root, output_path=str(output_path))
        _write_bytes_atomically(output_path, write_cs2(document))

        animation_type = _animation_type(part)
        created_rules = ensure_unit_rules(
            assembly_kit_root, output_path, [(output_path.stem, animation_type)]
        )
        warnings.extend(_rules_warnings(assembly_kit_root, output_path, animation_type, created_rules))
    except (ExtractionError, UnitBuildError) as error:
        return UnitExportResult(success=False, message=str(error), warnings=[], parts=[])
    # Not exporter.export_boundary: a unit batch answers with UnitExportResult, and its message
    # names the asset that failed because several are reported together.
    except Exception as error:  # noqa: BLE001
        return UnitExportResult(
            success=False,
            message=f"Unexpected error exporting '{unit_collection.name}': {error}",
            warnings=[],
            parts=[],
        )

    result = ExportResult(
        success=True,
        message=f"Exported '{output_path.name}' to {output_path.parent}.",
        warnings=warnings,
        cs2_path=output_path,
    )
    return UnitExportResult(success=True, message=result.message, warnings=warnings, parts=[result])
