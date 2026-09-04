import sys
import tempfile
import traceback
from pathlib import Path

import addon_utils
import bpy

REPO_ROOT = r"C:\Users\Khaiali\source\repos\blender_buildings_plugin"
SKELETON_DIR = Path(
    r"D:\SteamLibrary\steamapps\common\Total War Attila\assembly_kit\raw_data\animations\skeletons"
)
SKELETON_CS2 = SKELETON_DIR / "rome_man_game.cs2"
SKELETON_BONE_TABLE = SKELETON_DIR / "rome_man_game.bone_table"

if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

# Blender stores edit-bone head/tail/roll as float32 and the rest pose is rebuilt from them, so the
# transforms come back close rather than bit-identical. Both tolerances are far below what a bone
# position or orientation would have to drift by to be visible.
POSITION_TOLERANCE = 1e-4
ROTATION_TOLERANCE = 1e-3

failures = []


def check(label: str, condition: bool) -> None:
    print(("  OK   " if condition else "  FAIL ") + label)
    if not condition:
        failures.append(label)


def quaternion_distance(a, b) -> float:
    # q and -q are the same rotation, so this measures whether the rotation survived, not which of
    # the two representatives was written. The sign convention is asserted separately below - being
    # blind to it here is deliberate, but being blind to it everywhere is how a real bug hid once.
    same = max(abs(x - y) for x, y in zip(a, b))
    flipped = max(abs(x + y) for x, y in zip(a, b))
    return min(same, flipped)


def main() -> None:
    if not SKELETON_CS2.exists():
        raise RuntimeError(f"Skeleton sample not found: {SKELETON_CS2}")

    module = addon_utils.enable("total_war_buildings", default_set=True, persistent=False)
    if module is None:
        raise RuntimeError("addon_utils.enable returned failure")

    from binary.bone_table import read_bone_table, write_bone_table
    from binary.cs2_reader import read_cs2
    from binary.cs2_writer import write_cs2
    from bob import rules
    from extraction.skeleton_extract import extract_skeleton
    from importer import import_file
    from props.properties import NO_BONE_TYPE
    from scene_model.skeleton_builder import build_bone_table, build_skeleton_cs2_document
    from validation.rules import has_blocking_issues, validate_skeleton

    original_document = read_cs2(SKELETON_CS2.read_bytes())
    original_nodes = original_document.scene_root.scene_nodes
    original_table_bytes = SKELETON_BONE_TABLE.read_bytes()
    original_table = read_bone_table(original_table_bytes, "rome_man_game")

    print("=== registration ===")
    # bpy.ops resolves attributes lazily, so hasattr() is true for any name at all - dir() is what
    # actually lists the registered operators.
    registered = set(dir(bpy.ops.tw_buildings))
    for name in ("export_skeleton", "validate_skeleton", "import_file"):
        check(f"tw_buildings.{name} is registered", name in registered)
    check("Bone.tw_bone_type is registered", hasattr(bpy.types.Bone, "tw_bone_type"))
    check("Armature.tw_reference_skeleton is registered", hasattr(bpy.types.Armature, "tw_reference_skeleton"))
    check("there is no separate skeleton import operator", "import_skeleton" not in registered)

    print("=== one import path routes by file contents ===")
    # Deliberately starting in the wrong workflow: importing a skeleton has to switch to it.
    bpy.context.scene.tw_workflow = "BUILDING"
    collection, warnings, kind = import_file(str(SKELETON_CS2), bpy.context)
    check("a skeleton .cs2 is recognised as a skeleton", kind == "SKELETON")
    check("importing it switches to the Skeleton workflow", bpy.context.scene.tw_workflow == "SKELETON")
    check("no import warnings", not warnings)
    check("collection carries the SKELETON role", collection.tw_role == "SKELETON")

    armature_objects = [obj for obj in collection.all_objects if obj.type == "ARMATURE"]
    check("exactly one Armature was created", len(armature_objects) == 1)
    armature_object = armature_objects[0]
    armature = armature_object.data
    check("armature is named after the file", armature_object.name == "rome_man_game")
    check(f"all {len(original_nodes)} scene nodes became bones", len(armature.bones) == len(original_nodes))
    check("bone names match the .cs2 node names",
          {bone.name for bone in armature.bones} == {node.name for node in original_nodes})

    parents = {}
    for index, node in enumerate(original_nodes):
        parents[node.name] = original_nodes[node.parent_index - 1].name if node.parent_index else None
    check("bone hierarchy matches the .cs2 hierarchy",
          all((bone.parent.name if bone.parent else None) == parents[bone.name] for bone in armature.bones))
    check("exactly one root bone", sum(1 for bone in armature.bones if bone.parent is None) == 1)
    check("no bone was renamed on creation", all(bone.name in parents for bone in armature.bones))

    print("=== bone table properties ===")
    listed = [bone for bone in armature.bones if bone.tw_bone_type != NO_BONE_TYPE]
    check(f"{len(original_table.entries)} bones carry a bone type", len(listed) == len(original_table.entries))
    check("bone types match the table",
          all(armature.bones[entry.name].tw_bone_type == entry.bone_type for entry in original_table.entries))
    check("sort orders match the table",
          all(armature.bones[entry.name].tw_bone_sort_order == entry.sort_order for entry in original_table.entries))
    check("bn_hips is the root bone type", armature.bones["bn_hips"].tw_bone_type == "BT_ROOT")
    check("bn_hips is the only sort order 0", [b.name for b in listed if b.tw_bone_sort_order == 0] == ["bn_hips"])
    check("the five weapon bones are floating",
          all(armature.bones[f"bn_weapon_{i:02d}"].tw_bone_type == "BT_FLOATING" for i in range(1, 6)))
    check("ref_ nodes are not in the bone table",
          all(bone.tw_bone_type == NO_BONE_TYPE for bone in armature.bones if bone.name.startswith("ref_")))
    check("LimbLength presence round-tripped",
          all(bone.tw_is_limb == (not bone.name.startswith(("ref_", "null_"))) for bone in armature.bones))
    check("MaxHandle round-tripped",
          armature.bones["bn_hips"].tw_max_handle
          == next(a.value for n in original_nodes if n.name == "bn_hips" for a in n.attributes.integers))
    check("armature header flags round-tripped",
          (armature.tw_bone_table_version, armature.tw_reference_skeleton, armature.tw_cinematic) == (1, True, False))

    check("the collection is named after the file, as a building's is", collection.name == "rome_man_game")

    print("=== rest pose survives the Blender armature ===")
    check("skeleton stands upright and roughly human-sized",
          1.5 < max(bone.head_local.z for bone in armature.bones) < 1.8)
    check("hands are left/right of the origin",
          armature.bones["bn_lefthand"].head_local.x * armature.bones["bn_righthand"].head_local.x < 0)
    check("no bone has zero length", all(bone.length > 0.0 for bone in armature.bones))

    print("=== validation ===")
    issues = validate_skeleton(collection)
    check("the imported skeleton validates clean", not issues)

    print("=== a building .cs2 still routes to the building importer ===")
    building_cs2 = Path(REPO_ROOT) / "Input" / "examples" / "raw_data" / "bridge_stone_1" / "bridge_stone_1.CS2"
    if building_cs2.exists():
        building_collection, _building_warnings, building_kind = import_file(str(building_cs2), bpy.context)
        check("a building .cs2 is recognised as a building", building_kind == "BUILDING")
        check("importing it switches back to the Building workflow",
              bpy.context.scene.tw_workflow == "BUILDING")
        check("it imported as a BUILDING collection", building_collection.tw_role == "BUILDING")
        bpy.context.scene.tw_workflow = "SKELETON"
    else:
        check(f"building sample present at {building_cs2}", False)

    print("=== the exported name is the collection's name ===")
    check("it comes off the collection", extract_skeleton(collection)[0].name == "rome_man_game")
    armature_object.name = "renamed_by_the_artist"
    check("renaming the Armature object does not change it",
          extract_skeleton(collection)[0].name == "rome_man_game")
    collection.name = "some_other_skeleton"
    check("any name is usable", extract_skeleton(collection)[0].name == "some_other_skeleton")
    check("the bone table header follows it",
          build_bone_table(extract_skeleton(collection)[0]).skeleton_name == "some_other_skeleton")
    collection.name = "rome_man_game"
    armature_object.name = "rome_man_game"

    print("=== BOB recipe ===")
    from bob import cli

    skeleton_cs2 = SKELETON_DIR / "rome_man_game.CS2"
    kit_root = str(SKELETON_DIR.parents[2])
    check("skeleton output lands in working_data/animations/skeletons",
          cli.working_data_output_dir(kit_root, skeleton_cs2)
          == Path(kit_root) / "working_data" / "animations" / "skeletons")
    with tempfile.TemporaryDirectory() as fake_kit:
        written = cli.write_configuration(
            fake_kit,
            cli.SKELETON_CONFIGURATION_NAME,
            cli._CS2_CONFIGURATION_TEMPLATE,
            [cli.raw_data_logical_path(kit_root, skeleton_cs2)],
            directory="<raw>/animations/skeletons/",
        )
        configuration = written.read_text(encoding="utf-8")
    check("it uses the Cs2 processor", "<processor>Cs2</processor>" in configuration)
    check("it scans the skeleton's own folder",
          "<directory>&lt;raw&gt;/animations/skeletons/</directory>" in configuration)
    # Path.resolve() normalises to the file's real on-disk casing, so the entry follows the file
    # rather than whatever spelling the caller passed - which is what BOB needs either way.
    check("it selects the skeleton itself as a consumer",
          "<entry>&lt;raw&gt;/animations/skeletons/rome_man_game.cs2</entry>" in configuration)

    print("=== export ===")
    skeleton, export_warnings = extract_skeleton(collection)
    check("no export warnings", not export_warnings)
    check("every bone was extracted", len(skeleton.bones) == len(original_nodes))

    rebuilt = build_skeleton_cs2_document(skeleton, output_path="test.CS2")
    rebuilt_nodes = rebuilt.scene_root.scene_nodes
    check("node order and parent links match the original",
          [(n.name, n.parent_index) for n in rebuilt_nodes] == [(n.name, n.parent_index) for n in original_nodes])
    check("node attributes match the original",
          all(a.attributes == b.attributes for a, b in zip(rebuilt_nodes, original_nodes)))

    worst_position = max(
        max(abs(x - y) for x, y in zip(a.anim.translations[0], b.anim.translations[0]))
        for a, b in zip(rebuilt_nodes, original_nodes)
    )
    worst_rotation = max(
        quaternion_distance(a.anim.rotations[0], b.anim.rotations[0])
        for a, b in zip(rebuilt_nodes, original_nodes)
    )
    print(f"  worst translation drift {worst_position:.3e}, worst rotation drift {worst_rotation:.3e}")
    check("rest-pose translations survive the round trip", worst_position < POSITION_TOLERANCE)
    check("rest-pose rotations survive the round trip", worst_rotation < ROTATION_TOLERANCE)

    check("every exported quaternion uses the w >= 0 representative",
          all(node.anim.rotations[0][3] >= 0.0 for node in rebuilt_nodes))
    source_negative = sum(1 for node in original_nodes if node.anim.rotations[0][3] < 0.0)
    print(f"  {source_negative} source quaternions carry w < 0 and are written as their negation")

    from binary.cs2_templates import SKELETON_SCENE_ROOT_ROTATION, scene_root_rotation_of

    check("the scene root rotation is read back from the file",
          skeleton.scene_root_rotation == scene_root_rotation_of(original_document.scene_root.scene_hierarchy_metadata))
    check("it is the half turn about Y every skeleton carries",
          skeleton.scene_root_rotation == SKELETON_SCENE_ROOT_ROTATION)
    check("the exported scene root block carries it, not the building identity",
          scene_root_rotation_of(rebuilt.scene_root.scene_hierarchy_metadata) == SKELETON_SCENE_ROOT_ROTATION)

    check("the rebuilt .cs2 writes without error", len(write_cs2(rebuilt)) > 0)
    check("the rebuilt .bone_table is byte-identical", write_bone_table(build_bone_table(skeleton)) == original_table_bytes)

    print("=== export writes both files ===")
    from export.skeleton_exporter import export_skeleton

    with tempfile.TemporaryDirectory() as output_dir:
        result = export_skeleton(collection, output_dir, str(SKELETON_DIR.parents[2]))
        check("export reports success", result.success)
        written_cs2 = Path(output_dir) / "rome_man_game.CS2"
        written_table = Path(output_dir) / "rome_man_game.bone_table"
        check("the .CS2 was written", written_cs2.is_file())
        check("the .bone_table sidecar was written beside it", written_table.is_file())
        check("the written .bone_table is byte-identical", written_table.read_bytes() == original_table_bytes)
        check("the written .CS2 reads back with every bone",
              len(read_cs2(written_cs2.read_bytes()).scene_root.scene_nodes) == len(original_nodes))
        check("exporting outside raw_data/animations/skeletons warns about the bone definition lookup",
              any("bone definition" in warning for warning in result.warnings))

    print("=== rules.bob ===")
    check("skeleton rules match CA's own file byte for byte",
          rules._SKELETON_RULES.encode("ascii") == (SKELETON_DIR / "rules.bob").read_bytes())
    with tempfile.TemporaryDirectory() as outside:
        check("no rules.bob is written outside raw_data",
              rules.ensure_skeleton_rules(str(Path(outside) / "kit"), Path(outside) / "x.CS2") is None)

    print("=== validation catches real mistakes ===")
    for bone in armature.bones:
        bone.tw_bone_type = NO_BONE_TYPE
    issues = validate_skeleton(collection)
    check("an empty bone table blocks the export", has_blocking_issues(issues))

    empty_collection = bpy.data.collections.new("Empty Skeleton")
    empty_collection.tw_role = "SKELETON"
    bpy.context.scene.collection.children.link(empty_collection)
    check("a skeleton with no Armature blocks the export", has_blocking_issues(validate_skeleton(empty_collection)))

    second = bpy.data.objects.new("Second", bpy.data.armatures.new("Second"))
    collection.objects.link(second)
    check("two Armatures in one skeleton block the export", has_blocking_issues(validate_skeleton(collection)))

    print()
    if failures:
        print(f"FAILED {len(failures)} check(s):")
        for failure in failures:
            print("   ", failure)
        raise SystemExit(1)
    print("all checks passed")


try:
    main()
except Exception:
    traceback.print_exc()
    sys.exit(1)
