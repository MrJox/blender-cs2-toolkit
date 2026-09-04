import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from binary.cs2_reader import read_cs2
from binary.cs2_writer import write_cs2


SAMPLES = [
    "bridge_stone_1/bridge_stone_1.CS2",
    "eastern_new_1/eastern_new_1.CS2",
    "gondor_building_5/gondor_building_5.CS2",
    "gondor_fort_gateway_e/gondor_fort_gateway_e.CS2",
]


def check(sample_path: Path) -> bool:
    original = sample_path.read_bytes()
    doc = read_cs2(original)
    rebuilt = write_cs2(doc)

    if rebuilt == original:
        print(sample_path.name, "EXACT MATCH:", len(rebuilt), "bytes")
        return True

    print(sample_path.name, "MISMATCH: original", len(original), "bytes, rebuilt", len(rebuilt), "bytes")
    first_diff = next((i for i in range(min(len(original), len(rebuilt))) if original[i] != rebuilt[i]), None)
    if first_diff is not None:
        start = max(0, first_diff - 16)
        print(f"  first differing byte at offset {first_diff}")
        print("  original:", original[start : first_diff + 16].hex())
        print("  rebuilt: ", rebuilt[start : first_diff + 16].hex())
    return False


def main() -> None:
    raw_data_root = Path(__file__).resolve().parent.parent.parent / "Input/examples/raw_data"
    all_ok = True
    for relative in SAMPLES:
        all_ok = check(raw_data_root / relative) and all_ok
    if not all_ok:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
