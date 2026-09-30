import shutil
import sys
import tempfile
import traceback
from pathlib import Path

import addon_utils
import bpy

REPO_ROOT = r"C:\Users\Khaiali\source\repos\blender_buildings_plugin"
ASSEMBLY_KIT_ROOT = r"D:\SteamLibrary\steamapps\common\Total War Attila\assembly_kit"
WORKING_TEXTURES = Path(ASSEMBLY_KIT_ROOT) / "working_data" / "RigidModels" / "Buildings" / "Textures"
CAMPAIGN_MASKS = (
    Path(ASSEMBLY_KIT_ROOT).parent
    / "assembly_kit_campaign_tilemap"
    / "working_data"
    / "RigidModels"
    / "campaign"
)
# Real source files to copy FROM - never written to. The compile test builds in a scratch raw_data
# folder of its own (cleaned up afterward) rather than round_curved_shield's real folder, because
# that folder is already covered by CA's own ancestor rules.bob (see PLAN_textures.md 3.3) and
# compiling into it in place would overwrite real shipped working_data output.
SHIELD_TEX_DIR = Path(ASSEMBLY_KIT_ROOT) / "raw_data" / "VariantMeshes" / "VariantModels" / "man" / "shield" / "tex"
COMPILE_SCRATCH_DIR = Path(ASSEMBLY_KIT_ROOT) / "raw_data" / "_tw_addon_texture_compile_test"
COMPILE_SCRATCH_TARGET = "_tw_addon_texture_compile_test_output"
COMPILE_SCRATCH_OUTPUT = Path(ASSEMBLY_KIT_ROOT) / "working_data" / COMPILE_SCRATCH_TARGET

if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)


def main() -> None:
    print("=== enabling add-on ===")
    module = addon_utils.enable("total_war_cs2_addon", default_set=True, persistent=False)
    if module is None:
        raise RuntimeError("addon_utils.enable returned failure")

    prefs = bpy.context.preferences.addons["total_war_cs2_addon"].preferences
    prefs.assembly_kit_root = ASSEMBLY_KIT_ROOT

    scratch = Path(tempfile.mkdtemp(prefix="tw_texture_test_"))
    try:
        print("=== decompile a chosen selection ===")
        out_selected = scratch / "selected"
        names = [
            "gondorean_reskin_new_1_gloss_map.dds",
            "gondorean_reskin_new_1_normal.dds",
            "gondorean_reskin_new_1_diffuse.dds",
        ]
        for name in names:
            if not (WORKING_TEXTURES / name).is_file():
                raise RuntimeError(f"expected corpus file missing: {WORKING_TEXTURES / name}")

        result = bpy.ops.tw_buildings.decompile_textures(
            directory=str(WORKING_TEXTURES) + "\\",
            files=[{"name": name} for name in names],
            output_directory=str(out_selected),
            overwrite=False,
        )
        print("operator result:", result)
        assert result == {"FINISHED"}, result

        expected = [
            "gondorean_reskin_new_1_gloss.tga",
            "gondorean_reskin_new_1_level.tga",
            "gondorean_reskin_new_1_normal.tga",
            "gondorean_reskin_new_1_diffuse.tga",
        ]
        for name in expected:
            path = out_selected / name
            if not path.is_file():
                raise RuntimeError(f"expected output missing: {path}")
            print("  wrote", name, path.stat().st_size, "bytes")

        print("=== re-run without overwrite reports nothing written ===")
        result = bpy.ops.tw_buildings.decompile_textures(
            directory=str(WORKING_TEXTURES) + "\\",
            files=[{"name": names[0]}],
            output_directory=str(out_selected),
            overwrite=False,
        )
        print("operator result:", result)
        assert result == {"CANCELLED"}, result

        print("=== whole-folder convenience (no files selected) ===")
        mask_dds = next(CAMPAIGN_MASKS.rglob("*_mask.dds"))
        folder_in = scratch / "folder_in"
        folder_in.mkdir()
        shutil.copy(mask_dds, folder_in / mask_dds.name)
        shutil.copy(
            WORKING_TEXTURES / "gondorean_reskin_new_2_specular.dds",
            folder_in / "gondorean_reskin_new_2_specular.dds",
        )
        out_folder = scratch / "folder_out"

        result = bpy.ops.tw_buildings.decompile_textures(
            directory=str(folder_in) + "\\",
            files=[],
            output_directory=str(out_folder),
            overwrite=False,
        )
        print("operator result:", result)
        assert result == {"FINISHED"}, result
        mask_base = mask_dds.stem[: -len("_mask")]
        expected_names = [f"{mask_base}_mask{n}.tga" for n in (1, 2, 3)] + [
            "gondorean_reskin_new_2_specular.tga"
        ]
        for name in expected_names:
            path = out_folder / name
            if not path.is_file():
                raise RuntimeError(f"expected output missing: {path}")
            print("  wrote", name, path.stat().st_size, "bytes")

        print("=== compile: mask1 selection pulls in mask2/mask3, real BOB run ===")
        if COMPILE_SCRATCH_DIR.exists():
            raise RuntimeError(f"expected a clean fixture folder, found an existing {COMPILE_SCRATCH_DIR}")
        COMPILE_SCRATCH_DIR.mkdir()
        try:
            for suffix in ("_mask1", "_mask2", "_mask3", "_gloss", "_level"):
                name = f"round_curved_shield{suffix}.tga"
                shutil.copy(SHIELD_TEX_DIR / name, COMPILE_SCRATCH_DIR / name)

            mask_output = COMPILE_SCRATCH_OUTPUT / "round_curved_shield_mask.dds"
            gloss_map_output = COMPILE_SCRATCH_OUTPUT / "round_curved_shield_gloss_map.dds"
            scratch_rules_bob = COMPILE_SCRATCH_DIR / "rules.bob"

            result = bpy.ops.tw_buildings.compile_textures(
                directory=str(COMPILE_SCRATCH_DIR) + "\\",
                files=[{"name": "round_curved_shield_mask1.tga"}],
                target_path=COMPILE_SCRATCH_TARGET,
            )
            print("operator result:", result)
            assert result == {"FINISHED"}, result
            if not mask_output.is_file():
                raise RuntimeError(f"expected compiled output missing: {mask_output}")
            print("  compiled", mask_output.name, mask_output.stat().st_size, "bytes")
            if not scratch_rules_bob.is_file():
                raise RuntimeError(f"expected rules.bob to have been written: {scratch_rules_bob}")
            print("  wrote", scratch_rules_bob)

            print("=== compile: gloss selection, same already-covered scratch folder ===")
            result = bpy.ops.tw_buildings.compile_textures(
                directory=str(COMPILE_SCRATCH_DIR) + "\\",
                files=[{"name": "round_curved_shield_gloss.tga"}],
                target_path=COMPILE_SCRATCH_TARGET,
            )
            print("operator result:", result)
            assert result == {"FINISHED"}, result
            if not gloss_map_output.is_file():
                raise RuntimeError(f"expected compiled output missing: {gloss_map_output}")
            print("  compiled", gloss_map_output.name, gloss_map_output.stat().st_size, "bytes")
        finally:
            shutil.rmtree(COMPILE_SCRATCH_DIR, ignore_errors=True)
            shutil.rmtree(COMPILE_SCRATCH_OUTPUT, ignore_errors=True)

        print("=== TEXTURE TEST PASSED ===")
    finally:
        shutil.rmtree(scratch, ignore_errors=True)


try:
    main()
except Exception:
    print("=== TEXTURE TEST FAILED ===")
    traceback.print_exc()
    sys.exit(1)
