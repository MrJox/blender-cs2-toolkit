import bpy

from props.properties import VEGETATION_LOD_INDEX_BY_IDENTIFIER
from scene_model.vegetation_models import VegetationLod, VegetationModel
from .extract import ExtractionError, _convert_mesh_indexed, _read_object_materials

WIND_WEIGHT_ATTRIBUTE = "tw_tree_wind_weight"


def vegetation_display_collections(model_collection: bpy.types.Collection) -> list[bpy.types.Collection]:
    return [child for child in model_collection.children if child.tw_role == "VEGETATION_DISPLAY"]


def vegetation_mesh_objects(model_collection: bpy.types.Collection) -> list[bpy.types.Object]:
    return [
        obj
        for display in vegetation_display_collections(model_collection)
        for obj in display.objects
        if obj.type == "MESH"
    ]


def _wind_weights(obj: bpy.types.Object, source_indices: list[int]) -> list[float]:
    attribute = obj.data.attributes.get(WIND_WEIGHT_ATTRIBUTE)
    if attribute is None or attribute.domain != "POINT" or attribute.data_type != "FLOAT":
        return []
    per_source = [entry.value for entry in attribute.data]
    return [per_source[index] if index < len(per_source) else 0.0 for index in source_indices]


def _extract_lod(obj: bpy.types.Object, depsgraph: bpy.types.Depsgraph) -> VegetationLod:
    materials = _read_object_materials(obj)
    if not materials:
        raise ExtractionError(f"'{obj.name}' has no material assigned.")
    mesh, source_indices = _convert_mesh_indexed(obj, depsgraph)
    return VegetationLod(
        lod_index=VEGETATION_LOD_INDEX_BY_IDENTIFIER[obj.tw_vegetation_lod],
        mesh=mesh,
        materials=materials,
        wind_weights=_wind_weights(obj, source_indices) or [0.0] * len(mesh.vertices),
    )


def extract_vegetation(
    model_collection: bpy.types.Collection, depsgraph: bpy.types.Depsgraph
) -> tuple[VegetationModel, list[str]]:
    warnings: list[str] = []
    objects = vegetation_mesh_objects(model_collection)
    if not objects:
        raise ExtractionError(f"'{model_collection.name}' has no meshes to export.")

    lods = []
    seen: dict[int, str] = {}
    for obj in objects:
        lod = _extract_lod(obj, depsgraph)
        existing = seen.get(lod.lod_index)
        if existing is not None:
            raise ExtractionError(
                f"'{obj.name}' and '{existing}' are both LOD {lod.lod_index} - each mesh of a vegetation "
                "model needs its own LOD Level."
            )
        seen[lod.lod_index] = obj.name
        lods.append(lod)

    return VegetationModel(name=model_collection.name, lods=lods), warnings


__all__ = ["extract_vegetation", "vegetation_display_collections", "vegetation_mesh_objects"]
