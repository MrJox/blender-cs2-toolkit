from dataclasses import dataclass, field

from .models import MaterialDef, MeshData

TREE_ANIMATION_TYPE = "tree"

# BOB refuses a tree vertex carrying any other number of influences ("is missing the required number
# of bones"), and drops an influence on bone id 0 outright - a real compile weighted that way came
# back with every vertex collapsed onto the origin. 1 and 2 are the lowest pair it accepts, and
# writing them in ascending order is what makes the compiled weight quad pair each weight with its
# own bone (written descending, the same compile came back with the two weights swapped).
TREE_ANCHOR_BONE = 1
TREE_WIND_BONE = 2
TREE_BONE_NAMES = ("bn_tree_anchor", "bn_tree_wind")

# The four rungs of the fixed ladder, and which one each LOD slot lands on. The node's "_lodNN"
# postfix picks the rung, so a model that starts at LOD 2 simply has no 100m mesh.
LOD_CAMERA_DISTANCES = (100.0, 200.0, 400.0, 500.0)


@dataclass
class VegetationLod:
    lod_index: int
    mesh: MeshData
    materials: list[MaterialDef] = field(default_factory=list)
    # One entry per mesh vertex: how much of it the wind bone carries. The anchor bone takes the
    # rest, because every real tree vertex's two weights sum to exactly 1.
    wind_weights: list[float] = field(default_factory=list)


@dataclass
class VegetationModel:
    name: str
    lods: list[VegetationLod] = field(default_factory=list)
