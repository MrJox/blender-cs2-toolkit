import getpass
from datetime import datetime

from binary import cs2_structures as s
from binary import cs2_templates as t
from binary.bone_table import BoneTable, BoneTableEntry
from naming.naming import skeleton_bone_attributes
from .animation_models import AnimationClip
from .cs2_builder import _scene_node_for
from .skeleton_models import Skeleton, SkeletonBone, table_bones


class SkeletonBuildError(Exception):
    pass


def build_bone_table(skeleton: Skeleton) -> BoneTable:
    return BoneTable(
        skeleton_name=skeleton.name,
        version=skeleton.bone_table_version,
        reference_skeleton=skeleton.reference_skeleton,
        cinematic=skeleton.cinematic,
        entries=[
            BoneTableEntry(name=bone.name, bone_type=bone.bone_type, sort_order=bone.sort_order, flags=bone.bone_table_flags)
            for bone in table_bones(skeleton)
        ],
    )


def build_skeleton_cs2_document(
    skeleton: Skeleton, output_path: str = "", clip: AnimationClip | None = None
) -> s.CS2Document:
    # A clip is the same document with multi-key tracks on the bones it animates - CA's own authored
    # clips are the skeleton's whole node tree with 7 of 266 nodes carrying a translation track and
    # 29 a rotation track, every other node keeping its single rest key (PLAN_units.md 1.11).
    if not skeleton.bones:
        raise SkeletonBuildError("Skeleton has no bones.")

    tracks = clip.tracks if clip is not None else {}
    scene_nodes: list[s.SceneNode] = []
    for index, bone in enumerate(skeleton.bones):
        if bone.parent_index >= index:
            raise SkeletonBuildError(f"Bone '{bone.name}' is parented to a bone that comes after it.")
        node = _scene_node_for(
            bone.name,
            skeleton_bone_attributes(bone.max_handle, bone.is_limb),
            translation=bone.translation,
            rotation=bone.rotation,
            keyframes=tracks.get(bone.name),
        )
        node.parent_index = bone.parent_index + 1
        scene_nodes.append(node)

    details = t.build_details_string(
        username=getpass.getuser(),
        export_timestamp=datetime.now().strftime("%d/%m/%Y,%H:%M:%S"),
        cas_name_path=output_path,
    )

    return s.CS2Document(
        header=s.Header(
            file_format=t.FILE_FORMAT_MAGIC,
            exporter_version=t.EXPORTER_VERSION,
            feature_flags=t.FEATURE_FLAGS,
            plugin=t.get_plugin_header_string(),
            details=details,
        ),
        scene_block=s.SceneBlockData(
            format_compatibility_version=t.FORMAT_COMPATIBILITY_VERSION,
            object_types_count=t.OBJECT_TYPES_COUNT,
            lights_count=0,
            cameras_count=0,
            rigid_models_count=0,
            total_scene_vertex_count=0,
            weighted_models_count=0,
            lines_count=0,
            dummies_count=0,
            materials_count=0,
            total_scene_triangle_count=0,
            instances_count=0,
            scene_bbox_and_world_matrix=t.SCENE_BBOX_AND_WORLD_MATRIX,
        ),
        timeline_block=s.TimelineBlockData(
            frame_rate_fps=t.TIMELINE_FRAME_RATE_FPS,
            start_frame_time=t.TIMELINE_START_FRAME_TIME,
            end_frame_time=clip.duration if clip is not None else t.TIMELINE_END_FRAME_TIME,
            track_metadata=t.TIMELINE_TRACK_METADATA,
        ),
        morph_block=s.MorphAndSplineBlockData(morph_track_flags=t.MORPH_TRACK_FLAGS, tracks=[]),
        cameras=[],
        rigid_models=[],
        weighted_models=[],
        lines=[],
        dummies=[],
        scene_root=s.SceneRootNode(
            node_name=t.SCENE_ROOT_NODE_NAME,
            up_axis_orientation=t.SCENE_ROOT_UP_AXIS_ORIENTATION,
            scene_unit_scale=t.SCENE_ROOT_UNIT_SCALE,
            scene_hierarchy_metadata=t.scene_root_hierarchy_metadata(skeleton.scene_root_rotation),
            info=details,
            active_camera_index=0,
            active_light_index=0,
            root_end_padding=t.SCENE_ROOT_END_PADDING,
            scene_nodes=scene_nodes,
        ),
        materials=[],
        instances=[],
    )


def is_skeleton_document(document: s.CS2Document) -> bool:
    # A skeleton is a pure SCENE_ROOT tree - rigid_models/weighted_models/lines are all empty
    # (PLAN_units.md 1.4). Authored animation clips have that same shape, so they are told apart by
    # their multi-key tracks rather than by anything structural.
    return (
        not document.rigid_models
        and not document.weighted_models
        and not document.lines
        and bool(document.scene_root.scene_nodes)
    )


def is_animation_document(document: s.CS2Document) -> bool:
    return is_skeleton_document(document) and any(
        len(node.anim.translations) > 1 or len(node.anim.rotations) > 1 for node in document.scene_root.scene_nodes
    )


def skeleton_from_cs2_document(document: s.CS2Document, name: str, bone_table: BoneTable | None = None) -> Skeleton:
    if not is_skeleton_document(document):
        raise SkeletonBuildError("This .cs2 holds meshes - it is a model, not a skeleton.")

    entries = {entry.name: (order, entry) for order, entry in enumerate(bone_table.entries, start=1)} if bone_table else {}
    bones = []
    for node in document.scene_root.scene_nodes:
        if not node.anim.translations or not node.anim.rotations:
            raise SkeletonBuildError(f"Bone '{node.name}' has no rest-pose keyframe.")
        order, entry = entries.get(node.name, (0, None))
        bones.append(
            SkeletonBone(
                name=node.name,
                # SceneNode.parent_index is 1-based with 0 meaning "no parent" (PLAN_units.md 1.4).
                parent_index=node.parent_index - 1,
                translation=node.anim.translations[0],
                rotation=node.anim.rotations[0],
                max_handle=next((a.value for a in node.attributes.integers if a.name == "MaxHandle"), 0),
                is_limb=any(a.name == "LimbLength" for a in node.attributes.floats),
                bone_type=entry.bone_type if entry else "",
                sort_order=entry.sort_order if entry else 1,
                bone_table_flags=entry.flags if entry else "",
                bone_table_order=order,
            )
        )

    return Skeleton(
        name=name,
        bones=bones,
        scene_root_rotation=t.scene_root_rotation_of(document.scene_root.scene_hierarchy_metadata),
        bone_table_version=bone_table.version if bone_table else 1,
        reference_skeleton=bone_table.reference_skeleton if bone_table else True,
        cinematic=bone_table.cinematic if bone_table else False,
    )


__all__ = [
    "SkeletonBuildError",
    "is_skeleton_document",
    "is_animation_document",
    "build_bone_table",
    "build_skeleton_cs2_document",
    "skeleton_from_cs2_document",
]
