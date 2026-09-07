import shutil
import sys
import tempfile
import traceback
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
ADDON_ROOT = REPO_ROOT / "total_war_cs2_addon"
if str(ADDON_ROOT) not in sys.path:
    sys.path.insert(0, str(ADDON_ROOT))

from binary.cs2_parsed_patch import find_parsed_files, patch_bytes, patch_folder  # noqa: E402
from binary.cs2_parsed_reader import CS2ParsedReader  # noqa: E402

SAMPLES = REPO_ROOT / "Input" / "examples" / "working_data"
OLD = "torch_sconce"

failures = []


def check(label: str, condition: bool) -> None:
    print(("  OK   " if condition else "  FAIL ") + label)
    if not condition:
        failures.append(label)


def references(data: bytes) -> list[tuple[str, str]]:
    document = CS2ParsedReader.read_bytes(data)
    return [
        (reference.key, reference.name)
        for piece in document.pieces
        for destruct in piece.destructs
        for reference in destruct.file_refs
    ]


def main() -> None:
    samples = find_parsed_files(SAMPLES)
    if not samples:
        raise RuntimeError(f"No .cs2.parsed samples under {SAMPLES}")
    with_refs = [path for path in samples if any(name == OLD for _key, name in references(path.read_bytes()))]
    print(f"{len(samples)} sample(s), {len(with_refs)} referencing '{OLD}'")
    if not with_refs:
        raise RuntimeError(f"No sample references '{OLD}' - the patch cannot be verified")

    print("=== a replacement is exact, whatever the new name's length ===")
    for source in with_refs:
        original = source.read_bytes()
        before = references(original)
        for new in ("brazier", "a", "very_long_replacement_prop_name_xyz"):
            patched, replaced = patch_bytes(original, OLD, new)
            after = references(patched)
            expected = sum(1 for _key, name in before if name == OLD)
            grew = (len(new) - len(OLD)) * 2
            # Both strings of a reference carry the name: the name itself and the tail of its key.
            check(
                f"{source.name} -> '{new}': every reference moved",
                replaced == expected and all(name == new for _key, name in after),
            )
            check(
                f"{source.name} -> '{new}': the key followed its name",
                all(key.endswith(f"file:{new}") for key, _name in after),
            )
            check(
                f"{source.name} -> '{new}': the file grew by exactly the string delta",
                len(patched) - len(original) == expected * grew * 2,
            )
            # Nothing outside the spliced strings may move, and the only honest way to show that is
            # to patch back and compare every byte.
            restored, _count = patch_bytes(patched, new, OLD)
            check(f"{source.name} -> '{new}': patching back is byte-identical", restored == original)

    print("=== a name nothing references is left completely alone ===")
    source = with_refs[0]
    original = source.read_bytes()
    untouched, replaced = patch_bytes(original, "no_such_prop", "whatever")
    check("nothing was replaced", replaced == 0)
    check("the bytes are identical", untouched == original)

    print("=== a folder run patches recursively and skips what it cannot parse ===")
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        nested = root / "deep" / "nested"
        nested.mkdir(parents=True)
        for index, path in enumerate(with_refs):
            shutil.copy2(path, (root if index == 0 else nested) / path.name)
        decoy = nested / "broken_tech.cs2.parsed"
        decoy.write_bytes(b"not a real parsed file")
        ignored = root / "notes.txt"
        ignored.write_text("left alone")

        results = patch_folder(root, OLD, "brazier")
        changed = [result for result in results if result.changed]
        skipped = [result for result in results if result.message]
        check("every real sample was found recursively", len(changed) == len(with_refs))
        check("the unparseable file was skipped rather than corrupted", len(skipped) == 1)
        check("the unparseable file is untouched", decoy.read_bytes() == b"not a real parsed file")
        check("a non-parsed file is not even considered", ignored.read_text() == "left alone")
        check(
            "every patched file still parses and carries the new name",
            all(
                all(name == "brazier" for _key, name in references(result.path.read_bytes()))
                for result in changed
            ),
        )
        check("no .tmp file was left behind", not list(root.rglob("*.tmp")))

    print()
    if failures:
        print(f"FAILED {len(failures)} check(s):")
        for failure in failures:
            print("   ", failure)
        raise SystemExit(1)
    print("all checks passed")


try:
    main()
except SystemExit:
    raise
except Exception:
    traceback.print_exc()
    sys.exit(1)
