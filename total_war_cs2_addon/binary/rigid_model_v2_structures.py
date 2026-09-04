from dataclasses import dataclass, field

Vec3 = tuple[float, float, float]
Vec4 = tuple[float, float, float, float]
Matrix43 = tuple[Vec4, Vec4, Vec4]
BoundingBox = tuple[Vec3, Vec3]

FILE_SIGNATURE = b"RMV2"
FILE_VERSION_ATTILA = 6
FILE_HEADER_SIZE = 140
LOD_HEADER_SIZE = 20
COMMON_MESH_HEADER_SIZE = 80
MESH_HEADER_V5_SIZE = 860
ATTACHMENT_POINT_SIZE = 84
TEXTURE_ENTRY_SIZE = 260

SHADER_STANDARD_TILED_DIRTMAP_V5 = 63
SHADER_STANDARD_V5 = 68
SHADER_TREE_V5 = 74
SHADER_LEAF_V5 = 75
SHADER_CAMERA_ALIGNED_BILLBOARD_V6 = 89
SHADER_WEIGHTED_V5 = 65
SHADER_WEIGHTED_SKIN_V5 = 70
SHADER_STANDARD_WITH_DECAL_V5 = 71
SHADER_STANDARD_WITH_DECAL_DIRTMAP_V5 = 72
SHADER_STANDARD_WITH_DIRTMAP_V5 = 73
SHADER_WEIGHTED_WITH_DECAL_V5 = 77
SHADER_WEIGHTED_WITH_DECAL_DIRTMAP_V5 = 78
SHADER_WEIGHTED_WITH_DIRTMAP_V5 = 79
SHADER_WEIGHTED_SKIN_DECAL_V5 = 80
SHADER_WEIGHTED_SKIN_DECAL_DIRTMAP_V5 = 81
SHADER_WEIGHTED_SKIN_DIRTMAP_V5 = 82

VERTEX_STANDARD_RIGID = 0
VERTEX_RIGID_COLLISION = 1
VERTEX_RIGID_TEXTURE_BLEND = 2
VERTEX_WEIGHTED_2_BONES = 3
VERTEX_WEIGHTED_4_BONES = 4
VERTEX_TREE = 6
VERTEX_BILLBOARD = 7

VERTEX_SIZES = {
    VERTEX_STANDARD_RIGID: 32,
    VERTEX_RIGID_COLLISION: 24,
    VERTEX_RIGID_TEXTURE_BLEND: 28,
    VERTEX_WEIGHTED_2_BONES: 28,
    VERTEX_WEIGHTED_4_BONES: 32,
    VERTEX_TREE: 60,
    VERTEX_BILLBOARD: 12,
}

# The three shaders every battlefield tree, shrub and stone is built from, and nothing else uses.
# PLAN_vegetation.md 1.2: measured across all 315 game-ready models, 1439 meshes.
VEGETATION_SHADERS = frozenset({SHADER_TREE_V5, SHADER_LEAF_V5, SHADER_CAMERA_ALIGNED_BILLBOARD_V6})

WEIGHTED_SHADERS = frozenset(
    {
        SHADER_WEIGHTED_V5,
        SHADER_WEIGHTED_SKIN_V5,
        SHADER_WEIGHTED_WITH_DECAL_V5,
        SHADER_WEIGHTED_WITH_DECAL_DIRTMAP_V5,
        SHADER_WEIGHTED_WITH_DIRTMAP_V5,
        SHADER_WEIGHTED_SKIN_DECAL_V5,
        SHADER_WEIGHTED_SKIN_DECAL_DIRTMAP_V5,
        SHADER_WEIGHTED_SKIN_DIRTMAP_V5,
    }
)

TEXTURE_PARAM_NAMES = {
    0: "diffuse",
    1: "normal",
    2: "detail_normal",
    3: "faction_mask",
    4: "material_map",
    5: "ambient_occlusion_uv2",
    6: "displacement",
    7: "dirtmap_uv2",
    8: "alpha_mask",
    9: "dissolve",
    10: "skin_mask",
    11: "specular",
    12: "gloss",
    13: "decal_dirtmap",
    14: "decal_dirtmask",
    15: "decal_mask",
    16: "diffuse_burn",
    17: "diffuse_damage",
    18: "diffuse_sp",
    19: "diffuse_su",
    20: "diffuse_au",
    21: "diffuse_wi",
    22: "diffuse_snow",
}


@dataclass
class AttachmentPoint:
    name: str
    transform: Matrix43
    bone_index: int


@dataclass
class TextureEntry:
    texture_id: int
    path: str


@dataclass
class StringParam:
    param_id: int
    value: str


@dataclass
class FloatParam:
    param_id: int
    value: float


@dataclass
class IntParam:
    param_id: int
    value: int


@dataclass
class Vec4Param:
    param_id: int
    value: Vec4


@dataclass
class MeshHeaderV5:
    vertex_format: int
    name: str
    texture_directory: str
    filters: str
    pivot: Vec3
    matrix1: Matrix43
    matrix2: Matrix43
    matrix3: Matrix43
    matrix_index: int
    parent_matrix_index: int
    attachment_points: list[AttachmentPoint] = field(default_factory=list)
    textures: list[TextureEntry] = field(default_factory=list)
    string_params: list[StringParam] = field(default_factory=list)
    float_params: list[FloatParam] = field(default_factory=list)
    int_params: list[IntParam] = field(default_factory=list)
    vec4_params: list[Vec4Param] = field(default_factory=list)


@dataclass
class Vertex:
    position: Vec3
    uv: tuple[float, float]
    normal: Vec3
    tangent: Vec3
    binormal: Vec3
    uv2: tuple[float, float] | None = None
    colour: tuple[int, int, int, int] | None = None
    bone_indices: tuple[int, ...] = ()
    bone_weights: tuple[float, ...] = ()
    # WS_VF_TREE_VERTEX only. Kept under the format's own field names rather than an interpretation:
    # PLAN_vegetation.md 1.4 measures what they contain (position0 is a point inside the model that
    # the vertex sits away from, the first two weights always sum to 1) but what the shader does
    # with them is not established, and naming them "wind pivot" would state more than is known.
    tree_position0: Vec3 | None = None
    tree_weights: Vec4 | None = None


@dataclass
class Mesh:
    shader_flags: int
    render_flags: int
    section_size: int
    vertex_count: int
    index_count: int
    bounding_box: BoundingBox
    lighting_constants_name: str
    shader_params_raw: bytes
    material: MeshHeaderV5 | None
    material_raw: bytes
    vertex_format: int | None
    vertex_stride: int
    vertices: list[Vertex]
    vertices_raw: bytes
    indices: list[int]


@dataclass
class Lod:
    camera_distance: float
    total_vertex_size: int
    total_index_size: int
    meshes: list[Mesh]


@dataclass
class RigidModelV2:
    signature: bytes
    version: int
    bone_table_name: str
    lods: list[Lod]


# Every other shader carries one of the small special-purpose headers (projected decal,
# collision shape, cloth, billboard, point light, terrain), which this reader keeps opaque.
#
# 89 is not in the published mapping, which lists only the V5 billboard as taking the small
# BILLBOARD_MESH_HEADER. Measured against all 315 vegetation models: the V6 billboard carries a full
# MESH_HEADER_V5 (vertex format 7, name "generated_billboard", a texture list and the three colour
# vec4s), so it belongs here.
MESH_HEADER_V5_SHADERS = frozenset(
    {26, 27, 41, 59, 61, 63, 64, 65, 68, 69, 70, 71, 72, 73, 74, 75, 77, 78, 79, 80, 81, 82, 83, 84, 85, 86, 89, 92, 94}
)

DEFAULT_VERTEX_FORMAT_BY_SHADER = {
    0: VERTEX_STANDARD_RIGID,
    3: 5,
    6: 6,
    7: 6,
    8: 7,
    26: VERTEX_STANDARD_RIGID,
    27: VERTEX_STANDARD_RIGID,
    28: VERTEX_STANDARD_RIGID,
    47: VERTEX_STANDARD_RIGID,
    49: VERTEX_STANDARD_RIGID,
    58: VERTEX_WEIGHTED_2_BONES,
    59: VERTEX_WEIGHTED_2_BONES,
    60: VERTEX_STANDARD_RIGID,
    61: VERTEX_RIGID_COLLISION,
    62: VERTEX_RIGID_COLLISION,
    63: VERTEX_STANDARD_RIGID,
    64: VERTEX_STANDARD_RIGID,
    65: VERTEX_WEIGHTED_2_BONES,
    66: VERTEX_STANDARD_RIGID,
    67: VERTEX_STANDARD_RIGID,
    68: VERTEX_STANDARD_RIGID,
    69: 5,
    70: VERTEX_WEIGHTED_2_BONES,
    71: VERTEX_STANDARD_RIGID,
    72: VERTEX_STANDARD_RIGID,
    73: VERTEX_STANDARD_RIGID,
    74: 6,
    75: 6,
    76: 7,
    77: VERTEX_WEIGHTED_2_BONES,
    78: VERTEX_WEIGHTED_2_BONES,
    79: VERTEX_WEIGHTED_2_BONES,
    80: VERTEX_WEIGHTED_2_BONES,
    81: VERTEX_WEIGHTED_2_BONES,
    82: VERTEX_WEIGHTED_2_BONES,
    83: VERTEX_STANDARD_RIGID,
    84: VERTEX_STANDARD_RIGID,
    85: VERTEX_WEIGHTED_2_BONES,
    86: VERTEX_STANDARD_RIGID,
    87: VERTEX_STANDARD_RIGID,
    SHADER_CAMERA_ALIGNED_BILLBOARD_V6: VERTEX_BILLBOARD,
    92: 11,
    94: 12,
    95: VERTEX_STANDARD_RIGID,
}
