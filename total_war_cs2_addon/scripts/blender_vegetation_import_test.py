import sys
import traceback
from pathlib import Path

import addon_utils
import bpy

REPO_ROOT = r"C:\Users\Khaiali\source\repos\blender_buildings_plugin"
TREES = Path(r"C:\Users\Khaiali\Desktop\battleterrain\vegetation\trees")

if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

# oak_h is the smallest full tree in the corpus and the one PLAN_vegetation.md decodes by hand:
# 4 LODs, bark plus leaf at every mesh LOD, a 16-vertex 6-face hull and 2 fire emitters.
OAK = TREES / "oak" / "oak_h.rigid_model_v2"
OAK_TECH = TREES / "oak" / "oak_h_tech.cs2.parsed"
SHRUB = TREES / "shrubs_med" / "drya_a.rigid_model_v2"
BUILDING_TECH = Path(REPO_ROOT) / "Input/examples/working_data/gondor_building_5/gondor_building_5_tech.cs2.parsed"
UNIT_PART = Path(REPO_ROOT) / "Input/examples/working_data/variantmeshes/_variantmodels/gondor/armour/swan_gorget_01.rigid_model_v2"

failures = []


def check(label: str, condition: bool) -> None:
    print(("  OK   " if condition else "  FAIL ") + label)
    if not condition:
        failures.append(label)


def clear_scene() -> None:
    for collection in list(bpy.data.collections):
        bpy.data.collections.remove(collection)
    for obj in list(bpy.data.objects):
        bpy.data.objects.remove(obj, do_unlink=True)


def children_by_role(collection, role):
    return [child for child in collection.children if child.tw_role == role]


class StubLayout:
    # blender_panel_draw_test only ever sees an empty scene, so the panel's real branches - the ones
    # that walk an imported model's children - are only reached here.
    def __getattr__(self, _name):
        return lambda *args, **kwargs: StubLayout()


def draw_vegetation_panel() -> str:
    bpy.context.scene.tw_workflow = "VEGETATION"
    panel = bpy.types.TW_PT_vegetation_setup
    try:
        panel.draw(type("PanelStub", (), {"layout": StubLayout()})(), bpy.context)
    except Exception as error:  # noqa: BLE001 - the whole point of the check
        traceback.print_exc()
        return f"{type(error).__name__}: {error}"
    return ""


def main() -> None:
    if addon_utils.enable("total_war_cs2_addon", default_set=True, persistent=False) is None:
        raise RuntimeError("addon_utils.enable returned failure")

    from importer.file_router import import_file

    print("=== the binary layer decodes every vegetation mesh in the corpus ===")
    from binary.rigid_model_v2_reader import read_rigid_model_v2
    from binary.vegetation_tech_reader import VegetationTechReader

    models = sorted(TREES.rglob("*.rigid_model_v2"))
    undecoded = []
    for path in models:
        model = read_rigid_model_v2(path.read_bytes())
        for lod in model.lods:
            for mesh in lod.meshes:
                if mesh.vertex_count and len(mesh.vertices) != mesh.vertex_count:
                    undecoded.append((path.name, mesh.shader_flags))
    check(f"all {len(models)} models decode with no undecoded mesh", not undecoded)

    techs = sorted(TREES.rglob("*_tech.cs2.parsed"))
    partitioned = 0
    for path in techs:
        tech = VegetationTechReader.read_file(str(path))
        owned = sorted({index for node in tech.vfx_nodes for index in node.face_indices})
        if owned == list(range(tech.hull.face_count)):
            partitioned += 1
    check(f"all {len(techs)} tech sidecars parse and partition their hull", partitioned == len(techs))

    print("=== a tree imports as a vegetation model, not a unit part ===")
    clear_scene()
    collection, warnings, kind = import_file(str(OAK), bpy.context)
    check("kind is VEGETATION", kind == "VEGETATION")
    check("workflow switched to VEGETATION", bpy.context.scene.tw_workflow == "VEGETATION")
    check("root collection carries the VEGETATION role", collection.tw_role == "VEGETATION")
    check("bone table name is recorded", collection.get("tw_bone_table_name") == "tree")

    display = children_by_role(collection, "VEGETATION_DISPLAY")
    check("its meshes sit in one Display collection", len(display) == 1)
    meshes = list(display[0].objects)
    check("oak_h has 3 LOD meshes, one per level", len(meshes) == 3)
    check("each carries its own LOD Level",
          [obj.tw_vegetation_lod for obj in meshes] == ["LOD01", "LOD02", "LOD03"])
    check("a LOD's subobjects arrive as material slots on one object, not as separate objects",
          all(len(obj.data.materials) == 2 for obj in meshes))
    check("and its faces are split between those slots",
          all({polygon.material_index for polygon in obj.data.polygons} == {0, 1} for obj in meshes))

    shader_types = {material.tw_shader_type for obj in meshes for material in obj.data.materials}
    check("both tree shaders are used", shader_types == {"tree", "tree_leaf"})
    leaf = [m for obj in meshes for m in obj.data.materials if m.tw_shader_type == "tree_leaf"][0]
    check("leaf cards are alpha tested", leaf.tw_alpha_mode == "ALPHA_TEST")
    check("the three colour params are kept on the material",
          all(f"tw_tree_colour_{index}" in leaf for index in range(3)))

    mesh_data = meshes[0].data
    check("the tree vertex fields survive import",
          {"tw_tree_position0", "tw_tree_wind_weight", "tw_tree_wind_bone", "tw_tree_anchor_bone"}
          <= set(mesh_data.attributes.keys()))
    check("the weight quad's last two components import as bone indices, not weights",
          {entry.value for entry in mesh_data.attributes["tw_tree_wind_bone"].data} == {2})
    check("a colour attribute is created", "Colour" in mesh_data.color_attributes)

    check("nothing BOB generates is imported alongside them",
          [child.tw_role for child in collection.children] == ["VEGETATION_DISPLAY"])
    check("and the artist is told the billboard was left out",
          any("billboard" in message for message in warnings))

    problem = draw_vegetation_panel()
    check(f"the Vegetation panel draws over a real model{': ' + problem if problem else ''}", not problem)

    print("=== a leaf-only shrub imports with no bark mesh ===")
    clear_scene()
    collection, _warnings, kind = import_file(str(SHRUB), bpy.context)
    check("shrub is VEGETATION", kind == "VEGETATION")
    meshes = list(children_by_role(collection, "VEGETATION_DISPLAY")[0].objects)
    check("the shrub has 2 LOD meshes", len(meshes) == 2)
    check("its LODs start at level 2, not level 1",
          [obj.tw_vegetation_lod for obj in meshes] == ["LOD02", "LOD03"])
    check("every shrub mesh is a leaf",
          all(m.tw_shader_type == "tree_leaf" for obj in meshes for m in obj.data.materials))
    check("a leaf-only LOD has a single material slot", all(len(obj.data.materials) == 1 for obj in meshes))

    print("=== a lone tech sidecar is refused, with a reason ===")
    clear_scene()
    from importer.file_router import UnsupportedFileError

    try:
        import_file(str(OAK_TECH), bpy.context)
        refusal = ""
    except UnsupportedFileError as error:
        refusal = str(error)
    check("picking one says what it is instead of importing it", "generates" in refusal)
    check("and points at the file that can be authored", ".rigid_model_v2" in refusal)
    check("nothing was created for it", not bpy.data.collections)

    print("=== the two file types that share an extension still route correctly ===")
    clear_scene()
    _collection, _warnings, kind = import_file(str(BUILDING_TECH), bpy.context)
    check("a building .cs2.parsed is still a BUILDING", kind == "BUILDING")
    clear_scene()
    _collection, _warnings, kind = import_file(str(UNIT_PART), bpy.context)
    check("a unit .rigid_model_v2 is still a UNIT PART", kind == "UNIT PART")

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
    sys.stdout.flush()
    bpy.ops.wm.quit_blender()
