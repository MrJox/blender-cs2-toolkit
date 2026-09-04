import os
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass

Vec3 = tuple[float, float, float]

_DESTRUCT_KEY = re.compile(r"piece\d+_destruct\d+", re.IGNORECASE)


@dataclass
class DockingLineRecord:
    name: str
    destruct_key: str
    start: Vec3
    end: Vec3
    direction: Vec3


def find_building_logic_xml(filepath: str) -> str | None:
    # Docking lines are absent from the compiled .cs2.parsed entirely: EMPIREUTILITY::DESTRUCTION_LEVEL
    # (the struct that file encodes) has no docking-line list, and its `docking_points` array is a
    # different tech (PLACEMENT_DATA nodes). BOB compiles DockingLine nodes into this building-logic
    # XML instead, alongside the EFLines - confirmed against a real building's compiled output.
    dir_path = os.path.dirname(filepath)
    filename = os.path.basename(filepath)
    lower = filename.lower()

    if lower.endswith(".cs2.parsed"):
        stem = filename[:-11]
    elif lower.endswith(".cs2"):
        stem = filename[:-4]
    else:
        stem = os.path.splitext(filename)[0]

    candidates = [f"{stem}.xml"]
    if stem.lower().endswith("_tech"):
        candidates.append(f"{stem[:-5]}_tech.xml")
    else:
        candidates.append(f"{stem}_tech.xml")

    for candidate in candidates:
        path = os.path.join(dir_path, candidate)
        if os.path.isfile(path):
            return path
    return None


def _point(element) -> Vec3:
    # No axis conversion: this XML carries the node's user_defined_properties text verbatim, and
    # that buffer is authoring (Z-up) space - the same boundary naming._to_authoring_space exists
    # for. Confirmed against gondor_fort_tower_C_straight, whose EFLine UDP text and compiled
    # <end>/<direction> values are identical component for component.
    return (
        float(element.attrib.get("x", "0.0")),
        float(element.attrib.get("y", "0.0")),
        float(element.attrib.get("z", "0.0")),
    )


def read_docking_lines(xml_path: str) -> list[DockingLineRecord]:
    root = ET.parse(xml_path).getroot()
    group = root.find("docking_lines")
    if group is None:
        return []

    records: list[DockingLineRecord] = []
    for element in group.findall("docking_line"):
        ends = [_point(e) for e in element.findall("end")]
        direction_element = element.find("direction")
        if len(ends) != 2 or direction_element is None:
            continue
        name = element.attrib.get("name", "")
        key_match = _DESTRUCT_KEY.search(name)
        records.append(
            DockingLineRecord(
                name=name or "DockingLine",
                destruct_key=key_match.group(0).lower() if key_match else "",
                start=ends[0],
                end=ends[1],
                direction=_point(direction_element),
            )
        )
    return records
