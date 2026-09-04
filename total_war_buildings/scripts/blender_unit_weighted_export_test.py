import shutil
import sys
import traceback
from pathlib import Path

import addon_utils
import bpy

REPO_ROOT = r"C:\Users\Khaiali\source\repos\blender_buildings_plugin"
ASSEMBLY_KIT_ROOT = r"D:\SteamLibrary\steamapps\common\Total War Attila\assembly_kit"
SKELETON_CS2 = Path(ASSEMBLY_KIT_ROOT) / "raw_data" / "animations" / "skeletons" / "rome_man_game.cs2"

# A folder of its own under raw_data/variantmeshes, so the export writes its own rules.bob rather
# than inheriting CA's at VariantModels/ - the AnimationType that rules.bob carries is the whole
# point of the test. Everything written here is removed again in the finally block.
EXPORT_DIR = Path(ASSEMBLY_KIT_ROOT) / "raw_data" / "variantmeshes" / "blender_unit_weighted_test"
PART_NAME = "blender_weighted_box"
# A rigid part exported alongside, so the run also proves the batch requirement: several parts in
# one folder, one BOB run, and a rules.bob whose default AnimationType names the skeleton with a
# per-file override for the one part that needs an empty one.
RIGID_PART_NAME = "blender_batch_prop"
SKELETON_NAME = "rome_man_game"

if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

failures = []


def check(label: str, condition: bool) -> None:
    print(("  OK   " if condition else "  FAIL ") + label)
    if not condition:
        failures.append(label)


# BOB refuses a weighted mesh whose material has no t_albedo ("Error: invalid texture list"), so
# the test needs real image files rather than the add-on's generated placeholders.
SHADER_TEXTURE_SOURCES = {
    "Diffuse": "test_gray.tga",
    "Normal": "flatnormal.tga",
    "Gloss": "test_gray.tga",
    "Level": "test_gray.tga",
    "Specular": "test_white.tga",
}


def assign_test_textures(material: bpy.types.Material, export_dir: Path, stem: str) -> None:
    from materials.material_builder import TW_PLACEHOLDER_MARKER

    source_dir = Path(ASSEMBLY_KIT_ROOT) / "max_exporter" / "max_shader"
    texture_dir = export_dir / "tex"
    texture_dir.mkdir(parents=True, exist_ok=True)
    for node_name, source in SHADER_TEXTURE_SOURCES.items():
        target = texture_dir / f"{stem}_{node_name.lower()}.tga"
        shutil.copyfile(source_dir / source, target)
        image = bpy.data.images.load(str(target), check_existing=True)
        if TW_PLACEHOLDER_MARKER in image:
            del image[TW_PLACEHOLDER_MARKER]
        material.node_tree.nodes[node_name].image = image


# Off the bone's own centre line and unequal on every axis, so the half turn BOB applies from the
# skeleton shows up in the round trip instead of hiding behind symmetry - a box sat squarely on
# bn_spine1 looks identical flipped.
BOX_OFFSET = (0.15, 0.25, 0.0)
BOX_HALF_EXTENTS = (0.05, 0.09, 0.13)


def build_box(name: str, collection: bpy.types.Collection, material: bpy.types.Material, centre) -> bpy.types.Object:
    corners = [
        (
            centre[0] + x * BOX_HALF_EXTENTS[0],
            centre[1] + y * BOX_HALF_EXTENTS[1],
            centre[2] + z * BOX_HALF_EXTENTS[2],
        )
        for x in (-1, 1)
        for y in (-1, 1)
        for z in (-1, 1)
    ]
    faces = [(0, 1, 3, 2), (4, 6, 7, 5), (0, 4, 5, 1), (2, 3, 7, 6), (0, 2, 6, 4), (1, 5, 7, 3)]
    mesh = bpy.data.meshes.new(name)
    mesh.from_pydata(corners, [], faces)
    uv_layer = mesh.uv_layers.new(name="UVMap")
    for index, loop in enumerate(mesh.loops):
        uv_layer.data[index].uv = ((index % 4) / 3.0, (index % 3) / 2.0)
    mesh.materials.append(material)
    mesh.update()
    obj = bpy.data.objects.new(name, mesh)
    collection.objects.link(obj)
    return obj


def axis_bounds(points):
    return tuple((min(p[a] for p in points), max(p[a] for p in points)) for a in range(3))


def rounded(bounds):
    return tuple(tuple(round(v, 4) for v in pair) for pair in bounds)


def close(a, b, tolerance: float = 5e-3) -> bool:
    return all(abs(x - y) < tolerance for x, y in zip(a, b))


def mesh_bounds(obj: bpy.types.Object):
    points = [obj.matrix_world @ vertex.co for vertex in obj.data.vertices]
    return axis_bounds(points)


def bounds_match(a, b, tolerance: float = 5e-3) -> bool:
    matched = all(close(pair_a, pair_b, tolerance) for pair_a, pair_b in zip(a, b))
    if not matched:
        print("       bounds differ:")
        print("         got     ", rounded(a))
        print("         expected", rounded(b))
    return matched


def new_asset(asset_name: str, kind: str):
    # Two levels: the asset names the file, the model names the mesh inside it and carries the type.
    unit = bpy.data.collections.new(asset_name)
    unit.tw_role = "UNIT"
    bpy.context.scene.collection.children.link(unit)
    model = bpy.data.collections.new(f"{asset_name}_mesh")
    model.tw_role = "UNIT_MESH"
    model.tw_unit_part_kind = kind
    unit.children.link(model)
    return unit, model


def main() -> None:
    if not SKELETON_CS2.is_file():
        raise RuntimeError(f"Skeleton sample not found: {SKELETON_CS2}")

    module = addon_utils.enable("total_war_buildings", default_set=True, persistent=False)
    if module is None:
        raise RuntimeError("addon_utils.enable returned failure")

    from binary import rigid_model_v2_structures as rs
    from binary.rigid_model_v2_reader import read_rigid_model_v2
    from bob.cli import compile_unit_parts, is_bob_running, unit_output_dir
    from export.unit_exporter import export_unit
    from binary.cs2_reader import read_cs2
    from extraction.skeleton_extract import extract_skeleton_from_armature
    from importer import import_file
    from materials.material_builder import create_total_war_material
    from scene_model.skeleton_models import compiled_bone_order

    if is_bob_running():
        raise RuntimeError("BOB is already open - close it before running this test.")

    skeleton_collection, _warnings, _kind = import_file(str(SKELETON_CS2), bpy.context)
    check("the skeleton imported under its own name", skeleton_collection.name == SKELETON_NAME)
    armature_object = next(obj for obj in skeleton_collection.all_objects if obj.type == "ARMATURE")

    bpy.context.scene.tw_workflow = "UNIT"
    # One unit asset per exported file, named after the asset - the model collection under it only
    # says which of the two export shapes it is.
    unit, mesh_collection = new_asset(PART_NAME, "WEIGHTED")

    material = bpy.data.materials.new("blender_weighted_box_material")
    material.tw_shader_type = "weighted"
    create_total_war_material(material)
    EXPORT_DIR.mkdir(parents=True, exist_ok=True)
    assign_test_textures(material, EXPORT_DIR, PART_NAME)

    # Sat on the spine so the two bones it is weighted to are real game bones, not helper nodes.
    spine = armature_object.data.bones["bn_spine1"]
    spine2 = armature_object.data.bones["bn_spine2"]
    head = armature_object.matrix_world @ spine.head_local
    centre = (head[0] + BOX_OFFSET[0], head[1] + BOX_OFFSET[1], head[2] + BOX_OFFSET[2])
    obj = build_box(f"{PART_NAME}_lod1", mesh_collection, material, centre)
    for bone in (spine, spine2):
        group = obj.vertex_groups.new(name=bone.name)
        group.add([vertex.index for vertex in obj.data.vertices], 0.5, "REPLACE")
    modifier = obj.modifiers.new(name="Armature", type="ARMATURE")
    modifier.object = armature_object

    point = bpy.data.objects.new("weapon_01", None)
    point.tw_attachment_point_name = "weapon_01"
    unit.objects.link(point)
    point.parent = armature_object
    point.parent_type = "BONE"
    point.parent_bone = "bn_weapon_01"

    rigid_unit, rigid_mesh_collection = new_asset(RIGID_PART_NAME, "RIGID_ATTACHMENT")
    rigid_material = bpy.data.materials.new("blender_batch_prop_material")
    rigid_material.tw_shader_type = "default"
    create_total_war_material(rigid_material)
    assign_test_textures(rigid_material, EXPORT_DIR, RIGID_PART_NAME)
    build_box(f"{RIGID_PART_NAME}_lod1", rigid_mesh_collection, rigid_material, (0.0, 0.0, 0.0))

    skeleton, _skeleton_warnings = extract_skeleton_from_armature(armature_object, SKELETON_NAME)
    compiled = unit_output_dir(ASSEMBLY_KIT_ROOT) / f"{PART_NAME}.rigid_model_v2"
    rigid_compiled = unit_output_dir(ASSEMBLY_KIT_ROOT) / f"{RIGID_PART_NAME}.rigid_model_v2"
    try:
        EXPORT_DIR.mkdir(parents=True, exist_ok=True)
        print("=== export ===")
        results = [
            export_unit(asset, str(EXPORT_DIR), ASSEMBLY_KIT_ROOT, bpy.context)
            for asset in (unit, rigid_unit)
        ]
        result = results[0]
        for entry in results:
            for warning in entry.warnings:
                print(f"       warning: {warning}")
        check("export succeeded", all(entry.success for entry in results))
        cs2_paths = [path for entry in results for path in entry.cs2_paths]
        check("both assets exported", len(cs2_paths) == 2)
        rules_path = EXPORT_DIR / "rules.bob"
        check("a rules.bob was written beside it", rules_path.is_file())
        if rules_path.is_file():
            # Bytes, not read_text: universal newlines would turn the file's CRLF into LF and the
            # CRLF-sensitive checks below would silently never match.
            rules_text = rules_path.read_bytes().decode("ascii")
            print("       rules.bob:", rules_text.replace(chr(13) + chr(10), " | "))
            check("the weighted asset's override names the skeleton",
                  f"<Files> = ...{PART_NAME}.cs2\r\n\tAnimationType = {SKELETON_NAME}" in rules_text)
            check("the rigid asset's override is empty",
                  f"<Files> = ...{RIGID_PART_NAME}.cs2\r\n\tAnimationType = \r\n" in rules_text)

        print("=== BOB compiles it ===")
        # Still one BOB run for both files - the batch capability the Cs2 configuration provides.
        bob_result = compile_unit_parts(ASSEMBLY_KIT_ROOT, cs2_paths)
        print("  BOB said:", bob_result.message.replace("\n", " | "))
        check("BOB reported success", bob_result.success)
        check(f"BOB produced {compiled.name}", compiled.is_file())
        check("one BOB run compiled both parts", rigid_compiled.is_file())
        if rigid_compiled.is_file():
            check("the rigid part compiled with an empty bone table name",
                  read_rigid_model_v2(rigid_compiled.read_bytes()).bone_table_name == "")

        if compiled.is_file():
            model = read_rigid_model_v2(compiled.read_bytes())
            check("the compiled file is an Attila rigid_model_v2", model.version == rs.FILE_VERSION_ATTILA)
            check("its bone table name is the skeleton", model.bone_table_name == SKELETON_NAME)
            meshes = [mesh for lod in model.lods for mesh in lod.meshes]
            check("it holds at least one mesh", bool(meshes))
            if meshes:
                mesh = meshes[0]
                check("the mesh uses RS_WEIGHTED_V5", mesh.shader_flags == rs.SHADER_WEIGHTED_V5)
                check("it uses the 2-bone weighted vertex format",
                      mesh.vertex_format == rs.VERTEX_WEIGHTED_2_BONES)
                bone_indices = {index for vertex in mesh.vertices for index in vertex.bone_indices}
                order = compiled_bone_order(skeleton)
                expected = {order.index("bn_spine1"), order.index("bn_spine2")}
                print("       compiled bone indices:", sorted(bone_indices), "expected", sorted(expected))
                # The check that caught the 1-based BoneWeight.bone_id: written 0-based these came
                # out as bn_spine/bn_spine1, one bone too early in each chain.
                check("the vertices land on the bones they were painted to", bone_indices == expected)
                points = {point.name: point for point in mesh.material.attachment_points} if mesh.material else {}
                print("       compiled attachment points:", sorted(points))
                check("the authored attachment point survives", "weapon_01" in points)
                if "weapon_01" in points:
                    check("it targets the bone it was parented to",
                          points["weapon_01"].bone_index == order.index("bn_weapon_01"))

                # The half turn about Y that PLAN_units.md 1.4 measured, here from BOB's own output:
                # engine X and Z come back negated and Y untouched. This is what the importer undoes.
                authored = read_cs2((EXPORT_DIR / f"{PART_NAME}.CS2").read_bytes())
                node = next(n for n in authored.weighted_models if n.node_name.endswith("_lod1"))
                authored_positions = [v.position for c in node.geometry_chunks for v in c.vertices]
                authored_bounds = axis_bounds(authored_positions)
                compiled_bounds = axis_bounds([v.position for v in mesh.vertices])
                print(f"       authored engine bounds {rounded(authored_bounds)}")
                print(f"       compiled bounds        {rounded(compiled_bounds)}")
                check("BOB negates engine X and Z and leaves Y alone",
                      close(compiled_bounds[0], (-authored_bounds[0][1], -authored_bounds[0][0]))
                      and close(compiled_bounds[1], authored_bounds[1])
                      and close(compiled_bounds[2], (-authored_bounds[2][1], -authored_bounds[2][0])))
                check("a weighted mesh carries no pivot",
                      all(abs(axis) < 1e-6 for axis in mesh.material.pivot))

            print("=== it imports back where it was modelled ===")
            imported, _warnings, _kind = import_file(str(compiled), bpy.context)
            imported_object = next(obj for child in imported.children for obj in child.objects)
            check("the round-tripped mesh lands on the original",
                  bounds_match(mesh_bounds(imported_object), mesh_bounds(obj)))
            check("its vertex groups are the bones it was painted to",
                  {group.name for group in imported_object.vertex_groups} == {"bn_spine1", "bn_spine2"})
    finally:
        shutil.rmtree(EXPORT_DIR, ignore_errors=True)
        for stem in (PART_NAME, RIGID_PART_NAME):
            for path in unit_output_dir(ASSEMBLY_KIT_ROOT).glob(f"{stem}.*"):
                try:
                    path.unlink()
                except OSError:
                    pass

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
