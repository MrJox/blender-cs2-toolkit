import re
from contextlib import contextmanager

import bpy

from props.properties import LOD_INDEX_BY_IDENTIFIER
from scene_model.unit_models import (
    MAX_BONE_INFLUENCES,
    AttachmentPoint,
    UnitLod,
    UnitMeshPart,
    UnitPart,
    WEIGHTED_KIND,
)
from .bone_space import blender_bone_to_engine, blender_object_to_engine, local_translation_rotation
from .extract import ExtractionError, _convert_mesh_indexed, _read_object_materials, _uv2_layer_name
from .skeleton_extract import extract_skeleton_from_armature


def unit_model_collections(unit_collection: bpy.types.Collection) -> list[bpy.types.Collection]:
    # A unit asset holds its models directly. Nested, not just direct children, because a
    # .variantmeshdefinition import groups what it brings in under one collection per slot.
    models: list[bpy.types.Collection] = []
    for child in unit_collection.children:
        if child.tw_role == "UNIT_MESH":
            models.append(child)
        elif child.tw_role != "UNIT":
            models.extend(unit_model_collections(child))
    return models


def armature_of(obj: bpy.types.Object) -> bpy.types.Object | None:
    for modifier in obj.modifiers:
        if modifier.type == "ARMATURE" and modifier.object is not None:
            return modifier.object
    return None


def attachment_point_objects(collection: bpy.types.Collection) -> list[bpy.types.Object]:
    return [obj for obj in collection.all_objects if obj.tw_attachment_point_name]


def mesh_objects(collection: bpy.types.Collection) -> list[bpy.types.Object]:
    return [obj for obj in collection.objects if obj.type == "MESH"]


# Blender collection names are globally unique, so a model named after the same thing as its asset -
# a single-model file, which is most of them - comes back as "<name>.001". That suffix is Blender's,
# not the artist's, and the model name becomes MeshHeaderV5.name in the compiled file, so it is
# dropped on the way out. The asset's own name is never touched this way: it is the filename, and
# TW_OT_new_unit warns rather than silently renaming when Blender uniquifies it.
_BLENDER_SUFFIX = re.compile(r"^(?P<name>.+)\.\d{3}$")


def _model_export_name(name: str) -> str:
    match = _BLENDER_SUFFIX.match(name)
    return match.group("name") if match else name


def unit_kind(unit_collection: bpy.types.Collection) -> str:
    # Every model in one asset has to agree - validation blocks a mixture - so the first one speaks
    # for the file.
    models = unit_model_collections(unit_collection)
    return models[0].tw_unit_part_kind if models else WEIGHTED_KIND


def armature_for_models(models: list[bpy.types.Collection]) -> bpy.types.Object | None:
    for model in models:
        for obj in mesh_objects(model):
            armature_object = armature_of(obj)
            if armature_object is not None:
                return armature_object
    return None


def find_unit_armature(unit_collection: bpy.types.Collection) -> bpy.types.Object | None:
    return armature_for_models(unit_model_collections(unit_collection))


def skeleton_name_for(armature_object: bpy.types.Object) -> str:
    # A skeleton exports as <its collection name>.CS2 + .bone_table and BOB resolves it by that name
    # through the rules.bob AnimationType, so the name a weighted asset has to quote is the
    # collection's, not the Armature object's - Blender uniquifies those independently (Phase 4).
    for collection in armature_object.users_collection:
        if collection.tw_role == "SKELETON":
            return collection.name
    return armature_object.name


@contextmanager
def _rest_pose(armature_objects: list[bpy.types.Object], view_layer: bpy.types.ViewLayer | None):
    # A weighted model is authored in the skeleton's rest pose and exports at it: reading the mesh
    # through the depsgraph while the armature is posed would bake that pose into the file. Rest
    # position makes the Armature modifier a no-op, so the same evaluated read gives the undeformed
    # mesh without having to special-case the modifier stack.
    posed = [obj for obj in armature_objects if obj.data.pose_position != "REST"]
    for obj in posed:
        obj.data.pose_position = "REST"
    if posed and view_layer is not None:
        view_layer.update()
    try:
        yield
    finally:
        for obj in posed:
            obj.data.pose_position = "POSE"
        if posed and view_layer is not None:
            view_layer.update()


def _vertex_weights(
    obj: bpy.types.Object,
    source_indices: list[int],
    bone_names: set[str],
    warnings: list[str],
) -> list[list[tuple[str, float]]]:
    group_names = {group.index: group.name for group in obj.vertex_groups}
    reduced = 0
    per_source: dict[int, list[tuple[str, float]]] = {}
    for vertex in obj.data.vertices:
        influences = [
            (group_names[element.group], element.weight)
            for element in vertex.groups
            if group_names.get(element.group) in bone_names and element.weight > 0.0
        ]
        influences.sort(key=lambda entry: entry[1], reverse=True)
        if len(influences) > MAX_BONE_INFLUENCES:
            reduced += 1
            influences = influences[:MAX_BONE_INFLUENCES]
        if not influences:
            raise ExtractionError(
                f"'{obj.name}' has vertices weighted to no bone at all - every vertex of a weighted "
                "model needs at least one bone weight."
            )
        total = sum(weight for _name, weight in influences)
        per_source[vertex.index] = [(name, weight / total) for name, weight in influences]

    if reduced:
        warnings.append(
            f"'{obj.name}' had {reduced} vertex(es) weighted to more than {MAX_BONE_INFLUENCES} bones; "
            f"the {MAX_BONE_INFLUENCES} strongest were kept and renormalised, which is what every real "
            "unit model carries."
        )
    return [per_source[index] for index in source_indices]


def _extract_lod(
    obj: bpy.types.Object,
    depsgraph: bpy.types.Depsgraph,
    weighted: bool,
    bone_names: set[str],
    warnings: list[str],
) -> UnitLod:
    materials = _read_object_materials(obj)
    if not materials:
        raise ExtractionError(f"'{obj.name}' has no material assigned.")
    mesh, source_indices = _convert_mesh_indexed(obj, depsgraph, uv2_layer_name=_uv2_layer_name(materials))
    weights = _vertex_weights(obj, source_indices, bone_names, warnings) if weighted else []
    return UnitLod(
        lod_index=LOD_INDEX_BY_IDENTIFIER[obj.tw_lod_index],
        mesh=mesh,
        materials=materials,
        weights=weights,
    )


def _extract_attachment_points(
    unit_collection: bpy.types.Collection,
    armature_object: bpy.types.Object | None,
    bone_names: set[str],
    warnings: list[str],
) -> list[AttachmentPoint]:
    points: list[AttachmentPoint] = []
    for obj in attachment_point_objects(unit_collection):
        if obj.parent is not armature_object or obj.parent_type != "BONE" or obj.parent_bone not in bone_names:
            warnings.append(
                f"Attachment point '{obj.name}' is not parented to a bone of the asset's skeleton and was "
                "skipped - parent it to the bone it hangs off (Ctrl+P > Bone) so the game knows where it goes."
            )
            continue
        bone = armature_object.data.bones[obj.parent_bone]
        bone_world = blender_bone_to_engine(armature_object.matrix_world @ bone.matrix_local)
        translation, rotation = local_translation_rotation(
            blender_object_to_engine(obj.matrix_world), bone_world
        )
        points.append(
            AttachmentPoint(
                name=obj.tw_attachment_point_name,
                bone_name=obj.parent_bone,
                translation=translation,
                rotation=rotation,
            )
        )
    return points


def extract_unit(
    unit_collection: bpy.types.Collection,
    depsgraph: bpy.types.Depsgraph,
    view_layer: bpy.types.ViewLayer | None = None,
) -> tuple[UnitPart, list[str]]:
    warnings: list[str] = []
    model_collections = unit_model_collections(unit_collection)
    if not model_collections:
        raise ExtractionError(f"'{unit_collection.name}' has no models yet.")

    kind = model_collections[0].tw_unit_part_kind
    weighted = kind == WEIGHTED_KIND
    armature_object = armature_for_models(model_collections) if weighted else None
    skeleton = None
    bone_names: set[str] = set()
    if weighted:
        if armature_object is None:
            raise ExtractionError(
                f"'{unit_collection.name}' is a Weighted Model asset but none of its models has an "
                "Armature modifier - bind them to the skeleton first."
            )
        skeleton, skeleton_warnings = extract_skeleton_from_armature(
            armature_object, skeleton_name_for(armature_object)
        )
        warnings.extend(skeleton_warnings)
        bone_names = {bone.name for bone in skeleton.bones}

    with _rest_pose([armature_object] if armature_object is not None else [], view_layer):
        meshes: list[UnitMeshPart] = []
        for model in model_collections:
            lod_objects = mesh_objects(model)
            if not lod_objects:
                warnings.append(f"'{model.name}' holds no meshes and was skipped.")
                continue
            lods = [_extract_lod(obj, depsgraph, weighted, bone_names, warnings) for obj in lod_objects]
            seen: dict[int, str] = {}
            for lod, obj in zip(lods, lod_objects):
                if lod.lod_index in seen:
                    warnings.append(
                        f"'{model.name}' has two meshes at LOD {lod.lod_index} "
                        f"('{seen[lod.lod_index]}' and '{obj.name}') - they export as two nodes with the same name."
                    )
                seen[lod.lod_index] = obj.name
            meshes.append(UnitMeshPart(name=_model_export_name(model.name), lods=lods))

        attachment_points = (
            _extract_attachment_points(unit_collection, armature_object, bone_names, warnings)
            if weighted
            else []
        )

    if not weighted and attachment_point_objects(unit_collection):
        warnings.append(
            f"'{unit_collection.name}' is a Rigid Model asset, so its attachment point objects were not "
            "exported - attachment points live on the weighted asset the item hangs off, not on the item itself."
        )

    if not meshes:
        raise ExtractionError(f"'{unit_collection.name}' has no meshes to export.")

    return (
        UnitPart(
            name=unit_collection.name,
            kind=kind,
            meshes=meshes,
            skeleton=skeleton,
            attachment_points=attachment_points,
        ),
        warnings,
    )
