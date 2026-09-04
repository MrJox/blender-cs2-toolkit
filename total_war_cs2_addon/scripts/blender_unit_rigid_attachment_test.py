import shutil
import sys
import traceback
from pathlib import Path

import addon_utils
import bpy

REPO_ROOT = r"C:\Users\Khaiali\source\repos\blender_buildings_plugin"
ASSEMBLY_KIT_ROOT = r"D:\SteamLibrary\steamapps\common\Total War Attila\assembly_kit"

# Its own folder under raw_data/variantmeshes, so the export writes its own rules.bob instead of
# inheriting CA's at VariantModels/ - a weapon needs an empty AnimationType, and CA's names
# rome_man_game. Everything written here is removed again in the finally block.
EXPORT_DIR = Path(ASSEMBLY_KIT_ROOT) / "raw_data" / "variantmeshes" / "blender_unit_rigid_test"
PART_NAME = "blender_rigid_box"

# BOB refuses any mesh whose material has no t_albedo, so the test needs real image files rather
# than the add-on's generated placeholders.
SHADER_TEXTURE_SOURCES = {
    "Diffuse": "test_gray.tga",
    "Normal": "flatnormal.tga",
    "Gloss": "test_gray.tga",
    "Level": "test_gray.tga",
    "Specular": "test_white.tga",
}

if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

failures = []


def check(label: str, condition: bool) -> None:
    print(("  OK   " if condition else "  FAIL ") + label)
    if not condition:
        failures.append(label)


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


# Off the origin and unequal on every axis, so a missing pivot, a swapped axis or a half turn all
# show up in the round trip instead of hiding behind symmetry.
BOX_CENTRE = (0.21, -0.34, 1.05)
BOX_HALF_EXTENTS = (0.05, 0.09, 0.13)


def build_box(name: str, collection: bpy.types.Collection, material: bpy.types.Material, half=None):
    half = half or BOX_HALF_EXTENTS
    corners = [
        (BOX_CENTRE[0] + x * half[0], BOX_CENTRE[1] + y * half[1], BOX_CENTRE[2] + z * half[2])
        for x in (-1, 1)
        for y in (-1, 1)
        for z in (-1, 1)
    ]
    faces = [(0, 1, 3, 2), (4, 6, 7, 5), (0, 4, 5, 1), (2, 3, 7, 6), (0, 2, 6, 4), (1, 5, 7, 3)]
    mesh = bpy.data.meshes.new(name)
    mesh.from_pydata(corners, [], faces)
    uv_layer = mesh.uv_layers.new(name="UVMap")
    for index in range(len(mesh.loops)):
        uv_layer.data[index].uv = ((index % 4) / 3.0, (index % 3) / 2.0)
    mesh.materials.append(material)
    mesh.update()
    obj = bpy.data.objects.new(name, mesh)
    collection.objects.link(obj)
    return obj


def mesh_bounds(obj: bpy.types.Object):
    points = [obj.matrix_world @ vertex.co for vertex in obj.data.vertices]
    return tuple((min(p[a] for p in points), max(p[a] for p in points)) for a in range(3))


def bounds_match(a, b, tolerance: float = 5e-3) -> bool:
    matched = all(abs(x - y) < tolerance for pair_a, pair_b in zip(a, b) for x, y in zip(pair_a, pair_b))
    if not matched:
        print("       bounds differ:")
        print("         got     ", tuple(tuple(round(v, 4) for v in p) for p in a))
        print("         expected", tuple(tuple(round(v, 4) for v in p) for p in b))
    return matched


def main() -> None:
    module = addon_utils.enable("total_war_cs2_addon", default_set=True, persistent=False)
    if module is None:
        raise RuntimeError("addon_utils.enable returned failure")

    from binary import rigid_model_v2_structures as rs
    from binary.rigid_model_v2_reader import read_rigid_model_v2
    from bob.cli import compile_unit_parts, is_bob_running, unit_output_dir
    from export.unit_exporter import export_unit
    from importer import import_file
    from materials.material_builder import create_total_war_material

    if is_bob_running():
        raise RuntimeError("BOB is already open - close it before running this test.")

    bpy.context.scene.tw_workflow = "UNIT"
    # The unit asset carries the name the file exports under; the model collection under it only
    # says which of the two export shapes this is.
    unit = bpy.data.collections.new(PART_NAME)
    unit.tw_role = "UNIT"
    bpy.context.scene.collection.children.link(unit)
    mesh_collection = bpy.data.collections.new(f"{PART_NAME}_mesh")
    mesh_collection.tw_role = "UNIT_MESH"
    mesh_collection.tw_unit_part_kind = "RIGID_ATTACHMENT"
    unit.children.link(mesh_collection)

    material = bpy.data.materials.new("blender_rigid_box_material")
    material.tw_shader_type = "default"
    create_total_war_material(material)
    EXPORT_DIR.mkdir(parents=True, exist_ok=True)
    assign_test_textures(material, EXPORT_DIR, PART_NAME)

    # Two LODs, so the compiled file has to carry a real LOD chain rather than one level.
    lod1 = build_box(f"{PART_NAME}_lod1", mesh_collection, material)
    lod1.tw_lod_index = "LOD01"
    lod2 = build_box(f"{PART_NAME}_lod2", mesh_collection, material, (0.04, 0.08, 0.12))
    lod2.tw_lod_index = "LOD02"

    # Blender Z-up to engine Y-up, the same swap extraction._to_engine_space makes.
    engine_centre = (BOX_CENTRE[0], BOX_CENTRE[2], BOX_CENTRE[1])
    compiled = unit_output_dir(ASSEMBLY_KIT_ROOT) / f"{PART_NAME}.rigid_model_v2"
    try:
        print("=== export ===")
        result = export_unit(unit, str(EXPORT_DIR), ASSEMBLY_KIT_ROOT, bpy.context)
        for warning in result.warnings:
            print(f"       warning: {warning}")
        check("export succeeded", result.success)
        rules_path = EXPORT_DIR / "rules.bob"
        check("a rules.bob was written beside it", rules_path.is_file())
        if rules_path.is_file():
            rules_text = rules_path.read_text(encoding="utf-8")
            print("       rules.bob:", rules_text.replace("\r\n", " | "))
            # A weapon, shield or prop compiles with an empty bone table name, exactly as CA's own
            # shield and crest rules.bob files do (PLAN_units.md 1.8).
            check("this asset gets its own override", f"<Files> = ...{PART_NAME}.cs2" in rules_text)
            animation_types = [
                line.split("=", 1)[1].strip()
                for line in rules_text.splitlines()
                if line.strip().lower().startswith("animationtype")
            ]
            check("every AnimationType in it is empty", animation_types and not any(animation_types))

        print("=== BOB compiles it ===")
        bob_result = compile_unit_parts(ASSEMBLY_KIT_ROOT, result.cs2_paths)
        print("  BOB said:", bob_result.message.replace("\n", " | "))
        check("BOB reported success", bob_result.success)
        check(f"BOB produced {compiled.name}", compiled.is_file())

        if compiled.is_file():
            model = read_rigid_model_v2(compiled.read_bytes())
            check("the compiled file is an Attila rigid_model_v2", model.version == rs.FILE_VERSION_ATTILA)
            check("a rigid attachment part carries no bone table name", model.bone_table_name == "")
            check("both LODs came through", len(model.lods) == 2)
            meshes = [mesh for lod in model.lods for mesh in lod.meshes]
            check("it holds a mesh per LOD", len(meshes) == 2)
            if meshes:
                mesh = meshes[0]
                check("the mesh uses RS_STANDARD_V5", mesh.shader_flags == rs.SHADER_STANDARD_V5)
                check("it uses the standard rigid vertex format",
                      mesh.vertex_format == rs.VERTEX_STANDARD_RIGID)
                check("no vertex carries bone weights",
                      not any(vertex.bone_indices for vertex in mesh.vertices))
                check("it carries no attachment points of its own",
                      mesh.material is not None and not mesh.material.attachment_points)
                # A rigid mesh is stored relative to its pivot, so the pivot has to be the authored
                # centre - it is what the importer adds back to put the mesh where it was modelled.
                check("the compiled pivot is the authored centre",
                      all(abs(a - b) < 1e-3 for a, b in zip(mesh.material.pivot, engine_centre)))

            print("=== it imports back where it was modelled ===")
            imported, _warnings, _kind = import_file(str(compiled), bpy.context)
            imported_object = next(obj for child in imported.children for obj in child.objects)
            check("the round-tripped mesh lands on the original",
                  bounds_match(mesh_bounds(imported_object), mesh_bounds(lod1)))
    finally:
        shutil.rmtree(EXPORT_DIR, ignore_errors=True)
        for path in unit_output_dir(ASSEMBLY_KIT_ROOT).glob(f"{PART_NAME}.*"):
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
