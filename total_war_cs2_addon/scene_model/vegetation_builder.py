import getpass
from datetime import datetime

from binary import cs2_structures as s
from binary import cs2_templates as t
from materials.template import build_directx_material_node
from naming.naming import skeleton_bone_attributes, vegetation_lod_node_name
from .cs2_builder import _material_key, _scene_node_for, _weighted_geometry_chunk
from .models import MaterialDef
from .vegetation_models import (
    TREE_ANCHOR_BONE,
    TREE_BONE_NAMES,
    TREE_WIND_BONE,
    VegetationModel,
)


class VegetationBuildError(Exception):
    pass


def _material_order(model: VegetationModel) -> tuple[list[MaterialDef], dict[tuple, int]]:
    order: list[MaterialDef] = []
    index_by_key: dict[tuple, int] = {}
    for lod in model.lods:
        for material in lod.materials:
            key = _material_key(material)
            if key not in index_by_key:
                index_by_key[key] = len(order)
                order.append(material)
    return order, index_by_key


def _bone_scene_nodes() -> list[s.SceneNode]:
    # Two bones at the origin, so every vertex position comes back out of BOB in the space it was
    # authored in: the compiled tree vertex stores the position once per influence, each relative to
    # that influence's own bone, and a real compile against a bone two metres up came back with the
    # whole mesh shifted down by exactly that much.
    nodes = []
    for index, name in enumerate(TREE_BONE_NAMES):
        node = _scene_node_for(name, skeleton_bone_attributes(index + 1, index > 0))
        node.parent_index = index
        nodes.append(node)
    return nodes


def _influences(wind_weight: float) -> list[tuple[int, float]]:
    wind = min(max(wind_weight, 0.0), 1.0)
    return [(TREE_ANCHOR_BONE, 1.0 - wind), (TREE_WIND_BONE, wind)]


def build_vegetation_cs2_document(
    model: VegetationModel, assembly_kit_root: str, output_path: str = ""
) -> s.CS2Document:
    if not model.lods:
        raise VegetationBuildError(f"Vegetation model '{model.name}' has no LODs to export.")

    material_order, material_index_by_key = _material_order(model)
    scene_nodes = _bone_scene_nodes()
    weighted_models: list[s.WeightedModelNode] = []

    for lod in sorted(model.lods, key=lambda entry: entry.lod_index):
        node_name = vegetation_lod_node_name(model.name, lod.lod_index)
        material_ids = [material_index_by_key[_material_key(material)] for material in lod.materials]
        weights = [
            _influences(lod.wind_weights[index] if index < len(lod.wind_weights) else 0.0)
            for index in range(len(lod.mesh.vertices))
        ]
        attributes = s.NodeAttributes()
        weighted_models.append(
            s.WeightedModelNode(
                node_name=node_name,
                node_metadata_string="",
                user_defined_properties="",
                node_index=len(scene_nodes) + 1,
                attributes=attributes,
                geometry_chunks=[_weighted_geometry_chunk(lod.mesh, weights, material_ids)],
            )
        )
        scene_nodes.append(_scene_node_for(node_name, attributes))

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
            gloss_texture_path=material.gloss_texture_path,
            specular_texture_path=material.specular_texture_path,
            alpha_mode=material.alpha_mode,
            vec4_colours=material.tree_colours,
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
            rigid_models_count=0,
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
        rigid_models=[],
        weighted_models=weighted_models,
        lines=[],
        dummies=[],
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


__all__ = ["VegetationBuildError", "build_vegetation_cs2_document"]
