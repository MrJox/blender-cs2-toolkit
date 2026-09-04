bl_info = {
    "name": "Blender CS2 All-in-One Kit",
    "author": "Blender CS2 All-in-One Kit Add-on",
    "version": (0, 1, 0),
    "blender": (4, 0, 0),
    "location": "View3D > Sidebar > Total War",
    "description": "Create and export Total War / CS2 battlefield buildings and units as .CS2 files",
    "category": "Import-Export",
}

import os
import sys

import bpy

# This add-on's sub-packages (binary/, scene_model/, naming/, ...) import each other with plain
# top-level names (e.g. "from binary import cs2_structures") so the same code also runs unmodified
# as a standalone pure-Python library outside Blender. Blender only puts the add-ons root directory
# on sys.path, not this add-on's own folder, so it has to be added here.
_ADDON_DIR = os.path.dirname(__file__)
if _ADDON_DIR not in sys.path:
    sys.path.insert(0, _ADDON_DIR)

from props import properties
from ui import (
    animation_operators,
    animation_panels,
    operators,
    panels,
    unit_operators,
    unit_panels,
    vegetation_panels,
)


@bpy.app.handlers.persistent
def _follow_preview_light(scene, depsgraph=None) -> None:
    # Cheap by construction: the light parameters live on the one shared node tree, so this reads a
    # single lamp and writes at most four values, whatever the scene contains.
    if not getattr(scene, "tw_live_preview_light", False):
        return
    from materials.fx_nodegroup import find_preview_light, sync_light

    sync_light(find_preview_light(scene))


def register() -> None:
    properties.set_addon_package_name(__name__)
    properties.register()
    operators.register()
    unit_operators.register()
    animation_operators.register()
    panels.register()
    unit_panels.register()
    animation_panels.register()
    vegetation_panels.register()
    if _follow_preview_light not in bpy.app.handlers.depsgraph_update_post:
        bpy.app.handlers.depsgraph_update_post.append(_follow_preview_light)


def unregister() -> None:
    if _follow_preview_light in bpy.app.handlers.depsgraph_update_post:
        bpy.app.handlers.depsgraph_update_post.remove(_follow_preview_light)
    vegetation_panels.unregister()
    animation_panels.unregister()
    unit_panels.unregister()
    panels.unregister()
    animation_operators.unregister()
    unit_operators.unregister()
    operators.unregister()
    properties.unregister()
