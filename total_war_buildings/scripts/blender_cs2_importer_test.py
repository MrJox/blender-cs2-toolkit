import sys
import tempfile
from pathlib import Path

import addon_utils
import bpy

# Ensure add-on package root is on sys.path
ADDON_DIR = Path(__file__).resolve().parent.parent
if str(ADDON_DIR) not in sys.path:
    sys.path.insert(0, str(ADDON_DIR))

from importer import import_cs2
from validation.rules import validate_building
from export.exporter import export_building
from binary.cs2_reader import read_cs2

SAMPLES = [
    "bridge_stone_1/bridge_stone_1.CS2",
    "eastern_new_1/eastern_new_1.CS2",
    "gondor_building_5/gondor_building_5.CS2",
    "gondor_fort_tower_C_straight/gondor_fort_tower_C_straight.CS2",
    "gondor_fort_gateway_e/gondor_fort_gateway_e.CS2",
]


def test_sample(sample_path: Path) -> None:
    print(f"=== Testing CS2 Import: {sample_path.name} ===")

    # Clear existing scene collections/objects
    bpy.ops.wm.read_factory_settings(use_empty=True)
    properties.register()

    building_coll, warnings = import_cs2(str(sample_path), bpy.context)
    print(f"Imported collection '{building_coll.name}' with {len(warnings)} warning(s).")
    for w in warnings:
        print(f"  Warning: {w}")

    assert building_coll.tw_role == "BUILDING"
    assert len(building_coll.children) > 0

    pieces = [child for child in building_coll.children if child.tw_role == "PIECE"]
    print(f"Found {len(pieces)} piece collection(s).")
    assert len(pieces) > 0

    for piece in pieces:
        destructs = [child for child in piece.children if child.tw_role == "DESTRUCT"]
        print(f"  Piece '{piece.name}' has {len(destructs)} destruct level(s).")
        assert len(destructs) > 0

    # Validate building
    issues = validate_building(building_coll)
    error_issues = [i for i in issues if i.severity == "ERROR"]
    print(f"Validation reported {len(issues)} issue(s) ({len(error_issues)} error(s)).")
    for issue in issues:
        print(f"  [{issue.severity}] {issue.message}")
    assert len(error_issues) == 0, f"Imported building '{building_coll.name}' failed validation with errors!"

    # Export building back to CS2
    with tempfile.TemporaryDirectory() as tmp_dir:
        assembly_kit_root = r"D:\SteamLibrary\steamapps\common\Total War Attila\assembly_kit"
        result = export_building(building_coll, tmp_dir, assembly_kit_root, bpy.context)
        print(f"Export result success: {result.success}, message: {result.message}")
        assert result.success, f"Export failed: {result.message}"

        exported_cs2_path = Path(tmp_dir) / f"{building_coll.name}.CS2"
        assert exported_cs2_path.exists()

        orig_doc = read_cs2(sample_path.read_bytes())
        reexp_doc = read_cs2(exported_cs2_path.read_bytes())

        print(f"Original CS2 rigid models: {len(orig_doc.rigid_models)}, lines: {len(orig_doc.lines)}, materials: {len(orig_doc.materials)}")
        print(f"Re-exported CS2 rigid models: {len(reexp_doc.rigid_models)}, lines: {len(reexp_doc.lines)}, materials: {len(reexp_doc.materials)}")

        assert len(reexp_doc.rigid_models) > 0
        assert len(reexp_doc.materials) > 0

    print(f"=== CS2 Import Test Passed for {sample_path.name} ===\n")


from props import properties

def main() -> None:
    print("=== enabling add-on ===")
    module = addon_utils.enable("total_war_buildings", default_set=True, persistent=False)
    if module is None:
        raise RuntimeError("addon_utils.enable returned failure")
    properties.register()

    raw_data_root = ADDON_DIR.parent / "Input/examples/raw_data"
    for relative in SAMPLES:
        sample_path = raw_data_root / relative
        test_sample(sample_path)

    print("=== ALL CS2 IMPORTER TESTS PASSED ===")


if __name__ == "__main__":
    main()
