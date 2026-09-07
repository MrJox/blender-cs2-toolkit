import struct
from dataclasses import dataclass
from pathlib import Path

from .cs2_parsed_reader import CS2ParsedReader

FILE_KEY_SEPARATOR = "file:"


class CS2ParsedPatchError(Exception):
    pass


@dataclass
class PatchResult:
    path: Path
    replaced: int
    changed: bool
    message: str = ""


def _encode_string(value: str) -> bytes:
    encoded = value.encode("utf-16-le")
    characters = len(encoded) // 2
    if characters > 0xFFFF:
        raise CS2ParsedPatchError(f"'{value}' is too long for a 16-bit length prefix.")
    return struct.pack("<H", characters) + encoded


def _rekeyed(key: str, old: str, new: str) -> str | None:
    # The key embeds the prop it points at - 'piece01_destruct01_file:torch_sconce' - so replacing
    # only the name would leave the key naming a prop the file no longer references. The prefix
    # differs per piece and destruct level, so only the part after 'file:' is touched.
    suffix = f"{FILE_KEY_SEPARATOR}{old}"
    if key.endswith(suffix):
        return key[: -len(suffix)] + f"{FILE_KEY_SEPARATOR}{new}"
    if key == old:
        return new
    return None


def _edits(document, old: str, new: str) -> list[tuple[int, int, bytes]]:
    edits: list[tuple[int, int, bytes]] = []
    for piece in document.pieces:
        for destruct in piece.destructs:
            for reference in destruct.file_refs:
                if reference.name != old:
                    continue
                edits.append((*reference.name_span, _encode_string(new)))
                rekeyed = _rekeyed(reference.key, old, new)
                if rekeyed is not None:
                    edits.append((*reference.key_span, _encode_string(rekeyed)))
    return edits


def _reference_names(document) -> list[str]:
    return [
        reference.name
        for piece in document.pieces
        for destruct in piece.destructs
        for reference in destruct.file_refs
    ]


def patch_bytes(data: bytes, old: str, new: str) -> tuple[bytes, int]:
    document = CS2ParsedReader.read_bytes(data)
    edits = _edits(document, old, new)
    if not edits:
        return data, 0

    # Back to front, so each splice leaves the offsets of the ones still to apply untouched.
    patched = data
    for start, end, replacement in sorted(edits, reverse=True):
        patched = patched[:start] + replacement + patched[end:]

    # The only real proof the file is still valid: read it back. The reader walks every array and
    # asserts it lands exactly on the end of the file, so a length prefix left disagreeing with its
    # data would derail the walk long before that check.
    try:
        reparsed = CS2ParsedReader.read_bytes(patched)
    except Exception as error:  # noqa: BLE001
        raise CS2ParsedPatchError(f"the patched file no longer parses ({error})") from error
    before, after = _reference_names(document), _reference_names(reparsed)
    replaced = before.count(old)
    if old in after:
        raise CS2ParsedPatchError(f"'{old}' still appears in the patched file's references.")
    if after.count(new) != before.count(new) + replaced:
        raise CS2ParsedPatchError("the patched file does not carry the expected replacement count.")
    if len(after) != len(before):
        raise CS2ParsedPatchError("the patched file has a different number of references.")
    return patched, replaced


def patch_file(path: Path, old: str, new: str) -> PatchResult:
    path = Path(path)
    try:
        original = path.read_bytes()
    except OSError as error:
        return PatchResult(path=path, replaced=0, changed=False, message=f"could not be read ({error})")

    try:
        patched, replaced = patch_bytes(original, old, new)
    except CS2ParsedPatchError as error:
        return PatchResult(path=path, replaced=0, changed=False, message=str(error))
    except Exception as error:  # noqa: BLE001
        return PatchResult(path=path, replaced=0, changed=False, message=f"could not be parsed ({error})")

    if not replaced:
        return PatchResult(path=path, replaced=0, changed=False)

    temporary = path.with_suffix(path.suffix + ".tmp")
    try:
        temporary.write_bytes(patched)
        temporary.replace(path)
    except OSError as error:
        temporary.unlink(missing_ok=True)
        return PatchResult(path=path, replaced=0, changed=False, message=f"could not be written ({error})")
    return PatchResult(path=path, replaced=replaced, changed=True)


def find_parsed_files(folder: Path) -> list[Path]:
    return sorted(Path(folder).rglob("*.cs2.parsed"))


def patch_folder(folder: Path, old: str, new: str) -> list[PatchResult]:
    return [patch_file(path, old, new) for path in find_parsed_files(folder)]


__all__ = [
    "CS2ParsedPatchError",
    "PatchResult",
    "patch_bytes",
    "patch_file",
    "patch_folder",
    "find_parsed_files",
]
