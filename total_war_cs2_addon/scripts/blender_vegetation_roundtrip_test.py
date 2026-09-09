"""Import a game-ready tree, export it, build the result with BOB, and compare the two models.

Run it the way every other Blender-side script here is run:

    blender.exe --background --python scripts/blender_vegetation_roundtrip_test.py

It writes into the Assembly Kit's raw_data, because BOB refuses to build anything outside it, and
cleans up after itself.
"""

import shutil
import struct
import sys
import traceback
from pathlib import Path

import addon_utils
import bpy

REPO_ROOT = r"C:\Users\Khaiali\source\repos\blender_buildings_plugin"
ASSEMBLY_KIT = Path(r"D:\SteamLibrary\steamapps\common\Total War Attila\assembly_kit")
TREES = Path(r"C:\Users\Khaiali\Desktop\battleterrain\vegetation\trees")
SOURCE = TREES / "oak" / "oak_h.rigid_model_v2"
SOURCE_TECH = TREES / "oak" / "oak_h_tech.cs2.parsed"
MODEL_NAME = "oak_h"

# bob.rules.GLOSS_MAP_SUFFIX, repeated because the add-on is not importable until it is enabled.
GLOSS_MAP_SUFFIX = "_gloss_map"

EXPORT_DIR = ASSEMBLY_KIT / "raw_data" / "BattleTerrain" / "vegetation" / "trees" / "roundtrip"
TEXTURE_DIR = ASSEMBLY_KIT / "raw_data" / "BattleTerrain" / "vegetation" / "trees" / "textures" / "roundtrip"
BUILD_DIR = ASSEMBLY_KIT / "working_data" / "BattleTerrain" / "vegetation" / "trees" / "roundtrip"

if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

failures = []


def check(label: str, condition: bool) -> None:
    print(("  OK   " if condition else "  FAIL ") + label)
    if not condition:
        failures.append(label)


def write_stub_tga(path: Path) -> None:
    # BOB resolves a mesh's texture directory from the rules.bob, not from where the source texture
    # sits, but the source still has to exist for the action to run. The game's own art ships as
    # compiled .dds, so the roundtrip needs a stand-in .tga of the same name.
    header = struct.pack("<BBBHHBHHHHBB", 0, 0, 2, 0, 0, 0, 0, 0, 4, 4, 24, 0)
    path.write_bytes(header + bytes(3) * 16)


def authored_stem(compiled_stem: str) -> str:
    # BOB rebuilds the gloss map's name as <base>_gloss_map (bob.rules.compiled_gloss_map_name), so
    # the game's own test_gloss_map.dds was authored as test_gloss.tga. Feeding the compiled name
    # back in would make BOB suffix it a second time - which the exporter warns about, and which the
    # roundtrip would otherwise be measuring instead of measuring itself.
    if compiled_stem.endswith(GLOSS_MAP_SUFFIX):
        return compiled_stem[: -len("_map")]
    return compiled_stem


def stub_textures(model_collection) -> None:
    TEXTURE_DIR.mkdir(parents=True, exist_ok=True)
    for lod in model_collection.children:
        for obj in lod.objects:
            for material in obj.data.materials:
                if not material.use_nodes:
                    continue
                for node in material.node_tree.nodes:
                    if node.type != "TEX_IMAGE" or node.image is None:
                        continue
                    stem = authored_stem(Path(node.image.filepath or node.image.name).stem)
                    stub = TEXTURE_DIR / f"{stem}.tga"
                    write_stub_tga(stub)
                    node.image.filepath = str(stub)


def cleanup() -> None:
    for directory in (EXPORT_DIR, TEXTURE_DIR, BUILD_DIR):
        shutil.rmtree(directory, ignore_errors=True)


def mesh_signature(lods, prefix: str):
    # The compiled mesh name is "<node> subobject N" and the node is named after the model, so the
    # rebuilt names differ from the original's by that prefix alone - the export collection carries
    # the add-on's name for the model, not the name CA happened to give their Max scene.
    return [
        [
            (
                mesh.shader_flags,
                mesh.vertex_format,
                (mesh.material.name if mesh.material is not None else "").replace(prefix, "<model>", 1),
                len(mesh.vertices),
                len(mesh.indices),
            )
            for mesh in lod.meshes
        ]
        for lod in lods
    ]


def rounded(values, digits=3):
    return sorted(tuple(round(value, digits) for value in entry) for entry in values)


def close(before, after, tolerance) -> bool:
    # Every position in a compiled model is a float16, so re-authoring one from an imported model
    # feeds BOB values that have already been quantised once. Positions survive that unchanged
    # (float16 is idempotent), but the burn hull is float32 derived from them, so it lands within
    # one quantisation step rather than exactly.
    left = sorted(tuple(entry) for entry in before)
    right = sorted(tuple(entry) for entry in after)
    if len(left) != len(right):
        return False
    return all(
        abs(a - b) <= tolerance for pair in zip(left, right) for a, b in zip(*pair)
    )


def main() -> None:
    if addon_utils.enable("total_war_cs2_addon", default_set=True, persistent=False) is None:
        raise RuntimeError("addon_utils.enable returned failure")

    from binary.rigid_model_v2_reader import read_rigid_model_v2
    from binary.vegetation_tech_reader import VegetationTechReader
    from bob.cli import compile_vegetation
    from export.vegetation_exporter import export_vegetation
    from importer.file_router import import_file

    cleanup()
    EXPORT_DIR.mkdir(parents=True, exist_ok=True)

    print("=== import ===")
    collection, _warnings, kind = import_file(str(SOURCE), bpy.context)
    check("the sample imports as vegetation", kind == "VEGETATION")
    collection.name = MODEL_NAME
    stub_textures(collection)

    print("=== export ===")
    result = export_vegetation(collection, str(EXPORT_DIR), str(ASSEMBLY_KIT), bpy.context)
    check(f"export succeeded: {result.message}", result.success)
    if not result.success:
        return

    print("=== BOB ===")
    bob = compile_vegetation(str(ASSEMBLY_KIT), result.cs2_path)
    check(f"BOB built it: {bob.message}", bob.success)
    built = BUILD_DIR / f"{MODEL_NAME}.rigid_model_v2"
    built_tech = BUILD_DIR / f"{MODEL_NAME}_tech.cs2.parsed"
    check("BOB wrote the model", built.is_file())
    check("BOB wrote the tech sidecar", built_tech.is_file())
    if not built.is_file():
        return

    print("=== compare ===")
    original = read_rigid_model_v2(SOURCE.read_bytes())
    rebuilt = read_rigid_model_v2(built.read_bytes())

    check("the bone table name matches", original.bone_table_name == rebuilt.bone_table_name == "tree")
    check("the version matches", original.version == rebuilt.version)

    # The last LOD of the original is the billboard BOB generates from the model, and its
    # tree-billboard step crashes on this Assembly Kit (bob.rules.VEGETATION_BILLBOARD_NOTE), so the
    # rebuilt model is compared against the authored LODs only.
    authored = [lod for lod in original.lods if any(mesh.shader_flags != 89 for mesh in lod.meshes)]
    check(f"every authored LOD came back ({len(authored)})", len(rebuilt.lods) == len(authored))
    check("the camera-distance ladder matches",
          [lod.camera_distance for lod in rebuilt.lods] == [lod.camera_distance for lod in authored])

    check("every mesh matches on shader, vertex format, name, vertex count and index count",
          mesh_signature(authored, "oak") == mesh_signature(rebuilt.lods, MODEL_NAME))

    for index, (before, after) in enumerate(zip(authored, rebuilt.lods)):
        for mesh_a, mesh_b in zip(before.meshes, after.meshes):
            label = f"LOD {index} '{mesh_a.material.name}'"
            check(f"{label}: the vertex positions are the same set",
                  rounded(v.position for v in mesh_a.vertices) == rounded(v.position for v in mesh_b.vertices))
            check(f"{label}: the UVs are the same set",
                  rounded((v.uv for v in mesh_a.vertices), 3) == rounded((v.uv for v in mesh_b.vertices), 3))
            check(f"{label}: the texture slots are the same",
                  [t.texture_id for t in mesh_a.material.textures] == [t.texture_id for t in mesh_b.material.textures])
            check(f"{label}: the texture filenames are the same",
                  [Path(t.path).name for t in mesh_a.material.textures]
                  == [Path(t.path).name for t in mesh_b.material.textures])
            check(f"{label}: the three COLOUR_ params are the same",
                  rounded((p.value for p in mesh_a.material.vec4_params), 4)
                  == rounded((p.value for p in mesh_b.material.vec4_params), 4))
            check(f"{label}: every vertex still carries two influences summing to one",
                  all(abs(v.tree_weights[0] + v.tree_weights[1] - 1.0) < 0.01 for v in mesh_b.vertices))

    if built_tech.is_file():
        tech_before = VegetationTechReader.read_file(str(SOURCE_TECH))
        tech_after = VegetationTechReader.read_file(str(built_tech))
        check("the burn hull is named lowest_lod in both",
              tech_before.hull.name == tech_after.hull.name == "lowest_lod")
        check("the hull has the same vertex and face count",
              (len(tech_before.hull.vertices), tech_before.hull.face_count)
              == (len(tech_after.hull.vertices), tech_after.hull.face_count))
        lowest = rebuilt.lods[-1]
        check("the hull BOB built is exactly the model's own lowest LOD",
              close(tech_after.hull.vertices, [v.position for mesh in lowest.meshes for v in mesh.vertices], 1e-4))
        # The shipped oak_h's hull sits about 0.0115 higher in Y than its own lowest LOD - a pure
        # translation, not quantisation noise, and the same unexplained divergence PLAN_vegetation.md
        # 2.2 flags across part of the corpus. A hull BOB builds today has no such offset.
        check("and lands within that known offset of the shipped model's hull",
              close(tech_before.hull.vertices, tech_after.hull.vertices, 0.02))
        check("the same number of fire emitters was generated",
              len(tech_before.vfx_nodes) == len(tech_after.vfx_nodes))
        check("they carry the same VFX action name",
              {node.name for node in tech_before.vfx_nodes} == {node.name for node in tech_after.vfx_nodes})
        check("the emitters still partition the hull's faces",
              sorted({i for node in tech_after.vfx_nodes for i in node.face_indices})
              == list(range(tech_after.hull.face_count)))

    print()
    if failures:
        print(f"FAILED {len(failures)} check(s):")
        for failure in failures:
            print(f"  - {failure}")
    else:
        print("ALL CHECKS PASSED")


try:
    main()
except Exception:
    traceback.print_exc()
    failures.append("exception")
finally:
    cleanup()
    sys.stdout.flush()
    bpy.ops.wm.quit_blender()
