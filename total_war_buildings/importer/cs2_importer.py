import os
import re
import math
import bpy
import mathutils

from binary.cs2_reader import read_cs2
from binary import cs2_structures as s
from scene_model.models import AnimationKeyframes
from extraction.animation import bake_keyframes_onto_object
from props.properties import EFLINE_ACTION_ITEMS, SHADER_TYPES, COLLISION_MESH_TYPES, TW_ROLE_LABELS
from materials.material_builder import create_total_war_material, TW_PLACEHOLDER_MARKER

# Template for Arrow Emitters (in Blender Z-up space)
_ARROW_EMITTER_TEMPLATE_VERTICES = [
    (-0.3, -0.295, 0.0),
    (-0.3, 0.295, 0.0),
    (0.0, 0.0, 0.0),
    (0.3, 0.295, 0.0),
    (0.3, -0.295, 0.0),
    (0.0, -0.295, 0.0),
]
_ARROW_EMITTER_TEMPLATE_TRIANGLES = [
    (1, 5, 2),
    (1, 0, 5),
    (2, 4, 3),
    (4, 2, 5),
]

_PLACEHOLDER_FILENAMES = {
    "test_gray.tga",
    "flatnormal.tga",
    "test_black.tga",
    "test_white.tga",
    "test_cubemap.dds",
    "test_cubemap_blurry.dds",
}

_EFLINE_ACTION_LOOKUP = {}
for _id, _label, _ in EFLINE_ACTION_ITEMS:
    _EFLINE_ACTION_LOOKUP[_id.lower()] = _id
    _EFLINE_ACTION_LOOKUP[_label.lower()] = _id


def _marker_line_mesh(name, start, end, direction):
    # Rebuild the same 4-vertex shape ui/operators.marker_line_geometry creates, but aimed by the
    # file's own stored direction rather than the perpendicular formula - half of real content has
    # the opposite sign to what that formula gives, and re-exporting must not silently flip it.
    mid = tuple((s + e) / 2.0 for s, e in zip(start, end))
    half_length = math.hypot(end[0] - start[0], end[1] - start[1]) / 2.0
    dx, dy = (direction[0], direction[1]) if direction else (0.0, 0.0)
    length = math.hypot(dx, dy)
    if length == 0.0:
        dx, dy, length = -(end[1] - start[1]), end[0] - start[0], half_length * 2.0
    if length == 0.0:
        return None
    tip = (mid[0] + dx / length * half_length, mid[1] + dy / length * half_length, mid[2])
    mesh = bpy.data.meshes.new(name)
    mesh.from_pydata([start, mid, end, tip], [(0, 1), (1, 2), (1, 3)], [])
    mesh.update()
    return mesh


def _lock_marker_line_tilt(obj) -> None:
    # Only yaw matters for a marker (see ui/operators.lock_marker_line_tilt), so imported ones get
    # the same two rotation axes locked as ones created in Blender.
    obj.lock_rotation[0] = True
    obj.lock_rotation[1] = True


def _udp_vec3_to_blender_space(vector: tuple[float, float, float]) -> tuple[float, float, float]:
    # UDP text is 3ds Max's own buffer and stores Max Z-up coordinates verbatim (TWBuildingsTech.ms
    # writes getKnotPoint's x/y/z straight out), so unlike every other vector in the file these are
    # already in Blender's space and must not be converted.
    return vector


def _to_blender_space(vector: tuple[float, float, float]) -> tuple[float, float, float]:
    # Inverse of extraction._to_engine_space, which is its own inverse.
    x, y, z = vector
    return (x, z, y)


def winds_upward(points: list[tuple[float, float, float]]) -> bool:
    # Blender-space counterpart of extraction._orient_faces_upward's test: BOB only accepts a
    # platform polygon whose normal points up, so a file authored with them pointing down is
    # imported flipped rather than handed to the artist in a state the exporter would have to
    # silently correct again.
    area = 0.0
    for index, (x, y, _z) in enumerate(points):
        next_x, next_y, _next_z = points[(index + 1) % len(points)]
        area += x * next_y - next_x * y
    return area >= 0.0


def infer_line_type(line_name: str) -> str:
    name_lower = line_name.lower()
    if "ground_ad" in name_lower:
        return "GROUND_AD"
    if "outline" in name_lower:
        return "OUTLINE"
    if "pipe_wall_door" in name_lower:
        return "PIPE_WALL_DOOR"
    if "pipe_window" in name_lower:
        return "PIPE_WINDOW"
    if "pipe_door" in name_lower:
        return "PIPE_DOOR"
    if "pipe_jump_ramp" in name_lower:
        return "PIPE_JUMP_RAMP"
    if "pipe_jump_disembark" in name_lower:
        return "PIPE_JUMP_DISEMBARK"
    if "pipe_jump" in name_lower:
        return "PIPE_JUMP"
    if "pipe_rigging" in name_lower:
        return "PIPE_RIGGING"
    if "pipe_destroyed_climb_wood" in name_lower:
        return "PIPE_DESTROYED_CLIMB_WOOD"
    if "pipe_destroyed_climb" in name_lower:
        return "PIPE_DESTROYED_CLIMB"
    if "pipe_climb_wood" in name_lower:
        return "PIPE_CLIMB_WOOD"
    if "pipe_climb" in name_lower:
        return "PIPE_CLIMB"
    if "pipe_rope" in name_lower:
        return "PIPE_ROPE"
    if "pipe_stair" in name_lower:
        return "PIPE_STAIR"
    if "pipe_siegeladder" in name_lower or "pipe_siege_ladder" in name_lower:
        return "PIPE_SIEGE_LADDER"
    if "pipe_ladder_right" in name_lower:
        return "PIPE_LADDER_RIGHT"
    if "pipe_ladder_left" in name_lower:
        return "PIPE_LADDER_LEFT"
    if "pipe_ladder" in name_lower:
        return "PIPE_LADDER"
    if "hard" in name_lower:
        return "HARD"
    return "OUTLINE"


# Each entry maps a node's class_rigidINFO to the (kind, value) the importer needs: a
# tw_collision_type, a Display sub-collection role plus its LOD number, or a tw_line_type. Not
# gate-specific despite the "_GATE_" history in some names below - Boiling Oil follows the exact
# same shape (confirmed from a real sample: gondor_fort_gateway_oil_e.CS2).
_GATE_PART_PATTERNS = [
    (re.compile(r"^collision3d_gate_closed$", re.IGNORECASE), ("COLLISION", "GATE_CLOSED")),
    (re.compile(r"^collision3d_gate_ajar$", re.IGNORECASE), ("COLLISION", "GATE_AJAR")),
    (re.compile(r"^gate_closed_lod(\d+)$", re.IGNORECASE), ("DISPLAY", "GATE_CLOSED_DISPLAY")),
    (re.compile(r"^gate_open_lod(\d+)$", re.IGNORECASE), ("DISPLAY", "GATE_OPEN_DISPLAY")),
    (re.compile(r"^gate_closed_hard(\d+)$", re.IGNORECASE), ("LINE", "GATE_CLOSED_HARD")),
    (re.compile(r"^gate_ajar_hard(\d+)$", re.IGNORECASE), ("LINE", "GATE_AJAR_HARD")),
    (re.compile(r"^collision3d_boiling_oil$", re.IGNORECASE), ("COLLISION", "BOILING_OIL")),
    (re.compile(r"^boiling_oil_lod(\d+)$", re.IGNORECASE), ("DISPLAY", "BOILING_OIL_DISPLAY")),
]


# class_rigidINFO values confirmed from gondor_fort_gateway_e.CS2's real
# building_pieceNN_destructNN_gate_*_anim nodes - mirrors naming.GATE_ANIM_CLASS_RIGID_INFO.
_GATE_ANIM_CLASS_RIGID_INFO_TO_KIND = {
    "gate_opening_anim": "GATE_OPENING",
    "gate_closing_anim": "GATE_CLOSING",
    "gate_closed_destruct_anim": "GATE_CLOSED_DESTRUCT",
    "gate_open_destruct_anim": "GATE_OPEN_DESTRUCT",
}
_DESTRUCTION_ANIM_CLASS_RIGID_INFO = "anim"


def nested_part_of(class_rigid_info: str, node_name: str) -> tuple[str, str, int] | None:
    # Matched against class_rigidINFO first because the node name carries the piece/destruct prefix
    # and, for the animation nodes, an extra "building_" one. Anything ending in "_anim" is an
    # open/close or destruct animation and is deliberately not a gate part - animation is out of
    # scope, and those nodes share the same gate_open/gate_closed words.
    candidates = [class_rigid_info]
    stripped = re.sub(r"^(building_)?piece\d+[a-z]?_destruct\d+_", "", node_name, flags=re.IGNORECASE)
    if stripped != node_name:
        candidates.append(stripped)
    for candidate in candidates:
        if not candidate or candidate.lower().endswith("_anim"):
            continue
        for pattern, (kind, value) in _GATE_PART_PATTERNS:
            match = pattern.match(candidate)
            if match:
                return kind, value, int(match.group(1)) if match.groups() else 1
    return None


def _is_closed_loop(points: list[tuple[float, float, float]]) -> bool:
    return (
        len(points) > 2
        and math.isclose(points[0][0], points[-1][0], abs_tol=1e-3)
        and math.isclose(points[0][1], points[-1][1], abs_tol=1e-3)
        and math.isclose(points[0][2], points[-1][2], abs_tol=1e-3)
    )


def _point_lies_on_segment(point, start, end) -> bool:
    span = tuple(end[axis] - start[axis] for axis in range(3))
    offset = tuple(point[axis] - start[axis] for axis in range(3))
    span_length_sq = sum(component * component for component in span)
    if span_length_sq == 0.0:
        return all(abs(component) <= 1e-3 for component in offset)
    along = sum(offset[axis] * span[axis] for axis in range(3)) / span_length_sq
    if not -1e-3 <= along <= 1.0 + 1e-3:
        return False
    perpendicular_sq = sum((offset[axis] - along * span[axis]) ** 2 for axis in range(3))
    return perpendicular_sq <= max(1e-6, 1e-8 * span_length_sq)


def _undo_line_tessellation(points: list[tuple[float, float, float]]) -> list[tuple[float, float, float]]:
    # Inverse of extraction._subdivide_line_points: the exporter splits every authored edge into
    # exactly 3 vertices, so a stored line always has 3*edges+1 of them and only every third one is
    # a corner the artist actually placed. Keeping the interpolated ones would hand the artist a
    # curve with 3x the control points and make every re-export tessellate what was already
    # tessellated, tripling the vertex count again on each pass.
    #
    # The test is "the two interior points add no shape", not "they sit on exact thirds": real
    # content is not always evenly subdivided (gondor_fort_gateway_e's region_zone02 has an edge
    # split at its midpoint and a zero-length one), and every such line still reduces to the right
    # corner list. A line whose intermediate points are genuine corners fails this and is left
    # alone.
    if len(points) < 4 or (len(points) - 1) % 3 != 0:
        return points
    for index in range(0, len(points) - 1, 3):
        start, end = points[index], points[index + 3]
        if not all(_point_lies_on_segment(points[index + step], start, end) for step in (1, 2)):
            return points
    return points[::3]


def _extract_raw_piece_str(node_name: str, attributes: s.NodeAttributes) -> str:
    for attr in attributes.strings:
        if attr.name == "piece_INFO" and attr.value:
            return attr.value
    match = re.search(r"(piece\d+[a-z]?)", node_name, re.IGNORECASE)
    if match:
        return match.group(1)
    return "piece01"


def _extract_destruct_index(node_name: str, attributes: s.NodeAttributes) -> int:
    for attr in attributes.strings:
        if attr.name == "destruct_ID" and attr.value:
            match = re.search(r"destruct(\d+)", attr.value, re.IGNORECASE)
            if match:
                return int(match.group(1))

    match = re.search(r"destruct(\d+)", node_name, re.IGNORECASE)
    if match:
        return int(match.group(1))
    return 1


def _parse_udp_key_values(udp_text: str) -> dict[str, str]:
    res = {}
    if not udp_text:
        return res
    for line in udp_text.replace("\r", "").split("\n"):
        line = line.strip()
        if "=" in line:
            k, v = line.split("=", 1)
            res[k.strip()] = v.strip()
    return res


def _parse_vec3_from_string(vec_str: str) -> tuple[float, float, float] | None:
    m_x = re.search(r'x:"?([-+]?\d*\.?\d+(?:[eE][-+]?\d+)?)"?', vec_str)
    m_y = re.search(r'y:"?([-+]?\d*\.?\d+(?:[eE][-+]?\d+)?)"?', vec_str)
    m_z = re.search(r'z:"?([-+]?\d*\.?\d+(?:[eE][-+]?\d+)?)"?', vec_str)
    if m_x and m_y and m_z:
        return (float(m_x.group(1)), float(m_y.group(1)), float(m_z.group(1)))
    return None


_ENGINE_SPACE_MATRIX = mathutils.Matrix(((1.0, 0.0, 0.0), (0.0, 0.0, 1.0), (0.0, 1.0, 0.0)))


def _create_mesh_from_rigid_node(
    mesh_name: str,
    rm: s.RigidModelNode,
    blender_materials: list[bpy.types.Material],
    default_mat: bpy.types.Material,
    orient_upward_matrix: mathutils.Matrix | None = None,
    warnings: list[str] | None = None,
) -> tuple[bpy.types.Mesh, list[bpy.types.Material]]:
    all_positions = []
    all_normals = []
    all_colours = []
    all_triangles = []
    triangle_material_indices = []

    # Determine maximum number of UV channels across all vertices in all chunks
    max_uv_channels = 0
    for chunk in rm.geometry_chunks:
        for v in chunk.vertices:
            if v.tex_coords:
                max_uv_channels = max(max_uv_channels, len(v.tex_coords))

    all_uv_channels: list[list[tuple[float, float]]] = [[] for _ in range(max_uv_channels)]

    mat_id_to_slot: dict[int, int] = {}
    assigned_materials: list[bpy.types.Material] = []

    vertex_offset = 0

    for chunk in rm.geometry_chunks:
        chunk_positions = [_to_blender_space(v.position) for v in chunk.vertices]
        chunk_normals = [_to_blender_space(v.normal) for v in chunk.vertices]

        all_positions.extend(chunk_positions)
        all_normals.extend(chunk_normals)
        all_colours.extend(tuple(v.color) for v in chunk.vertices)

        # Inverse of extraction's _to_engine_uv: CS2's V origin is top-left, Blender's bottom-left.
        for v in chunk.vertices:
            for c_idx in range(max_uv_channels):
                if v.tex_coords and c_idx < len(v.tex_coords):
                    all_uv_channels[c_idx].append((v.tex_coords[c_idx][0], 1.0 - v.tex_coords[c_idx][1]))
                else:
                    all_uv_channels[c_idx].append((0.0, 0.0))

        for submesh in chunk.submeshes:
            mat_id = submesh.material_id
            if mat_id not in mat_id_to_slot:
                if 0 <= mat_id < len(blender_materials):
                    mat = blender_materials[mat_id]
                else:
                    mat = default_mat
                assigned_materials.append(mat)
                mat_id_to_slot[mat_id] = len(assigned_materials) - 1

            slot_idx = mat_id_to_slot[mat_id]

            # _to_blender_space is a reflection, so keeping the file's corner order would leave the
            # imported faces wound against their own normals - the mirror of what extraction does.
            for v0, v1, v2 in submesh.triangles:
                all_triangles.append((vertex_offset + v2, vertex_offset + v1, vertex_offset + v0))
                triangle_material_indices.append(slot_idx)

        vertex_offset += len(chunk.vertices)

    if not assigned_materials:
        assigned_materials.append(default_mat)

    if orient_upward_matrix is not None:
        # The test has to be in world space: gondor_fort_gateway_e's piece04 platform is wound
        # downwards in its own geometry and turned the right way up by a 180-degree scene-node
        # rotation, so judging the local mesh alone would "fix" a platform that was already correct.
        placed = [orient_upward_matrix @ mathutils.Vector(position) for position in all_positions]
        flipped_vertices = set()
        for index, (i0, i1, i2) in enumerate(all_triangles):
            if winds_upward([placed[i0], placed[i1], placed[i2]]):
                continue
            all_triangles[index] = (i2, i1, i0)
            flipped_vertices.update((i0, i1, i2))
        for index in flipped_vertices:
            nx, ny, nz = all_normals[index]
            all_normals[index] = (-nx, -ny, -nz)
        if flipped_vertices and warnings is not None:
            warnings.append(
                f"'{mesh_name}' had face(s) pointing downwards in the file; they were flipped so the "
                "platform faces up, which is what BOB needs to place EFLines on it."
            )

    mesh_data = bpy.data.meshes.new(mesh_name)
    mesh_data.from_pydata(all_positions, [], all_triangles)

    for c_idx, channel_uvs in enumerate(all_uv_channels):
        if c_idx == 0 or any(u != (0.0, 0.0) for u in channel_uvs):
            layer_name = f"UV{c_idx + 1}"
            uv_layer = mesh_data.uv_layers.new(name=layer_name)
            for polygon in mesh_data.polygons:
                for loop_idx in polygon.loop_indices:
                    v_idx = mesh_data.loops[loop_idx].vertex_index
                    if v_idx < len(channel_uvs):
                        uv_layer.data[loop_idx].uv = channel_uvs[v_idx]

    # Skipped when every vertex is plain white, because that is exactly what extraction falls back
    # to for a mesh with no colour attribute at all - so an all-white attribute would only add
    # clutter. ps_common_blend_decal reads 1 - alpha, so the alpha channel has to come across too.
    if any(tuple(c) != (1.0, 1.0, 1.0, 1.0) for c in all_colours):
        colour_layer = mesh_data.color_attributes.new(name="Colour", type="FLOAT_COLOR", domain="POINT")
        for v_idx, colour in enumerate(all_colours):
            if v_idx < len(colour_layer.data):
                colour_layer.data[v_idx].color = colour
        try:
            mesh_data.color_attributes.render_color_index = mesh_data.color_attributes.find(colour_layer.name)
            mesh_data.color_attributes.active_color_index = mesh_data.color_attributes.find(colour_layer.name)
        except (AttributeError, TypeError):
            pass

    if any(math.sqrt(n[0] ** 2 + n[1] ** 2 + n[2] ** 2) > 0.01 for n in all_normals):
        mesh_data.polygons.foreach_set("use_smooth", [True] * len(mesh_data.polygons))
        split_normals = [all_normals[loop.vertex_index] for loop in mesh_data.loops]
        try:
            mesh_data.normals_split_custom_set(split_normals)
        except Exception:
            pass

    for poly, slot_idx in zip(mesh_data.polygons, triangle_material_indices):
        poly.material_index = slot_idx

    mesh_data.update()
    return mesh_data, assigned_materials


def _to_blender_rotation(rotation_eng) -> mathutils.Quaternion:
    # Inverse of extraction._to_engine_rotation, which is its own inverse (same reflection-matrix
    # conjugation trick).
    r_eng = rotation_eng
    q_eng = mathutils.Quaternion((r_eng[3], r_eng[0], r_eng[1], r_eng[2]))
    return (_ENGINE_SPACE_MATRIX @ q_eng.to_matrix() @ _ENGINE_SPACE_MATRIX).to_quaternion()


def _scene_node_for_index(node_index: int, scene_nodes: list[s.SceneNode]) -> s.SceneNode | None:
    # SceneNode has no NodeIndex field of its own - the only reliable link back to a RigidModelNode/
    # LineNode is array position, and RigidModelNode.node_index (1-based) is confirmed against every
    # ground-truth sample to equal that position + 1 (see naming.naming's node_index note). This
    # matters far more than it used to: destruction debris and gate animation nodes legitimately
    # share the exact same node_name within a piece/destruct level (see naming.py), so a name-keyed
    # lookup silently collapses them all onto whichever one was inserted last into the dict - a real
    # bug this feature's own test caught, not a hypothetical one.
    index = node_index - 1
    if 0 <= index < len(scene_nodes):
        return scene_nodes[index]
    return None


def _scene_node_own_matrix(scene_node: s.SceneNode | None) -> mathutils.Matrix | None:
    # This node's own first-keyframe transform only, no ancestor composition - the building block
    # _scene_node_matrix below composes into a chain.
    sn = scene_node
    if not (sn and sn.anim and sn.anim.translations and sn.anim.rotations):
        return None
    loc_blender = mathutils.Vector(_to_blender_space(sn.anim.translations[0]))
    q_blender = _to_blender_rotation(sn.anim.rotations[0])
    return mathutils.Matrix.Translation(loc_blender) @ q_blender.to_matrix().to_4x4()


def _scene_node_ancestor_chain(scene_node: s.SceneNode, scene_nodes: list[s.SceneNode]) -> list[s.SceneNode]:
    # SceneNode.ParentIndex (the *first* field in the struct - distinct from ParentNodeIndex/
    # TargetLinkageName, which this codebase's own EFLine/DockingLine/RegionZone authoring repurposes
    # for UDP text) is almost always 0 (no parent) in every real sample, but not always: confirmed
    # against gondor_fort_gateway_e's own two flanking-tower collision3d nodes, which are genuinely
    # authored relative to the main gatehouse collision's transform - reproducing BOB's own compiled
    # collision bounds exactly (to float precision) required composing this chain; a single node's
    # own transform in isolation placed it 5 units off on one axis. 0-length loop guard included in
    # case a future sample's chain is malformed.
    chain = [scene_node]
    seen = {id(scene_node)}
    current = scene_node
    while current.parent_index != 0:
        parent_position = current.parent_index - 1
        if not 0 <= parent_position < len(scene_nodes):
            break
        parent = scene_nodes[parent_position]
        if id(parent) in seen:
            break
        chain.append(parent)
        seen.add(id(parent))
        current = parent
    return chain


def _scene_node_matrix(scene_node: s.SceneNode | None, scene_nodes: list[s.SceneNode]) -> mathutils.Matrix:
    if scene_node is None:
        return mathutils.Matrix.Identity(4)
    chain = _scene_node_ancestor_chain(scene_node, scene_nodes)
    matrix = mathutils.Matrix.Identity(4)
    for node in reversed(chain):  # root-most ancestor first, self last
        own = _scene_node_own_matrix(node)
        if own is not None:
            matrix = matrix @ own
    return matrix


def _scene_node_transform(
    scene_node: s.SceneNode | None,
    scene_nodes: list[s.SceneNode],
) -> tuple[mathutils.Vector, mathutils.Quaternion] | None:
    # First-keyframe-only, on purpose: used only where a single matrix is needed (e.g. orienting a
    # platform's upward normal), never for placing/animating an object - that's
    # _apply_scene_node_transform below, which bakes the node's full keyframe track.
    if scene_node is None:
        return None
    loc_blender, q_blender, _scale = _scene_node_matrix(scene_node, scene_nodes).decompose()
    return loc_blender, q_blender


def _apply_scene_node_transform(
    obj: bpy.types.Object,
    scene_node: s.SceneNode | None,
    scene_nodes: list[s.SceneNode],
    scene: bpy.types.Scene | None = None,
) -> None:
    # Bakes the node's full keyframe track (real ground truth has up to 141 keys - see
    # naming.GATE_ANIM_CLASS_RIGID_INFO / DESTRUCTION_ANIM_CLASS_RIGID_INFO) onto the object's own
    # location/rotation_quaternion F-curves when the scene is known and there is more than one key;
    # otherwise falls back to the plain static placement every other node type has always used
    # (also what a single-keyframe node - the common case - degenerates to). No real sample has ever
    # combined a multi-keyframe track with a non-zero ParentIndex, so the animated branch below
    # intentionally does not compose the ancestor chain _scene_node_transform now does - only the
    # static branch needs it (see _scene_node_ancestor_chain).
    sn = scene_node
    if sn and scene is not None and (len(sn.anim.translation_frame_times) > 1 or len(sn.anim.rotation_frame_times) > 1):
        keyframes = AnimationKeyframes(
            translation_times=list(sn.anim.translation_frame_times),
            translations=list(sn.anim.translations),
            rotation_times=list(sn.anim.rotation_frame_times),
            rotations=list(sn.anim.rotations),
        )
        bake_keyframes_onto_object(obj, keyframes, scene, _to_blender_space, _to_blender_rotation)
        return

    transform = _scene_node_transform(scene_node, scene_nodes)
    if transform is None:
        return
    loc_blender, q_blender = transform
    obj.rotation_mode = "QUATERNION"
    obj.rotation_quaternion = q_blender
    obj.location = loc_blender
    obj.matrix_world = mathutils.Matrix.Translation(loc_blender) @ q_blender.to_matrix().to_4x4()


def import_cs2(
    filepath: str, context: bpy.types.Context, document: s.CS2Document | None = None
) -> tuple[bpy.types.Collection, list[str]]:
    doc = document if document is not None else read_cs2(open(filepath, "rb").read())
    scene_nodes = doc.scene_root.scene_nodes

    filename_stem = os.path.splitext(os.path.basename(filepath))[0]
    if filename_stem.lower().endswith(".cs2"):
        filename_stem = filename_stem[:-4]

    building_coll = bpy.data.collections.new(filename_stem)
    building_coll.tw_role = "BUILDING"
    building_coll.tw_asset_type = "DISPLAY_BUILDING"
    context.scene.collection.children.link(building_coll)

    warnings: list[str] = []

    # Import materials
    blender_materials: list[bpy.types.Material] = []
    valid_shader_types = {st[0] for st in SHADER_TYPES}
    texture_slot_map = {
        "t_albedo": "Diffuse",
        "t_normal": "Normal",
        "t_ambient_occlusion_uv2": "Mask",
        "t_dirtmap_uv2": "Dirtmap",
        "t_alpha_mask": "Dirtmask",
        "t_smoothness": "Gloss",
        "t_reflectivity": "Level",
        "t_specular_colour": "Specular",
        "t_mask1": "Tint Mask 1",
        "t_mask2": "Tint Mask 2",
        "t_mask3": "Tint Mask 3",
        "t_decal_diffuse": "Decal Diffuse",
        "t_decal_normal": "Decal Normal",
        "t_decal_mask": "Decal Mask",
    }

    for idx, mat_node in enumerate(doc.materials):
        mat_name = mat_node.node_name or mat_node.material_name or f"{filename_stem}_mat_{idx+1}"
        mat = bpy.data.materials.get(mat_name)
        if mat is None:
            mat = bpy.data.materials.new(mat_name)

        rigid_mat = "default"
        if mat_node.material_attributes:
            for attr in mat_node.material_attributes.strings:
                if attr.name == "rigid_material":
                    rigid_mat = attr.value
                    break

        if rigid_mat in valid_shader_types:
            mat.tw_shader_type = rigid_mat
        else:
            mat.tw_shader_type = "default"

        create_total_war_material(mat)

        if mat_node.directx_material:
            for tex in mat_node.directx_material.textures:
                if tex.texture_name in texture_slot_map:
                    slot_label = texture_slot_map[tex.texture_name]
                    path = tex.texture_path
                    base_name = os.path.basename(path).lower()
                    if path and base_name not in _PLACEHOLDER_FILENAMES:
                        tex_node = mat.node_tree.nodes.get(slot_label)
                        if tex_node and tex_node.type == "TEX_IMAGE":
                            if os.path.exists(path):
                                img = bpy.data.images.load(path, check_existing=True)
                            else:
                                img = bpy.data.images.get(os.path.basename(path))
                                if img is None:
                                    img = bpy.data.images.new(os.path.basename(path), width=4, height=4)
                                    img.filepath = path
                            if TW_PLACEHOLDER_MARKER in img:
                                del img[TW_PLACEHOLDER_MARKER]
                            tex_node.image = img

            u_tile = None
            v_tile = None
            for fa in mat_node.directx_material.float_attributes:
                if fa.name == "f_uv2_tile_interval_u":
                    u_tile = fa.value
                elif fa.name == "f_uv2_tile_interval_v":
                    v_tile = fa.value

            if u_tile is not None and v_tile is not None:
                tiling_node = mat.node_tree.nodes.get("Dirtmap Tiling")
                if tiling_node and tiling_node.type == "MAPPING":
                    tiling_node.inputs["Scale"].default_value = (u_tile, v_tile, 1.0)

            tint_node = mat.node_tree.nodes.get("Faction Tint")
            if tint_node is not None:
                for va in mat_node.directx_material.vec4_attributes:
                    if va.name.startswith("vec4_colour_"):
                        index = int(va.name.rsplit("_", 1)[1]) + 1
                        socket = tint_node.inputs.get(f"Colour {index}")
                        if socket is not None:
                            socket.default_value = tuple(max(c, 0.0) ** 2.2 for c in va.value[:3]) + (1.0,)
                for ia in mat_node.directx_material.integer_attributes:
                    if ia.name == "b_faction_colouring":
                        tint_node.inputs["Faction Colouring"].default_value = 1.0 if ia.value else 0.0

        blender_materials.append(mat)

    # Fallback default material if a mesh has no material assigned in binary
    default_mat = None
    if blender_materials:
        default_mat = blender_materials[0]
    else:
        default_mat = bpy.data.materials.get(f"{filename_stem}_material")
        if default_mat is None:
            default_mat = bpy.data.materials.new(f"{filename_stem}_material")
            create_total_war_material(default_mat)
        blender_materials.append(default_mat)

    # 2-Pass Piece Key Mapping
    piece_key_map: dict[str, int] = {}

    # Pass 1: Collect piece keys from DISPLAY nodes
    for rm in doc.rigid_models:
        name_lower = rm.node_name.lower()
        if "_anim" in name_lower or name_lower.endswith("anim") or "gate_open" in name_lower or "gate_closed" in name_lower:
            continue

        class_rigid_info = ""
        class_type = ""
        for attr in rm.attributes.strings:
            if attr.name == "class_rigidINFO":
                class_rigid_info = attr.value
            elif attr.name == "class_TYPE":
                class_type = attr.value

        m_lod = re.search(r"lod(\d+)", class_rigid_info, re.IGNORECASE) or re.search(r"lod(\d+)", rm.node_name, re.IGNORECASE)
        if m_lod or class_type == "DISPLAY":
            raw_piece = _extract_raw_piece_str(rm.node_name, rm.attributes)
            if raw_piece not in piece_key_map:
                piece_key_map[raw_piece] = len(piece_key_map) + 1

    def resolve_piece_index(raw_piece: str) -> int:
        if raw_piece in piece_key_map:
            return piece_key_map[raw_piece]
        for key, idx in piece_key_map.items():
            if key.startswith(raw_piece) or raw_piece.startswith(key):
                return idx
        piece_key_map[raw_piece] = len(piece_key_map) + 1
        return piece_key_map[raw_piece]

    # Collection managers
    piece_collections: dict[int, bpy.types.Collection] = {}
    destruct_collections: dict[tuple[int, int], bpy.types.Collection] = {}
    sub_collections: dict[tuple[int, int, str], bpy.types.Collection] = {}

    def get_sub_coll(piece_idx: int, destruct_idx: int, role: str) -> bpy.types.Collection:
        if piece_idx not in piece_collections:
            name = "Piece" if piece_idx == 1 else f"Piece {piece_idx}"
            p_coll = bpy.data.collections.new(name)
            p_coll.tw_role = "PIECE"
            building_coll.children.link(p_coll)
            piece_collections[piece_idx] = p_coll

        p_coll = piece_collections[piece_idx]
        key = (piece_idx, destruct_idx)
        if key not in destruct_collections:
            name = "Destruct" if destruct_idx == 1 else f"Destruct {destruct_idx}"
            d_coll = bpy.data.collections.new(name)
            d_coll.tw_role = "DESTRUCT"
            p_coll.children.link(d_coll)
            destruct_collections[key] = d_coll

            # Every Destruct level automatically gets a Display and Collision collection
            disp_coll = bpy.data.collections.new("Display")
            disp_coll.tw_role = "DISPLAY"
            d_coll.children.link(disp_coll)
            sub_collections[(piece_idx, destruct_idx, "DISPLAY")] = disp_coll

            col_coll = bpy.data.collections.new("Collision")
            col_coll.tw_role = "COLLISION"
            d_coll.children.link(col_coll)
            sub_collections[(piece_idx, destruct_idx, "COLLISION")] = col_coll

        d_coll = destruct_collections[key]
        sub_key = (piece_idx, destruct_idx, role)
        if sub_key not in sub_collections:
            role_labels = {
                "DISPLAY": "Display",
                "COLLISION": "Collision",
                "PLATFORM": "Platform",
                "FILE_REFERENCE": "Referenced Props",
                "LINES": "Lines",
                "EF_LINES": "EFLines",
                "DOCKING_LINES": "Docking Lines",
                "ARROW_EMITTERS": "Arrow Emitters",
                "HEIGHT_MAP_MESH": "Height Map Mesh",
                "DESTRUCTION_ANIM": "Destruction Animation",
            }
            s_coll = bpy.data.collections.new(role_labels.get(role, role))
            s_coll.tw_role = role
            d_coll.children.link(s_coll)
            sub_collections[sub_key] = s_coll

        return sub_collections[sub_key]

    gate_display_collections: dict[tuple[int, int, str], bpy.types.Collection] = {}

    def get_gate_display_coll(piece_idx: int, destruct_idx: int, role: str) -> bpy.types.Collection:
        key = (piece_idx, destruct_idx, role)
        if key not in gate_display_collections:
            display_coll = get_sub_coll(piece_idx, destruct_idx, "DISPLAY")
            gate_coll = bpy.data.collections.new(TW_ROLE_LABELS[role])
            gate_coll.tw_role = role
            display_coll.children.link(gate_coll)
            gate_display_collections[key] = gate_coll
        return gate_display_collections[key]

    gate_anim_collections: dict[tuple[int, int], bpy.types.Collection] = {}

    def get_gate_anim_coll(piece_idx: int, destruct_idx: int) -> bpy.types.Collection:
        key = (piece_idx, destruct_idx)
        if key not in gate_anim_collections:
            display_coll = get_sub_coll(piece_idx, destruct_idx, "DISPLAY")
            anim_coll = bpy.data.collections.new("Gate Animation")
            anim_coll.tw_role = "GATE_ANIMATION"
            display_coll.children.link(anim_coll)
            gate_anim_collections[key] = anim_coll
        return gate_anim_collections[key]

    flag_coll = None

    # Process Rigid Model Nodes
    for rm in doc.rigid_models:
        node_name = rm.node_name
        scene_node = _scene_node_for_index(rm.node_index, scene_nodes)
        raw_piece = _extract_raw_piece_str(node_name, rm.attributes)
        piece_idx = resolve_piece_index(raw_piece)
        destruct_idx = _extract_destruct_index(node_name, rm.attributes)

        class_rigid_info = ""
        class_type = ""
        rigid_object = ""

        for attr in rm.attributes.strings:
            if attr.name == "class_rigidINFO":
                class_rigid_info = attr.value
            elif attr.name == "class_TYPE":
                class_type = attr.value
            elif attr.name == "rigid_OBJECT":
                rigid_object = attr.value

        # Gate - checked ahead of the animation skip below, which matches on the same
        # gate_open/gate_closed words and used to swallow the real gate parts along with the
        # animation nodes.
        gate_match = nested_part_of(class_rigid_info, node_name) if rm.geometry_chunks else None
        if gate_match is not None and gate_match[0] in ("COLLISION", "DISPLAY"):
            kind, value, lod_num = gate_match
            mesh, assigned_mats = _create_mesh_from_rigid_node(node_name, rm, blender_materials, default_mat)
            obj = bpy.data.objects.new(node_name, mesh)
            if kind == "COLLISION":
                coll = get_sub_coll(piece_idx, destruct_idx, "COLLISION")
                obj.tw_collision_type = value
            else:
                coll = get_gate_display_coll(piece_idx, destruct_idx, value)
                obj.tw_lod_index = f"LOD{lod_num:02d}"
                for mat in assigned_mats:
                    obj.data.materials.append(mat)
            _apply_scene_node_transform(obj, scene_node, scene_nodes, context.scene)
            coll.objects.link(obj)
            continue

        # Gate Animation (opening/closing/closed-destruct/open-destruct) - a real moving door leaf
        # or its debris, distinct from the static gate_closed/gate_open Display meshes above. Class
        # rigidINFO values confirmed from gondor_fort_gateway_e.CS2's real anim nodes.
        gate_anim_kind = _GATE_ANIM_CLASS_RIGID_INFO_TO_KIND.get(class_rigid_info)
        if gate_anim_kind is not None and rm.geometry_chunks:
            coll = get_gate_anim_coll(piece_idx, destruct_idx)
            mesh, assigned_mats = _create_mesh_from_rigid_node(node_name, rm, blender_materials, default_mat)
            obj = bpy.data.objects.new(node_name, mesh)
            obj.tw_gate_anim_kind = gate_anim_kind
            for mat in assigned_mats:
                obj.data.materials.append(mat)
            _apply_scene_node_transform(obj, scene_node, scene_nodes, context.scene)
            coll.objects.link(obj)
            continue

        # Destruction Animation - a debris chunk with its own local mesh plus a real keyframe track.
        if class_rigid_info == _DESTRUCTION_ANIM_CLASS_RIGID_INFO and rm.geometry_chunks:
            coll = get_sub_coll(piece_idx, destruct_idx, "DESTRUCTION_ANIM")
            mesh, assigned_mats = _create_mesh_from_rigid_node(node_name, rm, blender_materials, default_mat)
            obj = bpy.data.objects.new(node_name, mesh)
            for mat in assigned_mats:
                obj.data.materials.append(mat)
            _apply_scene_node_transform(obj, scene_node, scene_nodes, context.scene)
            coll.objects.link(obj)
            continue

        # EFLine
        if node_name.startswith("EFline_") or class_rigid_info.startswith("EFLine"):
            coll = get_sub_coll(piece_idx, destruct_idx, "EF_LINES")
            udp = _parse_udp_key_values(rm.user_defined_properties)
            action_raw = udp.get("EFLine_Action", "LOW_WALL")
            action_id = _EFLINE_ACTION_LOOKUP.get(action_raw.lower(), "LOW_WALL")

            start_raw = _parse_vec3_from_string(udp.get("EFLine_Info", ""))
            end_raw = _parse_vec3_from_string(udp.get("EFLine_Info_End", ""))

            if start_raw and end_raw:
                start_pt = _udp_vec3_to_blender_space(start_raw)
                end_pt = _udp_vec3_to_blender_space(end_raw)
                direction_raw = _parse_vec3_from_string(udp.get("EFLine_Direction", ""))
                direction_pt = _udp_vec3_to_blender_space(direction_raw) if direction_raw else None
                ef_mesh = _marker_line_mesh(node_name, start_pt, end_pt, direction_pt)
                if ef_mesh is None:
                    warnings.append(f"Skipped degenerate EFLine '{node_name}'.")
                    continue
                ef_obj = bpy.data.objects.new(node_name, ef_mesh)
                _lock_marker_line_tilt(ef_obj)
                ef_obj.tw_efline_action = action_id
                coll.objects.link(ef_obj)
            continue

        # DockingLine
        if node_name.startswith("DockingLine_") or class_rigid_info.startswith("DockingLine"):
            coll = get_sub_coll(piece_idx, destruct_idx, "DOCKING_LINES")
            udp = _parse_udp_key_values(rm.user_defined_properties)
            start_raw = _parse_vec3_from_string(udp.get("DockingLine_Info", ""))
            end_raw = _parse_vec3_from_string(udp.get("DockingLine_Info_End", ""))

            if start_raw and end_raw:
                start_pt = _udp_vec3_to_blender_space(start_raw)
                end_pt = _udp_vec3_to_blender_space(end_raw)
                direction_raw = _parse_vec3_from_string(udp.get("DockingLine_Direction", ""))
                direction_pt = _udp_vec3_to_blender_space(direction_raw) if direction_raw else None
                dock_mesh = _marker_line_mesh(node_name, start_pt, end_pt, direction_pt)
                if dock_mesh is None:
                    warnings.append(f"Skipped degenerate Docking Line '{node_name}'.")
                    continue
                dock_obj = bpy.data.objects.new(node_name, dock_mesh)
                _lock_marker_line_tilt(dock_obj)
                coll.objects.link(dock_obj)
            continue

        # Fallback: an animation-shaped node that didn't match a known destruction/gate anim kind
        # above (e.g. empty geometry, or a genuinely new class_rigidINFO value not in
        # _GATE_ANIM_CLASS_RIGID_INFO_TO_KIND) - every real kind is handled by the two blocks above.
        name_lower = node_name.lower()
        if "_anim" in name_lower or name_lower.endswith("anim") or class_rigid_info.lower() == "anim" or "gate_open" in name_lower or "gate_closed" in name_lower:
            warnings.append(f"Skipped animation node '{node_name}'.")
            continue

        if not rm.geometry_chunks:
            continue

        # File Reference
        if class_rigid_info == "key" or "_file:" in node_name or rigid_object:
            coll = get_sub_coll(piece_idx, destruct_idx, "FILE_REFERENCE")
            ref_name = ""
            if "_file:" in node_name:
                ref_name = node_name.split("_file:", 1)[1]
            elif rigid_object:
                ref_name = rigid_object.replace("RigidModels\\Buildings\\", "").rstrip("\\").rstrip("/")

            mesh, assigned_mats = _create_mesh_from_rigid_node(node_name, rm, blender_materials, default_mat)
            obj = bpy.data.objects.new(node_name, mesh)
            obj.tw_file_reference_name = ref_name
            for mat in assigned_mats:
                obj.data.materials.append(mat)
            _apply_scene_node_transform(obj, scene_node, scene_nodes, context.scene)
            coll.objects.link(obj)
            continue

        # Soft Collision
        if class_rigid_info == "soft_collision" or node_name.endswith("_soft_collision"):
            coll = get_sub_coll(piece_idx, destruct_idx, "COLLISION")
            mesh, _ = _create_mesh_from_rigid_node(node_name, rm, blender_materials, default_mat)
            obj = bpy.data.objects.new(node_name, mesh)
            obj.tw_collision_type = "SOFT_COLLISION"
            _apply_scene_node_transform(obj, scene_node, scene_nodes, context.scene)
            coll.objects.link(obj)
            continue

        # Hard Collision
        if class_rigid_info == "collision3d" or "_collision3d" in node_name:
            coll = get_sub_coll(piece_idx, destruct_idx, "COLLISION")
            mesh, _ = _create_mesh_from_rigid_node(node_name, rm, blender_materials, default_mat)
            obj = bpy.data.objects.new(node_name, mesh)
            obj.tw_collision_type = "COLLISION"
            _apply_scene_node_transform(obj, scene_node, scene_nodes, context.scene)
            coll.objects.link(obj)
            continue

        # Platform Ground
        if class_rigid_info == "platform_ground" or node_name.endswith("_platform_ground"):
            coll = get_sub_coll(piece_idx, destruct_idx, "PLATFORM")
            mesh, _ = _create_mesh_from_rigid_node(
                node_name,
                rm,
                blender_materials,
                default_mat,
                orient_upward_matrix=_scene_node_matrix(scene_node, scene_nodes),
                warnings=warnings,
            )
            obj = bpy.data.objects.new(node_name, mesh)
            obj.tw_platform_type = "PLATFORM_GROUND"
            _apply_scene_node_transform(obj, scene_node, scene_nodes, context.scene)
            coll.objects.link(obj)
            continue

        # Platform
        if class_rigid_info.startswith("platform") or "_platform" in node_name:
            coll = get_sub_coll(piece_idx, destruct_idx, "PLATFORM")
            mesh, _ = _create_mesh_from_rigid_node(
                node_name,
                rm,
                blender_materials,
                default_mat,
                orient_upward_matrix=_scene_node_matrix(scene_node, scene_nodes),
                warnings=warnings,
            )
            obj = bpy.data.objects.new(node_name, mesh)
            obj.tw_platform_type = "PLATFORM"
            _apply_scene_node_transform(obj, scene_node, scene_nodes, context.scene)
            coll.objects.link(obj)
            continue

        # Arrow Emitter
        if class_rigid_info.startswith("arrow_emitter") or "_arrow_emitter" in node_name:
            coll = get_sub_coll(piece_idx, destruct_idx, "ARROW_EMITTERS")
            mesh, _ = _create_mesh_from_rigid_node(node_name, rm, blender_materials, default_mat)
            obj = bpy.data.objects.new(node_name, mesh)
            _apply_scene_node_transform(obj, scene_node, scene_nodes, context.scene)
            coll.objects.link(obj)
            continue

        # Flag - building-global, so it doesn't go through get_sub_coll's piece/destruct nesting
        if class_rigid_info == "flag" or node_name == "flag":
            if flag_coll is None:
                flag_coll = bpy.data.collections.new("Flag")
                flag_coll.tw_role = "FLAG"
                building_coll.children.link(flag_coll)
            mesh, _ = _create_mesh_from_rigid_node(node_name, rm, blender_materials, default_mat)
            obj = bpy.data.objects.new(node_name, mesh)
            _apply_scene_node_transform(obj, scene_node, scene_nodes, context.scene)
            flag_coll.objects.link(obj)
            continue

        # Height Map Mesh
        if class_rigid_info.startswith("height_map_mesh") or "_height_map_mesh" in node_name:
            coll = get_sub_coll(piece_idx, destruct_idx, "HEIGHT_MAP_MESH")
            mesh, _ = _create_mesh_from_rigid_node(node_name, rm, blender_materials, default_mat)
            obj = bpy.data.objects.new(node_name, mesh)
            _apply_scene_node_transform(obj, scene_node, scene_nodes, context.scene)
            coll.objects.link(obj)
            continue

        # LOD Display Mesh
        m_lod = re.search(r"lod(\d+)", class_rigid_info, re.IGNORECASE) or re.search(r"lod(\d+)", node_name, re.IGNORECASE)
        if m_lod or class_type == "DISPLAY":
            lod_num = int(m_lod.group(1)) if m_lod else 1
            lod_key = f"LOD{lod_num:02d}"

            coll = get_sub_coll(piece_idx, destruct_idx, "DISPLAY")
            mesh, assigned_mats = _create_mesh_from_rigid_node(node_name, rm, blender_materials, default_mat)
            obj = bpy.data.objects.new(node_name, mesh)
            obj.tw_lod_index = lod_key
            for mat in assigned_mats:
                obj.data.materials.append(mat)
            _apply_scene_node_transform(obj, scene_node, scene_nodes, context.scene)
            coll.objects.link(obj)
            continue

        warnings.append(f"Skipped unrecognized rigid node '{node_name}'.")

    # Process Line Nodes
    region_zones_coll = None

    for line_node in doc.lines:
        node_name = line_node.node_name
        name_lower = node_name.lower()

        class_rigid_info = ""
        for attr in line_node.attributes.strings:
            if attr.name == "class_rigidINFO":
                class_rigid_info = attr.value

        gate_match = nested_part_of(class_rigid_info, node_name)
        if gate_match is None and ("_anim" in name_lower or "gate" in name_lower):
            warnings.append(f"Skipped animation line '{node_name}'.")
            continue

        # A node can carry several geometry chunks and each chunk several LINE_DATA blocks. One
        # curve object per block rather than one multi-spline curve, because extraction requires
        # exactly one spline per curve object.
        line_datas = [line_data for chunk in line_node.geometry_chunks for line_data in chunk.lines if line_data.vertices]
        if not line_datas:
            continue

        for line_index, line_data in enumerate(line_datas, start=1):
            object_name = node_name if len(line_datas) == 1 else f"{node_name}_line{line_index:02d}"
            blender_pts = _undo_line_tessellation([_to_blender_space(v) for v in line_data.vertices])
            is_closed = _is_closed_loop(blender_pts)
            if is_closed:
                blender_pts = blender_pts[:-1]

            # Region Zone
            if node_name.startswith("region_zone") or class_rigid_info.startswith("region_zone"):
                if region_zones_coll is None:
                    region_zones_coll = bpy.data.collections.new("Region Zones")
                    region_zones_coll.tw_role = "REGION_ZONES"
                    building_coll.children.link(region_zones_coll)
                coll = region_zones_coll
                line_type = ""
                is_closed = True
            else:
                raw_piece = _extract_raw_piece_str(node_name, line_node.attributes)
                piece_idx = resolve_piece_index(raw_piece)
                destruct_idx = _extract_destruct_index(node_name, line_node.attributes)
                coll = get_sub_coll(piece_idx, destruct_idx, "LINES")
                if gate_match is not None:
                    line_type = gate_match[1]
                    is_closed = True
                else:
                    line_type = infer_line_type(node_name)
                    is_closed = is_closed or line_type == "OUTLINE"

            curve_data = bpy.data.curves.new(object_name, type="CURVE")
            curve_data.dimensions = "3D"
            spline = curve_data.splines.new("POLY")
            spline.use_cyclic_u = is_closed
            spline.points.add(len(blender_pts) - 1)
            for pt_idx, pt in enumerate(blender_pts):
                spline.points[pt_idx].co = (pt[0], pt[1], pt[2], 1.0)

            line_obj = bpy.data.objects.new(object_name, curve_data)
            if line_type:
                line_obj.tw_line_type = line_type
            coll.objects.link(line_obj)

    # Restore Damage Parent links: the parent_index on a destruct01 collision node is 1-based
    # against node_index, which real files keep in step with the scene-node array.
    all_scene_nodes = doc.scene_root.scene_nodes
    for scene_node in all_scene_nodes:
        if scene_node.parent_index == 0 or "collision3d" not in scene_node.name:
            continue
        parent_position = scene_node.parent_index - 1
        if not 0 <= parent_position < len(all_scene_nodes):
            continue
        parent_node = all_scene_nodes[parent_position]
        if "collision3d" not in parent_node.name:
            continue
        child_coll = piece_collections.get(resolve_piece_index(_extract_raw_piece_str(scene_node.name, scene_node.attributes)))
        parent_coll = piece_collections.get(resolve_piece_index(_extract_raw_piece_str(parent_node.name, parent_node.attributes)))
        if child_coll is not None and parent_coll is not None and child_coll is not parent_coll:
            child_coll.tw_damage_parent = parent_coll

    # Ensure every Destruct Level has valid Display and Collision objects
    for (p_idx, d_idx), d_coll in destruct_collections.items():
        disp_coll = sub_collections.get((p_idx, d_idx, "DISPLAY"))
        has_display = disp_coll is not None and (
            bool(disp_coll.objects) or any(child.objects for child in disp_coll.children)
        )
        if disp_coll is not None and not has_display:
            disp_mesh_data = bpy.data.meshes.new(f"piece{p_idx:02d}_destruct{d_idx:02d}_lod01")
            verts = [
                (-0.1, -0.1, 0.0), (0.1, -0.1, 0.0), (0.1, 0.1, 0.0), (-0.1, 0.1, 0.0),
                (-0.1, -0.1, 0.2), (0.1, -0.1, 0.2), (0.1, 0.1, 0.2), (-0.1, 0.1, 0.2)
            ]
            faces = [(0, 1, 2, 3), (4, 7, 6, 5), (0, 4, 5, 1), (1, 5, 6, 2), (2, 6, 7, 3), (3, 7, 4, 0)]
            disp_mesh_data.from_pydata(verts, [], faces)
            uv_layer = disp_mesh_data.uv_layers.new(name="UVMap")
            disp_mesh_data.update()
            disp_obj = bpy.data.objects.new(f"piece{p_idx:02d}_destruct{d_idx:02d}_lod01", disp_mesh_data)
            disp_obj.tw_lod_index = "LOD01"
            disp_obj.data.materials.append(default_mat)
            disp_coll.objects.link(disp_obj)

        col_colls = [c for c in d_coll.children if c.tw_role == "COLLISION"]
        has_collision = False
        if col_colls:
            has_collision = any(
                obj.type == "MESH" and getattr(obj, "tw_collision_type", "") in COLLISION_MESH_TYPES
                for obj in col_colls[0].objects
            )

        if not has_collision:
            c_coll = col_colls[0] if col_colls else get_sub_coll(p_idx, d_idx, "COLLISION")
            col_mesh_data = bpy.data.meshes.new(f"piece{p_idx:02d}_destruct{d_idx:02d}_collision3d")
            verts = [
                (-0.05, -0.05, 0.0), (0.05, -0.05, 0.0), (0.05, 0.05, 0.0), (-0.05, 0.05, 0.0),
                (-0.05, -0.05, 0.1), (0.05, -0.05, 0.1), (0.05, 0.05, 0.1), (-0.05, 0.05, 0.1)
            ]
            faces = [(0, 1, 2, 3), (4, 7, 6, 5), (0, 4, 5, 1), (1, 5, 6, 2), (2, 6, 7, 3), (3, 7, 4, 0)]
            col_mesh_data.from_pydata(verts, [], faces)
            col_mesh_data.update()
            col_obj = bpy.data.objects.new(f"piece{p_idx:02d}_destruct{d_idx:02d}_collision3d", col_mesh_data)
            col_obj.tw_collision_type = "COLLISION"
            c_coll.objects.link(col_obj)

        # Ensure if a Destruct level has EFLines, it also has a Platform mesh
        ef_colls = [c for c in d_coll.children if c.tw_role == "EF_LINES"]
        plat_colls = [c for c in d_coll.children if c.tw_role == "PLATFORM"]
        has_eflines = bool(ef_colls and ef_colls[0].objects)
        has_platform = bool(plat_colls and any(obj.type == "MESH" for obj in plat_colls[0].objects))

        if has_eflines and not has_platform:
            p_coll = plat_colls[0] if plat_colls else get_sub_coll(p_idx, d_idx, "PLATFORM")
            plat_mesh_data = bpy.data.meshes.new(f"piece{p_idx:02d}_destruct{d_idx:02d}_platform01")
            verts = [
                (-10.0, -10.0, 0.0), (10.0, -10.0, 0.0), (10.0, 10.0, 0.0), (-10.0, 10.0, 0.0)
            ]
            faces = [(0, 1, 2, 3)]
            plat_mesh_data.from_pydata(verts, [], faces)
            plat_mesh_data.update()
            plat_obj = bpy.data.objects.new(f"piece{p_idx:02d}_destruct{d_idx:02d}_platform01", plat_mesh_data)
            plat_obj.tw_platform_type = "PLATFORM"
            p_coll.objects.link(plat_obj)

    return building_coll, warnings
