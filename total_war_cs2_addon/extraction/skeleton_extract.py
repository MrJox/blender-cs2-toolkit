import bpy

from props.properties import NO_BONE_TYPE
from scene_model.skeleton_models import Skeleton, SkeletonBone
from .bone_space import blender_bone_to_engine, local_translation_rotation
from .extract import ExtractionError


def find_armature(collection: bpy.types.Collection) -> bpy.types.Object | None:
    for obj in collection.all_objects:
        if obj.type == "ARMATURE":
            return obj
    return None


def _ordered_bones(armature: bpy.types.Armature) -> list[bpy.types.Bone]:
    # A .cs2 scene node can only refer to a parent that already appeared, so the flat bone list has
    # to be walked into parents-first order rather than used as Blender happens to store it.
    ordered: list[bpy.types.Bone] = []

    def walk(bone: bpy.types.Bone) -> None:
        ordered.append(bone)
        for child in bone.children:
            walk(child)

    for bone in armature.bones:
        if bone.parent is None:
            walk(bone)
    return ordered


def extract_skeleton(collection: bpy.types.Collection) -> tuple[Skeleton, list[str]]:
    armature_object = find_armature(collection)
    if armature_object is None:
        raise ExtractionError(f"'{collection.name}' holds no Armature - add one before exporting.")
    return extract_skeleton_from_armature(armature_object, collection.name)


def extract_skeleton_from_armature(
    armature_object: bpy.types.Object, name: str
) -> tuple[Skeleton, list[str]]:
    armature = armature_object.data
    if not armature.bones:
        raise ExtractionError(f"'{armature_object.name}' has no bones.")

    warnings: list[str] = []
    if any(abs(axis - 1.0) > 1e-4 for axis in armature_object.scale):
        warnings.append(
            f"'{armature_object.name}' is scaled {tuple(round(axis, 3) for axis in armature_object.scale)} - "
            "the skeleton exports at its scaled size, and the scale itself is not written to the file."
        )

    ordered = _ordered_bones(armature)
    index_by_name = {bone.name: index for index, bone in enumerate(ordered)}
    world_matrices = [blender_bone_to_engine(armature_object.matrix_world @ bone.matrix_local) for bone in ordered]

    bones = []
    next_handle = max((bone.tw_max_handle for bone in ordered), default=0) + 1
    for index, bone in enumerate(ordered):
        parent_index = index_by_name[bone.parent.name] if bone.parent is not None else -1
        translation, rotation = local_translation_rotation(
            world_matrices[index], world_matrices[parent_index] if parent_index >= 0 else None
        )
        max_handle = bone.tw_max_handle
        if max_handle == 0:
            max_handle = next_handle
            next_handle += 1
        bone_type = bone.tw_bone_type
        bones.append(
            SkeletonBone(
                name=bone.name,
                parent_index=parent_index,
                translation=translation,
                rotation=rotation,
                max_handle=max_handle,
                is_limb=bone.tw_is_limb,
                bone_type="" if bone_type == NO_BONE_TYPE else bone_type,
                sort_order=bone.tw_bone_sort_order,
                bone_table_flags=bone.tw_bone_flags,
                bone_table_order=bone.tw_bone_table_order,
            )
        )

    if not any(bone.bone_type for bone in bones):
        warnings.append(
            f"No bone in '{armature_object.name}' is listed in the bone table, so the exported "
            ".bone_table has no entries - set each game bone's Bone Type."
        )

    skeleton = Skeleton(
        name=name,
        bones=bones,
        bone_table_version=armature.tw_bone_table_version,
        reference_skeleton=armature.tw_reference_skeleton,
        cinematic=armature.tw_cinematic,
    )
    return skeleton, warnings
