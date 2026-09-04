import math

import mathutils

from binary import anim_structures as a
from binary.anim_reader import bone_local_transform
from binary.bone_table import DEFAULT_BONE_TYPE, ROOT_BONE_TYPE, BoneTable
from extraction.bone_space import local_engine_matrix, local_translation_rotation
from scene_model.skeleton_models import Skeleton, SkeletonBone

# A compiled .anim is in the space BOB produces, which is the skeleton's own authoring space turned
# a half turn about Y - measured by compiling CA's rome_man_game.cs2 and comparing the two rest
# poses bone by bone: 145.5 cm worst offset as stored, 0.009 cm after this turn. Undoing it here
# means Blender holds one space whether a skeleton arrived as a .cs2 or as a .anim.
ENGINE_HALF_TURN = mathutils.Matrix.Rotation(math.pi, 4, "Y")


def skeleton_from_anim(animation: a.Animation, name: str, bone_table: BoneTable | None = None) -> Skeleton:
    if not animation.bones:
        raise ValueError(f"'{name}' carries no bones.")
    if not animation.frames:
        raise ValueError(f"'{name}' carries no frames, so it has no rest pose.")

    entries = (
        {entry.name: (order, entry) for order, entry in enumerate(bone_table.entries, start=1)}
        if bone_table
        else {}
    )

    bones: list[SkeletonBone] = []
    for index, source in enumerate(animation.bones):
        translation, rotation = bone_local_transform(animation, index, 0)
        local = local_engine_matrix(translation, rotation)
        if source.parent_id < 0:
            # Pre-multiplying the root's local transform applies the turn globally: every
            # descendant's world transform is composed onto its root's.
            local = ENGINE_HALF_TURN @ local
        translation, rotation = local_translation_rotation(local, None)

        order, entry = entries.get(source.name, (0, None))
        if entry is not None:
            bone_type, sort_order, flags = entry.bone_type, entry.sort_order, entry.flags
        else:
            # Every bone a compiled .anim lists is a game bone by definition - that list is the
            # bone table collapsed to the bones the engine indexes. Which of BT_FACE/BT_FLOATING/
            # BT_LEFT_HAND a given one was is not recoverable from the .anim, so they all come in
            # as plain core bones unless a real .bone_table turns up beside it.
            bone_type = ROOT_BONE_TYPE if index == 0 else DEFAULT_BONE_TYPE
            sort_order = 0 if index == 0 else 1
            flags = ""

        bones.append(
            SkeletonBone(
                name=source.name,
                parent_index=source.parent_id,
                translation=translation,
                rotation=rotation,
                bone_type=bone_type,
                sort_order=sort_order,
                bone_table_flags=flags,
                bone_table_order=order,
            )
        )

    return Skeleton(
        name=name,
        bones=bones,
        bone_table_version=bone_table.version if bone_table else 1,
        reference_skeleton=bone_table.reference_skeleton if bone_table else True,
        cinematic=bone_table.cinematic if bone_table else False,
    )


def is_reference_pose(animation: a.Animation) -> bool:
    # BOB writes a skeleton compiled with ExportAsReferencePose as two frames; a real clip has
    # dozens (47-95 across the samples here), and its frame 0 is a pose rather than the rest pose.
    return len(animation.frames) <= 2


__all__ = ["skeleton_from_anim", "is_reference_pose", "ENGINE_HALF_TURN"]
