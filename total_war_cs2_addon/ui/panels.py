import textwrap

import bpy

from props.properties import (
    TW_ROLE_LABELS,
    TW_ROLE_DESCRIPTIONS,
    DAMAGE_PARENT_DESCRIPTION,
    NESTED_DISPLAY_ROLES,
)
from extraction.animation import object_keyframe_frames
from .collection_utils import (
    get_active_collection,
    find_collection_with_role,
    find_piece_collection,
    get_object_collection_role,
)
from materials.shader_types import SHADER_TYPE_LABELS, shader_types_for_workflow
from .operators import DESTRUCT_COLLECTION_ROLES, BUILDING_COLLECTION_ROLES, DISPLAY_COLLECTION_ROLES

# Workflows selectable in the switcher that no panel set answers to, so the sidebar would otherwise
# go silently blank. Empty since Phase 6 gave Skeletal Animation its own panel; the guard stays for
# whichever workflow is added next.
WORKFLOWS_WITHOUT_PANELS = set()


class WorkflowGatedPanel:
    # Mixin, not a Panel subclass, so Blender never tries to register it on its own.
    # Sidebar order is bl_order first, registration order second, so every panel in the category
    # sets bl_order explicitly: the unit and skeleton panels register from a later module than
    # this one and would otherwise always sort below Export. 0 workflow switch, 1 the per-workflow
    # setup panel, 2 materials, 3 validation, 4 export.
    workflows = frozenset()

    @classmethod
    def poll(cls, context: bpy.types.Context) -> bool:
        return context.scene.tw_workflow in cls.workflows


def marker_line_direction(obj: bpy.types.Object):
    # Mirrors extraction._extract_ef_line_geometry so the panel can never disagree with the
    # exported EFLine_Direction: read off the pointer when there is one, else the MaxScript's own
    # perpendicular. World space, since that's what gets exported.
    points = [obj.matrix_world @ vertex.co for vertex in obj.data.vertices]
    if len(points) == 4:
        base, tip = points[1], points[3]
    elif len(points) == 2:
        start, end = points
        base = start
        tip = (start[0] - (end[1] - start[1]), start[1] + (end[0] - start[0]), start[2])
    else:
        return None
    dx, dy = tip[0] - base[0], tip[1] - base[1]
    length = (dx * dx + dy * dy) ** 0.5
    if length == 0.0:
        return None
    return (dx / length, dy / length, 0.0)


def draw_animation_keyframe_summary(layout: bpy.types.UILayout, obj: bpy.types.Object) -> None:
    frames = object_keyframe_frames(obj)
    if not frames:
        layout.label(text="No keyframes - exports as a static mesh", icon="INFO")
    else:
        layout.label(text=f"Keyframes: {len(frames)} (frame {frames[0]} - {frames[-1]})", icon="ANIM")


def draw_shader_type_choice(layout: bpy.types.UILayout, context: bpy.types.Context, material: bpy.types.Material) -> None:
    current = material.tw_shader_type
    allowed = [identifier for identifier, _label, _description in shader_types_for_workflow(context.scene.tw_workflow)]
    row = layout.row()
    row.menu("TW_MT_shader_types", text=SHADER_TYPE_LABELS.get(current, current), icon="NODE_MATERIAL")
    if current not in allowed:
        layout.label(text=f"{SHADER_TYPE_LABELS.get(current, current)} is not used by this workflow", icon="ERROR")


def draw_marker_line_direction(layout: bpy.types.UILayout, obj: bpy.types.Object) -> None:
    direction = marker_line_direction(obj)
    if direction is None:
        layout.label(text="Direction: needs a valid line", icon="ERROR")
        layout.operator("tw_buildings.reset_marker_line_direction", icon="FILE_REFRESH")
        return
    layout.label(text=f"Direction: {direction[0]:.3f}, {direction[1]:.3f}, {direction[2]:.3f}")
    row = layout.row(align=True)
    row.operator("tw_buildings.invert_marker_line_direction", icon="ARROW_LEFTRIGHT")
    row.operator("tw_buildings.reset_marker_line_direction", icon="FILE_REFRESH")


def object_section_visible(context: bpy.types.Context) -> bool:
    # "Is the artist looking at this object" is answered by whether it is still selected. Clicking
    # any collection deselects the objects - confirmed by the user in a real Blender, which is the
    # only way to establish it: assigning the properties in a script is not equivalent to a click.
    # That one fact replaces the draw-time recency tracking this used to do, and it is strictly
    # better: the two cases recency could not separate - clicking the collection an object is
    # already in, which changes no state at all, and clicking the object's own collection - both
    # deselect, so both now hide the box. Selection also survives a redraw, so there is no module
    # state and no ordering to get wrong.
    obj = context.object
    if obj is None:
        return False
    try:
        return obj.select_get()
    except RuntimeError:
        # An object outside the view layer (its collection excluded or hidden) cannot report
        # selection; it is not what the artist is looking at either.
        return False


def active_role_collection(context: bpy.types.Context, on_object: bool, role: str) -> bpy.types.Collection | None:
    # Reuse object_section_visible's answer rather than the active collection alone: a
    # collection click must not leave a different piece's (or skeleton's) box behind.
    obj = context.object
    if on_object and obj is not None:
        for collection in obj.users_collection:
            found = find_collection_with_role(context, role, collection)
            if found is not None:
                return found
    return find_collection_with_role(context, role)


def active_piece_collection(context: bpy.types.Context, on_object: bool) -> bpy.types.Collection | None:
    return active_role_collection(context, on_object, "PIECE")


def _draw_wrapped_text(layout: bpy.types.UILayout, text: str, width: int = 46) -> None:
    # UILayout.label() doesn't wrap text on its own, so split it into lines ourselves. 46 chars is
    # a rough fit for the default Properties editor sidebar width - not exact, but close enough
    # that a resize won't make it look broken.
    col = layout.column(align=True)
    for line in textwrap.wrap(text, width=width):
        col.label(text=line)


class TW_MT_add_destruct_feature(bpy.types.Menu):
    bl_label = "Add..."
    bl_idname = "TW_MT_add_destruct_feature"

    def draw(self, context: bpy.types.Context) -> None:
        layout = self.layout
        for role, (name, _hint) in DESTRUCT_COLLECTION_ROLES.items():
            layout.operator("tw_buildings.add_destruct_collection", text=name).role = role


class TW_MT_add_building_feature(bpy.types.Menu):
    bl_label = "Add..."
    bl_idname = "TW_MT_add_building_feature"

    def draw(self, context: bpy.types.Context) -> None:
        layout = self.layout
        for role, (name, _hint) in BUILDING_COLLECTION_ROLES.items():
            layout.operator("tw_buildings.add_building_collection", text=name).role = role


class TW_MT_add_display_feature(bpy.types.Menu):
    bl_label = "Add..."
    bl_idname = "TW_MT_add_display_feature"

    def draw(self, context: bpy.types.Context) -> None:
        layout = self.layout
        for role, (name, _hint) in DISPLAY_COLLECTION_ROLES.items():
            layout.operator("tw_buildings.add_display_collection", text=name).role = role


class TW_PT_workflow(bpy.types.Panel):
    # The one panel that is never gated - it is how the gate itself is set.
    bl_label = "Workflow"
    bl_idname = "TW_PT_workflow"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "Total War"
    bl_order = 0

    def draw(self, context: bpy.types.Context) -> None:
        layout = self.layout
        layout.prop(context.scene, "tw_workflow", text="")
        if context.scene.tw_workflow in WORKFLOWS_WITHOUT_PANELS:
            layout.label(text="Not implemented yet", icon="INFO")


class TW_MT_shader_types(bpy.types.Menu):
    bl_label = "Shader Type"
    bl_idname = "TW_MT_shader_types"

    def draw(self, context: bpy.types.Context) -> None:
        layout = self.layout
        for identifier, label, _description in shader_types_for_workflow(context.scene.tw_workflow):
            layout.operator("tw_buildings.set_shader_type", text=label).shader_type = identifier


class TW_PT_building_setup(WorkflowGatedPanel, bpy.types.Panel):
    bl_label = "Building Setup"
    bl_idname = "TW_PT_building_setup"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "Total War"
    bl_order = 1
    workflows = frozenset({"BUILDING"})

    def draw(self, context: bpy.types.Context) -> None:
        layout = self.layout
        layout.operator("tw_buildings.new_building", icon="ADD")

        # Each Add button appears only where it can act, the same rule the Unit panel follows:
        # New Destruct Level is meaningless before there is a Piece to put one in.
        active = get_active_collection(context)
        on_object = object_section_visible(context)
        building = active_role_collection(context, on_object, "BUILDING")
        piece = active_piece_collection(context, on_object)

        if building is None:
            _draw_wrapped_text(
                layout,
                "Start with New Building, then give it a Piece and a Destruct Level. Select any "
                "collection to read what it is for under Properties > Collection > Total War Info.",
            )
        if building is not None:
            layout.operator("tw_buildings.new_piece", icon="ADD")
        if piece is not None:
            layout.operator("tw_buildings.new_destruct_level", icon="ADD")

        if active is not None and active.tw_role == "BUILDING":
            box = layout.box()
            box.label(text=active.name, icon="OUTLINER_COLLECTION")
            box.prop(active, "tw_asset_type")
            box.menu("TW_MT_add_building_feature", icon="ADD")

        if piece is not None:
            box = layout.box()
            box.label(text=piece.name, icon="OUTLINER_COLLECTION")
            box.prop(piece, "tw_damage_parent")

        if active is not None and active.tw_role == "DESTRUCT":
            box = layout.box()
            box.label(text=active.name, icon="OUTLINER_COLLECTION")
            box.menu("TW_MT_add_destruct_feature", icon="ADD")

        if active is not None and active.tw_role == "ARROW_EMITTERS":
            box = layout.box()
            box.label(text=active.name, icon="OUTLINER_COLLECTION")
            box.operator("tw_buildings.new_arrow_emitter", icon="ADD")

        if active is not None and active.tw_role == "DISPLAY":
            box = layout.box()
            box.label(text=active.name, icon="OUTLINER_COLLECTION")
            box.menu("TW_MT_add_display_feature", icon="ADD")

        if active is not None and active.tw_role == "FLAG":
            box = layout.box()
            box.label(text=active.name, icon="OUTLINER_COLLECTION")
            box.operator("tw_buildings.new_flag", icon="ADD")

        if active is not None and active.tw_role in ("EF_LINES", "DOCKING_LINES"):
            box = layout.box()
            box.label(text=active.name, icon="OUTLINER_COLLECTION")
            box.operator("tw_buildings.new_marker_line", icon="ADD")

        obj = context.object
        if on_object:
            role = get_object_collection_role(obj)
            if obj.type == "MESH" and (role == "DISPLAY" or role in NESTED_DISPLAY_ROLES):
                box = layout.box()
                box.label(text=obj.name)
                box.prop(obj, "tw_lod_index")
            elif obj.type == "MESH" and role == "COLLISION":
                box = layout.box()
                box.label(text=obj.name)
                box.prop(obj, "tw_collision_type")
            elif obj.type == "MESH" and role == "PLATFORM":
                box = layout.box()
                box.label(text=obj.name)
                box.prop(obj, "tw_platform_type")
            elif role == "FILE_REFERENCE":
                box = layout.box()
                box.label(text=obj.name)
                box.prop(obj, "tw_file_reference_name")
            elif obj.type == "CURVE" and role == "LINES":
                box = layout.box()
                box.label(text=obj.name)
                box.prop(obj, "tw_line_type")
            elif obj.type == "MESH" and role == "EF_LINES":
                box = layout.box()
                box.label(text=obj.name)
                box.prop(obj, "tw_efline_action")
                draw_marker_line_direction(box, obj)
            elif obj.type == "MESH" and role == "DOCKING_LINES":
                box = layout.box()
                box.label(text=obj.name)
                draw_marker_line_direction(box, obj)
            elif obj.type == "MESH" and role == "GATE_ANIMATION":
                box = layout.box()
                box.label(text=obj.name)
                box.prop(obj, "tw_gate_anim_kind")
                draw_animation_keyframe_summary(box, obj)
            elif obj.type == "MESH" and role == "DESTRUCTION_ANIM":
                box = layout.box()
                box.label(text=obj.name)
                draw_animation_keyframe_summary(box, obj)


class TW_PT_collection_info(bpy.types.Panel):
    # Blender's Outliner tree has no public API for custom per-item hover tooltips on plain
    # collections (only Asset Browser entries get one, via asset_data.description) - this
    # Collection Properties tab panel is the closest equivalent: click any Total War collection
    # anywhere (including from the Outliner) and see what it's for, persistently rather than on
    # hover. Shares its text with the "Add..." menu tooltips via props.properties.TW_ROLE_*.
    bl_label = "Total War Info"
    bl_idname = "TW_PT_collection_info"
    bl_space_type = "PROPERTIES"
    bl_region_type = "WINDOW"
    bl_context = "collection"

    @classmethod
    def poll(cls, context: bpy.types.Context) -> bool:
        collection = context.collection
        return collection is not None and collection.tw_role != "NONE"

    def draw(self, context: bpy.types.Context) -> None:
        layout = self.layout
        role = context.collection.tw_role
        layout.label(text=TW_ROLE_LABELS.get(role, role), icon="INFO")
        description = TW_ROLE_DESCRIPTIONS.get(role, "")
        if description:
            _draw_wrapped_text(layout, description)

        piece = find_piece_collection(context, context.collection)
        if piece is not None:
            layout.separator()
            if piece is not context.collection:
                layout.label(text=piece.name, icon="OUTLINER_COLLECTION")
            layout.prop(piece, "tw_damage_parent")
            _draw_wrapped_text(layout, DAMAGE_PARENT_DESCRIPTION)


class TW_PT_materials(WorkflowGatedPanel, bpy.types.Panel):
    bl_label = "Materials"
    bl_idname = "TW_PT_materials"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "Total War"
    bl_order = 2
    workflows = frozenset({"BUILDING", "UNIT", "VEGETATION"})

    def draw(self, context: bpy.types.Context) -> None:
        layout = self.layout
        layout.operator("tw_buildings.make_material", icon="MATERIAL")

        obj = context.object
        if obj is not None and obj.active_material is not None:
            draw_shader_type_choice(layout, context, obj.active_material)
            layout.prop(obj.active_material, "tw_alpha_mode")
        else:
            layout.label(text="Select a mesh with a material to set its shader", icon="INFO")

        # The shader carries its own light, so Blender's lamps do not affect it on their own.
        box = layout.box()
        box.label(text="Shader Preview Light")
        _draw_wrapped_text(box, "The game shader lights itself, so Blender's own lamps never reach it.")
        box.prop(context.scene, "tw_preview_light", text="")
        box.prop(context.scene, "tw_live_preview_light")
        box.operator("tw_buildings.sync_preview_light", icon="LIGHT_SUN")


class TW_PT_validation(WorkflowGatedPanel, bpy.types.Panel):
    bl_label = "Validation"
    bl_idname = "TW_PT_validation"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "Total War"
    bl_order = 3
    workflows = frozenset({"BUILDING", "UNIT", "SKELETON", "SKELETAL_ANIMATION"})

    def draw(self, context: bpy.types.Context) -> None:
        if context.scene.tw_workflow == "SKELETON":
            self.layout.operator("tw_buildings.validate_skeleton", icon="CHECKMARK")
            return
        if context.scene.tw_workflow == "UNIT":
            self.layout.operator("tw_buildings.validate_unit", icon="CHECKMARK")
            return
        if context.scene.tw_workflow == "SKELETAL_ANIMATION":
            self.layout.operator("tw_buildings.validate_animation", icon="CHECKMARK")
            return
        self.layout.operator("tw_buildings.validate", icon="CHECKMARK")


class TW_PT_export(WorkflowGatedPanel, bpy.types.Panel):
    bl_label = "Export"
    bl_idname = "TW_PT_export"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "Total War"
    bl_order = 4
    workflows = frozenset({"BUILDING", "UNIT", "SKELETON", "SKELETAL_ANIMATION"})

    def draw(self, context: bpy.types.Context) -> None:
        if context.scene.tw_workflow == "SKELETON":
            self.layout.operator("tw_buildings.export_skeleton", icon="EXPORT")
            return
        if context.scene.tw_workflow == "UNIT":
            self.layout.operator("tw_buildings.export_units", icon="EXPORT")
            return
        if context.scene.tw_workflow == "SKELETAL_ANIMATION":
            self.layout.operator("tw_buildings.export_animation", icon="EXPORT")
            return
        self.layout.operator("tw_buildings.export_building", icon="EXPORT")


CLASSES = (
    TW_PT_workflow,
    TW_MT_shader_types,
    TW_MT_add_destruct_feature,
    TW_MT_add_building_feature,
    TW_MT_add_display_feature,
    TW_PT_building_setup,
    TW_PT_collection_info,
    TW_PT_materials,
    TW_PT_validation,
    TW_PT_export,
)


def register() -> None:
    for cls in CLASSES:
        bpy.utils.register_class(cls)


def unregister() -> None:
    for cls in reversed(CLASSES):
        bpy.utils.unregister_class(cls)
