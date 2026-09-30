import bpy

from .panels import WorkflowGatedPanel


class TW_PT_textures(WorkflowGatedPanel, bpy.types.Panel):
    # Its own workflow rather than always-visible: the sidebar's workflow switcher is already this
    # add-on's top-level mode selector for every other file-on-disk utility, so Texture gets the
    # same treatment instead of being the one panel that ignores it. No scene collections belong to
    # this workflow, so unlike Building/Unit/Vegetation it has no Materials/Validation/Export panel.
    bl_label = "Textures"
    bl_idname = "TW_PT_textures"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "Total War"
    bl_order = 1
    workflows = frozenset({"TEXTURE"})

    def draw(self, context: bpy.types.Context) -> None:
        layout = self.layout
        layout.label(text="Working data -> raw data", icon="TRIA_DOWN")
        layout.operator("tw_buildings.decompile_textures", icon="TEXTURE")

        layout.separator()
        layout.label(text="Raw data -> working data", icon="TRIA_UP")
        layout.operator("tw_buildings.compile_textures", icon="TEXTURE")


CLASSES = (TW_PT_textures,)


def register() -> None:
    for cls in CLASSES:
        bpy.utils.register_class(cls)


def unregister() -> None:
    for cls in reversed(CLASSES):
        bpy.utils.unregister_class(cls)
