from binary.cs2_structures import NodeAttributes, NodeAttributeString, NodeAttributeInteger, NodeAttributeFloat

METADATA_VERSION = "Metadata Version 1.9"


def piece_label(piece_index: int) -> str:
    return f"piece{piece_index:02d}"


def destruct_label(destruct_index: int) -> str:
    return f"destruct{destruct_index:02d}"


def lod_label(lod_index: int) -> str:
    return f"lod{lod_index:02d}"


def platform_label(variation_index: int) -> str:
    return f"platform{variation_index:02d}"


def lod_node_name(piece_index: int, destruct_index: int, lod_index: int) -> str:
    return f"{piece_label(piece_index)}_{destruct_label(destruct_index)}_{lod_label(lod_index)}"


def collision_node_name(piece_index: int, destruct_index: int) -> str:
    return f"{piece_label(piece_index)}_{destruct_label(destruct_index)}_collision3d"


def soft_collision_node_name(piece_index: int, destruct_index: int) -> str:
    # No variation suffix - confirmed from two real samples (gondorean_marchingcamp_table,
    # gondorean_marchingcamp_equipment01), each with exactly one soft_collision per destruct01 and
    # none on destruct02, unlike platform/file_reference/outline which always carry a "VV" number.
    return f"{piece_label(piece_index)}_{destruct_label(destruct_index)}_soft_collision"


def platform_node_name(piece_index: int, destruct_index: int, variation_index: int) -> str:
    return f"{piece_label(piece_index)}_{destruct_label(destruct_index)}_{platform_label(variation_index)}"


def arrow_emitter_label(variation_index: int) -> str:
    return f"arrow_emitter{variation_index:02d}"


def arrow_emitter_node_name(piece_index: int, destruct_index: int, variation_index: int) -> str:
    # Confirmed from a real sample (gondor_fort_tower_C_straight): "arrow_emitter" supports
    # variation (not in TWBuildingsTech.ms's supportsVariation exclusion list) and isn't
    # special-cased in the name-building script, so it follows the same generic
    # "piece%_destruct%_%%" pattern as "hard" - no suffix, no prefix reordering.
    return f"{piece_label(piece_index)}_{destruct_label(destruct_index)}_{arrow_emitter_label(variation_index)}"


def height_map_mesh_label(variation_index: int) -> str:
    return "height_map_mesh" if variation_index == 1 else f"height_map_mesh{variation_index:02d}"


def height_map_mesh_node_name(piece_index: int, destruct_index: int, variation_index: int) -> str:
    return f"{piece_label(piece_index)}_{destruct_label(destruct_index)}_{height_map_mesh_label(variation_index)}"


def platform_ground_node_name(piece_index: int, destruct_index: int) -> str:
    # No variation suffix - confirmed from two real samples (gondorean_marchingcamp_table,
    # gondorean_marchingcamp_equipment01), each with at most one platform_ground per destruct level.
    return f"{piece_label(piece_index)}_{destruct_label(destruct_index)}_platform_ground"


def file_reference_node_name(piece_index: int, destruct_index: int, reference_name: str) -> str:
    return f"{piece_label(piece_index)}_{destruct_label(destruct_index)}_file:{reference_name}"


def file_reference_rigid_object_path(reference_name: str) -> str:
    return f"RigidModels\\Buildings\\{reference_name}\\"


# Tech names from TWBuildingsTech.ms, for every "Line Type" this add-on exposes on a Lines
# collection object. GROUND_AD has no variation number (supportsVariation returns false for it in
# the script); every other entry here does.
LINE_TYPE_TECH_NAMES = {
    "OUTLINE": "outline",
    "HARD": "hard",
    # Gate lines need no special-casing: the generic "<tech><VV>" rule already produces the real
    # sample's gate_closed_hard01 / gate_ajar_hard01 verbatim.
    "GATE_CLOSED_HARD": "gate_closed_hard",
    "GATE_AJAR_HARD": "gate_ajar_hard",
    "GROUND_AD": "ground_ad",
    "PIPE_WALL_DOOR": "pipe_wall_door",
    "PIPE_WINDOW": "pipe_window",
    "PIPE_DOOR": "pipe_door",
    "PIPE_JUMP": "pipe_jump",
    "PIPE_JUMP_RAMP": "pipe_jump_ramp",
    "PIPE_JUMP_DISEMBARK": "pipe_jump_disembark",
    "PIPE_RIGGING": "pipe_rigging",
    "PIPE_DESTROYED_CLIMB": "pipe_destroyed_climb",
    "PIPE_DESTROYED_CLIMB_WOOD": "pipe_destroyed_climb_wood",
    "PIPE_CLIMB": "pipe_climb",
    "PIPE_CLIMB_WOOD": "pipe_climb_wood",
    "PIPE_ROPE": "pipe_rope",
    "PIPE_STAIR": "pipe_stair",
    "PIPE_SIEGE_LADDER": "pipe_siegeladder",
    "PIPE_LADDER": "pipe_ladder",
    "PIPE_LADDER_RIGHT": "pipe_ladder_right",
    "PIPE_LADDER_LEFT": "pipe_ladder_left",
}


# BOB keeps at most one plain "hardVV" node per destruct level and silently drops it altogether
# once an "outlineVV_hard" node precedes it, whatever the variation numbers are - reproduced
# through a real compile, see the plan file. Both names are the same RDT_2DCOLLISION_HARD tech, so
# Hard is written under Outline's name, sharing its variation numbering (see
# extraction._extract_line_features).
HARD_COLLISION_LINE_TYPES = ("OUTLINE", "HARD")


def line_feature_class_rigid_info(line_type: str, variation_index: int) -> str:
    tech = LINE_TYPE_TECH_NAMES[line_type]
    if line_type == "GROUND_AD":
        return tech
    if line_type in HARD_COLLISION_LINE_TYPES:
        return f"{LINE_TYPE_TECH_NAMES['OUTLINE']}{variation_index:02d}_hard"
    return f"{tech}{variation_index:02d}"


def line_feature_node_name(piece_index: int, destruct_index: int, line_type: str, variation_index: int) -> str:
    tech = LINE_TYPE_TECH_NAMES[line_type]
    if line_type == "GROUND_AD":
        return f"{piece_label(piece_index)}_{destruct_label(destruct_index)}_{tech}"
    return f"{piece_label(piece_index)}_{destruct_label(destruct_index)}_{line_feature_class_rigid_info(line_type, variation_index)}"


def region_zone_node_name(variation_index: int) -> str:
    # Region zones are building-global, not piece/destruct-prefixed - confirmed from a real
    # sample (region_zone01, region_zone02, ... with no piece/destruct in the node name).
    return f"region_zone{variation_index:02d}"


def ef_line_node_name(piece_index: int, destruct_index: int, variation_index: int) -> str:
    # Note the piece/destruct numbers come after the "EFline" prefix here, unlike every other
    # node type where the tech name comes last - confirmed from TWBuildingsTech.ms's own format().
    return f"EFline_{piece_label(piece_index)}_{destruct_label(destruct_index)}_line{variation_index:02d}"


def docking_line_node_name(piece_index: int, destruct_index: int, variation_index: int) -> str:
    return f"DockingLine_{piece_label(piece_index)}_{destruct_label(destruct_index)}_line{variation_index:02d}"


def _common_string_attributes(
    piece_index: int,
    destruct_index: int,
    building_name: str,
    class_type: str,
    graphics_option: str,
    class_rigid_info: str,
    rigid_object: str = "",
) -> list[NodeAttributeString]:
    return [
        NodeAttributeString("metadata_versionNO", METADATA_VERSION),
        NodeAttributeString("rigid_TYPE", "STAND_RIGID"),
        NodeAttributeString("class_TYPE", class_type),
        NodeAttributeString("piece_INFO", piece_label(piece_index)),
        NodeAttributeString("destruct_ID", destruct_label(destruct_index)),
        NodeAttributeString("graphics_OPTION", graphics_option),
        NodeAttributeString("class_rigidINFO", class_rigid_info),
        NodeAttributeString("assigned_OBJECT", building_name),
        NodeAttributeString("rigid_OBJECT", rigid_object),
    ]


def _common_integer_attributes(info_num: int = 1) -> list[NodeAttributeInteger]:
    return [
        NodeAttributeInteger("metadata_rigidTYPE", 1),
        NodeAttributeInteger("metadata_classTYPE", 1),
        NodeAttributeInteger("metadata_pieceINFO", 1),
        NodeAttributeInteger("metadata_idNUM", 1),
        NodeAttributeInteger("metadata_idNUM2", 1),
        NodeAttributeInteger("metadata_destructID", 1),
        NodeAttributeInteger("metadata_desNUM", 1),
        NodeAttributeInteger("metadata_graphicsOPTION", 1),
        NodeAttributeInteger("metadata_INFO", 1),
        NodeAttributeInteger("metadata_infoNUM", info_num),
        NodeAttributeInteger("metadata_assignedOBJECT", 1),
    ]


def lod_attributes(piece_index: int, destruct_index: int, lod_index: int, building_name: str) -> NodeAttributes:
    strings = _common_string_attributes(
        piece_index, destruct_index, building_name, class_type="DISPLAY", graphics_option="GRAPHICS_HIGH", class_rigid_info=lod_label(lod_index)
    )
    return NodeAttributes(strings=strings, integers=_common_integer_attributes(info_num=lod_index))


def collision_attributes(piece_index: int, destruct_index: int, building_name: str) -> NodeAttributes:
    strings = _common_string_attributes(
        piece_index, destruct_index, building_name, class_type="TECH", graphics_option="NOT_GRAPHICS", class_rigid_info="collision3d"
    )
    return NodeAttributes(strings=strings, integers=_common_integer_attributes())


def soft_collision_attributes(piece_index: int, destruct_index: int, building_name: str) -> NodeAttributes:
    strings = _common_string_attributes(
        piece_index, destruct_index, building_name, class_type="TECH", graphics_option="NOT_GRAPHICS", class_rigid_info="soft_collision"
    )
    return NodeAttributes(strings=strings, integers=_common_integer_attributes())


# Confirmed from a real sample (Input/examples/raw_data/gondor_fort_gateway_e/
# gondor_fort_gateway_oil_e.CS2): collision3d_boiling_oil carries no variation suffix - same
# un-numbered pattern as plain collision3d/soft_collision - while the display mesh is LOD-numbered
# exactly like a gate's, "boiling_oil_lodVV" rather than the flat "boiling_oilVV" TWBuildingsTech.ms's
# generic supportsVariation branch would otherwise produce; the real sample settles it.
def boiling_oil_collision_node_name(piece_index: int, destruct_index: int) -> str:
    return f"{piece_label(piece_index)}_{destruct_label(destruct_index)}_collision3d_boiling_oil"


def boiling_oil_collision_attributes(piece_index: int, destruct_index: int, building_name: str) -> NodeAttributes:
    strings = _common_string_attributes(
        piece_index, destruct_index, building_name, class_type="TECH", graphics_option="NOT_GRAPHICS", class_rigid_info="collision3d_boiling_oil"
    )
    return NodeAttributes(strings=strings, integers=_common_integer_attributes())


def boiling_oil_display_node_name(piece_index: int, destruct_index: int, lod_index: int) -> str:
    return f"{piece_label(piece_index)}_{destruct_label(destruct_index)}_boiling_oil_{lod_label(lod_index)}"


def boiling_oil_display_attributes(piece_index: int, destruct_index: int, lod_index: int, building_name: str) -> NodeAttributes:
    strings = _common_string_attributes(
        piece_index,
        destruct_index,
        building_name,
        class_type="DISPLAY",
        graphics_option="GRAPHICS_HIGH",
        class_rigid_info=f"boiling_oil_{lod_label(lod_index)}",
    )
    return NodeAttributes(strings=strings, integers=_common_integer_attributes(info_num=lod_index))


def platform_attributes(piece_index: int, destruct_index: int, variation_index: int, building_name: str) -> NodeAttributes:
    strings = _common_string_attributes(
        piece_index,
        destruct_index,
        building_name,
        class_type="TECH",
        graphics_option="NOT_GRAPHICS",
        class_rigid_info=platform_label(variation_index),
    )
    return NodeAttributes(strings=strings, integers=_common_integer_attributes())


def arrow_emitter_attributes(piece_index: int, destruct_index: int, variation_index: int, building_name: str) -> NodeAttributes:
    strings = _common_string_attributes(
        piece_index,
        destruct_index,
        building_name,
        class_type="TECH",
        graphics_option="NOT_GRAPHICS",
        class_rigid_info=arrow_emitter_label(variation_index),
    )
    return NodeAttributes(strings=strings, integers=_common_integer_attributes())


def height_map_mesh_attributes(piece_index: int, destruct_index: int, variation_index: int, building_name: str) -> NodeAttributes:
    strings = _common_string_attributes(
        piece_index,
        destruct_index,
        building_name,
        class_type="IGNORE",
        graphics_option="NOT_GRAPHICS",
        class_rigid_info=f"height_map_mesh{variation_index:02d}",
    )
    return NodeAttributes(strings=strings, integers=_common_integer_attributes())


def platform_ground_attributes(piece_index: int, destruct_index: int, building_name: str) -> NodeAttributes:
    strings = _common_string_attributes(
        piece_index, destruct_index, building_name, class_type="TECH", graphics_option="NOT_GRAPHICS", class_rigid_info="platform_ground"
    )
    return NodeAttributes(strings=strings, integers=_common_integer_attributes())


def file_reference_attributes(piece_index: int, destruct_index: int, reference_name: str, building_name: str) -> NodeAttributes:
    strings = _common_string_attributes(
        piece_index,
        destruct_index,
        building_name,
        class_type="TECH",
        graphics_option="NOT_GRAPHICS",
        class_rigid_info="key",
        rigid_object=file_reference_rigid_object_path(reference_name),
    )
    return NodeAttributes(strings=strings, integers=_common_integer_attributes())


def line_feature_attributes(piece_index: int, destruct_index: int, line_type: str, variation_index: int, building_name: str) -> NodeAttributes:
    strings = _common_string_attributes(
        piece_index,
        destruct_index,
        building_name,
        class_type="TECH",
        graphics_option="NOT_GRAPHICS",
        class_rigid_info=line_feature_class_rigid_info(line_type, variation_index),
    )
    return NodeAttributes(strings=strings, integers=_common_integer_attributes())


def region_zone_attributes(variation_index: int, building_name: str) -> NodeAttributes:
    # Region zones aren't really tied to a piece/destruct, but every real sample still carries
    # the default "piece01"/"destruct01" values in these fields (they come from UI text boxes in
    # TWBuildingsTech.ms that default to "01" and are never tied to the actual zone).
    strings = _common_string_attributes(
        1, 1, building_name, class_type="TECH", graphics_option="NOT_GRAPHICS", class_rigid_info=f"region_zone{variation_index:02d}"
    )
    return NodeAttributes(strings=strings, integers=_common_integer_attributes())


GATE_COLLISION_LABELS = {"GATE_CLOSED": "collision3d_gate_closed", "GATE_AJAR": "collision3d_gate_ajar"}
GATE_DISPLAY_LABELS = {"GATE_CLOSED_DISPLAY": "gate_closed", "GATE_OPEN_DISPLAY": "gate_open"}


def gate_collision_node_name(piece_index: int, destruct_index: int, collision_type: str) -> str:
    return f"{piece_label(piece_index)}_{destruct_label(destruct_index)}_{GATE_COLLISION_LABELS[collision_type]}"


def gate_collision_attributes(piece_index: int, destruct_index: int, collision_type: str, building_name: str) -> NodeAttributes:
    strings = _common_string_attributes(
        piece_index,
        destruct_index,
        building_name,
        class_type="TECH",
        graphics_option="NOT_GRAPHICS",
        class_rigid_info=GATE_COLLISION_LABELS[collision_type],
    )
    return NodeAttributes(strings=strings, integers=_common_integer_attributes())


def gate_display_node_name(piece_index: int, destruct_index: int, gate_role: str, lod_index: int) -> str:
    return (
        f"{piece_label(piece_index)}_{destruct_label(destruct_index)}_"
        f"{GATE_DISPLAY_LABELS[gate_role]}_{lod_label(lod_index)}"
    )


def gate_display_attributes(piece_index: int, destruct_index: int, gate_role: str, lod_index: int, building_name: str) -> NodeAttributes:
    strings = _common_string_attributes(
        piece_index,
        destruct_index,
        building_name,
        class_type="DISPLAY",
        graphics_option="GRAPHICS_HIGH",
        class_rigid_info=f"{GATE_DISPLAY_LABELS[gate_role]}_{lod_label(lod_index)}",
    )
    return NodeAttributes(strings=strings, integers=_common_integer_attributes(info_num=lod_index))


DESTRUCTION_ANIM_CLASS_RIGID_INFO = "anim"

# class_rigidINFO vocabulary confirmed from gondor_fort_gateway_e.CS2's real gate_opening_anim/
# gate_closing_anim/gate_closed_destruct_anim/gate_open_destruct_anim nodes.
GATE_ANIM_CLASS_RIGID_INFO = {
    "GATE_OPENING": "gate_opening_anim",
    "GATE_CLOSING": "gate_closing_anim",
    "GATE_CLOSED_DESTRUCT": "gate_closed_destruct_anim",
    "GATE_OPEN_DESTRUCT": "gate_open_destruct_anim",
}


def destruction_anim_node_name(piece_index: int, destruct_index: int) -> str:
    # Confirmed from real ground truth: every destruction debris chunk for the same piece/destruct
    # level shares this exact literal name - no "VV" numbering, unlike every other node type in this
    # module. The "building_" prefix is real and unique to this and the gate anim kinds below; no
    # other node type in this codebase carries it.
    return f"building_{piece_label(piece_index)}_{destruct_label(destruct_index)}_{DESTRUCTION_ANIM_CLASS_RIGID_INFO}"


def gate_anim_node_name(piece_index: int, destruct_index: int, gate_anim_kind: str) -> str:
    return f"building_{piece_label(piece_index)}_{destruct_label(destruct_index)}_{GATE_ANIM_CLASS_RIGID_INFO[gate_anim_kind]}"


def destruction_anim_attributes(piece_index: int, destruct_index: int, building_name: str) -> NodeAttributes:
    strings = _common_string_attributes(
        piece_index,
        destruct_index,
        building_name,
        class_type="DISPLAY",
        graphics_option="GRAPHICS_HIGH",
        class_rigid_info=DESTRUCTION_ANIM_CLASS_RIGID_INFO,
    )
    return NodeAttributes(strings=strings, integers=_common_integer_attributes())


def gate_anim_attributes(piece_index: int, destruct_index: int, gate_anim_kind: str, building_name: str) -> NodeAttributes:
    strings = _common_string_attributes(
        piece_index,
        destruct_index,
        building_name,
        class_type="DISPLAY",
        graphics_option="GRAPHICS_HIGH",
        class_rigid_info=GATE_ANIM_CLASS_RIGID_INFO[gate_anim_kind],
    )
    return NodeAttributes(strings=strings, integers=_common_integer_attributes())


def flag_node_name() -> str:
    return "flag"


def flag_attributes(building_name: str) -> NodeAttributes:
    # Like region zones, the flag is building-global but still carries the default
    # "piece01"/"destruct01" values - confirmed against both real samples that have one
    # (gondor_fort_gateway_e, gondor_fort_tower_C_straight), which agree field for field.
    strings = _common_string_attributes(
        1, 1, building_name, class_type="TECH", graphics_option="NOT_GRAPHICS", class_rigid_info="flag"
    )
    return NodeAttributes(strings=strings, integers=_common_integer_attributes())


def _to_authoring_space(vector) -> tuple[float, float, float]:
    # The UDP block is 3ds Max's own text buffer, so BOB reads the vectors in it as Max Z-up
    # coordinates and applies its own axis swap - unlike geometry, which the exporter has already
    # converted. Confirmed against gondor_fort_tower_C_straight: EFLine_Info x:"10.252" y:"2.15"
    # z:"15.0" comes out of BOB's compiled tech as engine (10.252, 15.0, 2.15). The swap is its own
    # inverse, so this is extraction._to_engine_space run backwards.
    x, y, z = vector
    return (x, z, y)


def _format_float_attribute(value: float) -> str:
    # MaxScript's `format "%"` prints 6 significant digits and always keeps a decimal point. Python's
    # default float repr can emit exponent notation instead, which BOB's line-by-line property parser
    # has no reason to accept ("Syntax error in EFline property (").
    if value == 0.0:
        value = 0.0
    text = f"{value:.6g}"
    if "e" in text:
        text = f"{value:.6f}".rstrip("0")
    if "." not in text:
        text += ".0"
    elif text.endswith("."):
        text += "0"
    return text


def _format_user_defined_properties(lines: list[str], terminate_last: bool) -> str:
    # EFLine blocks terminate their last property line, DockingLine blocks don't - 154 of 154 vs
    # 0 of 4 across the two real samples that carry them.
    text = "\r\n".join(lines)
    return f"{text}\r\n" if terminate_last else text


def _format_vec3_attribute(vector) -> str:
    # Matches TWBuildingsTech.ms's `format "x:\"%\" y:\"%\" z:\"%\"" x y z` exactly, including the
    # embedded literal quote characters around each component.
    x, y, z = _to_authoring_space(vector)
    return f'x:"{_format_float_attribute(x)}" y:"{_format_float_attribute(y)}" z:"{_format_float_attribute(z)}"'


def ef_line_attributes(piece_index: int, destruct_index: int, variation_index: int, building_name: str) -> NodeAttributes:
    strings = _common_string_attributes(
        piece_index,
        destruct_index,
        building_name,
        class_type="TECH",
        graphics_option="NOT_GRAPHICS",
        class_rigid_info=f"EFLine{variation_index:02d}",
    )
    return NodeAttributes(strings=strings, integers=_common_integer_attributes())


def docking_line_attributes(piece_index: int, destruct_index: int, variation_index: int, building_name: str) -> NodeAttributes:
    strings = _common_string_attributes(
        piece_index,
        destruct_index,
        building_name,
        class_type="TECH",
        graphics_option="NOT_GRAPHICS",
        class_rigid_info=f"DockingLine{variation_index:02d}",
    )
    return NodeAttributes(strings=strings, integers=_common_integer_attributes())


def ef_line_user_defined_properties(piece_index: int, destruct_index: int, variation_index: int, action: str, start, end, direction) -> str:
    # CONFIRMED BY A REAL BOB CRASH: putting these as NodeAttributeString entries (the previous
    # approach) makes BOB read the action value as the literal sentinel text "INVALID VALUE" and
    # crash with "action type INVALID VALUE not recognised." BOB's own error strings
    # ("Syntax error in EFline property (", "Unknown item in EFline properties (") only make sense
    # for line-by-line text parsing, which is exactly what 3ds Max's User Defined Properties (UDP)
    # buffer is - a separate free-text field per node (setUserProp/getUserProp in MaxScript),
    # distinct from the strongly-typed Custom Attributes block used for class_TYPE/piece_INFO/etc.
    # This is that UDP block's text, one "Key = Value" line per property (see NodeCommon's
    # user_defined_properties field). The key names and the `x:"%" y:"%" z:"%"` value format are
    # both confirmed against literal strings found in BOB's own binary (bob.dll's string table).
    node_name = ef_line_node_name(piece_index, destruct_index, variation_index)
    lines = [
        f"EFLine_Name = {node_name}",
        f"EFLine_Action = {action}",
        f"EFLine_Info = {_format_vec3_attribute(start)}",
        f"EFLine_Info_End = {_format_vec3_attribute(end)}",
        f"EFLine_Direction = {_format_vec3_attribute(direction)}",
    ]
    return _format_user_defined_properties(lines, terminate_last=True)


def region_zone_user_defined_properties(corner_points) -> str:
    # Same UDP-buffer mechanism as ef_line_user_defined_properties, and needed for the same reason:
    # BOB reads a region zone's corners from this text (its "Syntax error in Region properties ("
    # / "Region_" strings), not from the LINE geometry, so a zone exported without it compiles to no
    # region at all. TWBuildingsTech.ms writes one "Region_pos<i>" per authored knot, so these are
    # the curve's own corners, not the tessellated line vertices. The doubled space before "=" is
    # what both real samples carry (gondor_fort_gateway_e, gondor_fort_tower_C_straight), unlike the
    # single space in every EFLine/DockingLine block.
    lines = [f"Region_pos{index}  = {_format_vec3_attribute(point)}" for index, point in enumerate(corner_points, start=1)]
    return _format_user_defined_properties(lines, terminate_last=True)


def docking_line_user_defined_properties(start, end, direction) -> str:
    # See ef_line_user_defined_properties - same UDP-buffer mechanism. TWBuildingsTech.ms's
    # dockingline_name branch never sets a "DockingLine_Name" UserProp (unlike EFLine), so it's
    # omitted here too - BOB's DOCKING_LINE::parse falls back to the node's own NodeName for that.
    lines = [
        f"DockingLine_Info = {_format_vec3_attribute(start)}",
        f"DockingLine_Info_End = {_format_vec3_attribute(end)}",
        f"DockingLine_Direction = {_format_vec3_attribute(direction)}",
    ]
    return _format_user_defined_properties(lines, terminate_last=False)


# rome_man_game.cs2 gives every one of its 228 skeleton nodes a MaxHandle and nothing else, plus a
# LimbLength of 1.0 on the 172 that are Max Bone objects rather than point helpers. None of the
# metadata_* attributes every building node carries appear on a skeleton node at all.
SKELETON_LIMB_LENGTH = 1.0


def skeleton_bone_attributes(max_handle: int, is_limb: bool) -> NodeAttributes:
    return NodeAttributes(
        integers=[NodeAttributeInteger("MaxHandle", max_handle)],
        floats=[NodeAttributeFloat("LimbLength", SKELETON_LIMB_LENGTH)] if is_limb else [],
    )


# CA's own authored unit parts (nordic_leather_armour, generic_spangenhelm_elite,
# round_curved_shield, ridge_crest_tall) name every mesh node "<mesh>_lod<N>" with N from 1 and no
# zero padding, and give those nodes no attributes at all - none of the metadata_* strings a
# building node carries.
def unit_lod_node_name(mesh_name: str, lod_index: int) -> str:
    return f"{mesh_name}_lod{lod_index}"


# generic_spangenhelm_elite.cs2 authors AP_crest_centre/_left/_right and the compiled helmet carries
# MESH_ATTACH_POINTs named crest_centre/crest_left/crest_right - BOB strips this prefix.
ATTACHMENT_POINT_PREFIX = "AP_"


def attachment_point_node_name(point_name: str) -> str:
    return f"{ATTACHMENT_POINT_PREFIX}{point_name}"


def attachment_point_name_of(node_name: str) -> str:
    return node_name[len(ATTACHMENT_POINT_PREFIX):] if node_name.startswith(ATTACHMENT_POINT_PREFIX) else node_name
