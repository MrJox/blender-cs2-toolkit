import sys
import tempfile
import traceback
from fnmatch import fnmatch
from pathlib import Path

import addon_utils
import bpy

REPO_ROOT = r"C:\Users\Khaiali\source\repos\blender_buildings_plugin"
ASSEMBLY_KIT_ROOT = r"D:\SteamLibrary\steamapps\common\Total War Attila\assembly_kit"
SKELETON_CS2 = Path(ASSEMBLY_KIT_ROOT) / "raw_data" / "animations" / "skeletons" / "rome_man_game.cs2"
SAMPLE_MODEL = Path(REPO_ROOT) / "Input/examples/working_data/variantmeshes/_variantmodels/gondor/armour/gondor_infantry_armour.rigid_model_v2"
SAMPLE_WEAPON = Path(REPO_ROOT) / "Input/examples/working_data/variantmeshes/_variantmodels/gondor/weapons/gondor_sword_01.rigid_model_v2"
SAMPLE_VMD = Path(REPO_ROOT) / "Input/examples/working_data/variantmeshes/_variantmodels/gondor/weapons/gondor_swords.variantmeshdefinition"

if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

# One real filename per supported type, so a pattern that is short enough but wrong still fails.
IMPORTABLE_SAMPLES = (
    "rome_man_game.cs2",
    "gondor_building_5.CS2",
    "gondor_building_5.cs2.parsed",
    "gondor_sword_01.rigid_model_v2",
    "gon_bowmen.variantmeshdefinition",
)

failures = []


def check(label: str, condition: bool) -> None:
    print(("  OK   " if condition else "  FAIL ") + label)
    if not condition:
        failures.append(label)


def new_material(name: str, shader_type: str) -> bpy.types.Material:
    from materials.material_builder import create_total_war_material

    material = bpy.data.materials.new(name)
    material.tw_shader_type = shader_type
    create_total_war_material(material)
    return material


def add_box(name: str, collection: bpy.types.Collection, material: bpy.types.Material, location=(0.0, 0.0, 0.0)):
    mesh = bpy.data.meshes.new(name)
    size = 0.1
    corners = [
        (x * size + location[0], y * size + location[1], z * size + location[2])
        for x in (-1, 1)
        for y in (-1, 1)
        for z in (-1, 1)
    ]
    faces = [
        (0, 1, 3, 2), (4, 6, 7, 5), (0, 4, 5, 1), (2, 3, 7, 6), (0, 2, 6, 4), (1, 5, 7, 3),
    ]
    mesh.from_pydata(corners, [], faces)
    mesh.uv_layers.new(name="UVMap")
    mesh.materials.append(material)
    mesh.update()
    obj = bpy.data.objects.new(name, mesh)
    collection.objects.link(obj)
    return obj


def build_skeleton(name: str) -> bpy.types.Object:
    armature = bpy.data.armatures.new(name)
    armature_object = bpy.data.objects.new(name, armature)
    collection = bpy.data.collections.new(name)
    collection.tw_role = "SKELETON"
    bpy.context.scene.collection.children.link(collection)
    collection.objects.link(armature_object)

    bpy.context.view_layer.objects.active = armature_object
    bpy.ops.object.mode_set(mode="EDIT")
    root = armature.edit_bones.new("bn_root")
    root.head = (0.0, 0.0, 0.0)
    root.tail = (0.0, 0.0, 0.5)
    child = armature.edit_bones.new("bn_child")
    child.head = (0.0, 0.0, 0.5)
    child.tail = (0.0, 0.0, 1.0)
    child.parent = root
    bpy.ops.object.mode_set(mode="OBJECT")
    armature.bones["bn_root"].tw_bone_type = "BT_ROOT"
    armature.bones["bn_root"].tw_bone_sort_order = 0
    armature.bones["bn_child"].tw_bone_type = "BT_CORE"
    return armature_object


# Two levels: a unit asset named after the file it exports as, holding models named after the
# meshes inside that file. The Model Type lives on the model.
def new_asset(asset_name: str, kind: str, model_name: str):
    unit = bpy.data.collections.new(asset_name)
    unit.tw_role = "UNIT"
    bpy.context.scene.collection.children.link(unit)
    model = bpy.data.collections.new(model_name)
    model.tw_role = "UNIT_MESH"
    model.tw_unit_part_kind = kind
    unit.children.link(model)
    return unit, model


def build_unit(armature_object: bpy.types.Object):
    unit, body_mesh = new_asset("test_body", "WEIGHTED", "test_body_mesh")

    material = new_material("test_weighted", "weighted")
    body = add_box("test_body_lod1", body_mesh, material, location=(0.0, 0.0, 0.5))
    for bone in armature_object.data.bones:
        group = body.vertex_groups.new(name=bone.name)
        group.add([v.index for v in body.data.vertices], 0.5, "REPLACE")
    modifier = body.modifiers.new(name="Armature", type="ARMATURE")
    modifier.object = armature_object

    point = bpy.data.objects.new("weapon_01", None)
    point.tw_attachment_point_name = "weapon_01"
    unit.objects.link(point)
    point.parent = armature_object
    point.parent_type = "BONE"
    point.parent_bone = "bn_child"
    point.matrix_world = point.matrix_world  # settle the parent inverse

    sword_unit, sword_mesh = new_asset("test_sword", "RIGID_ATTACHMENT", "test_sword_mesh")
    add_box("test_sword_lod1", sword_mesh, new_material("test_rigid", "default"))
    return unit, sword_unit, body_mesh, body


def main() -> None:
    module = addon_utils.enable("total_war_cs2_addon", default_set=True, persistent=False)
    if module is None:
        raise RuntimeError("addon_utils.enable returned failure")

    from binary.cs2_reader import read_cs2
    from binary.cs2_writer import write_cs2
    from bob.rules import unit_rules_text
    from export.unit_exporter import export_unit
    from importer import import_file
    from naming.naming import attachment_point_node_name, unit_lod_node_name
    from scene_model.skeleton_models import compiled_bone_order
    from ui.operators import IMPORT_FILTER_GLOB, MAX_FILTER_GLOB_PATTERN
    from validation.rules import has_blocking_issues, validate_unit

    bpy.context.scene.tw_workflow = "UNIT"
    armature_object = build_skeleton("test_skeleton")
    unit, sword_unit, body_model, body = build_unit(armature_object)

    print("=== validation ===")
    issues = validate_unit(unit) + validate_unit(sword_unit)
    for issue in issues:
        print(f"       {issue.severity}: {issue.message}")
    check("a well-formed unit validates with no blocking issues", not has_blocking_issues(issues))

    # One asset compiles to one file, which carries a single shader family and bone table.
    spare = bpy.data.collections.new("spare_model")
    spare.tw_role = "UNIT_MESH"
    spare.tw_unit_part_kind = "RIGID_ATTACHMENT"
    unit.children.link(spare)
    check("mixing Weighted and Rigid models in one asset is blocked", has_blocking_issues(validate_unit(unit)))
    unit.children.unlink(spare)
    bpy.data.collections.remove(spare)

    print("=== LOD chain ===")
    # BOB compiles all of these, so they warn rather than block - see _validate_lod_chain.
    def lod_warnings(collection):
        return [i for i in validate_unit(collection) if "LOD" in i.message and i.severity == "WARNING"]

    check("a chain starting at LOD 1 says nothing", not lod_warnings(unit))
    second = add_box("test_body_lod2", body_model, body.data.materials[0], location=(0.0, 0.0, 0.5))
    second.tw_lod_index = "LOD04"
    for group in body.vertex_groups:
        second.vertex_groups.new(name=group.name).add(
            [v.index for v in second.data.vertices], 0.5, "REPLACE"
        )
    second.modifiers.new(name="Armature", type="ARMATURE").object = armature_object
    check("a gap in the chain warns", any("skips LOD" in i.message for i in lod_warnings(unit)))
    check("a gap does not block the export", not has_blocking_issues(validate_unit(unit)))
    body.tw_lod_index = "LOD02"
    check("no LOD 1 warns", any("no LOD 1" in i.message for i in lod_warnings(unit)))
    body.tw_lod_index = "LOD01"
    second.tw_lod_index = "LOD02"
    check("a contiguous chain is quiet again", not lod_warnings(unit))
    bpy.data.objects.remove(second)

    body.data.materials[0].tw_shader_type = "default"
    check("a weighted mesh with a non-weighted shader is blocked", has_blocking_issues(validate_unit(unit)))
    body.data.materials[0].tw_shader_type = "weighted"

    stray = bpy.data.objects.new("stray_point", None)
    stray.tw_attachment_point_name = "crest_centre"
    unit.objects.link(stray)
    check("an unparented attachment point is blocked", has_blocking_issues(validate_unit(unit)))
    bpy.data.objects.remove(stray)

    print("=== export ===")
    with tempfile.TemporaryDirectory() as directory:
        results = [export_unit(asset, directory, ASSEMBLY_KIT_ROOT, bpy.context) for asset in (unit, sword_unit)]
        for result in results:
            for warning in result.warnings:
                print(f"       warning: {warning}")
        check("export succeeded", all(result.success for result in results))
        paths = [path for result in results for path in result.cs2_paths]
        check("one .CS2 per unit asset", len(paths) == 2)

        by_name = {path.stem: path for path in paths}
        check("each file is named after its unit asset", set(by_name) == {"test_body", "test_sword"})

        for name, path in by_name.items():
            data = path.read_bytes()
            check(f"{name}.CS2 round-trips byte-exactly through the reader and writer",
                  write_cs2(read_cs2(data)) == data)

        weighted_document = read_cs2(by_name["test_body"].read_bytes())
        check("the weighted part holds one WEIGHTED_MODEL node", len(weighted_document.weighted_models) == 1)
        check("its mesh node is named <mesh>_lod1",
              weighted_document.weighted_models[0].node_name == unit_lod_node_name("test_body_mesh", 1))
        check("the whole skeleton tree is embedded",
              [node.name for node in weighted_document.scene_root.scene_nodes[:2]] == ["bn_root", "bn_child"])

        chunk = weighted_document.weighted_models[0].geometry_chunks[0]
        check("every vertex carries two influences",
              all(len(vertex.bone_weights) == 2 for vertex in chunk.vertices))
        check("weights sum to one",
              all(abs(sum(w.weight for w in v.bone_weights) - 1.0) < 1e-5 for v in chunk.vertices))
        bone_ids = {w.bone_id for v in chunk.vertices for w in v.bone_weights}
        # 1-based into the file's own scene_nodes, the convention BOB's own compile settled.
        check("bone ids are 1-based indices into the file's own scene nodes", bone_ids == {1, 2})
        check("the weighted chunk carries no vertex colour channel", chunk.vertex_color_channel_flags == 0)

        attachment_nodes = [node for node in weighted_document.rigid_models if node.node_name.startswith("AP_")]
        check("the attachment point is authored as an AP_ rigid node",
              [node.node_name for node in attachment_nodes] == [attachment_point_node_name("weapon_01")])
        ap_scene_node = weighted_document.scene_root.scene_nodes[attachment_nodes[0].node_index - 1]
        check("the AP node is parented to its bone", ap_scene_node.parent_index == 2)

        rigid_document = read_cs2(by_name["test_sword"].read_bytes())
        check("the rigid part holds no weighted models", not rigid_document.weighted_models)
        check("the rigid part holds one rigid model node", len(rigid_document.rigid_models) == 1)
        check("a rigid part embeds no skeleton", not rigid_document.scene_root.scene_nodes[:1] or
              rigid_document.scene_root.scene_nodes[0].name == unit_lod_node_name("test_sword_mesh", 1))
        check("a unit part carries the identity scene root rotation",
              read_cs2(by_name["test_body"].read_bytes()).scene_root.scene_hierarchy_metadata
              == rigid_document.scene_root.scene_hierarchy_metadata)

    print("=== rules.bob ===")
    text = unit_rules_text([("test_body", "test_skeleton"), ("test_sword", "")])
    check("each asset gets its own override",
          "<Files> = ...test_body.cs2" in text and "<Files> = ...test_sword.cs2" in text)
    check("the weighted one names its skeleton", "AnimationType = test_skeleton" in text)

    print("=== the single import path ===")
    # Blender registers an operator under a name built from its bl_idname, not its class name.
    importers = [
        name
        for name in dir(bpy.types)
        if name.startswith("TW_BUILDINGS_OT_import") and name != "TW_BUILDINGS_OT_import_report"
    ]
    check("only one operator imports files", importers == ["TW_BUILDINGS_OT_import_file"])
    patterns = IMPORT_FILTER_GLOB.split(";")
    # Every ;-separated pattern has to survive Blender's char[16] copy, or the browser lists no
    # files at all - which is exactly what "*.rigid_model_v2" and "*.variantmeshdefinition" did.
    check("every filter pattern is short enough for Blender to apply",
          all(len(pattern) <= MAX_FILTER_GLOB_PATTERN for pattern in patterns))
    for sample in IMPORTABLE_SAMPLES:
        check(f"the file browser lists {sample}",
              any(fnmatch(sample, pattern) for pattern in patterns))

    print("=== rigid_model_v2 import ===")
    if SAMPLE_WEAPON.is_file():
        weapon_collection, warnings, kind = import_file(str(SAMPLE_WEAPON), bpy.context)
        for warning in warnings:
            print(f"       warning: {warning}")
        check("the router recognises a .rigid_model_v2 and switches workflow",
              kind == "UNIT PART" and bpy.context.scene.tw_workflow == "UNIT")
        weapon_model = next(c for c in weapon_collection.children if c.tw_role == "UNIT_MESH")
        check("a compiled weapon imports as a Rigid Model",
              weapon_model.tw_unit_part_kind == "RIGID_ATTACHMENT")
        check("its four LODs each become an object in the model", len(weapon_model.objects) == 4)
    else:
        check(f"weapon sample present at {SAMPLE_WEAPON}", False)

    if SAMPLE_MODEL.is_file() and SKELETON_CS2.is_file():
        skeleton_collection, _warnings, skeleton_kind = import_file(str(SKELETON_CS2), bpy.context)
        check("the router still recognises a skeleton .cs2", skeleton_kind == "SKELETON")
        bpy.context.scene.tw_workflow = "UNIT"
        body_collection, warnings, _kind = import_file(str(SAMPLE_MODEL), bpy.context)
        for warning in warnings:
            print(f"       warning: {warning}")
        check("a compiled body imports as a weighted part", body_collection.tw_unit_part_kind == "WEIGHTED")
        imported = next(iter(body_collection.children)).objects[0]
        check("its vertex groups carry real bone names",
              all(not group.name.startswith("bone_") for group in imported.vertex_groups))
        check("it is bound to the imported skeleton",
              any(modifier.type == "ARMATURE" for modifier in imported.modifiers))
        points = {obj.tw_attachment_point_name for obj in body_collection.objects if obj.tw_attachment_point_name}
        check("its five weapon attachment points come across",
              points == {f"weapon_0{index}" for index in range(1, 6)})

        armature = next(obj for obj in skeleton_collection.all_objects if obj.type == "ARMATURE")
        from importer.rigid_model_v2_importer import bone_names_by_compiled_index

        order = bone_names_by_compiled_index(armature)
        check("the compiled bone order matches PLAN_units.md 1.3",
              order[:6] == ["bn_hips"] + [f"bn_weapon_0{index}" for index in range(1, 6)]
              and order[23] == "bn_head")
    else:
        check(f"body sample and skeleton present", False)

    print("=== variantmeshdefinition import ===")
    if SAMPLE_VMD.is_file():
        from importer.vmd_importer import resolve_asset_path, working_data_root

        root = working_data_root(SAMPLE_VMD)
        check("the working_data root is found", root is not None)
        check("a mixed-separator reference resolves case-insensitively",
              resolve_asset_path(root, "VariantMeshes/_VariantModels/gondor\\weapons/gondor_sword_01.rigid_model_v2")
              is not None)
        assembled, warnings, vmd_kind = import_file(str(SAMPLE_VMD), bpy.context)
        for warning in warnings:
            print(f"       warning: {warning}")
        check("the router recognises a .variantmeshdefinition", vmd_kind == "VARIANT MESH")
        slot = next(iter(assembled.children))
        check("the definition's four swords import into one slot collection",
              len(assembled.children) == 1 and len(slot.children) == 4)
        check("only the first alternative is left visible",
              [child.hide_viewport for child in slot.children].count(False) == 1)
    else:
        check(f"VMD sample present at {SAMPLE_VMD}", False)

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
