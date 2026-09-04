import re
import shutil
import struct
import sys
import tempfile
import traceback
from pathlib import Path

import addon_utils
import bpy

REPO_ROOT = r"C:\Users\Khaiali\source\repos\blender_buildings_plugin"
ASSEMBLY_KIT_ROOT = r"D:\SteamLibrary\steamapps\common\Total War Attila\assembly_kit"
RAW_DATA_DIR = ASSEMBLY_KIT_ROOT + r"\raw_data\art\battle\land\models\architecture\blender_test"
# BOB refuses a mesh whose textures are not real raw_data files, so the max_shader placeholders the
# material generator falls back to are not enough to get a compile out of it.
_TEXTURE_DIR = ASSEMBLY_KIT_ROOT + r"\raw_data\art\battle\land\models\architecture\gondorean\textures"
TEXTURE_NODES = {
    "Diffuse": _TEXTURE_DIR + r"\gondorean_reskin_new_1_diffuse.tga",
    "Normal": _TEXTURE_DIR + r"\gondorean_reskin_new_1_normal.tga",
    "Gloss": _TEXTURE_DIR + r"\gondorean_reskin_new_1_gloss.tga",
    "Level": _TEXTURE_DIR + r"\gondorean_reskin_new_1_level.tga",
    "Specular": _TEXTURE_DIR + r"\gondorean_reskin_new_1_specular.tga",
}
BUILDING_NAME = "BobCliTest"

if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)


def active_layer_collection_for(collection: bpy.types.Collection) -> bpy.types.LayerCollection:
    def find(layer_collection: bpy.types.LayerCollection):
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


def build_minimal_building() -> bpy.types.Collection:
    bpy.ops.tw_buildings.new_building()
    building = [c for c in bpy.data.collections if c.tw_role == "BUILDING"][-1]
    building.name = BUILDING_NAME
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
    for coll in list(collision_box.users_collection):
        coll.objects.unlink(collision_box)
    collision.objects.link(collision_box)
    collision_box.tw_collision_type = "COLLISION"

    bpy.context.view_layer.active_layer_collection = active_layer_collection_for(destruct)
    return building


def read_pack(path: Path) -> tuple[str, int, int, list[str]]:
    data = path.read_bytes()
    names = [
        m.group().decode("ascii")
        for m in re.finditer(rb"[ -~]{6,}", data[:800])
        if b"\\" in m.group()
    ]
    return data[:4].decode("ascii", "replace"), struct.unpack_from("<I", data, 4)[0], struct.unpack_from("<I", data, 16)[0], names


def remove_build_artifacts(name: str) -> None:
    kit = Path(ASSEMBLY_KIT_ROOT)
    stem = name.lower()
    targets = [
        kit.parent / "data" / f"{stem}.pack",
        kit / "retail" / "data" / f"{stem}.pack",
        Path(RAW_DATA_DIR) / f"{name}.CS2",
        kit / "working_data" / "RigidModels" / "Buildings" / stem,
        kit / "raw_data" / "EmpireDesignData" / "buildings" / stem,
        kit / "raw_data" / "EmpireDesignData" / f"bob_building_{stem}_models_building.xml",
        kit / "raw_data" / "EmpireDesignData" / f"bob_building_{stem}_battlefield_buildings.xml",
        kit / "working_data" / "db" / "models_building_tables" / f"bob_building_{stem}_models_building",
        kit / "working_data" / "db" / "battlefield_buildings_tables" / f"bob_building_{stem}_battlefield_buildings",
    ]
    for target in targets:
        if target.is_dir():
            shutil.rmtree(target, ignore_errors=True)
        elif target.exists():
            target.unlink()


def check(condition: bool, description: str) -> None:
    if not condition:
        raise AssertionError(description)
    print("  OK:", description)


def main() -> None:
    module = addon_utils.enable("total_war_buildings", default_set=True, persistent=False)
    if module is None:
        raise RuntimeError("addon_utils.enable returned failure")
    bpy.context.preferences.addons["total_war_buildings"].preferences.assembly_kit_root = ASSEMBLY_KIT_ROOT

    from bob import cli

    print("=== logical path resolution ===")
    inside = Path(RAW_DATA_DIR) / f"{BUILDING_NAME}.CS2"
    check(
        cli.raw_data_logical_path(ASSEMBLY_KIT_ROOT, inside)
        == "<raw>/art/battle/land/models/architecture/blender_test/BobCliTest.CS2",
        "a raw_data file resolves to its <raw>-relative logical path",
    )
    outside_dir = tempfile.mkdtemp(prefix="bobclitest_")
    try:
        cli.raw_data_logical_path(ASSEMBLY_KIT_ROOT, Path(outside_dir) / f"{BUILDING_NAME}.CS2")
        raise AssertionError("a file outside raw_data should not resolve")
    except cli.BobError as error:
        check("raw_data" in str(error), "a file outside raw_data is refused with an explanation")
    finally:
        shutil.rmtree(outside_dir, ignore_errors=True)

    print("=== rules.bob creation ===")
    from bob import rules

    # No [Building] rule exists anywhere between here and raw_data (raw_data/rules.bob is all
    # [Texture]), so a building exported into a fresh folder here genuinely needs its own.
    uncovered_dir = Path(RAW_DATA_DIR).parent / "bobclitest_rules"
    uncovered_dir.mkdir(exist_ok=True)
    try:
        check(
            not rules.building_rule_in_scope(ASSEMBLY_KIT_ROOT, uncovered_dir / f"{BUILDING_NAME}.CS2"),
            "a folder with no [Building] rule above it is seen as uncovered",
        )
        created = rules.ensure_building_rules(ASSEMBLY_KIT_ROOT, uncovered_dir / f"{BUILDING_NAME}.CS2")
        check(created is not None and created.is_file(), "a missing rules.bob is created beside the export")
        check(
            created.read_bytes() == (Path(RAW_DATA_DIR) / "rules.bob").read_bytes(),
            "the created rules.bob is byte-identical to the one CA ships",
        )
        check(
            rules.ensure_building_rules(ASSEMBLY_KIT_ROOT, uncovered_dir / f"{BUILDING_NAME}.CS2") is None,
            "an existing rules.bob is left alone",
        )
    finally:
        shutil.rmtree(uncovered_dir, ignore_errors=True)

    covered_dir = Path(RAW_DATA_DIR) / "bobclitest_rules"
    covered_dir.mkdir(exist_ok=True)
    try:
        check(
            rules.building_rule_in_scope(ASSEMBLY_KIT_ROOT, covered_dir / f"{BUILDING_NAME}.CS2"),
            "a parent folder's [Building] rule is seen as covering a sub-folder",
        )
        check(
            rules.ensure_building_rules(ASSEMBLY_KIT_ROOT, covered_dir / f"{BUILDING_NAME}.CS2") is None,
            "no rules.bob is spawned when a parent already provides a [Building] rule",
        )
        check(
            not (covered_dir / rules.RULES_FILENAME).exists(),
            "the covered sub-folder really was left empty",
        )
    finally:
        shutil.rmtree(covered_dir, ignore_errors=True)

    check(
        not rules.building_rule_in_scope(
            ASSEMBLY_KIT_ROOT, Path(ASSEMBLY_KIT_ROOT) / "raw_data" / f"{BUILDING_NAME}.CS2"
        ),
        "raw_data/rules.bob's [Texture]-only sections do not count as a [Building] rule",
    )
    outside = tempfile.mkdtemp(prefix="bobclitest_")
    try:
        check(
            rules.ensure_building_rules(ASSEMBLY_KIT_ROOT, Path(outside) / f"{BUILDING_NAME}.CS2") is None,
            "no rules.bob is written outside raw_data, where BOB would never read it",
        )
    finally:
        shutil.rmtree(outside, ignore_errors=True)

    print("=== export, compile and pack through BOB ===")
    remove_build_artifacts(BUILDING_NAME)
    building = build_minimal_building()
    result = bpy.ops.tw_buildings.export_building(
        directory=RAW_DATA_DIR, compile_with_bob=True, create_pack=True
    )
    check(result == {"FINISHED"}, "export operator finished, BOB run included")
    cs2_path = Path(RAW_DATA_DIR) / f"{building.name}.CS2"
    check(cs2_path.is_file(), f"exported {cs2_path.name}")

    output_dir = cli.compiled_output_dir(ASSEMBLY_KIT_ROOT, cs2_path)
    check(output_dir.is_dir(), f"BOB created {output_dir}")
    produced = sorted(p.name for p in output_dir.iterdir())
    print("  produced:", produced)
    check(
        any(name.endswith(".rigid_model_v2") for name in produced),
        "a .rigid_model_v2 display model was produced",
    )
    check(
        any(name.endswith(".cs2.parsed") for name in produced),
        "a .cs2.parsed tech file was produced",
    )

    print("=== pack ===")
    stem = BUILDING_NAME.lower()
    pack = rules.installed_pack_path(ASSEMBLY_KIT_ROOT, stem)
    check(pack.is_file(), f"the pack was moved to the game's data folder: {pack}")
    check(
        not rules.pack_path(ASSEMBLY_KIT_ROOT, stem).exists(),
        "nothing was left behind in the Assembly Kit's retail folder",
    )
    magic, pack_type, entry_count, names = read_pack(pack)
    print("  pack:", magic, "type", pack_type, "entries", entry_count)
    for name in names:
        print("   ", name)
    check(magic == "PFH4", "the pack has a PFH4 header")
    check(pack_type == 1, "the pack is a release pack (type 1), which is what TEd will open")
    check(entry_count == 4, "the pack holds 4 entries")
    check(
        any(name.startswith(f"rigidmodels\\buildings\\{stem}\\") and name.endswith(".rigid_model_v2") for name in names),
        "the pack holds the display model",
    )
    check(
        any(name.endswith(".cs2.parsed") for name in names),
        "the pack holds the tech file",
    )
    for folder, suffix in rules.DB_TABLES:
        check(
            f"db\\{folder}\\bob_building_{stem}_{suffix}" in names,
            f"the pack holds the {folder} database file",
        )

    working_data = Path(ASSEMBLY_KIT_ROOT) / "working_data"
    check(
        not (working_data / "db" / rules.RULES_FILENAME).exists(),
        "the db pack rule was cleaned out of working_data",
    )
    check(
        not (working_data / "RigidModels" / "Buildings" / stem / rules.RULES_FILENAME).exists(),
        "the building pack rule was cleaned out of working_data",
    )

    print("=== mod pack ===")
    mod_result = cli.start_pack(ASSEMBLY_KIT_ROOT, [cs2_path], rules.MOD_PACK_TYPE).wait()
    check(mod_result.success, "a mod pack builds from the same compiled output")
    check("launcher" in mod_result.message, "the mod pack message says it has to be enabled first")
    magic, pack_type, entry_count, names = read_pack(pack)
    print("  pack:", magic, "type", pack_type, "entries", entry_count)
    check(pack_type == 3, "the pack is a mod pack (type 3), which is what the game loads")
    check(entry_count == 4, "the mod pack holds the same 4 entries")
    check(
        not (working_data / "db" / rules.RULES_FILENAME).exists(),
        "the mod pack rule was cleaned out of working_data too",
    )

    print("=== failure reporting and cleanup ===")
    broken_name = f"{BUILDING_NAME}Broken"
    broken_path = Path(RAW_DATA_DIR) / f"{broken_name}.CS2"
    broken_path.write_bytes(cs2_path.read_bytes()[:2000])
    broken_result = cli.compile_building(ASSEMBLY_KIT_ROOT, broken_path, create_pack=True)
    print("  BOB says:", broken_result.message)
    check(not broken_result.success, "a truncated .CS2 is reported as a failure")
    check("cas2" in broken_result.message.lower(), "the failure message carries BOB's own reason")
    check(
        not (working_data / "db" / rules.RULES_FILENAME).exists(),
        "a failed build leaves no pack rule behind in working_data",
    )

    rules.write_pack_rules(ASSEMBLY_KIT_ROOT, ["bobclitest_never_compiled"])
    try:
        cli.start_pack(ASSEMBLY_KIT_ROOT, [Path(RAW_DATA_DIR) / "BobCliTestNeverCompiled.CS2"])
        raise AssertionError("packing something that was never compiled should be refused")
    except cli.BobError as error:
        check("nothing compiled" in str(error), "packing an uncompiled building is refused with an explanation")
    rules.remove_pack_rules(ASSEMBLY_KIT_ROOT, ["bobclitest_never_compiled"])
    check(
        not (working_data / "db" / rules.RULES_FILENAME).exists(),
        "remove_pack_rules clears the db rule it wrote",
    )
    shutil.rmtree(
        working_data / "RigidModels" / "Buildings" / "bobclitest_never_compiled", ignore_errors=True
    )

    remove_build_artifacts(broken_name)
    remove_build_artifacts(BUILDING_NAME)
    print("=== BOB CLI TEST PASSED ===")


if __name__ == "__main__":
    try:
        main()
    except Exception:
        print("=== BOB CLI TEST FAILED ===")
        traceback.print_exc()
        sys.exit(1)
