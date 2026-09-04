from dataclasses import dataclass, field

Vec3 = tuple[float, float, float]
Vec4 = tuple[float, float, float, float]
BoundingBox = tuple[Vec3, Vec3]


@dataclass
class NodeAttributeString:
    name: str
    value: str


@dataclass
class NodeAttributeInteger:
    name: str
    value: int
    # Every real sample file uses these exact non-zero defaults (Linear interpolation,
    # 0 keyframes, EndFrame=1, ReservedFlags=1) even for a plain static value; the
    # InterpolationMode=0 ("Static") path this implies exists appears to be untested by
    # BOB and crashes it (see naming/naming.py and materials/template.py callers).
    interpolation_mode: int = 1
    num_keys: int = 0
    start_frame: int = 0
    end_frame: int = 1
    loop_flags: int = 0
    reserved_flags: int = 1


@dataclass
class NodeAttributeFloat:
    name: str
    value: float
    # Every real sample file uses these exact non-zero defaults (Linear interpolation,
    # 0 keyframes, EndFrame=1, ReservedFlags=1) even for a plain static value; the
    # InterpolationMode=0 ("Static") path this implies exists appears to be untested by
    # BOB and crashes it (see naming/naming.py and materials/template.py callers).
    interpolation_mode: int = 1
    num_keys: int = 0
    start_frame: int = 0
    end_frame: int = 1
    loop_flags: int = 0
    reserved_flags: int = 1


@dataclass
class NodeAttributeVec3:
    name: str
    value: Vec3
    # Every real sample file uses these exact non-zero defaults (Linear interpolation,
    # 0 keyframes, EndFrame=1, ReservedFlags=1) even for a plain static value; the
    # InterpolationMode=0 ("Static") path this implies exists appears to be untested by
    # BOB and crashes it (see naming/naming.py and materials/template.py callers).
    interpolation_mode: int = 1
    num_keys: int = 0
    start_frame: int = 0
    end_frame: int = 1
    loop_flags: int = 0
    reserved_flags: int = 1


@dataclass
class NodeAttributeVec4:
    name: str
    value: Vec4
    # Every real sample file uses these exact non-zero defaults (Linear interpolation,
    # 0 keyframes, EndFrame=1, ReservedFlags=1) even for a plain static value; the
    # InterpolationMode=0 ("Static") path this implies exists appears to be untested by
    # BOB and crashes it (see naming/naming.py and materials/template.py callers).
    interpolation_mode: int = 1
    num_keys: int = 0
    start_frame: int = 0
    end_frame: int = 1
    loop_flags: int = 0
    reserved_flags: int = 1


@dataclass
class NodeAttributes:
    strings: list[NodeAttributeString] = field(default_factory=list)
    integers: list[NodeAttributeInteger] = field(default_factory=list)
    floats: list[NodeAttributeFloat] = field(default_factory=list)
    vec3s: list[NodeAttributeVec3] = field(default_factory=list)
    vec4s: list[NodeAttributeVec4] = field(default_factory=list)


@dataclass
class LineSegment:
    start_vertex_index: int
    end_vertex_index: int


@dataclass
class LineData:
    vertices: list[Vec3]
    segments: list[LineSegment]


@dataclass
class RigidVertex:
    position: Vec3
    normal: Vec3
    color: Vec4
    tex_coords: list[Vec3]
    vertex_ao_or_morph_weight: float


@dataclass
class BoneWeight:
    bone_id: int
    weight: float


@dataclass
class WeightedVertex:
    position: Vec3
    normal: Vec3
    color: Vec4
    tex_coords: list[Vec3]
    vertex_ao_or_morph_weight: float
    bone_weights: list[BoneWeight]
    unskinned_position: Vec3
    unskinned_normal: Vec3


@dataclass
class SubMesh:
    triangles: list[tuple[int, int, int]]
    material_id: int


@dataclass
class GeometryChunkCommon:
    header_padding: bytes
    bounding_box_extent_floats: list[float]
    bounding_boxes: list[BoundingBox]
    lines: list[LineData]


@dataclass
class RigidGeometryChunk(GeometryChunkCommon):
    uvw_channel_ids: list[int]
    vertices: list[RigidVertex]
    submeshes: list[SubMesh]
    vertex_color_channel_flags: int


@dataclass
class WeightedGeometryChunk(GeometryChunkCommon):
    uvw_channel_ids: list[int]
    vertices: list[WeightedVertex]
    submeshes: list[SubMesh]
    vertex_color_channel_flags: int


@dataclass
class LineGeometryChunk(GeometryChunkCommon):
    vertex_color_channel_flags: int


@dataclass
class InstanceGeometryChunk(GeometryChunkCommon):
    original_node_index: int
    vertex_color_channel_flags: int
    material_id: int | None = None


@dataclass
class NodeCommon:
    node_name: str
    node_metadata_string: str
    user_defined_properties: str
    node_index: int
    attributes: NodeAttributes


@dataclass
class RigidModelNode(NodeCommon):
    geometry_chunks: list[RigidGeometryChunk]


@dataclass
class WeightedModelNode(NodeCommon):
    geometry_chunks: list[WeightedGeometryChunk]


@dataclass
class LineNode(NodeCommon):
    geometry_chunks: list[LineGeometryChunk]


@dataclass
class InstanceNode(NodeCommon):
    override_material: bool
    leading_unknown: int
    geometry_chunks: list[InstanceGeometryChunk]


@dataclass
class DummyNode(NodeCommon):
    geometry_data_count: int


@dataclass
class CameraNode(NodeCommon):
    camera_parameters: bytes


@dataclass
class SceneNodeAnimTrack:
    translation_frame_times: list[float]
    translations: list[Vec3]
    scale_track_or_bbox: bytes
    rotation_frame_times: list[float]
    rotations: list[Vec4]


@dataclass
class SceneNode:
    name: str
    parent_index: int
    default_scale_or_pivot: Vec4
    anim: SceneNodeAnimTrack
    parent_node_index: int
    target_linkage_name: str
    attributes: NodeAttributes


@dataclass
class SceneRootNode:
    node_name: str
    up_axis_orientation: int
    scene_unit_scale: int
    scene_hierarchy_metadata: bytes
    info: str
    active_camera_index: int
    active_light_index: int
    root_end_padding: bytes
    scene_nodes: list[SceneNode]


@dataclass
class DefaultMaterial:
    # Legacy 3ds Max "standard material" path. This plugin never authors MATERIAL_TYPE_DEFAULT
    # nodes (only MATERIAL_TYPE_DIRECTX), so its internal layout is kept opaque and round-tripped
    # verbatim rather than fully decomposed.
    raw_body: bytes


@dataclass
class MaterialLightProperty:
    property_name: str
    parameter_type: int
    parameter_flags: int


@dataclass
class MaterialTexture:
    texture_name: str
    texture_path: str


@dataclass
class DirectXMaterial:
    shader_fx_path: str
    shader_technique_index: int
    textures: list[MaterialTexture]
    light_properties: list[MaterialLightProperty]
    float_attributes: list[NodeAttributeFloat]
    integer_attributes: list[NodeAttributeInteger]
    shader_pass_index: int
    vec4_attributes: list[NodeAttributeVec4]
    shader_flags: int


@dataclass
class MaterialNode:
    material_type: int
    node_name: str
    material_name: str
    material_attributes: NodeAttributes
    default_material: DefaultMaterial | None
    directx_material: DirectXMaterial | None


@dataclass
class Header:
    file_format: bytes
    exporter_version: float
    feature_flags: int
    plugin: str
    details: str


@dataclass
class SceneBlockData:
    format_compatibility_version: int
    object_types_count: int
    lights_count: int
    cameras_count: int
    rigid_models_count: int
    total_scene_vertex_count: int
    weighted_models_count: int
    lines_count: int
    dummies_count: int
    materials_count: int
    total_scene_triangle_count: int
    instances_count: int
    scene_bbox_and_world_matrix: bytes


@dataclass
class TimelineBlockData:
    frame_rate_fps: int
    start_frame_time: float
    end_frame_time: float
    track_metadata: bytes


@dataclass
class MorphSplineTrack:
    track_id1: int
    track_id2: int
    track_id3: int
    keyframe_values: list[float]
    vertex_indices: list[int]


@dataclass
class MorphAndSplineBlockData:
    morph_track_flags: int
    tracks: list[MorphSplineTrack]


@dataclass
class CS2Document:
    header: Header
    scene_block: SceneBlockData
    timeline_block: TimelineBlockData
    morph_block: MorphAndSplineBlockData
    cameras: list[CameraNode]
    rigid_models: list[RigidModelNode]
    weighted_models: list[WeightedModelNode]
    lines: list[LineNode]
    dummies: list[DummyNode]
    scene_root: SceneRootNode
    materials: list[MaterialNode]
    instances: list[InstanceNode]


NODE_TYPE_LIGHT = 5
NODE_TYPE_CAMERA = 6
NODE_TYPE_RIGID_MODEL = 7
NODE_TYPE_WEIGHTED_MODEL = 10
NODE_TYPE_LINE = 11
NODE_TYPE_SCENE_ROOT = 12
NODE_TYPE_MATERIAL = 13
NODE_TYPE_INSTANCE_NO_MATERIAL = 16
NODE_TYPE_DUMMY = 17
NODE_TYPE_INSTANCE_OVERRIDE_MATERIAL = 18

MATERIAL_TYPE_DEFAULT = 0
MATERIAL_TYPE_DIRECTX = 1
