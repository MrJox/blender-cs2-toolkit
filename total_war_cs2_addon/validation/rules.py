from dataclasses import dataclass

import bpy

from extraction.extract import has_second_uv_layer
from extraction.animation import has_keyframed_animation
from materials.material_builder import is_placeholder_image, read_uv2_layer_name
from binary.bone_table import ROOT_BONE_TYPE
from materials.shader_types import (
    SHADER_TYPE_LABELS,
    UV2_TEXTURE_SLOT_BY_SHADER_TYPE,
    WEIGHTED_SHADER_TYPES,
)
from props.properties import (
    COLLISION_MESH_TYPES,
    COLLISION_TYPE_LABELS,
    LOD_INDEX_BY_IDENTIFIER,
    LOD_LABELS,
    NESTED_DISPLAY_ROLES,
    NO_BONE_TYPE,
)
from extraction.unit_extract import (
    armature_of,
    attachment_point_objects,
    find_unit_armature,
    mesh_objects,
    unit_kind,
    unit_model_collections,
)
from scene_model.unit_models import MAX_BONE_INFLUENCES, WEIGHTED_KIND


@dataclass
class ValidationIssue:
    severity: str
    message: str
    object_name: str = ""


def _children_with_role(collection: bpy.types.Collection, role: str) -> list[bpy.types.Collection]:
    return [child for child in collection.children if child.tw_role == role]


def _lod_collections(display_collection: bpy.types.Collection) -> list[bpy.types.Collection]:
    # A Display collection and each nested sub-collection inside it are separate LOD namespaces: a
    # plain lod01, a gate_closed_lod01, and a boiling_oil_lod01 are all different nodes and may all
    # exist at once.
    return [display_collection] + [
        child for role in NESTED_DISPLAY_ROLES for child in _children_with_role(display_collection, role)
    ]


def _object_materials(obj: bpy.types.Object) -> list[bpy.types.Material]:
    materials = [slot.material for slot in obj.material_slots if slot.material is not None]
    if not materials and obj.active_material is not None:
        materials.append(obj.active_material)
    return materials


# The CS2 scene node carries no authored scale - cs2_builder writes the fixed
# SCENE_NODE_DEFAULT_SCALE_OR_PIVOT every real sample has - so for the nodes whose mesh stays in
# local space the object's scale reaches neither the file nor the game. Applying it is only a real
# fix where the mesh itself is exported; a file reference's size comes from the prop it names.
def _validate_ignored_scale(obj: bpy.types.Object, mesh_is_exported: bool = True) -> list[ValidationIssue]:
    if all(abs(component - 1.0) < 1e-4 for component in obj.matrix_world.to_scale()):
        return []
    remedy = (
        " Apply it with Object > Apply > Scale to bake the size into the mesh."
        if mesh_is_exported
        else " Its size in game comes from the prop it references."
    )
    return [
        ValidationIssue(
            "WARNING",
            f"'{obj.name}' is scaled in Object Mode, but only its position and rotation are exported, "
            f"so the scale is dropped.{remedy}",
            obj.name,
        )
    ]


def _validate_uv2_preview(obj: bpy.types.Object, materials: list[bpy.types.Material]) -> list[ValidationIssue]:
    # Export is unaffected - _second_uv_layer falls back to the mesh's own second layer - but
    # Blender's UV Map node has no such fallback, so an unresolvable name shows channel 1 in the
    # viewport while the game gets channel 2.
    issues = []
    for material in materials:
        shader_type = getattr(material, "tw_shader_type", "default")
        texture_slot = UV2_TEXTURE_SLOT_BY_SHADER_TYPE.get(shader_type)
        if texture_slot is None or obj.data.uv_layers.get(read_uv2_layer_name(material)) is not None:
            continue
        issues.append(
            ValidationIssue(
                "WARNING",
                f"'{obj.name}' exports UV channel 2 correctly, but '{material.name}'s UV2 node is not "
                f"pointed at any of this mesh's UV maps, so its {texture_slot} looks wrong in the Blender "
                f"preview only. Press Make Total War Material again to point it at the second UV map.",
                obj.name,
            )
        )
    return issues


def _validate_uv2_channel(obj: bpy.types.Object) -> list[ValidationIssue]:
    if not obj.data.uv_layers:
        return []

    materials = _object_materials(obj)
    uv2_layer_name = ""
    for material in materials:
        uv2_layer_name = read_uv2_layer_name(material)
        if uv2_layer_name:
            break
    if has_second_uv_layer(obj.data, uv2_layer_name):
        return _validate_uv2_preview(obj, materials)

    issues = []
    for material in materials:
        shader_type = getattr(material, "tw_shader_type", "default")
        texture_slot = UV2_TEXTURE_SLOT_BY_SHADER_TYPE.get(shader_type)
        if texture_slot is None:
            continue
        issues.append(
            ValidationIssue(
                "WARNING",
                f"'{obj.name}' has no second UV map, but its material '{material.name}' uses the "
                f"{SHADER_TYPE_LABELS[shader_type]} shader, which reads its {texture_slot} from UV channel 2. "
                f"Add a second UV map and point the material's UV2 node at it, or that texture will be "
                f"wrong in game.",
                obj.name,
            )
        )
    return issues


def _validate_lod_chain(lod_objects_by_level: dict[str, str], where: str) -> list[ValidationIssue]:
    # BOB compiles any of these without complaint, so they are warnings rather than blocking errors -
    # measured by compiling the same three-mesh model three ways:
    #   levels 1, 2, 3 -> three LODs at camera distances 100 / 200 / 400
    #   levels 1, 2, 4 -> three LODs at 100 / 200 / 500, so the meshes pack into consecutive slots
    #                     while each keeps the distance its own level implies
    #   levels 2, 3    -> two LODs starting at 200, leaving the closest band to the level 2 mesh
    # Every authored chain in the sample corpus starts at 1 and has no gaps (24 of 24), though their
    # lengths vary from one level to five, so a short chain is normal and only these two are not.
    if not lod_objects_by_level:
        return []
    levels = sorted(LOD_INDEX_BY_IDENTIFIER[identifier] for identifier in lod_objects_by_level)
    issues = []
    if levels[0] != 1:
        issues.append(
            ValidationIssue(
                "WARNING",
                f"'{where}' has no LOD 1, so its closest-camera level is the LOD {levels[0]} mesh - "
                f"nothing is defined nearer than that level's own distance.",
                where,
            )
        )
    missing = [level for level in range(levels[0], levels[-1]) if level not in levels]
    if missing:
        listed = ", ".join(str(level) for level in missing)
        issues.append(
            ValidationIssue(
                "WARNING",
                f"'{where}' skips LOD {listed}. The levels it does have compile into consecutive slots, "
                "each keeping the camera distance its own level implies, so the result is a shorter "
                "chain with a gap in the distances rather than what the numbering suggests.",
                where,
            )
        )
    return issues


def _validate_display_object(obj: bpy.types.Object) -> list[ValidationIssue]:
    issues = []
    if obj.type != "MESH":
        return issues

    if not obj.data.uv_layers:
        issues.append(
            ValidationIssue(
                "ERROR",
                f"'{obj.name}' is missing a UV map. Display models need UV coordinates for their textures.",
                obj.name,
            )
        )

    if obj.active_material is None:
        issues.append(ValidationIssue("ERROR", f"'{obj.name}' has no material assigned.", obj.name))
    else:
        material = obj.active_material
        if getattr(material, "tw_shader_type", "default") == "collision":
            issues.append(
                ValidationIssue(
                    "WARNING",
                    f"'{obj.name}' is a visible Display mesh but its material '{material.name}' uses the Collision shader type.",
                    obj.name,
                )
            )
        if material.use_nodes and material.node_tree is not None:
            diffuse_node = material.node_tree.nodes.get("Diffuse")
            if diffuse_node is None or diffuse_node.image is None or is_placeholder_image(diffuse_node.image):
                issues.append(
                    ValidationIssue(
                        "WARNING",
                        f"'{material.name}' has no Diffuse texture assigned and will render as a flat default colour.",
                        obj.name,
                    )
                )
    issues.extend(_validate_uv2_channel(obj))
    return issues


def _validate_animated_mesh_object(obj: bpy.types.Object) -> list[ValidationIssue]:
    issues = _validate_display_object(obj)
    if obj.type == "MESH" and not has_keyframed_animation(obj):
        issues.append(
            ValidationIssue(
                "WARNING",
                f"'{obj.name}' has no keyframed animation and will export as a static, unmoving mesh. "
                "Add location/rotation keyframes in Blender's timeline (I to insert a key) if it should move.",
                obj.name,
            )
        )
    return issues


def _has_destruct01_collision(piece_collection: bpy.types.Collection) -> bool:
    # "COLLISION" or "BOILING_OIL" specifically, matching cs2_builder.py's damage-link anchor
    # fallback exactly (a piece with no plain collision mesh still needs a destruct01 collision-type
    # node to anchor the link to - confirmed real for Boiling Oil, see cs2_builder.py's comment).
    # Not GATE_CLOSED/GATE_AJAR - cs2_builder.py has no matching fallback for those yet, so accepting
    # them here would let validation pass while export silently drops the link.
    destruct_collections = _children_with_role(piece_collection, "DESTRUCT")
    if not destruct_collections:
        return False
    for collision_collection in _children_with_role(destruct_collections[0], "COLLISION"):
        for obj in collision_collection.objects:
            if obj.type == "MESH" and obj.tw_collision_type in ("COLLISION", "BOILING_OIL"):
                return True
    return False


def _validate_damage_parents(piece_collections: list[bpy.types.Collection]) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    siblings = {collection.as_pointer() for collection in piece_collections}

    for piece_collection in piece_collections:
        parent = piece_collection.tw_damage_parent
        if parent is None:
            continue

        if parent is piece_collection:
            issues.append(
                ValidationIssue("ERROR", f"'{piece_collection.name}' is set as its own Damage Parent.")
            )
            continue

        if parent.tw_role != "PIECE" or parent.as_pointer() not in siblings:
            issues.append(
                ValidationIssue(
                    "ERROR",
                    f"'{piece_collection.name}' has Damage Parent '{parent.name}', which isn't a "
                    "Building Piece of this building.",
                )
            )
            continue

        if not _has_destruct01_collision(piece_collection):
            issues.append(
                ValidationIssue(
                    "ERROR",
                    f"'{piece_collection.name}' has a Damage Parent but no collision mesh on its "
                    "first destruct level, which is where the link is stored.",
                )
            )

        seen = {piece_collection.as_pointer()}
        depth = 0
        walker = parent
        while walker is not None and walker.as_pointer() not in seen and walker.tw_role == "PIECE":
            seen.add(walker.as_pointer())
            depth += 1
            walker = walker.tw_damage_parent

        if walker is not None and walker.as_pointer() in seen:
            issues.append(
                ValidationIssue(
                    "ERROR",
                    f"'{piece_collection.name}' is part of a Damage Parent loop - follow the chain "
                    "and it comes back to itself.",
                )
            )
        elif depth > 1:
            issues.append(
                ValidationIssue(
                    "WARNING",
                    f"'{piece_collection.name}' is {depth} Damage Parents deep. No real Total War "
                    "building nests them more than one level, so this is untested.",
                )
            )

    return issues


def _validate_unroled_collections(collection: bpy.types.Collection) -> list[ValidationIssue]:
    # Every extraction step reads a collection's own .objects, never all_objects, so a plain
    # organisational sub-collection an artist adds inside Display (or any other role) takes its
    # meshes out of the export without anything else noticing.
    issues = []
    for child in collection.children:
        if child.tw_role == "NONE" and len(child.objects) > 0:
            issues.append(
                ValidationIssue(
                    "WARNING",
                    f"'{child.name}' sits inside '{collection.name}' but is not one of the add-on's own "
                    f"collections, so the {len(child.objects)} object(s) in it are left out of the export. "
                    f"Move them up into '{collection.name}' itself.",
                    child.name,
                )
            )
        issues.extend(_validate_unroled_collections(child))
    return issues


# The exported .CS2 is named after the collection, and Blender lets a collection be called
# anything - a name Windows cannot spell reaches the artist as an OSError from the write, long
# after the point they could have fixed it, and one holding a separator writes outside the export
# folder entirely.
_ILLEGAL_FILENAME_CHARACTERS = set(r'<>:"/\|?*') | {chr(code) for code in range(32)}
_RESERVED_FILENAMES = {"CON", "PRN", "AUX", "NUL"} | {
    f"{prefix}{digit}" for prefix in ("COM", "LPT") for digit in "123456789"
}


def _validate_export_name(name: str) -> list[ValidationIssue]:
    illegal = sorted({character for character in name if character in _ILLEGAL_FILENAME_CHARACTERS})
    if illegal:
        shown = ", ".join(repr(character) for character in illegal)
        return [
            ValidationIssue(
                "ERROR",
                f"'{name}' is the name of the exported file, and it contains {shown} - rename it to "
                "something a filename can hold.",
                name,
            )
        ]
    if name != name.rstrip(" .") or name.upper() in _RESERVED_FILENAMES:
        return [
            ValidationIssue(
                "ERROR",
                f"'{name}' is the name of the exported file, and Windows cannot hold a file by that "
                "name - rename it.",
                name,
            )
        ]
    return []


def validate_building(building_collection: bpy.types.Collection) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []

    issues.extend(_validate_export_name(building_collection.name))

    issues.extend(_validate_unroled_collections(building_collection))

    piece_collections = _children_with_role(building_collection, "PIECE")
    if not piece_collections:
        issues.append(ValidationIssue("ERROR", f"Building '{building_collection.name}' has no Building Pieces yet."))
        return issues

    issues.extend(_validate_damage_parents(piece_collections))

    for piece_collection in piece_collections:
        destruct_collections = _children_with_role(piece_collection, "DESTRUCT")
        if not destruct_collections:
            issues.append(ValidationIssue("ERROR", f"'{piece_collection.name}' has no destruct levels yet."))
            continue

        for destruct_collection in destruct_collections:
            display_collections = _children_with_role(destruct_collection, "DISPLAY")
            if not display_collections:
                issues.append(ValidationIssue("ERROR", f"'{destruct_collection.name}' has no Display collection."))
                continue

            display_objects = [
                obj for collection in _lod_collections(display_collections[0]) for obj in collection.objects if obj.type == "MESH"
            ]
            if not display_objects:
                issues.append(ValidationIssue("ERROR", f"'{display_collections[0].name}' has no meshes in it yet."))
            for obj in display_objects:
                issues.extend(_validate_display_object(obj))

            for collection in _lod_collections(display_collections[0]):
                lod_indices_seen: dict[str, str] = {}
                for obj in collection.objects:
                    if obj.type != "MESH":
                        continue
                    existing = lod_indices_seen.get(obj.tw_lod_index)
                    if existing is not None:
                        issues.append(
                            ValidationIssue(
                                "ERROR",
                                f"'{obj.name}' and '{existing}' both use LOD Level '{LOD_LABELS[obj.tw_lod_index]}' - "
                                "each Display mesh needs a distinct LOD Level.",
                                obj.name,
                            )
                        )
                    else:
                        lod_indices_seen[obj.tw_lod_index] = obj.name
                issues.extend(_validate_lod_chain(lod_indices_seen, collection.name))

            collision_collections = _children_with_role(destruct_collection, "COLLISION")
            collision_objects = []
            soft_collision_objects = []
            for collision_collection in collision_collections:
                for obj in collision_collection.objects:
                    if obj.type != "MESH":
                        continue
                    collision_objects.append(obj)
                    if obj.tw_collision_type == "SOFT_COLLISION":
                        soft_collision_objects.append(obj)
                    elif obj.tw_collision_type not in COLLISION_MESH_TYPES:
                        issues.append(
                            ValidationIssue(
                                "WARNING",
                                f"'{obj.name}' uses collision type "
                                f"'{COLLISION_TYPE_LABELS.get(obj.tw_collision_type, obj.tw_collision_type)}', which isn't "
                                "supported yet and will be skipped on export.",
                                obj.name,
                            )
                        )

            for obj in soft_collision_objects:
                if len(obj.data.vertices) == 0:
                    issues.append(ValidationIssue("ERROR", f"'{obj.name}' has no geometry.", obj.name))

            if not any(obj.tw_collision_type in COLLISION_MESH_TYPES for obj in collision_objects):
                issues.append(
                    ValidationIssue(
                        "ERROR",
                        f"'{destruct_collection.name}' has no collision mesh. Total War buildings need at least "
                        "one collision mesh in their Collision collection, or BOB will crash when processing them.",
                    )
                )

            for platform_collection in _children_with_role(destruct_collection, "PLATFORM"):
                for obj in platform_collection.objects:
                    if obj.type != "MESH":
                        continue
                    if len(obj.data.vertices) == 0:
                        issues.append(ValidationIssue("ERROR", f"'{obj.name}' has no geometry.", obj.name))
                        continue
                    # Confirmed via a real BOB run: BOB can't place an EFLine on a platform polygon
                    # that faces downwards. The exporter flips these, but the artist should know.
                    # World space, like the exporter: gondor_fort_gateway_e's piece04 platform is
                    # wound downwards in its own mesh and stood up by the object's rotation, and
                    # judging the local normal reported it as broken when it is not.
                    normal_matrix = obj.matrix_world.to_3x3().inverted_safe().transposed()
                    downward = sum(1 for polygon in obj.data.polygons if (normal_matrix @ polygon.normal).z < 0.0)
                    if downward:
                        issues.append(
                            ValidationIssue(
                                "WARNING",
                                f"'{obj.name}' has {downward} face(s) pointing downwards. A platform is a walkable "
                                "surface, so BOB can't place EFLines on it that way - the exporter flips them, but "
                                "fixing it in Blender (Mesh > Normals > Recalculate Outside, or Flip) is cleaner.",
                                obj.name,
                            )
                        )

            for arrow_emitters_collection in _children_with_role(destruct_collection, "ARROW_EMITTERS"):
                for obj in arrow_emitters_collection.objects:
                    if obj.type == "MESH" and len(obj.data.vertices) == 0:
                        issues.append(ValidationIssue("ERROR", f"'{obj.name}' has no geometry.", obj.name))
                    issues.extend(_validate_ignored_scale(obj))

            for destruction_anim_collection in _children_with_role(destruct_collection, "DESTRUCTION_ANIM"):
                for obj in destruction_anim_collection.objects:
                    if obj.type == "MESH":
                        issues.extend(_validate_animated_mesh_object(obj))

            for gate_anim_collection in _children_with_role(display_collections[0], "GATE_ANIMATION"):
                for obj in gate_anim_collection.objects:
                    if obj.type == "MESH":
                        issues.extend(_validate_animated_mesh_object(obj))

            for file_reference_collection in _children_with_role(destruct_collection, "FILE_REFERENCE"):
                for obj in file_reference_collection.objects:
                    if not obj.tw_file_reference_name:
                        issues.append(
                            ValidationIssue(
                                "ERROR",
                                f"'{obj.name}' needs a Referenced Prop Name set before it can be exported.",
                                obj.name,
                            )
                        )
                    issues.extend(_validate_display_object(obj))
                    issues.extend(_validate_ignored_scale(obj, mesh_is_exported=False))

            for lines_collection in _children_with_role(destruct_collection, "LINES"):
                for obj in lines_collection.objects:
                    issues.extend(_validate_line_object(obj))

            ef_lines_collections = _children_with_role(destruct_collection, "EF_LINES")
            # Confirmed via a real BOB run: EFLine needs to sit on a platform
            # ("couldn't find platform for efline") - Docking Lines (a separate collection/tech,
            # see DOCKING_LINES below) don't have this requirement.
            ef_line_objects = [obj for c in ef_lines_collections for obj in c.objects if obj.type == "MESH"]
            if ef_line_objects:
                platform_footprints = [
                    footprint
                    for platform_collection in _children_with_role(destruct_collection, "PLATFORM")
                    for footprint in _platform_footprints(platform_collection)
                ]
                if not platform_footprints:
                    issues.append(
                        ValidationIssue(
                            "ERROR",
                            f"'{destruct_collection.name}' has EFLines but no Platform mesh. BOB requires every "
                            "EFLine to sit within a platform's bounds (\"couldn't find platform for efline\") - "
                            "add a Platform collection with a mesh that covers them.",
                        )
                    )
                else:
                    for obj in ef_line_objects:
                        if len(obj.data.vertices) != 2:
                            continue
                        start = obj.data.vertices[0].co
                        end = obj.data.vertices[1].co
                        if not any(_point_in_footprint(start, fp) and _point_in_footprint(end, fp) for fp in platform_footprints):
                            issues.append(
                                ValidationIssue(
                                    "WARNING",
                                    f"'{obj.name}' doesn't look like it's within any Platform's horizontal bounds "
                                    "(checked against each platform mesh's bounding box, not its exact outline). "
                                    "BOB requires EFLines to sit on a platform - double check placement.",
                                    obj.name,
                                )
                            )

            for ef_lines_collection in ef_lines_collections:
                for obj in ef_lines_collection.objects:
                    issues.extend(_validate_two_point_line_object(obj))

            for docking_lines_collection in _children_with_role(destruct_collection, "DOCKING_LINES"):
                for obj in docking_lines_collection.objects:
                    issues.extend(_validate_two_point_line_object(obj))

    for flag_collection in _children_with_role(building_collection, "FLAG"):
        for obj in flag_collection.objects:
            issues.extend(_validate_ignored_scale(obj))

    for region_zone_collection in _children_with_role(building_collection, "REGION_ZONES"):
        for obj in region_zone_collection.objects:
            issues.extend(_validate_region_zone_object(obj))

    return issues


def _validate_line_object(obj: bpy.types.Object) -> list[ValidationIssue]:
    issues = []
    if obj.type != "CURVE":
        issues.append(ValidationIssue("ERROR", f"'{obj.name}' must be a curve object.", obj.name))
        return issues
    if len(obj.data.splines) != 1:
        issues.append(ValidationIssue("ERROR", f"'{obj.name}' must have exactly one spline.", obj.name))
    elif len(obj.data.splines[0].points) < 2 and len(obj.data.splines[0].bezier_points) < 2:
        issues.append(ValidationIssue("ERROR", f"'{obj.name}' needs at least 2 points.", obj.name))
    # Confirmed against real BOB behaviour: an Outline that isn't a closed loop hung BOB during
    # tech processing (a boundary-walking algorithm that presumably never finds its way back to a
    # start point that doesn't exist). extraction/extract.py force-closes it regardless, but this
    # is surfaced as a WARNING (not an error) since the auto-fix already makes it safe to export.
    if obj.tw_line_type == "OUTLINE" and obj.type == "CURVE" and obj.data.splines and not obj.data.splines[0].use_cyclic_u:
        issues.append(
            ValidationIssue(
                "WARNING",
                f"'{obj.name}' is an Outline but isn't a closed (cyclic) curve. Outlines must be closed "
                "loops or BOB can hang while processing the building's tech data - it will be closed "
                "automatically on export, but consider marking the curve Cyclic yourself to see the "
                "real shape while editing.",
                obj.name,
            )
        )
    return issues


def _validate_region_zone_object(obj: bpy.types.Object) -> list[ValidationIssue]:
    issues = _validate_line_object(obj)
    if obj.type == "CURVE" and obj.data.splines and not obj.data.splines[0].use_cyclic_u:
        issues.append(
            ValidationIssue(
                "WARNING",
                f"'{obj.name}' is not a closed (cyclic) curve; region zones must be closed loops and it will be closed automatically on export.",
                obj.name,
            )
        )
    return issues


def _platform_footprints(platform_collection: bpy.types.Collection) -> list[tuple[float, float, float, float]]:
    # A platform's exact outline can be non-convex, and validation has no depsgraph here (see
    # validate_building's signature), so this checks each platform mesh's local-space horizontal
    # (X/Y) bounding box rather than its precise footprint polygon - a cheap, artist-facing
    # approximation of BOB's "couldn't find platform for efline" containment check, not an exact
    # match for it.
    footprints = []
    for obj in platform_collection.objects:
        if obj.type != "MESH" or len(obj.data.vertices) == 0:
            continue
        xs = [v.co.x for v in obj.data.vertices]
        ys = [v.co.y for v in obj.data.vertices]
        footprints.append((min(xs), max(xs), min(ys), max(ys)))
    return footprints


def _point_in_footprint(point, footprint: tuple[float, float, float, float]) -> bool:
    min_x, max_x, min_y, max_y = footprint
    return min_x <= point.x <= max_x and min_y <= point.y <= max_y


def _validate_two_point_line_object(obj: bpy.types.Object) -> list[ValidationIssue]:
    issues = []
    if obj.type != "MESH":
        issues.append(ValidationIssue("ERROR", f"'{obj.name}' must be a mesh object.", obj.name))
        return issues
    vertex_count = len(obj.data.vertices)
    if vertex_count not in (2, 4):
        issues.append(
            ValidationIssue(
                "ERROR",
                f"'{obj.name}' must have either 4 vertices (start, midpoint, end, direction tip - use the "
                f"New Line button) or 2 vertices (a plain start and end point), found {vertex_count}.",
                obj.name,
            )
        )
        return issues
    points = [obj.matrix_world @ vertex.co for vertex in obj.data.vertices]
    start, end = (points[0], points[1]) if vertex_count == 2 else (points[0], points[2])
    if (round(start[0], 6), round(start[1], 6)) == (round(end[0], 6), round(end[1], 6)):
        issues.append(
            ValidationIssue("ERROR", f"'{obj.name}' has no horizontal length - its start and end points overlap.", obj.name)
        )
        return issues
    if vertex_count == 2:
        issues.append(
            ValidationIssue(
                "WARNING",
                f"'{obj.name}' has no direction pointer, so its facing is guessed from the order of its two "
                "points. Select it and click Reset Direction Pointer to add one you can see and aim.",
                obj.name,
            )
        )
        return issues
    base, tip = points[1], points[3]
    if (round(base[0], 6), round(base[1], 6)) == (round(tip[0], 6), round(tip[1], 6)):
        issues.append(
            ValidationIssue(
                "ERROR",
                f"'{obj.name}' has a direction pointer with no horizontal length, so it doesn't point anywhere. "
                "Move its tip, or click Reset Direction Pointer.",
                obj.name,
            )
        )
    # Units stand on a platform and look horizontally, so only the heading is exported. Every one of
    # the 158 markers in the real samples is perfectly level.
    if abs(start[2] - end[2]) > 1e-4:
        issues.append(
            ValidationIssue(
                "WARNING",
                f"'{obj.name}' is not level - its two ends sit at different heights. Only its horizontal "
                "heading affects which way its units face, and real markers are always flat on their platform.",
                obj.name,
            )
        )
    return issues


def validate_skeleton(skeleton_collection: bpy.types.Collection) -> list[ValidationIssue]:
    armatures = [obj for obj in skeleton_collection.all_objects if obj.type == "ARMATURE"]
    if not armatures:
        return [ValidationIssue("ERROR", f"'{skeleton_collection.name}' holds no Armature.", skeleton_collection.name)]
    if len(armatures) > 1:
        names = ", ".join(sorted(obj.name for obj in armatures))
        return [
            ValidationIssue(
                "ERROR",
                f"'{skeleton_collection.name}' holds {len(armatures)} Armatures ({names}) - a skeleton exports as one .CS2, so it can only hold one.",
                skeleton_collection.name,
            )
        ]

    armature_object = armatures[0]
    bones = armature_object.data.bones
    issues = []
    if not bones:
        issues.append(ValidationIssue("ERROR", f"'{armature_object.name}' has no bones.", armature_object.name))
        return issues

    roots = [bone for bone in bones if bone.parent is None]
    if len(roots) > 1:
        names = ", ".join(sorted(bone.name for bone in roots)[:5])
        issues.append(
            ValidationIssue(
                "WARNING",
                f"'{armature_object.name}' has {len(roots)} root bones ({names}) - every real skeleton has exactly one.",
                armature_object.name,
            )
        )

    table_bones = [bone for bone in bones if bone.tw_bone_type != NO_BONE_TYPE]
    if not table_bones:
        issues.append(
            ValidationIssue(
                "ERROR",
                f"No bone in '{armature_object.name}' has a Bone Type, so its .bone_table would be empty and the game would index no bones at all.",
                armature_object.name,
            )
        )

    root_bones = [bone for bone in table_bones if bone.tw_bone_type == ROOT_BONE_TYPE]
    if table_bones and len(root_bones) != 1:
        issues.append(
            ValidationIssue(
                "WARNING",
                f"'{armature_object.name}' lists {len(root_bones)} bones as Root in its bone table - rome_man_game lists exactly one (bn_hips).",
                armature_object.name,
            )
        )
    for bone in root_bones:
        if bone.tw_bone_sort_order != 0:
            issues.append(
                ValidationIssue(
                    "WARNING",
                    f"Root bone '{bone.name}' has sort order {bone.tw_bone_sort_order} - the root bone is the only one with sort order 0 in every real bone table.",
                    bone.name,
                )
            )

    return issues


def _validate_weighted_object(
    obj: bpy.types.Object, armature_object: bpy.types.Object | None
) -> list[ValidationIssue]:
    issues = []
    if armature_object is None:
        issues.append(
            ValidationIssue(
                "ERROR",
                f"'{obj.name}' has no Armature modifier, so it is not skinned to anything.",
                obj.name,
            )
        )
        return issues

    bone_names = {bone.name for bone in armature_object.data.bones}
    group_names = {group.index: group.name for group in obj.vertex_groups}
    unmatched = sorted({name for name in group_names.values() if name not in bone_names})
    if unmatched:
        issues.append(
            ValidationIssue(
                "WARNING",
                f"'{obj.name}' has vertex group(s) matching no bone in '{armature_object.name}' "
                f"({', '.join(unmatched[:5])}) - their weights are dropped on export.",
                obj.name,
            )
        )

    unweighted = 0
    over_weighted = 0
    for vertex in obj.data.vertices:
        influences = sum(
            1
            for element in vertex.groups
            if group_names.get(element.group) in bone_names and element.weight > 0.0
        )
        if influences == 0:
            unweighted += 1
        elif influences > MAX_BONE_INFLUENCES:
            over_weighted += 1

    if unweighted:
        issues.append(
            ValidationIssue(
                "ERROR",
                f"'{obj.name}' has {unweighted} vertex(es) weighted to no bone - every vertex of a "
                "weighted part needs at least one bone weight.",
                obj.name,
            )
        )
    if over_weighted:
        issues.append(
            ValidationIssue(
                "WARNING",
                f"'{obj.name}' has {over_weighted} vertex(es) weighted to more than {MAX_BONE_INFLUENCES} "
                f"bones - the {MAX_BONE_INFLUENCES} strongest are kept and renormalised, as in every real unit part.",
                obj.name,
            )
        )
    return issues


def _has_diffuse_texture(material: bpy.types.Material) -> bool:
    if not material.use_nodes or material.node_tree is None:
        return False
    diffuse_node = material.node_tree.nodes.get("Diffuse")
    return diffuse_node is not None and diffuse_node.image is not None and not is_placeholder_image(diffuse_node.image)


def _validate_unit_shader(obj: bpy.types.Object, weighted: bool) -> list[ValidationIssue]:
    issues = []
    for material in _object_materials(obj):
        shader_type = getattr(material, "tw_shader_type", "default")
        label = SHADER_TYPE_LABELS.get(shader_type, shader_type)
        if weighted and shader_type not in WEIGHTED_SHADER_TYPES:
            issues.append(
                ValidationIssue(
                    "ERROR",
                    f"'{obj.name}' is in a Weighted Model but its material '{material.name}' uses "
                    f"'{label}' - a skinned mesh needs one of the weighted shader types.",
                    obj.name,
                )
            )
        elif not weighted and shader_type in WEIGHTED_SHADER_TYPES:
            issues.append(
                ValidationIssue(
                    "ERROR",
                    f"'{obj.name}' is in a Rigid Model but its material '{material.name}' uses "
                    f"'{label}' - a rigid item carries no bone weights for a weighted shader to read.",
                    obj.name,
                )
            )
        if not _has_diffuse_texture(material):
            issues.append(
                ValidationIssue(
                    "WARNING",
                    f"'{material.name}' on '{obj.name}' has no Diffuse texture. Unlike a building, a unit "
                    "cannot compile on the placeholder - BOB refuses a mesh whose material has no "
                    "t_albedo ('Rigid mesh ... is missing texture t_albedo'), so assign a real .tga "
                    "before compiling.",
                    obj.name,
                )
            )
    return issues


def _validate_attachment_points(
    unit_collection: bpy.types.Collection, weighted: bool, armature_object: bpy.types.Object | None
) -> list[ValidationIssue]:
    issues = []
    points = attachment_point_objects(unit_collection)
    if points and not weighted:
        issues.append(
            ValidationIssue(
                "WARNING",
                f"'{unit_collection.name}' is a Rigid Model asset, so its attachment point object(s) are not "
                "exported - attachment points are authored on the weighted asset an item hangs off, and a "
                ".variantmeshdefinition binds this item to one of those by name.",
                unit_collection.name,
            )
        )
        return issues

    seen: dict[str, str] = {}
    bone_names = {bone.name for bone in armature_object.data.bones} if armature_object is not None else set()
    for obj in points:
        name = obj.tw_attachment_point_name
        if name in seen:
            issues.append(
                ValidationIssue(
                    "ERROR",
                    f"'{obj.name}' and '{seen[name]}' are both named attachment point '{name}'.",
                    obj.name,
                )
            )
        seen[name] = obj.name
        if armature_object is None or obj.parent is not armature_object or obj.parent_type != "BONE":
            issues.append(
                ValidationIssue(
                    "ERROR",
                    f"Attachment point '{obj.name}' is not parented to a bone of the part's skeleton - select it, "
                    "then the Armature, enter Pose Mode, pick the bone and press Ctrl+P > Bone.",
                    obj.name,
                )
            )
        elif obj.parent_bone not in bone_names:
            issues.append(
                ValidationIssue(
                    "ERROR",
                    f"Attachment point '{obj.name}' names bone '{obj.parent_bone}', which the skeleton does not have.",
                    obj.name,
                )
            )
    return issues


def validate_unit(unit_collection: bpy.types.Collection) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = _validate_export_name(unit_collection.name)
    model_collections = unit_model_collections(unit_collection)
    if not model_collections:
        return [
            ValidationIssue("ERROR", f"'{unit_collection.name}' has no models yet.", unit_collection.name)
        ]

    kinds = {model.tw_unit_part_kind for model in model_collections}
    if len(kinds) > 1:
        issues.append(
            ValidationIssue(
                "ERROR",
                f"'{unit_collection.name}' mixes Weighted and Rigid models. One asset compiles to one file, "
                "which carries a single shader family and a single bone table, so every model in it has to "
                "be the same Model Type - split them into two assets.",
                unit_collection.name,
            )
        )
    weighted = unit_kind(unit_collection) == WEIGHTED_KIND
    armature_object = find_unit_armature(unit_collection) if weighted else None

    for model in model_collections:
        objects = mesh_objects(model)
        if not objects:
            issues.append(ValidationIssue("ERROR", f"'{model.name}' has no meshes in it yet.", model.name))
            continue
        lod_indices_seen: dict[str, str] = {}
        for obj in objects:
            issues.extend(_validate_display_object(obj))
            issues.extend(_validate_unit_shader(obj, model.tw_unit_part_kind == WEIGHTED_KIND))
            if model.tw_unit_part_kind == WEIGHTED_KIND:
                issues.extend(_validate_weighted_object(obj, armature_of(obj)))
            existing = lod_indices_seen.get(obj.tw_lod_index)
            if existing is not None:
                issues.append(
                    ValidationIssue(
                        "ERROR",
                        f"'{obj.name}' and '{existing}' both use LOD Level '{LOD_LABELS[obj.tw_lod_index]}' - "
                        "each mesh in a model needs a distinct one.",
                        obj.name,
                    )
                )
            else:
                lod_indices_seen[obj.tw_lod_index] = obj.name
        issues.extend(_validate_lod_chain(lod_indices_seen, model.name))

    if weighted and armature_object is not None:
        listed = [bone for bone in armature_object.data.bones if bone.tw_bone_type != NO_BONE_TYPE]
        if not listed:
            issues.append(
                ValidationIssue(
                    "WARNING",
                    f"No bone in '{armature_object.name}' is listed in its bone table, so the game would index "
                    "no bones at all for this asset - set each game bone's Bone Type in the Skeleton workflow.",
                    armature_object.name,
                )
            )

    issues.extend(_validate_attachment_points(unit_collection, weighted, armature_object))
    return issues


# The seven channel flags the exported rules.bob carries, copied from CA's own animation folders,
# tell BOB to drop translation on everything but the root and floating bones - so a translated core
# bone is authored data that silently will not survive the compile.
CHANNEL_DROPPED_BONE_TYPES = {"BT_CORE", "BT_CORE_TRANS", "BT_FACE", "BT_LEFT_HAND", "BT_RIGHT_HAND", "BT_BEARD"}


def _animated_bone_names(action: bpy.types.Action, kind: str) -> set[str]:
    names = set()
    for path in action_data_paths(action):
        if not path.startswith('pose.bones["') or not path.endswith(kind):
            continue
        names.add(path[len('pose.bones["') : path.index('"]')])
    return names


def action_data_paths(action: bpy.types.Action) -> list[str]:
    # Same layered-action walk extraction.animation does for objects, over an Action that may not be
    # assigned to anything yet - so it goes through every slot rather than one object's own.
    if hasattr(action, "fcurves"):
        return [fcurve.data_path for fcurve in action.fcurves]
    paths = []
    for layer in action.layers:
        for strip in layer.strips:
            if strip.type != "KEYFRAME":
                continue
            for slot in action.slots:
                channelbag = strip.channelbag(slot)
                if channelbag is not None:
                    paths.extend(fcurve.data_path for fcurve in channelbag.fcurves)
    return paths


def validate_animation(
    armature_object: bpy.types.Object | None,
    action: bpy.types.Action | None,
    scene: bpy.types.Scene,
) -> list[ValidationIssue]:
    if armature_object is None or armature_object.type != "ARMATURE":
        return [ValidationIssue("ERROR", "A clip animates a skeleton, and none is selected.")]
    if action is None:
        return [
            ValidationIssue(
                "ERROR",
                f"'{armature_object.name}' has no animation clip assigned - pick one, or make a new one.",
                armature_object.name,
            )
        ]

    # Deliberately not the skeleton's own validation: a clip writes no .bone_table, and BOB resolves
    # the one it needs by name out of raw_data/animations/skeletons/, so the in-scene Armature's bone
    # table settings have no bearing on whether this clip compiles.
    issues: list[ValidationIssue] = []
    bones = armature_object.data.bones
    rotated = _animated_bone_names(action, "rotation_quaternion")
    translated = _animated_bone_names(action, "location")
    animated = rotated | translated
    unmatched = sorted(name for name in animated if name not in bones)
    if unmatched:
        issues.append(
            ValidationIssue(
                "ERROR",
                f"'{action.name}' animates {len(unmatched)} bone(s) '{armature_object.name}' does not have "
                f"({', '.join(unmatched[:5])}) - it belongs to a different skeleton.",
                action.name,
            )
        )
    if not animated:
        issues.append(
            ValidationIssue(
                "ERROR",
                f"'{action.name}' keys no pose bone at all, so it would compile to a clip that never moves.",
                action.name,
            )
        )

    dropped = sorted(
        name
        for name in translated
        if name in bones and bones[name].tw_bone_type in CHANNEL_DROPPED_BONE_TYPES
    )
    if dropped:
        issues.append(
            ValidationIssue(
                "WARNING",
                f"{len(dropped)} bone(s) are moved as well as rotated ({', '.join(dropped[:5])}), but the "
                "rules.bob written beside a clip keeps translation only on Root and Floating bones, as "
                "every CA animation folder does - their movement will not reach the compiled .anim.",
                action.name,
            )
        )

    start, end = action.frame_range
    if round(end) <= round(start):
        issues.append(
            ValidationIssue(
                "ERROR",
                f"'{action.name}' spans a single frame ({round(start)}) - there is nothing to play.",
                action.name,
            )
        )
    return issues


def has_blocking_issues(issues: list[ValidationIssue]) -> bool:
    return any(issue.severity == "ERROR" for issue in issues)
