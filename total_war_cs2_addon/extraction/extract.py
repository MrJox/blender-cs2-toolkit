import math

import bpy
import mathutils

from scene_model.models import (
    BuildingAsset,
    Piece,
    DestructLevel,
    LodMesh,
    CollisionMesh,
    SoftCollisionMesh,
    PlatformMesh,
    PlatformGroundMesh,
    FileReference,
    LineFeature,
    RegionZone,
    EFLine,
    DockingLine,
    ArrowEmitter,
    HeightMapMesh,
    Flag,
    DestructionAnimMesh,
    GateAnimMesh,
    MeshData,
    MeshVertex,
    MeshTriangle,
    MaterialDef,
    Vec3,
    Vec4,
)
from materials.material_builder import read_material_def
from extraction.animation import sample_object_animation
from naming.naming import HARD_COLLISION_LINE_TYPES
from props.properties import (
    EFLINE_ACTION_LABELS,
    LOD_INDEX_BY_IDENTIFIER,
    COLLISION_MESH_TYPES,
    COLLISION_TYPE_LABELS,
)


class ExtractionError(Exception):
    pass


def _children_with_role(collection: bpy.types.Collection, role: str) -> list[bpy.types.Collection]:
    return [child for child in collection.children if child.tw_role == role]


def _to_engine_space(vector: tuple[float, float, float]) -> tuple[float, float, float]:
    # Blender (like 3ds Max) authors Z-up right-handed; CS2 stores Y-up left-handed. The exact map
    # is pinned by gondor_fort_gateway_e's region_zone01, which carries the same four corners twice
    # in one node: as Max-space UDP text (y = 1.0 .. 5.5, z = 0.0) and as CS2 LINE geometry
    # (z = -2.2275 .. 2.2725 about a node translation of 3.2275, y = 0.0). Max y maps to engine z
    # with no sign change, traversal order included.
    x, y, z = vector
    return (x, z, y)


# _to_engine_space swaps two axes, so it is a reflection (determinant -1) and has no quaternion of
# its own - the change of basis has to be done as a matrix. The conjugate of a rotation by a
# reflection is still a rotation, so the result converts back to a quaternion cleanly.
_ENGINE_SPACE_MATRIX = mathutils.Matrix(((1.0, 0.0, 0.0), (0.0, 0.0, 1.0), (0.0, 1.0, 0.0)))


def _to_engine_rotation(rotation: mathutils.Quaternion) -> Vec4:
    q = (_ENGINE_SPACE_MATRIX @ rotation.to_matrix() @ _ENGINE_SPACE_MATRIX).to_quaternion()
    return (q.x, q.y, q.z, q.w)


def _to_engine_uv(uv) -> tuple[float, float]:
    # CS2 stores V with the D3D top-left origin, Blender uses the bottom-left one: measured across
    # the raw_data samples, 76-94% of wall polygons have V decreasing as world height increases.
    # 1 - v rather than -v so ordinary [0,1] coordinates stay in [0,1].
    return (uv[0], 1.0 - uv[1])


def _primary_uv_layer(mesh: bpy.types.Mesh):
    # uv_layers.active only follows the UV Maps list selection in the UI, so adding a second UV set
    # with that panel's + button silently makes it the exported diffuse channel. active_render is
    # the flag that actually marks the layer meant for rendering/export.
    for layer in mesh.uv_layers:
        if layer.active_render:
            return layer
    return mesh.uv_layers[0] if mesh.uv_layers else None


def _colour_attribute(mesh: bpy.types.Mesh):
    # ps_common_blend_decal takes its blend weight from 1 - vertex alpha, so terrain_blend meshes need
    # real vertex colours. Every other technique this add-on supports ignores them, and a mesh with no
    # colour attribute keeps the previous constant white, so this is additive.
    attributes = getattr(mesh, "color_attributes", None)
    if not attributes:
        return None
    # ShaderNodeVertexColor with an empty layer_name reads the *render* colour attribute, not the
    # UI-active one, so the export has to read the same attribute the preview does - exactly the trap
    # _primary_uv_layer documents for uv_layers.active_render. Verified by rendering a mesh whose two
    # attributes were deliberately assigned to different roles.
    render_name = getattr(mesh, "default_color_name", "") or getattr(attributes, "default_color_name", "")
    return attributes.get(render_name) or attributes.active_color or attributes[0]


def _vertex_colour(colours, loop_index: int, vertex_index: int) -> Vec4:
    if colours is None:
        return (1.0, 1.0, 1.0, 1.0)
    index = loop_index if colours.domain == "CORNER" else vertex_index
    try:
        return tuple(colours.data[index].color)
    except (IndexError, AttributeError):
        return (1.0, 1.0, 1.0, 1.0)


def _second_uv_layer(mesh: bpy.types.Mesh, primary, uv2_layer_name: str):
    # ps30_full_ao and ps30_full_dirtmap both read TEXCOORD1 unconditionally (AO and the dirtmask
    # sample TexCoord.zw), so channel 2 has to be exported whenever the mesh actually has a second
    # UV set. A named lookup alone is not enough: create_total_war_material defaults the "UV2" node's
    # uv_map to the literal string "UV2", which matches no real Blender layer name, so an
    # unresolvable or empty name means "not configured" and falls back to the mesh's own second
    # layer. A name that does resolve is honoured, including resolving to the primary layer, which
    # stays the artist's explicit way to say there is no distinct UV2 set.
    if uv2_layer_name:
        named = mesh.uv_layers.get(uv2_layer_name)
        if named is not None:
            return None if primary is not None and named.name == primary.name else named
    for layer in mesh.uv_layers:
        if primary is None or layer.name != primary.name:
            return layer
    return None


def has_second_uv_layer(mesh: bpy.types.Mesh, uv2_layer_name: str = "") -> bool:
    return _second_uv_layer(mesh, _primary_uv_layer(mesh), uv2_layer_name) is not None


def second_uv_layer_name(mesh: bpy.types.Mesh, uv2_layer_name: str = "") -> str:
    layer = _second_uv_layer(mesh, _primary_uv_layer(mesh), uv2_layer_name)
    return layer.name if layer is not None else ""


def _filled_material_slots(obj: bpy.types.Object) -> list[int]:
    return [index for index, slot in enumerate(obj.material_slots) if slot.material is not None]


def _convert_mesh(
    obj: bpy.types.Object,
    depsgraph: bpy.types.Depsgraph,
    apply_world_matrix: bool = True,
    uv2_layer_name: str = "",
) -> MeshData:
    return _convert_mesh_indexed(obj, depsgraph, apply_world_matrix, uv2_layer_name)[0]


# Every exported vertex is one mesh loop, so the mapping back to the object's own vertex indices is
# what lets bone weights (which live per source vertex) be carried across - see
# extraction.unit_extract.
def _convert_mesh_indexed(
    obj: bpy.types.Object,
    depsgraph: bpy.types.Depsgraph,
    apply_world_matrix: bool = True,
    uv2_layer_name: str = "",
) -> tuple[MeshData, list[int]]:
    obj_eval = obj.evaluated_get(depsgraph)
    mesh = obj_eval.to_mesh()
    if mesh is None or len(mesh.vertices) == 0:
        raise ExtractionError(f"'{obj.name}' has no geometry.")

    mesh.calc_loop_triangles()
    try:
        mesh.calc_normals_split()
    except AttributeError:
        pass

    uv_layer = _primary_uv_layer(mesh)
    uv2_layer = _second_uv_layer(mesh, uv_layer, uv2_layer_name)
    colours = _colour_attribute(mesh)
    world_matrix = obj_eval.matrix_world if apply_world_matrix else mathutils.Matrix.Identity(4)
    normal_matrix = world_matrix.to_3x3().inverted_safe().transposed()
    # Real CS2 samples wind every triangle so that cross(v1-v0, v2-v0) agrees with the stored
    # normal (97376 of 97505 triangles across all seven samples; 73 disagree, 56 are degenerate).
    # _to_engine_space is a reflection, which reverses that sense on its own, and a mirrored object
    # (negative scale on an odd number of axes) reverses it again - so the corners need re-ordering
    # when exactly one of the two applies.
    mirrored = world_matrix.to_3x3().determinant() < 0.0
    reverse_winding = not mirrored
    # _read_object_materials drops empty slots, so a polygon's slot index has to be pulled back by
    # however many empty slots precede it or it lands on the wrong material.
    material_remap = {slot: position for position, slot in enumerate(_filled_material_slots(obj))}

    vertices: list[MeshVertex] = []
    source_indices: list[int] = []
    triangles: list[MeshTriangle] = []
    for tri in mesh.loop_triangles:
        corner_indices = []
        for loop_index in tri.loops:
            loop = mesh.loops[loop_index]
            vertex = mesh.vertices[loop.vertex_index]
            local_normal = loop.normal if loop.normal.length > 0 else vertex.normal
            position = _to_engine_space(tuple(world_matrix @ vertex.co))
            normal = _to_engine_space(tuple((normal_matrix @ local_normal).normalized()))
            uv = _to_engine_uv(uv_layer.data[loop_index].uv) if uv_layer is not None else (0.0, 0.0)
            uv2 = _to_engine_uv(uv2_layer.data[loop_index].uv) if uv2_layer is not None else None
            colour = _vertex_colour(colours, loop_index, loop.vertex_index)
            vertices.append(MeshVertex(position=position, normal=normal, uv=uv, uv2=uv2, color=colour))
            source_indices.append(loop.vertex_index)
            corner_indices.append(len(vertices) - 1)
        if reverse_winding:
            corner_indices.reverse()
        triangles.append(
            MeshTriangle(
                indices=tuple(corner_indices),
                material_index=material_remap.get(tri.material_index, 0),
            )
        )

    obj_eval.to_mesh_clear()
    return MeshData(vertices=vertices, triangles=triangles), source_indices


def _uv2_layer_name(materials: list[MaterialDef]) -> str:
    for material in materials:
        if material.uv2_layer_name:
            return material.uv2_layer_name
    return ""


def _read_object_materials(obj: bpy.types.Object) -> list[MaterialDef]:
    materials = [
        read_material_def(obj.material_slots[index].material)
        for index in _filled_material_slots(obj)
    ]
    if not materials and obj.active_material is not None:
        materials.append(read_material_def(obj.active_material))
    return materials


def _extract_lod(obj: bpy.types.Object, depsgraph: bpy.types.Depsgraph) -> LodMesh:
    materials = _read_object_materials(obj)
    if not materials:
        raise ExtractionError(f"'{obj.name}' has no material assigned.")
    mesh = _convert_mesh(obj, depsgraph, uv2_layer_name=_uv2_layer_name(materials))
    lod_index = LOD_INDEX_BY_IDENTIFIER[obj.tw_lod_index]
    return LodMesh(lod_index=lod_index, mesh=mesh, materials=materials)


def _extract_local_mesh_with_materials(obj: bpy.types.Object, depsgraph: bpy.types.Depsgraph) -> tuple[MeshData, list[MaterialDef]]:
    # Local-space counterpart of _extract_lod, for node kinds where the SceneNode keyframe carries
    # the real placement (arrow emitters/flag/file references already establish this pattern; here
    # it's what lets a moving transform track do real work instead of geometry pre-baked into world
    # space at frame 0).
    materials = _read_object_materials(obj)
    if not materials:
        raise ExtractionError(f"'{obj.name}' has no material assigned.")
    mesh = _convert_mesh(obj, depsgraph, apply_world_matrix=False, uv2_layer_name=_uv2_layer_name(materials))
    return mesh, materials


def _extract_destruction_anim_meshes(
    collection: bpy.types.Collection, depsgraph: bpy.types.Depsgraph, scene: bpy.types.Scene, warnings: list[str]
) -> list[DestructionAnimMesh]:
    meshes: list[DestructionAnimMesh] = []
    for obj in collection.objects:
        if obj.type != "MESH":
            continue
        try:
            mesh, materials = _extract_local_mesh_with_materials(obj, depsgraph)
        except ExtractionError as error:
            warnings.append(f"'{obj.name}' was skipped: {error}")
            continue
        keyframes = sample_object_animation(obj, depsgraph, scene, _to_engine_space, _to_engine_rotation)
        meshes.append(DestructionAnimMesh(mesh=mesh, keyframes=keyframes, materials=materials))
    return meshes


def _extract_gate_anim_meshes(
    display_collection: bpy.types.Collection, depsgraph: bpy.types.Depsgraph, scene: bpy.types.Scene, warnings: list[str]
) -> list[GateAnimMesh]:
    meshes: list[GateAnimMesh] = []
    for gate_anim_collection in _children_with_role(display_collection, "GATE_ANIMATION"):
        for obj in gate_anim_collection.objects:
            if obj.type != "MESH":
                continue
            try:
                mesh, materials = _extract_local_mesh_with_materials(obj, depsgraph)
            except ExtractionError as error:
                warnings.append(f"'{obj.name}' was skipped: {error}")
                continue
            keyframes = sample_object_animation(obj, depsgraph, scene, _to_engine_space, _to_engine_rotation)
            meshes.append(
                GateAnimMesh(gate_anim_kind=obj.tw_gate_anim_kind, mesh=mesh, keyframes=keyframes, materials=materials)
            )
    return meshes


def _extract_collision(collision_collection: bpy.types.Collection, depsgraph: bpy.types.Depsgraph, warnings: list[str]) -> CollisionMesh | None:
    supported_objects = [obj for obj in collision_collection.objects if obj.type == "MESH" and obj.tw_collision_type == "COLLISION"]
    unsupported_objects = [
        obj
        for obj in collision_collection.objects
        if obj.type == "MESH" and obj.tw_collision_type not in COLLISION_MESH_TYPES + ("SOFT_COLLISION",)
    ]

    for obj in unsupported_objects:
        warnings.append(
            f"'{obj.name}' uses collision type '{obj.tw_collision_type}', which isn't supported yet and was skipped."
        )

    if not supported_objects:
        return None
    if len(supported_objects) > 1:
        warnings.append(
            f"Destruct level has {len(supported_objects)} collision meshes; only '{supported_objects[0].name}' was used."
        )
    return CollisionMesh(mesh=_convert_mesh(supported_objects[0], depsgraph))


def _extract_soft_collision(
    collision_collection: bpy.types.Collection, depsgraph: bpy.types.Depsgraph, warnings: list[str]
) -> SoftCollisionMesh | None:
    supported_objects = [obj for obj in collision_collection.objects if obj.type == "MESH" and obj.tw_collision_type == "SOFT_COLLISION"]
    if not supported_objects:
        return None
    if len(supported_objects) > 1:
        warnings.append(
            f"Destruct level has {len(supported_objects)} soft collision meshes; only '{supported_objects[0].name}' was used."
        )
    return SoftCollisionMesh(mesh=_convert_mesh(supported_objects[0], depsgraph))


def _extract_gate_collision(
    collision_collection: bpy.types.Collection, collision_type: str, depsgraph: bpy.types.Depsgraph, warnings: list[str]
) -> CollisionMesh | None:
    objects = [obj for obj in collision_collection.objects if obj.type == "MESH" and obj.tw_collision_type == collision_type]
    if not objects:
        return None
    if len(objects) > 1:
        warnings.append(
            f"Destruct level has {len(objects)} '{COLLISION_TYPE_LABELS[collision_type]}' meshes; "
            f"only '{objects[0].name}' was used."
        )
    return CollisionMesh(mesh=_convert_mesh(objects[0], depsgraph))


def _extract_gate_display(
    display_collection: bpy.types.Collection, gate_role: str, depsgraph: bpy.types.Depsgraph, warnings: list[str]
) -> list[LodMesh]:
    lods: list[LodMesh] = []
    seen: dict[int, str] = {}
    for gate_collection in _children_with_role(display_collection, gate_role):
        for obj in gate_collection.objects:
            if obj.type != "MESH":
                continue
            try:
                lod = _extract_lod(obj, depsgraph)
            except ExtractionError as error:
                warnings.append(f"'{obj.name}' was skipped: {error}")
                continue
            existing = seen.get(lod.lod_index)
            if existing is not None:
                warnings.append(
                    f"'{obj.name}' and '{existing}' both use LOD Level '{obj.tw_lod_index}' in "
                    f"'{gate_collection.name}'; only the first was used."
                )
                continue
            seen[lod.lod_index] = obj.name
            lods.append(lod)
    return lods


def _orient_faces_upward(mesh: MeshData) -> int:
    # CONFIRMED BY A REAL BOB RUN: BOB's "which platform is this EFLine standing on" test only
    # accepts a platform polygon wound so its normal points up. On a building whose platform faces
    # pointed down in Blender, all 98 EFLines over an up-facing polygon were placed and all 27 over
    # a down-facing one failed with "couldn't find platform for efline" - no exceptions either way.
    # Real samples are up-facing throughout (28 of 28, 10 of 10), and a walkable surface facing down
    # has no meaning, so flipping is always the right reading of the artist's intent.
    flipped = 0
    for index, triangle in enumerate(mesh.triangles):
        v0, v1, v2 = (mesh.vertices[i].position for i in triangle.indices)
        edge1_x, edge1_z = v1[0] - v0[0], v1[2] - v0[2]
        edge2_x, edge2_z = v2[0] - v0[0], v2[2] - v0[2]
        if edge1_z * edge2_x - edge1_x * edge2_z >= 0.0:
            continue
        first, middle, last = triangle.indices
        mesh.triangles[index] = MeshTriangle(indices=(last, middle, first), material_index=triangle.material_index)
        for vertex_index in triangle.indices:
            vertex = mesh.vertices[vertex_index]
            vertex.normal = (-vertex.normal[0], -vertex.normal[1], -vertex.normal[2])
        flipped += 1
    return flipped


def _extract_platform_mesh(obj: bpy.types.Object, depsgraph: bpy.types.Depsgraph, warnings: list[str]) -> MeshData:
    mesh = _convert_mesh(obj, depsgraph)
    flipped = _orient_faces_upward(mesh)
    if flipped:
        warnings.append(
            f"'{obj.name}' had {flipped} face(s) pointing downwards; they were flipped so the platform faces up. "
            "BOB can't place EFLines on a downward-facing platform - fix the normals in Blender "
            "(Mesh > Normals > Recalculate Outside, or Flip) to stop this recurring."
        )
    return mesh


def _extract_platforms(
    platform_collection: bpy.types.Collection, depsgraph: bpy.types.Depsgraph, warnings: list[str]
) -> list[PlatformMesh]:
    mesh_objects = [
        obj for obj in platform_collection.objects if obj.type == "MESH" and obj.tw_platform_type == "PLATFORM"
    ]
    return [
        PlatformMesh(variation_index=variation_index, mesh=_extract_platform_mesh(obj, depsgraph, warnings))
        for variation_index, obj in enumerate(mesh_objects, start=1)
    ]


def _extract_platform_ground(
    platform_collection: bpy.types.Collection, depsgraph: bpy.types.Depsgraph, warnings: list[str]
) -> PlatformGroundMesh | None:
    supported_objects = [
        obj for obj in platform_collection.objects if obj.type == "MESH" and obj.tw_platform_type == "PLATFORM_GROUND"
    ]
    if not supported_objects:
        return None
    if len(supported_objects) > 1:
        warnings.append(
            f"Destruct level has {len(supported_objects)} Platform Ground meshes; only '{supported_objects[0].name}' was used."
        )
    return PlatformGroundMesh(mesh=_extract_platform_mesh(supported_objects[0], depsgraph, warnings))


def _curve_world_points(obj: bpy.types.Object, depsgraph: bpy.types.Depsgraph, force_closed: bool = False) -> tuple[list[Vec3], bool]:
    if obj.type != "CURVE":
        raise ExtractionError(f"'{obj.name}' must be a curve object.")
    if len(obj.data.splines) != 1:
        raise ExtractionError(f"'{obj.name}' must have exactly one spline (found {len(obj.data.splines)}).")

    closed = force_closed or obj.data.splines[0].use_cyclic_u

    obj_eval = obj.evaluated_get(depsgraph)
    mesh = obj_eval.to_mesh()
    if mesh is None or len(mesh.vertices) == 0:
        obj_eval.to_mesh_clear()
        raise ExtractionError(f"'{obj.name}' has no curve geometry.")

    world_matrix = obj_eval.matrix_world
    points = [_to_engine_space(tuple(world_matrix @ v.co)) for v in mesh.vertices]
    obj_eval.to_mesh_clear()

    if closed and points[0] != points[-1]:
        points.append(points[0])
    return points, closed


def _sample_curve_points(obj: bpy.types.Object, depsgraph: bpy.types.Depsgraph, force_closed: bool = False) -> tuple[list[Vec3], bool]:
    points, closed = _curve_world_points(obj, depsgraph, force_closed)
    return _subdivide_line_points(points), closed


def _subdivide_line_points(points: list[Vec3]) -> list[Vec3]:
    # Confirmed from every real LINE sample in Input/examples/raw_data/ (open and closed alike):
    # vertex count is always 3*(edge count)+1 - e.g. a real ground_ad's 4 vertices for its single
    # authored edge are exactly the 1/3 and 2/3 linear-interpolation points between its two
    # endpoints (verified to float precision), and closed hard/outline/region_zone lines follow the
    # same rule per edge (13 verts = 4 edges, 19 verts = 6 edges). LineSegments is a fixed, seemingly
    # inert `(3, 0)` tuple repeated once per edge (see `_line_segments_for`) - actual connectivity is
    # just the vertex array's own order, corner list or not.
    if len(points) < 2:
        return points
    subdivided: list[Vec3] = [points[0]]
    for a, b in zip(points, points[1:]):
        subdivided.append(tuple(a[i] + (b[i] - a[i]) / 3.0 for i in range(3)))
        subdivided.append(tuple(a[i] + (b[i] - a[i]) * 2.0 / 3.0 for i in range(3)))
        subdivided.append(b)
    return subdivided


def _extract_line_features(lines_collection: bpy.types.Collection, depsgraph: bpy.types.Depsgraph, warnings: list[str]) -> list[LineFeature]:
    features: list[LineFeature] = []
    variation_counters: dict[str, int] = {}
    for obj in lines_collection.objects:
        if obj.type != "CURVE":
            continue
        line_type = obj.tw_line_type
        try:
            # OUTLINE and HARD must be closed loops - confirmed from every real sample checked
            # (vertices[0] == vertices[-1] always, hard01 included). An open outline was found to
            # hang BOB during tech processing (a boundary-walking algorithm presumably never finds
            # its way back to the start), so these are force-closed the same way region zones
            # already are, rather than relying on the artist remembering to mark the curve Cyclic.
            points, closed = _sample_curve_points(
                obj, depsgraph, force_closed=(line_type in HARD_COLLISION_LINE_TYPES)
            )
        except ExtractionError as error:
            warnings.append(f"'{obj.name}' was skipped: {error}")
            continue
        # Hard shares Outline's node name, so it has to share its numbering too - see
        # naming.line_feature_class_rigid_info.
        counter_key = "OUTLINE" if line_type in HARD_COLLISION_LINE_TYPES else line_type
        variation_index = variation_counters.get(counter_key, 0) + 1
        variation_counters[counter_key] = variation_index
        features.append(LineFeature(line_type=line_type, variation_index=variation_index, points=points, closed=closed))
    return features


def _extract_region_zones(region_zone_collection: bpy.types.Collection, depsgraph: bpy.types.Depsgraph, warnings: list[str]) -> list[RegionZone]:
    zones: list[RegionZone] = []
    variation_index = 0
    for obj in region_zone_collection.objects:
        if obj.type != "CURVE":
            continue
        if obj.data.splines and not obj.data.splines[0].use_cyclic_u:
            warnings.append(f"'{obj.name}' is not a closed (cyclic) curve; region zones must be closed loops - it will be closed automatically.")
        try:
            corners, _closed = _curve_world_points(obj, depsgraph, force_closed=True)
        except ExtractionError as error:
            warnings.append(f"'{obj.name}' was skipped: {error}")
            continue
        variation_index += 1
        # The closing repeat of the first corner is the loop's own, not an authored knot - see
        # naming.region_zone_user_defined_properties for why the un-tessellated corners are needed.
        zones.append(
            RegionZone(
                variation_index=variation_index,
                points=_subdivide_line_points(corners),
                corner_points=corners[:-1],
            )
        )
    return zones


def _ef_line_direction(start: Vec3, end: Vec3) -> Vec3:
    # Mirrors TWBuildingsTech.ms: perpendicular of the horizontal (X/Y) projection of end-start,
    # computed here in Blender's Z-up space, before _to_engine_space() is applied to the result -
    # same as every other new vector this feature introduces.
    dx = end[0] - start[0]
    dy = end[1] - start[1]
    length = math.sqrt(dx * dx + dy * dy)
    if length == 0.0:
        raise ExtractionError("An EFLine/DockingLine's start and end points must not be identical.")
    return (-dy / length, dx / length, 0.0)


def _direction_from_pointer(base: Vec3, tip: Vec3) -> Vec3:
    dx = tip[0] - base[0]
    dy = tip[1] - base[1]
    length = math.sqrt(dx * dx + dy * dy)
    if length == 0.0:
        raise ExtractionError("An EFLine/DockingLine's direction pointer has no horizontal length - it must point somewhere.")
    return (dx / length, dy / length, 0.0)


def _extract_ef_line_geometry(obj: bpy.types.Object, depsgraph: bpy.types.Depsgraph) -> tuple[Vec3, Vec3, Vec3]:
    # Two shapes are accepted. The 4-vertex one mirrors TWBuildingsTech.ms, which subdivides the
    # artist's 2-knot line and hangs a second spline off the midpoint pointing where the line faces:
    # v0 start, v1 midpoint, v2 end, v3 pointer tip. The direction is read back off that pointer
    # rather than recomputed, because both perpendicular signs occur in real content (79 of the 158
    # real markers match normalize[-dy, dx, 0] and the other 79 are its opposite), so the facing is
    # authored, not derivable from endpoint order. The 2-vertex shape is what this add-on accepted
    # before the pointer existed; it still works, falling back to the MaxScript's own formula.
    obj_eval = obj.evaluated_get(depsgraph)
    mesh = obj_eval.to_mesh()
    count = 0 if mesh is None else len(mesh.vertices)
    if count not in (2, 4):
        if mesh is not None:
            obj_eval.to_mesh_clear()
        raise ExtractionError(
            f"'{obj.name}' must have either 4 vertices (start, midpoint, end, direction tip - use "
            f"the New EFLine button) or 2 vertices (a plain start and end point), found {count}."
        )
    world_matrix = obj_eval.matrix_world
    points = [tuple(world_matrix @ vertex.co) for vertex in mesh.vertices]
    obj_eval.to_mesh_clear()

    if count == 2:
        start, end = points
        return start, end, _ef_line_direction(start, end)
    start, mid, end, tip = points
    return start, end, _direction_from_pointer(mid, tip)


def _extract_ef_lines(ef_lines_collection: bpy.types.Collection, depsgraph: bpy.types.Depsgraph, warnings: list[str]) -> list[EFLine]:
    ef_lines: list[EFLine] = []
    for obj in ef_lines_collection.objects:
        if obj.type != "MESH":
            continue
        try:
            start_raw, end_raw, direction_raw = _extract_ef_line_geometry(obj, depsgraph)
        except ExtractionError as error:
            warnings.append(f"'{obj.name}' was skipped: {error}")
            continue

        action = EFLINE_ACTION_LABELS.get(obj.tw_efline_action, obj.tw_efline_action)
        ef_lines.append(
            EFLine(
                variation_index=len(ef_lines) + 1,
                action=action,
                start=_to_engine_space(start_raw),
                end=_to_engine_space(end_raw),
                direction=_to_engine_space(direction_raw),
            )
        )
    return ef_lines


def _extract_docking_lines(docking_lines_collection: bpy.types.Collection, depsgraph: bpy.types.Depsgraph, warnings: list[str]) -> list[DockingLine]:
    docking_lines: list[DockingLine] = []
    for obj in docking_lines_collection.objects:
        if obj.type != "MESH":
            continue
        try:
            start_raw, end_raw, direction_raw = _extract_ef_line_geometry(obj, depsgraph)
        except ExtractionError as error:
            warnings.append(f"'{obj.name}' was skipped: {error}")
            continue

        docking_lines.append(
            DockingLine(
                variation_index=len(docking_lines) + 1,
                start=_to_engine_space(start_raw),
                end=_to_engine_space(end_raw),
                direction=_to_engine_space(direction_raw),
            )
        )
    return docking_lines


def _extract_arrow_emitters(arrow_emitters_collection: bpy.types.Collection, depsgraph: bpy.types.Depsgraph) -> list[ArrowEmitter]:
    # Unlike every other tech type, arrow emitters do NOT bake world position into their geometry -
    # a real sample's 8 arrow emitters all share one identical local shape, and a real BOB run
    # confirmed it reads position/direction from the node's own transform keyframe instead (see
    # cs2_builder._scene_node_for). So the mesh stays in local space and the object's placement is
    # extracted separately as a transform.
    mesh_objects = [obj for obj in arrow_emitters_collection.objects if obj.type == "MESH"]
    arrow_emitters: list[ArrowEmitter] = []
    for variation_index, obj in enumerate(mesh_objects, start=1):
        obj_eval = obj.evaluated_get(depsgraph)
        translation, rotation, _scale = obj_eval.matrix_world.decompose()
        arrow_emitters.append(
            ArrowEmitter(
                variation_index=variation_index,
                mesh=_convert_mesh(obj, depsgraph, apply_world_matrix=False),
                transform_translation=_to_engine_space(tuple(translation)),
                transform_rotation=_to_engine_rotation(rotation),
            )
        )
    return arrow_emitters


def _extract_flag(flag_collection: bpy.types.Collection, depsgraph: bpy.types.Depsgraph, warnings: list[str]) -> Flag | None:
    # Same placement rule as arrow emitters: both real samples' flag nodes carry the identical
    # 0.5 x 0.5 x 1.0 local box and differ only in their scene-node keyframe, so the mesh stays in
    # local space and the object's own transform is what positions it.
    mesh_objects = [obj for obj in flag_collection.objects if obj.type == "MESH"]
    if not mesh_objects:
        return None
    if len(mesh_objects) > 1:
        warnings.append(
            f"Building has {len(mesh_objects)} flag meshes; only '{mesh_objects[0].name}' was used."
        )
    obj = mesh_objects[0]
    obj_eval = obj.evaluated_get(depsgraph)
    translation, rotation, _scale = obj_eval.matrix_world.decompose()
    return Flag(
        mesh=_convert_mesh(obj, depsgraph, apply_world_matrix=False),
        transform_translation=_to_engine_space(tuple(translation)),
        transform_rotation=_to_engine_rotation(rotation),
    )


def _extract_file_references(
    file_reference_collection: bpy.types.Collection, depsgraph: bpy.types.Depsgraph, warnings: list[str]
) -> list[FileReference]:
    # Same placement rule as arrow emitters and the flag, and here it is what the compiled output
    # proves: gondor_fort_gateway_e's four torch_sconce nodes share one identical local mesh, and
    # BOB copies each node's own keyframe verbatim into the .cs2.parsed file ref's matrix while
    # dropping the mesh entirely. The mesh is preview geometry for the artist, so an object with no
    # mesh at all (an Empty) is a complete file reference on its own.
    references: list[FileReference] = []
    for obj in file_reference_collection.objects:
        if not obj.tw_file_reference_name:
            warnings.append(f"'{obj.name}' has no Referenced Prop Name set and was skipped.")
            continue

        obj_eval = obj.evaluated_get(depsgraph)
        translation, rotation, _scale = obj_eval.matrix_world.decompose()

        mesh = None
        materials: list[MaterialDef] = []
        if obj.type == "MESH":
            materials = _read_object_materials(obj)
            if not materials:
                warnings.append(f"'{obj.name}' has no material assigned and was skipped.")
                continue
            mesh = _convert_mesh(
                obj, depsgraph, apply_world_matrix=False, uv2_layer_name=_uv2_layer_name(materials)
            )

        references.append(
            FileReference(
                reference_name=obj.tw_file_reference_name,
                transform_translation=_to_engine_space(tuple(translation)),
                transform_rotation=_to_engine_rotation(rotation),
                mesh=mesh,
                materials=materials,
            )
        )
    return references


def extract_building(
    building_collection: bpy.types.Collection, depsgraph: bpy.types.Depsgraph, scene: bpy.types.Scene
) -> tuple[BuildingAsset, list[str]]:
    warnings: list[str] = []
    pieces: list[Piece] = []

    piece_collections = _children_with_role(building_collection, "PIECE")
    if not piece_collections:
        raise ExtractionError(f"Building '{building_collection.name}' has no Building Pieces yet.")

    piece_index_by_collection = {
        collection.as_pointer(): index for index, collection in enumerate(piece_collections, start=1)
    }
    damage_parent_collections: dict[int, bpy.types.Collection] = {}

    for piece_index, piece_collection in enumerate(piece_collections, start=1):
        damage_parent = piece_collection.tw_damage_parent
        if damage_parent is not None:
            damage_parent_collections[piece_index] = damage_parent

        destruct_collections = _children_with_role(piece_collection, "DESTRUCT")
        if not destruct_collections:
            warnings.append(f"Piece {piece_index} ('{piece_collection.name}') has no destruct levels and was skipped.")
            continue

        destruct_levels: list[DestructLevel] = []
        for destruct_index, destruct_collection in enumerate(destruct_collections, start=1):
            display_collections = _children_with_role(destruct_collection, "DISPLAY")
            if not display_collections:
                warnings.append(
                    f"Piece {piece_index}, destruct level {destruct_index} has no Display collection and was skipped."
                )
                continue

            gate_closed_lods = _extract_gate_display(display_collections[0], "GATE_CLOSED_DISPLAY", depsgraph, warnings)
            gate_open_lods = _extract_gate_display(display_collections[0], "GATE_OPEN_DISPLAY", depsgraph, warnings)
            gate_anim_meshes = _extract_gate_anim_meshes(display_collections[0], depsgraph, scene, warnings)
            boiling_oil_lods = _extract_gate_display(display_collections[0], "BOILING_OIL_DISPLAY", depsgraph, warnings)

            lod_objects = [obj for obj in display_collections[0].objects if obj.type == "MESH"]
            if not lod_objects and not gate_closed_lods and not gate_open_lods and not boiling_oil_lods:
                warnings.append(
                    f"Piece {piece_index}, destruct level {destruct_index} has an empty Display collection and was skipped."
                )
                continue

            lod_meshes = [_extract_lod(obj, depsgraph) for obj in lod_objects]

            collision_collections = _children_with_role(destruct_collection, "COLLISION")
            collision_mesh = None
            soft_collision_mesh = None
            gate_closed_collision = None
            gate_ajar_collision = None
            boiling_oil_collision = None
            if collision_collections:
                collision_mesh = _extract_collision(collision_collections[0], depsgraph, warnings)
                soft_collision_mesh = _extract_soft_collision(collision_collections[0], depsgraph, warnings)
                gate_closed_collision = _extract_gate_collision(collision_collections[0], "GATE_CLOSED", depsgraph, warnings)
                gate_ajar_collision = _extract_gate_collision(collision_collections[0], "GATE_AJAR", depsgraph, warnings)
                boiling_oil_collision = _extract_gate_collision(collision_collections[0], "BOILING_OIL", depsgraph, warnings)

            platform_meshes: list[PlatformMesh] = []
            platform_ground_candidates: list[PlatformGroundMesh] = []
            for platform_collection in _children_with_role(destruct_collection, "PLATFORM"):
                platform_meshes.extend(_extract_platforms(platform_collection, depsgraph, warnings))
                ground_mesh = _extract_platform_ground(platform_collection, depsgraph, warnings)
                if ground_mesh is not None:
                    platform_ground_candidates.append(ground_mesh)
            platform_ground_mesh = None
            if platform_ground_candidates:
                if len(platform_ground_candidates) > 1:
                    warnings.append(
                        f"Piece {piece_index}, destruct level {destruct_index} has more than one Platform "
                        "Ground mesh across its Platform collections; only the first was used."
                    )
                platform_ground_mesh = platform_ground_candidates[0]

            file_references: list[FileReference] = []
            for file_reference_collection in _children_with_role(destruct_collection, "FILE_REFERENCE"):
                file_references.extend(_extract_file_references(file_reference_collection, depsgraph, warnings))

            line_features: list[LineFeature] = []
            for lines_collection in _children_with_role(destruct_collection, "LINES"):
                line_features.extend(_extract_line_features(lines_collection, depsgraph, warnings))

            ef_lines: list[EFLine] = []
            for ef_lines_collection in _children_with_role(destruct_collection, "EF_LINES"):
                ef_lines.extend(_extract_ef_lines(ef_lines_collection, depsgraph, warnings))

            docking_lines: list[DockingLine] = []
            for docking_lines_collection in _children_with_role(destruct_collection, "DOCKING_LINES"):
                docking_lines.extend(_extract_docking_lines(docking_lines_collection, depsgraph, warnings))

            arrow_emitters: list[ArrowEmitter] = []
            for arrow_emitters_collection in _children_with_role(destruct_collection, "ARROW_EMITTERS"):
                arrow_emitters.extend(_extract_arrow_emitters(arrow_emitters_collection, depsgraph))

            height_map_meshes: list[HeightMapMesh] = []
            for height_map_collection in _children_with_role(destruct_collection, "HEIGHT_MAP_MESH"):
                mesh_objects = [obj for obj in height_map_collection.objects if obj.type == "MESH"]
                for var_idx, obj in enumerate(mesh_objects, start=1):
                    height_map_meshes.append(HeightMapMesh(variation_index=var_idx, mesh=_convert_mesh(obj, depsgraph)))

            destruction_anim_meshes: list[DestructionAnimMesh] = []
            for destruction_anim_collection in _children_with_role(destruct_collection, "DESTRUCTION_ANIM"):
                destruction_anim_meshes.extend(
                    _extract_destruction_anim_meshes(destruction_anim_collection, depsgraph, scene, warnings)
                )

            destruct_levels.append(
                DestructLevel(
                    destruct_index=destruct_index,
                    lod_meshes=lod_meshes,
                    collision_mesh=collision_mesh,
                    soft_collision_mesh=soft_collision_mesh,
                    platform_meshes=platform_meshes,
                    platform_ground_mesh=platform_ground_mesh,
                    file_references=file_references,
                    line_features=line_features,
                    ef_lines=ef_lines,
                    docking_lines=docking_lines,
                    arrow_emitters=arrow_emitters,
                    height_map_meshes=height_map_meshes,
                    gate_closed_collision=gate_closed_collision,
                    gate_ajar_collision=gate_ajar_collision,
                    gate_closed_lods=gate_closed_lods,
                    gate_open_lods=gate_open_lods,
                    destruction_anim_meshes=destruction_anim_meshes,
                    gate_anim_meshes=gate_anim_meshes,
                    boiling_oil_collision=boiling_oil_collision,
                    boiling_oil_lods=boiling_oil_lods,
                )
            )

        if not destruct_levels:
            continue
        pieces.append(Piece(piece_index=piece_index, destruct_levels=destruct_levels))

    if not pieces:
        raise ExtractionError(f"Building '{building_collection.name}' has no exportable geometry.")

    exported_piece_indices = {piece.piece_index for piece in pieces}
    for piece in pieces:
        damage_parent = damage_parent_collections.get(piece.piece_index)
        if damage_parent is None:
            continue
        parent_index = piece_index_by_collection.get(damage_parent.as_pointer())
        if parent_index is None or parent_index not in exported_piece_indices:
            warnings.append(
                f"Piece {piece.piece_index}'s Damage Parent ('{damage_parent.name}') is not an "
                "exported piece of this building and was ignored."
            )
            continue
        piece.damage_parent_piece_index = parent_index

    region_zones: list[RegionZone] = []
    for region_zone_collection in _children_with_role(building_collection, "REGION_ZONES"):
        region_zones.extend(_extract_region_zones(region_zone_collection, depsgraph, warnings))

    flag = None
    for flag_collection in _children_with_role(building_collection, "FLAG"):
        flag = _extract_flag(flag_collection, depsgraph, warnings) or flag

    building = BuildingAsset(
        name=building_collection.name,
        asset_type=building_collection.tw_asset_type,
        pieces=pieces,
        region_zones=region_zones,
        flag=flag,
    )
    return building, warnings
