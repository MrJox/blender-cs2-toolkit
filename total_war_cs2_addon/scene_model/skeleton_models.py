from dataclasses import dataclass, field

from binary.bone_table import DEFAULT_BONE_TYPE
from binary.cs2_templates import SKELETON_SCENE_ROOT_ROTATION

Vec3 = tuple[float, float, float]
Vec4 = tuple[float, float, float, float]


@dataclass
class SkeletonBone:
    name: str
    parent_index: int
    translation: Vec3
    rotation: Vec4
    max_handle: int = 0
    # rome_man_game.cs2 gives a LimbLength of 1.0 to all 172 of its bn_/end_/drive_ nodes and to
    # none of its 56 ref_/null_ ones, which is 3ds Max's split between Bone objects and point
    # helpers. Kept per bone rather than re-derived from the name prefix so an imported skeleton
    # writes back exactly what it was read from.
    is_limb: bool = True
    bone_type: str = ""
    sort_order: int = 1
    bone_table_flags: str = ""
    # Line position in the .bone_table, 1-based; 0 for a bone the table does not list. The line
    # order is neither the hierarchy nor the compiled bone index order (PLAN_units.md 1.3/1.9), so
    # there is no rule to re-derive it from - it is preserved from the file it was read out of.
    bone_table_order: int = 0


@dataclass
class Skeleton:
    name: str
    bones: list[SkeletonBone] = field(default_factory=list)
    # The scene root's own rotation. Every skeleton observed carries the same half turn about Y,
    # and it is not something the artist authors in Blender - but it is read back from an imported
    # file rather than assumed, so a skeleton that ever carries a different one round-trips.
    scene_root_rotation: Vec4 = SKELETON_SCENE_ROOT_ROTATION
    bone_table_version: int = 1
    reference_skeleton: bool = True
    cinematic: bool = False


def table_bones(skeleton: Skeleton) -> list[SkeletonBone]:
    listed = [bone for bone in skeleton.bones if bone.bone_type]
    return sorted(listed, key=lambda bone: (bone.bone_table_order or len(listed) + 1, bone.name))


def compiled_bone_order(skeleton: Skeleton) -> list[str]:
    # The compiled bone index a weighted vertex and a MESH_ATTACH_POINT use is the bone's position
    # in the bone-table bones sorted by (depth in the hierarchy collapsed to those bones ascending,
    # name ascending) - PLAN_units.md 1.3, re-confirmed end to end by BOB's own output in Phase 4.
    listed = {bone.name for bone in skeleton.bones if bone.bone_type}
    depth_by_name: dict[str, int] = {}
    for bone in skeleton.bones:
        if bone.name not in listed:
            continue
        depth = 0
        parent_index = bone.parent_index
        while parent_index >= 0:
            parent = skeleton.bones[parent_index]
            if parent.name in listed:
                depth = depth_by_name[parent.name] + 1
                break
            parent_index = parent.parent_index
        depth_by_name[bone.name] = depth
    return sorted(listed, key=lambda name: (depth_by_name[name], name))
