from dataclasses import dataclass, field
from pathlib import Path
from xml.etree import ElementTree

import bpy

from .rigid_model_v2_importer import import_rigid_model_v2


class VmdError(Exception):
    pass


@dataclass
class VmdEntry:
    model_path: Path
    slot_name: str
    attach_point: str


@dataclass
class VmdSlot:
    name: str
    attach_point: str
    entries: list[VmdEntry] = field(default_factory=list)


def working_data_root(path: Path) -> Path | None:
    # Every path inside a .variantmeshdefinition is rooted at the Assembly Kit's working_data
    # folder, and the definitions themselves live under it.
    for parent in path.parents:
        if parent.name.lower() == "working_data":
            return parent
    return None


def resolve_asset_path(root: Path, reference: str) -> Path | None:
    # References mix / and \ separators and are cased however the artist typed them, so each
    # component is matched case-insensitively against what is actually on disk.
    current = root
    parts = [part for part in reference.replace("\\", "/").split("/") if part]
    for index, part in enumerate(parts):
        candidate = current / part
        if candidate.exists():
            current = candidate
            continue
        wanted = part.lower()
        try:
            match = next((child for child in current.iterdir() if child.name.lower() == wanted), None)
        except OSError:
            return None
        if match is None:
            return None
        current = match
        if index == len(parts) - 1 and not current.is_file():
            return None
    return current if current.is_file() else None


def _slot_entries(element: ElementTree.Element, root: Path, seen: set[Path], warnings: list[str]) -> list[VmdSlot]:
    slots: list[VmdSlot] = []
    for slot_element in element:
        if slot_element.tag.upper() != "SLOT":
            continue
        slot = VmdSlot(
            name=slot_element.get("name", ""),
            attach_point=slot_element.get("attach_point", ""),
        )
        for child in slot_element:
            tag = child.tag.upper()
            if tag == "VARIANT_MESH":
                model = child.get("model")
                if model:
                    resolved = resolve_asset_path(root, model)
                    if resolved is None:
                        warnings.append(f"Slot '{slot.name}' references '{model}', which is not on disk.")
                    else:
                        slot.entries.append(
                            VmdEntry(model_path=resolved, slot_name=slot.name, attach_point=slot.attach_point)
                        )
                for nested in _slot_entries(child, root, seen, warnings):
                    slots.append(nested)
            elif tag == "VARIANT_MESH_REFERENCE":
                definition = child.get("definition", "")
                resolved = resolve_asset_path(root, definition)
                if resolved is None:
                    warnings.append(f"Slot '{slot.name}' includes '{definition}', which is not on disk.")
                    continue
                if resolved in seen:
                    continue
                seen.add(resolved)
                for nested in read_vmd(resolved, root, seen, warnings):
                    # An included definition's own slots inherit the including slot's attach point
                    # when they declare none of their own - that is how a weapon definition full of
                    # sword variants lands on weapon_02.
                    if not nested.attach_point and slot.attach_point:
                        nested.attach_point = slot.attach_point
                        for entry in nested.entries:
                            entry.attach_point = slot.attach_point
                    slots.append(nested)
        slots.append(slot)
    return slots


def read_vmd(path: Path, root: Path, seen: set[Path], warnings: list[str]) -> list[VmdSlot]:
    try:
        tree = ElementTree.fromstring(path.read_text(encoding="utf-8", errors="replace"))
    except ElementTree.ParseError as error:
        raise VmdError(f"'{path.name}' is not valid XML: {error}") from error
    return _slot_entries(tree, root, seen, warnings)


def _attachment_points_in(collection: bpy.types.Collection) -> dict[str, bpy.types.Object]:
    return {obj.tw_attachment_point_name: obj for obj in collection.all_objects if obj.tw_attachment_point_name}


def import_vmd(filepath: str, context: bpy.types.Context) -> tuple[bpy.types.Collection, list[str]]:
    path = Path(bpy.path.abspath(filepath))
    root = working_data_root(path)
    if root is None:
        raise VmdError(
            f"'{path.name}' is not inside the Assembly Kit's working_data folder, so the models it "
            "references cannot be found."
        )

    warnings: list[str] = []
    slots = read_vmd(path, root, {path}, warnings)

    # The assembly itself is not an exportable asset - it is several of them, one per referenced
    # file - so it is a plain grouping collection, and so are its slots.
    unit_collection = bpy.data.collections.new(path.stem)
    context.scene.collection.children.link(unit_collection)

    attachment_points: dict[str, bpy.types.Object] = {}
    pending: list[tuple[bpy.types.Collection, str]] = []
    for slot in slots:
        if not slot.entries:
            continue
        slot_collection = bpy.data.collections.new(slot.name or "slot")
        unit_collection.children.link(slot_collection)
        for index, entry in enumerate(slot.entries):
            try:
                part_collection, part_warnings = import_rigid_model_v2(
                    str(entry.model_path), context, parent_collection=slot_collection
                )
            except Exception as error:  # noqa: BLE001 - one bad model must not lose the whole assembly
                warnings.append(f"'{entry.model_path.name}' could not be imported: {error}")
                continue
            warnings.extend(part_warnings)
            # First one wins: alternatives in a slot carry the same point names as each other, and
            # the first is the one left visible below, so overwriting would hang a weapon off a
            # hidden body's socket.
            for name, point in _attachment_points_in(part_collection).items():
                attachment_points.setdefault(name, point)
            if entry.attach_point:
                pending.append((part_collection, entry.attach_point))
            # Siblings in one slot are the alternatives the game picks between at random, so only
            # the first is left visible - all of them at once is an unreadable pile.
            if index > 0:
                part_collection.hide_viewport = True

    for part_collection, attach_point in pending:
        target = attachment_points.get(attach_point)
        if target is None:
            warnings.append(
                f"'{part_collection.name}' binds to attachment point '{attach_point}', which no imported part "
                "carries - it was left at the origin."
            )
            continue
        for obj in part_collection.all_objects:
            if obj.parent is not None:
                continue
            obj.parent = target
            obj.matrix_parent_inverse = target.matrix_world.inverted()

    if not any(unit_collection.children):
        warnings.append(f"'{path.name}' referenced no model this add-on could import.")
    return unit_collection, warnings


__all__ = ["VmdError", "import_vmd", "read_vmd", "resolve_asset_path", "working_data_root"]
