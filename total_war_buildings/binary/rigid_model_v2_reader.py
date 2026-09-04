from .reader import BinaryReader
from . import rigid_model_v2_structures as s


def _byte_vector(r: BinaryReader) -> s.Vec3:
    x, y, z = r.u8(), r.u8(), r.u8()
    r.u8()
    return ((x - 127.0) / 127.0, (y - 127.0) / 127.0, (z - 127.0) / 127.0)


def _swapped_byte_vector(r: BinaryReader) -> s.Vec3:
    z, y, x = r.u8(), r.u8(), r.u8()
    r.u8()
    return ((x - 127.0) / 127.0, (y - 127.0) / 127.0, (z - 127.0) / 127.0)


def _matrix_43(r: BinaryReader) -> s.Matrix43:
    return (r.vec4(), r.vec4(), r.vec4())


def read_standard_vertex(r: BinaryReader) -> s.Vertex:
    position = (r.f16(), r.f16(), r.f16())
    r.f16()
    uv = (r.f16(), r.f16())
    uv2 = (r.f16(), r.f16())
    # Only this vertex format stores the packed byte triples z-first; the weighted ones do not.
    # Measured against triangle face normals on real samples, not taken from the spec.
    normal = _swapped_byte_vector(r)
    tangent = _swapped_byte_vector(r)
    binormal = _swapped_byte_vector(r)
    colour = (r.u8(), r.u8(), r.u8(), r.u8())
    return s.Vertex(
        position=position,
        uv=uv,
        uv2=uv2,
        normal=normal,
        tangent=tangent,
        binormal=binormal,
        colour=colour,
    )


def read_weighted_2_bone_vertex(r: BinaryReader) -> s.Vertex:
    position = (r.f16(), r.f16(), r.f16())
    r.f16()
    bone_0, bone_1, weight_0 = r.u8(), r.u8(), r.u8()
    # The 4th byte holds weight 1 in some real files and zero in others, sometimes within the
    # same file, so the second weight is derived rather than read.
    r.u8()
    normal = _byte_vector(r)
    uv = (r.f16(), r.f16())
    binormal = _byte_vector(r)
    tangent = _byte_vector(r)
    return s.Vertex(
        position=position,
        uv=uv,
        normal=normal,
        tangent=tangent,
        binormal=binormal,
        bone_indices=(bone_0, bone_1),
        bone_weights=(weight_0 / 255.0, (255 - weight_0) / 255.0),
    )


def read_weighted_4_bone_vertex(r: BinaryReader) -> s.Vertex:
    position = (r.f16(), r.f16(), r.f16())
    r.f16()
    bones = (r.u8(), r.u8(), r.u8(), r.u8())
    weights = (r.u8() / 255.0, r.u8() / 255.0, r.u8() / 255.0, r.u8() / 255.0)
    normal = _byte_vector(r)
    uv = (r.f16(), r.f16())
    binormal = _byte_vector(r)
    tangent = _byte_vector(r)
    return s.Vertex(
        position=position,
        uv=uv,
        normal=normal,
        tangent=tangent,
        binormal=binormal,
        bone_indices=bones,
        bone_weights=weights,
    )


def read_tree_vertex(r: BinaryReader) -> s.Vertex:
    # Every field is a float16 quad, so unlike the rigid formats there is no packed-byte triple and
    # no axis swap: the stone models' vertex normals agree with their own face normals (mean dot
    # +0.95 over a closed solid) when read straight through in position order.
    position0 = (r.f16(), r.f16(), r.f16())
    r.f16()
    position = (r.f16(), r.f16(), r.f16())
    r.f16()
    normal = (r.f16(), r.f16(), r.f16())
    r.f16()
    tangent = (r.f16(), r.f16(), r.f16())
    r.f16()
    binormal = (r.f16(), r.f16(), r.f16())
    r.f16()
    uv = (r.f16(), r.f16())
    weights = (r.f16(), r.f16(), r.f16(), r.f16())
    colour = tuple(min(255, max(0, round(r.f16() * 255.0))) for _ in range(4))
    return s.Vertex(
        position=position,
        uv=uv,
        normal=normal,
        tangent=tangent,
        binormal=binormal,
        colour=colour,
        tree_position0=position0,
        tree_weights=weights,
    )


def read_billboard_vertex(r: BinaryReader) -> s.Vertex:
    position = (r.f16(), r.f16(), r.f16())
    r.f16()
    uv = (r.f16(), r.f16())
    return s.Vertex(position=position, uv=uv, normal=(0.0, 0.0, 0.0), tangent=(0.0, 0.0, 0.0), binormal=(0.0, 0.0, 0.0))


VERTEX_READERS = {
    s.VERTEX_STANDARD_RIGID: read_standard_vertex,
    s.VERTEX_WEIGHTED_2_BONES: read_weighted_2_bone_vertex,
    s.VERTEX_WEIGHTED_4_BONES: read_weighted_4_bone_vertex,
    s.VERTEX_TREE: read_tree_vertex,
    s.VERTEX_BILLBOARD: read_billboard_vertex,
}


def read_mesh_header_v5(r: BinaryReader) -> s.MeshHeaderV5:
    vertex_format = r.u16()
    name = r.fixed_string(32)
    texture_directory = r.fixed_string(256)
    filters = r.fixed_string(256)
    # Struct padding realigning the transform block after the uint16 vertex format; the
    # published spec's field offsets omit it.
    r.raw(2)
    pivot = r.vec3()
    matrix1 = _matrix_43(r)
    matrix2 = _matrix_43(r)
    matrix3 = _matrix_43(r)
    matrix_index = r.i32()
    parent_matrix_index = r.i32()
    attachment_count = r.u32()
    texture_count = r.u32()
    string_param_count = r.u32()
    float_param_count = r.u32()
    int_param_count = r.u32()
    vec4_param_count = r.u32()
    r.raw(124)

    attachment_points = []
    for _ in range(attachment_count):
        attachment_points.append(
            s.AttachmentPoint(name=r.fixed_string(32), transform=_matrix_43(r), bone_index=r.i32())
        )

    textures = []
    for _ in range(texture_count):
        textures.append(s.TextureEntry(texture_id=r.i32(), path=r.fixed_string(256)))

    string_params = [s.StringParam(param_id=r.i32(), value=r.length_prefixed_ascii()) for _ in range(string_param_count)]
    float_params = [s.FloatParam(param_id=r.i32(), value=r.f32()) for _ in range(float_param_count)]
    int_params = [s.IntParam(param_id=r.i32(), value=r.i32()) for _ in range(int_param_count)]
    vec4_params = [s.Vec4Param(param_id=r.i32(), value=r.vec4()) for _ in range(vec4_param_count)]

    return s.MeshHeaderV5(
        vertex_format=vertex_format,
        name=name,
        texture_directory=texture_directory,
        filters=filters,
        pivot=pivot,
        matrix1=matrix1,
        matrix2=matrix2,
        matrix3=matrix3,
        matrix_index=matrix_index,
        parent_matrix_index=parent_matrix_index,
        attachment_points=attachment_points,
        textures=textures,
        string_params=string_params,
        float_params=float_params,
        int_params=int_params,
        vec4_params=vec4_params,
    )


def read_mesh(data: bytes, mesh_offset: int) -> s.Mesh:
    r = BinaryReader(data)
    r.offset = mesh_offset
    shader_flags = r.u16()
    render_flags = r.u16()
    section_size = r.u32()
    vertex_offset = r.u32()
    vertex_count = r.u32()
    index_offset = r.u32()
    index_count = r.u32()
    bounding_box = r.bounding_box()
    shader_params_raw = r.raw(32)
    lighting_constants_name = shader_params_raw[:12].split(b"\x00", 1)[0].decode("latin-1")

    material_raw = data[mesh_offset + s.COMMON_MESH_HEADER_SIZE : mesh_offset + vertex_offset]
    material = None
    if shader_flags in s.MESH_HEADER_V5_SHADERS and len(material_raw) >= s.MESH_HEADER_V5_SIZE:
        material = read_mesh_header_v5(BinaryReader(material_raw))
    vertex_format = material.vertex_format if material else s.DEFAULT_VERTEX_FORMAT_BY_SHADER.get(shader_flags)
    vertices_raw = data[mesh_offset + vertex_offset : mesh_offset + index_offset]
    vertex_stride = len(vertices_raw) // vertex_count if vertex_count else 0

    # The projected-decal shaders carry a 16-byte vertex the spec does not describe, so decode
    # only when the file's own stride agrees with the declared format.
    vertices: list[s.Vertex] = []
    vertex_reader = VERTEX_READERS.get(vertex_format)
    if vertex_reader is not None and vertex_stride == s.VERTEX_SIZES.get(vertex_format):
        r.offset = mesh_offset + vertex_offset
        vertices = [vertex_reader(r) for _ in range(vertex_count)]

    r.offset = mesh_offset + index_offset
    indices = [r.u16() for _ in range(index_count)]

    return s.Mesh(
        shader_flags=shader_flags,
        render_flags=render_flags,
        section_size=section_size,
        vertex_count=vertex_count,
        index_count=index_count,
        bounding_box=bounding_box,
        lighting_constants_name=lighting_constants_name,
        shader_params_raw=shader_params_raw,
        material=material,
        material_raw=material_raw,
        vertex_format=vertex_format,
        vertex_stride=vertex_stride,
        vertices=vertices,
        vertices_raw=vertices_raw,
        indices=indices,
    )


def read_rigid_model_v2(data: bytes) -> s.RigidModelV2:
    r = BinaryReader(data)
    signature = r.raw(4)
    if signature != s.FILE_SIGNATURE:
        raise ValueError(f"not a rigid_model_v2 file: signature {signature!r}")
    version = r.u32()
    if version != s.FILE_VERSION_ATTILA:
        raise ValueError(f"unsupported rigid_model_v2 version {version}")
    lod_count = r.u32()
    bone_table_name = r.fixed_string(128)

    lod_headers = []
    for _ in range(lod_count):
        mesh_count = r.u32()
        total_vertex_size = r.u32()
        total_index_size = r.u32()
        first_mesh_offset = r.u32()
        camera_distance = r.f32()
        lod_headers.append((mesh_count, total_vertex_size, total_index_size, first_mesh_offset, camera_distance))

    lods = []
    for mesh_count, total_vertex_size, total_index_size, first_mesh_offset, camera_distance in lod_headers:
        meshes = []
        mesh_offset = first_mesh_offset
        for _ in range(mesh_count):
            mesh = read_mesh(data, mesh_offset)
            meshes.append(mesh)
            mesh_offset += mesh.section_size
        lods.append(
            s.Lod(
                camera_distance=camera_distance,
                total_vertex_size=total_vertex_size,
                total_index_size=total_index_size,
                meshes=meshes,
            )
        )

    return s.RigidModelV2(signature=signature, version=version, bone_table_name=bone_table_name, lods=lods)
