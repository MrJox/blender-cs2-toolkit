import struct
from dataclasses import dataclass, field
from binary.reader import BinaryReader

Vec3 = tuple[float, float, float]


@dataclass
class CS2ParsedHeader:
    version: int
    bounding_box: tuple[Vec3, Vec3]
    flag_name: str
    flag_transform: list[float]


@dataclass
class CS2ParsedCollision:
    name: str
    node_index: int
    unk2: int
    vertices: list[Vec3]
    faces_bytes: bytes
    face_count: int


@dataclass
class CS2ParsedSpecialItem:
    closed: "CS2ParsedCollision"
    ajar: "CS2ParsedCollision"


@dataclass
class CS2ParsedLine:
    name: str
    vertices: list[Vec3]
    line_type: int


@dataclass
class CS2ParsedPipe:
    name: str
    vertices: list[Vec3]
    pipe_type: int


@dataclass
class CS2ParsedNogoZone:
    points: list[tuple[float, float, int]]


@dataclass
class CS2ParsedPlatformPolygon:
    normal: Vec3
    vertices: list[Vec3]
    is_ground: bool


@dataclass
class CS2ParsedPlatform:
    polygons: list[CS2ParsedPlatformPolygon]
    parent_index: int


@dataclass
class CS2ParsedTechNode:
    name: str
    transform: list[float]


@dataclass
class CS2ParsedFileRef:
    key: str
    name: str
    matrix: list[float]
    unk: int


@dataclass
class CS2ParsedSoftCollision:
    name: str
    transform: list[float]
    cylinder_id: int
    radius: float
    height: float


@dataclass
class CS2ParsedEFLine:
    name: str
    action: int
    start: Vec3
    end: Vec3
    direction: Vec3
    parent: int


@dataclass
class CS2ParsedDestruct:
    name: str
    index: int
    collision: CS2ParsedCollision
    windows_count: int = 0
    doors_count: int = 0
    windows: list[CS2ParsedCollision] = field(default_factory=list)
    doors: list[CS2ParsedCollision] = field(default_factory=list)
    special_items: list[CS2ParsedSpecialItem] = field(default_factory=list)
    lines: list[CS2ParsedLine] = field(default_factory=list)
    pipes: list[CS2ParsedPipe] = field(default_factory=list)
    nogo_zones: list[CS2ParsedNogoZone] = field(default_factory=list)
    platform: CS2ParsedPlatform | None = None
    bounding_box: tuple[Vec3, Vec3] | None = None
    cannons_count: int = 0
    arrow_emitters_count: int = 0
    arrow_emitters: list[CS2ParsedTechNode] = field(default_factory=list)
    docking_points_count: int = 0
    soft_collisions: list[CS2ParsedSoftCollision] = field(default_factory=list)
    hit_points_threshold: int = 0
    file_refs: list[CS2ParsedFileRef] = field(default_factory=list)
    eflines: list[CS2ParsedEFLine] = field(default_factory=list)
    vfx1_count: int = 0
    vfx2_count: int = 0
    attachments1_count: int = 0
    attachments2_count: int = 0


@dataclass
class CS2ParsedPiece:
    name: str
    place_name: str
    place_transform: list[float]
    parent_index: int
    destructs: list[CS2ParsedDestruct] = field(default_factory=list)


@dataclass
class CS2ParsedData:
    header: CS2ParsedHeader
    pieces: list[CS2ParsedPiece] = field(default_factory=list)


def _read_collision3d(r: BinaryReader) -> CS2ParsedCollision:
    name = r.utf16_string()
    node_index = r.u32()
    unk2 = r.u32()
    vertex_count = r.u32()
    vertices = [r.vec3() for _ in range(vertex_count)]
    face_count = r.u32()
    faces_bytes = r.raw(face_count * 81)
    return CS2ParsedCollision(
        name=name,
        node_index=node_index,
        unk2=unk2,
        vertices=vertices,
        faces_bytes=faces_bytes,
        face_count=face_count,
    )


class CS2ParsedReader:
    @staticmethod
    def read_bytes(data: bytes) -> CS2ParsedData:
        r = BinaryReader(data)
        version = r.u32()
        bbox = r.bounding_box()
        flag_name = r.utf16_string()
        flag_transform = [r.f32() for _ in range(16)]
        reserved = r.u32()
        assert reserved == 0

        header = CS2ParsedHeader(
            version=version,
            bounding_box=bbox,
            flag_name=flag_name,
            flag_transform=flag_transform,
        )

        piece_count = r.u32()
        pieces: list[CS2ParsedPiece] = []

        for p_idx in range(piece_count):
            p_name = r.utf16_string()
            place_name = r.utf16_string()
            place_transform = [r.f32() for _ in range(16)]
            parent_idx = r.u32()
            destruct_count = r.u32()

            destructs: list[CS2ParsedDestruct] = []
            for d_idx in range(destruct_count):
                d_name = r.utf16_string()
                d_index = r.u32()

                # 1. collision3d
                collision = _read_collision3d(r)

                # 2. windows
                num_windows = r.u32()
                windows = [_read_collision3d(r) for _ in range(num_windows)]

                # 3. doors
                num_doors = r.u32()
                doors = [_read_collision3d(r) for _ in range(num_doors)]

                # 4. special - toggle_items, a pair of collision meshes per item. This is what a
                # gate compiles to: its closed volume and its ajar volume, in that order.
                num_special = r.u32()
                special_items: list[CS2ParsedSpecialItem] = []
                for _ in range(num_special):
                    first = _read_collision3d(r)
                    second = _read_collision3d(r)
                    sp_res1 = r.u32(); assert sp_res1 == 0
                    sp_res2 = r.u32(); assert sp_res2 == 0
                    special_items.append(CS2ParsedSpecialItem(closed=first, ajar=second))

                # 5. lines
                num_lines = r.u32()
                lines: list[CS2ParsedLine] = []
                for _ in range(num_lines):
                    l_name = r.utf16_string()
                    l_nv = r.u32()
                    l_verts = [r.vec3() for _ in range(l_nv)]
                    l_type = r.u32()
                    lines.append(CS2ParsedLine(name=l_name, vertices=l_verts, line_type=l_type))

                # 6. pipes
                num_pipes = r.u32()
                pipes: list[CS2ParsedPipe] = []
                for _ in range(num_pipes):
                    p_pipe_name = r.utf16_string()
                    p_nv = r.u32()
                    p_verts = [r.vec3() for _ in range(p_nv)]
                    p_type = r.u32()
                    pipes.append(CS2ParsedPipe(name=p_pipe_name, vertices=p_verts, pipe_type=p_type))

                # 7. nogo_zones
                num_nogo = r.u32()
                nogo_zones: list[CS2ParsedNogoZone] = []
                for _ in range(num_nogo):
                    nl = r.u32()
                    pts = [(r.f32(), r.f32(), r.u32()) for _ in range(nl)]
                    nogo_zones.append(CS2ParsedNogoZone(points=pts))

                # 8. Platform
                num_poly = r.u32()
                polygons: list[CS2ParsedPlatformPolygon] = []
                for _ in range(num_poly):
                    norm = r.vec3()
                    pv_cnt = r.u32()
                    p_verts = [r.vec3() for _ in range(pv_cnt)]
                    r.raw(1)
                    is_ground = r.raw(1)[0] != 0
                    r.raw(1)
                    polygons.append(CS2ParsedPlatformPolygon(normal=norm, vertices=p_verts, is_ground=is_ground))
                plat_parent = r.u32()
                platform = CS2ParsedPlatform(polygons=polygons, parent_index=plat_parent)

                # 9. destruct bbox, THEN hit_points_threshold (confirmed real order is
                # bbox-then-threshold, not the reverse the format spec documents - verified via a
                # real BOB compile: reading in the documented order produced a nonsense
                # hit_points_threshold whose bits were exactly a plausible-looking bounding-box
                # float, and a clean hit_points_threshold=0 only appears when read after the bbox).
                d_bbox = r.bounding_box()
                hit_points_threshold = r.u32()

                # 10. arrow_emitters, THEN cannons - also confirmed swapped from the documented
                # order via a real sample (gondor_fort_tower_C_straight) containing 8 real arrow
                # emitters that only decode correctly in this order; the previous order plus a
                # missing hit_points_threshold read happened to cancel out for buildings with no
                # cannons and hit_points_threshold == 0, which is why this went unnoticed before.
                num_arrow = r.u32()
                arrow_emitters: list[CS2ParsedTechNode] = []
                for _ in range(num_arrow):
                    ae_name = r.utf16_string()
                    ae_transform = list(struct.unpack("<16f", r.raw(64)))
                    arrow_emitters.append(CS2ParsedTechNode(name=ae_name, transform=ae_transform))

                # 11. cannons
                num_cannons = r.u32()
                for _ in range(num_cannons):
                    r.utf16_string(); r.raw(64)

                # 12. soft_collisions, THEN docking_points - also confirmed swapped from the
                # documented order (same investigation as the arrow_emitters/cannons swap above):
                # a real sample's soft_collision entry only decodes correctly in this order.
                num_soft = r.u32()
                soft_collisions: list[CS2ParsedSoftCollision] = []
                for _ in range(num_soft):
                    sc_name = r.utf16_string()
                    sc_transform = list(struct.unpack("<16f", r.raw(64)))
                    sc_id = r.u16()
                    sc_radius = r.f32()
                    sc_height = r.f32()
                    soft_collisions.append(
                        CS2ParsedSoftCollision(
                            name=sc_name,
                            transform=sc_transform,
                            cylinder_id=sc_id,
                            radius=sc_radius,
                            height=sc_height,
                        )
                    )

                # 13. docking_points
                num_docking = r.u32()
                for _ in range(num_docking):
                    r.utf16_string(); r.raw(64)

                # The format spec documents an "unknown_array_1" reserved-must-be-0 field here,
                # before file_refs. It doesn't actually exist for version 13: confirmed on a real
                # sample (gondor_fort_tower_C_straight) whose "reserved" value here was 4, and the
                # very next bytes decoded as a well-formed unicode_string - reading it directly as
                # num_file_refs gave exactly 4, matching this building's 4 real torch_sconce file
                # references from its raw .CS2. Every previously-tested file simply had zero file
                # references at this position, which is why this went unnoticed - the assert was
                # never exercised against real non-zero data.
                num_unk_soft = 0

                # 15. file_refs (num_fileref IS the u32 documented as "unknown_array_1" above)
                num_fileref = r.u32()
                file_refs: list[CS2ParsedFileRef] = []
                for _ in range(num_fileref):
                    f_key = r.utf16_string()
                    f_name = r.utf16_string()
                    f_mat = [r.f32() for _ in range(16)]
                    f_unk = r.u16()
                    file_refs.append(CS2ParsedFileRef(key=f_key, name=f_name, matrix=f_mat, unk=f_unk))

                # 16. eflines
                num_efline = r.u32()
                eflines: list[CS2ParsedEFLine] = []
                for _ in range(num_efline):
                    ef_name = r.utf16_string()
                    ef_action = r.u32()
                    ef_start = r.vec3()
                    ef_end = r.vec3()
                    ef_dir = r.vec3()
                    ef_parent = r.u32()
                    eflines.append(
                        CS2ParsedEFLine(
                            name=ef_name,
                            action=ef_action,
                            start=ef_start,
                            end=ef_end,
                            direction=ef_dir,
                            parent=ef_parent,
                        )
                    )

                # 17. reserved_2
                res2 = r.u32()
                assert res2 == 0

                vfx1_count = 0
                vfx2_count = 0
                att1_count = 0
                att2_count = 0

                if version == 13:
                    vfx1_count = r.u32()
                    for _ in range(vfx1_count):
                        r.utf16_string(); r.raw(64)
                    vfx2_count = r.u32()
                    for _ in range(vfx2_count):
                        r.utf16_string(); r.raw(64)
                    att1_count = r.u32()
                    for _ in range(att1_count):
                        cnt = r.u32(); r.raw(cnt * 2)
                    att2_count = r.u32()
                    for _ in range(att2_count):
                        cnt = r.u32(); r.raw(cnt * 2)
                    while r.remaining() >= 2 and struct.unpack_from("<H", r.data, r.offset)[0] == 0:
                        r.u16()

                destructs.append(
                    CS2ParsedDestruct(
                        name=d_name,
                        index=d_index,
                        collision=collision,
                        windows_count=num_windows,
                        doors_count=num_doors,
                        windows=windows,
                        doors=doors,
                        special_items=special_items,
                        lines=lines,
                        pipes=pipes,
                        nogo_zones=nogo_zones,
                        platform=platform,
                        bounding_box=d_bbox,
                        cannons_count=num_cannons,
                        arrow_emitters_count=num_arrow,
                        arrow_emitters=arrow_emitters,
                        docking_points_count=num_docking,
                        soft_collisions=soft_collisions,
                        hit_points_threshold=hit_points_threshold,
                        file_refs=file_refs,
                        eflines=eflines,
                        vfx1_count=vfx1_count,
                        vfx2_count=vfx2_count,
                        attachments1_count=att1_count,
                        attachments2_count=att2_count,
                    )
                )

            if version == 12 and r.remaining() >= 4 and struct.unpack_from("<I", r.data, r.offset)[0] == 0:
                piece_res = r.u32()
                assert piece_res == 0

            pieces.append(
                CS2ParsedPiece(
                    name=p_name,
                    place_name=place_name,
                    place_transform=place_transform,
                    parent_index=parent_idx,
                    destructs=destructs,
                )
            )

        while r.remaining() >= 2 and struct.unpack_from("<H", r.data, r.offset)[0] == 0:
            r.u16()

        assert r.at_end(), f"Extra bytes remaining: {r.remaining()}"
        return CS2ParsedData(header=header, pieces=pieces)

    @classmethod
    def read_file(cls, filepath: str) -> CS2ParsedData:
        with open(filepath, "rb") as f:
            data = f.read()
        return cls.read_bytes(data)
