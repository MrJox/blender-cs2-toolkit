from dataclasses import dataclass, field

from .models import MaterialDef, MeshData, Vec3, Vec4
from .skeleton_models import Skeleton

WEIGHTED_KIND = "WEIGHTED"
RIGID_ATTACHMENT_KIND = "RIGID_ATTACHMENT"

# Every real weighted unit vertex carries at most two influences summing to 1.0, and the compiled
# formats only have room for two (PLAN_units.md 1.1/1.7).
MAX_BONE_INFLUENCES = 2


@dataclass
class UnitLod:
    lod_index: int
    mesh: MeshData
    materials: list[MaterialDef] = field(default_factory=list)
    # One entry per mesh vertex, each a list of (bone name, weight). Empty on a rigid part.
    weights: list[list[tuple[str, float]]] = field(default_factory=list)

    @property
    def material(self) -> MaterialDef:
        return self.materials[0] if self.materials else MaterialDef(name="default", shader_type="default")


@dataclass
class UnitMeshPart:
    name: str
    lods: list[UnitLod] = field(default_factory=list)


@dataclass
class AttachmentPoint:
    name: str
    bone_name: str
    translation: Vec3
    rotation: Vec4


@dataclass
class UnitPart:
    name: str
    kind: str
    meshes: list[UnitMeshPart] = field(default_factory=list)
    # A weighted part embeds the whole skeleton node tree so its per-vertex bone ids have something
    # to index; a rigid attachment part carries none at all (PLAN_units.md 1.7).
    skeleton: Skeleton | None = None
    attachment_points: list[AttachmentPoint] = field(default_factory=list)

    @property
    def is_weighted(self) -> bool:
        return self.kind == WEIGHTED_KIND
