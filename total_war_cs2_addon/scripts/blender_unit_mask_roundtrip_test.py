import shutil
import sys
import traceback
from pathlib import Path

import addon_utils
import bpy

REPO_ROOT = r"C:\Users\Khaiali\source\repos\blender_buildings_plugin"
ASSEMBLY_KIT_ROOT = r"D:\SteamLibrary\steamapps\common\Total War Attila\assembly_kit"
SKELETON_CS2 = Path(ASSEMBLY_KIT_ROOT) / "raw_data" / "animations" / "skeletons" / "rome_man_game.cs2"
# Two folders of their own under raw_data/variantmeshes - one BOB run per folder - removed again at
# the end.
EXPORT_DIR = Path(ASSEMBLY_KIT_ROOT) / "raw_data" / "variantmeshes" / "blender_unit_mask_test"
REEXPORT_DIR = Path(ASSEMBLY_KIT_ROOT) / "raw_data" / "variantmeshes" / "blender_unit_mask_test_re"

SHADER_TEXTURE_SOURCES = {
    "Diffuse": "test_gray.tga",
    "Normal": "flatnormal.tga",
    "Gloss": "test_gray.tga",
    "Level": "test_gray.tga",
    "Specular": "test_white.tga",
}

FACTION_MASK = 3
SKIN_MASK = 10

# part name -> (shader, kind, authored Tint Mask stems, compiled mask slot, compiled mask file)
PARTS = {
    "mask_rigid": ("default", "RIGID_ATTACHMENT", ("mask_rigid_mask1", "mask_rigid_mask2", "mask_rigid_mask3"),
                   FACTION_MASK, "mask_rigid_mask.dds"),
    "mask_weighted": ("weighted", "WEIGHTED", ("mask_weighted_mask1", "mask_weighted_mask2", "mask_weighted_mask3"),
                      FACTION_MASK, "mask_weighted_mask.dds"),
    # Left untouched: the export fills test_black.tga, which BOB compiles to test_mask.dds.
    "mask_skin": ("weighted_skin", "WEIGHTED", (), SKIN_MASK, "test_mask.dds"),
}

if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

failures = []


def check(label: str, condition: bool) -> None:
    print(("  OK   " if condition else "  FAIL ") + label)
    if not condition:
        failures.append(label)


def load(path: Path) -> bpy.types.Image:
    from materials.material_builder import TW_PLACEHOLDER_MARKER

    image = bpy.data.images.load(str(path), check_existing=True)
    if TW_PLACEHOLDER_MARKER in image:
        del image[TW_PLACEHOLDER_MARKER]
    return image


def build_part(name: str, shader: str, kind: str, masks: tuple, armature: bpy.types.Object) -> bpy.types.Collection:
    from materials.material_builder import create_total_war_material

    unit = bpy.data.collections.new(name)
    unit.tw_role = "UNIT"
    bpy.context.scene.collection.children.link(unit)
    model = bpy.data.collections.new(f"{name}_mesh")
    model.tw_role = "UNIT_MESH"
    model.tw_unit_part_kind = kind
    unit.children.link(model)

    material = bpy.data.materials.new(f"{name}_material")
    material.tw_shader_type = shader
    create_total_war_material(material)
    texture_dir = EXPORT_DIR / "tex"
    texture_dir.mkdir(parents=True, exist_ok=True)
    source_dir = Path(ASSEMBLY_KIT_ROOT) / "max_exporter" / "max_shader"
    for node_name, source in SHADER_TEXTURE_SOURCES.items():
        target = texture_dir / f"{name}_{node_name.lower()}.tga"
        shutil.copyfile(source_dir / source, target)
        material.node_tree.nodes[node_name].image = load(target)
    for index, stem in enumerate(masks, 1):
        target = texture_dir / f"{stem}.tga"
        shutil.copyfile(source_dir / "test_black.tga", target)
        material.node_tree.nodes[f"Tint Mask {index}"].image = load(target)

    mesh = bpy.data.meshes.new(f"{name}_lod1")
    corners = [(x * 0.05, 0.25 + y * 0.09, 1.2 + z * 0.13) for x in (-1, 1) for y in (-1, 1) for z in (-1, 1)]
    faces = [(0, 1, 3, 2), (4, 6, 7, 5), (0, 4, 5, 1), (2, 3, 7, 6), (0, 2, 6, 4), (1, 5, 7, 3)]
    mesh.from_pydata(corners, [], faces)
    uv_layer = mesh.uv_layers.new(name="UVMap")
    for index in range(len(mesh.loops)):
        uv_layer.data[index].uv = ((index % 4) / 3.0, (index % 3) / 2.0)
    mesh.materials.append(material)
    obj = bpy.data.objects.new(f"{name}_lod1", mesh)
    model.objects.link(obj)
    if kind == "WEIGHTED":
        group = obj.vertex_groups.new(name="bn_spine1")
        group.add([vertex.index for vertex in mesh.vertices], 1.0, "REPLACE")
        obj.modifiers.new(name="Armature", type="ARMATURE").object = armature
    return unit


def compiled_textures(path: Path) -> dict[int, str]:
    from binary.rigid_model_v2_reader import read_rigid_model_v2

    model = read_rigid_model_v2(path.read_bytes())
    return {texture.texture_id: texture.path for texture in model.lods[0].meshes[0].material.textures}


def cs2_masks(path: Path) -> list[str]:
    from binary.cs2_reader import read_cs2

    found = []

    def walk(node, depth=0):
        if depth > 12:
            return
        material = getattr(node, "directx_material", None)
        if material is not None:
            found.extend(
                Path(t.texture_path.replace("\\", "/")).name for t in material.textures if t.texture_name.startswith("t_mask")
            )
            return
        if isinstance(node, list):
            for child in node:
                walk(child, depth + 1)
        elif hasattr(node, "__dataclass_fields__"):
            for field in node.__dataclass_fields__:
                walk(getattr(node, field), depth + 1)

    walk(read_cs2(path.read_bytes()))
    return found


def export_units(units: list, directory: Path) -> list[Path]:
    from export.unit_exporter import export_unit

    directory.mkdir(parents=True, exist_ok=True)
    results = [export_unit(unit, str(directory), ASSEMBLY_KIT_ROOT, bpy.context) for unit in units]
    check(f"export into {directory.name} succeeded", all(result.success for result in results))
    return [Path(path) for entry in results for path in entry.cs2_paths]


def compile_parts(cs2_paths: list[Path], directory: Path) -> bool:
    from bob.cli import compile_unit_parts

    result = compile_unit_parts(ASSEMBLY_KIT_ROOT, cs2_paths)
    check(f"BOB compiled {directory.name}", result.success)
    if not result.success:
        print("  BOB said:", result.message.replace("\n", " | "))
    return result.success


def main() -> None:
    module = addon_utils.enable("total_war_cs2_addon", default_set=True, persistent=False)
    if module is None:
        raise RuntimeError("addon_utils.enable returned failure")

    from bob.cli import is_bob_running, unit_output_dir
    from importer import import_file
    from materials.material_builder import read_material_def

    if is_bob_running():
        raise RuntimeError("BOB is already open - close it before running this test.")

    skeleton, _warnings, _kind = import_file(str(SKELETON_CS2), bpy.context)
    armature = next(obj for obj in skeleton.all_objects if obj.type == "ARMATURE")
    bpy.context.scene.tw_workflow = "UNIT"
    output_dir = unit_output_dir(ASSEMBLY_KIT_ROOT)

    try:
        print("=== author, export and compile ===")
        units = [build_part(name, shader, kind, masks, armature) for name, (shader, kind, masks, _, _) in PARTS.items()]
        if not compile_parts(export_units(units, EXPORT_DIR), EXPORT_DIR):
            raise SystemExit(1)
        check("the untouched skin part's .CS2 carries test_black in all three slots",
              cs2_masks(EXPORT_DIR / "mask_skin.CS2") == ["test_black.tga"] * 3)
        for name, (_shader, _kind, _masks, slot, expected) in PARTS.items():
            textures = compiled_textures(output_dir / f"{name}.rigid_model_v2")
            check(f"{name}: compiled mask slot {slot} is {expected}", Path(textures.get(slot, "")).name == expected)

        print("=== re-import, re-export and compile again ===")
        reimported = []
        for name, (_shader, _kind, _masks, _slot, expected) in PARTS.items():
            collection, _warnings, _kind = import_file(str(output_dir / f"{name}.rigid_model_v2"), bpy.context)
            base = expected.removesuffix("_mask.dds")
            materials = {slot.material for obj in collection.all_objects for slot in obj.material_slots if slot.material}
            paths = [read_material_def(material).tint_mask_texture_paths for material in materials]
            check(f"{name}: re-imported Tint Masks point at {base}_mask1/2/3.tga",
                  bool(paths) and all([Path(p).name for p in entry] == [f"{base}_mask{i}.tga" for i in (1, 2, 3)]
                                      for entry in paths))
            collection.name = f"{name}_re"
            reimported.append(collection)
        reexported = export_units(reimported, REEXPORT_DIR)
        for name, (_shader, _kind, _masks, _slot, expected) in PARTS.items():
            base = expected.removesuffix("_mask.dds")
            check(f"{name}: the re-exported .CS2 carries {base}_mask1/2/3.tga",
                  cs2_masks(REEXPORT_DIR / f"{name}_re.CS2") == [f"{base}_mask{i}.tga" for i in (1, 2, 3)])
        # Only the rigid part rebuilds end to end from a re-import today: a weighted one's stub textures
        # and a skin one's missing Level stop BOB for reasons unrelated to masks (PLAN_units.md).
        if not compile_parts([path for path in reexported if path.stem == "mask_rigid_re"], REEXPORT_DIR):
            raise SystemExit(1)
        textures = compiled_textures(output_dir / "mask_rigid_re.rigid_model_v2")
        check("mask_rigid: the rebuilt faction_mask is still mask_rigid_mask.dds",
              Path(textures.get(FACTION_MASK, "")).name == "mask_rigid_mask.dds")
    finally:
        shutil.rmtree(EXPORT_DIR, ignore_errors=True)
        shutil.rmtree(REEXPORT_DIR, ignore_errors=True)
        for name in PARTS:
            for pattern in (f"{name}.*", f"{name}_re.*"):
                for path in output_dir.glob(pattern):
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
