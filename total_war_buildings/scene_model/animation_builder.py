from binary import cs2_structures as s
from .animation_models import AnimationClip
from .models import AnimationKeyframes
from .skeleton_builder import build_skeleton_cs2_document, is_animation_document
from .skeleton_models import Skeleton


class AnimationBuildError(Exception):
    pass


def build_animation_cs2_document(
    skeleton: Skeleton, clip: AnimationClip, output_path: str = ""
) -> s.CS2Document:
    if not clip.tracks:
        raise AnimationBuildError(f"'{clip.name}' has no animated bones.")
    unknown = sorted(set(clip.tracks) - {bone.name for bone in skeleton.bones})
    if unknown:
        raise AnimationBuildError(
            f"'{clip.name}' animates {len(unknown)} bone(s) that '{skeleton.name}' does not have: "
            + ", ".join(unknown[:5])
        )
    # A CS2 node's keys are local to its own parent node, so a clip whose locals are relative to a
    # different hierarchy - a compiled .anim's collapsed bone list - cannot be written straight out.
    # Export always re-samples from the posed Armature, which is relative to the skeleton, so this
    # only ever fires on a clip handed in from the import side.
    parent_by_name = {
        bone.name: (skeleton.bones[bone.parent_index].name if bone.parent_index >= 0 else "")
        for bone in skeleton.bones
    }
    rehung = sorted(name for name, parent in clip.parents.items() if parent_by_name.get(name, parent) != parent)
    if rehung:
        raise AnimationBuildError(
            f"'{clip.name}' holds transforms relative to a different bone hierarchy than "
            f"'{skeleton.name}' ({', '.join(rehung[:5])}) - it has to be sampled off the posed "
            "Armature before it can be written."
        )
    return build_skeleton_cs2_document(skeleton, output_path=output_path, clip=clip)


def animation_from_cs2_document(document: s.CS2Document, name: str, frame_rate: float) -> AnimationClip:
    if not is_animation_document(document):
        raise AnimationBuildError(
            f"'{name}' carries a single keyframe on every node - it is a skeleton rest pose, not a clip."
        )

    tracks: dict[str, AnimationKeyframes] = {}
    start = min(
        min(node.anim.translation_frame_times + node.anim.rotation_frame_times)
        for node in document.scene_root.scene_nodes
    )
    end = start
    # Every node, not only the moving ones: a real clip poses bones statically as well as animating
    # them - sws_run_443_cm holds bn_lefthandindex2 0.84 of a quaternion away from the skeleton's
    # rest pose on a single key, gripping the sword - and dropping those single keys imports a
    # running man with open hands. Which of them say anything the rest pose does not is decided
    # against the Armature, by the caller, since the clip file has no rest pose to compare with.
    for node in document.scene_root.scene_nodes:
        if len(node.anim.translations) > 1 or len(node.anim.rotations) > 1:
            end = max(end, *node.anim.translation_frame_times, *node.anim.rotation_frame_times)
        tracks[node.name] = AnimationKeyframes(
            # A real clip's key times are absolute seconds on the animator's own Max timeline
            # (sws_run_443_cm runs 7.30 - 7.93s), so they are rebased onto the clip's own start.
            translation_times=[time - start for time in node.anim.translation_frame_times],
            translations=list(node.anim.translations),
            rotation_times=[time - start for time in node.anim.rotation_frame_times],
            rotations=list(node.anim.rotations),
        )

    return AnimationClip(
        name=name,
        skeleton_name="",
        frame_rate=frame_rate,
        frame_count=round((end - start) * frame_rate) + 1,
        tracks=tracks,
    )


def cs2_frame_rate(document: s.CS2Document) -> float:
    # The .cs2 stores key times in seconds, not frame numbers, and carries no rate of its own - the
    # rate is the reciprocal of the spacing the animator sampled at. Measured off the longest track
    # rather than assumed: CA's sword_and_shield clips all come out at 60.
    deltas = []
    for node in document.scene_root.scene_nodes:
        for times in (node.anim.translation_frame_times, node.anim.rotation_frame_times):
            deltas.extend(b - a for a, b in zip(times, times[1:]) if b > a)
    if not deltas:
        return 0.0
    return round(1.0 / (sum(deltas) / len(deltas)))


__all__ = [
    "AnimationBuildError",
    "build_animation_cs2_document",
    "animation_from_cs2_document",
    "cs2_frame_rate",
]
