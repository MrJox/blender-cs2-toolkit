from dataclasses import dataclass, field

# Any bone_type string reads back, so the set of them lives with the dropdown that offers them
# (props.properties.BONE_TYPE_ITEMS) rather than being enforced here - a table from a later Total
# War title uses types Attila never does, and rejecting it would help nobody.
DEFAULT_BONE_TYPE = "BT_CORE"
ROOT_BONE_TYPE = "BT_ROOT"

_TAB_WIDTH = 8
_BONE_TYPE_COLUMN = 48
_SORT_ORDER_COLUMN = 88
_FLAGS_COLUMN = 112

_HEADER_COMMENT = "// <bone_name>,\t\t\t\t<bone_type>,\t\t\t\t<sort_order>\t\t\t<optional flags>"


@dataclass
class BoneTableEntry:
    name: str
    bone_type: str = DEFAULT_BONE_TYPE
    sort_order: int = 1
    flags: str = ""


@dataclass
class BoneTable:
    skeleton_name: str
    version: int = 1
    reference_skeleton: bool = True
    cinematic: bool = False
    entries: list[BoneTableEntry] = field(default_factory=list)


class BoneTableError(Exception):
    pass


def _advance(column: int, text: str) -> int:
    for character in text:
        column = (column // _TAB_WIDTH + 1) * _TAB_WIDTH if character == "\t" else column + 1
    return column


def _pad_to(column: int, target: int) -> str:
    tabs = ""
    while column < target:
        tabs += "\t"
        column = (column // _TAB_WIDTH + 1) * _TAB_WIDTH
    return tabs


def _parse_bool(value: str) -> bool:
    return value.strip().lower() == "true"


def read_bone_table(data: bytes, skeleton_name: str = "") -> BoneTable:
    table = BoneTable(skeleton_name=skeleton_name)
    for raw_line in data.decode("latin-1").replace("\r\n", "\n").split("\n"):
        line = raw_line.split("//", 1)[0].strip()
        if not line:
            continue
        if "=" in line:
            key, _, value = line.partition("=")
            key = key.strip().lower()
            if key == "version":
                table.version = int(value.strip())
            elif key == "reference_skeleton":
                table.reference_skeleton = _parse_bool(value)
            elif key == "cinematic":
                table.cinematic = _parse_bool(value)
            continue
        # Attila and Rome II comma-separate the columns and tab-align them; Pharaoh and Three
        # Kingdoms drop the commas and space-align instead. Both shapes reach the same fields.
        fields = [part.strip() for part in (line.split(",") if "," in line else line.split())]
        fields = [part for part in fields if part]
        if len(fields) < 3:
            raise BoneTableError(f"bone table line has {len(fields)} fields, expected at least 3: {line!r}")
        table.entries.append(
            BoneTableEntry(
                name=fields[0],
                bone_type=fields[1],
                sort_order=int(fields[2]),
                flags=fields[3] if len(fields) > 3 else "",
            )
        )
    return table


def write_bone_table(table: BoneTable) -> bytes:
    lines = [
        f'// "{table.skeleton_name}" bones definition',
        "",
        "// please remember to update version number!",
        f"version={table.version}",
        f"reference_skeleton={'true' if table.reference_skeleton else 'false'}",
        f"cinematic={'true' if table.cinematic else 'false'}",
        "",
        _HEADER_COMMENT,
    ]
    for entry in table.entries:
        text = f"{entry.name},"
        text += _pad_to(_advance(0, text), _BONE_TYPE_COLUMN)
        text += f"{entry.bone_type},"
        text += _pad_to(_advance(0, text), _SORT_ORDER_COLUMN)
        text += str(entry.sort_order)
        if entry.flags:
            text += "," + _pad_to(_advance(0, text) + 1, _FLAGS_COLUMN) + entry.flags
        lines.append(text)
    return ("\r\n".join(lines) + "\r\n").encode("latin-1")
