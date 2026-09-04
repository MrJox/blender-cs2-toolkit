from .writer import BinaryWriter
from . import cs2_structures as s


def write_node_attributes(w: BinaryWriter, attrs: s.NodeAttributes) -> None:
    w.u32(len(attrs.strings))
    for a in attrs.strings:
        w.utf16_string(a.name)
        w.u32(1)
        w.utf16_string(a.value)

    w.u32(len(attrs.integers))
    for a in attrs.integers:
        w.utf16_string(a.name)
        w.u32(a.interpolation_mode)
        w.u32(8)
        w.u32(a.num_keys)
        w.u32(a.start_frame)
        w.u32(a.end_frame)
        w.u32(a.loop_flags)
        w.u32(a.reserved_flags)
        w.u32(a.value)

    w.u32(len(attrs.floats))
    for a in attrs.floats:
        w.utf16_string(a.name)
        w.u32(a.interpolation_mode)
        w.u32(0)
        w.u32(a.num_keys)
        w.u32(a.start_frame)
        w.u32(a.end_frame)
        w.u32(a.loop_flags)
        w.u32(a.reserved_flags)
        w.f32(a.value)

    w.u32(len(attrs.vec3s))
    for a in attrs.vec3s:
        w.utf16_string(a.name)
        w.u32(a.interpolation_mode)
        w.u32(3)
        w.u32(a.num_keys)
        w.u32(a.start_frame)
        w.u32(a.end_frame)
        w.u32(a.loop_flags)
        w.u32(a.reserved_flags)
        w.vec3(a.value)

    w.u32(len(attrs.vec4s))
    for a in attrs.vec4s:
        w.utf16_string(a.name)
        w.u32(a.interpolation_mode)
        w.u32(9)
        w.u32(a.num_keys)
        w.u32(a.start_frame)
        w.u32(a.end_frame)
        w.u32(a.loop_flags)
        w.u32(a.reserved_flags)
        w.vec4(a.value)


def write_line_data(w: BinaryWriter, line: s.LineData) -> None:
    w.u32(len(line.vertices))
    for v in line.vertices:
        w.vec3(v)
    w.u32(len(line.segments))
    for seg in line.segments:
        w.u32(seg.start_vertex_index)
        w.u32(seg.end_vertex_index)


def write_geometry_chunk_common(w: BinaryWriter, chunk: s.GeometryChunkCommon) -> None:
    w.fixed_bytes(chunk.header_padding, 12)
    w.float_array(chunk.bounding_box_extent_floats)
    w.u32(len(chunk.bounding_boxes))
    for bbox in chunk.bounding_boxes:
        w.bounding_box(bbox[0], bbox[1])
    w.u32(len(chunk.lines))
    for line in chunk.lines:
        write_line_data(w, line)


def write_rigid_vertex(w: BinaryWriter, v: s.RigidVertex) -> None:
    w.vec3(v.position)
    w.vec3(v.normal)
    w.vec4(v.color)
    w.u32(len(v.tex_coords))
    for uv in v.tex_coords:
        w.vec3(uv)
    w.f32(v.vertex_ao_or_morph_weight)


def write_weighted_vertex(w: BinaryWriter, v: s.WeightedVertex) -> None:
    w.vec3(v.position)
    w.vec3(v.normal)
    w.vec4(v.color)
    w.u32(len(v.tex_coords))
    for uv in v.tex_coords:
        w.vec3(uv)
    w.f32(v.vertex_ao_or_morph_weight)
    w.u32(len(v.bone_weights))
    for bw in v.bone_weights:
        w.u32(bw.bone_id)
        w.f32(bw.weight)
    w.vec3(v.unskinned_position)
    w.vec3(v.unskinned_normal)


def write_submeshes(w: BinaryWriter, submeshes: list[s.SubMesh]) -> None:
    w.u32(len(submeshes))
    for sm in submeshes:
        w.u32(len(sm.triangles))
        for tri in sm.triangles:
            w.u32(tri[0])
            w.u32(tri[1])
            w.u32(tri[2])
        w.i32(sm.material_id)


def write_rigid_geometry_chunk(w: BinaryWriter, chunk: s.RigidGeometryChunk) -> None:
    write_geometry_chunk_common(w, chunk)
    w.u32(len(chunk.uvw_channel_ids))
    for uid in chunk.uvw_channel_ids:
        w.u32(uid)
    w.u32(len(chunk.vertices))
    for v in chunk.vertices:
        write_rigid_vertex(w, v)
    write_submeshes(w, chunk.submeshes)
    w.i32(chunk.vertex_color_channel_flags)


def write_weighted_geometry_chunk(w: BinaryWriter, chunk: s.WeightedGeometryChunk) -> None:
    write_geometry_chunk_common(w, chunk)
    w.u32(len(chunk.uvw_channel_ids))
    for uid in chunk.uvw_channel_ids:
        w.u32(uid)
    w.u32(len(chunk.vertices))
    for v in chunk.vertices:
        write_weighted_vertex(w, v)
    write_submeshes(w, chunk.submeshes)
    w.i32(chunk.vertex_color_channel_flags)


def write_line_geometry_chunk(w: BinaryWriter, chunk: s.LineGeometryChunk) -> None:
    write_geometry_chunk_common(w, chunk)
    w.i32(chunk.vertex_color_channel_flags)


def write_instance_geometry_chunk(w: BinaryWriter, chunk: s.InstanceGeometryChunk) -> None:
    write_geometry_chunk_common(w, chunk)
    w.u32(chunk.original_node_index)
    w.i32(chunk.vertex_color_channel_flags)
    if chunk.material_id is not None:
        w.u32(chunk.material_id)


def write_node_common_fields(w: BinaryWriter, node: s.NodeCommon) -> None:
    w.utf16_string(node.node_name)
    w.utf16_string(node.node_metadata_string)
    w.utf16_string(node.user_defined_properties)
    w.u32(node.node_index)
    write_node_attributes(w, node.attributes)


def _write_node_with_length_prefix(node_type: int, body_writer_fn) -> bytes:
    inner = BinaryWriter()
    inner.u32(node_type)
    body_writer_fn(inner)
    payload = inner.bytes()
    outer = BinaryWriter()
    outer.u32(len(payload) + 4)
    outer.raw(payload)
    return outer.bytes()


def write_rigid_model_node(node: s.RigidModelNode) -> bytes:
    def body(w: BinaryWriter) -> None:
        write_node_common_fields(w, node)
        w.u32(len(node.geometry_chunks))
        for chunk in node.geometry_chunks:
            write_rigid_geometry_chunk(w, chunk)

    return _write_node_with_length_prefix(s.NODE_TYPE_RIGID_MODEL, body)


def write_weighted_model_node(node: s.WeightedModelNode) -> bytes:
    def body(w: BinaryWriter) -> None:
        write_node_common_fields(w, node)
        w.u32(len(node.geometry_chunks))
        for chunk in node.geometry_chunks:
            write_weighted_geometry_chunk(w, chunk)

    return _write_node_with_length_prefix(s.NODE_TYPE_WEIGHTED_MODEL, body)


def write_line_node(node: s.LineNode) -> bytes:
    def body(w: BinaryWriter) -> None:
        write_node_common_fields(w, node)
        w.u32(len(node.geometry_chunks))
        for chunk in node.geometry_chunks:
            write_line_geometry_chunk(w, chunk)

    return _write_node_with_length_prefix(s.NODE_TYPE_LINE, body)


def write_instance_node(node: s.InstanceNode) -> bytes:
    node_type = s.NODE_TYPE_INSTANCE_OVERRIDE_MATERIAL if node.override_material else s.NODE_TYPE_INSTANCE_NO_MATERIAL

    def body(w: BinaryWriter) -> None:
        w.u32(node.leading_unknown)
        write_node_common_fields(w, node)
        w.u32(len(node.geometry_chunks))
        for chunk in node.geometry_chunks:
            write_instance_geometry_chunk(w, chunk)

    return _write_node_with_length_prefix(node_type, body)


def write_dummy_node(node: s.DummyNode) -> bytes:
    def body(w: BinaryWriter) -> None:
        write_node_common_fields(w, node)
        w.u32(node.geometry_data_count)

    return _write_node_with_length_prefix(s.NODE_TYPE_DUMMY, body)


def write_camera_node(node: s.CameraNode) -> bytes:
    def body(w: BinaryWriter) -> None:
        write_node_common_fields(w, node)
        w.fixed_bytes(node.camera_parameters, 144)

    return _write_node_with_length_prefix(s.NODE_TYPE_CAMERA, body)


def write_scene_node(w: BinaryWriter, node: s.SceneNode) -> None:
    w.utf16_string(node.name)
    w.u32(node.parent_index)
    w.vec4(node.default_scale_or_pivot)
    w.u32(len(node.anim.translation_frame_times))
    for t in node.anim.translation_frame_times:
        w.f32(t)
    w.u32(len(node.anim.translations))
    for t in node.anim.translations:
        w.vec3(t)
    w.fixed_bytes(node.anim.scale_track_or_bbox, 16)
    w.u32(len(node.anim.rotation_frame_times))
    for t in node.anim.rotation_frame_times:
        w.f32(t)
    w.u32(len(node.anim.rotations))
    for t in node.anim.rotations:
        w.vec4(t)
    w.i32(node.parent_node_index)
    w.utf16_string(node.target_linkage_name)
    write_node_attributes(w, node.attributes)


def write_scene_root_node(node: s.SceneRootNode) -> bytes:
    def body(w: BinaryWriter) -> None:
        w.u32(len(node.scene_nodes) + 1)
        w.utf16_string(node.node_name)
        w.i32(node.up_axis_orientation)
        w.i32(node.scene_unit_scale)
        w.fixed_bytes(node.scene_hierarchy_metadata, 84)
        w.utf16_string(node.info)
        w.i32(node.active_camera_index)
        w.i32(node.active_light_index)
        w.fixed_bytes(node.root_end_padding, 12)
        for sn in node.scene_nodes:
            write_scene_node(w, sn)

    return _write_node_with_length_prefix(s.NODE_TYPE_SCENE_ROOT, body)


def write_default_material(w: BinaryWriter, m: s.DefaultMaterial) -> None:
    w.raw(m.raw_body)


def write_directx_material(w: BinaryWriter, m: s.DirectXMaterial) -> None:
    w.utf16_string(m.shader_fx_path)
    w.u32(m.shader_technique_index)
    w.u32(len(m.textures))
    for t in m.textures:
        w.utf16_string(t.texture_name)
        w.utf16_string(t.texture_path)
    w.u32(len(m.light_properties))
    for lp in m.light_properties:
        w.utf16_string(lp.property_name)
        w.i32(lp.parameter_type)
        w.i32(lp.parameter_flags)
    w.u32(len(m.float_attributes))
    for a in m.float_attributes:
        w.utf16_string(a.name)
        w.u32(a.interpolation_mode)
        w.u32(0)
        w.u32(a.num_keys)
        w.u32(a.start_frame)
        w.u32(a.end_frame)
        w.u32(a.loop_flags)
        w.u32(a.reserved_flags)
        w.f32(a.value)
    w.u32(len(m.integer_attributes))
    for a in m.integer_attributes:
        w.utf16_string(a.name)
        w.u32(a.interpolation_mode)
        w.u32(8)
        w.u32(a.num_keys)
        w.u32(a.start_frame)
        w.u32(a.end_frame)
        w.u32(a.loop_flags)
        w.u32(a.reserved_flags)
        w.u32(a.value)
    w.i32(m.shader_pass_index)
    w.u32(len(m.vec4_attributes))
    for a in m.vec4_attributes:
        w.utf16_string(a.name)
        w.u32(a.interpolation_mode)
        w.u32(9)
        w.u32(a.num_keys)
        w.u32(a.start_frame)
        w.u32(a.end_frame)
        w.u32(a.loop_flags)
        w.u32(a.reserved_flags)
        w.vec4(a.value)
    w.i32(m.shader_flags)


def write_material_node(node: s.MaterialNode) -> bytes:
    def body(w: BinaryWriter) -> None:
        w.u32(node.material_type)
        w.utf16_string(node.node_name)
        w.utf16_string(node.material_name)
        write_node_attributes(w, node.material_attributes)
        if node.material_type == s.MATERIAL_TYPE_DEFAULT:
            write_default_material(w, node.default_material)
        else:
            write_directx_material(w, node.directx_material)

    return _write_node_with_length_prefix(s.NODE_TYPE_MATERIAL, body)


def write_header(w: BinaryWriter, header: s.Header) -> None:
    w.fixed_bytes(header.file_format, 4)
    header_size_placeholder_index = len(w.buffer)
    w.u32(0)
    w.f32(header.exporter_version)
    w.u32(header.feature_flags)
    w.utf16_string(header.plugin)
    w.utf16_string(header.details)
    header_size = len(w.buffer) - header_size_placeholder_index
    w.buffer[header_size_placeholder_index : header_size_placeholder_index + 4] = header_size.to_bytes(4, "little")


def write_scene_block(w: BinaryWriter, block: s.SceneBlockData) -> None:
    size_placeholder_index = len(w.buffer)
    w.u32(0)
    w.u32(block.format_compatibility_version)
    w.u32(block.object_types_count)
    w.u32(block.lights_count)
    w.u32(block.cameras_count)
    w.u32(block.rigid_models_count)
    w.u64(block.total_scene_vertex_count)
    w.u32(block.weighted_models_count)
    w.u32(block.lines_count)
    w.u32(block.dummies_count)
    w.u32(block.materials_count)
    w.u64(block.total_scene_triangle_count)
    w.u32(block.instances_count)
    w.fixed_bytes(block.scene_bbox_and_world_matrix, 44)
    block_size = len(w.buffer) - size_placeholder_index
    w.buffer[size_placeholder_index : size_placeholder_index + 4] = block_size.to_bytes(4, "little")


def write_timeline_block(w: BinaryWriter, block: s.TimelineBlockData) -> None:
    block_size = 16 + len(block.track_metadata)
    w.u32(block_size)
    w.u32(block.frame_rate_fps)
    w.f32(block.start_frame_time)
    w.f32(block.end_frame_time)
    w.raw(block.track_metadata)


def write_morph_block(w: BinaryWriter, block: s.MorphAndSplineBlockData) -> None:
    size_placeholder_index = len(w.buffer)
    w.u32(0)
    w.u32(block.morph_track_flags)
    w.u32(len(block.tracks))
    for track in block.tracks:
        w.i32(track.track_id1)
        w.i32(track.track_id2)
        w.i32(track.track_id3)
        w.float_array(track.keyframe_values)
        w.int_array(track.vertex_indices)
    block_size = len(w.buffer) - size_placeholder_index
    w.buffer[size_placeholder_index : size_placeholder_index + 4] = block_size.to_bytes(4, "little")


def write_cs2(doc: s.CS2Document) -> bytes:
    w = BinaryWriter()
    write_header(w, doc.header)
    write_scene_block(w, doc.scene_block)
    write_timeline_block(w, doc.timeline_block)
    write_morph_block(w, doc.morph_block)

    for node in doc.cameras:
        w.raw(write_camera_node(node))
    for node in doc.rigid_models:
        w.raw(write_rigid_model_node(node))
    for node in doc.weighted_models:
        w.raw(write_weighted_model_node(node))
    for node in doc.lines:
        w.raw(write_line_node(node))
    for node in doc.dummies:
        w.raw(write_dummy_node(node))

    w.raw(write_scene_root_node(doc.scene_root))

    for node in doc.materials:
        w.raw(write_material_node(node))
    for node in doc.instances:
        w.raw(write_instance_node(node))

    return w.bytes()
