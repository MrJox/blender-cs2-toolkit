import math
from pathlib import Path

import bpy

from binary import rigid_model_v2_structures as rs
from binary.rigid_model_v2_reader import read_rigid_model_v2
from materials.material_builder import TW_PLACEHOLDER_MARKER, create_total_war_material
from props.properties import TW_ROLE_LABELS, VEGETATION_LOD_IDENTIFIER_BY_INDEX
from scene_model.vegetation_models import LOD_CAMERA_DISTANCES
from .rigid_model_v2_importer import TEXTURE_NODE_BY_ID, _load_texture

SHADER_TYPE_BY_FLAGS = {
    rs.SHADER_TREE_V5: "tree",
    rs.SHADER_LEAF_V5: "tree_leaf",
}

# The three VEC4_PARAM_COLOUR_ slots every vegetation mesh carries, kept on the Blender material so
# the exporter can write back what the file said. They are shader constants, not textures, so
# nothing in the preview graph reads them.
COLOUR_PARAM_PROPERTIES = {1: "tw_tree_colour_0", 2: "tw_tree_colour_1", 3: "tw_tree_colour_2"}

SUBOBJECT_SUFFIX = " subobject "


def _to_blender_space(vector) -> tuple[float, float, float]:
    x, y, z = vector
    return (x, z, y)


def _resolve_texture(path: str, model_path: Path) -> str:
    # A vegetation texture lives beside the models but not under them - the compiled path is rooted
    # at battleterrain/, and the folder that path is relative to is an ancestor of the model's own
    # folder without being named working_data, which is the only root the unit importer looks for.
    relative = path.replace("\\", "/")
    for ancestor in model_path.parents:
        candidate = ancestor / relative
        if candidate.is_file():
            return str(candidate)
    return path


def is_vegetation_model(model: rs.RigidModelV2) -> bool:
    return any(mesh.shader_flags in rs.VEGETATION_SHADERS for lod in model.lods for mesh in lod.meshes)


def _material_for(mesh: rs.Mesh, model_path: Path) -> bpy.types.Material:
    header = mesh.material
    shader_type = SHADER_TYPE_BY_FLAGS[mesh.shader_flags]
    directory = header.texture_directory.rstrip("/") if header is not None else ""
    base = Path(directory).name if directory else model_path.stem
    name = f"{base}_{shader_type}"
    existing = bpy.data.materials.get(name)
    if existing is not None:
        return existing

    material = bpy.data.materials.new(name)
    material.tw_shader_type = shader_type
    # Leaf cards are cut-outs: their silhouette lives entirely in the diffuse alpha, so previewing
    # one without the clip shows opaque rectangles instead of foliage.
    material.tw_alpha_mode = "ALPHA_TEST" if mesh.shader_flags == rs.SHADER_LEAF_V5 else "NONE"
    material.use_backface_culling = False
    create_total_war_material(material)
    if header is None:
        return material

    for texture in header.textures:
        node = material.node_tree.nodes.get(TEXTURE_NODE_BY_ID.get(texture.texture_id, ""))
        if node is None or node.type != "TEX_IMAGE":
            continue
        image = _load_texture(_resolve_texture(texture.path, model_path), model_path)
        if image is None:
            continue
        if TW_PLACEHOLDER_MARKER in image:
            del image[TW_PLACEHOLDER_MARKER]
        node.image = image
    for parameter in header.vec4_params:
        property_name = COLOUR_PARAM_PROPERTIES.get(parameter.param_id)
        if property_name is not None:
            material[property_name] = list(parameter.value)
    return material


def _store_tree_vertex_data(mesh_data: bpy.types.Mesh, vertices) -> None:
    # The weight quad is (weight, weight, bone index, bone index), not four weights - measured by
    # compiling a tree through BOB with known influences and reading the result back. Only the first
    # weight is stored: the second is always 1 minus it. position0 is the vertex in the first bone's
    # own space; BOB recomputes it on export, so it is carried for fidelity rather than read back.
    position0 = mesh_data.attributes.new("tw_tree_position0", "FLOAT_VECTOR", "POINT")
    wind_weight = mesh_data.attributes.new("tw_tree_wind_weight", "FLOAT", "POINT")
    wind_bone = mesh_data.attributes.new("tw_tree_wind_bone", "INT", "POINT")
    anchor_bone = mesh_data.attributes.new("tw_tree_anchor_bone", "INT", "POINT")
    colour = mesh_data.color_attributes.new("Colour", "FLOAT_COLOR", "POINT")
    for index, vertex in enumerate(vertices):
        position0.data[index].vector = _to_blender_space(vertex.tree_position0 or (0.0, 0.0, 0.0))
        weights = vertex.tree_weights or (0.0, 1.0, 2.0, 0.0)
        wind_weight.data[index].value = weights[0]
        wind_bone.data[index].value = int(weights[2])
        anchor_bone.data[index].value = int(weights[3])
        colour.data[index].color = [channel / 255.0 for channel in (vertex.colour or (255, 255, 255, 255))]


def _build_mesh(name: str, meshes: list[rs.Mesh], materials: list[bpy.types.Material]) -> bpy.types.Mesh:
    # One Blender object per LOD carrying one material slot per subobject, rather than one object per
    # subobject: BOB splits a node by material itself, and that split is what the compiled
    # "<node> subobject N" names are. Keeping them apart in the scene would ask the artist to
    # maintain by hand a division the tools already make.
    positions: list[tuple[float, float, float]] = []
    triangles: list[tuple[int, int, int]] = []
    slot_of_triangle: list[int] = []
    vertices = []
    for slot, mesh in enumerate(meshes):
        offset = len(positions)
        positions.extend(_to_blender_space(vertex.position) for vertex in mesh.vertices)
        vertices.extend(mesh.vertices)
        # The axis swap is a reflection, so the file's corner order would leave every face wound
        # against its own normal - the same correction the building and unit importers make.
        for index in range(0, len(mesh.indices) - 2, 3):
            triangles.append(tuple(mesh.indices[index + step] + offset for step in (2, 1, 0)))
            slot_of_triangle.append(slot)

    mesh_data = bpy.data.meshes.new(name)
    mesh_data.from_pydata(positions, [], triangles)
    uv_layer = mesh_data.uv_layers.new(name="UVMap")
    for loop in mesh_data.loops:
        u, v = vertices[loop.vertex_index].uv
        uv_layer.data[loop.index].uv = (u, 1.0 - v)

    for material in materials:
        mesh_data.materials.append(material)
    for polygon, slot in zip(mesh_data.polygons, slot_of_triangle):
        polygon.material_index = slot

    normals = [_to_blender_space(vertex.normal) for vertex in vertices]
    if any(math.sqrt(sum(axis * axis for axis in normal)) > 0.01 for normal in normals):
        mesh_data.polygons.foreach_set("use_smooth", [True] * len(mesh_data.polygons))
        try:
            mesh_data.normals_split_custom_set([normals[loop.vertex_index] for loop in mesh_data.loops])
        except Exception:
            pass

    if all(mesh.vertex_format == rs.VERTEX_TREE for mesh in meshes):
        _store_tree_vertex_data(mesh_data, vertices)
    mesh_data.update()
    return mesh_data


def _lod_rung(camera_distance: float, fallback: int) -> int:
    # The rung, not the position in the file: a shrub whose meshes are named _lod02/_lod03 has two
    # LODs but they belong at 200m and 400m, and re-exporting it as LOD 1 and LOD 2 would move the
    # whole model a rung closer to the camera.
    for index, distance in enumerate(LOD_CAMERA_DISTANCES, start=1):
        if abs(distance - camera_distance) < 0.5:
            return index
    return fallback


# BOB appends " subobject N" per material split, so the part before it is the node the artist named.
def _node_name(meshes: list[rs.Mesh], fallback: str) -> str:
    for mesh in meshes:
        name = mesh.material.name if mesh.material is not None else ""
        if SUBOBJECT_SUFFIX in name:
            return name.split(SUBOBJECT_SUFFIX)[0]
        if name:
            return name
    return fallback


def import_vegetation(filepath: str, context: bpy.types.Context) -> tuple[bpy.types.Collection, list[str]]:
    path = Path(bpy.path.abspath(filepath))
    model = read_rigid_model_v2(path.read_bytes())
    warnings: list[str] = []

    root = bpy.data.collections.new(path.stem)
    root.tw_role = "VEGETATION"
    root["tw_bone_table_name"] = model.bone_table_name
    context.scene.collection.children.link(root)

    display = bpy.data.collections.new(TW_ROLE_LABELS["VEGETATION_DISPLAY"])
    display.tw_role = "VEGETATION_DISPLAY"
    root.children.link(display)

    lod_number = 0
    billboards = 0
    for lod in model.lods:
        # The billboard LOD is BOB's, rebuilt from the model on every compile, and so is the burn
        # hull in the sidecar beside it. Neither is authored and neither is exported, so importing
        # them would only put objects in the scene that an artist can edit to no effect.
        billboards += sum(
            1 for mesh in lod.meshes if mesh.shader_flags == rs.SHADER_CAMERA_ALIGNED_BILLBOARD_V6
        )
        renderables = [mesh for mesh in lod.meshes if mesh.shader_flags in SHADER_TYPE_BY_FLAGS]
        skipped = len(lod.meshes) - len(renderables) - sum(
            1 for mesh in lod.meshes if mesh.shader_flags == rs.SHADER_CAMERA_ALIGNED_BILLBOARD_V6
        )
        if skipped > 0:
            warnings.append(
                f"Skipped {skipped} mesh(es) at camera distance {lod.camera_distance:g} using a shader this "
                "add-on does not read as vegetation."
            )

        if not renderables:
            continue
        lod_number += 1
        rung = _lod_rung(lod.camera_distance, lod_number)
        name = _node_name(renderables, f"{path.stem}_lod{rung:02d}")
        materials = [_material_for(mesh, path) for mesh in renderables]
        obj = bpy.data.objects.new(name, _build_mesh(name, renderables, materials))
        obj.tw_vegetation_lod = VEGETATION_LOD_IDENTIFIER_BY_INDEX.get(rung, "LOD03")
        display.objects.link(obj)

    if lod_number == 0:
        warnings.append(f"'{path.name}' held no vegetation mesh this add-on could decode.")
    if billboards:
        warnings.append(
            f"'{path.name}' carries {billboards} generated billboard mesh(es), which were not imported - "
            "BOB builds the billboard from the model itself, so there is nothing in it to author."
        )
    return root, warnings


__all__ = ["import_vegetation", "is_vegetation_model"]
