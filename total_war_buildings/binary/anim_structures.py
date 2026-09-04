from dataclasses import dataclass, field

Vec3 = tuple[float, float, float]
Vec4 = tuple[float, float, float, float]

FILE_VERSION_ATTILA = 5
QUATERNION_SCALE = 1.0 / 32767.0
STATIC_TRACK_BASE = 10000
NO_TRACK = -1

BUILDING_SKELETON_NAME = "building"


@dataclass
class AnimBone:
    name: str
    parent_id: int


@dataclass
class AnimFrame:
    translations: list[Vec3] = field(default_factory=list)
    rotations: list[Vec4] = field(default_factory=list)


@dataclass
class Animation:
    version: int
    bone_name_table_version: int
    frame_rate: float
    skeleton_name: str
    duration: float
    bones: list[AnimBone]
    translation_mappings: list[int]
    rotation_mappings: list[int]
    frames: list[AnimFrame]

    def is_building_debris(self) -> bool:
        return self.skeleton_name == BUILDING_SKELETON_NAME
