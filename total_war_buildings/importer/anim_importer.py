from pathlib import Path

import bpy
import mathutils

from binary import anim_structures as a
from binary.anim_reader import bone_local_transform, read_anim
from binary.cs2_reader import read_cs2
from extraction.bone_space import (
    blender_object_to_engine,
    engine_to_blender_bone,
    local_engine_matrix,
    local_translation_rotation,
)
from extraction.animation_extract import matches_rest
from extraction.skeleton_extract import extract_skeleton_from_armature
from extraction.unit_extract import skeleton_name_for
from props.properties import get_assembly_kit_root_or_empty
from scene_model.animation_builder import animation_from_cs2_document, cs2_frame_rate
from scene_model.animation_models import AnimationClip
from scene_model.models import AnimationKeyframes
from scene_model.skeleton_models import Skeleton
from .anim_skeleton import ENGINE_HALF_TURN, is_reference_pose
from .messages import ImportNote
from .rigid_model_v2_importer import find_armature_for, import_rigid_model_v2
from .skeleton_importer import import_skeleton_source
from .skeleton_lookup import find_skeleton_source, searched_locations

# Clips are keyed one Blender frame per source frame, starting here rather than at 0: the clip's own
# frame rate is kept on the Action and the playback operator sets the scene to it, so a clip plays at
# the speed it was authored at and exports back out on the same frames it came in on.
FIRST_FRAME = 1

DEBRIS_MODEL_SUFFIX = ".rigid_model_v2"


class AnimImportError(Exception):
    pass


def clip_from_anim(animation: a.Animation, name: str) -> AnimationClip:
    # A mapping of -1 means "this channel has no data, keep the rest transform" (anim_spec 3.4), and
    # the .anim does not store that rest transform - so such a channel gets no track and the bone
    # keeps whatever the Armature already holds. Writing the zeros bone_local_transform returns for
    # it would collapse the bone onto its parent, which is what 27 of a deer clip's 28 bones would do.
    times = [index / animation.frame_rate for index in range(len(animation.frames))]
    tracks: dict[str, AnimationKeyframes] = {}
    parents: dict[str, str] = {}
    for index, bone in enumerate(animation.bones):
        translation_track = animation.translation_mappings[index]
        rotation_track = animation.rotation_mappings[index]
        has_translation = 0 <= translation_track < a.STATIC_TRACK_BASE
        has_rotation = 0 <= rotation_track < a.STATIC_TRACK_BASE
        if not has_translation and not has_rotation:
            continue

        translations = []
        rotations = []
        for frame in animation.frames:
            translation = frame.translations[translation_track] if has_translation else (0.0, 0.0, 0.0)
            rotation = frame.rotations[rotation_track] if has_rotation else (0.0, 0.0, 0.0, 1.0)
            if bone.parent_id < 0:
                # A compiled clip lives in the space BOB produces, which is the authoring space
                # turned a half turn about Y - the same turn anim_skeleton undoes for a rest pose.
                turned = ENGINE_HALF_TURN @ local_engine_matrix(translation, rotation)
                translation, rotation = local_translation_rotation(turned, None)
            translations.append(translation)
            rotations.append(rotation)

        tracks[bone.name] = AnimationKeyframes(
            translation_times=list(times) if has_translation else [],
            translations=translations if has_translation else [],
            rotation_times=list(times) if has_rotation else [],
            rotations=rotations if has_rotation else [],
        )
        parents[bone.name] = animation.bones[bone.parent_id].name if bone.parent_id >= 0 else ""

    return AnimationClip(
        name=name,
        skeleton_name=animation.skeleton_name,
        frame_rate=animation.frame_rate,
        frame_count=len(animation.frames),
        tracks=tracks,
        parents=parents,
    )


def _lerp_vector(first, second, factor):
    return tuple(start + (end - start) * factor for start, end in zip(first, second))


def _slerp_quaternion(first, second, factor):
    blended = mathutils.Quaternion((first[3], first[0], first[1], first[2])).slerp(
        mathutils.Quaternion((second[3], second[0], second[1], second[2])), factor
    )
    return (blended.x, blended.y, blended.z, blended.w)


def _interpolate(times, values, time, blend):
    # An .anim keys every dynamic channel on every frame, but an authored .cs2 clip does not - its
    # translation and rotation tracks carry different key counts on the same node - so a track is
    # sampled by time rather than indexed by frame.
    if not values:
        return None
    if len(values) == 1 or time <= times[0]:
        return values[0]
    if time >= times[-1]:
        return values[-1]
    for index in range(1, len(times)):
        if times[index] >= time:
            span = times[index] - times[index - 1]
            factor = (time - times[index - 1]) / span if span else 0.0
            return blend(values[index - 1], values[index], factor)
    return values[-1]


def _posed_world_matrices(clip: AnimationClip, skeleton: Skeleton, time: float, world_inverse):
    # A tracked bone composes onto whichever parent the clip says it hangs from - every such parent
    # is an ancestor in the skeleton too, so it is always already computed by the time it is needed.
    engine_world = []
    by_name: dict[str, mathutils.Matrix] = {}
    posed = []
    for bone in skeleton.bones:
        keyframes = clip.tracks.get(bone.name)
        translation, rotation = bone.translation, bone.rotation
        parent = engine_world[bone.parent_index] if bone.parent_index >= 0 else None
        if keyframes is not None:
            translation = _interpolate(keyframes.translation_times, keyframes.translations, time, _lerp_vector) or translation
            rotation = _interpolate(keyframes.rotation_times, keyframes.rotations, time, _slerp_quaternion) or rotation
            if bone.name in clip.parents:
                parent_name = clip.parents[bone.name]
                parent = by_name[parent_name] if parent_name else None
        local = local_engine_matrix(translation, rotation)
        world = local if parent is None else parent @ local
        engine_world.append(world)
        by_name[bone.name] = world
        posed.append(world_inverse @ engine_to_blender_bone(world))
    return posed


def bake_clip(armature_object: bpy.types.Object, clip: AnimationClip, skeleton: Skeleton) -> bpy.types.Action:
    # Blender composes a pose bone as
    #   pose.matrix = parent.pose.matrix @ parent.bone.matrix_local^-1 @ bone.matrix_local @ basis
    # (verified exactly against a real armature), so the basis a target pose needs is that product
    # inverted onto it - which keys the Action directly, with no depsgraph round trip per bone.
    armature = armature_object.data
    rest = [armature.bones[bone.name].matrix_local for bone in skeleton.bones]
    rest_inverse = [matrix.inverted() for matrix in rest]
    world_inverse = armature_object.matrix_world.inverted()
    animated = [index for index, bone in enumerate(skeleton.bones) if bone.name in clip.tracks]

    action = bpy.data.actions.new(clip.name)
    # Actions with no user are dropped when the .blend is saved, and an imported clip is exactly the
    # thing the artist expects to still be there after a reload.
    action.use_fake_user = True
    action.tw_skeleton_name = clip.skeleton_name or skeleton_name_for(armature_object)
    action.tw_frame_rate = clip.frame_rate

    animation_data = armature_object.animation_data_create()
    previous_action = animation_data.action
    animation_data.action = action
    try:
        for index in animated:
            armature_object.pose.bones[skeleton.bones[index].name].rotation_mode = "QUATERNION"
        for frame_index in range(clip.frame_count):
            time = frame_index / clip.frame_rate if clip.frame_rate else 0.0
            frame = FIRST_FRAME + frame_index
            posed = _posed_world_matrices(clip, skeleton, time, world_inverse)
            for index in animated:
                bone = skeleton.bones[index]
                parent_index = bone.parent_index
                reference = (
                    rest[index]
                    if parent_index < 0
                    else posed[parent_index] @ rest_inverse[parent_index] @ rest[index]
                )
                pose_bone = armature_object.pose.bones[bone.name]
                pose_bone.matrix_basis = reference.inverted() @ posed[index]
                keyframes = clip.tracks[bone.name]
                if keyframes.translations and (len(keyframes.translations) > 1 or frame_index == 0):
                    pose_bone.keyframe_insert(data_path="location", frame=frame)
                if keyframes.rotations and (len(keyframes.rotations) > 1 or frame_index == 0):
                    pose_bone.keyframe_insert(data_path="rotation_quaternion", frame=frame)
    finally:
        animation_data.action = previous_action
    return action


def _resolve_armature(
    skeleton_name: str, path: Path, context: bpy.types.Context, warnings: list[str]
) -> bpy.types.Object:
    armature_object = find_armature_for(skeleton_name)
    if armature_object is not None:
        return armature_object

    assembly_kit_root = get_assembly_kit_root_or_empty()
    source = find_skeleton_source(skeleton_name, path, assembly_kit_root)
    if source is not None:
        armature_object, _collection, skeleton_warnings = import_skeleton_source(source, context)
        warnings.extend(skeleton_warnings)
        warnings.append(ImportNote(f"Skeleton '{skeleton_name}' was imported from {source.where}: {source.path}"))
        return armature_object

    looked_in = "\n".join(f"  {folder}" for folder in searched_locations(path, assembly_kit_root))
    raise AnimImportError(
        f"'{path.name}' animates the skeleton '{skeleton_name}', which is not in the scene. A clip "
        "cannot supply one: its static channels say only 'keep the rest transform', and the rest "
        "transform is not in the file. Import the skeleton first. Looked in:\n" + looked_in
    )


def _prune(clip: AnimationClip, skeleton: Skeleton) -> list[str]:
    # A clip carries a track for every node in the file it came from. Two kinds say nothing: one for
    # a node the Armature does not have - a clip .cs2 also holds the animator's own prop meshes -
    # and one holding a single key that is already the bone's rest transform. Only a moving track
    # with nowhere to go is worth telling the artist about.
    rest = {bone.name: bone for bone in skeleton.bones}
    unmatched: list[str] = []
    for name, keyframes in list(clip.tracks.items()):
        bone = rest.get(name)
        moving = len(keyframes.translations) > 1 or len(keyframes.rotations) > 1
        if bone is None:
            if moving:
                unmatched.append(name)
        elif moving or not matches_rest(bone, keyframes.translations[0], keyframes.rotations[0]):
            continue
        clip.tracks.pop(name)
        clip.parents.pop(name, None)
    return sorted(unmatched)


def _apply_clip(
    armature_object: bpy.types.Object,
    clip: AnimationClip,
    context: bpy.types.Context,
    warnings: list[str],
) -> bpy.types.Action:
    skeleton, _skeleton_warnings = extract_skeleton_from_armature(armature_object, skeleton_name_for(armature_object))
    missing = _prune(clip, skeleton)
    if missing:
        warnings.append(
            f"{len(missing)} animated bone(s) have no matching bone in '{armature_object.name}' and "
            f"were skipped: {', '.join(missing[:5])}"
        )
    if not clip.tracks:
        raise AnimImportError(
            f"None of '{clip.name}'s bones match '{armature_object.name}' - this clip is for a "
            "different skeleton."
        )

    action = bake_clip(armature_object, clip, skeleton)
    apply_action(armature_object, action, context.scene)
    warnings.append(
        ImportNote(
            f"'{action.name}' plays on '{armature_object.name}': {clip.frame_count} frames at "
            f"{clip.frame_rate:g} fps, {len(clip.tracks)} animated bone(s)."
        )
    )
    return action


def rest_pose(armature_object: bpy.types.Object) -> None:
    # Unassigning the Action is not enough on its own: a pose channel keeps whatever value was last
    # written to it, so the skeleton stays frozen wherever the clip left it - measured 2.55 m off its
    # rest pose. Clearing every basis is what actually puts it back.
    if armature_object.animation_data is not None:
        armature_object.animation_data.action = None
    for pose_bone in armature_object.pose.bones:
        pose_bone.matrix_basis = mathutils.Matrix()


def apply_action(armature_object: bpy.types.Object, action: bpy.types.Action, scene: bpy.types.Scene) -> None:
    # The rest pose first, every time. A clip only keys the bones it animates, and bake_clip computes
    # each of those against its ancestors sitting at rest - so a bone the new clip does not key must
    # not still be holding the last one's pose. A compiled .anim carries only the 50 game bones while
    # rome_man_game has 228 nodes, and a .cs2 clip poses ref_skeleton a quarter turn about X, so
    # loading the .anim after the .cs2 left the whole skeleton 90 degrees face-down.
    rest_pose(armature_object)
    animation_data = armature_object.animation_data_create()
    animation_data.action = action
    start, end = action.frame_range
    scene.frame_start = round(start)
    scene.frame_end = round(end)
    scene.frame_set(round(start))
    if action.tw_frame_rate:
        scene.render.fps = max(1, round(action.tw_frame_rate))
        scene.render.fps_base = 1.0


def _armature_collection(armature_object: bpy.types.Object, context: bpy.types.Context) -> bpy.types.Collection:
    for collection in armature_object.users_collection:
        if collection.tw_role == "SKELETON":
            return collection
    return armature_object.users_collection[0] if armature_object.users_collection else context.scene.collection


def import_debris_bundle(
    path: Path, animation: a.Animation, context: bpy.types.Context
) -> tuple[bpy.types.Collection, list[str]]:
    # A debris clip and the pieces it drives are the same file stem in the same folder, and each
    # rigid mesh's MESH_HEADER_V5.matrix_index is its track number in the clip - many meshes can
    # share one piece's track (PLAN_units.md 1.5).
    model_path = path.with_name(path.stem + DEBRIS_MODEL_SUFFIX)
    if not model_path.is_file():
        raise AnimImportError(
            f"'{path.name}' is a building debris clip, which only means something alongside the "
            f"pieces it moves - but '{model_path.name}' is not in the same folder."
        )

    collection, warnings = import_rigid_model_v2(str(model_path), context)
    # The pieces are a reference import, not an authorable asset: a debris bundle is a building's
    # compiled output, and the Building workflow authors debris from its own scene animation.
    collection.tw_role = "NONE"
    for child in collection.children_recursive:
        child.tw_role = "NONE"

    applied = 0
    unmatched = set()
    for obj in collection.all_objects:
        index = obj.tw_debris_track_index
        if index < 0:
            continue
        if index >= len(animation.bones):
            unmatched.add(index)
            continue
        _bake_object_track(obj, animation, index)
        applied += 1

    context.scene.frame_start = FIRST_FRAME
    context.scene.frame_end = FIRST_FRAME + len(animation.frames) - 1
    context.scene.render.fps = max(1, round(animation.frame_rate))
    context.scene.render.fps_base = 1.0
    context.scene.frame_set(FIRST_FRAME)

    if unmatched:
        warnings.append(
            f"{len(unmatched)} mesh(es) name a debris track '{path.name}' does not have - they were "
            "left where the model put them."
        )
    warnings.append(
        ImportNote(
            f"'{path.name}' moved {applied} of {len(collection.all_objects)} imported piece(s) over "
            f"{len(animation.frames)} frames at {animation.frame_rate:g} fps."
        )
    )
    return collection, warnings


def _bake_object_track(obj: bpy.types.Object, animation: a.Animation, index: int) -> None:
    # A debris piece is a plain object, not a bone: its mesh is stored about its own origin and the
    # clip carries the world placement, which is why an unbundled debris model imports as a heap at
    # the origin. No half turn here - a building's own scene root rotation is the identity.
    obj.rotation_mode = "QUATERNION"
    obj.animation_data_create()
    for frame_index in range(len(animation.frames)):
        translation, rotation = bone_local_transform(animation, index, frame_index)
        frame = FIRST_FRAME + frame_index
        # blender_object_to_engine is its own inverse, so the same call converts back out of engine.
        placement = blender_object_to_engine(local_engine_matrix(translation, rotation))
        obj.location = placement.translation
        obj.rotation_quaternion = placement.to_quaternion()
        obj.keyframe_insert(data_path="location", frame=frame)
        obj.keyframe_insert(data_path="rotation_quaternion", frame=frame)


def import_anim(filepath: str, context: bpy.types.Context) -> tuple[bpy.types.Collection, list[str], str]:
    path = Path(bpy.path.abspath(filepath))
    animation = read_anim(path.read_bytes())

    if animation.is_building_debris():
        collection, warnings = import_debris_bundle(path, animation, context)
        return collection, warnings, "DEBRIS ANIMATION"

    if is_reference_pose(animation):
        raise AnimImportError(
            f"'{path.name}' holds no motion - it is a compiled skeleton rest pose, which BOB writes "
            "as two frames. Import it through the Skeleton workflow instead."
        )

    warnings: list[str] = []
    armature_object = _resolve_armature(animation.skeleton_name, path, context, warnings)
    _apply_clip(armature_object, clip_from_anim(animation, path.stem), context, warnings)
    return _armature_collection(armature_object, context), warnings, "ANIMATION"


def import_animation_cs2(
    filepath: str, context: bpy.types.Context, document=None
) -> tuple[bpy.types.Collection, list[str], str]:
    path = Path(bpy.path.abspath(filepath))
    if document is None:
        document = read_cs2(path.read_bytes())

    warnings: list[str] = []
    clip = animation_from_cs2_document(document, path.stem, cs2_frame_rate(document))
    # An authored clip names no skeleton anywhere in the file - it embeds the whole node tree
    # instead - so the one already in the scene is the only thing that can say which it is.
    armature_object = next(
        (obj for obj in bpy.data.objects if obj.type == "ARMATURE" and _covers(obj, clip)), None
    )
    if armature_object is None:
        raise AnimImportError(
            f"'{path.name}' is an authored animation clip. It carries no skeleton name, so the "
            "skeleton it animates has to be in the scene already - import that first."
        )
    clip.skeleton_name = skeleton_name_for(armature_object)
    _apply_clip(armature_object, clip, context, warnings)
    return _armature_collection(armature_object, context), warnings, "ANIMATION"


def _covers(armature_object: bpy.types.Object, clip: AnimationClip) -> bool:
    # Only the moving tracks have to be there. A clip .cs2 also carries the animator's own prop
    # meshes and every static node in his scene, none of which any skeleton has.
    names = {bone.name for bone in armature_object.data.bones}
    moving = {
        name
        for name, keyframes in clip.tracks.items()
        if len(keyframes.translations) > 1 or len(keyframes.rotations) > 1
    }
    return bool(moving) and not (moving - names)


__all__ = [
    "AnimImportError",
    "rest_pose",
    "import_anim",
    "import_animation_cs2",
    "import_debris_bundle",
    "clip_from_anim",
    "bake_clip",
    "apply_action",
    "FIRST_FRAME",
]
