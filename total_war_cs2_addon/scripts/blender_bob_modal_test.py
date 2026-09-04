"""Run WITHOUT --background - the export operator's BOB watch is a modal timer, which needs a
real event loop. Pass/fail is decided from the console output this prints."""

import sys
import time
import traceback
from pathlib import Path

import addon_utils
import bpy

REPO_ROOT = r"C:\Users\Khaiali\source\repos\blender_buildings_plugin"

if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

sys.path.insert(0, str(Path(__file__).parent))
from blender_bob_cli_test import (  # noqa: E402
    ASSEMBLY_KIT_ROOT,
    BUILDING_NAME,
    RAW_DATA_DIR,
    build_minimal_building,
    remove_build_artifacts,
)

DEADLINE_SECONDS = 300


def main() -> None:
    if bpy.app.background:
        raise RuntimeError("this test has to run in a real Blender window, not --background")

    module = addon_utils.enable("total_war_cs2_addon", default_set=True, persistent=False)
    if module is None:
        raise RuntimeError("addon_utils.enable returned failure")
    bpy.context.preferences.addons["total_war_cs2_addon"].preferences.assembly_kit_root = ASSEMBLY_KIT_ROOT

    from bob import cli, rules

    remove_build_artifacts(BUILDING_NAME)
    build_minimal_building()

    cs2_path = Path(RAW_DATA_DIR) / f"{BUILDING_NAME}.CS2"
    output_dir = cli.compiled_output_dir(ASSEMBLY_KIT_ROOT, cs2_path)
    pack = rules.installed_pack_path(ASSEMBLY_KIT_ROOT, rules.building_name_for(cs2_path))

    result = bpy.ops.tw_buildings.export_building(
        "EXEC_DEFAULT", directory=RAW_DATA_DIR, compile_with_bob=True, create_pack=True
    )
    print("MODALTEST operator returned", result)
    if result != {"RUNNING_MODAL"}:
        print("=== BOB MODAL TEST FAILED === operator did not hand off to a modal BOB watch")
        bpy.ops.wm.quit_blender()
        return

    started_at = time.monotonic()
    state = {"heartbeats": 0}

    # The operator chains two BOB runs (compile, then pack), so "BOB is gone" is not on its own a
    # finish signal - the pack landing in the game's data folder is.
    def watch() -> float | None:
        state["heartbeats"] += 1
        elapsed = time.monotonic() - started_at
        if output_dir.is_dir() and "compiled_at" not in state:
            state["compiled_at"] = elapsed
            print(f"MODALTEST compiled output appeared after {elapsed:.0f}s")
        if pack.is_file() and "packed_at" not in state:
            state["packed_at"] = elapsed
            print(f"MODALTEST pack appeared after {elapsed:.0f}s")
        if "packed_at" in state and not cli.is_bob_running() and elapsed > state["packed_at"] + 5:
            print(
                f"MODALTEST finished after {elapsed:.0f}s, "
                f"{state['heartbeats']} heartbeats while Blender stayed responsive"
            )
            print('=== BOB MODAL TEST PASSED === expect a "packed it into" operator report above')
            remove_build_artifacts(BUILDING_NAME)
            bpy.ops.wm.quit_blender()
            return None
        if elapsed > DEADLINE_SECONDS:
            print(f"=== BOB MODAL TEST FAILED === no pack within {DEADLINE_SECONDS}s (state: {state})")
            remove_build_artifacts(BUILDING_NAME)
            bpy.ops.wm.quit_blender()
            return None
        return 1.0

    bpy.app.timers.register(watch, first_interval=1.0)


try:
    main()
except Exception:
    print("=== BOB MODAL TEST FAILED ===")
    traceback.print_exc()
    bpy.ops.wm.quit_blender()
