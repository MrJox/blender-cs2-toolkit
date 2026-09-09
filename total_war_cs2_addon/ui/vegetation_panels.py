import bpy

from .collection_utils import get_object_collection_role
from .panels import WorkflowGatedPanel, _draw_wrapped_text, active_role_collection, object_section_visible


def vegetation_object_box(context: bpy.types.Context, on_object: bool) -> bpy.types.Object | None:
    obj = context.object
    if not on_object or obj is None or obj.type != "MESH":
        return None
    return obj if get_object_collection_role(obj) == "VEGETATION_DISPLAY" else None


class TW_PT_vegetation_setup(WorkflowGatedPanel, bpy.types.Panel):
    bl_label = "Vegetation Setup"
    bl_idname = "TW_PT_vegetation_setup"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "Total War"
    bl_order = 1
    workflows = frozenset({"VEGETATION"})

    def draw(self, context: bpy.types.Context) -> None:
        layout = self.layout
        layout.operator("tw_buildings.new_vegetation", icon="ADD")

        on_object = object_section_visible(context)
        model = active_role_collection(context, on_object, "VEGETATION")
        if model is None:
            _draw_wrapped_text(
                layout,
                "Start with New Vegetation Model - one model is one exported file. Bring an existing "
                "one in with File > Import instead.",
            )
            return

        box = layout.box()
        box.label(text=model.name, icon="OUTLINER_COLLECTION")

        obj = vegetation_object_box(context, on_object)
        if obj is None:
            return
        box = layout.box()
        box.label(text=obj.name, icon="MESH_DATA")
        box.prop(obj, "tw_vegetation_lod")


CLASSES = (TW_PT_vegetation_setup,)


def register() -> None:
    for cls in CLASSES:
        bpy.utils.register_class(cls)


def unregister() -> None:
    for cls in reversed(CLASSES):
        bpy.utils.unregister_class(cls)
