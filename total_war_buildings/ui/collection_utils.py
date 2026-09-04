import bpy


def _iter_collections(root: bpy.types.Collection):
    yield root
    for child in root.children:
        yield from _iter_collections(child)


def _build_parent_map(scene: bpy.types.Scene) -> dict:
    parent_map = {}
    for collection in _iter_collections(scene.collection):
        for child in collection.children:
            parent_map[child] = collection
    return parent_map


def get_active_collection(context: bpy.types.Context) -> bpy.types.Collection | None:
    active_layer_collection = context.view_layer.active_layer_collection
    return active_layer_collection.collection if active_layer_collection else None


def _find_ancestor_with_role(
    context: bpy.types.Context, start: bpy.types.Collection | None, role: str
) -> bpy.types.Collection | None:
    if start is None:
        return None
    parent_map = _build_parent_map(context.scene)
    current = start
    while current is not None:
        if current.tw_role == role:
            return current
        current = parent_map.get(current)
    return None


def find_collection_with_role(
    context: bpy.types.Context, role: str, start: bpy.types.Collection | None = None
) -> bpy.types.Collection | None:
    if start is None:
        start = get_active_collection(context)
    return _find_ancestor_with_role(context, start, role)


def find_building_collection(context: bpy.types.Context) -> bpy.types.Collection | None:
    return find_collection_with_role(context, "BUILDING")


def _find_role_from_selection(context: bpy.types.Context, role: str) -> bpy.types.Collection | None:
    # An Outliner click on an object syncs the active collection to it, but a viewport click does
    # not - so without this fallback the panels, which resolve the same role through the selected
    # object's own collections, offer buttons that then refuse to act.
    found = find_collection_with_role(context, role)
    if found is not None:
        return found
    obj = context.object
    for collection in obj.users_collection if obj is not None else ():
        found = find_collection_with_role(context, role, collection)
        if found is not None:
            return found
    return None


def find_unit_collection(context: bpy.types.Context) -> bpy.types.Collection | None:
    return _find_role_from_selection(context, "UNIT")


def find_skeleton_collection(context: bpy.types.Context) -> bpy.types.Collection | None:
    return _find_role_from_selection(context, "SKELETON")


def find_piece_collection(
    context: bpy.types.Context, start: bpy.types.Collection | None = None
) -> bpy.types.Collection | None:
    return find_collection_with_role(context, "PIECE", start)


def get_object_collection_role(obj: bpy.types.Object) -> str:
    for collection in obj.users_collection:
        if collection.tw_role != "NONE":
            return collection.tw_role
    return "NONE"


ASSET_ROLES = ("BUILDING", "UNIT", "SKELETON")

_ASSET_ROLE_NAMES = {
    "BUILDING": ("building", "buildings"),
    "UNIT": ("unit asset", "unit assets"),
    "SKELETON": ("skeleton", "skeletons"),
}


class MixedSelectionError(Exception):
    pass


def _outliner_collections(context: bpy.types.Context) -> list[bpy.types.Collection]:
    # A collection carries its selection nowhere but the Outliner's own context, so reading it takes
    # an area override. A background Blender never builds the Outliner's tree and raises here, which
    # is why every caller treats an empty answer as "fall back to the active collection".
    screen = getattr(context, "screen", None)
    for area in screen.areas if screen is not None else ():
        if area.type != "OUTLINER":
            continue
        try:
            with context.temp_override(area=area):
                selected = list(context.selected_ids)
        except (AttributeError, TypeError, RuntimeError):
            continue
        collections = [block for block in selected if isinstance(block, bpy.types.Collection)]
        if collections:
            return collections
    return []


def _selection_roots(context: bpy.types.Context) -> list[bpy.types.Collection]:
    # Clicking a collection in the Outliner deselects the objects, so a live object selection is
    # always the more recent of the two - reading the Outliner as well would fold a left-over
    # collection highlight into the batch. Same ground truth panels.object_section_visible rests on.
    selected = getattr(context, "selected_objects", None) or []
    if selected:
        return [collection for obj in selected for collection in obj.users_collection]
    return _outliner_collections(context)


def selected_assets(context: bpy.types.Context) -> dict[str, list[bpy.types.Collection]]:
    parent_map = _build_parent_map(context.scene)
    found: dict[str, list[bpy.types.Collection]] = {}
    for start in _selection_roots(context):
        current = start
        while current is not None and current.tw_role not in ASSET_ROLES:
            current = parent_map.get(current)
        if current is None:
            continue
        assets = found.setdefault(current.tw_role, [])
        if current not in assets:
            assets.append(current)
    return found


def _describe(role: str, count: int) -> str:
    singular, plural = _ASSET_ROLE_NAMES[role]
    return f"{count} {singular if count == 1 else plural}"


def export_batch(context: bpy.types.Context, role: str, fallback) -> list[bpy.types.Collection]:
    found = selected_assets(context)
    if any(other != role for other in found):
        selection = ", ".join(_describe(other, len(assets)) for other, assets in sorted(found.items()))
        raise MixedSelectionError(
            f"One export builds one kind of asset, and this selection holds {selection}.\n"
            f"Select only the {_ASSET_ROLE_NAMES[role][1]} you want built and export again."
        )
    assets = found.get(role, [])
    if assets:
        return assets
    single = fallback(context)
    return [single] if single is not None else []
