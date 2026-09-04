import math
import re
from pathlib import Path

import bpy
import mathutils

from binary import rigid_model_v2_structures as rs
from binary.rigid_model_v2_reader import read_rigid_model_v2
from extraction.bone_space import blender_bone_to_engine, blender_object_to_engine
from extraction.skeleton_extract import extract_skeleton_from_armature
from extraction.unit_extract import armature_of
from materials.material_builder import TW_PLACEHOLDER_MARKER, create_total_war_material
from materials.shader_types import SHADER_TYPE_IDENTIFIERS
from props.properties import (
    LOD_IDENTIFIER_BY_INDEX,
    get_assembly_kit_root_or_empty,
)
from scene_model.skeleton_models import compiled_bone_order
from scene_model.unit_models import RIGID_ATTACHMENT_KIND, WEIGHTED_KIND
from .messages import ImportNote
from .skeleton_importer import import_skeleton_source
from .skeleton_lookup import find_skeleton_source, searched_locations

# The compiled shader id back to the rigid_material this add-on authors. Only the ones the add-on
# can round-trip are listed; anything else imports as "default" with a warning, so an unsupported
# shader never silently becomes a wrong one.
SHADER_TYPE_BY_FLAGS = {
    rs.SHADER_STANDARD_V5: "default",
    rs.SHADER_STANDARD_WITH_DECAL_DIRTMAP_V5: "default",
    rs.SHADER_STANDARD_TILED_DIRTMAP_V5: "tiled_dirtmap",
    rs.SHADER_WEIGHTED_V5: "weighted",
    rs.SHADER_WEIGHTED_SKIN_V5: "weighted_skin",
    rs.SHADER_WEIGHTED_WITH_DIRTMAP_V5: "weighted_dirtmap",
    rs.SHADER_WEIGHTED_SKIN_DIRTMAP_V5: "weighted_skin_dirtmap",
    rs.SHADER_WEIGHTED_WITH_DECAL_V5: "weighted_decal",
    rs.SHADER_WEIGHTED_WITH_DECAL_DIRTMAP_V5: "weighted_decal_dirtmap",
    rs.SHADER_WEIGHTED_SKIN_DECAL_V5: "weighted_skin_decal",
    rs.SHADER_WEIGHTED_SKIN_DECAL_DIRTMAP_V5: "weighted_skin_decal_dirtmap",
}

# rigid_model_v2_structures.TEXTURE_PARAM_NAMES id -> the texture node create_total_war_material
# builds for it. Slots with no node in the preview graph are deliberately absent.
TEXTURE_NODE_BY_ID = {
    0: "Diffuse",
    1: "Normal",
    3: "Mask",
    5: "Ambient Map",
    7: "Dirtmap",
    8: "Dirtmask",
    11: "Specular",
    12: "Gloss",
    13: "Decal Dirtmap",
    14: "Decal Dirtmask",
    15: "Decal Mask",
}


# A compiled mesh is not stored in the space this add-on authors in, and the two corrections it
# needs are different for the two kinds of mesh. Both were measured by compiling a deliberately
# asymmetric box through BOB and comparing the authored .CS2 against the result:
#
#   weighted - engine X and Z come back negated, Y untouched: the half turn about Y that the
#     skeleton's own scene root rotation carries and BOB applies (PLAN_units.md 1.4). Undoing it
#     puts the mesh back in the space a .cs2-imported skeleton lives in.
#   rigid - vertices are stored relative to MESH_HEADER_V5.pivot, with no rotation at all, so the
#     pivot has to be added back or the mesh arrives at the origin.
#
# The two never overlap in the 1134-mesh corpus: every mesh under a humanoid bone table (rome_man,
# rome_man_game) is weighted with a zero pivot, and every mesh with a non-zero pivot is rigid. The
# expression below still handles both at once, which is why it is written as one rule.
def _engine_to_blender_position(vector, pivot, half_turn: bool) -> tuple[float, float, float]:
    x, y, z = (axis + offset for axis, offset in zip(vector, pivot))
    if half_turn:
        x, z = -x, -z
    return (x, z, y)


def _engine_to_blender_normal(vector, half_turn: bool) -> tuple[float, float, float]:
    x, y, z = vector
    if half_turn:
        x, z = -x, -z
    return (x, z, y)


def _texture_search_roots(model_path: Path) -> list[Path]:
    # A compiled texture path is relative to working_data, and the models themselves live under it,
    # so walking up from the model's own folder finds the root without needing the add-on
    # preferences - which point at raw_data, not at the compiled tree.
    roots = [model_path.parent]
    for parent in model_path.parents:
        if parent.name.lower() == "working_data":
            roots.append(parent)
            break
    return roots


def _load_texture(path: str, model_path: Path) -> bpy.types.Image | None:
    if not path:
        return None
    name = Path(path.replace("\\", "/")).name
    for root in _texture_search_roots(model_path):
        for candidate in (root / path.replace("\\", "/"), root / name):
            if candidate.is_file():
                return bpy.data.images.load(str(candidate), check_existing=True)
    existing = bpy.data.images.get(name)
    if existing is not None:
        return existing
    # The compiled .dds usually is not on disk beside the model; a stub keeps the path visible in
    # the material so the artist can point it at the real file.
    image = bpy.data.images.new(name, width=4, height=4)
    image.filepath = path
    return image


def _material_for(mesh: rs.Mesh, model_path: Path, warnings: list[str]) -> bpy.types.Material:
    header = mesh.material
    base_name = header.name if header is not None and header.name else model_path.stem
    shader_type = SHADER_TYPE_BY_FLAGS.get(mesh.shader_flags)
    if shader_type is None:
        shader_type = "default"
        warnings.append(
            f"'{base_name}' uses compiled shader {mesh.shader_flags}, which this add-on cannot author - "
            "it was imported as Standard."
        )
    name = f"{base_name}_{shader_type}"
    material = bpy.data.materials.get(name)
    if material is not None:
        return material

    material = bpy.data.materials.new(name)
    if shader_type in SHADER_TYPE_IDENTIFIERS:
        material.tw_shader_type = shader_type
    create_total_war_material(material)

    if header is not None:
        for texture in header.textures:
            node_name = TEXTURE_NODE_BY_ID.get(texture.texture_id)
            node = material.node_tree.nodes.get(node_name) if node_name else None
            if node is None or node.type != "TEX_IMAGE":
                continue
            image = _load_texture(texture.path, model_path)
            if image is None:
                continue
            if TW_PLACEHOLDER_MARKER in image:
                del image[TW_PLACEHOLDER_MARKER]
            node.image = image
    return material


# naming.unit_lod_node_name builds "<model>_lod<N>", and BOB carries that straight into
# MeshHeaderV5.name for a rigid model - gondor_sword_01's four LODs are named gondor_sword_01_lod1
# through _lod4. Stripping the suffix is its exact inverse, and recovers the one model those four
# LODs belong to. A weighted model carries the bare name on every LOD, so this leaves it alone.
_LOD_SUFFIX = re.compile(r"^(?P<name>.+?)_lod\d+$", re.IGNORECASE)


def _model_name(mesh: rs.Mesh, model_path: Path) -> str:
    name = mesh.material.name if mesh.material is not None and mesh.material.name else ""
    if not name:
        return model_path.stem
    match = _LOD_SUFFIX.match(name)
    return match.group("name") if match else name


def _build_mesh(
    name: str, mesh: rs.Mesh, material: bpy.types.Material, warnings: list[str]
) -> bpy.types.Mesh:
    half_turn = mesh.shader_flags in rs.WEIGHTED_SHADERS
    pivot = mesh.material.pivot if mesh.material is not None else (0.0, 0.0, 0.0)
    positions = [_engine_to_blender_position(vertex.position, pivot, half_turn) for vertex in mesh.vertices]
    normals = [_engine_to_blender_normal(vertex.normal, half_turn) for vertex in mesh.vertices]
    # The axis swap is a reflection, so keeping the file's corner order would leave every face wound
    # against its own normal - the same correction importer.cs2_importer makes. The half turn is a
    # rotation and so leaves the winding alone.
    triangles = [
        (mesh.indices[index + 2], mesh.indices[index + 1], mesh.indices[index])
        for index in range(0, len(mesh.indices) - 2, 3)
    ]

    mesh_data = bpy.data.meshes.new(name)
    mesh_data.from_pydata(positions, [], triangles)
    uv_layer = mesh_data.uv_layers.new(name="UVMap")
    for polygon in mesh_data.polygons:
        for loop_index in polygon.loop_indices:
            vertex_index = mesh_data.loops[loop_index].vertex_index
            u, v = mesh.vertices[vertex_index].uv
            uv_layer.data[loop_index].uv = (u, 1.0 - v)

    if any(math.sqrt(sum(axis * axis for axis in normal)) > 0.01 for normal in normals):
        mesh_data.polygons.foreach_set("use_smooth", [True] * len(mesh_data.polygons))
        try:
            mesh_data.normals_split_custom_set([normals[loop.vertex_index] for loop in mesh_data.loops])
        except Exception as error:  # noqa: BLE001 - a mesh that shades wrong is still worth importing
            warnings.append(
                f"'{name}' kept Blender's own shading - the normals in the file could not be applied "
                f"to it: {error}"
            )

    mesh_data.materials.append(material)
    mesh_data.update()
    return mesh_data


def bone_names_by_compiled_index(armature_object: bpy.types.Object) -> list[str]:
    skeleton, _warnings = extract_skeleton_from_armature(armature_object, armature_object.name)
    return compiled_bone_order(skeleton)


def find_armature_for(bone_table_name: str) -> bpy.types.Object | None:
    if not bone_table_name:
        return None
    wanted = bone_table_name.lower()
    for collection in bpy.data.collections:
        if collection.tw_role == "SKELETON" and collection.name.lower() == wanted:
            for obj in collection.all_objects:
                if obj.type == "ARMATURE":
                    return obj
    for obj in bpy.data.objects:
        if obj.type == "ARMATURE" and obj.name.lower() == wanted:
            return obj
    return None


# The name a vertex group takes when no skeleton is available to say what compiled bone 11 is.
# bind_part_to_armature renames them once one turns up.
UNRESOLVED_GROUP_PREFIX = "bone_"


def unresolved_bone_index(group_name: str) -> int | None:
    if not group_name.startswith(UNRESOLVED_GROUP_PREFIX):
        return None
    suffix = group_name[len(UNRESOLVED_GROUP_PREFIX):]
    return int(suffix) if suffix.isdigit() else None


def models_needing_a_skeleton(collection: bpy.types.Collection) -> list[bpy.types.Collection]:
    def walk(current):
        yield current
        for child in current.children:
            yield from walk(child)

    needing = []
    for candidate in walk(collection):
        if candidate.tw_role != "UNIT_MESH" or candidate.tw_unit_part_kind != WEIGHTED_KIND:
            continue
        if any(armature_of(obj) is not None for obj in candidate.objects):
            continue
        if any(
            unresolved_bone_index(group.name) is not None
            for obj in candidate.all_objects
            for group in obj.vertex_groups
        ):
            needing.append(candidate)
    return needing


def _apply_vertex_groups(
    obj: bpy.types.Object, mesh: rs.Mesh, bone_names: list[str], warnings: list[str]
) -> None:
    groups: dict[str, bpy.types.VertexGroup] = {}
    missing: set[int] = set()
    for vertex_index, vertex in enumerate(mesh.vertices):
        for bone_index, weight in zip(vertex.bone_indices, vertex.bone_weights):
            if weight <= 0.0:
                continue
            if bone_index < len(bone_names):
                name = bone_names[bone_index]
            else:
                missing.add(bone_index)
                name = f"{UNRESOLVED_GROUP_PREFIX}{bone_index}"
            group = groups.get(name)
            if group is None:
                group = groups[name] = obj.vertex_groups.new(name=name)
            group.add([vertex_index], weight, "ADD")
    if missing:
        warnings.append(
            f"'{obj.name}' is weighted to bone index(es) {sorted(missing)[:5]} the skeleton in the scene does "
            "not have - those groups are named bone_<index> instead."
        )


def _import_attachment_points(
    mesh: rs.Mesh,
    part_collection: bpy.types.Collection,
    armature_object: bpy.types.Object | None,
    bone_names: list[str],
    warnings: list[str],
) -> None:
    if mesh.material is None:
        return
    for point in mesh.material.attachment_points:
        if part_collection.objects.get(point.name) is not None:
            continue
        empty = bpy.data.objects.new(point.name, None)
        empty.empty_display_type = "ARROWS"
        empty.empty_display_size = 0.05
        empty.tw_attachment_point_name = point.name
        part_collection.objects.link(empty)

        bone_name = bone_names[point.bone_index] if point.bone_index < len(bone_names) else ""
        if armature_object is None or bone_name not in armature_object.data.bones:
            warnings.append(
                f"Attachment point '{point.name}' targets compiled bone {point.bone_index}; with no matching "
                "skeleton in the scene it was placed at the origin, unparented."
            )
            continue
        empty.parent = armature_object
        empty.parent_type = "BONE"
        empty.parent_bone = bone_name
        # The compiled transform is 3 rows of (x, y, z, translation) in engine space, i.e. the
        # transpose of the row-vector 4x4 the CS2 side uses, and it is relative to the target bone.
        rows = point.transform
        rotation = mathutils.Matrix(
            ((rows[0][0], rows[0][1], rows[0][2]), (rows[1][0], rows[1][1], rows[1][2]), (rows[2][0], rows[2][1], rows[2][2]))
        ).transposed()
        local_engine = rotation.to_4x4()
        local_engine.translation = (rows[0][3], rows[1][3], rows[2][3])
        bone = armature_object.data.bones[bone_name]
        bone_world_engine = blender_bone_to_engine(armature_object.matrix_world @ bone.matrix_local)
        # blender_object_to_engine is its own inverse, so the same call converts back out of engine
        # space. Reading the compiled transform as bone-local this way is UNCONFIRMED beyond the
        # weapon_01..05 points, which are identity and so cannot tell the conventions apart; the
        # helmet crest points are the only non-identity sample.
        empty.matrix_world = blender_object_to_engine(bone_world_engine @ local_engine)


def import_rigid_model_v2(
    filepath: str, context: bpy.types.Context, parent_collection: bpy.types.Collection | None = None
) -> tuple[bpy.types.Collection, list[str]]:
    path = Path(bpy.path.abspath(filepath))
    model = read_rigid_model_v2(path.read_bytes())
    warnings: list[str] = []

    weighted = any(
        mesh.shader_flags in rs.WEIGHTED_SHADERS for lod in model.lods for mesh in lod.meshes
    )
    # One file is one unit asset, in the same shape the Unit workflow authors by hand, so it can be
    # edited, validated and exported like one built in Blender: a UNIT named after the asset - which
    # is what the export writes its file as - holding its models directly. A caller assembling
    # several files (the .vmd importer) passes a collection to group them under; each is still its
    # own asset.
    unit_collection = bpy.data.collections.new(path.stem)
    unit_collection.tw_role = "UNIT"
    (parent_collection or context.scene.collection).children.link(unit_collection)

    # A skeleton is only looked up for a model that both holds weighted meshes and names one. A
    # weapon, a shield or a building carries an empty bone table name and has nothing to look up,
    # so it must never trigger a search or a missing-skeleton message.
    needs_skeleton = weighted and bool(model.bone_table_name)
    armature_object = find_armature_for(model.bone_table_name) if needs_skeleton else None
    if needs_skeleton and armature_object is None:
        assembly_kit_root = get_assembly_kit_root_or_empty()
        source = find_skeleton_source(model.bone_table_name, path, assembly_kit_root)
        if source is not None:
            # import_skeleton_source links it at the scene root, which is where it belongs: a
            # skeleton is shared by every model weighted to it, so it is not part of any one unit.
            armature_object, _skeleton_collection, skeleton_warnings = import_skeleton_source(source, context)
            warnings.extend(skeleton_warnings)
            warnings.append(
                ImportNote(f"Skeleton '{model.bone_table_name}' was imported from {source.where}: {source.path}")
            )
        else:
            looked_in = "\n".join(f"  {folder}" for folder in searched_locations(path, assembly_kit_root))
            warnings.append(
                f"No skeleton named '{model.bone_table_name}' was found. Looked in:\n{looked_in}"
            )
    bone_names = bone_names_by_compiled_index(armature_object) if armature_object is not None else []

    kind = WEIGHTED_KIND if weighted else RIGID_ATTACHMENT_KIND
    part_collection = unit_collection

    mesh_collections: dict[str, bpy.types.Collection] = {}
    for lod_index, lod in enumerate(model.lods, start=1):
        for mesh in lod.meshes:
            if not mesh.vertices:
                warnings.append(
                    f"A LOD{lod_index} mesh uses vertex format {mesh.vertex_format}, which this add-on cannot "
                    "decode, and was skipped."
                )
                continue
            mesh_name = _model_name(mesh, path)
            mesh_collection = mesh_collections.get(mesh_name)
            if mesh_collection is None:
                # One model per named mesh in the file, holding that model's LOD objects. The Model
                # Type lives here, on the model, not on the asset above it.
                mesh_collection = bpy.data.collections.new(mesh_name)
                mesh_collection.tw_role = "UNIT_MESH"
                mesh_collection.tw_unit_part_kind = kind
                part_collection.children.link(mesh_collection)
                mesh_collections[mesh_name] = mesh_collection

            material = _material_for(mesh, path, warnings)
            obj = bpy.data.objects.new(
                f"{mesh_name}_lod{lod_index}",
                _build_mesh(f"{mesh_name}_lod{lod_index}", mesh, material, warnings),
            )
            obj.tw_lod_index = LOD_IDENTIFIER_BY_INDEX.get(lod_index, "LOD01")
            # Which debris track drives this mesh, for the .anim bundle importer to key it from.
            # Several meshes legitimately share one track (PLAN_units.md 1.5), and it is -1 on
            # everything that is not debris.
            obj.tw_debris_track_index = mesh.material.matrix_index if mesh.material is not None else -1
            mesh_collection.objects.link(obj)

            if needs_skeleton and mesh.vertices and mesh.vertices[0].bone_indices:
                _apply_vertex_groups(obj, mesh, bone_names, warnings)
                if armature_object is not None:
                    modifier = obj.modifiers.new(name="Armature", type="ARMATURE")
                    modifier.object = armature_object

            if lod_index == 1:
                _import_attachment_points(mesh, part_collection, armature_object, bone_names, warnings)

    if not mesh_collections:
        warnings.append(f"'{path.name}' held no mesh this add-on could decode.")
    return part_collection, warnings


__all__ = [
    "import_rigid_model_v2",
    "find_armature_for",
    "bone_names_by_compiled_index",
    "models_needing_a_skeleton",
]
