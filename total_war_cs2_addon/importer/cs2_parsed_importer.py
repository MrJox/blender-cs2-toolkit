import os
import struct
import math
import bpy
import mathutils

from binary import CS2ParsedReader, CS2ParsedData
from props.properties import (
    EFLINE_ACTION_ITEMS,
    LINE_TYPE_BY_BUILDING_DATA_TYPE,
    BUILDING_DATA_TYPE_2DCOLLISION_HARD,
    BUILDING_DATA_TYPE_2DCOLLISION_GATE,
    GATE_COLLISION_TYPES,
)
from .zone_tech_importer import find_zone_tech_xml, import_zone_tech_xml
from .building_logic_importer import DockingLineRecord, find_building_logic_xml, read_docking_lines
from .cs2_importer import infer_line_type, nested_part_of, winds_upward, _is_closed_loop
from .proxy_loader import get_arrow_emitter_proxy_geometry, FLAG_VERTICES, FLAG_FACES

SOFT_COLLISION_CYLINDER_SIDES = 5


def _to_blender_space(vector: tuple[float, float, float]) -> tuple[float, float, float]:
    # Inverse of extraction._to_engine_space, which is its own inverse.
    x, y, z = vector
    return (x, z, y)


# Same template as ui/operators.py's TW_OT_new_arrow_emitter (kept as a separate copy rather than a
# shared import to avoid a circular import between this package and ui.operators, which already
# imports from here) - see that operator's own comment for where this shape comes from.
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


def _marker_line_geometry(start, end, direction):
    # Same 4-vertex shape as ui/operators.marker_line_geometry, aimed by the stored direction so a
    # re-export keeps the facing this file actually recorded.
    mid = tuple((s + e) / 2.0 for s, e in zip(start, end))
    half_length = math.hypot(end[0] - start[0], end[1] - start[1]) / 2.0
    length = math.hypot(direction[0], direction[1])
    if length == 0.0:
        return [start, end], [(0, 1)]
    tip = (mid[0] + direction[0] / length * half_length, mid[1] + direction[1] / length * half_length, mid[2])
    return [start, mid, end, tip], [(0, 1), (1, 2), (1, 3)]


def _matrix_to_blender_space(mat_floats: list[float]) -> mathutils.Matrix:
    # mathutils.Matrix's own `.translation` (and general row/column convention) expects the
    # translation in column 3, but the file's 4 float-groups are its rows in that sense - grouping
    # them directly into a Matrix(...) puts the real translation (the file's 4th group) into row 3
    # instead, which mathutils reads as (0, 0, 0) since column 3 ends up (0, 0, 0, 1). Confirmed
    # directly: building the matrix this way and reading .translation gave (0, 0, 0) even though
    # the file's own last float-group clearly held the true position - transposing fixes it exactly.
    mat = mathutils.Matrix([
        mat_floats[0:4],
        mat_floats[4:8],
        mat_floats[8:12],
        mat_floats[12:16],
    ]).transposed()
    swap = mathutils.Matrix([
        [1, 0, 0, 0],
        [0, 0, 1, 0],
        [0, 1, 0, 0],
        [0, 0, 0, 1],
    ])
    return swap @ mat @ swap.inverted()


def _line_type_for(building_data_type: int, name: str) -> str:
    # The compiled type is authoritative except where one value covers two authoring names, and
    # then only the node name separates them: RDT_2DCOLLISION_HARD is both Outline and Hard,
    # RDT_2DCOLLISION_GATE is both Gate Closed and Gate Ajar.
    if building_data_type == BUILDING_DATA_TYPE_2DCOLLISION_GATE:
        gate_match = nested_part_of("", name)
        return gate_match[1] if gate_match is not None else "GATE_CLOSED_HARD"
    if building_data_type == BUILDING_DATA_TYPE_2DCOLLISION_HARD:
        return infer_line_type(name)
    return LINE_TYPE_BY_BUILDING_DATA_TYPE.get(building_data_type) or infer_line_type(name)


def _as_signed32(value: int) -> int:
    # Blender's integer custom properties are C ints, so a raw uint32 overflows on assignment. The
    # only out-of-range value these fields actually carry is 0xFFFFFFFF, the format's "none"
    # sentinel, and reinterpreting it as signed turns it into the -1 it stands for.
    return value - 0x100000000 if value >= 0x80000000 else value


def _collision_object(collision, fallback_name: str) -> bpy.types.Object:
    name = collision.name or fallback_name
    blender_verts = [_to_blender_space(v) for v in collision.vertices]
    triangles = []
    for index in range(collision.face_count):
        v0, v1, v2 = struct.unpack_from("<III", collision.faces_bytes, index * 81 + 5)
        if v0 < len(blender_verts) and v1 < len(blender_verts) and v2 < len(blender_verts):
            # Reversed for the same reason as the platform polygons above.
            triangles.append((v2, v1, v0))

    mesh = bpy.data.meshes.new(name)
    mesh.from_pydata(blender_verts, [], triangles)
    mesh.update()

    obj = bpy.data.objects.new(name, mesh)
    obj["tw_source_node_index"] = _as_signed32(collision.node_index)
    obj["tw_source_node_flags"] = _as_signed32(collision.unk2)
    return obj


def _soft_collision_mesh(name: str, radius: float, height: float) -> bpy.types.Mesh:
    # BOB compiles the authored box into a cylinder by halving its width and keeping its height
    # (confirmed against both real samples: a 3.0 x 3.0 x 2.0 box became radius 1.5/height 2.0, and
    # a 0.7 x 0.7 x 2.5 box became radius 0.35/height 2.5), so radius is a circumradius here and
    # the base sits on the object origin the same way the authored box does.
    verts = []
    for level in (0.0, height):
        for corner in range(SOFT_COLLISION_CYLINDER_SIDES):
            angle = 2.0 * math.pi * corner / SOFT_COLLISION_CYLINDER_SIDES
            verts.append((radius * math.cos(angle), radius * math.sin(angle), level))

    sides = SOFT_COLLISION_CYLINDER_SIDES
    faces = [tuple(range(sides - 1, -1, -1)), tuple(range(sides, 2 * sides))]
    for corner in range(sides):
        nxt = (corner + 1) % sides
        faces.append((corner, nxt, nxt + sides, corner + sides))

    mesh = bpy.data.meshes.new(name)
    mesh.from_pydata(verts, [], faces)
    mesh.update()
    return mesh


def _infer_efline_action(action_id: int) -> str:
    if 0 <= action_id < len(EFLINE_ACTION_ITEMS):
        return EFLINE_ACTION_ITEMS[action_id][0]
    return "LOW_WALL"


def _build_combined_platform_mesh(mesh_name: str, polygons: list) -> tuple[bpy.types.Mesh | None, int]:
    combined_verts = []
    combined_faces = []
    already_upward = 0

    for poly in polygons:
        # _to_blender_space is a reflection, so a file polygon wound the way BOB wants it arrives
        # here wound the opposite way - and BOB refuses to place EFLines on a downward-facing
        # platform, so re-exporting one imported that way fails with "couldn't find platform for
        # efline". Deciding per polygon rather than reversing every one also corrects a file whose
        # platform was authored facing down in the first place.
        blender_pts = [_to_blender_space(v) for v in poly.vertices]
        if len(blender_pts) < 3:
            continue
        if winds_upward(blender_pts):
            # Already up here means it was down in the file - the one case that is a real fix
            # rather than the routine undoing of the reflection, so it is the one worth reporting.
            already_upward += 1
        else:
            blender_pts.reverse()
        base_idx = len(combined_verts)
        combined_verts.extend(blender_pts)
        for i in range(1, len(blender_pts) - 1):
            combined_faces.append((base_idx, base_idx + i, base_idx + i + 1))

    if not combined_verts or not combined_faces:
        return None, already_upward

    mesh_data = bpy.data.meshes.new(mesh_name)
    mesh_data.from_pydata(combined_verts, [], combined_faces)
    mesh_data.update()
    return mesh_data, already_upward


def _create_docking_lines(
    records: list[DockingLineRecord], destruct_collections: dict[str, bpy.types.Collection]
) -> tuple[int, int]:
    imported = 0
    unmatched = 0
    docking_collections: dict[str, bpy.types.Collection] = {}
    for record in records:
        destruct_coll = destruct_collections.get(record.destruct_key)
        if destruct_coll is None:
            unmatched += 1
            continue

        docking_coll = docking_collections.get(record.destruct_key)
        if docking_coll is None:
            docking_coll = bpy.data.collections.new("Docking Lines")
            docking_coll.tw_role = "DOCKING_LINES"
            destruct_coll.children.link(docking_coll)
            docking_collections[record.destruct_key] = docking_coll

        verts, edges = _marker_line_geometry(record.start, record.end, record.direction)
        mesh = bpy.data.meshes.new(record.name)
        mesh.from_pydata(verts, edges, [])
        mesh.update()

        obj = bpy.data.objects.new(record.name, mesh)
        # See ui/operators.lock_marker_line_tilt - only yaw matters for a marker.
        obj.lock_rotation[0] = True
        obj.lock_rotation[1] = True
        docking_coll.objects.link(obj)
        imported += 1
    return imported, unmatched


def import_cs2_parsed(filepath: str, context: bpy.types.Context) -> tuple[bpy.types.Collection, list[str]]:
    parsed = CS2ParsedReader.read_file(filepath)
    filename_stem = os.path.splitext(os.path.basename(filepath))[0]
    if filename_stem.endswith(".cs2"):
        filename_stem = os.path.splitext(filename_stem)[0]
    if filename_stem.endswith("_tech"):
        filename_stem = filename_stem[:-5]

    building_coll = bpy.data.collections.new(filename_stem)
    building_coll.tw_role = "BUILDING"
    building_coll.tw_asset_type = "DISPLAY_BUILDING"
    building_coll["tw_source_bounding_box"] = [c for corner in parsed.header.bounding_box for c in corner]
    context.scene.collection.children.link(building_coll)

    warnings: list[str] = []
    destruct_collections: dict[str, bpy.types.Collection] = {}
    piece_collections: list[bpy.types.Collection] = []

    downward_platform_polygons = 0
    skipped_windows = 0
    skipped_doors = 0
    skipped_nogo = 0
    skipped_cannons = 0
    skipped_docking = 0

    for piece in parsed.pieces:
        piece_coll = bpy.data.collections.new(piece.name or "Piece")
        piece_coll.tw_role = "PIECE"
        piece_coll["tw_placement_name"] = piece.place_name
        piece_coll["tw_placement_transform"] = list(piece.place_transform)
        building_coll.children.link(piece_coll)
        piece_collections.append(piece_coll)

        for destruct in piece.destructs:
            destruct_coll = bpy.data.collections.new(destruct.name or "Destruct")
            destruct_coll.tw_role = "DESTRUCT"
            destruct_coll["tw_destruct_index"] = _as_signed32(destruct.index)
            destruct_coll["tw_hit_points_threshold"] = _as_signed32(destruct.hit_points_threshold)
            if destruct.bounding_box is not None:
                destruct_coll["tw_source_bounding_box"] = [c for corner in destruct.bounding_box for c in corner]
            piece_coll.children.link(destruct_coll)
            destruct_collections[(destruct.name or "").lower()] = destruct_coll

            display_coll = bpy.data.collections.new("Display")
            display_coll.tw_role = "DISPLAY"
            destruct_coll.children.link(display_coll)

            collision_coll = bpy.data.collections.new("Collision")
            collision_coll.tw_role = "COLLISION"
            destruct_coll.children.link(collision_coll)

            c = destruct.collision
            if len(c.vertices) > 0:
                col_obj = _collision_object(c, c.name or f"{destruct.name}_collision3d")
                col_obj.tw_collision_type = "COLLISION"
                collision_coll.objects.link(col_obj)
            else:
                col_mesh_data = bpy.data.meshes.new(c.name or f"{destruct.name}_collision3d")
                verts = [
                    (-0.05, -0.05, 0.0),
                    (0.05, -0.05, 0.0),
                    (0.05, 0.05, 0.0),
                    (-0.05, 0.05, 0.0),
                    (-0.05, -0.05, 0.1),
                    (0.05, -0.05, 0.1),
                    (0.05, 0.05, 0.1),
                    (-0.05, 0.05, 0.1),
                ]
                faces = [(0, 1, 2, 3), (4, 7, 6, 5), (0, 4, 5, 1), (1, 5, 6, 2), (2, 6, 7, 3), (3, 7, 4, 0)]
                col_mesh_data.from_pydata(verts, [], faces)
                col_mesh_data.update()

                col_obj = bpy.data.objects.new(c.name or f"{destruct.name}_collision3d", col_mesh_data)
                col_obj.tw_collision_type = "COLLISION"
                col_obj["tw_source_node_index"] = _as_signed32(c.node_index)
                col_obj["tw_source_node_flags"] = _as_signed32(c.unk2)
                collision_coll.objects.link(col_obj)

            # Boiling Oil collision - UNCONFIRMED which array BOB actually compiles this into; no
            # compiled .cs2.parsed exists yet for a boiling-oil building to check against. Best
            # effort: _read_collision3d already preserves each volume's own authored name generically
            # (proven for the gate toggle_items pair below), so scan windows/doors - the two arrays
            # for "additional named collision3d beyond the main one" - for a name match rather than
            # assuming one specific array. Harmless if this guess is wrong: the object is just not
            # found, nothing else is affected. Revisit once a real BOB compile of a boiling-oil
            # building exists.
            for candidate in destruct.windows + destruct.doors:
                named = nested_part_of("", candidate.name)
                if named is not None and named[1] == "BOILING_OIL":
                    oil_obj = _collision_object(candidate, candidate.name)
                    oil_obj.tw_collision_type = "BOILING_OIL"
                    collision_coll.objects.link(oil_obj)
                    break

            # A gate compiles to a toggle_items pair (closed volume, ajar volume) plus its
            # RDT_2DCOLLISION_GATE lines. Display meshes live in the .rigid_model_v2, not here.
            gate_lines = [l for l in destruct.lines if l.line_type == BUILDING_DATA_TYPE_2DCOLLISION_GATE]

            for item_index, item in enumerate(destruct.special_items, start=1):
                for collision_type, collision in (("GATE_CLOSED", item.closed), ("GATE_AJAR", item.ajar)):
                    if not collision.vertices:
                        continue
                    # BOB keeps the authored node names, so they decide which half is which; the
                    # pair's own order is only the fallback.
                    named = nested_part_of("", collision.name)
                    if named is not None and named[1] in GATE_COLLISION_TYPES:
                        collision_type = named[1]
                    suffix = "gate_closed" if collision_type == "GATE_CLOSED" else "gate_ajar"
                    obj = _collision_object(collision, f"{destruct.name}_collision3d_{suffix}{item_index:02d}")
                    obj.tw_collision_type = collision_type
                    collision_coll.objects.link(obj)

            for soft in destruct.soft_collisions:
                soft_name = soft.name or f"{destruct.name}_soft_collision"
                soft_obj = bpy.data.objects.new(soft_name, _soft_collision_mesh(soft_name, soft.radius, soft.height))
                soft_obj.tw_collision_type = "SOFT_COLLISION"
                soft_obj.matrix_world = _matrix_to_blender_space(soft.transform)
                soft_obj["tw_soft_collision_id"] = soft.cylinder_id
                collision_coll.objects.link(soft_obj)

            # Build Platforms (combining polygons per platform type)
            if destruct.platform and len(destruct.platform.polygons) > 0:
                platform_coll = bpy.data.collections.new("Platform")
                platform_coll.tw_role = "PLATFORM"
                destruct_coll.children.link(platform_coll)

                regular_polys = [p for p in destruct.platform.polygons if not p.is_ground]
                ground_polys = [p for p in destruct.platform.polygons if p.is_ground]

                if regular_polys:
                    plat_name = f"{destruct.name}_platform01"
                    plat_mesh, plat_downward = _build_combined_platform_mesh(plat_name, regular_polys)
                    downward_platform_polygons += plat_downward
                    if plat_mesh:
                        plat_obj = bpy.data.objects.new(plat_name, plat_mesh)
                        plat_obj.tw_platform_type = "PLATFORM"
                        platform_coll.objects.link(plat_obj)

                if ground_polys:
                    ground_name = f"{destruct.name}_platform_ground"
                    ground_mesh, ground_downward = _build_combined_platform_mesh(ground_name, ground_polys)
                    downward_platform_polygons += ground_downward
                    if ground_mesh:
                        ground_obj = bpy.data.objects.new(ground_name, ground_mesh)
                        ground_obj.tw_platform_type = "PLATFORM_GROUND"
                        platform_coll.objects.link(ground_obj)

            if len(destruct.file_refs) > 0:
                fileref_coll = bpy.data.collections.new("Referenced Props")
                fileref_coll.tw_role = "FILE_REFERENCE"
                destruct_coll.children.link(fileref_coll)

                for ref in destruct.file_refs:
                    ref_name = f"{destruct.name}_file:{ref.name or ref.key}"
                    empty_obj = bpy.data.objects.new(ref_name, None)
                    empty_obj.empty_display_type = "CUBE"
                    empty_obj.empty_display_size = 1.0
                    empty_obj.tw_file_reference_name = ref.name or ref.key
                    empty_obj.matrix_world = _matrix_to_blender_space(ref.matrix)
                    empty_obj["tw_file_reference_key"] = ref.key
                    empty_obj["tw_file_reference_flags"] = _as_signed32(ref.unk)
                    fileref_coll.objects.link(empty_obj)

            # Build Lines & Pipes
            plain_entries = [(l, l.line_type) for l in destruct.lines if l.line_type != BUILDING_DATA_TYPE_2DCOLLISION_GATE]
            plain_entries += [(p, p.pipe_type) for p in destruct.pipes]
            lines_coll = None
            if plain_entries or gate_lines:
                lines_coll = bpy.data.collections.new("Lines")
                lines_coll.tw_role = "LINES"
                destruct_coll.children.link(lines_coll)

            # A line is closed only when it actually comes back to its own start: a real
            # ground_ad is a 2-vertex open line, and the gate hard lines are 4-vertex open
            # ones, so closing every entry here turned real open lines into loops.
            for entry, entry_type in plain_entries + [(l, l.line_type) for l in gate_lines]:
                if len(entry.vertices) < 2:
                    continue
                blender_pts = [_to_blender_space(v) for v in entry.vertices]
                closed = _is_closed_loop(blender_pts)
                if closed:
                    blender_pts = blender_pts[:-1]

                curve_data = bpy.data.curves.new(entry.name, type="CURVE")
                curve_data.dimensions = "3D"
                spline = curve_data.splines.new("POLY")
                spline.use_cyclic_u = closed
                spline.points.add(len(blender_pts) - 1)
                for pt_idx, pt in enumerate(blender_pts):
                    spline.points[pt_idx].co = (pt[0], pt[1], pt[2], 1.0)

                line_obj = bpy.data.objects.new(entry.name, curve_data)
                line_obj["tw_source_building_data_type"] = entry_type
                line_obj.tw_line_type = _line_type_for(entry_type, entry.name)
                lines_coll.objects.link(line_obj)

            if len(destruct.eflines) > 0:
                eflines_coll = bpy.data.collections.new("EFLines")
                eflines_coll.tw_role = "EF_LINES"
                destruct_coll.children.link(eflines_coll)

                for efline in destruct.eflines:
                    start_pt = _to_blender_space(efline.start)
                    end_pt = _to_blender_space(efline.end)
                    verts, edges = _marker_line_geometry(start_pt, end_pt, _to_blender_space(efline.direction))
                    ef_mesh = bpy.data.meshes.new(efline.name)
                    ef_mesh.from_pydata(verts, edges, [])
                    ef_mesh.update()

                    ef_obj = bpy.data.objects.new(efline.name, ef_mesh)
                    # See ui/operators.lock_marker_line_tilt - only yaw matters for a marker.
                    ef_obj.lock_rotation[0] = True
                    ef_obj.lock_rotation[1] = True
                    ef_obj.tw_efline_action = _infer_efline_action(efline.action)
                    ef_obj["tw_platform_parent_index"] = _as_signed32(efline.parent)
                    eflines_coll.objects.link(ef_obj)

            if len(destruct.arrow_emitters) > 0:
                arrow_coll = bpy.data.collections.new("Arrow Emitters")
                arrow_coll.tw_role = "ARROW_EMITTERS"
                destruct_coll.children.link(arrow_coll)

                ae_verts, ae_tris = get_arrow_emitter_proxy_geometry()
                for emitter in destruct.arrow_emitters:
                    ae_mesh = bpy.data.meshes.new(emitter.name)
                    ae_mesh.from_pydata(ae_verts, [], ae_tris)
                    ae_mesh.update()

                    ae_obj = bpy.data.objects.new(emitter.name, ae_mesh)
                    ae_obj.matrix_world = _matrix_to_blender_space(emitter.transform)
                    arrow_coll.objects.link(ae_obj)

            skipped_windows += destruct.windows_count
            skipped_doors += destruct.doors_count
            skipped_nogo += len(destruct.nogo_zones)
            skipped_cannons += destruct.cannons_count
            skipped_docking += destruct.docking_points_count

    # BuildingPiece.parent_index is the compiled form of the Damage Parent link, with 0xFFFFFFFF
    # for a top-level piece.
    for piece, piece_coll in zip(parsed.pieces, piece_collections):
        if not 0 <= piece.parent_index < len(piece_collections):
            continue
        parent_coll = piece_collections[piece.parent_index]
        if parent_coll is not piece_coll:
            piece_coll.tw_damage_parent = parent_coll

    if parsed.header.flag_name:
        flag_coll = bpy.data.collections.new("Flag")
        flag_coll.tw_role = "FLAG"
        building_coll.children.link(flag_coll)
        flag_mesh = bpy.data.meshes.new(parsed.header.flag_name)
        flag_mesh.from_pydata(FLAG_VERTICES, [], FLAG_FACES)
        flag_mesh.update()
        flag_obj = bpy.data.objects.new(parsed.header.flag_name, flag_mesh)
        flag_obj.matrix_world = _matrix_to_blender_space(parsed.header.flag_transform)
        flag_coll.objects.link(flag_obj)

    xml_path = find_zone_tech_xml(filepath)
    if xml_path:
        zone_count = import_zone_tech_xml(xml_path, building_coll)
        if zone_count > 0:
            warnings.append(f"Imported {zone_count} Region Zone(s) from '{os.path.basename(xml_path)}'.")

    logic_path = find_building_logic_xml(filepath)
    if logic_path:
        docking_count, unmatched = _create_docking_lines(read_docking_lines(logic_path), destruct_collections)
        if docking_count > 0:
            warnings.append(f"Imported {docking_count} Docking Line(s) from '{os.path.basename(logic_path)}'.")
        if unmatched > 0:
            warnings.append(
                f"Skipped {unmatched} Docking Line(s) from '{os.path.basename(logic_path)}' that name no "
                "destruct level in this file."
            )

    if downward_platform_polygons > 0:
        warnings.append(
            f"Flipped {downward_platform_polygons} platform polygon(s) that faced downwards in the file, so "
            "they face up as BOB needs them to."
        )
    if skipped_windows > 0:
        warnings.append(f"Skipped {skipped_windows} Window collision object(s) (postponed for future implementation).")
    if skipped_doors > 0:
        warnings.append(f"Skipped {skipped_doors} Door collision object(s) (postponed for future implementation).")
    if skipped_nogo > 0:
        warnings.append(f"Skipped {skipped_nogo} No-Go Zone(s) (postponed for future implementation).")
    if skipped_cannons > 0:
        warnings.append(f"Skipped {skipped_cannons} Cannon emitter(s) (postponed for future implementation).")
    if skipped_docking > 0:
        warnings.append(f"Skipped {skipped_docking} Docking point(s) (postponed for future implementation).")

    return building_coll, warnings
