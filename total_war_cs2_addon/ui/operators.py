import time

import bpy
from bpy_extras.io_utils import ImportHelper

from props.properties import get_assembly_kit_root, TW_ROLE_LABELS, TW_ROLE_DESCRIPTIONS
from materials.fx_nodegroup import find_preview_light, sync_light
from extraction.extract import second_uv_layer_name
from materials.material_builder import apply_standard_view_transform, bind_uv2_layer, create_total_war_material
from materials.shader_types import SHADER_TYPE_DESCRIPTIONS
from validation.rules import validate_building
from export.exporter import export_building
from bob import rules
from bob.cli import BobError, BobResult, start_building_batch
from importer import import_file, UnsupportedFileError
from importer.messages import severity_of
from importer.rigid_model_v2_importer import models_needing_a_skeleton
from importer.proxy_loader import get_arrow_emitter_proxy_geometry, FLAG_VERTICES, FLAG_FACES
from .collection_utils import (
    export_batch,
    find_building_collection,
    get_active_collection,
    get_object_collection_role,
    MixedSelectionError,
)

# role -> (default collection name, what-to-do-next hint shown after creating it). The tooltip
# text itself lives in props.properties.TW_ROLE_DESCRIPTIONS (single source of truth, also used by
# the Collection Properties panel in ui/panels.py) - don't duplicate it here. Adding a new
# "Add ..." destruct-level feature is one line here plus one line in TW_ROLE_ITEMS - no new
# Operator class needed, and it automatically gets a menu entry and a tooltip.
DESTRUCT_COLLECTION_ROLES = {
    "PLATFORM": (TW_ROLE_LABELS["PLATFORM"], "Add walkable surface meshes to it."),
    "FILE_REFERENCE": (
        TW_ROLE_LABELS["FILE_REFERENCE"],
        "Add an Empty (or a preview mesh) per prop, place it, and set its Referenced Prop Name.",
    ),
    "LINES": (TW_ROLE_LABELS["LINES"], "Add curve objects to it and set each one's Line Type."),
    "EF_LINES": (
        TW_ROLE_LABELS["EF_LINES"],
        "Use New Line to add one, then move its points to place it and its pointer tip to aim it.",
    ),
    "DOCKING_LINES": (
        TW_ROLE_LABELS["DOCKING_LINES"],
        "Use New Line to add one, then move its points to place it and its pointer tip to aim it.",
    ),
    "ARROW_EMITTERS": (
        TW_ROLE_LABELS["ARROW_EMITTERS"],
        "Click 'New Arrow Emitter' to add one, then move/rotate it to position and aim it.",
    ),
    "HEIGHT_MAP_MESH": (
        TW_ROLE_LABELS["HEIGHT_MAP_MESH"],
        "Add terrain height-map mesh objects to it.",
    ),
    "DESTRUCTION_ANIM": (
        TW_ROLE_LABELS["DESTRUCTION_ANIM"],
        "Add debris chunk meshes to it (UV + material required), then keyframe-animate each one's "
        "transform in Blender's own timeline.",
    ),
}

# role -> (default collection name, hint) for building-level (not destruct-scoped) features.
BUILDING_COLLECTION_ROLES = {
    "REGION_ZONES": (TW_ROLE_LABELS["REGION_ZONES"], "Add closed (cyclic) curve objects to it, one per region zone."),
    "FLAG": (TW_ROLE_LABELS["FLAG"], "Click 'New Flag' to add the marker, then move it to where the UI icon should sit."),
}

# role -> (default collection name, hint) for collections that live inside a Display collection.
DISPLAY_COLLECTION_ROLES = {
    "GATE_CLOSED_DISPLAY": (
        TW_ROLE_LABELS["GATE_CLOSED_DISPLAY"],
        "Add the shut gate's LOD meshes to it. Its collision goes in the Collision collection "
        "(Collision 3D Gate Closed) and its pathfinding line in Lines (Gate Closed Hard Collision).",
    ),
    "GATE_OPEN_DISPLAY": (
        TW_ROLE_LABELS["GATE_OPEN_DISPLAY"],
        "Add the open gate's LOD meshes to it, modelled where they end up once swung open.",
    ),
    "GATE_ANIMATION": (
        TW_ROLE_LABELS["GATE_ANIMATION"],
        "Add the moving door leaf meshes to it (UV + material required), set each one's Gate "
        "Animation Kind, then keyframe-animate its transform in Blender's own timeline.",
    ),
    "BOILING_OIL_DISPLAY": (
        TW_ROLE_LABELS["BOILING_OIL_DISPLAY"],
        "Add the boiling-oil mechanism's LOD meshes to it. Its collision goes in the Collision "
        "collection (Collision 3D Boiling Oil).",
    ),
}

DESTRUCT_COLLECTION_ROLE_ITEMS = [(role, name, TW_ROLE_DESCRIPTIONS[role]) for role, (name, _hint) in DESTRUCT_COLLECTION_ROLES.items()]
BUILDING_COLLECTION_ROLE_ITEMS = [(role, name, TW_ROLE_DESCRIPTIONS[role]) for role, (name, _hint) in BUILDING_COLLECTION_ROLES.items()]
DISPLAY_COLLECTION_ROLE_ITEMS = [(role, name, TW_ROLE_DESCRIPTIONS[role]) for role, (name, _hint) in DISPLAY_COLLECTION_ROLES.items()]


# Mixin, not an Operator subclass, so Blender never registers it on its own. A menu row takes its
# tooltip from the operator it runs, not from the enum item it sets, so without this every "Add..."
# row would share one generic description instead of explaining its own collection.
class RoleTooltipMixin:
    @classmethod
    def description(cls, context: bpy.types.Context, properties) -> str:
        return TW_ROLE_DESCRIPTIONS.get(properties.role, cls.bl_description)


class TW_OT_new_building(bpy.types.Operator):
    bl_idname = "tw_buildings.new_building"
    bl_label = "New Building"
    bl_description = (
        "Create a new battlefield building. Name it after the file it should export as, then add a "
        "Piece and a Destruct Level to it"
    )
    bl_options = {"REGISTER", "UNDO"}

    asset_name: bpy.props.StringProperty(
        name="Building Name",
        default="new_building",
        description="What this building exports as - the .CS2 and everything BOB compiles from it take this name",
    )

    def invoke(self, context: bpy.types.Context, event: bpy.types.Event):
        return context.window_manager.invoke_props_dialog(self)

    def execute(self, context: bpy.types.Context):
        if not self.asset_name.strip():
            self.report({"ERROR"}, "A building needs a name - it is what the exported file is called.")
            return {"CANCELLED"}
        try:
            collection = bpy.data.collections.new(self.asset_name.strip())
            collection.tw_role = "BUILDING"
            context.scene.collection.children.link(collection)
        except Exception as error:  # noqa: BLE001
            self.report({"ERROR"}, f"Could not create building: {error}")
            return {"CANCELLED"}
        if collection.name != self.asset_name.strip():
            self.report(
                {"WARNING"},
                f"'{self.asset_name.strip()}' was already taken, so this one is '{collection.name}' - "
                "which is the name it will export under.",
            )
        self.report({"INFO"}, f"Created '{collection.name}'. Add a Building Piece next.")
        return {"FINISHED"}


class TW_OT_new_piece(bpy.types.Operator):
    bl_idname = "tw_buildings.new_piece"
    bl_label = "New Building Piece"
    bl_description = (
        "Add a structural piece to the selected building - a gatehouse, a tower, one wall segment. A "
        "piece is destroyed as a unit, so split the building wherever parts should fall separately"
    )
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context: bpy.types.Context):
        building = get_active_collection(context)
        if building is None or building.tw_role != "BUILDING":
            self.report({"ERROR"}, "Select a Building collection in the Outliner first.")
            return {"CANCELLED"}
        try:
            piece = bpy.data.collections.new("Piece")
            piece.tw_role = "PIECE"
            building.children.link(piece)
        except Exception as error:  # noqa: BLE001
            self.report({"ERROR"}, f"Could not create building piece: {error}")
            return {"CANCELLED"}
        self.report({"INFO"}, f"Created '{piece.name}'. Add a Destruct Level next.")
        return {"FINISHED"}


class TW_OT_new_destruct_level(bpy.types.Operator):
    bl_idname = "tw_buildings.new_destruct_level"
    bl_label = "New Destruct Level"
    bl_description = (
        "Add a damage state to the selected piece, with the Display and Collision collections it needs. "
        "The first is the undamaged building, each one after it is how the piece looks once it has taken "
        "more damage"
    )
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context: bpy.types.Context):
        piece = get_active_collection(context)
        if piece is None or piece.tw_role != "PIECE":
            self.report({"ERROR"}, "Select a Building Piece collection in the Outliner first.")
            return {"CANCELLED"}
        try:
            destruct = bpy.data.collections.new("Destruct")
            destruct.tw_role = "DESTRUCT"
            piece.children.link(destruct)

            display = bpy.data.collections.new("Display")
            display.tw_role = "DISPLAY"
            destruct.children.link(display)

            collision = bpy.data.collections.new("Collision")
            collision.tw_role = "COLLISION"
            destruct.children.link(collision)
        except Exception as error:  # noqa: BLE001
            self.report({"ERROR"}, f"Could not create destruct level: {error}")
            return {"CANCELLED"}
        self.report({"INFO"}, f"Created '{destruct.name}'. Populate its Display and Collision sub-collections next.")
        return {"FINISHED"}


class TW_OT_add_destruct_collection(RoleTooltipMixin, bpy.types.Operator):
    bl_idname = "tw_buildings.add_destruct_collection"
    bl_label = "Add Destruct Feature Collection"
    bl_description = "Add a feature collection to the selected Destruct Level"
    bl_options = {"REGISTER", "UNDO"}

    role: bpy.props.EnumProperty(items=DESTRUCT_COLLECTION_ROLE_ITEMS, name="Role")

    def execute(self, context: bpy.types.Context):
        destruct = get_active_collection(context)
        if destruct is None or destruct.tw_role != "DESTRUCT":
            self.report({"ERROR"}, "Select a Destruct Level collection in the Outliner first.")
            return {"CANCELLED"}

        existing_roles = {child.tw_role for child in destruct.children}
        if self.role in existing_roles:
            self.report({"WARNING"}, f"'{destruct.name}' already has a {TW_ROLE_LABELS[self.role]} collection.")
            return {"CANCELLED"}

        default_name, hint = DESTRUCT_COLLECTION_ROLES[self.role]
        try:
            collection = bpy.data.collections.new(default_name)
            collection.tw_role = self.role
            destruct.children.link(collection)
        except Exception as error:  # noqa: BLE001
            self.report({"ERROR"}, f"Could not create collection: {error}")
            return {"CANCELLED"}

        self.report({"INFO"}, f"Created '{collection.name}'. {hint}")
        return {"FINISHED"}


class TW_OT_add_building_collection(RoleTooltipMixin, bpy.types.Operator):
    bl_idname = "tw_buildings.add_building_collection"
    bl_label = "Add Building Feature Collection"
    bl_description = "Add a feature collection that belongs to the whole building rather than to one piece"
    bl_options = {"REGISTER", "UNDO"}

    role: bpy.props.EnumProperty(items=BUILDING_COLLECTION_ROLE_ITEMS, name="Role")

    def execute(self, context: bpy.types.Context):
        building = find_building_collection(context)
        if building is None:
            self.report({"ERROR"}, "Select something inside a Building collection first.")
            return {"CANCELLED"}

        existing_roles = {child.tw_role for child in building.children}
        if self.role in existing_roles:
            self.report({"WARNING"}, f"'{building.name}' already has a {TW_ROLE_LABELS[self.role]} collection.")
            return {"CANCELLED"}

        default_name, hint = BUILDING_COLLECTION_ROLES[self.role]
        try:
            collection = bpy.data.collections.new(default_name)
            collection.tw_role = self.role
            building.children.link(collection)
        except Exception as error:  # noqa: BLE001
            self.report({"ERROR"}, f"Could not create collection: {error}")
            return {"CANCELLED"}

        self.report({"INFO"}, f"Created '{collection.name}'. {hint}")
        return {"FINISHED"}


# Vertices/triangles extracted directly from a real sample's arrow_emitter geometry
# (gondor_fort_tower_C_straight.CS2, all 8 instances share this shape up to floating-point export
# noise), converted from the CS2 file's engine (Y-up) space back to Blender's Z-up via
# (X, Y, Z) -> (X, Z, Y) - the inverse of extraction._to_engine_space(). The shape is a flat
# rectangle with one long edge pulled in to a center point, forming a chevron/arrow - a real visual
# direction indicator for the artist, not a rendered mesh (it exports with material_id=-1, same as
# collision/platform). The artist aims it purely by rotating the whole object; BOB derives its own
# game-side transform from the exported geometry, the same way it already does for platforms.
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


class TW_OT_new_arrow_emitter(bpy.types.Operator):
    bl_idname = "tw_buildings.new_arrow_emitter"
    bl_label = "New Arrow Emitter"
    bl_description = (
        "Add an arrow emitter - a firing position siege-tower archers shoot from. Move and rotate the "
        "marker to place it and aim it; its shape is fixed and is not exported as geometry"
    )
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context: bpy.types.Context):
        collection = get_active_collection(context)
        if collection is None or collection.tw_role != "ARROW_EMITTERS":
            self.report({"ERROR"}, "Select an Arrow Emitters collection in the Outliner first.")
            return {"CANCELLED"}
        try:
            verts, tris = get_arrow_emitter_proxy_geometry()
            mesh = bpy.data.meshes.new("ArrowEmitter")
            mesh.from_pydata(verts, [], tris)
            mesh.update()
            obj = bpy.data.objects.new("ArrowEmitter", mesh)
            collection.objects.link(obj)
            context.view_layer.objects.active = obj
            obj.select_set(True)
        except Exception as error:  # noqa: BLE001
            self.report({"ERROR"}, f"Could not create arrow emitter: {error}")
            return {"CANCELLED"}
        self.report({"INFO"}, f"Created '{obj.name}'. Move/rotate it to position and aim it.")
        return {"FINISHED"}


class TW_OT_add_display_collection(RoleTooltipMixin, bpy.types.Operator):
    bl_idname = "tw_buildings.add_display_collection"
    bl_label = "Add Display Feature Collection"
    bl_description = "Add a gate or boiling-oil collection to the selected Display collection"
    bl_options = {"REGISTER", "UNDO"}

    role: bpy.props.EnumProperty(items=DISPLAY_COLLECTION_ROLE_ITEMS, name="Role")

    def execute(self, context: bpy.types.Context):
        display = get_active_collection(context)
        if display is None or display.tw_role != "DISPLAY":
            self.report({"ERROR"}, "Select a Display collection in the Outliner first.")
            return {"CANCELLED"}

        if self.role in {child.tw_role for child in display.children}:
            self.report({"WARNING"}, f"'{display.name}' already has a {TW_ROLE_LABELS[self.role]} collection.")
            return {"CANCELLED"}

        default_name, hint = DISPLAY_COLLECTION_ROLES[self.role]
        try:
            collection = bpy.data.collections.new(default_name)
            collection.tw_role = self.role
            display.children.link(collection)
        except Exception as error:  # noqa: BLE001
            self.report({"ERROR"}, f"Could not create collection: {error}")
            return {"CANCELLED"}

        self.report({"INFO"}, f"Created '{collection.name}'. {hint}")
        return {"FINISHED"}


class TW_OT_new_flag(bpy.types.Operator):
    bl_idname = "tw_buildings.new_flag"
    bl_label = "New Flag"
    bl_description = (
        "Add the building's flag point - the position its icon is drawn at in the battle UI. Move the "
        "marker to place it. One per building"
    )
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context: bpy.types.Context):
        collection = get_active_collection(context)
        if collection is None or collection.tw_role != "FLAG":
            self.report({"ERROR"}, "Select a Flag collection in the Outliner first.")
            return {"CANCELLED"}
        if any(obj.type == "MESH" for obj in collection.objects):
            self.report({"WARNING"}, "This building already has a flag; only one is exported.")
            return {"CANCELLED"}
        try:
            mesh = bpy.data.meshes.new("Flag")
            mesh.from_pydata(FLAG_VERTICES, [], FLAG_FACES)
            mesh.update()
            obj = bpy.data.objects.new("Flag", mesh)
            collection.objects.link(obj)
            context.view_layer.objects.active = obj
            obj.select_set(True)
        except Exception as error:  # noqa: BLE001
            self.report({"ERROR"}, f"Could not create flag: {error}")
            return {"CANCELLED"}
        self.report({"INFO"}, f"Created '{obj.name}'. Move it to where the building's UI icon should sit.")
        return {"FINISHED"}


MARKER_LINE_ROLES = ("EF_LINES", "DOCKING_LINES")


def marker_line_geometry(start, end):
    # TWBuildingsTech.ms subdivides the artist's 2-knot line and hangs a second spline off the
    # midpoint at `pt_mid + [-Rv.y, Rv.x, 0]`, where Rv is the midpoint minus the start - so the
    # pointer is perpendicular to the line and half its length. Same shape here, as one mesh:
    # v0 start, v1 midpoint, v2 end, v3 pointer tip.
    mid = tuple((s + e) / 2.0 for s, e in zip(start, end))
    rv_x, rv_y = mid[0] - start[0], mid[1] - start[1]
    tip = (mid[0] - rv_y, mid[1] + rv_x, mid[2])
    return [start, mid, end, tip], [(0, 1), (1, 2), (1, 3)]


def lock_marker_line_tilt(obj) -> None:
    # Units standing on an EFLine are on a platform looking horizontally, so only yaw - rotation
    # about Blender Z, which is the engine's up axis Y - changes anything the exporter writes. All
    # 158 real markers are perfectly level with a perfectly horizontal direction. Locking the other
    # two rotation axes keeps a marker out of a tilted state that could never round-trip.
    obj.lock_rotation[0] = True
    obj.lock_rotation[1] = True


def _marker_line_start_end_tip(obj):
    points = [tuple(vertex.co) for vertex in obj.data.vertices]
    if len(points) == 2:
        return points[0], points[1], None
    if len(points) == 4:
        return points[0], points[2], points[3]
    raise ValueError(f"expected 2 or 4 vertices, found {len(points)}")


def _write_marker_line_mesh(obj, verts, edges) -> None:
    obj.data.clear_geometry()
    obj.data.from_pydata(verts, edges, [])
    obj.data.update()
    lock_marker_line_tilt(obj)


def rebuild_marker_line_mesh(obj) -> None:
    start, end, _tip = _marker_line_start_end_tip(obj)
    if (start[0], start[1]) == (end[0], end[1]):
        raise ValueError("the line has no horizontal length, so it has no perpendicular")
    _write_marker_line_mesh(obj, *marker_line_geometry(start, end))


def invert_marker_line_mesh(obj) -> None:
    start, end, tip = _marker_line_start_end_tip(obj)
    if (start[0], start[1]) == (end[0], end[1]):
        raise ValueError("the line has no horizontal length, so it has no direction to invert")
    verts, edges = marker_line_geometry(start, end)
    mid = verts[1]
    current = verts[3] if tip is None else tip
    # Only the heading is inverted, and the tip comes back level with the midpoint: a tip's height
    # never reaches the exported direction, so leaving it raised would show a tilt that isn't real.
    inverted = (2.0 * mid[0] - current[0], 2.0 * mid[1] - current[1], mid[2])
    if (inverted[0], inverted[1]) == (mid[0], mid[1]):
        raise ValueError("the direction pointer has no horizontal length, so there is nothing to invert")
    verts[3] = inverted
    _write_marker_line_mesh(obj, verts, edges)


class TW_OT_new_marker_line(bpy.types.Operator):
    bl_idname = "tw_buildings.new_marker_line"
    bl_label = "New Line"
    bl_description = (
        "Add a marker line with its direction pointer - move the start and end points to place the line, "
        "and the pointer tip to turn the way its units face. Keep both ends at the same height"
    )
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context: bpy.types.Context):
        collection = get_active_collection(context)
        if collection is None or collection.tw_role not in MARKER_LINE_ROLES:
            self.report({"ERROR"}, "Select an EFLines or Docking Lines collection in the Outliner first.")
            return {"CANCELLED"}
        try:
            name = "EFLine" if collection.tw_role == "EF_LINES" else "DockingLine"
            verts, edges = marker_line_geometry((-1.0, 0.0, 0.0), (1.0, 0.0, 0.0))
            mesh = bpy.data.meshes.new(name)
            mesh.from_pydata(verts, edges, [])
            mesh.update()
            obj = bpy.data.objects.new(name, mesh)
            lock_marker_line_tilt(obj)
            collection.objects.link(obj)
            context.view_layer.objects.active = obj
            obj.select_set(True)
        except Exception as error:  # noqa: BLE001
            self.report({"ERROR"}, f"Could not create line: {error}")
            return {"CANCELLED"}
        self.report({"INFO"}, f"Created '{obj.name}'. Move its points to place it, and the pointer tip to aim it.")
        return {"FINISHED"}


class _MarkerLineEditOperator(bpy.types.Operator):
    bl_options = {"REGISTER", "UNDO"}

    edit = staticmethod(rebuild_marker_line_mesh)
    past_tense = "Edited"

    def execute(self, context: bpy.types.Context):
        targets = [
            obj
            for obj in context.selected_objects
            if obj.type == "MESH" and get_object_collection_role(obj) in MARKER_LINE_ROLES
        ]
        if not targets:
            self.report({"ERROR"}, "Select one or more EFLine or Docking Line objects first.")
            return {"CANCELLED"}
        failures = []
        for obj in targets:
            try:
                type(self).edit(obj)
            except Exception as error:  # noqa: BLE001
                failures.append(f"'{obj.name}' ({error})")
        if failures:
            self.report(
                {"WARNING"},
                f"{self.past_tense} {len(targets) - len(failures)} line(s); skipped {', '.join(failures)}.",
            )
            return {"FINISHED"}
        self.report({"INFO"}, f"{self.past_tense} {len(targets)} line(s).")
        return {"FINISHED"}


class TW_OT_reset_marker_line_direction(_MarkerLineEditOperator):
    bl_idname = "tw_buildings.reset_marker_line_direction"
    bl_label = "Reset Direction Pointer"
    bl_description = (
        "Aim the direction pointer square to the line again, and give a line that has no pointer yet "
        "one to aim"
    )

    edit = staticmethod(rebuild_marker_line_mesh)
    past_tense = "Reset the direction pointer on"


class TW_OT_invert_marker_line_direction(_MarkerLineEditOperator):
    bl_idname = "tw_buildings.invert_marker_line_direction"
    bl_label = "Invert Direction"
    bl_description = "Turn the direction pointer through 180 degrees, so its units face the other way"

    edit = staticmethod(invert_marker_line_mesh)
    past_tense = "Inverted"


class TW_OT_make_material(bpy.types.Operator):
    bl_idname = "tw_buildings.make_material"
    bl_label = "Make Total War Material"
    bl_description = (
        "Rebuild the active material with the game's own shader, so the viewport preview matches what "
        "the game will draw. Its texture slots then appear as image nodes to fill in"
    )
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context: bpy.types.Context):
        obj = context.active_object
        if obj is None or obj.active_material is None:
            self.report({"ERROR"}, "Select a mesh object with an active material first.")
            return {"CANCELLED"}
        try:
            create_total_war_material(obj.active_material)
            bound_uv2 = obj.type == "MESH" and bind_uv2_layer(obj.active_material, second_uv_layer_name(obj.data))
        except Exception as error:  # noqa: BLE001
            self.report({"ERROR"}, f"Could not format material: {error}")
            return {"CANCELLED"}
        message = f"Formatted '{obj.active_material.name}' as a Total War DirectX Shader material."
        if bound_uv2:
            message += f" Its UV2 node now reads '{obj.active_material.node_tree.nodes['UV2'].uv_map}'."
        if apply_standard_view_transform(context.scene):
            message += " View Transform set to Standard so the preview matches the game tonemap."
        self.report({"INFO"}, message)
        return {"FINISHED"}


class TW_OT_set_shader_type(bpy.types.Operator):
    bl_idname = "tw_buildings.set_shader_type"
    bl_label = "Set Shader Type"
    bl_description = "Set the active material's Total War shader type"
    bl_options = {"REGISTER", "UNDO"}

    shader_type: bpy.props.StringProperty(name="Shader Type")

    @classmethod
    def description(cls, context: bpy.types.Context, properties) -> str:
        return SHADER_TYPE_DESCRIPTIONS.get(properties.shader_type, cls.bl_description)

    def execute(self, context: bpy.types.Context):
        material = context.object.active_material if context.object else None
        if material is None:
            self.report({"ERROR"}, "Select an object with an active material first.")
            return {"CANCELLED"}
        try:
            material.tw_shader_type = self.shader_type
        except TypeError:
            self.report({"ERROR"}, f"'{self.shader_type}' is not a known shader type.")
            return {"CANCELLED"}
        return {"FINISHED"}


class TW_OT_sync_preview_light(bpy.types.Operator):
    bl_idname = "tw_buildings.sync_preview_light"
    bl_label = "Sync Preview Light"
    bl_description = (
        "Match the shader preview to the scene's preview light once, now. Only needed when Follow Light "
        "is off, or after swapping which light drives the preview"
    )
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context: bpy.types.Context):
        light = find_preview_light(context.scene)
        if light is None:
            self.report({"ERROR"}, "No light in the scene to sync from.")
            return {"CANCELLED"}
        sync_light(light)
        self.report({"INFO"}, f"Shader preview now follows '{light.name}'.")
        return {"FINISHED"}


class TW_OT_validate(bpy.types.Operator):
    bl_idname = "tw_buildings.validate"
    bl_label = "Validate"
    bl_description = (
        "Check the selected building for problems and list them in the status bar. Export runs the same "
        "checks and refuses on an error, so this is the safe way to see them early"
    )
    bl_options = {"REGISTER"}

    def execute(self, context: bpy.types.Context):
        building = find_building_collection(context)
        if building is None:
            self.report({"ERROR"}, "Select something inside a Building collection first.")
            return {"CANCELLED"}
        try:
            issues = validate_building(building)
        except Exception as error:  # noqa: BLE001
            self.report({"ERROR"}, f"Validation could not complete: {error}")
            return {"CANCELLED"}
        if not issues:
            self.report({"INFO"}, f"'{building.name}' looks good - no problems found.")
            return {"FINISHED"}
        for issue in issues:
            self.report({issue.severity}, issue.message)
        return {"FINISHED"}


def draw_export_targets(layout, targets, singular: str, plural: str) -> None:
    names = [target.name for target in targets]
    if len(names) == 1:
        layout.label(text=f"{singular}: {names[0]}", icon="OUTLINER_COLLECTION")
        return
    box = layout.box()
    box.label(text=f"{len(names)} {plural}", icon="OUTLINER_COLLECTION")
    for name in names:
        box.label(text=name, icon="BLANK1")


# A warning reads the same whichever asset raised it, so a batch has to say which one did.
def report_export_warnings(operator, names: list[str], results: list) -> None:
    for name, result in zip(names, results):
        for warning in result.warnings:
            operator.report({"WARNING"}, f"{name}: {warning}" if len(names) > 1 else warning)


# Whatever exported before the first failure is left on disk - they are complete files, and deleting
# an artist's last good export to tidy up would be worse - but nothing is handed to BOB, so a batch
# never half-builds into working_data.
def export_failure_message(names: list[str], results: list) -> str | None:
    failed = [(name, result) for name, result in zip(names, results) if not result.success]
    if not failed:
        return None
    if len(names) == 1:
        return failed[0][1].message
    return "\n\n".join(f"{name}:\n{result.message}" for name, result in failed)


def export_blocked_headline(count: int, noun: str) -> str:
    if count == 1:
        return f"The {noun} was not exported."
    return f"None of the {count} selected {noun}s were built."


class TW_PG_export_target(bpy.types.PropertyGroup):
    pass


class ExportTargetsMixin:
    # What the artist had selected when the button was pressed, resolved once in invoke() rather
    # than in draw(): the file browser redraws constantly, and reading the Outliner's own selection
    # takes a context override that has no business running inside a draw callback. Names, because
    # an operator property cannot hold a Collection.
    targets: bpy.props.CollectionProperty(type=TW_PG_export_target, options={"HIDDEN"})
    asset_role: str
    asset_noun: str

    def find_one(self, context: bpy.types.Context) -> bpy.types.Collection | None:
        raise NotImplementedError

    def collect_targets(self, context: bpy.types.Context) -> list[bpy.types.Collection] | None:
        try:
            assets = export_batch(context, self.asset_role, self.find_one)
        except MixedSelectionError as error:
            self.report({"ERROR"}, str(error))
            if not bpy.app.background:
                bpy.ops.tw_buildings.export_blocked(
                    "INVOKE_DEFAULT", message=str(error), headline="Nothing was exported."
                )
            return None
        if not assets:
            self.report({"ERROR"}, f"Select something inside a {self.asset_noun.title()} collection first.")
            return None
        self.targets.clear()
        for asset in assets:
            self.targets.add().name = asset.name
        return assets

    # execute() runs on its own whenever the operator is called from a script, so the names invoke()
    # stored are a shortcut rather than the only source.
    def resolve_targets(self, context: bpy.types.Context) -> list[bpy.types.Collection] | None:
        if not self.targets:
            return self.collect_targets(context)
        assets = [bpy.data.collections.get(target.name) for target in self.targets]
        missing = [target.name for target, asset in zip(self.targets, assets) if asset is None]
        if missing:
            self.report({"ERROR"}, f"{', '.join(missing)} is no longer in the scene - select again.")
            return None
        return assets


class BobWaitMixin:
    # Mixin, not an Operator subclass, so Blender never registers it on its own. Shared by the
    # building and skeleton exports: the two hand BOB different work, but waiting for it, reporting
    # it and keeping the scene un-editable while it writes are identical.
    bob_subject = "building"

    def wait_for_bob(self, context: bpy.types.Context, start, export_message: str):
        try:
            self._bob_run = start()
        except BobError as error:
            self.report({"WARNING"}, str(error))
            self.report({"INFO"}, export_message)
            return {"FINISHED"}
        except Exception as error:  # noqa: BLE001
            self.report({"WARNING"}, f"BOB could not be started: {error}")
            self.report({"INFO"}, export_message)
            return {"FINISHED"}

        # A background Blender runs no event loop, so its timer would never fire - wait BOB out there.
        if bpy.app.background or context.window is None:
            return self._report_bob_result(context, self._bob_run.wait())

        self.report({"INFO"}, f"{export_message} BOB is building it now...")
        self._bob_started_at = time.monotonic()
        self._bob_timer = context.window_manager.event_timer_add(0.5, window=context.window)
        context.window.cursor_modal_set("WAIT")
        self._show_progress(context)
        context.window_manager.modal_handler_add(self)
        return {"RUNNING_MODAL"}

    # Every event is swallowed, not passed through: BOB is writing the files this scene was just
    # exported to, so the scene must not be edited underneath it. The timeout in bob.cli is what
    # guarantees this ends.
    def modal(self, context: bpy.types.Context, event: bpy.types.Event):
        if event.type != "TIMER":
            return {"RUNNING_MODAL"}
        try:
            bob_result = self._bob_run.poll()
        except Exception as error:  # noqa: BLE001
            self._stop_progress(context)
            return self._report_bob_result(
                context, BobResult(False, f"Lost track of BOB while it was building: {error}")
            )
        if bob_result is None:
            self._show_progress(context)
            return {"RUNNING_MODAL"}
        self._stop_progress(context)
        return self._report_bob_result(context, bob_result)

    def _show_progress(self, context: bpy.types.Context) -> None:
        elapsed = int(time.monotonic() - self._bob_started_at)
        context.workspace.status_text_set(
            f"{self._bob_run.label} - BOB has been running {elapsed}s. Blender is waiting for it to finish..."
        )

    def _stop_progress(self, context: bpy.types.Context) -> None:
        context.window_manager.event_timer_remove(self._bob_timer)
        context.workspace.status_text_set(None)
        context.window.cursor_modal_restore()

    def _report_bob_result(self, context: bpy.types.Context, bob_result: BobResult):
        self.report({"INFO"} if bob_result.success else {"ERROR"}, bob_result.message)
        if not bpy.app.background:
            bpy.ops.tw_buildings.bob_report(
                "INVOKE_DEFAULT", message=bob_result.message, success=bob_result.success, subject=self.bob_subject
            )
        return {"FINISHED"} if bob_result.success else {"CANCELLED"}


class TW_OT_export_building(ExportTargetsMixin, BobWaitMixin, bpy.types.Operator):
    bl_idname = "tw_buildings.export_building"
    bl_label = "Export Building"
    bl_description = (
        "Validate every selected building, write each out as its own .CS2, and build them into "
        "game-ready files. Select several buildings to build them all in one go. Choose the folder, "
        "and whether to compile and pack, in the dialog"
    )
    bl_options = {"REGISTER"}
    asset_role = "BUILDING"
    asset_noun = "building"

    def find_one(self, context: bpy.types.Context) -> bpy.types.Collection | None:
        return find_building_collection(context)

    directory: bpy.props.StringProperty(subtype="DIR_PATH")
    compile_with_bob: bpy.props.BoolProperty(
        name="Compile With BOB",
        description=(
            "Build the exported file into game-ready files straight away, instead of opening BOB "
            "and clicking Build by hand. Only possible when exporting into the Assembly Kit's "
            "raw_data folder"
        ),
        default=True,
    )
    create_pack: bpy.props.BoolProperty(
        name="Create a Pack",
        description=(
            "Also build a .pack file holding the compiled building and its two database tables, and "
            "put it in the game's data folder so TEd and the game can load it"
        ),
        default=True,
    )
    pack_type: bpy.props.EnumProperty(
        name="Pack Type",
        description="Which kind of pack to build - it decides where the building can be loaded. Both land in the game's data folder",
        items=[
            (rules.RELEASE_PACK_TYPE, "Release", "Loadable in TEd, the Assembly Kit's battlefield editor"),
            (rules.MOD_PACK_TYPE, "Mod", "Loadable in the game itself, alongside other mods"),
        ],
        default=rules.DEFAULT_PACK_TYPE,
    )

    def invoke(self, context: bpy.types.Context, event: bpy.types.Event):
        if self.collect_targets(context) is None:
            return {"CANCELLED"}
        context.window_manager.fileselect_add(self)
        return {"RUNNING_MODAL"}

    def draw(self, context: bpy.types.Context) -> None:
        layout = self.layout
        draw_export_targets(layout, self.targets, "Building", "buildings")
        layout.prop(self, "compile_with_bob")
        pack_row = layout.row()
        pack_row.enabled = self.compile_with_bob
        pack_row.prop(self, "create_pack")
        pack_type_row = layout.row()
        pack_type_row.enabled = self.compile_with_bob and self.create_pack
        pack_type_row.prop(self, "pack_type")

    def execute(self, context: bpy.types.Context):
        buildings = self.resolve_targets(context)
        if buildings is None:
            return {"CANCELLED"}
        if not self.directory:
            self.report({"ERROR"}, "Choose an output folder first.")
            return {"CANCELLED"}

        try:
            assembly_kit_root = get_assembly_kit_root(context)
        except Exception:  # noqa: BLE001
            self.report({"ERROR"}, "Set the Assembly Kit folder in the add-on preferences first.")
            return {"CANCELLED"}

        results = [
            export_building(building, self.directory, assembly_kit_root, context) for building in buildings
        ]
        report_export_warnings(self, [building.name for building in buildings], results)
        blocked = export_failure_message([building.name for building in buildings], results)
        if blocked is not None:
            self.report({"ERROR"}, blocked)
            if not bpy.app.background:
                bpy.ops.tw_buildings.export_blocked(
                    "INVOKE_DEFAULT", message=blocked, headline=export_blocked_headline(len(buildings), "building")
                )
            return {"CANCELLED"}

        message = "\n".join(result.message for result in results)
        cs2_paths = [result.cs2_path for result in results]
        if not self.compile_with_bob:
            self.report({"INFO"}, message)
            return {"FINISHED"}
        return self.wait_for_bob(
            context,
            lambda: start_building_batch(assembly_kit_root, cs2_paths, self.create_pack, self.pack_type),
            message,
        )


# Blender's status bar shows one truncated line, so a list of blocking problems has to be a dialog
# for the artist to read it at all - same reasoning as TW_OT_bob_report.
class TW_OT_export_blocked(bpy.types.Operator):
    bl_idname = "tw_buildings.export_blocked"
    bl_label = "Export"
    bl_options = {"REGISTER", "INTERNAL"}

    message: bpy.props.StringProperty(default="")
    headline: bpy.props.StringProperty(default="The building was not exported.")

    def invoke(self, context: bpy.types.Context, event: bpy.types.Event):
        if context.window:
            context.window.cursor_warp(context.window.width // 2, context.window.height // 2)
        return context.window_manager.invoke_props_dialog(
            self, width=560, title="Export blocked", confirm_text="OK"
        )

    def draw(self, context: bpy.types.Context) -> None:
        layout = self.layout
        layout.label(text=self.headline, icon="ERROR")
        box = layout.box()
        for line in self.message.splitlines():
            box.label(text=line)

    def execute(self, context: bpy.types.Context):
        return {"FINISHED"}


class TW_OT_bob_report(bpy.types.Operator):
    bl_idname = "tw_buildings.bob_report"
    bl_label = "BOB"
    bl_options = {"REGISTER", "INTERNAL"}

    message: bpy.props.StringProperty(default="")
    success: bpy.props.BoolProperty(default=True)
    subject: bpy.props.StringProperty(default="building")

    def invoke(self, context: bpy.types.Context, event: bpy.types.Event):
        if context.window:
            context.window.cursor_warp(context.window.width // 2, context.window.height // 2)
        return context.window_manager.invoke_props_dialog(
            self,
            width=560,
            title="BOB finished" if self.success else "BOB failed",
            confirm_text="OK",
        )

    def draw(self, context: bpy.types.Context) -> None:
        layout = self.layout
        layout.label(
            text=f"The {self.subject} is built and ready." if self.success else "The build did not finish.",
            icon="CHECKMARK" if self.success else "ERROR",
        )
        box = layout.box()
        for line in self.message.splitlines():
            box.label(text=line)

    def execute(self, context: bpy.types.Context):
        return {"FINISHED"}


class TW_OT_import_report(bpy.types.Operator):
    bl_idname = "tw_buildings.import_report"
    bl_label = "Import Report"
    bl_description = "Show the notes from the last import again"
    bl_options = {"REGISTER"}

    messages: list[str] = []

    def invoke(self, context: bpy.types.Context, event: bpy.types.Event):
        if context.window:
            context.window.cursor_warp(context.window.width // 2, context.window.height // 2)
        return context.window_manager.invoke_props_dialog(self, width=500, confirm_text="OK")

    def draw(self, context: bpy.types.Context):
        layout = self.layout
        layout.label(text="The import finished, with these notes:", icon="INFO")
        box = layout.box()
        for msg in TW_OT_import_report.messages:
            box.label(text=msg, icon="BLANK1")

    def execute(self, context: bpy.types.Context):
        return {"FINISHED"}


# The one import path. Every supported file type arrives through this operator, and
# importer.file_router decides what the file actually is from its own name and contents - the same
# reasoning that made a skeleton and a building share one entry in Phase 4, extended to the two
# unit formats.
#
# Each ;-separated pattern has to stay at 15 characters or shorter: Blender copies it into a
# char[16] before matching (BLI_path_extension_check_glob), so "*.rigid_model_v2" silently became
# "*.rigid_model_v" and the file browser listed nothing at all.
MAX_FILTER_GLOB_PATTERN = 15
IMPORT_FILTER_GLOB = "*.cs2;*.CS2;*.cs2.parsed;*.anim;*.rigid_model*;*.variantmesh*"


class TW_OT_import_file(bpy.types.Operator, ImportHelper):
    bl_idname = "tw_buildings.import_file"
    bl_label = "Import Total War File"
    bl_description = (
        "Import a Total War file - a .cs2 building, skeleton or animation clip, a .cs2.parsed "
        "building tech file, a compiled .anim clip, a compiled .rigid_model_v2 model, or a "
        ".variantmeshdefinition assembly. Which one it is comes from the file itself, and the "
        "workflow switches to match"
    )
    bl_options = {"REGISTER", "UNDO"}

    filename_ext = ".cs2"
    filter_glob: bpy.props.StringProperty(default=IMPORT_FILTER_GLOB, options={"HIDDEN"})

    def execute(self, context: bpy.types.Context):
        if not self.filepath:
            self.report({"ERROR"}, "No file selected.")
            return {"CANCELLED"}

        try:
            collection, warnings, kind = import_file(self.filepath, context)
        except UnsupportedFileError as error:
            self.report({"ERROR"}, str(error))
            return {"CANCELLED"}
        except Exception as error:  # noqa: BLE001
            self.report({"ERROR"}, f"Could not import file: {error}")
            return {"CANCELLED"}

        for message in warnings:
            self.report({severity_of(message)}, message)
        problems = [message for message in warnings if severity_of(message) != "INFO"]

        # A weighted model whose skeleton could not be found still imports - it just cannot animate
        # or export until one is bound, so the artist is told loudly rather than in the log.
        unbound = models_needing_a_skeleton(collection)
        if unbound:
            names = ", ".join(f"'{model.name}'" for model in unbound)
            self.report(
                {"ERROR"},
                f"No skeleton was found for {names}, so it was imported without one - its vertex "
                "groups are named bone_<index> and it cannot be animated or exported until a "
                "matching skeleton is in the scene. See the warnings above for where this looked.",
            )

        self.report({"INFO"}, f"Imported '{collection.name}' and switched to the {kind.title()} workflow.")
        if problems:
            TW_OT_import_report.messages = problems
            bpy.ops.tw_buildings.import_report("INVOKE_DEFAULT")
        return {"FINISHED"}


def menu_func_import(self, context):
    self.layout.operator(TW_OT_import_file.bl_idname, text="Total War (.cs2, .anim, .rigid_model_v2, ...)")


CLASSES = (
    TW_PG_export_target,
    TW_OT_new_building,
    TW_OT_new_piece,
    TW_OT_new_destruct_level,
    TW_OT_add_destruct_collection,
    TW_OT_add_building_collection,
    TW_OT_add_display_collection,
    TW_OT_new_arrow_emitter,
    TW_OT_new_flag,
    TW_OT_new_marker_line,
    TW_OT_reset_marker_line_direction,
    TW_OT_invert_marker_line_direction,
    TW_OT_make_material,
    TW_OT_set_shader_type,
    TW_OT_sync_preview_light,
    TW_OT_validate,
    TW_OT_export_building,
    TW_OT_export_blocked,
    TW_OT_bob_report,
    TW_OT_import_report,
    TW_OT_import_file,
)


def register() -> None:
    for cls in CLASSES:
        bpy.utils.register_class(cls)
    bpy.types.TOPBAR_MT_file_import.append(menu_func_import)


def unregister() -> None:
    bpy.types.TOPBAR_MT_file_import.remove(menu_func_import)
    for cls in reversed(CLASSES):
        bpy.utils.unregister_class(cls)

