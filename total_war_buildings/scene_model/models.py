from dataclasses import dataclass, field

Vec2 = tuple[float, float]
Vec3 = tuple[float, float, float]
Vec4 = tuple[float, float, float, float]


@dataclass
class MeshVertex:
    position: Vec3
    normal: Vec3
    uv: Vec2
    color: Vec4 = (1.0, 1.0, 1.0, 1.0)
    uv2: Vec2 | None = None


@dataclass
class MeshTriangle:
    indices: tuple[int, int, int]
    material_index: int = 0


@dataclass
class MeshData:
    vertices: list[MeshVertex]
    triangles: list[MeshTriangle]


@dataclass
class MaterialDef:
    name: str
    shader_type: str
    diffuse_texture_path: str = ""
    normal_texture_path: str = ""
    mask_texture_path: str = ""
    dirtmap_texture_path: str = ""
    dirtmask_texture_path: str = ""
    gloss_texture_path: str = ""
    level_texture_path: str = ""
    specular_texture_path: str = ""
    tint_mask_texture_paths: tuple[str, str, str] = ("", "", "")
    decal_texture_paths: tuple[str, str, str] = ("", "", "")
    decal_dirtmap_texture_paths: tuple[str, str] = ("", "")
    tint_colours: tuple[tuple[float, float, float], ...] = (
        (0.5 ** 2.2, 0.1 ** 2.2, 0.1 ** 2.2),
        (0.3 ** 2.2, 0.6 ** 2.2, 0.5 ** 2.2),
        (0.5 ** 2.2, 0.2 ** 2.2, 0.1 ** 2.2),
    )
    faction_colouring: bool = True
    dirtmap_tile_u: float = 4.0
    dirtmap_tile_v: float = 4.0
    dirt_uv_offset_u: float = 0.5
    dirt_uv_offset_v: float = 0.5
    alpha_mode: int = -1
    uv2_layer_name: str = ""


@dataclass
class LodMesh:
    lod_index: int
    mesh: MeshData
    materials: list[MaterialDef] = field(default_factory=list)

    @property
    def material(self) -> MaterialDef:
        return self.materials[0] if self.materials else MaterialDef(name="default", shader_type="default")


@dataclass
class CollisionMesh:
    mesh: MeshData


@dataclass
class SoftCollisionMesh:
    mesh: MeshData


@dataclass
class PlatformMesh:
    variation_index: int
    mesh: MeshData


@dataclass
class PlatformGroundMesh:
    mesh: MeshData


@dataclass
class FileReference:
    reference_name: str
    transform_translation: Vec3
    transform_rotation: Vec4
    mesh: MeshData | None = None
    materials: list[MaterialDef] = field(default_factory=list)

    @property
    def material(self) -> MaterialDef:
        return self.materials[0] if self.materials else MaterialDef(name="default", shader_type="default")


@dataclass
class LineFeature:
    line_type: str
    variation_index: int
    points: list[Vec3]
    closed: bool = False


@dataclass
class RegionZone:
    variation_index: int
    points: list[Vec3]
    corner_points: list[Vec3] = field(default_factory=list)


@dataclass
class EFLine:
    variation_index: int
    action: str
    start: Vec3
    end: Vec3
    direction: Vec3


@dataclass
class DockingLine:
    variation_index: int
    start: Vec3
    end: Vec3
    direction: Vec3


@dataclass
class ArrowEmitter:
    variation_index: int
    mesh: MeshData
    transform_translation: Vec3
    transform_rotation: Vec4


@dataclass
class HeightMapMesh:
    variation_index: int
    mesh: MeshData


@dataclass
class Flag:
    mesh: MeshData
    transform_translation: Vec3
    transform_rotation: Vec4


@dataclass
class AnimationKeyframes:
    # Independent translation/rotation tracks, exactly mirroring binary.cs2_structures.
    # SceneNodeAnimTrack (which this converts into 1:1) - a real sample keys them independently and
    # with different key counts, so they're never zipped together. A single-frame track (times=[0.0])
    # is the valid, common "authored but not actually animated" case - real ground truth has both.
    translation_times: list[float]
    translations: list[Vec3]
    rotation_times: list[float]
    rotations: list[Vec4]


@dataclass
class DestructionAnimMesh:
    # A single destruction debris chunk - its own local-space mesh plus the keyframe track that
    # flies/falls it away. Node name is shared across every chunk in the same piece/destruct level
    # (no per-object numbering, confirmed from real ground truth), so unlike LodMesh there is no
    # variation_index here - array order is the only thing that tells two chunks apart.
    mesh: MeshData
    keyframes: AnimationKeyframes
    materials: list[MaterialDef] = field(default_factory=list)

    @property
    def material(self) -> MaterialDef:
        return self.materials[0] if self.materials else MaterialDef(name="default", shader_type="default")


@dataclass
class GateAnimMesh:
    # gate_anim_kind matches props.properties.GATE_ANIM_KIND_ITEMS: GATE_OPENING, GATE_CLOSING,
    # GATE_CLOSED_DESTRUCT, GATE_OPEN_DESTRUCT.
    gate_anim_kind: str
    mesh: MeshData
    keyframes: AnimationKeyframes
    materials: list[MaterialDef] = field(default_factory=list)

    @property
    def material(self) -> MaterialDef:
        return self.materials[0] if self.materials else MaterialDef(name="default", shader_type="default")


@dataclass
class DestructLevel:
    destruct_index: int
    lod_meshes: list[LodMesh] = field(default_factory=list)
    collision_mesh: CollisionMesh | None = None
    soft_collision_mesh: SoftCollisionMesh | None = None
    platform_meshes: list[PlatformMesh] = field(default_factory=list)
    platform_ground_mesh: PlatformGroundMesh | None = None
    file_references: list[FileReference] = field(default_factory=list)
    line_features: list[LineFeature] = field(default_factory=list)
    ef_lines: list[EFLine] = field(default_factory=list)
    docking_lines: list[DockingLine] = field(default_factory=list)
    arrow_emitters: list[ArrowEmitter] = field(default_factory=list)
    height_map_meshes: list[HeightMapMesh] = field(default_factory=list)
    gate_closed_collision: CollisionMesh | None = None
    gate_ajar_collision: CollisionMesh | None = None
    gate_closed_lods: list[LodMesh] = field(default_factory=list)
    gate_open_lods: list[LodMesh] = field(default_factory=list)
    destruction_anim_meshes: list[DestructionAnimMesh] = field(default_factory=list)
    gate_anim_meshes: list[GateAnimMesh] = field(default_factory=list)
    boiling_oil_collision: CollisionMesh | None = None
    boiling_oil_lods: list[LodMesh] = field(default_factory=list)


@dataclass
class Piece:
    piece_index: int
    destruct_levels: list[DestructLevel] = field(default_factory=list)
    damage_parent_piece_index: int | None = None


@dataclass
class BuildingAsset:
    name: str
    asset_type: str
    pieces: list[Piece] = field(default_factory=list)
    region_zones: list[RegionZone] = field(default_factory=list)
    flag: Flag | None = None
