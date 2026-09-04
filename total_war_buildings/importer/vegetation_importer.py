import math
import struct
from pathlib import Path

import bpy

from binary import rigid_model_v2_structures as rs
from binary.rigid_model_v2_reader import read_rigid_model_v2
from binary.vegetation_tech_reader import VegetationTechReader
from materials.material_builder import TW_PLACEHOLDER_MARKER, create_total_war_material
from props.properties import LOD_IDENTIFIER_BY_INDEX
from .rigid_model_v2_importer import TEXTURE_NODE_BY_ID, _load_texture

SHADER_TYPE_BY_FLAGS = {
    rs.SHADER_TREE_V5: "tree",
    rs.SHADER_LEAF_V5: "tree_leaf",
}

# The three VEC4_PARAM_COLOUR_ slots every vegetation mesh carries, kept on the Blender material so
# a future exporter can write back what the file said. They are shader constants, not textures, so
# nothing in the preview graph reads them.
COLOUR_PARAM_PROPERTIES = {1: "tw_tree_colour_0", 2: "tw_tree_colour_1", 3: "tw_tree_colour_2"}

FIRE_HULL_COLLECTION = "Fire Hull"
BILLBOARD_COLLECTION = "Billboard"
TECH_SUFFIX = "_tech.cs2.parsed"


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
    # position0 and the weight quad have no established meaning (PLAN_vegetation.md 1.4), so they
    # are carried through under the file's own field names rather than thrown away or renamed to a
    # guess. The first two weights always sum to 1, so weight 1 is not stored.
    position0 = mesh_data.attributes.new("tw_tree_position0", "FLOAT_VECTOR", "POINT")
    weight_0 = mesh_data.attributes.new("tw_tree_weight_0", "FLOAT", "POINT")
    weight_3 = mesh_data.attributes.new("tw_tree_weight_3", "FLOAT", "POINT")
    colour = mesh_data.color_attributes.new("Colour", "FLOAT_COLOR", "POINT")
    for index, vertex in enumerate(vertices):
        position0.data[index].vector = _to_blender_space(vertex.tree_position0 or (0.0, 0.0, 0.0))
        weights = vertex.tree_weights or (0.0, 0.0, 0.0, 0.0)
        weight_0.data[index].value = weights[0]
        weight_3.data[index].value = weights[3]
        colour.data[index].color = [channel / 255.0 for channel in (vertex.colour or (255, 255, 255, 255))]


def _build_mesh(name: str, mesh: rs.Mesh, material: bpy.types.Material) -> bpy.types.Mesh:
    positions = [_to_blender_space(vertex.position) for vertex in mesh.vertices]
    # The axis swap is a reflection, so the file's corner order would leave every face wound against
    # its own normal - the same correction the building and unit importers make.
    triangles = [
        (mesh.indices[index + 2], mesh.indices[index + 1], mesh.indices[index])
        for index in range(0, len(mesh.indices) - 2, 3)
    ]

    mesh_data = bpy.data.meshes.new(name)
    mesh_data.from_pydata(positions, [], triangles)
    uv_layer = mesh_data.uv_layers.new(name="UVMap")
    for loop in mesh_data.loops:
        u, v = mesh.vertices[loop.vertex_index].uv
        uv_layer.data[loop.index].uv = (u, 1.0 - v)

    normals = [_to_blender_space(vertex.normal) for vertex in mesh.vertices]
    if any(math.sqrt(sum(axis * axis for axis in normal)) > 0.01 for normal in normals):
        mesh_data.polygons.foreach_set("use_smooth", [True] * len(mesh_data.polygons))
        try:
            mesh_data.normals_split_custom_set([normals[loop.vertex_index] for loop in mesh_data.loops])
        except Exception:
            pass

    if mesh.vertex_format == rs.VERTEX_TREE:
        _store_tree_vertex_data(mesh_data, mesh.vertices)
    mesh_data.materials.append(material)
    mesh_data.update()
    return mesh_data


def _billboard_mesh(name: str, mesh: rs.Mesh) -> bpy.types.Mesh:
    positions = [_to_blender_space(vertex.position) for vertex in mesh.vertices]
    triangles = [
        (mesh.indices[index + 2], mesh.indices[index + 1], mesh.indices[index])
        for index in range(0, len(mesh.indices) - 2, 3)
    ]
    mesh_data = bpy.data.meshes.new(name)
    mesh_data.from_pydata(positions, [], triangles)
    uv_layer = mesh_data.uv_layers.new(name="UVMap")
    for loop in mesh_data.loops:
        u, v = mesh.vertices[loop.vertex_index].uv
        uv_layer.data[loop.index].uv = (u, 1.0 - v)
    mesh_data.update()
    return mesh_data


def _billboard_material(mesh: rs.Mesh, model_path: Path) -> bpy.types.Material | None:
    # Deliberately a plain Blender material, not a Total War one: RS_CAMERA_ALIGNED_BILLBOARD_V6 is
    # not a rigid_material an artist can assign, so giving it a tw_shader_type would claim the
    # add-on can author a billboard when BOB is the only thing that makes one.
    header = mesh.material
    if header is None or not header.textures:
        return None
    name = f"{model_path.stem}_billboard"
    material = bpy.data.materials.get(name)
    if material is not None:
        return material

    material = bpy.data.materials.new(name)
    material.use_nodes = True
    material.use_backface_culling = False
    material.surface_render_method = "DITHERED"
    principled = material.node_tree.nodes["Principled BSDF"]
    image = _load_texture(_resolve_texture(header.textures[0].path, model_path), model_path)
    if image is not None:
        if TW_PLACEHOLDER_MARKER in image:
            del image[TW_PLACEHOLDER_MARKER]
        texture = material.node_tree.nodes.new("ShaderNodeTexImage")
        texture.image = image
        texture.location = (-400, 300)
        material.node_tree.links.new(texture.outputs["Color"], principled.inputs["Base Color"])
        material.node_tree.links.new(texture.outputs["Alpha"], principled.inputs["Alpha"])
    return material


def _lod_collection(parent: bpy.types.Collection, lod_index: int, camera_distance: float) -> bpy.types.Collection:
    collection = bpy.data.collections.new(f"LOD {lod_index}")
    collection.tw_role = "VEGETATION_LOD"
    collection["tw_lod_camera_distance"] = camera_distance
    parent.children.link(collection)
    return collection


def _hull_object(tech, name: str) -> bpy.types.Object:
    hull = tech.hull
    positions = [_to_blender_space(vertex) for vertex in hull.vertices]
    triangles = []
    subobjects = []
    for index in range(hull.face_count):
        subobject, = struct.unpack_from("<I", hull.faces_bytes, index * 81)
        v0, v1, v2 = struct.unpack_from("<III", hull.faces_bytes, index * 81 + 5)
        if max(v0, v1, v2) >= len(positions):
            continue
        triangles.append((v2, v1, v0))
        subobjects.append(subobject)

    mesh_data = bpy.data.meshes.new(name)
    mesh_data.from_pydata(positions, [], triangles)

    owner_by_face = {}
    for node_index, node in enumerate(tech.vfx_nodes):
        for face_index in node.face_indices:
            owner_by_face[face_index] = node_index
    emitter = mesh_data.attributes.new("tw_fire_emitter", "INT", "FACE")
    source = mesh_data.attributes.new("tw_source_subobject", "INT", "FACE")
    for face_index in range(len(triangles)):
        emitter.data[face_index].value = owner_by_face.get(face_index, -1)
        source.data[face_index].value = subobjects[face_index]

    mesh_data.update()
    obj = bpy.data.objects.new(name, mesh_data)
    obj.display_type = "WIRE"
    return obj


def _emitter_objects(tech) -> list[bpy.types.Object]:
    # Every emitter transform in the whole game corpus is a pure translation and they all share one
    # action name, so one point-cloud object per distinct action carries the file exactly and keeps
    # a large tree from arriving as hundreds of empties.
    by_action: dict[str, list[tuple[float, float, float]]] = {}
    for node in tech.vfx_nodes:
        by_action.setdefault(node.name, []).append(
            _to_blender_space((node.transform[12], node.transform[13], node.transform[14]))
        )

    objects = []
    for action, points in by_action.items():
        mesh_data = bpy.data.meshes.new(action)
        mesh_data.from_pydata(points, [], [])
        mesh_data.update()
        obj = bpy.data.objects.new(action, mesh_data)
        obj["tw_vfx_action"] = action
        objects.append(obj)
    return objects


def _build_fire_hull(tech, parent: bpy.types.Collection, stem: str) -> bpy.types.Collection:
    collection = bpy.data.collections.new(FIRE_HULL_COLLECTION)
    collection.tw_role = "VEGETATION_FIRE"
    parent.children.link(collection)
    collection.objects.link(_hull_object(tech, tech.hull.name or f"{stem}_hull"))
    for obj in _emitter_objects(tech):
        collection.objects.link(obj)
    return collection


def find_tech_sidecar(model_path: Path) -> Path | None:
    candidate = model_path.with_name(f"{model_path.stem}{TECH_SUFFIX}")
    return candidate if candidate.is_file() else None


def import_vegetation_tech(
    filepath: str, context: bpy.types.Context, parent_collection: bpy.types.Collection | None = None
) -> tuple[bpy.types.Collection, list[str]]:
    path = Path(bpy.path.abspath(filepath))
    tech = VegetationTechReader.read_file(str(path))
    stem = path.name[: -len(TECH_SUFFIX)] if path.name.endswith(TECH_SUFFIX) else path.stem

    if parent_collection is None:
        parent_collection = bpy.data.collections.new(stem)
        parent_collection.tw_role = "VEGETATION"
        context.scene.collection.children.link(parent_collection)

    _build_fire_hull(tech, parent_collection, stem)
    emitters = len(tech.vfx_nodes)
    return parent_collection, [
        f"'{path.name}' holds the burn hull BOB derives from the lowest LOD ({tech.hull.face_count} faces) and "
        f"{emitters} fire emitter(s) it distributed over it. Both are generated - editing them changes nothing."
    ]


def import_vegetation(filepath: str, context: bpy.types.Context) -> tuple[bpy.types.Collection, list[str]]:
    path = Path(bpy.path.abspath(filepath))
    model = read_rigid_model_v2(path.read_bytes())
    warnings: list[str] = []

    root = bpy.data.collections.new(path.stem)
    root.tw_role = "VEGETATION"
    root["tw_bone_table_name"] = model.bone_table_name
    context.scene.collection.children.link(root)

    lod_number = 0
    for lod in model.lods:
        billboards = [mesh for mesh in lod.meshes if mesh.shader_flags == rs.SHADER_CAMERA_ALIGNED_BILLBOARD_V6]
        renderables = [mesh for mesh in lod.meshes if mesh.shader_flags in SHADER_TYPE_BY_FLAGS]
        skipped = len(lod.meshes) - len(billboards) - len(renderables)
        if skipped:
            warnings.append(
                f"Skipped {skipped} mesh(es) at camera distance {lod.camera_distance:g} using a shader this "
                "add-on does not read as vegetation."
            )

        if billboards:
            collection = bpy.data.collections.new(BILLBOARD_COLLECTION)
            collection.tw_role = "VEGETATION_BILLBOARD"
            collection["tw_lod_camera_distance"] = lod.camera_distance
            root.children.link(collection)
            for mesh in billboards:
                name = mesh.material.name if mesh.material is not None and mesh.material.name else "billboard"
                obj = bpy.data.objects.new(name, _billboard_mesh(name, mesh))
                material = _billboard_material(mesh, path)
                if material is not None:
                    obj.data.materials.append(material)
                collection.objects.link(obj)

        if not renderables:
            continue
        lod_number += 1
        collection = _lod_collection(root, lod_number, lod.camera_distance)
        for mesh in renderables:
            header_name = mesh.material.name if mesh.material is not None else ""
            name = header_name or f"{path.stem}_lod{lod_number}"
            obj = bpy.data.objects.new(name, _build_mesh(name, mesh, _material_for(mesh, path)))
            obj.tw_lod_index = LOD_IDENTIFIER_BY_INDEX.get(lod_number, "LOD05")
            collection.objects.link(obj)

    if lod_number == 0:
        warnings.append(f"'{path.name}' held no vegetation mesh this add-on could decode.")

    sidecar = find_tech_sidecar(path)
    if sidecar is not None:
        _, tech_warnings = import_vegetation_tech(str(sidecar), context, root)
        warnings.extend(tech_warnings)
    else:
        warnings.append(
            f"No '{path.stem}{TECH_SUFFIX}' beside the model, so its burn hull and fire emitters were not "
            "imported."
        )
    return root, warnings


__all__ = ["import_vegetation", "import_vegetation_tech", "is_vegetation_model", "find_tech_sidecar"]
