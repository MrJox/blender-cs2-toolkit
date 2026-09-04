import re
import shutil
import sys
import time
import traceback
from pathlib import Path

import addon_utils
import bpy

REPO_ROOT = r"C:\Users\Khaiali\source\repos\blender_buildings_plugin"
ASSEMBLY_KIT_ROOT = r"D:\SteamLibrary\steamapps\common\Total War Attila\assembly_kit"
RAW_DATA_DIR = ASSEMBLY_KIT_ROOT + r"\raw_data\art\battle\land\models\architecture\blender_test"
_TEXTURE_DIR = ASSEMBLY_KIT_ROOT + r"\raw_data\art\battle\land\models\architecture\gondorean\textures"
TEXTURE_NODES = {
    "Diffuse": _TEXTURE_DIR + r"\gondorean_reskin_new_1_diffuse.tga",
    "Normal": _TEXTURE_DIR + r"\gondorean_reskin_new_1_normal.tga",
    "Gloss": _TEXTURE_DIR + r"\gondorean_reskin_new_1_gloss.tga",
    "Level": _TEXTURE_DIR + r"\gondorean_reskin_new_1_level.tga",
    "Specular": _TEXTURE_DIR + r"\gondorean_reskin_new_1_specular.tga",
}
BUILDING_NAMES = ("BobBatchOne", "BobBatchTwo")

if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

failures = []


def check(label: str, condition: bool) -> None:
    print(("  OK   " if condition else "  FAIL ") + label)
    if not condition:
        failures.append(label)


def active_layer_collection_for(collection):
    def find(layer_collection):
        if layer_collection.collection == collection:
            return layer_collection
        for child in layer_collection.children:
            found = find(child)
            if found is not None:
                return found
        return None

    result = find(bpy.context.view_layer.layer_collection)
    if result is None:
        raise RuntimeError(f"Could not find layer collection for {collection.name}")
    return result


def build_minimal_building(name: str):
    bpy.ops.tw_buildings.new_building()
    building = [c for c in bpy.data.collections if c.tw_role == "BUILDING"][-1]
    building.name = name
    bpy.context.view_layer.active_layer_collection = active_layer_collection_for(building)

    bpy.ops.tw_buildings.new_piece()
    piece = building.children[0]
    bpy.context.view_layer.active_layer_collection = active_layer_collection_for(piece)

    bpy.ops.tw_buildings.new_destruct_level()
    destruct = piece.children[0]
    display = [c for c in destruct.children if c.tw_role == "DISPLAY"][0]
    collision = [c for c in destruct.children if c.tw_role == "COLLISION"][0]

    bpy.ops.mesh.primitive_cube_add()
    cube = bpy.context.active_object
    cube.name = f"{name}_display"
    for coll in list(cube.users_collection):
        coll.objects.unlink(cube)
    display.objects.link(cube)
    bpy.context.view_layer.objects.active = cube
    cube.select_set(True)
    bpy.ops.object.mode_set(mode="EDIT")
    bpy.ops.mesh.select_all(action="SELECT")
    bpy.ops.uv.smart_project()
    bpy.ops.object.mode_set(mode="OBJECT")

    material = bpy.data.materials.new(name=f"{cube.name}_Material")
    cube.data.materials.append(material)
    cube.active_material = material
    bpy.ops.tw_buildings.make_material()
    for node_name, texture_path in TEXTURE_NODES.items():
        node = material.node_tree.nodes.get(node_name)
        if node is None:
            raise RuntimeError(f"generated material has no {node_name} image node")
        node.image = bpy.data.images.load(texture_path, check_existing=True)

    bpy.ops.mesh.primitive_cube_add()
    collision_box = bpy.context.active_object
    collision_box.name = f"{name}_collision"
    for coll in list(collision_box.users_collection):
        coll.objects.unlink(collision_box)
    collision.objects.link(collision_box)
    collision_box.tw_collision_type = "COLLISION"
    collision_box.select_set(False)
    cube.select_set(False)
    return building


def remove_build_artifacts(name: str) -> None:
    kit = Path(ASSEMBLY_KIT_ROOT)
    stem = name.lower()
    targets = [
        kit.parent / "data" / f"{stem}.pack",
        kit / "retail" / "data" / f"{stem}.pack",
        kit / "working_data" / "db" / "models_building_tables" / f"bob_building_{stem}_models_building",
        kit / "working_data" / "db" / "battlefield_buildings_tables" / f"bob_building_{stem}_battlefield_buildings",
        Path(RAW_DATA_DIR) / f"{name}.CS2",
        kit / "working_data" / "RigidModels" / "Buildings" / stem,
        kit / "raw_data" / "EmpireDesignData" / "buildings" / stem,
        kit / "raw_data" / "EmpireDesignData" / f"bob_building_{stem}_models_building.xml",
        kit / "raw_data" / "EmpireDesignData" / f"bob_building_{stem}_battlefield_buildings.xml",
    ]
    for target in targets:
        if target.is_dir():
            shutil.rmtree(target, ignore_errors=True)
        elif target.exists():
            target.unlink()


def main() -> None:
    module = addon_utils.enable("total_war_buildings", default_set=True, persistent=False)
    if module is None:
        raise RuntimeError("addon_utils.enable returned failure")
    bpy.context.preferences.addons["total_war_buildings"].preferences.assembly_kit_root = ASSEMBLY_KIT_ROOT

    from bob import cli
    from export.exporter import export_building

    if cli.is_bob_running():
        raise RuntimeError("BOB is already open - close it before running this test.")

    for name in BUILDING_NAMES:
        remove_build_artifacts(name)

    buildings = [build_minimal_building(name) for name in BUILDING_NAMES]
    cs2_paths = []
    for building in buildings:
        result = export_building(building, RAW_DATA_DIR, ASSEMBLY_KIT_ROOT, bpy.context)
        if not result.success:
            raise RuntimeError(f"{building.name} did not export: {result.message}")
        cs2_paths.append(result.cs2_path)
    check("both buildings exported", all(path.is_file() for path in cs2_paths))

    print("=== one BOB run builds every building of the batch ===")
    started = time.monotonic()
    batch = cli.start_building_batch(ASSEMBLY_KIT_ROOT, cs2_paths, create_pack=False)
    check("a batch of buildings is a single BobRun, not a sequence", isinstance(batch, cli.BobRun))
    bob_result = batch.wait()
    print(f"    {len(BUILDING_NAMES)} buildings compiled in {time.monotonic() - started:.1f}s of BOB")
    print("   ", bob_result.message.replace("\n", " | "))
    check("the batch reported success", bob_result.success)
    for name in BUILDING_NAMES:
        output = cli.compiled_output_dir(ASSEMBLY_KIT_ROOT, Path(RAW_DATA_DIR) / f"{name}.CS2")
        check(f"BOB wrote {name}'s output folder", output.is_dir())
        check(
            f"{name} compiled to a .rigid_model_v2",
            any(output.glob("*.rigid_model_v2")),
        )
        check(f"the batch message names {name}", name.lower() in bob_result.message.lower())

    summary = cli.read_failure_summary(ASSEMBLY_KIT_ROOT)
    check("BOB logged no error line across the batch", not summary)

    print("=== one more run packs every building of the batch ===")
    from bob import rules

    started = time.monotonic()
    pack_result = cli.start_pack(ASSEMBLY_KIT_ROOT, cs2_paths).wait()
    print(f"    {len(BUILDING_NAMES)} packs built in {time.monotonic() - started:.1f}s of BOB")
    print("   ", pack_result.message.replace("\n", " | "))
    check("the pack run reported success", pack_result.success)
    for name in BUILDING_NAMES:
        installed = rules.installed_pack_path(ASSEMBLY_KIT_ROOT, name.lower())
        check(f"{name}.pack was installed into the game's data folder", installed.is_file())
        if installed.is_file():
            head = installed.read_bytes()[:900]
            listed = [
                match.decode("ascii", "replace")
                for match in re.findall(rb"[ -~]{6,}", head)
                if b"bob_building_" in match
            ]
            check(
                f"{name}.pack holds only its own db tables",
                listed and all(name.lower() in entry for entry in listed),
            )
    working_data = Path(ASSEMBLY_KIT_ROOT) / "working_data"
    check(
        "the shared db pack rule was cleaned out again",
        not (working_data / "db" / rules.RULES_FILENAME).exists(),
    )

    if failures:
        raise RuntimeError(f"{len(failures)} check(s) failed: " + "; ".join(failures))
    print("ALL BATCH BOB CHECKS PASSED")


try:
    main()
except Exception:
    print("=== BATCH BOB TEST FAILED ===")
    traceback.print_exc()
    sys.exit(1)
finally:
    for building_name in BUILDING_NAMES:
        remove_build_artifacts(building_name)
