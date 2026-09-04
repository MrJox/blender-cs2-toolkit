import functools
import os
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

import bpy

from validation.rules import validate_building, has_blocking_issues
from extraction.extract import extract_building, ExtractionError
from scene_model.cs2_builder import build_cs2_document
from binary.cs2_writer import write_cs2
from bob.handoff import build_handoff_message
from bob.rules import ensure_building_rules


def _write_bytes_atomically(output_path: Path, data: bytes) -> None:
    # A half-written .CS2 is worse than no .CS2 at all: BOB reads whatever is on disk, and the file
    # being overwritten is usually the artist's last working export. Writing beside it and renaming
    # means a crash or a full disk leaves the previous file untouched.
    temporary_path = output_path.with_name(output_path.name + ".partial")
    try:
        temporary_path.write_bytes(data)
        os.replace(temporary_path, output_path)
    except OSError:
        temporary_path.unlink(missing_ok=True)
        raise


@dataclass
class ExportResult:
    success: bool
    message: str
    warnings: list[str]
    cs2_path: Path | None


def blocking_export_result(issues: list) -> ExportResult | None:
    if not has_blocking_issues(issues):
        return None
    blocking = [issue.message for issue in issues if issue.severity == "ERROR"]
    return ExportResult(
        success=False,
        message="Cannot export - please fix the following first:\n" + "\n".join(f"- {m}" for m in blocking),
        warnings=[],
        cs2_path=None,
    )


def export_boundary(*expected: type[BaseException]):
    # Every exporter owes the artist the same two answers: a domain error is a message they can act
    # on, and anything else is a bug that still has to come back as a failed export rather than a
    # traceback in Blender's console. See the plan section on error handling.
    def decorate(export):
        @functools.wraps(export)
        def guarded(*args, **kwargs) -> ExportResult:
            try:
                return export(*args, **kwargs)
            except expected as error:
                return ExportResult(success=False, message=str(error), warnings=[], cs2_path=None)
            except Exception as error:  # noqa: BLE001
                return ExportResult(
                    success=False,
                    message=f"Unexpected error during export: {error}",
                    warnings=[],
                    cs2_path=None,
                )

        return guarded

    return decorate


def _collection_tree(collection: bpy.types.Collection) -> list[bpy.types.Collection]:
    tree = [collection]
    for child in collection.children:
        tree.extend(_collection_tree(child))
    return tree


def _layer_collections_for(
    view_layer: bpy.types.ViewLayer, collections: list[bpy.types.Collection]
) -> list[bpy.types.LayerCollection]:
    found: list[bpy.types.LayerCollection] = []

    def walk(layer_collection: bpy.types.LayerCollection) -> None:
        if layer_collection.collection in collections:
            found.append(layer_collection)
        for child in layer_collection.children:
            walk(child)

    walk(view_layer.layer_collection)
    return found


@contextmanager
def _evaluated_transforms(building_collection: bpy.types.Collection, view_layer: bpy.types.ViewLayer):
    # matrix_world is a depsgraph-evaluated cache, so anything the view layer stops evaluating keeps
    # the transform it had at that moment - a marker moved afterwards (its Object Properties
    # transform stays editable from the Outliner) would export the position it had before the move.
    # Confirmed to affect Object.hide_viewport, Collection.hide_viewport and LayerCollection.exclude;
    # the eye icons (LayerCollection.hide_viewport, Object.hide_set) keep the object in the depsgraph
    # and are already correct.
    collections = _collection_tree(building_collection)
    hidden_objects = [obj for collection in collections for obj in collection.objects if obj.hide_viewport]
    hidden_collections = [collection for collection in collections if collection.hide_viewport]
    excluded = [lc for lc in _layer_collections_for(view_layer, collections) if lc.exclude]

    for obj in hidden_objects:
        obj.hide_viewport = False
    for collection in hidden_collections:
        collection.hide_viewport = False
    for layer_collection in excluded:
        layer_collection.exclude = False
    view_layer.update()
    try:
        yield
    finally:
        for layer_collection in excluded:
            layer_collection.exclude = True
        for collection in hidden_collections:
            collection.hide_viewport = True
        for obj in hidden_objects:
            obj.hide_viewport = True


@export_boundary(ExtractionError)
def export_building(
    building_collection: bpy.types.Collection,
    output_dir: str,
    assembly_kit_root: str,
    context: bpy.types.Context,
) -> ExportResult:
    with _evaluated_transforms(building_collection, context.view_layer):
        blocked = blocking_export_result(validate_building(building_collection))
        if blocked is not None:
            return blocked

        depsgraph = context.evaluated_depsgraph_get()
        building, warnings = extract_building(building_collection, depsgraph, context.scene)

        output_path = Path(bpy.path.abspath(output_dir)) / f"{building.name}.CS2"
        output_path.parent.mkdir(parents=True, exist_ok=True)

        document = build_cs2_document(building, assembly_kit_root, output_path=str(output_path))
        data = write_cs2(document)
        _write_bytes_atomically(output_path, data)

        created_rules = ensure_building_rules(assembly_kit_root, output_path)
        if created_rules is not None:
            warnings.append(
                f"BOB needs a rules.bob beside a building to process it, and this folder had "
                f"none - created {created_rules}"
            )

        return ExportResult(
            success=True,
            message=build_handoff_message(output_path),
            warnings=warnings,
            cs2_path=output_path,
        )
