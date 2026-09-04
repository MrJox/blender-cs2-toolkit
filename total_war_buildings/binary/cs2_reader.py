from .reader import BinaryReader
from . import cs2_structures as s


def read_node_attributes(r: BinaryReader) -> s.NodeAttributes:
    strings = []
    for _ in range(r.u32()):
        name = r.utf16_string()
        r.u32()
        value = r.utf16_string()
        strings.append(s.NodeAttributeString(name=name, value=value))

    integers = []
    for _ in range(r.u32()):
        name = r.utf16_string()
        interpolation_mode = r.u32()
        r.u32()
        num_keys = r.u32()
        start_frame = r.u32()
        end_frame = r.u32()
        loop_flags = r.u32()
        reserved_flags = r.u32()
        value = r.u32()
        integers.append(
            s.NodeAttributeInteger(
                name=name,
                value=value,
                interpolation_mode=interpolation_mode,
                num_keys=num_keys,
                start_frame=start_frame,
                end_frame=end_frame,
                loop_flags=loop_flags,
                reserved_flags=reserved_flags,
            )
        )

    floats = []
    for _ in range(r.u32()):
        name = r.utf16_string()
        interpolation_mode = r.u32()
        r.u32()
        num_keys = r.u32()
        start_frame = r.u32()
        end_frame = r.u32()
        loop_flags = r.u32()
        reserved_flags = r.u32()
        value = r.f32()
        floats.append(
            s.NodeAttributeFloat(
                name=name,
                value=value,
                interpolation_mode=interpolation_mode,
                num_keys=num_keys,
                start_frame=start_frame,
                end_frame=end_frame,
                loop_flags=loop_flags,
                reserved_flags=reserved_flags,
            )
        )

    vec3s = []
    for _ in range(r.u32()):
        name = r.utf16_string()
        interpolation_mode = r.u32()
        r.u32()
        num_keys = r.u32()
        start_frame = r.u32()
        end_frame = r.u32()
        loop_flags = r.u32()
        reserved_flags = r.u32()
        value = r.vec3()
        vec3s.append(
            s.NodeAttributeVec3(
                name=name,
                value=value,
                interpolation_mode=interpolation_mode,
                num_keys=num_keys,
                start_frame=start_frame,
                end_frame=end_frame,
                loop_flags=loop_flags,
                reserved_flags=reserved_flags,
            )
        )

    vec4s = []
    for _ in range(r.u32()):
        name = r.utf16_string()
        interpolation_mode = r.u32()
        r.u32()
        num_keys = r.u32()
        start_frame = r.u32()
        end_frame = r.u32()
        loop_flags = r.u32()
        reserved_flags = r.u32()
        value = r.vec4()
        vec4s.append(
            s.NodeAttributeVec4(
                name=name,
                value=value,
                interpolation_mode=interpolation_mode,
                num_keys=num_keys,
                start_frame=start_frame,
                end_frame=end_frame,
                loop_flags=loop_flags,
                reserved_flags=reserved_flags,
            )
        )

    return s.NodeAttributes(strings=strings, integers=integers, floats=floats, vec3s=vec3s, vec4s=vec4s)


def read_line_data(r: BinaryReader) -> s.LineData:
    vertex_count = r.u32()
    vertices = [r.vec3() for _ in range(vertex_count)]
    segment_count = r.u32()
    segments = [s.LineSegment(r.u32(), r.u32()) for _ in range(segment_count)]
    return s.LineData(vertices=vertices, segments=segments)


def read_geometry_chunk_common(r: BinaryReader) -> tuple[bytes, list[float], list[s.BoundingBox], list[s.LineData]]:
    header_padding = r.raw(12)
    bounding_box_extent_floats = r.float_array()
    bounding_box_count = r.u32()
    bounding_boxes = [r.bounding_box() for _ in range(bounding_box_count)]
    lines_count = r.u32()
    lines = [read_line_data(r) for _ in range(lines_count)]
    return header_padding, bounding_box_extent_floats, bounding_boxes, lines


def read_rigid_vertex(r: BinaryReader) -> s.RigidVertex:
    position = r.vec3()
    normal = r.vec3()
    color = r.vec4()
    tex_coord_count = r.u32()
    tex_coords = [r.vec3() for _ in range(tex_coord_count)]
    vertex_ao_or_morph_weight = r.f32()
    return s.RigidVertex(position, normal, color, tex_coords, vertex_ao_or_morph_weight)


def read_weighted_vertex(r: BinaryReader) -> s.WeightedVertex:
    position = r.vec3()
    normal = r.vec3()
    color = r.vec4()
    tex_coord_count = r.u32()
    tex_coords = [r.vec3() for _ in range(tex_coord_count)]
    vertex_ao_or_morph_weight = r.f32()
    bones_count = r.u32()
    bone_weights = [s.BoneWeight(r.u32(), r.f32()) for _ in range(bones_count)]
    unskinned_position = r.vec3()
    unskinned_normal = r.vec3()
    return s.WeightedVertex(
        position, normal, color, tex_coords, vertex_ao_or_morph_weight, bone_weights, unskinned_position, unskinned_normal
    )


def read_submeshes(r: BinaryReader) -> list[s.SubMesh]:
    submesh_count = r.u32()
    submeshes = []
    for _ in range(submesh_count):
        triangle_count = r.u32()
        triangles = [(r.u32(), r.u32(), r.u32()) for _ in range(triangle_count)]
        material_id = r.i32()
        submeshes.append(s.SubMesh(triangles=triangles, material_id=material_id))
    return submeshes


def read_rigid_geometry_chunk(r: BinaryReader) -> s.RigidGeometryChunk:
    header_padding, bbox_extents, bboxes, lines = read_geometry_chunk_common(r)
    uvw_channel_count = r.u32()
    uvw_channel_ids = [r.u32() for _ in range(uvw_channel_count)]
    vertex_count = r.u32()
    vertices = [read_rigid_vertex(r) for _ in range(vertex_count)]
    submeshes = read_submeshes(r)
    vertex_color_channel_flags = r.i32()
    return s.RigidGeometryChunk(
        header_padding=header_padding,
        bounding_box_extent_floats=bbox_extents,
        bounding_boxes=bboxes,
        lines=lines,
        uvw_channel_ids=uvw_channel_ids,
        vertices=vertices,
        submeshes=submeshes,
        vertex_color_channel_flags=vertex_color_channel_flags,
    )


def read_weighted_geometry_chunk(r: BinaryReader) -> s.WeightedGeometryChunk:
    header_padding, bbox_extents, bboxes, lines = read_geometry_chunk_common(r)
    uvw_channel_count = r.u32()
    uvw_channel_ids = [r.u32() for _ in range(uvw_channel_count)]
    vertex_count = r.u32()
    vertices = [read_weighted_vertex(r) for _ in range(vertex_count)]
    submeshes = read_submeshes(r)
    vertex_color_channel_flags = r.i32()
    return s.WeightedGeometryChunk(
        header_padding=header_padding,
        bounding_box_extent_floats=bbox_extents,
        bounding_boxes=bboxes,
        lines=lines,
        uvw_channel_ids=uvw_channel_ids,
        vertices=vertices,
        submeshes=submeshes,
        vertex_color_channel_flags=vertex_color_channel_flags,
    )


def read_line_geometry_chunk(r: BinaryReader) -> s.LineGeometryChunk:
    header_padding, bbox_extents, bboxes, lines = read_geometry_chunk_common(r)
    vertex_color_channel_flags = r.i32()
    return s.LineGeometryChunk(
        header_padding=header_padding,
        bounding_box_extent_floats=bbox_extents,
        bounding_boxes=bboxes,
        lines=lines,
        vertex_color_channel_flags=vertex_color_channel_flags,
    )


def read_instance_geometry_chunk(r: BinaryReader, override_material: bool) -> s.InstanceGeometryChunk:
    header_padding, bbox_extents, bboxes, lines = read_geometry_chunk_common(r)
    original_node_index = r.u32()
    vertex_color_channel_flags = r.i32()
    material_id = r.u32() if override_material else None
    return s.InstanceGeometryChunk(
        header_padding=header_padding,
        bounding_box_extent_floats=bbox_extents,
        bounding_boxes=bboxes,
        lines=lines,
        original_node_index=original_node_index,
        vertex_color_channel_flags=vertex_color_channel_flags,
        material_id=material_id,
    )


def read_node_common_fields(r: BinaryReader) -> tuple[str, str, str, int, s.NodeAttributes]:
    node_name = r.utf16_string()
    node_metadata_string = r.utf16_string()
    user_defined_properties = r.utf16_string()
    node_index = r.u32()
    attributes = read_node_attributes(r)
    return node_name, node_metadata_string, user_defined_properties, node_index, attributes


def read_rigid_model_node(r: BinaryReader) -> s.RigidModelNode:
    node_name, node_metadata_string, udp, node_index, attributes = read_node_common_fields(r)
    chunk_count = r.u32()
    chunks = [read_rigid_geometry_chunk(r) for _ in range(chunk_count)]
    return s.RigidModelNode(
        node_name=node_name,
        node_metadata_string=node_metadata_string,
        user_defined_properties=udp,
        node_index=node_index,
        attributes=attributes,
        geometry_chunks=chunks,
    )


def read_weighted_model_node(r: BinaryReader) -> s.WeightedModelNode:
    node_name, node_metadata_string, udp, node_index, attributes = read_node_common_fields(r)
    chunk_count = r.u32()
    chunks = [read_weighted_geometry_chunk(r) for _ in range(chunk_count)]
    return s.WeightedModelNode(
        node_name=node_name,
        node_metadata_string=node_metadata_string,
        user_defined_properties=udp,
        node_index=node_index,
        attributes=attributes,
        geometry_chunks=chunks,
    )


def read_line_node(r: BinaryReader) -> s.LineNode:
    node_name, node_metadata_string, udp, node_index, attributes = read_node_common_fields(r)
    chunk_count = r.u32()
    chunks = [read_line_geometry_chunk(r) for _ in range(chunk_count)]
    return s.LineNode(
        node_name=node_name,
        node_metadata_string=node_metadata_string,
        user_defined_properties=udp,
        node_index=node_index,
        attributes=attributes,
        geometry_chunks=chunks,
    )


def read_instance_node(r: BinaryReader, override_material: bool) -> s.InstanceNode:
    leading_unknown = r.u32()
    node_name, node_metadata_string, udp, node_index, attributes = read_node_common_fields(r)
    chunk_count = r.u32()
    chunks = [read_instance_geometry_chunk(r, override_material) for _ in range(chunk_count)]
    return s.InstanceNode(
        node_name=node_name,
        node_metadata_string=node_metadata_string,
        user_defined_properties=udp,
        node_index=node_index,
        attributes=attributes,
        override_material=override_material,
        leading_unknown=leading_unknown,
        geometry_chunks=chunks,
    )


def read_dummy_node(r: BinaryReader) -> s.DummyNode:
    node_name, node_metadata_string, udp, node_index, attributes = read_node_common_fields(r)
    geometry_data_count = r.u32()
    if geometry_data_count != 0:
        raise ValueError("DUMMY node with non-zero geometry data is not supported by this reader")
    return s.DummyNode(
        node_name=node_name,
        node_metadata_string=node_metadata_string,
        user_defined_properties=udp,
        node_index=node_index,
        attributes=attributes,
        geometry_data_count=geometry_data_count,
    )


def read_camera_node(r: BinaryReader) -> s.CameraNode:
    node_name, node_metadata_string, udp, node_index, attributes = read_node_common_fields(r)
    camera_parameters = r.raw(144)
    return s.CameraNode(
        node_name=node_name,
        node_metadata_string=node_metadata_string,
        user_defined_properties=udp,
        node_index=node_index,
        attributes=attributes,
        camera_parameters=camera_parameters,
    )


def read_scene_node(r: BinaryReader) -> s.SceneNode:
    name = r.utf16_string()
    parent_index = r.u32()
    default_scale_or_pivot = r.vec4()
    translation_frame_count = r.u32()
    translation_frame_times = [r.f32() for _ in range(translation_frame_count)]
    translation_count = r.u32()
    translations = [r.vec3() for _ in range(translation_count)]
    scale_track_or_bbox = r.raw(16)
    rotation_frame_count = r.u32()
    rotation_frame_times = [r.f32() for _ in range(rotation_frame_count)]
    rotation_count = r.u32()
    rotations = [r.vec4() for _ in range(rotation_count)]
    anim = s.SceneNodeAnimTrack(
        translation_frame_times=translation_frame_times,
        translations=translations,
        scale_track_or_bbox=scale_track_or_bbox,
        rotation_frame_times=rotation_frame_times,
        rotations=rotations,
    )
    parent_node_index = r.i32()
    target_linkage_name = r.utf16_string()
    attributes = read_node_attributes(r)
    return s.SceneNode(
        name=name,
        parent_index=parent_index,
        default_scale_or_pivot=default_scale_or_pivot,
        anim=anim,
        parent_node_index=parent_node_index,
        target_linkage_name=target_linkage_name,
        attributes=attributes,
    )


def read_scene_root_node(r: BinaryReader) -> s.SceneRootNode:
    nodes_count = r.u32()
    node_name = r.utf16_string()
    up_axis_orientation = r.i32()
    scene_unit_scale = r.i32()
    scene_hierarchy_metadata = r.raw(84)
    info = r.utf16_string()
    active_camera_index = r.i32()
    active_light_index = r.i32()
    root_end_padding = r.raw(12)
    scene_nodes = [read_scene_node(r) for _ in range(nodes_count - 1)]
    return s.SceneRootNode(
        node_name=node_name,
        up_axis_orientation=up_axis_orientation,
        scene_unit_scale=scene_unit_scale,
        scene_hierarchy_metadata=scene_hierarchy_metadata,
        info=info,
        active_camera_index=active_camera_index,
        active_light_index=active_light_index,
        root_end_padding=root_end_padding,
        scene_nodes=scene_nodes,
    )


def read_default_material(r: BinaryReader, node_end_offset: int) -> s.DefaultMaterial:
    raw_body = r.raw(node_end_offset - r.offset)
    return s.DefaultMaterial(raw_body=raw_body)


def read_directx_material(r: BinaryReader) -> s.DirectXMaterial:
    shader_fx_path = r.utf16_string()
    shader_technique_index = r.u32()
    texture_count = r.u32()
    textures = [s.MaterialTexture(r.utf16_string(), r.utf16_string()) for _ in range(texture_count)]
    light_property_count = r.u32()
    light_properties = [
        s.MaterialLightProperty(r.utf16_string(), r.i32(), r.i32()) for _ in range(light_property_count)
    ]
    float_attribute_count = r.u32()
    float_attributes = []
    for _ in range(float_attribute_count):
        name = r.utf16_string()
        interpolation_mode = r.u32()
        r.u32()
        num_keys = r.u32()
        start_frame = r.u32()
        end_frame = r.u32()
        loop_flags = r.u32()
        reserved_flags = r.u32()
        value = r.f32()
        float_attributes.append(
            s.NodeAttributeFloat(
                name=name,
                value=value,
                interpolation_mode=interpolation_mode,
                num_keys=num_keys,
                start_frame=start_frame,
                end_frame=end_frame,
                loop_flags=loop_flags,
                reserved_flags=reserved_flags,
            )
        )
    integer_attribute_count = r.u32()
    integer_attributes = []
    for _ in range(integer_attribute_count):
        name = r.utf16_string()
        interpolation_mode = r.u32()
        r.u32()
        num_keys = r.u32()
        start_frame = r.u32()
        end_frame = r.u32()
        loop_flags = r.u32()
        reserved_flags = r.u32()
        value = r.u32()
        integer_attributes.append(
            s.NodeAttributeInteger(
                name=name,
                value=value,
                interpolation_mode=interpolation_mode,
                num_keys=num_keys,
                start_frame=start_frame,
                end_frame=end_frame,
                loop_flags=loop_flags,
                reserved_flags=reserved_flags,
            )
        )
    shader_pass_index = r.i32()
    vec4_attribute_count = r.u32()
    vec4_attributes = []
    for _ in range(vec4_attribute_count):
        name = r.utf16_string()
        interpolation_mode = r.u32()
        r.u32()
        num_keys = r.u32()
        start_frame = r.u32()
        end_frame = r.u32()
        loop_flags = r.u32()
        reserved_flags = r.u32()
        value = r.vec4()
        vec4_attributes.append(
            s.NodeAttributeVec4(
                name=name,
                value=value,
                interpolation_mode=interpolation_mode,
                num_keys=num_keys,
                start_frame=start_frame,
                end_frame=end_frame,
                loop_flags=loop_flags,
                reserved_flags=reserved_flags,
            )
        )
    shader_flags = r.i32()
    return s.DirectXMaterial(
        shader_fx_path=shader_fx_path,
        shader_technique_index=shader_technique_index,
        textures=textures,
        light_properties=light_properties,
        float_attributes=float_attributes,
        integer_attributes=integer_attributes,
        shader_pass_index=shader_pass_index,
        vec4_attributes=vec4_attributes,
        shader_flags=shader_flags,
    )


def read_material_node(r: BinaryReader, node_end_offset: int) -> s.MaterialNode:
    material_type = r.u32()
    node_name = r.utf16_string()
    material_name = r.utf16_string()
    material_attributes = read_node_attributes(r)
    default_material = None
    directx_material = None
    if material_type == s.MATERIAL_TYPE_DEFAULT:
        default_material = read_default_material(r, node_end_offset)
    elif material_type == s.MATERIAL_TYPE_DIRECTX:
        directx_material = read_directx_material(r)
    else:
        raise ValueError(f"Unsupported material type {material_type}")
    return s.MaterialNode(
        material_type=material_type,
        node_name=node_name,
        material_name=material_name,
        material_attributes=material_attributes,
        default_material=default_material,
        directx_material=directx_material,
    )


_NODE_READERS = {
    s.NODE_TYPE_CAMERA: read_camera_node,
    s.NODE_TYPE_RIGID_MODEL: read_rigid_model_node,
    s.NODE_TYPE_WEIGHTED_MODEL: read_weighted_model_node,
    s.NODE_TYPE_LINE: read_line_node,
    s.NODE_TYPE_DUMMY: read_dummy_node,
}


def read_node(r: BinaryReader, expected_type: int):
    node_start = r.offset
    node_length = r.u32()
    node_type = r.u32()
    if node_type != expected_type and not (
        expected_type == s.NODE_TYPE_INSTANCE_NO_MATERIAL and node_type == s.NODE_TYPE_INSTANCE_OVERRIDE_MATERIAL
    ):
        raise ValueError(f"Expected node type {expected_type} at offset {node_start}, found {node_type}")
    node_end_offset = node_start + node_length
    if node_type in (s.NODE_TYPE_INSTANCE_NO_MATERIAL, s.NODE_TYPE_INSTANCE_OVERRIDE_MATERIAL):
        node = read_instance_node(r, override_material=(node_type == s.NODE_TYPE_INSTANCE_OVERRIDE_MATERIAL))
    elif node_type == s.NODE_TYPE_MATERIAL:
        node = read_material_node(r, node_end_offset)
    else:
        node = _NODE_READERS[node_type](r)
    consumed = r.offset - node_start
    if consumed != node_length:
        raise ValueError(
            f"Node at offset {node_start} (type {node_type}) declared length {node_length} but consumed {consumed}"
        )
    return node


def read_header(r: BinaryReader) -> s.Header:
    file_format = r.raw(4)
    r.u32()
    exporter_version = r.f32()
    feature_flags = r.u32()
    plugin = r.utf16_string()
    details = r.utf16_string()
    return s.Header(file_format=file_format, exporter_version=exporter_version, feature_flags=feature_flags, plugin=plugin, details=details)


def read_scene_block(r: BinaryReader) -> s.SceneBlockData:
    r.u32()
    format_compatibility_version = r.u32()
    object_types_count = r.u32()
    lights_count = r.u32()
    cameras_count = r.u32()
    rigid_models_count = r.u32()
    total_scene_vertex_count = r.u64()
    weighted_models_count = r.u32()
    lines_count = r.u32()
    dummies_count = r.u32()
    materials_count = r.u32()
    total_scene_triangle_count = r.u64()
    instances_count = r.u32()
    scene_bbox_and_world_matrix = r.raw(44)
    return s.SceneBlockData(
        format_compatibility_version=format_compatibility_version,
        object_types_count=object_types_count,
        lights_count=lights_count,
        cameras_count=cameras_count,
        rigid_models_count=rigid_models_count,
        total_scene_vertex_count=total_scene_vertex_count,
        weighted_models_count=weighted_models_count,
        lines_count=lines_count,
        dummies_count=dummies_count,
        materials_count=materials_count,
        total_scene_triangle_count=total_scene_triangle_count,
        instances_count=instances_count,
        scene_bbox_and_world_matrix=scene_bbox_and_world_matrix,
    )


def read_timeline_block(r: BinaryReader) -> s.TimelineBlockData:
    block_size = r.u32()
    frame_rate_fps = r.u32()
    start_frame_time = r.f32()
    end_frame_time = r.f32()
    track_metadata = r.raw(block_size - 16)
    return s.TimelineBlockData(frame_rate_fps=frame_rate_fps, start_frame_time=start_frame_time, end_frame_time=end_frame_time, track_metadata=track_metadata)


def read_morph_block(r: BinaryReader) -> s.MorphAndSplineBlockData:
    r.u32()
    morph_track_flags = r.u32()
    track_count = r.u32()
    tracks = []
    for _ in range(track_count):
        track_id1 = r.i32()
        track_id2 = r.i32()
        track_id3 = r.i32()
        keyframe_values = r.float_array()
        vertex_indices = r.int_array()
        tracks.append(
            s.MorphSplineTrack(track_id1=track_id1, track_id2=track_id2, track_id3=track_id3, keyframe_values=keyframe_values, vertex_indices=vertex_indices)
        )
    return s.MorphAndSplineBlockData(morph_track_flags=morph_track_flags, tracks=tracks)


def read_cs2(data: bytes) -> s.CS2Document:
    r = BinaryReader(data)
    header = read_header(r)
    scene_block = read_scene_block(r)
    timeline_block = read_timeline_block(r)
    morph_block = read_morph_block(r)

    if scene_block.lights_count != 0:
        raise ValueError(
            "This file contains LIGHT nodes. Their byte layout isn't in the CS2 spec and no sample "
            "file with lights was available to reverse-engineer it, so reading them isn't supported yet."
        )

    cameras = [read_node(r, s.NODE_TYPE_CAMERA) for _ in range(scene_block.cameras_count)]
    rigid_models = [read_node(r, s.NODE_TYPE_RIGID_MODEL) for _ in range(scene_block.rigid_models_count)]
    weighted_models = [read_node(r, s.NODE_TYPE_WEIGHTED_MODEL) for _ in range(scene_block.weighted_models_count)]
    lines = [read_node(r, s.NODE_TYPE_LINE) for _ in range(scene_block.lines_count)]
    dummies = [read_node(r, s.NODE_TYPE_DUMMY) for _ in range(scene_block.dummies_count)]

    scene_root_start = r.offset
    scene_root_length = r.u32()
    scene_root_type = r.u32()
    if scene_root_type != s.NODE_TYPE_SCENE_ROOT:
        raise ValueError(f"Expected SCENE_ROOT node, found type {scene_root_type}")
    scene_root = read_scene_root_node(r)
    if r.offset - scene_root_start != scene_root_length:
        raise ValueError("SCENE_ROOT node length mismatch")

    materials = [read_node(r, s.NODE_TYPE_MATERIAL) for _ in range(scene_block.materials_count)]
    instances = [read_node(r, s.NODE_TYPE_INSTANCE_NO_MATERIAL) for _ in range(scene_block.instances_count)]

    return s.CS2Document(
        header=header,
        scene_block=scene_block,
        timeline_block=timeline_block,
        morph_block=morph_block,
        cameras=cameras,
        rigid_models=rigid_models,
        weighted_models=weighted_models,
        lines=lines,
        dummies=dummies,
        scene_root=scene_root,
        materials=materials,
        instances=instances,
    )
