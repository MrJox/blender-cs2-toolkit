import getpass
import math
from datetime import datetime

from binary import cs2_structures as s
from binary import cs2_templates as t
from materials.template import build_directx_material_node
from naming.naming import (
    attachment_point_node_name,
    skeleton_bone_attributes,
    unit_lod_node_name,
)
from .cs2_builder import _material_key, _rigid_geometry_chunk, _scene_node_for, _weighted_geometry_chunk
from .models import MaterialDef, MeshData, MeshTriangle, MeshVertex
from .unit_models import UnitPart

# CA's AP_ nodes carry a small 18-triangle marker mesh roughly 2.7cm tall and 1.5cm across, drawn
# in the node's own local frame. Whether BOB reads any of it (rather than only the node's
# transform) is UNCONFIRMED - it is reproduced so an exported attachment point is the same shape of
# thing as generic_spangenhelm_elite's.
ATTACHMENT_MARKER_HEIGHT = 0.0273
ATTACHMENT_MARKER_RADIUS = 0.00727
ATTACHMENT_MARKER_SEGMENTS = 9


class UnitBuildError(Exception):
    pass


def _attachment_marker_mesh() -> MeshData:
    apex = (0.0, ATTACHMENT_MARKER_HEIGHT, 0.0)
    base_centre = (0.0, 0.0, 0.0)
    ring = []
    for step in range(ATTACHMENT_MARKER_SEGMENTS):
        angle = 2.0 * math.pi * step / ATTACHMENT_MARKER_SEGMENTS
        ring.append((ATTACHMENT_MARKER_RADIUS * math.sin(angle), 0.0, ATTACHMENT_MARKER_RADIUS * math.cos(angle)))

    vertices: list[MeshVertex] = []
    triangles: list[MeshTriangle] = []

    def add_triangle(corners: tuple[tuple[float, float, float], ...]) -> None:
        edge1 = [b - a for a, b in zip(corners[0], corners[1])]
        edge2 = [c - a for a, c in zip(corners[0], corners[2])]
        normal = (
            edge1[1] * edge2[2] - edge1[2] * edge2[1],
            edge1[2] * edge2[0] - edge1[0] * edge2[2],
            edge1[0] * edge2[1] - edge1[1] * edge2[0],
        )
        length = math.sqrt(sum(axis * axis for axis in normal)) or 1.0
        normal = tuple(axis / length for axis in normal)
        start = len(vertices)
        for corner in corners:
            vertices.append(MeshVertex(position=corner, normal=normal, uv=(0.0, 0.0)))
        triangles.append(MeshTriangle(indices=(start, start + 1, start + 2)))

    for index, corner in enumerate(ring):
        following = ring[(index + 1) % len(ring)]
        add_triangle((corner, following, apex))
        add_triangle((following, corner, base_centre))
    return MeshData(vertices=vertices, triangles=triangles)


def _material_order(part: UnitPart) -> tuple[list[MaterialDef], dict[tuple, int]]:
    order: list[MaterialDef] = []
    index_by_key: dict[tuple, int] = {}
    for mesh_part in part.meshes:
        for lod in mesh_part.lods:
            for material in lod.materials:
                key = _material_key(material)
                if key not in index_by_key:
                    index_by_key[key] = len(order)
                    order.append(material)
    return order, index_by_key


def _bone_scene_nodes(part: UnitPart) -> tuple[list[s.SceneNode], dict[str, int]]:
    if part.skeleton is None:
        return [], {}
    scene_nodes: list[s.SceneNode] = []
    index_by_name: dict[str, int] = {}
    for index, bone in enumerate(part.skeleton.bones):
        if bone.parent_index >= index:
            raise UnitBuildError(f"Bone '{bone.name}' is parented to a bone that comes after it.")
        node = _scene_node_for(
            bone.name,
            skeleton_bone_attributes(bone.max_handle, bone.is_limb),
            translation=bone.translation,
            rotation=bone.rotation,
        )
        node.parent_index = bone.parent_index + 1
        index_by_name[bone.name] = index
        scene_nodes.append(node)
    return scene_nodes, index_by_name


def _resolved_weights(
    lod_weights: list[list[tuple[str, float]]], bone_index_by_name: dict[str, int], vertex_count: int
) -> list[list[tuple[int, float]]]:
    resolved: list[list[tuple[int, float]]] = []
    for index in range(vertex_count):
        influences = lod_weights[index] if index < len(lod_weights) else []
        entries = []
        for bone_name, weight in influences:
            bone_index = bone_index_by_name.get(bone_name)
            if bone_index is None:
                raise UnitBuildError(f"Vertex group '{bone_name}' matches no bone in the skeleton.")
            # 1-based, the same convention SceneNode.parent_index and the model nodes' own
            # node_index use. Measured, not assumed: a box weighted to bn_spine1/bn_spine2 and
            # written 0-based came back out of BOB weighted to bn_spine/bn_spine1 - one bone too
            # early in every chain. Reading CA's nordic_leather_armour the same way turns its ids
            # into hips/spine/spine1/spine2/neck/neck1/shoulders/arms/upper legs, which is what a
            # torso armour is weighted to; the 0-based reading has a leather tunic weighted to the
            # head and the shins instead.
            entries.append((bone_index + 1, weight))
        if not entries:
            raise UnitBuildError("A weighted part has a vertex with no bone weights at all.")
        resolved.append(entries)
    return resolved


def build_unit_cs2_document(part: UnitPart, assembly_kit_root: str, output_path: str = "") -> s.CS2Document:
    if not part.meshes or not any(mesh_part.lods for mesh_part in part.meshes):
        raise UnitBuildError(f"Unit part '{part.name}' has no meshes to export.")
    if part.is_weighted and part.skeleton is None:
        raise UnitBuildError(f"Weighted unit part '{part.name}' has no skeleton to weight against.")

    material_order, material_index_by_key = _material_order(part)
    scene_nodes, bone_index_by_name = _bone_scene_nodes(part)

    rigid_models: list[s.RigidModelNode] = []
    weighted_models: list[s.WeightedModelNode] = []

    for mesh_part in part.meshes:
        for lod in sorted(mesh_part.lods, key=lambda entry: entry.lod_index):
            node_name = unit_lod_node_name(mesh_part.name, lod.lod_index)
            material_ids = [material_index_by_key[_material_key(material)] for material in lod.materials]
            node_index = len(scene_nodes) + 1
            # Real unit mesh nodes carry no node attributes at all, unlike every building node.
            attributes = s.NodeAttributes()
            if part.is_weighted:
                weighted_models.append(
                    s.WeightedModelNode(
                        node_name=node_name,
                        node_metadata_string="",
                        user_defined_properties="",
                        node_index=node_index,
                        attributes=attributes,
                        geometry_chunks=[
                            _weighted_geometry_chunk(
                                lod.mesh,
                                _resolved_weights(lod.weights, bone_index_by_name, len(lod.mesh.vertices)),
                                material_ids,
                            )
                        ],
                    )
                )
            else:
                rigid_models.append(
                    s.RigidModelNode(
                        node_name=node_name,
                        node_metadata_string="",
                        user_defined_properties="",
                        node_index=node_index,
                        attributes=attributes,
                        geometry_chunks=[
                            _rigid_geometry_chunk(lod.mesh, material_ids, include_uv=True, vertex_colors=False)
                        ],
                    )
                )
            scene_nodes.append(_scene_node_for(node_name, attributes))

    marker_material_id = 0 if material_order else -1
    for point in part.attachment_points:
        bone_index = bone_index_by_name.get(point.bone_name)
        if bone_index is None:
            raise UnitBuildError(
                f"Attachment point '{point.name}' targets bone '{point.bone_name}', which is not in the skeleton."
            )
        node_name = attachment_point_node_name(point.name)
        attributes = s.NodeAttributes()
        rigid_models.append(
            s.RigidModelNode(
                node_name=node_name,
                node_metadata_string="",
                user_defined_properties="",
                node_index=len(scene_nodes) + 1,
                attributes=attributes,
                geometry_chunks=[
                    _rigid_geometry_chunk(
                        _attachment_marker_mesh(),
                        material_id=marker_material_id,
                        include_uv=True,
                        compute_bounds=True,
                        vertex_colors=False,
                    )
                ],
            )
        )
        node = _scene_node_for(
            node_name, attributes, translation=point.translation, rotation=point.rotation
        )
        node.parent_index = bone_index + 1
        scene_nodes.append(node)

    details = t.build_details_string(
        username=getpass.getuser(),
        export_timestamp=datetime.now().strftime("%d/%m/%Y,%H:%M:%S"),
        cas_name_path=output_path,
    )

    materials = [
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
        for material in material_order
    ]

    return s.CS2Document(
        header=s.Header(
            file_format=t.FILE_FORMAT_MAGIC,
            exporter_version=t.EXPORTER_VERSION,
            feature_flags=t.FEATURE_FLAGS,
            plugin=t.get_plugin_header_string(),
            details=details,
        ),
        scene_block=s.SceneBlockData(
            format_compatibility_version=t.FORMAT_COMPATIBILITY_VERSION,
            object_types_count=t.OBJECT_TYPES_COUNT,
            lights_count=0,
            cameras_count=0,
            rigid_models_count=len(rigid_models),
            total_scene_vertex_count=0,
            weighted_models_count=len(weighted_models),
            lines_count=0,
            dummies_count=0,
            materials_count=len(materials),
            total_scene_triangle_count=0,
            instances_count=0,
            scene_bbox_and_world_matrix=t.SCENE_BBOX_AND_WORLD_MATRIX,
        ),
        timeline_block=s.TimelineBlockData(
            frame_rate_fps=t.TIMELINE_FRAME_RATE_FPS,
            start_frame_time=t.TIMELINE_START_FRAME_TIME,
            end_frame_time=t.TIMELINE_END_FRAME_TIME,
            track_metadata=t.TIMELINE_TRACK_METADATA,
        ),
        morph_block=s.MorphAndSplineBlockData(morph_track_flags=t.MORPH_TRACK_FLAGS, tracks=[]),
        cameras=[],
        rigid_models=rigid_models,
        weighted_models=weighted_models,
        lines=[],
        dummies=[],
        # A unit part carries the identity scene root rotation a building does, not the skeleton's
        # half turn about Y - checked byte for byte against all four CA-authored unit sources, whose
        # SceneHierarchyMetadata equals this add-on's building constant exactly. The embedded bone
        # tree is in the skeleton file's own space (nordic_leather_armour's bone world transforms
        # reproduce rome_man_game.cs2's to the last digit), and so are the mesh vertices, so BOB
        # applies the half turn from the skeleton it is told about rather than from this file.
        scene_root=s.SceneRootNode(
            node_name=t.SCENE_ROOT_NODE_NAME,
            up_axis_orientation=t.SCENE_ROOT_UP_AXIS_ORIENTATION,
            scene_unit_scale=t.SCENE_ROOT_UNIT_SCALE,
            scene_hierarchy_metadata=t.SCENE_ROOT_HIERARCHY_METADATA,
            info=details,
            active_camera_index=0,
            active_light_index=0,
            root_end_padding=t.SCENE_ROOT_END_PADDING,
            scene_nodes=scene_nodes,
        ),
        materials=materials,
        instances=[],
    )


__all__ = ["UnitBuildError", "build_unit_cs2_document"]
