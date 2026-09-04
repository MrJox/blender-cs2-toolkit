import statistics
from pathlib import Path

import bpy
import mathutils

from binary.anim_reader import read_anim
from binary.cs2_reader import read_cs2
from binary.cs2_templates import SKELETON_SCENE_ROOT_ROTATION
from binary.bone_table import read_bone_table
from .anim_skeleton import is_reference_pose, skeleton_from_anim
from .skeleton_lookup import ANIM_SOURCE, SkeletonSource
from extraction.bone_space import engine_to_blender_bone, world_engine_matrices
from props.properties import BONE_TYPE_ITEMS, NO_BONE_TYPE
from scene_model.skeleton_builder import skeleton_from_cs2_document
from scene_model.skeleton_models import Skeleton

# A Blender bone with no length is deleted the moment Edit Mode is left, and a .cs2 carries no
# length at all - only a transform per node. Bones are drawn as far as their first child and get
# this much when there is none or it sits on top of them.
LEAF_BONE_LENGTH = 0.02

_BONE_TYPES = {identifier for identifier, _label, _description in BONE_TYPE_ITEMS}


def _bone_lengths(skeleton: Skeleton, matrices: list[mathutils.Matrix]) -> list[float]:
    # The median distance to this bone's children, not the first child's. File order is arbitrary:
    # bn_righthand's first child is the thumb root 2.96cm away while bn_lefthand's is a finger root
    # at 10.28cm, so the right hand came out a third the size of the left for no reason. The median
    # is what makes the two agree (10.32 vs 10.31cm) without the max's failure mode - ref_skeleton
    # has six children up to 94cm away and would be drawn as a metre-long bone through the figure.
    # A bone with one child, which is most of them, is unaffected either way.
    lengths = [LEAF_BONE_LENGTH] * len(skeleton.bones)
    child_distances: dict[int, list[float]] = {}
    for index, bone in enumerate(skeleton.bones):
        if bone.parent_index < 0:
            continue
        distance = (matrices[index].translation - matrices[bone.parent_index].translation).length
        child_distances.setdefault(bone.parent_index, []).append(distance)
    for parent_index, distances in child_distances.items():
        median = statistics.median(distances)
        if median > LEAF_BONE_LENGTH:
            lengths[parent_index] = median
    return lengths


def _apply_bone_properties(armature: bpy.types.Armature, skeleton: Skeleton, warnings: list[str]) -> None:
    armature.tw_bone_table_version = skeleton.bone_table_version
    armature.tw_reference_skeleton = skeleton.reference_skeleton
    armature.tw_cinematic = skeleton.cinematic

    unknown = set()
    for source in skeleton.bones:
        bone = armature.bones.get(source.name)
        if bone is None:
            continue
        bone_type = source.bone_type or NO_BONE_TYPE
        if bone_type not in _BONE_TYPES:
            unknown.add(bone_type)
            bone_type = "BT_CORE"
        bone.tw_bone_type = bone_type
        bone.tw_bone_sort_order = source.sort_order
        bone.tw_bone_flags = source.bone_table_flags
        bone.tw_bone_table_order = source.bone_table_order
        bone.tw_max_handle = source.max_handle
        bone.tw_is_limb = source.is_limb

    if unknown:
        warnings.append(
            f"Bone table used {len(unknown)} bone type(s) this add-on does not know "
            f"({', '.join(sorted(unknown))}) - they were imported as BT_CORE."
        )


def build_armature(skeleton: Skeleton, warnings: list[str]) -> bpy.types.Object:
    armature = bpy.data.armatures.new(skeleton.name)
    armature_object = bpy.data.objects.new(skeleton.name, armature)
    bpy.context.scene.collection.objects.link(armature_object)

    previous_active = bpy.context.view_layer.objects.active
    bpy.context.view_layer.objects.active = armature_object
    bpy.ops.object.mode_set(mode="EDIT")
    try:
        matrices = [engine_to_blender_bone(matrix) for matrix in world_engine_matrices(skeleton.bones)]
        lengths = _bone_lengths(skeleton, matrices)
        edit_bones = []
        for source, matrix, length in zip(skeleton.bones, matrices, lengths):
            edit_bone = armature.edit_bones.new(source.name)
            if edit_bone.name != source.name:
                warnings.append(f"Bone '{source.name}' had to be renamed to '{edit_bone.name}'.")
            axis, roll = bpy.types.Bone.AxisRollFromMatrix(matrix.to_3x3())
            edit_bone.head = matrix.translation
            edit_bone.tail = matrix.translation + axis * length
            edit_bone.roll = roll
            edit_bones.append(edit_bone)
        for source, edit_bone in zip(skeleton.bones, edit_bones):
            if source.parent_index >= 0:
                edit_bone.parent = edit_bones[source.parent_index]
    finally:
        bpy.ops.object.mode_set(mode="OBJECT")
        bpy.context.view_layer.objects.active = previous_active

    _apply_bone_properties(armature, skeleton, warnings)
    bpy.context.scene.collection.objects.unlink(armature_object)
    return armature_object


def _link_skeleton(
    skeleton: Skeleton, context: bpy.types.Context, warnings: list[str]
) -> tuple[bpy.types.Object, bpy.types.Collection]:
    armature_object = build_armature(skeleton, warnings)
    # The collection's name is what the skeleton exports as, the same way a Building
    # collection's is - so it takes the file's own name rather than a generic label.
    collection = bpy.data.collections.new(skeleton.name)
    collection.tw_role = "SKELETON"
    context.scene.collection.children.link(collection)
    collection.objects.link(armature_object)
    return armature_object, collection


def _skeleton_from_cs2(path: Path, document, warnings: list[str]) -> Skeleton:
    bone_table_path = path.with_suffix(".bone_table")
    bone_table = None
    if bone_table_path.exists():
        bone_table = read_bone_table(bone_table_path.read_bytes(), path.stem)
    else:
        warnings.append(
            f"No {bone_table_path.name} beside the .cs2 - every bone was imported as a helper node. "
            "Set each game bone's Bone Type before exporting."
        )

    skeleton = skeleton_from_cs2_document(document, path.stem, bone_table)
    if skeleton.scene_root_rotation != SKELETON_SCENE_ROOT_ROTATION:
        warnings.append(
            f"This skeleton's scene root rotation is {tuple(round(v, 4) for v in skeleton.scene_root_rotation)}, "
            f"not the {SKELETON_SCENE_ROOT_ROTATION} every known skeleton carries. Re-exporting it will "
            "write the usual one, which would move the root and floating bones."
        )
    if bone_table is not None:
        listed = {bone.name for bone in skeleton.bones if bone.bone_type}
        missing = sorted({entry.name for entry in bone_table.entries} - listed)
        if missing:
            warnings.append(
                f"{len(missing)} bone table entries have no node in the .cs2: {', '.join(missing[:5])}"
            )
    return skeleton


def import_skeleton(
    filepath: str, context: bpy.types.Context, document=None
) -> tuple[bpy.types.Collection, list[str]]:
    path = Path(bpy.path.abspath(filepath))
    if document is None:
        document = read_cs2(path.read_bytes())
    warnings: list[str] = []
    skeleton = _skeleton_from_cs2(path, document, warnings)
    _armature_object, collection = _link_skeleton(skeleton, context, warnings)
    return collection, warnings


def import_skeleton_source(
    source: SkeletonSource, context: bpy.types.Context
) -> tuple[bpy.types.Object, bpy.types.Collection, list[str]]:
    warnings: list[str] = []
    if source.kind == ANIM_SOURCE:
        animation = read_anim(source.path.read_bytes())
        bone_table = (
            read_bone_table(source.bone_table_path.read_bytes(), animation.skeleton_name)
            if source.bone_table_path is not None
            else None
        )
        if not is_reference_pose(animation):
            warnings.append(
                f"'{source.path.name}' is an animation clip, not a reference pose ({len(animation.frames)} "
                "frames) - its first frame is a pose rather than the rest pose, so the skeleton it "
                "produces will not match how the model was bound."
            )
        # No warning when there is no .bone_table: a compiled .anim carrying only the game bones is
        # the normal, expected shape of a game-ready skeleton, not a shortfall.
        skeleton = skeleton_from_anim(animation, animation.skeleton_name or source.path.stem, bone_table)
    else:
        skeleton = _skeleton_from_cs2(source.path, read_cs2(source.path.read_bytes()), warnings)

    armature_object, collection = _link_skeleton(skeleton, context, warnings)
    return armature_object, collection, warnings
