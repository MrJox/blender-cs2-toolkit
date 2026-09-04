from contextlib import contextmanager

import bpy
import mathutils

from scene_model.animation_models import AnimationClip
from scene_model.models import AnimationKeyframes
from scene_model.skeleton_models import Skeleton
from .bone_space import blender_bone_to_engine, local_translation_rotation
from .extract import ExtractionError
from .skeleton_extract import extract_skeleton_from_armature
from .unit_extract import skeleton_name_for

TRANSLATION_TOLERANCE = 1e-5
ROTATION_TOLERANCE = 1e-5


@contextmanager
def _posed(armature_object: bpy.types.Object):
    # Rest position makes every pose bone evaluate to its rest matrix, so sampling a clip through it
    # would write out a skeleton standing still. The inverse of unit_extract._rest_pose, which forces
    # the other way for the same reason.
    was_rest = armature_object.data.pose_position == "REST"
    if was_rest:
        armature_object.data.pose_position = "POSE"
    try:
        yield
    finally:
        if was_rest:
            armature_object.data.pose_position = "REST"


@contextmanager
def _assigned(armature_object: bpy.types.Object, action: bpy.types.Action):
    # The pose is read back through the depsgraph, so what gets sampled is whatever clip the Armature
    # currently holds - not the one passed in. A batch export walks several clips of one skeleton, so
    # each has to be assigned while it is sampled and the artist's own choice put back afterwards.
    # Every basis is cleared on the way in and out because a clip keys only the bones it animates,
    # and the previous one's pose would otherwise bake into the rest of them (the measurement behind
    # that is in importer.anim_importer.rest_pose).
    animation_data = armature_object.animation_data_create()
    previous = animation_data.action
    if previous is action:
        yield
        return
    _clear_pose(armature_object)
    animation_data.action = action
    try:
        yield
    finally:
        _clear_pose(armature_object)
        animation_data.action = previous


def _clear_pose(armature_object: bpy.types.Object) -> None:
    for pose_bone in armature_object.pose.bones:
        pose_bone.matrix_basis = mathutils.Matrix()


def action_frame_range(action: bpy.types.Action, scene: bpy.types.Scene) -> tuple[int, int]:
    start, end = action.frame_range
    if end <= start:
        return scene.frame_start, scene.frame_end
    return round(start), round(end)


def clip_frame_rate(action: bpy.types.Action, scene: bpy.types.Scene) -> float:
    return action.tw_frame_rate or scene.render.fps / scene.render.fps_base


def _continuous(rotation: tuple[float, float, float, float], previous) -> tuple[float, float, float, float]:
    # BOB resamples the authored track, so two neighbouring keys holding q and -q - the same
    # rotation, written differently - would interpolate the long way round between them. Keep every
    # key on the same side of the hypersphere as the one before it.
    if previous is None:
        return rotation
    if sum(a * b for a, b in zip(rotation, previous)) < 0.0:
        return tuple(-component for component in rotation)
    return rotation


def _reduce(times: list[float], values: list, tolerance: float) -> tuple[list[float], list]:
    first = values[0]
    if all(max(abs(a - b) for a, b in zip(value, first)) <= tolerance for value in values):
        return [times[0]], [first]
    return times, values


def sample_clip(
    armature_object: bpy.types.Object,
    skeleton: Skeleton,
    action: bpy.types.Action,
    scene: bpy.types.Scene,
    depsgraph: bpy.types.Depsgraph,
) -> AnimationClip:
    start, end = action_frame_range(action, scene)
    frame_rate = clip_frame_rate(action, scene)
    frames = list(range(start, end + 1))

    translations: dict[str, list] = {bone.name: [] for bone in skeleton.bones}
    rotations: dict[str, list] = {bone.name: [] for bone in skeleton.bones}

    original_frame = scene.frame_current
    try:
        with _posed(armature_object), _assigned(armature_object, action):
            for frame in frames:
                scene.frame_set(frame)
                evaluated = armature_object.evaluated_get(depsgraph)
                world: list[mathutils.Matrix] = []
                for index, bone in enumerate(skeleton.bones):
                    pose_bone = evaluated.pose.bones.get(bone.name)
                    if pose_bone is None:
                        raise ExtractionError(f"'{armature_object.name}' has no pose bone '{bone.name}'.")
                    world.append(blender_bone_to_engine(evaluated.matrix_world @ pose_bone.matrix))
                    parent = world[bone.parent_index] if bone.parent_index >= 0 else None
                    translation, rotation = local_translation_rotation(world[index], parent)
                    translations[bone.name].append(translation)
                    previous = rotations[bone.name][-1] if rotations[bone.name] else None
                    rotations[bone.name].append(_continuous(rotation, previous))
    finally:
        scene.frame_set(original_frame)

    times = [(frame - start) / frame_rate for frame in frames]
    tracks: dict[str, AnimationKeyframes] = {}
    for bone in skeleton.bones:
        translation_times, bone_translations = _reduce(times, translations[bone.name], TRANSLATION_TOLERANCE)
        rotation_times, bone_rotations = _reduce(times, rotations[bone.name], ROTATION_TOLERANCE)
        static = len(translation_times) == 1 and len(rotation_times) == 1
        # A bone that neither moves nor sits away from its rest transform needs no track at all -
        # the document builder writes its rest key, which is what a real clip's static nodes carry.
        if static and matches_rest(bone, bone_translations[0], bone_rotations[0]):
            continue
        tracks[bone.name] = AnimationKeyframes(
            translation_times=translation_times,
            translations=bone_translations,
            rotation_times=rotation_times,
            rotations=bone_rotations,
        )

    return AnimationClip(
        name=action.name,
        skeleton_name=skeleton.name,
        frame_rate=frame_rate,
        frame_count=len(frames),
        tracks=tracks,
    )


def matches_rest(bone, translation, rotation) -> bool:
    if max(abs(a - b) for a, b in zip(translation, bone.translation)) > TRANSLATION_TOLERANCE:
        return False
    same = max(abs(a - b) for a, b in zip(rotation, bone.rotation))
    flipped = max(abs(a + b) for a, b in zip(rotation, bone.rotation))
    return min(same, flipped) <= ROTATION_TOLERANCE


def extract_animation(
    armature_object: bpy.types.Object,
    action: bpy.types.Action,
    scene: bpy.types.Scene,
    depsgraph: bpy.types.Depsgraph,
) -> tuple[Skeleton, AnimationClip, list[str]]:
    if armature_object is None or armature_object.type != "ARMATURE":
        raise ExtractionError("A clip exports against an Armature - none is bound.")
    skeleton, warnings = extract_skeleton_from_armature(armature_object, skeleton_name_for(armature_object))
    clip = sample_clip(armature_object, skeleton, action, scene, depsgraph)
    return skeleton, clip, warnings


__all__ = ["extract_animation", "sample_clip", "action_frame_range", "clip_frame_rate", "matches_rest"]
