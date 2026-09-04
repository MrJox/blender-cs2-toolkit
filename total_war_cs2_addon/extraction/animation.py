from typing import Callable

import bpy
import mathutils

from scene_model.models import AnimationKeyframes, Vec3, Vec4

# The real ground-truth sample's per-frame time deltas (0.03336670... s) are 1/29.97, the classic
# NTSC 30000/1001 broadcast rate - not a round 30fps. Used both ways: seconds -> Blender frame
# number on import, Blender frame number -> seconds on export, so a round trip lands on the same
# frame it started from.
ANIM_FRAME_RATE = 30000.0 / 1001.0

SpaceConverter = Callable[[Vec3], Vec3]
RotationConverter = Callable[[mathutils.Quaternion], Vec4] | Callable[[Vec4], mathutils.Quaternion]


def _object_fcurves(obj: bpy.types.Object) -> list[bpy.types.FCurve]:
    # Blender 4.4+ actions are "layered" (layers -> strips -> per-datablock channelbags) instead of
    # exposing a flat Action.fcurves list directly - Action.fcurves only still exists on an
    # old-style "legacy" action (Action.is_action_legacy), which a fresh 5.x file never has. Scoped
    # to this object's own action_slot so a shared/linked Action doesn't pull in another
    # datablock's channels.
    action_data = obj.animation_data
    if action_data is None or action_data.action is None:
        return []
    action = action_data.action
    if hasattr(action, "fcurves"):
        return list(action.fcurves)
    slot = getattr(action_data, "action_slot", None)
    if slot is None:
        return []
    fcurves: list[bpy.types.FCurve] = []
    for layer in action.layers:
        for strip in layer.strips:
            if strip.type != "KEYFRAME":
                continue
            channelbag = strip.channelbag(slot)
            if channelbag is not None:
                fcurves.extend(channelbag.fcurves)
    return fcurves


def object_keyframe_frames(obj: bpy.types.Object) -> list[int]:
    # Distinct whole Blender frame numbers this object has a location/rotation keyframe on, sorted
    # ascending. Empty if the object has no keyframed animation at all - a legitimate, common state
    # (real ground truth has both animated and static instances of the same node kind).
    frames: set[int] = set()
    for fcurve in _object_fcurves(obj):
        if fcurve.data_path not in ("location", "rotation_euler", "rotation_quaternion"):
            continue
        for keyframe in fcurve.keyframe_points:
            frames.add(round(keyframe.co.x))
    return sorted(frames)


def has_keyframed_animation(obj: bpy.types.Object) -> bool:
    return len(object_keyframe_frames(obj)) > 0


def sample_object_animation(
    obj: bpy.types.Object,
    depsgraph: bpy.types.Depsgraph,
    scene: bpy.types.Scene,
    to_engine_space: SpaceConverter,
    to_engine_rotation: Callable[[mathutils.Quaternion], Vec4],
) -> AnimationKeyframes:
    # Scrubs the scene to each of the object's own keyframed frames (or just samples its current
    # pose once, if it has none) and reads matrix_world at each one, producing independent
    # engine-space (time, translation)/(time, rotation) tracks - the authoring-side half of the
    # SceneNode.AnimData mechanism cs2_builder._scene_node_for already writes for every node, just
    # with real keyframes instead of always exactly one. to_engine_space/to_engine_rotation are
    # passed in (extraction.extract's, today) rather than imported, so this scrubbing logic stays
    # reusable by a future skeletal per-bone sampler without hardcoding this caller's axis
    # convention. Always restores the scene's original frame before returning, including on error.
    frames = object_keyframe_frames(obj)
    original_frame = scene.frame_current
    try:
        sample_frames = frames if frames else [original_frame]
        translations: list[Vec3] = []
        rotations: list[Vec4] = []
        for frame in sample_frames:
            scene.frame_set(frame)
            obj_eval = obj.evaluated_get(depsgraph)
            translation, rotation, _scale = obj_eval.matrix_world.decompose()
            translations.append(to_engine_space(tuple(translation)))
            rotations.append(to_engine_rotation(rotation))
    finally:
        scene.frame_set(original_frame)

    times = [frame / ANIM_FRAME_RATE for frame in sample_frames]
    return AnimationKeyframes(
        translation_times=list(times),
        translations=translations,
        rotation_times=list(times),
        rotations=rotations,
    )


def bake_keyframes_onto_object(
    obj: bpy.types.Object,
    keyframes: AnimationKeyframes,
    scene: bpy.types.Scene,
    to_blender_space: SpaceConverter,
    to_blender_rotation: Callable[[Vec4], mathutils.Quaternion],
) -> None:
    # The import-side inverse of sample_object_animation. Translation and rotation are keyed
    # independently (a real gate_opening_anim has 1 translation key but 115 rotation keys), so each
    # track only gets a keyframe at the times it actually has data for, rather than forcing both
    # tracks onto a merged time set.
    obj.rotation_mode = "QUATERNION"
    frame_times = sorted(set(keyframes.translation_times) | set(keyframes.rotation_times))
    if len(frame_times) <= 1:
        if keyframes.translations:
            obj.location = to_blender_space(keyframes.translations[0])
        if keyframes.rotations:
            obj.rotation_quaternion = to_blender_rotation(keyframes.rotations[0])
        return

    translation_by_time = dict(zip(keyframes.translation_times, keyframes.translations))
    rotation_by_time = dict(zip(keyframes.rotation_times, keyframes.rotations))
    original_frame = scene.frame_current
    try:
        for time in frame_times:
            frame = round(time * ANIM_FRAME_RATE)
            scene.frame_set(frame)
            if time in translation_by_time:
                obj.location = to_blender_space(translation_by_time[time])
                obj.keyframe_insert(data_path="location", frame=frame)
            if time in rotation_by_time:
                obj.rotation_quaternion = to_blender_rotation(rotation_by_time[time])
                obj.keyframe_insert(data_path="rotation_quaternion", frame=frame)
    finally:
        scene.frame_set(original_frame)
