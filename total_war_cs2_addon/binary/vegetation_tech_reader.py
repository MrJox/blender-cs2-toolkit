from dataclasses import dataclass, field

from binary.reader import BinaryReader
from binary.cs2_parsed_reader import CS2ParsedCollision, _read_collision3d

VEGETATION_TECH_VERSION = 0
LOWEST_LOD_HULL_NAME = "lowest_lod"


@dataclass
class VegetationVfxNode:
    name: str
    transform: list[float]
    face_indices: list[int] = field(default_factory=list)


@dataclass
class VegetationTechData:
    version: int
    hull: CS2ParsedCollision
    vfx_nodes: list[VegetationVfxNode] = field(default_factory=list)


def is_vegetation_tech(data: bytes) -> bool:
    return len(data) >= 4 and int.from_bytes(data[:4], "little") == VEGETATION_TECH_VERSION


# A tree's tech sidecar shares the .cs2.parsed name and two of its sub-structures, but not its
# container: there is no bounding box, no flag node and no piece/destruct tree, and the version word
# is 0 rather than a building's 11 or 13. Validated byte-exactly - zero bytes left over - against
# all 314 game-ready sidecars (PLAN_vegetation.md 2.1).
class VegetationTechReader:
    @staticmethod
    def read_bytes(data: bytes) -> VegetationTechData:
        r = BinaryReader(data)
        version = r.u32()
        if version != VEGETATION_TECH_VERSION:
            raise ValueError(f"not a vegetation tech file: version {version}")

        hull = _read_collision3d(r)

        nodes = []
        for _ in range(r.u32()):
            name = r.utf16_string()
            nodes.append(VegetationVfxNode(name=name, transform=[r.f32() for _ in range(16)]))

        # One index list per VFX node, in the same order, naming the hull faces that node owns. The
        # lists partition the hull exactly: their union is every face index, on all 314 samples.
        for index in range(r.u32()):
            count = r.u32()
            indices = [r.u16() for _ in range(count)]
            if index < len(nodes):
                nodes[index].face_indices = indices

        return VegetationTechData(version=version, hull=hull, vfx_nodes=nodes)

    @classmethod
    def read_file(cls, path: str) -> VegetationTechData:
        with open(path, "rb") as handle:
            return cls.read_bytes(handle.read())
