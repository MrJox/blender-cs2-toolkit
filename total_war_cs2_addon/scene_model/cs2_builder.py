import copy
import getpass
from datetime import datetime

from binary import cs2_structures as s
from binary import cs2_templates as t
from materials.template import build_directx_material_node
from naming.naming import (
    lod_node_name,
    collision_node_name,
    soft_collision_node_name,
    platform_node_name,
    platform_ground_node_name,
    file_reference_node_name,
    line_feature_node_name,
    region_zone_node_name,
    ef_line_node_name,
    docking_line_node_name,
    arrow_emitter_node_name,
    height_map_mesh_node_name,
    gate_collision_node_name,
    gate_collision_attributes,
    gate_display_node_name,
    gate_display_attributes,
    boiling_oil_collision_node_name,
    boiling_oil_collision_attributes,
    boiling_oil_display_node_name,
    boiling_oil_display_attributes,
    destruction_anim_node_name,
    destruction_anim_attributes,
    gate_anim_node_name,
    gate_anim_attributes,
    flag_node_name,
    flag_attributes,
    lod_attributes,
    collision_attributes,
    soft_collision_attributes,
    platform_attributes,
    platform_ground_attributes,
    file_reference_attributes,
    line_feature_attributes,
    region_zone_attributes,
    ef_line_attributes,
    docking_line_attributes,
    ef_line_user_defined_properties,
    docking_line_user_defined_properties,
    region_zone_user_defined_properties,
    arrow_emitter_attributes,
    height_map_mesh_attributes,
)
from .models import BuildingAsset, MeshData, MaterialDef, AnimationKeyframes, Vec3, Vec4


def _bounding_box_for(positions: list[Vec3]) -> tuple[Vec3, Vec3]:
    if not positions:
        return t.GEOMETRY_CHUNK_BOUNDING_BOX_SENTINEL
    lower = tuple(min(p[axis] for p in positions) for axis in range(3))
    upper = tuple(max(p[axis] for p in positions) for axis in range(3))
    return (lower, upper)


def _material_ids_for(material_ids: list[int] | int | None, material_id: int | None) -> list[int]:
    if material_id is not None:
        return [material_id]
    if isinstance(material_ids, int):
        return [material_ids]
    if material_ids is not None:
        return material_ids
    return [0]


def _submeshes_for(mesh: MeshData, mat_ids: list[int]) -> list[s.SubMesh]:
    submeshes_by_mat_id: dict[int, list[tuple[int, int, int]]] = {}
    for tri in mesh.triangles:
        slot_idx = tri.material_index if tri.material_index < len(mat_ids) else 0
        mat_id = mat_ids[slot_idx]
        if mat_id not in submeshes_by_mat_id:
            submeshes_by_mat_id[mat_id] = []
        submeshes_by_mat_id[mat_id].append(tri.indices)

    submeshes = [
        s.SubMesh(triangles=tris, material_id=mat_id)
        for mat_id, tris in submeshes_by_mat_id.items()
    ]
    return submeshes or [s.SubMesh(triangles=[], material_id=mat_ids[0])]


def _rigid_geometry_chunk(
    mesh: MeshData,
    material_ids: list[int] | int | None = None,
    include_uv: bool = True,
    material_id: int | None = None,
    compute_bounds: bool = False,
    vertex_colors: bool = True,
) -> s.RigidGeometryChunk:
    mat_ids = _material_ids_for(material_ids, material_id)

    # Real ground-truth samples commonly carry a second UVW channel (id 2, alongside the primary
    # id 1) on Display meshes whose material samples a texture in UV2 space (t_ambient_occlusion_uv2/
    # t_dirtmap_uv2) - confirmed by parsing raw_data/eastern_new_1.CS2 directly: its Display meshes
    # have uvw_channel_ids=[1, 2] with channel 2 carrying real, independent UV data. Only emitted when
    # every vertex actually has one (i.e. the artist pointed the material's "UV2" node at a real
    # second Blender UV layer - see extraction.extract._convert_mesh).
    has_uv2 = include_uv and mesh.vertices and all(v.uv2 is not None for v in mesh.vertices)
    vertices = [
        s.RigidVertex(
            position=v.position,
            normal=v.normal,
            color=v.color if vertex_colors else (0.0, 0.0, 0.0, 0.0),
            tex_coords=(
                [(v.uv[0], v.uv[1], 0.0), (v.uv2[0], v.uv2[1], 0.0)]
                if has_uv2
                else [(v.uv[0], v.uv[1], 0.0)] if include_uv else []
            ),
            vertex_ao_or_morph_weight=0.0,
        )
        for v in mesh.vertices
    ]

    submeshes = _submeshes_for(mesh, mat_ids)

    # Checked directly against 122 real cas2_exporter files (7 project ground-truth samples + the
    # full vanilla-game architecture corpus) rather than assumed: at the exporter tool version this
    # add-on's own header stamps (1.15, matching Input/examples/raw_data/bridge_stone_1.CS2, the
    # source of GEOMETRY_CHUNK_BOUNDING_BOX_SENTINEL), every rigid-model node type leaves this field
    # on the sentinel except destruction-debris animation meshes and EFLine/DockingLine markers
    # (the latter two handled by their own call sites - see destruction_anim's compute_bounds=True
    # and _line_marker_geometry_chunk's compute_bounds parameter). Real per-vertex bounds for plain
    # LOD/collision3d meshes appear only in a minority of hand-authored samples, not in the current
    # tool version's vanilla-shipped output, so they are not treated as the target to match.
    bounding_box = (
        _bounding_box_for([v.position for v in mesh.vertices])
        if compute_bounds
        else t.GEOMETRY_CHUNK_BOUNDING_BOX_SENTINEL
    )
    return s.RigidGeometryChunk(
        header_padding=t.GEOMETRY_CHUNK_HEADER_PADDING,
        bounding_box_extent_floats=list(t.GEOMETRY_CHUNK_BOUNDING_BOX_EXTENT_FLOATS),
        bounding_boxes=[bounding_box],
        lines=[],
        uvw_channel_ids=list(t.DISPLAY_UVW_CHANNEL_IDS) + [2] if has_uv2 else (list(t.DISPLAY_UVW_CHANNEL_IDS) if include_uv else []),
        vertices=vertices,
        submeshes=submeshes,
        vertex_color_channel_flags=t.DISPLAY_VERTEX_COLOR_CHANNEL_FLAGS if vertex_colors else 0,
    )


# Every CA-authored unit part - weighted and rigid alike - carries zero vertex colours and a
# vertex_color_channel_flags of 0, unlike a building Display mesh's 8. The weighted vertex's
# unskinned position/normal copy the skinned ones in all four authored sources, which is what an
# already-posed mesh means.
def _weighted_geometry_chunk(
    mesh: MeshData,
    bone_weights: list[list[tuple[int, float]]],
    material_ids: list[int] | int | None = None,
) -> s.WeightedGeometryChunk:
    mat_ids = _material_ids_for(material_ids, None)
    vertices = [
        s.WeightedVertex(
            position=v.position,
            normal=v.normal,
            color=(0.0, 0.0, 0.0, 0.0),
            tex_coords=[(v.uv[0], v.uv[1], 0.0)],
            vertex_ao_or_morph_weight=0.0,
            bone_weights=[s.BoneWeight(bone_id=bone_id, weight=weight) for bone_id, weight in weights],
            unskinned_position=v.position,
            unskinned_normal=v.normal,
        )
        for v, weights in zip(mesh.vertices, bone_weights)
    ]
    return s.WeightedGeometryChunk(
        header_padding=t.GEOMETRY_CHUNK_HEADER_PADDING,
        bounding_box_extent_floats=list(t.GEOMETRY_CHUNK_BOUNDING_BOX_EXTENT_FLOATS),
        bounding_boxes=[t.GEOMETRY_CHUNK_BOUNDING_BOX_SENTINEL],
        lines=[],
        uvw_channel_ids=list(t.DISPLAY_UVW_CHANNEL_IDS),
        vertices=vertices,
        submeshes=_submeshes_for(mesh, mat_ids),
        vertex_color_channel_flags=0,
    )


def _line_marker_geometry_chunk(start: Vec3, end: Vec3, compute_bounds: bool = True) -> s.RigidGeometryChunk:
    # EFLine/DockingLine nodes are NODE_TYPE_RIGID_MODEL carrying zero geometry - their position and
    # direction ride on the user_defined_properties text instead. All such chunks across real samples
    # agree on this exact shape, and it differs from every other node type in three ways that matter:
    # no submeshes at all (not one empty submesh pointing at material -1), vertex_color_channel_flags
    # 0, and (for EFLine specifically) a real bounding box rather than the sentinel.
    # DockingLine is NOT the same here despite sharing this node shape - checked directly against
    # real samples: every EFLine marker carries a real half-extent box, every DockingLine marker
    # carries the sentinel. Callers must pass compute_bounds=False for DockingLine.
    if compute_bounds:
        half = [(e - s) / 2.0 for s, e in zip(start, end)]
        lower = tuple(-abs(v) for v in half)
        upper = tuple(abs(v) for v in half)
        bounding_box = (lower, upper)
    else:
        bounding_box = t.GEOMETRY_CHUNK_BOUNDING_BOX_SENTINEL
    return s.RigidGeometryChunk(
        header_padding=t.GEOMETRY_CHUNK_HEADER_PADDING,
        bounding_box_extent_floats=list(t.GEOMETRY_CHUNK_BOUNDING_BOX_EXTENT_FLOATS),
        bounding_boxes=[bounding_box],
        lines=[],
        uvw_channel_ids=[],
        vertices=[],
        submeshes=[],
        vertex_color_channel_flags=0,
    )


def _midpoint(start: Vec3, end: Vec3) -> Vec3:
    return tuple((s + e) / 2.0 for s, e in zip(start, end))


def _line_segments_for(vertex_count: int) -> list[s.LineSegment]:
    # Attempt 1 (CONFIRMED WRONG via an earlier real BOB compile against a hand-authored, buggy
    # sample): reproducing a real-looking literal repeated `(3, 0)` pattern with one entry per
    # vertex. Attempt 2/3 (CONFIRMED WRONG via real BOB "not a closed outline" errors): consecutive-
    # chain / explicit-cycle-closing segment topology - neither changed anything, which in hindsight
    # makes sense given what direct inspection of the *actual shipped* ground-truth samples in
    # Input/examples/raw_data/ shows: every LINE node's `segments` list is that same `(3, 0)` tuple,
    # but repeated exactly once per authored EDGE, not once per vertex - because (see
    # `_subdivide_line_points`) each edge is itself tessellated into exactly 3 vertices. So
    # `vertex_count` is always `3 * edge_count + 1`, and this field's content is a fixed, apparently
    # inert filler value - actual connectivity is carried by the vertex array's own order.
    edge_count = max(0, (vertex_count - 1) // 3)
    return [s.LineSegment(start_vertex_index=3, end_vertex_index=0) for _ in range(edge_count)]


def _line_geometry_chunk(points: list[Vec3]) -> s.LineGeometryChunk:
    # Every LineNode (outline/hard/ground_ad/pipe/region_zone/gate line) checked across the full
    # ground-truth corpus carries the sentinel here, with zero exceptions - unlike the rigid-model
    # chunk types above, this one has no real-bounds exception at all.
    line_data = s.LineData(vertices=points, segments=_line_segments_for(len(points)))
    return s.LineGeometryChunk(
        header_padding=t.GEOMETRY_CHUNK_HEADER_PADDING,
        bounding_box_extent_floats=list(t.GEOMETRY_CHUNK_BOUNDING_BOX_EXTENT_FLOATS),
        bounding_boxes=[t.GEOMETRY_CHUNK_BOUNDING_BOX_SENTINEL],
        lines=[line_data],
        vertex_color_channel_flags=t.LINE_VERTEX_COLOR_CHANNEL_FLAGS,
    )


def _scene_node_for(
    node_name: str,
    attributes: s.NodeAttributes,
    translation: Vec3 = (0.0, 0.0, 0.0),
    rotation: Vec4 = (0.0, 0.0, 0.0, 1.0),
    target_linkage_name: str = "",
    keyframes: AnimationKeyframes | None = None,
) -> s.SceneNode:
    # Every real sample gives each scene node exactly one keyframe (rather than no keyframes at
    # all) and a full copy of its rigid node's attributes. Omitting either crashed BOB's building
    # processor - see the implementation plan for the bisection that found this. Most tech types
    # bake world position into their own geometry chunk and leave this keyframe at identity - the
    # exceptions are arrow emitters, the flag and file references, which BOB places using this
    # transform directly (confirmed by a real BOB warning for arrow emitters: "Arrow emitter
    # transform matrix is the identity, the emitter will appear at the centre of the building!"
    # when left at the default, and by gondor_fort_gateway_e's compiled file refs carrying their
    # scene nodes' translation/rotation verbatim). Destruction debris and gate animation nodes are a
    # further variant of the same exception: real keyframes instead of one, confirmed against
    # gondor_fort_gateway_e's own building_pieceNN_destructNN_anim / gate_*_anim nodes (up to 141
    # keys, translation and rotation keyed independently - see PLAN_buildings.md Phase 2).
    if keyframes is not None:
        anim = s.SceneNodeAnimTrack(
            translation_frame_times=list(keyframes.translation_times),
            translations=list(keyframes.translations),
            scale_track_or_bbox=t.SCENE_NODE_SCALE_TRACK_OR_BBOX,
            rotation_frame_times=list(keyframes.rotation_times),
            rotations=list(keyframes.rotations),
        )
    else:
        anim = s.SceneNodeAnimTrack(
            translation_frame_times=[0.0],
            translations=[translation],
            scale_track_or_bbox=t.SCENE_NODE_SCALE_TRACK_OR_BBOX,
            rotation_frame_times=[0.0],
            rotations=[rotation],
        )
    return s.SceneNode(
        name=node_name,
        parent_index=0,
        default_scale_or_pivot=t.SCENE_NODE_DEFAULT_SCALE_OR_PIVOT,
        anim=anim,
        parent_node_index=0,
        target_linkage_name=target_linkage_name,
        attributes=copy.deepcopy(attributes),
    )


def _material_key(material: MaterialDef) -> tuple:
    return (
        material.shader_type,
        material.diffuse_texture_path,
        material.normal_texture_path,
        material.mask_texture_path,
        material.dirtmap_texture_path,
        material.dirtmask_texture_path,
        material.gloss_texture_path,
        material.level_texture_path,
        material.specular_texture_path,
        material.tint_mask_texture_paths,
        material.decal_texture_paths,
        material.decal_dirtmap_texture_paths,
        material.tint_colours,
        material.faction_colouring,
        material.dirtmap_tile_u,
        material.dirtmap_tile_v,
        material.dirt_uv_offset_u,
        material.dirt_uv_offset_v,
        material.alpha_mode,
        material.uv2_layer_name,
    )


def build_cs2_document(building: BuildingAsset, assembly_kit_root: str, output_path: str = "") -> s.CS2Document:
    material_order: list[MaterialDef] = []
    material_index_by_key: dict[tuple, int] = {}

    for piece in building.pieces:
        for destruct in piece.destruct_levels:
            for lod in destruct.lod_meshes:
                for mat in lod.materials:
                    key = _material_key(mat)
                    if key not in material_index_by_key:
                        material_index_by_key[key] = len(material_order)
                        material_order.append(mat)
            for file_ref in destruct.file_references:
                for mat in file_ref.materials:
                    key = _material_key(mat)
                    if key not in material_index_by_key:
                        material_index_by_key[key] = len(material_order)
                        material_order.append(mat)
            for gate_lod in destruct.gate_closed_lods + destruct.gate_open_lods:
                for mat in gate_lod.materials:
                    key = _material_key(mat)
                    if key not in material_index_by_key:
                        material_index_by_key[key] = len(material_order)
                        material_order.append(mat)
            for anim_mesh in destruct.destruction_anim_meshes + destruct.gate_anim_meshes:
                for mat in anim_mesh.materials:
                    key = _material_key(mat)
                    if key not in material_index_by_key:
                        material_index_by_key[key] = len(material_order)
                        material_order.append(mat)

    rigid_models: list[s.RigidModelNode] = []
    lines: list[s.LineNode] = []
    scene_nodes: list[s.SceneNode] = []
    # Every real sample numbers node_index from 1 (gondor_building_5's two nodes are 1 and 2), and
    # SceneNode.parent_index refers to it directly, with 0 meaning "no parent" - so the counter has
    # to be 1-based for a parent link to be expressible at all.
    node_index_counter = 1
    destruct01_collision_node_index: dict[int, int] = {}
    damage_links: list[tuple[s.SceneNode, int]] = []

    for piece in building.pieces:
        for destruct in piece.destruct_levels:
            for lod in destruct.lod_meshes:
                node_name = lod_node_name(piece.piece_index, destruct.destruct_index, lod.lod_index)
                material_ids = [material_index_by_key[_material_key(m)] for m in lod.materials]
                attributes = lod_attributes(piece.piece_index, destruct.destruct_index, lod.lod_index, building.name)
                rigid_models.append(
                    s.RigidModelNode(
                        node_name=node_name,
                        node_metadata_string="",
                        user_defined_properties="",
                        node_index=node_index_counter,
                        attributes=attributes,
                        geometry_chunks=[_rigid_geometry_chunk(lod.mesh, material_ids, include_uv=True)],
                    )
                )
                scene_nodes.append(_scene_node_for(node_name, attributes))
                node_index_counter += 1

            if destruct.collision_mesh is not None:
                node_name = collision_node_name(piece.piece_index, destruct.destruct_index)
                attributes = collision_attributes(piece.piece_index, destruct.destruct_index, building.name)
                rigid_models.append(
                    s.RigidModelNode(
                        node_name=node_name,
                        node_metadata_string="",
                        user_defined_properties="",
                        node_index=node_index_counter,
                        attributes=attributes,
                        geometry_chunks=[_rigid_geometry_chunk(destruct.collision_mesh.mesh, material_id=-1, include_uv=True)],
                    )
                )
                scene_nodes.append(_scene_node_for(node_name, attributes))
                if destruct.destruct_index == 1:
                    destruct01_collision_node_index[piece.piece_index] = node_index_counter
                    if piece.damage_parent_piece_index is not None:
                        damage_links.append((scene_nodes[-1], piece.damage_parent_piece_index))
                node_index_counter += 1

            if destruct.soft_collision_mesh is not None:
                node_name = soft_collision_node_name(piece.piece_index, destruct.destruct_index)
                attributes = soft_collision_attributes(piece.piece_index, destruct.destruct_index, building.name)
                rigid_models.append(
                    s.RigidModelNode(
                        node_name=node_name,
                        node_metadata_string="",
                        user_defined_properties="",
                        node_index=node_index_counter,
                        attributes=attributes,
                        geometry_chunks=[_rigid_geometry_chunk(destruct.soft_collision_mesh.mesh, material_id=-1, include_uv=True)],
                    )
                )
                scene_nodes.append(_scene_node_for(node_name, attributes))
                node_index_counter += 1

            for platform in destruct.platform_meshes:
                node_name = platform_node_name(piece.piece_index, destruct.destruct_index, platform.variation_index)
                attributes = platform_attributes(piece.piece_index, destruct.destruct_index, platform.variation_index, building.name)
                rigid_models.append(
                    s.RigidModelNode(
                        node_name=node_name,
                        node_metadata_string="",
                        user_defined_properties="",
                        node_index=node_index_counter,
                        attributes=attributes,
                        geometry_chunks=[_rigid_geometry_chunk(platform.mesh, material_id=-1, include_uv=True)],
                    )
                )
                scene_nodes.append(_scene_node_for(node_name, attributes))
                node_index_counter += 1

            if destruct.platform_ground_mesh is not None:
                node_name = platform_ground_node_name(piece.piece_index, destruct.destruct_index)
                attributes = platform_ground_attributes(piece.piece_index, destruct.destruct_index, building.name)
                rigid_models.append(
                    s.RigidModelNode(
                        node_name=node_name,
                        node_metadata_string="",
                        user_defined_properties="",
                        node_index=node_index_counter,
                        attributes=attributes,
                        geometry_chunks=[_rigid_geometry_chunk(destruct.platform_ground_mesh.mesh, material_id=-1, include_uv=True)],
                    )
                )
                scene_nodes.append(_scene_node_for(node_name, attributes))
                node_index_counter += 1

            for file_ref in destruct.file_references:
                node_name = file_reference_node_name(piece.piece_index, destruct.destruct_index, file_ref.reference_name)
                attributes = file_reference_attributes(piece.piece_index, destruct.destruct_index, file_ref.reference_name, building.name)
                if file_ref.mesh is not None:
                    material_ids = [material_index_by_key[_material_key(m)] for m in file_ref.materials]
                    geometry_chunk = _rigid_geometry_chunk(file_ref.mesh, material_ids, include_uv=True)
                else:
                    geometry_chunk = _rigid_geometry_chunk(MeshData(vertices=[], triangles=[]), material_id=-1, include_uv=False)
                rigid_models.append(
                    s.RigidModelNode(
                        node_name=node_name,
                        node_metadata_string="",
                        user_defined_properties="",
                        node_index=node_index_counter,
                        attributes=attributes,
                        geometry_chunks=[geometry_chunk],
                    )
                )
                scene_nodes.append(
                    _scene_node_for(
                        node_name,
                        attributes,
                        translation=file_ref.transform_translation,
                        rotation=file_ref.transform_rotation,
                    )
                )
                node_index_counter += 1

            for line_feature in destruct.line_features:
                node_name = line_feature_node_name(
                    piece.piece_index, destruct.destruct_index, line_feature.line_type, line_feature.variation_index
                )
                attributes = line_feature_attributes(
                    piece.piece_index, destruct.destruct_index, line_feature.line_type, line_feature.variation_index, building.name
                )
                lines.append(
                    s.LineNode(
                        node_name=node_name,
                        node_metadata_string="",
                        user_defined_properties="",
                        node_index=node_index_counter,
                        attributes=attributes,
                        geometry_chunks=[_line_geometry_chunk(line_feature.points)],
                    )
                )
                scene_nodes.append(_scene_node_for(node_name, attributes))
                node_index_counter += 1

            for ef_line in destruct.ef_lines:
                node_name = ef_line_node_name(piece.piece_index, destruct.destruct_index, ef_line.variation_index)
                attributes = ef_line_attributes(piece.piece_index, destruct.destruct_index, ef_line.variation_index, building.name)
                user_defined_properties = ef_line_user_defined_properties(
                    piece.piece_index,
                    destruct.destruct_index,
                    ef_line.variation_index,
                    ef_line.action,
                    ef_line.start,
                    ef_line.end,
                    ef_line.direction,
                )
                rigid_models.append(
                    s.RigidModelNode(
                        node_name=node_name,
                        node_metadata_string="",
                        user_defined_properties=user_defined_properties,
                        node_index=node_index_counter,
                        attributes=attributes,
                        geometry_chunks=[_line_marker_geometry_chunk(ef_line.start, ef_line.end)],
                    )
                )
                scene_nodes.append(
                    _scene_node_for(
                        node_name,
                        attributes,
                        translation=_midpoint(ef_line.start, ef_line.end),
                        target_linkage_name=user_defined_properties,
                    )
                )
                node_index_counter += 1

            for docking_line in destruct.docking_lines:
                node_name = docking_line_node_name(piece.piece_index, destruct.destruct_index, docking_line.variation_index)
                attributes = docking_line_attributes(piece.piece_index, destruct.destruct_index, docking_line.variation_index, building.name)
                user_defined_properties = docking_line_user_defined_properties(docking_line.start, docking_line.end, docking_line.direction)
                rigid_models.append(
                    s.RigidModelNode(
                        node_name=node_name,
                        node_metadata_string="",
                        user_defined_properties=user_defined_properties,
                        node_index=node_index_counter,
                        attributes=attributes,
                        geometry_chunks=[_line_marker_geometry_chunk(docking_line.start, docking_line.end, compute_bounds=False)],
                    )
                )
                scene_nodes.append(
                    _scene_node_for(
                        node_name,
                        attributes,
                        translation=_midpoint(docking_line.start, docking_line.end),
                        target_linkage_name=user_defined_properties,
                    )
                )
                node_index_counter += 1

            for arrow_emitter in destruct.arrow_emitters:
                node_name = arrow_emitter_node_name(piece.piece_index, destruct.destruct_index, arrow_emitter.variation_index)
                attributes = arrow_emitter_attributes(
                    piece.piece_index, destruct.destruct_index, arrow_emitter.variation_index, building.name
                )
                rigid_models.append(
                    s.RigidModelNode(
                        node_name=node_name,
                        node_metadata_string="",
                        user_defined_properties="",
                        node_index=node_index_counter,
                        attributes=attributes,
                        geometry_chunks=[_rigid_geometry_chunk(arrow_emitter.mesh, material_id=-1, include_uv=True)],
                    )
                )
                scene_nodes.append(
                    _scene_node_for(
                        node_name,
                        attributes,
                        translation=arrow_emitter.transform_translation,
                        rotation=arrow_emitter.transform_rotation,
                    )
                )
                node_index_counter += 1

            for gate_role, gate_lods in (
                ("GATE_CLOSED_DISPLAY", destruct.gate_closed_lods),
                ("GATE_OPEN_DISPLAY", destruct.gate_open_lods),
            ):
                for gate_lod in gate_lods:
                    node_name = gate_display_node_name(
                        piece.piece_index, destruct.destruct_index, gate_role, gate_lod.lod_index
                    )
                    material_ids = [material_index_by_key[_material_key(m)] for m in gate_lod.materials]
                    attributes = gate_display_attributes(
                        piece.piece_index, destruct.destruct_index, gate_role, gate_lod.lod_index, building.name
                    )
                    rigid_models.append(
                        s.RigidModelNode(
                            node_name=node_name,
                            node_metadata_string="",
                            user_defined_properties="",
                            node_index=node_index_counter,
                            attributes=attributes,
                            geometry_chunks=[_rigid_geometry_chunk(gate_lod.mesh, material_ids, include_uv=True)],
                        )
                    )
                    scene_nodes.append(_scene_node_for(node_name, attributes))
                    node_index_counter += 1

            for collision_type, gate_collision in (
                ("GATE_CLOSED", destruct.gate_closed_collision),
                ("GATE_AJAR", destruct.gate_ajar_collision),
            ):
                if gate_collision is None:
                    continue
                node_name = gate_collision_node_name(piece.piece_index, destruct.destruct_index, collision_type)
                attributes = gate_collision_attributes(
                    piece.piece_index, destruct.destruct_index, collision_type, building.name
                )
                rigid_models.append(
                    s.RigidModelNode(
                        node_name=node_name,
                        node_metadata_string="",
                        user_defined_properties="",
                        node_index=node_index_counter,
                        attributes=attributes,
                        geometry_chunks=[_rigid_geometry_chunk(gate_collision.mesh, material_id=-1, include_uv=True)],
                    )
                )
                scene_nodes.append(_scene_node_for(node_name, attributes))
                node_index_counter += 1

            for boiling_oil_lod in destruct.boiling_oil_lods:
                node_name = boiling_oil_display_node_name(piece.piece_index, destruct.destruct_index, boiling_oil_lod.lod_index)
                material_ids = [material_index_by_key[_material_key(m)] for m in boiling_oil_lod.materials]
                attributes = boiling_oil_display_attributes(
                    piece.piece_index, destruct.destruct_index, boiling_oil_lod.lod_index, building.name
                )
                rigid_models.append(
                    s.RigidModelNode(
                        node_name=node_name,
                        node_metadata_string="",
                        user_defined_properties="",
                        node_index=node_index_counter,
                        attributes=attributes,
                        geometry_chunks=[_rigid_geometry_chunk(boiling_oil_lod.mesh, material_ids, include_uv=True)],
                    )
                )
                scene_nodes.append(_scene_node_for(node_name, attributes))
                node_index_counter += 1

            if destruct.boiling_oil_collision is not None:
                node_name = boiling_oil_collision_node_name(piece.piece_index, destruct.destruct_index)
                attributes = boiling_oil_collision_attributes(piece.piece_index, destruct.destruct_index, building.name)
                rigid_models.append(
                    s.RigidModelNode(
                        node_name=node_name,
                        node_metadata_string="",
                        user_defined_properties="",
                        node_index=node_index_counter,
                        attributes=attributes,
                        geometry_chunks=[_rigid_geometry_chunk(destruct.boiling_oil_collision.mesh, material_id=-1, include_uv=True)],
                    )
                )
                scene_nodes.append(_scene_node_for(node_name, attributes))
                # A piece with no plain collision mesh of its own (confirmed real: the sample's
                # boiling-oil piece has none, same as a gate-only piece) still needs *some*
                # destruct01 node to anchor a Damage Parent link to, since that link is authored as
                # SceneNode.parent_index on "the piece's destruct01 collision node" generically, not
                # specifically the plain-COLLISION-typed one - confirmed directly from this sample,
                # whose real piece05_destruct01_collision3d_boiling_oil carries a real parent_index.
                if destruct.destruct_index == 1 and piece.piece_index not in destruct01_collision_node_index:
                    destruct01_collision_node_index[piece.piece_index] = node_index_counter
                    if piece.damage_parent_piece_index is not None:
                        damage_links.append((scene_nodes[-1], piece.damage_parent_piece_index))
                node_index_counter += 1

            for height_map in destruct.height_map_meshes:
                node_name = height_map_mesh_node_name(piece.piece_index, destruct.destruct_index, height_map.variation_index)
                attributes = height_map_mesh_attributes(
                    piece.piece_index, destruct.destruct_index, height_map.variation_index, building.name
                )
                rigid_models.append(
                    s.RigidModelNode(
                        node_name=node_name,
                        node_metadata_string="",
                        user_defined_properties="",
                        node_index=node_index_counter,
                        attributes=attributes,
                        geometry_chunks=[_rigid_geometry_chunk(height_map.mesh, material_id=-1, include_uv=True)],
                    )
                )
                scene_nodes.append(_scene_node_for(node_name, attributes))
                node_index_counter += 1

            for destruction_anim in destruct.destruction_anim_meshes:
                node_name = destruction_anim_node_name(piece.piece_index, destruct.destruct_index)
                material_ids = [material_index_by_key[_material_key(m)] for m in destruction_anim.materials]
                attributes = destruction_anim_attributes(piece.piece_index, destruct.destruct_index, building.name)
                rigid_models.append(
                    s.RigidModelNode(
                        node_name=node_name,
                        node_metadata_string="",
                        user_defined_properties="",
                        node_index=node_index_counter,
                        attributes=attributes,
                        geometry_chunks=[_rigid_geometry_chunk(destruction_anim.mesh, material_ids, include_uv=True, compute_bounds=True)],
                    )
                )
                scene_nodes.append(_scene_node_for(node_name, attributes, keyframes=destruction_anim.keyframes))
                node_index_counter += 1

            for gate_anim in destruct.gate_anim_meshes:
                node_name = gate_anim_node_name(piece.piece_index, destruct.destruct_index, gate_anim.gate_anim_kind)
                material_ids = [material_index_by_key[_material_key(m)] for m in gate_anim.materials]
                attributes = gate_anim_attributes(
                    piece.piece_index, destruct.destruct_index, gate_anim.gate_anim_kind, building.name
                )
                rigid_models.append(
                    s.RigidModelNode(
                        node_name=node_name,
                        node_metadata_string="",
                        user_defined_properties="",
                        node_index=node_index_counter,
                        attributes=attributes,
                        geometry_chunks=[_rigid_geometry_chunk(gate_anim.mesh, material_ids, include_uv=True)],
                    )
                )
                scene_nodes.append(_scene_node_for(node_name, attributes, keyframes=gate_anim.keyframes))
                node_index_counter += 1

    for region_zone in building.region_zones:
        node_name = region_zone_node_name(region_zone.variation_index)
        attributes = region_zone_attributes(region_zone.variation_index, building.name)
        user_defined_properties = region_zone_user_defined_properties(region_zone.corner_points)
        lines.append(
            s.LineNode(
                node_name=node_name,
                node_metadata_string="",
                user_defined_properties=user_defined_properties,
                node_index=node_index_counter,
                attributes=attributes,
                geometry_chunks=[_line_geometry_chunk(region_zone.points)],
            )
        )
        scene_nodes.append(_scene_node_for(node_name, attributes, target_linkage_name=user_defined_properties))
        node_index_counter += 1

    if building.flag is not None:
        node_name = flag_node_name()
        attributes = flag_attributes(building.name)
        rigid_models.append(
            s.RigidModelNode(
                node_name=node_name,
                node_metadata_string="",
                user_defined_properties="",
                node_index=node_index_counter,
                attributes=attributes,
                geometry_chunks=[_rigid_geometry_chunk(building.flag.mesh, material_id=-1, include_uv=True)],
            )
        )
        scene_nodes.append(
            _scene_node_for(
                node_name,
                attributes,
                translation=building.flag.transform_translation,
                rotation=building.flag.transform_rotation,
            )
        )
        node_index_counter += 1

    # Both ground-truth samples that use damage linkage author it only on the destruct01 collision
    # node and leave the deeper destruct levels' collision nodes unparented.
    for scene_node, parent_piece_index in damage_links:
        parent_node_index = destruct01_collision_node_index.get(parent_piece_index)
        if parent_node_index is not None:
            scene_node.parent_index = parent_node_index

    materials: list[s.MaterialNode] = []
    for material in material_order:
        materials.append(
            build_directx_material_node(
                node_name=material.name,
                material_name=material.name,
                rigid_material=material.shader_type,
                assembly_kit_root=assembly_kit_root,
                diffuse_texture_path=material.diffuse_texture_path,
                normal_texture_path=material.normal_texture_path,
                mask_texture_path=material.mask_texture_path,
                dirtmap_texture_path=material.dirtmap_texture_path,
                gloss_texture_path=material.gloss_texture_path,
                level_texture_path=material.level_texture_path,
                specular_texture_path=material.specular_texture_path,
                dirtmask_texture_path=material.dirtmask_texture_path,
                tint_mask_texture_paths=material.tint_mask_texture_paths,
                decal_texture_paths=material.decal_texture_paths,
                decal_dirtmap_texture_paths=material.decal_dirtmap_texture_paths,
                tint_colours=material.tint_colours,
                faction_colouring=material.faction_colouring,
                dirtmap_tile_u=material.dirtmap_tile_u,
                dirtmap_tile_v=material.dirtmap_tile_v,
                dirt_uv_offset_u=material.dirt_uv_offset_u,
                dirt_uv_offset_v=material.dirt_uv_offset_v,
                alpha_mode=material.alpha_mode,
            )
        )
        node_index_counter += 1

    details = t.build_details_string(
        username=getpass.getuser(),
        export_timestamp=datetime.now().strftime("%d/%m/%Y,%H:%M:%S"),
        cas_name_path=output_path,
    )

    header = s.Header(
        file_format=t.FILE_FORMAT_MAGIC,
        exporter_version=t.EXPORTER_VERSION,
        feature_flags=t.FEATURE_FLAGS,
        plugin=t.get_plugin_header_string(),
        details=details,
    )

    scene_block = s.SceneBlockData(
        format_compatibility_version=t.FORMAT_COMPATIBILITY_VERSION,
        object_types_count=t.OBJECT_TYPES_COUNT,
        lights_count=0,
        cameras_count=0,
        rigid_models_count=len(rigid_models),
        total_scene_vertex_count=0,
        weighted_models_count=0,
        lines_count=len(lines),
        dummies_count=0,
        materials_count=len(materials),
        total_scene_triangle_count=0,
        instances_count=0,
        scene_bbox_and_world_matrix=t.SCENE_BBOX_AND_WORLD_MATRIX,
    )

    timeline_block = s.TimelineBlockData(
        frame_rate_fps=t.TIMELINE_FRAME_RATE_FPS,
        start_frame_time=t.TIMELINE_START_FRAME_TIME,
        end_frame_time=t.TIMELINE_END_FRAME_TIME,
        track_metadata=t.TIMELINE_TRACK_METADATA,
    )

    morph_block = s.MorphAndSplineBlockData(morph_track_flags=t.MORPH_TRACK_FLAGS, tracks=[])

    scene_root = s.SceneRootNode(
        node_name=t.SCENE_ROOT_NODE_NAME,
        up_axis_orientation=t.SCENE_ROOT_UP_AXIS_ORIENTATION,
        scene_unit_scale=t.SCENE_ROOT_UNIT_SCALE,
        scene_hierarchy_metadata=t.SCENE_ROOT_HIERARCHY_METADATA,
        info=details,
        active_camera_index=0,
        active_light_index=0,
        root_end_padding=t.SCENE_ROOT_END_PADDING,
        scene_nodes=scene_nodes,
    )

    return s.CS2Document(
        header=header,
        scene_block=scene_block,
        timeline_block=timeline_block,
        morph_block=morph_block,
        cameras=[],
        rigid_models=rigid_models,
        weighted_models=[],
        lines=lines,
        dummies=[],
        scene_root=scene_root,
        materials=materials,
        instances=[],
    )
