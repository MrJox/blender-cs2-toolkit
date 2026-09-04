import re
import winreg
from pathlib import Path

import bpy

from materials.shader_types import (
    SHADER_TYPES,
    DEFAULT_SHADER_TYPE,
    ALPHA_MODE_ITEMS,
    DEFAULT_ALPHA_MODE,
)

# The single source of truth for what each collection role means - reused by the "Add..." menu
# tooltips (ui/operators.py) and the Collection Properties panel (ui/panels.py) so the explanation
# only ever lives in one place. Real hover tooltips on Outliner collection icons aren't possible
# via the public API (the Outliner tree is fixed C-side UI with no per-item tooltip hook for plain
# ID datablocks - only Asset Browser entries get one, via asset_data.description) - the Collection
# Properties panel is the closest equivalent: click any collection, see what it's for.
TW_ROLE_ITEMS = [
    ("NONE", "None", ""),
    ("BUILDING", "Building", "The top-level container for one Total War battlefield building - everything else nests under this."),
    ("PIECE", "Piece", "One structural piece of the building - a building can have several, e.g. a gatehouse plus flanking towers."),
    (
        "DESTRUCT",
        "Destruct Level",
        "One destruction state of a piece (e.g. undamaged, damaged, destroyed) - each level has its own Display/Collision/etc.",
    ),
    (
        "DISPLAY",
        "Display",
        "The visible LOD meshes for this destruct level - one mesh per level of detail, each needs a UV map and material.",
    ),
    (
        "COLLISION",
        "Collision",
        "The collision volumes for this destruct level. At least one Collision 3D, gate or boiling-oil volume is required, or the build will fail.",
    ),
    (
        "PLATFORM",
        "Platform",
        "A walkable floor surface for this destruct level. Battlefield pathfinding uses it to know where units can stand on the building.",
    ),
    (
        "FILE_REFERENCE",
        "Referenced Props",
        "A placeholder that tells the game to insert an existing external prop (e.g. a torch or barrel) at this spot, instead of exporting new geometry for it. Position and rotation come entirely from the object's own transform, so an Empty is enough - a mesh here is only preview geometry for you, and the game never sees it.",
    ),
    (
        "LINES",
        "Lines",
        "Curves that tell the battlefield AI how to move around and through the building: footprint boundaries units cannot cross, ground area dividers, and routes over ladders, ropes, stairs and jump points. Each curve says which it is through its Line Type.",
    ),
    (
        "EF_LINES",
        "EFLines",
        "Entity Formation lines: short lines that tell the game to form units up here - on a wall, at a window, in a firing position - each with an Action saying what they are doing there and a pointer showing which way they face. Must sit within a Platform's bounds.",
    ),
    (
        "DOCKING_LINES",
        "Docking Lines",
        "Where siege engines dock against this building - siege towers dropping their ramp, siege ladders, battering rams. Each line carries a pointer showing which way it faces. Unlike EFLines, these don't need to sit on a Platform.",
    ),
    (
        "ARROW_EMITTERS",
        "Arrow Emitters",
        "Firing positions a fort tower shoots its arrows from. Use the 'New Arrow Emitter' button to create the correct marker shape, then move/rotate the object to position and aim it - direction comes entirely from the object's own transform, not its mesh data.",
    ),
    (
        "GATE_CLOSED_DISPLAY",
        "Gate Closed",
        "The visible gate meshes in their shut position, one per LOD. Lives inside a Display collection. The gate's collision goes in the Collision collection and its pathfinding lines in the Lines collection, each with its own Gate type; the leaves that swing go in a Gate Animation collection.",
    ),
    (
        "GATE_OPEN_DISPLAY",
        "Gate Open",
        "The visible gate meshes in their fully open position, one per LOD - model them swung open where they end up. Lives inside a Display collection.",
    ),
    (
        "GATE_ANIMATION",
        "Gate Animation",
        "The gate's opening/closing/destruct animation meshes - the actual moving door leaf geometry, separate from the static Gate Closed/Gate Open display meshes. Animate each object's transform with Blender's own keyframes (I to insert a key); set each object's Gate Animation Kind to say which of the four animations it belongs to. Lives inside a Display collection.",
    ),
    (
        "BOILING_OIL_DISPLAY",
        "Boiling Oil",
        "The visible meshes of the boiling-oil mechanism defenders pour from a gatehouse, one per LOD. Lives inside a Display collection; its collision volume goes in the Collision collection, set to Collision 3D Boiling Oil.",
    ),
    (
        "DESTRUCTION_ANIM",
        "Destruction Animation",
        "Debris chunks that fly/fall away when this destruct level is destroyed. Each object needs a UV map and material like a Display mesh, plus Blender's own keyframe animation (I to insert a key) on its transform describing the debris's trajectory - a chunk with no keyframes just stays put.",
    ),
    (
        "HEIGHT_MAP_MESH",
        "Height Map Mesh",
        "A 3D model placed as walkable terrain on a battle map in TEd. Note that it stays in the .CS2 - nothing compiles it into a game-ready file - so sharing one means sharing the .CS2 and its raw_data table entries too, or TEd will not find the terrain it refers to.",
    ),
    (
        "REGION_ZONES",
        "Region Zones",
        "Closed areas belonging to the whole building rather than to one piece or destruct level, drawn as cyclic curves. Real buildings carry them and they import and export faithfully, but exactly what the game does with them is not established - treat them as something to copy from a real building rather than to invent.",
    ),
    (
        "FLAG",
        "Flag",
        "Where the building's icon sits in the battle UI - this marker is that icon's position in 3D. At most one per building. Use the 'New Flag' button to create the correct marker shape, then move the object to place it - position comes entirely from the object's own transform, not its mesh data.",
    ),
    (
        "UNIT",
        "Unit Asset",
        "One exported unit asset - becomes a single .CS2 and a single .rigid_model_v2, named after this collection. Holds the models it is built from; the skeleton they are weighted to is a collection of its own, since several assets share it.",
    ),
    # Retired in favour of the two-level Asset > Model structure. Kept in this list only so the
    # roles after it keep their stored values - tw_role is a static EnumProperty, so removing an
    # entry would renumber SKELETON and silently change what existing scenes say. Nothing creates
    # or reads it, and tw_role is never drawn as an editable dropdown, so it is invisible in use.
    ("UNIT_PART", "Unit Part (retired)", "No longer used - a unit asset holds its models directly."),
    (
        "UNIT_MESH",
        "Unit Model",
        "One named model inside a unit asset, holding that model's LOD objects. Its Model Type says whether it is skinned to a skeleton (Weighted Model) or a rigid item that hangs off one bone (Rigid Model). An asset can hold several - a real head asset carries separate body and eyes/tongue models, each with its own LODs and material.",
    ),
    (
        "SKELETON",
        "Skeleton",
        "The skeleton unit models are weight-painted against - holds one Blender Armature. Several assets can share one, so it sits at the top of the scene rather than inside any single asset. Exports as its own .CS2 plus a .bone_table listing its bones.",
    ),
    (
        "VEGETATION",
        "Vegetation Model",
        "One tree, shrub or stone - becomes a single .rigid_model_v2 plus its _tech.cs2.parsed sidecar. Holds one collection per LOD, plus whatever BOB generated for it.",
    ),
    (
        "VEGETATION_LOD",
        "Vegetation LOD",
        "One level of detail of a vegetation model, holding a bark mesh, a leaf mesh, or both. Which LOD it is decides the camera distance it appears at: LOD 1 is 100m, LOD 2 200m, LOD 3 400m.",
    ),
    (
        "VEGETATION_BILLBOARD",
        "Generated Billboard",
        "The far-distance camera-aligned quad BOB generates from the model, with the atlas it also generates. Imported for reference only - it is never authored, so editing it changes nothing.",
    ),
    (
        "VEGETATION_FIRE",
        "Generated Fire Hull",
        "The burn hull BOB derives from the lowest LOD, and the fire VFX emitters it distributes over that hull. Imported for reference only - both are generated, not authored.",
    ),
]

TW_ROLE_DESCRIPTIONS = {identifier: description for identifier, _label, description in TW_ROLE_ITEMS}
TW_ROLE_LABELS = {identifier: label for identifier, label, _description in TW_ROLE_ITEMS}

ASSET_TYPE_ITEMS = [
    ("DISPLAY_BUILDING", "Display Building", "An ordinary battlefield building - a house, wall, tower or gatehouse"),
]

# Which sets of panels the sidebar shows. SHIP is reserved for a later workflow and is deliberately
# absent rather than present-but-disabled: an EnumProperty cannot grey an item out, and an item that
# errors when picked is worse than one that is not offered.
TW_WORKFLOW_ITEMS = [
    (
        "BUILDING",
        "Building",
        "Author battlefield buildings - their pieces, destruct levels, collision, platforms and markers",
    ),
    (
        "UNIT",
        "Unit",
        "Author the models a soldier is assembled from - skinned body and armour, and the rigid weapons, "
        "shields and crests that hang off his bones",
    ),
    (
        "SKELETON",
        "Skeleton",
        "Build a skeleton as a Blender Armature and say which of its bones the game indexes. Exports as a "
        ".CS2 plus its .bone_table",
    ),
    ("SKELETAL_ANIMATION", "Skeletal Animation", "Author, play back and export animation clips for a skeleton"),
    (
        "VEGETATION",
        "Vegetation",
        "Read battlefield trees, shrubs and stones back from their compiled .rigid_model_v2 and "
        "_tech.cs2.parsed. Import only - authoring one is not implemented",
    ),
]

# Which of the two export shapes a unit part takes. Deliberately an explicit choice rather than
# inferred from whether the meshes happen to have vertex groups: the two drive entirely different
# export paths, and an empty weight paint would silently pick the wrong one.
UNIT_PART_KIND_ITEMS = [
    (
        "WEIGHTED",
        "Weighted Model",
        "Skinned to a skeleton, so it bends with the soldier - body, armour, cloth. Every vertex needs bone weights, and at most two bones may pull on any one of them. Needs a skeleton in the scene",
    ),
    (
        "RIGID_ATTACHMENT",
        "Rigid Model",
        "A solid item that rides on a single bone without bending - weapon, shield, helmet crest. Carries no bone weights, and needs no skeleton in the scene",
    ),
]

# 5 levels, matching every real sample building's Display collection (lod01..lod05). Explicit
# per-object choice rather than inferring the index from collection order (order isn't something
# an artist consciously sets, and silently renumbers every LOD after it if two meshes get
# reordered) - same reasoning as tw_line_type.
LOD_ITEMS = [
    ("LOD01", "LOD 1", "Highest level of detail - shown at the closest camera distance"),
    ("LOD02", "LOD 2", "Second level of detail - takes over from LOD 1 as the camera pulls back"),
    ("LOD03", "LOD 3", "Middle level of detail"),
    ("LOD04", "LOD 4", "Second-lowest level of detail"),
    ("LOD05", "LOD 5", "Lowest level of detail - shown at the furthest camera distance"),
]

UNIT_PART_KIND_LABELS = {identifier: label for identifier, label, _description in UNIT_PART_KIND_ITEMS}

LOD_LABELS = {identifier: label for identifier, label, _description in LOD_ITEMS}

LOD_INDEX_BY_IDENTIFIER = {identifier: index for index, (identifier, _label, _description) in enumerate(LOD_ITEMS, start=1)}
LOD_IDENTIFIER_BY_INDEX = {index: identifier for identifier, index in LOD_INDEX_BY_IDENTIFIER.items()}

PLATFORM_TYPE_ITEMS = [
    ("PLATFORM", "Platform", "A walkable floor surface, usable while this destruct level is active"),
    (
        "PLATFORM_GROUND",
        "Platform Ground",
        "The irregular ground or rubble units walk over, typically the surface a destroyed piece leaves "
        "behind. Only one per destruct level, unlike the ordinary numbered Platform meshes",
    ),
]

COLLISION_TYPE_ITEMS = [
    (
        "COLLISION",
        "Collision 3D",
        "The solid volume the camera and projectiles collide with. Units are stopped by the Outline "
        "and Hard lines instead, not by this. Every destruct level needs one of these, a gate volume "
        "or a boiling-oil volume - a Soft Collision alone does not count",
    ),
    (
        "GATE_CLOSED",
        "Collision 3D Gate Closed",
        "The solid volume blocking the opening while the gate is shut. A single box across the whole "
        "opening is enough",
    ),
    (
        "GATE_AJAR",
        "Collision 3D Gate Ajar",
        "The solid volume of the gate once it has swung open, so units collide with the open leaves "
        "instead of the doorway",
    ),
    (
        "BOILING_OIL",
        "Collision 3D Boiling Oil",
        "The solid volume of the boiling-oil pouring mechanism. At most one per destruct level",
    ),
    (
        "SOFT_COLLISION",
        "Soft Collision",
        "Light clutter units walk straight through and knock down as they go - fences, stalls, market "
        "stands. It does not block anyone. Model it as a simple box: it becomes an upright cylinder as "
        "wide and as tall as that box",
    ),
]

# Tech names from TWBuildingsTech.ms's "Logic type" dropdown, for the curve-based LINE-node
# features this add-on exposes on a Lines collection object. Region zones are handled separately
# (a building-global "Region Zones" collection) since they aren't piece/destruct-scoped.
#
# CORRECTION: Outline's description previously said "ambient occlusion" - that was an unconfirmed
# guess and it was wrong. Input/file_format_specs/cs2_parsed_spec.md documents the compiled
# DestructLevel layout explicitly grouping "Pathfinding Outlines, Pipes & No-Go Zones" together,
# and its `line` (LineNode) struct's `line_type` enum lists "hard obstacle, ground ad, pipe, etc."
# as the possible values - i.e. Outline/Ground AD/Pipe all share the same LINE node shape (already
# implemented correctly) and are ALL pathfinding constructs, not rendering/decal ones. "Outline" ==
# the "hard obstacle" line_type - a closed boundary the AI can't path through, which is exactly why
# the real sample's outline nodes are closed loops (see HANDOVER doc) and why the tech name carries
# a literal "_hard" suffix (piece01_destruct01_outline01_hard). Ground AD's exact behaviour is still
# unconfirmed beyond "it's a pathfinding line_type alongside outline/pipe, not a visual decal".
LINE_TYPE_ITEMS = [
    (
        "OUTLINE",
        "Outline Collision",
        "A closed loop around the building's footprint that units cannot walk through. A destruct level "
        "can carry several, which is how the footprint is left open where a gate or other passable part sits",
    ),
    (
        "HARD",
        "Hard Collision",
        "The same blocking boundary as Outline, under its other name. Use Hard when one loop covers the "
        "whole footprint, and Outline when the footprint has to be split into several",
    ),
    (
        "GATE_CLOSED_HARD",
        "Gate Closed Hard Collision",
        "A closed loop stopping units from walking through the gateway while the gate is shut. Goes with "
        "a Collision 3D Gate Closed volume and the Gate Closed display meshes",
    ),
    (
        "GATE_AJAR_HARD",
        "Gate Ajar Hard Collision",
        "A closed loop stopping units from walking through where the open gate leaves stand, so they "
        "path around them instead",
    ),
    (
        "GROUND_AD",
        "Ground AD",
        "Ground Area Divider - a ground-level line splitting the terrain areas around the building. "
        "Unlike Outline and Hard it blocks nothing, and units cross it freely",
    ),
    ("PIPE_WALL_DOOR", "Pipe: Wall Door", "A route units take through a door in a wall"),
    ("PIPE_WINDOW", "Pipe: Window", "A route units take through a window"),
    ("PIPE_DOOR", "Pipe: Door", "A route units take through a door"),
    ("PIPE_JUMP", "Pipe: Jump", "A drop or gap units jump across"),
    ("PIPE_JUMP_RAMP", "Pipe: Jump Ramp", "A ramp units jump from"),
    ("PIPE_JUMP_DISEMBARK", "Pipe: Jump Disembark", "Where units jump down when leaving a ship or siege vehicle"),
    ("PIPE_RIGGING", "Pipe: Rigging", "A route units climb along a ship's rigging"),
    ("PIPE_DESTROYED_CLIMB", "Pipe: Destroyed Climb", "A route units climb over the rubble of a destroyed section"),
    (
        "PIPE_DESTROYED_CLIMB_WOOD",
        "Pipe: Destroyed Climb (Wood)",
        "A route units climb over the rubble of a destroyed wooden section",
    ),
    ("PIPE_CLIMB", "Pipe: Climb", "A surface units climb up or down"),
    ("PIPE_CLIMB_WOOD", "Pipe: Climb (Wood)", "A wooden surface units climb up or down"),
    ("PIPE_ROPE", "Pipe: Rope", "A rope units climb"),
    ("PIPE_STAIR", "Pipe: Stair", "A staircase units walk up and down"),
    ("PIPE_SIEGE_LADDER", "Pipe: Siege Ladder", "Where a siege ladder is set against the building and climbed"),
    ("PIPE_LADDER", "Pipe: Ladder", "A ladder units climb"),
    ("PIPE_LADDER_RIGHT", "Pipe: Ladder (Right)", "A ladder units climb, the right-handed variant"),
    ("PIPE_LADDER_LEFT", "Pipe: Ladder (Left)", "A ladder units climb, the left-handed variant"),
]

# EMPIREUTILITY::BUILDING_DATA_TYPE (Input/Attila.h) - the numeric type BOB stamps on every
# compiled line/pipe. Authoritative on import: a .cs2.parsed carries this value, so it beats
# guessing the type back out of the node name. RDT_2DCOLLISION_HARD is deliberately absent - it
# covers both Outline and Hard, which are the same tech under two authoring names, so only the
# node name can tell those two apart.
LINE_TYPE_BY_BUILDING_DATA_TYPE = {
    8: "PIPE_LADDER",
    9: "PIPE_STAIR",
    10: "PIPE_ROPE",
    11: "PIPE_CLIMB",
    12: "PIPE_DESTROYED_CLIMB",
    13: "PIPE_RIGGING",
    14: "PIPE_JUMP",
    15: "PIPE_DOOR",
    16: "PIPE_WINDOW",
    26: "GROUND_AD",
    28: "PIPE_CLIMB_WOOD",
    29: "PIPE_DESTROYED_CLIMB_WOOD",
    30: "PIPE_WALL_DOOR",
    31: "PIPE_JUMP_DISEMBARK",
    32: "PIPE_JUMP_RAMP",
    33: "PIPE_LADDER_LEFT",
    34: "PIPE_LADDER_RIGHT",
    35: "PIPE_SIEGE_LADDER",
}

BUILDING_DATA_TYPE_2DCOLLISION_HARD = 5
BUILDING_DATA_TYPE_2DCOLLISION_GATE = 19

COLLISION_TYPE_LABELS = {identifier: label for identifier, label, _description in COLLISION_TYPE_ITEMS}

GATE_COLLISION_TYPES = ("GATE_CLOSED", "GATE_AJAR")

# A gate's volumes are collision meshes like any other and its visible meshes are display meshes
# like any other - they only carry their own node names and, for display, their own LOD numbering.
# Every "is there a collision mesh / a display mesh here" question goes through these two. Boiling
# Oil follows the exact same pattern (confirmed from a real sample) - its collision is single/
# un-numbered like plain collision3d rather than paired like the two gate collision types, so it is
# added directly here rather than folded into GATE_COLLISION_TYPES.
COLLISION_MESH_TYPES = ("COLLISION",) + GATE_COLLISION_TYPES + ("BOILING_OIL",)

# Nested Display sub-collection roles that carry their own LOD-numbered meshes, each a separate LOD
# namespace from the plain Display collection they live in (a plain lod01 and a gate_closed_lod01,
# or a boiling_oil_lod01, are different nodes and may all exist at once). Not gate-specific despite
# the name's history - Boiling Oil is the same shape, confirmed from a real sample.
NESTED_DISPLAY_ROLES = ("GATE_CLOSED_DISPLAY", "GATE_OPEN_DISPLAY", "BOILING_OIL_DISPLAY")

# class_rigidINFO values confirmed from a real sample's building_pieceNN_destructNN_gate_*_anim
# nodes - see naming.GATE_ANIM_CLASS_RIGID_INFO, which this mirrors one-for-one.
GATE_ANIM_KIND_ITEMS = [
    ("GATE_OPENING", "Opening", "The gate leaf swinging from shut to fully open"),
    ("GATE_CLOSING", "Closing", "The gate leaf swinging from open back to shut"),
    ("GATE_CLOSED_DESTRUCT", "Closed Destruct", "Debris from the gate being destroyed while it was shut"),
    ("GATE_OPEN_DESTRUCT", "Open Destruct", "Debris from the gate being destroyed while it was open"),
]

# ~26 actions from TWBuildingsTech.ms's `actionDdl` dropdown, verbatim identifiers/labels.
# Descriptions below are a best-effort reading of what each position is for, based on the name
# itself plus general Total War siege/naval conventions - confirmed against BOB's binary only as
# far as the identifier list existing (see EFP_LOW_WALL etc. in HANDOVER_medium_effort_features.md);
# the exact in-game behaviour of each individual action is not independently verified. Correct
# freely if a real building sample or engine doc turns up a mismatch.
EFLINE_ACTION_ITEMS = [
    ("LOW_WALL", "Low wall", "A low wall the unit stands behind and fights/fires over"),
    ("HIGH_WALL", "High wall", "A tall wall opening (e.g. a battlement gap) to stand and fight over"),
    ("WINDOW", "Window", "A window opening used as a firing/defence position"),
    ("OVERFLOW", "Overflow", "An overflow slot used once the primary positions on this wall segment are full"),
    ("MARINES", "Marines", "A marine's combat position on a ship deck"),
    ("SEAMEN", "Seamen", "A ship crew (seaman) position - non-combat naval role"),
    ("GUNNERS_OVERFLOW", "Gunners_overflow", "An overflow slot for ship gun crews once the primary gunner slots are full"),
    ("CAPTAIN", "Captain", "The ship captain's position"),
    ("OFFICER1", "Officer1", "An officer position on the ship/building (variant 1)"),
    ("BOARDING", "Boarding", "A boarding-action position, used when units board an enemy ship"),
    ("NAVAL_FIRING_POSITION_STAND", "Naval_firing_position_stand", "A standing naval firing position"),
    ("NAVAL_FIRING_POSITION_CROUCH", "Naval_firing_position_crouch", "A crouching naval firing position"),
    (
        "NAVAL_FIRING_POSITION_STAND_360",
        "Naval_firing_position_stand_360",
        "A standing naval firing position with a full 360-degree firing arc",
    ),
    ("NAVAL_PERIMETER_POSITION", "Naval_perimeter_position", "A perimeter defence position on a ship"),
    ("TREE", "Tree", "Marks a tree/vegetation prop position, not a combat position"),
    ("ENTRANCE_DEFENCE", "Entrance Defence", "A defensive position covering a building entrance"),
    ("OFFICER2", "Officer2", "An officer position on the ship/building (variant 2)"),
    ("OFFICER3", "Officer3", "An officer position on the ship/building (variant 3)"),
    ("CRENEL_LEFT_OUTER", "Crenel left outer", "A crenellation firing position: left side, outer edge"),
    ("CRENEL_LEFT_INNER", "Crenel left inner", "A crenellation firing position: left side, inner edge"),
    ("CRENEL_RIGHT_INNER", "Crenel right inner", "A crenellation firing position: right side, inner edge"),
    ("CRENEL_RIGHT_OUTER", "Crenel right outer", "A crenellation firing position: right side, outer edge"),
    ("ENGINE_PLACEMENT", "Engine_placement", "A siege/war-engine placement position"),
    ("SECONDARY_ENGINE_PLACEMENT", "Secondary_engine_placement", "A secondary siege/war-engine placement position"),
    ("DISEMBARK_LEFT", "Disembark_left", "A disembarkation point on the left side, for units leaving a ship"),
    ("DISEMBARK_RIGHT", "Disembark_right", "A disembarkation point on the right side, for units leaving a ship"),
]

EFLINE_ACTION_LABELS = {identifier: label for identifier, label, _description in EFLINE_ACTION_ITEMS}


# .bone_table bone types. The first six are every type Attila's own rome_man_game.bone_table uses;
# the last two occur only in the Pharaoh and Three Kingdoms tables and are offered so a table
# imported from a later title round-trips rather than being silently rewritten. NONE is not a bone
# type - it marks a scene node the table does not list at all, which is what 178 of
# rome_man_game.cs2's 228 nodes are (helper points, end markers and face rig drivers).
BONE_TYPE_ITEMS = [
    ("NONE", "Not In Bone Table", "A helper or rig node the skeleton needs but the game never indexes as a bone"),
    ("BT_ROOT", "Root", "The skeleton's root bone - the only one with sort order 0"),
    ("BT_CORE", "Core", "An ordinary skeleton bone - spine, limbs, head, feet"),
    ("BT_FACE", "Face", "A facial rig bone - jaw, eyes, eyelids, eyebrows"),
    ("BT_FLOATING", "Floating", "A bone with no skin weighted to it, used to hang props off - the weapon_01..05 bones"),
    ("BT_LEFT_HAND", "Left Hand", "A left-hand finger bone"),
    ("BT_RIGHT_HAND", "Right Hand", "A right-hand finger bone"),
    ("BT_CORE_TRANS", "Core (Translating)", "Core bone that also translates. Later titles only - not used by Attila"),
    ("BT_BEARD", "Beard", "A beard rig bone. Later titles only - not used by Attila"),
]

NO_BONE_TYPE = "NONE"


_addon_package_name = "total_war_cs2_addon"

_ASSEMBLY_KIT_RELATIVE_PATH = Path("steamapps/common/Total War Attila/assembly_kit")


def _steam_roots() -> list[Path]:
    roots: list[Path] = []
    for hive, key in (
        (winreg.HKEY_CURRENT_USER, r"Software\Valve\Steam"),
        (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Valve\Steam"),
    ):
        for value in ("SteamPath", "InstallPath"):
            try:
                with winreg.OpenKey(hive, key) as handle:
                    roots.append(Path(winreg.QueryValueEx(handle, value)[0]))
            except OSError:
                pass
    roots.append(Path(r"C:\Program Files (x86)\Steam"))
    return roots


def _default_assembly_kit_root() -> str:
    # Steam spreads games across library folders on any drive, so no one install path can be
    # assumed. libraryfolders.vdf is Steam's own list of them, read as text rather than parsed as
    # real VDF because the only field wanted is each library's "path".
    candidates: list[Path] = []
    for steam_root in _steam_roots():
        candidates.append(steam_root)
        try:
            manifest = (steam_root / "steamapps/libraryfolders.vdf").read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        candidates.extend(Path(path.replace("\\\\", "\\")) for path in re.findall(r'"path"\s+"(.+?)"', manifest))
    for candidate in candidates:
        assembly_kit = candidate / _ASSEMBLY_KIT_RELATIVE_PATH
        try:
            if assembly_kit.is_dir():
                return str(assembly_kit)
        except OSError:
            pass
    return ""


class TWBuildingsPreferences(bpy.types.AddonPreferences):
    bl_idname = "total_war_cs2_addon"

    assembly_kit_root: bpy.props.StringProperty(
        name="Assembly Kit Folder",
        description=(
            "Where the Assembly Kit is installed - the folder holding 'raw_data', 'binaries' and "
            "'max_exporter'. The add-on needs it to find the game's shaders for the material preview, "
            "and to compile and pack what you export. Attila's kit is found automatically; point this at "
            "another title's kit by hand"
        ),
        subtype="DIR_PATH",
        default=_default_assembly_kit_root(),
    )

    def draw(self, context: bpy.types.Context) -> None:
        self.layout.prop(self, "assembly_kit_root")


def set_addon_package_name(name: str) -> None:
    global _addon_package_name
    _addon_package_name = name
    TWBuildingsPreferences.bl_idname = name


def get_assembly_kit_root(context: bpy.types.Context) -> str:
    return context.preferences.addons[_addon_package_name].preferences.assembly_kit_root


def get_assembly_kit_root_or_empty() -> str:
    # For callers with no context to hand, such as node-tree construction.
    try:
        return bpy.context.preferences.addons[_addon_package_name].preferences.assembly_kit_root
    except Exception:
        return ""


DAMAGE_PARENT_DESCRIPTION = (
    "When the parent piece takes damage, this piece takes partial damage too. Used for fort walls, "
    "where destroying one segment also partly damages the segments either side. Leave empty for a "
    "standalone piece"
)


def _damage_parent_poll(collection: bpy.types.Collection, candidate: bpy.types.Collection) -> bool:
    return candidate.tw_role == "PIECE" and candidate is not collection


def register() -> None:
    try:
        bpy.utils.register_class(TWBuildingsPreferences)
    except ValueError:
        pass

    bpy.types.Collection.tw_role = bpy.props.EnumProperty(
        items=TW_ROLE_ITEMS,
        name="Total War Role",
        description=(
            "What this collection holds. The New and Add buttons set it for you; select the collection "
            "to read what it is for in Properties > Collection > Total War Info"
        ),
        default="NONE",
    )
    bpy.types.Collection.tw_asset_type = bpy.props.EnumProperty(
        items=ASSET_TYPE_ITEMS,
        name="Asset Type",
        description="What kind of battlefield asset this building exports as",
        default="DISPLAY_BUILDING",
    )

    bpy.types.Collection.tw_unit_part_kind = bpy.props.EnumProperty(
        items=UNIT_PART_KIND_ITEMS,
        name="Model Type",
        description="Which export shape this model takes - hover an option below for details. Every model in one asset has to agree, because the compiled file carries a single shader family and bone table",
        default="WEIGHTED",
    )

    bpy.types.Collection.tw_damage_parent = bpy.props.PointerProperty(
        type=bpy.types.Collection,
        name="Damage Parent",
        description=DAMAGE_PARENT_DESCRIPTION,
        poll=_damage_parent_poll,
    )

    bpy.types.Object.tw_collision_type = bpy.props.EnumProperty(
        items=COLLISION_TYPE_ITEMS,
        name="Collision Type",
        description="What this collision mesh represents - hover an option below for details",
        default="COLLISION",
    )

    bpy.types.Object.tw_platform_type = bpy.props.EnumProperty(
        items=PLATFORM_TYPE_ITEMS,
        name="Platform Type",
        description="What this platform mesh represents - hover an option below for details",
        default="PLATFORM",
    )

    bpy.types.Object.tw_lod_index = bpy.props.EnumProperty(
        items=LOD_ITEMS,
        name="LOD Level",
        description=(
            "Which level of detail this mesh is. The game swaps in a lower level as the camera moves away. "
            "Skipping a level is allowed - the ones you do have pack into consecutive slots, each keeping "
            "the distance its own level implies, so you get a shorter chain rather than a gap"
        ),
        default="LOD01",
    )

    bpy.types.Object.tw_file_reference_name = bpy.props.StringProperty(
        name="Referenced Prop Name",
        description="The external prop this stands in for, e.g. 'torch_sconce' for RigidModels/Buildings/torch_sconce/. The object's own position and rotation are where the game puts it",
    )

    bpy.types.Object.tw_attachment_point_name = bpy.props.StringProperty(
        name="Attachment Point",
        description=(
            "Marks this object as an attachment point on a weighted unit part, under this name - "
            "'weapon_01', 'crest_centre'. Parent it to the bone it hangs off (Ctrl+P > Bone); a "
            ".variantmeshdefinition then binds a weapon, shield or crest to it by this name"
        ),
    )

    bpy.types.Object.tw_debris_track_index = bpy.props.IntProperty(
        name="Debris Track",
        description="Which track of the imported debris animation moves this chunk. -1 on anything that did not come in with one",
        default=-1,
    )

    bpy.types.Object.tw_line_type = bpy.props.EnumProperty(
        items=LINE_TYPE_ITEMS,
        name="Line Type",
        description="What this curve marks out - hover an option below for details",
        default="OUTLINE",
    )

    bpy.types.Object.tw_efline_action = bpy.props.EnumProperty(
        items=EFLINE_ACTION_ITEMS,
        name="EFLine Action",
        description="What the units standing on this line are doing there - hover an option below for details",
        default="LOW_WALL",
    )

    bpy.types.Object.tw_gate_anim_kind = bpy.props.EnumProperty(
        items=GATE_ANIM_KIND_ITEMS,
        name="Gate Animation Kind",
        description="Which of the gate's four animations this object's keyframes belong to",
        default="GATE_OPENING",
    )

    bpy.types.Scene.tw_workflow = bpy.props.EnumProperty(
        items=TW_WORKFLOW_ITEMS,
        name="Workflow",
        description=(
            "Which kind of asset you are working on. It only changes which panels the sidebar shows and "
            "which shaders the Materials panel offers - nothing in the scene is altered. Importing a file "
            "switches it for you"
        ),
        default="BUILDING",
    )

    bpy.types.Scene.tw_preview_light = bpy.props.PointerProperty(
        type=bpy.types.Object,
        name="Preview Light",
        description=(
            "The light the Total War shader lights its preview from. The game shader carries its own "
            "light, so Blender's lamps do not reach it on their own. Leave empty to use the first Sun in "
            "the scene"
        ),
        poll=lambda self, obj: obj.type == "LIGHT",
    )

    bpy.types.Scene.tw_live_preview_light = bpy.props.BoolProperty(
        name="Follow Light",
        description="Update the preview as the light is moved or recoloured, instead of only when Sync Preview Light is pressed",
        default=True,
    )

    bpy.types.Armature.tw_bone_table_version = bpy.props.IntProperty(
        name="Bone Table Version",
        description="Version stamp written into the exported .bone_table. Every bone table in the game carries 1",
        default=1,
        min=0,
    )

    bpy.types.Armature.tw_reference_skeleton = bpy.props.BoolProperty(
        name="Reference Skeleton",
        description="Mark this as a reference skeleton that other skeletons are derived from, rather than one derived from another",
        default=True,
    )

    bpy.types.Armature.tw_cinematic = bpy.props.BoolProperty(
        name="Cinematic",
        description="Mark this as a higher-detail skeleton for cinematics rather than one used in battle",
        default=False,
    )

    bpy.types.Bone.tw_bone_type = bpy.props.EnumProperty(
        items=BONE_TYPE_ITEMS,
        name="Bone Type",
        description="What kind of bone this is in the exported bone table - hover an option below for details",
        default="BT_CORE",
    )

    bpy.types.Bone.tw_bone_sort_order = bpy.props.IntProperty(
        name="Sort Order",
        description="This bone's sort order in the exported bone table. Every skeleton in the game uses 0 on the root bone and 1 on all the rest",
        default=1,
        min=0,
    )

    bpy.types.Bone.tw_bone_flags = bpy.props.StringProperty(
        name="Bone Flags",
        description="An optional extra tag for this bone. Attila leaves it empty; later titles use 'attachment_point'",
    )

    # Bone table line order is neither the hierarchy nor the compiled bone index order, so there is
    # no rule to re-derive it from - an imported skeleton keeps the order its file had, and bones
    # authored in Blender (order 0) are appended alphabetically after it.
    bpy.types.Bone.tw_bone_table_order = bpy.props.IntProperty(
        name="Bone Table Line",
        description="Which line this bone was on in the bone table it was imported from, so it exports in the same order. 0 on a bone added here",
        default=0,
        min=0,
    )

    bpy.types.Bone.tw_max_handle = bpy.props.IntProperty(
        name="Max Handle",
        description="The identifier this bone carried in the file it was imported from, kept so a re-export matches it",
        default=0,
        min=0,
    )

    bpy.types.Bone.tw_is_limb = bpy.props.BoolProperty(
        name="Bone Object",
        description="Export this as a real bone with a length rather than a bare marker point. Only affects one attribute in the exported skeleton",
        default=True,
    )

    bpy.types.Action.tw_skeleton_name = bpy.props.StringProperty(
        name="Skeleton",
        description="Which skeleton this clip animates. The compiled clip carries this name, and it is what tells BOB which skeleton to build the clip against",
    )

    bpy.types.Action.tw_frame_rate = bpy.props.FloatProperty(
        name="Clip FPS",
        description="How many frames a second this clip runs at. One Blender frame is one clip frame, so this is both what the scene plays back at and what the clip is compiled at",
        default=0.0,
        min=0.0,
    )

    bpy.types.Material.tw_alpha_mode = bpy.props.EnumProperty(
        items=ALPHA_MODE_ITEMS,
        name="Alpha Mode",
        description="How the shader treats the diffuse texture's alpha channel - hover an option below for details",
        default=DEFAULT_ALPHA_MODE,
    )

    bpy.types.Material.tw_shader_type = bpy.props.EnumProperty(
        items=[(identifier, label, description) for identifier, label, description in SHADER_TYPES],
        name="Total War Shader Type",
        description="Which of the game's shaders this material uses. Pick one from the Materials panel in the Total War sidebar",
        default=DEFAULT_SHADER_TYPE,
    )


def unregister() -> None:
    del bpy.types.Action.tw_frame_rate
    del bpy.types.Action.tw_skeleton_name
    del bpy.types.Material.tw_shader_type
    del bpy.types.Material.tw_alpha_mode
    del bpy.types.Bone.tw_is_limb
    del bpy.types.Bone.tw_max_handle
    del bpy.types.Bone.tw_bone_table_order
    del bpy.types.Bone.tw_bone_flags
    del bpy.types.Bone.tw_bone_sort_order
    del bpy.types.Bone.tw_bone_type
    del bpy.types.Armature.tw_cinematic
    del bpy.types.Armature.tw_reference_skeleton
    del bpy.types.Armature.tw_bone_table_version
    del bpy.types.Scene.tw_live_preview_light
    del bpy.types.Scene.tw_preview_light
    del bpy.types.Scene.tw_workflow
    del bpy.types.Object.tw_gate_anim_kind
    del bpy.types.Object.tw_efline_action
    del bpy.types.Object.tw_debris_track_index
    del bpy.types.Object.tw_line_type
    del bpy.types.Object.tw_attachment_point_name
    del bpy.types.Object.tw_lod_index
    del bpy.types.Object.tw_file_reference_name
    del bpy.types.Object.tw_platform_type
    del bpy.types.Object.tw_collision_type
    del bpy.types.Collection.tw_damage_parent
    del bpy.types.Collection.tw_unit_part_kind
    del bpy.types.Collection.tw_asset_type
    del bpy.types.Collection.tw_role

    bpy.utils.unregister_class(TWBuildingsPreferences)
