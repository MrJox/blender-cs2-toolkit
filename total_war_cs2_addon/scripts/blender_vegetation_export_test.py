import sys
import traceback
from pathlib import Path

import addon_utils
import bpy

REPO_ROOT = r"C:\Users\Khaiali\source\repos\blender_buildings_plugin"
TREES = Path(r"C:\Users\Khaiali\Desktop\battleterrain\vegetation\trees")
OAK = TREES / "oak" / "oak_h.rigid_model_v2"
SHRUB = TREES / "shrubs_med" / "drya_a.rigid_model_v2"
OUTPUT = Path(bpy.app.tempdir) / "tw_vegetation_export"

if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

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


def main() -> None:
    if addon_utils.enable("total_war_cs2_addon", default_set=True, persistent=False) is None:
        raise RuntimeError("addon_utils.enable returned failure")

    from binary.cs2_reader import read_cs2
    from binary.cs2_writer import write_cs2
    from binary.rigid_model_v2_reader import read_rigid_model_v2
    from bob.rules import vegetation_paths_for, vegetation_rules_text
    from export.vegetation_exporter import export_vegetation
    from extraction.vegetation_extract import extract_vegetation, vegetation_mesh_objects
    from importer.file_router import import_file
    from scene_model.vegetation_builder import build_vegetation_cs2_document
    from materials.material_builder import read_material_def
    from validation.rules import has_blocking_issues, validate_vegetation

    OUTPUT.mkdir(parents=True, exist_ok=True)

    print("=== an imported tree exports as a weighted .CS2 shaped the way BOB wants ===")
    clear_scene()
    model_collection, _warnings, _kind = import_file(str(OAK), bpy.context)
    source = read_rigid_model_v2(OAK.read_bytes())

    issues = validate_vegetation(model_collection)
    check("an imported tree validates clean", not has_blocking_issues(issues))

    result = export_vegetation(model_collection, str(OUTPUT), REPO_ROOT, bpy.context)
    check(f"export succeeded ({result.message})", result.success)
    check("a correct export warns about nothing the artist cannot act on",
          not any("billboard" in warning for warning in result.warnings))

    document = read_cs2(result.cs2_path.read_bytes())
    check("the model is written as weighted nodes, not rigid ones",
          len(document.weighted_models) == 3 and not document.rigid_models)
    check("the nodes carry the _lodNN postfix BOB reads the level off",
          [node.node_name for node in document.weighted_models]
          == ["oak_h_lod01", "oak_h_lod02", "oak_h_lod03"])

    bones = [node.name for node in document.scene_root.scene_nodes[:2]]
    check("two bones are emitted ahead of the meshes", bones == ["bn_tree_anchor", "bn_tree_wind"])

    chunk = document.weighted_models[0].geometry_chunks[0]
    influences = {len(vertex.bone_weights) for vertex in chunk.vertices}
    check("every vertex carries exactly the two influences BOB demands", influences == {2})
    ids = {tuple(weight.bone_id for weight in vertex.bone_weights) for vertex in chunk.vertices}
    check("both influences use the bone ids BOB accepts, in ascending order", ids == {(1, 2)})
    sums = {round(sum(weight.weight for weight in vertex.bone_weights), 4) for vertex in chunk.vertices}
    check("the two weights sum to one on every vertex", sums == {1.0})

    # A .CS2 carries one vertex per mesh loop, not per welded vertex - BOB welds them itself - so
    # the triangle count is what compares against the compiled file.
    check("LOD 1 holds both meshes' triangles in one node",
          sum(len(submesh.triangles) for submesh in chunk.submeshes)
          == sum(len(mesh.indices) // 3 for mesh in source.lods[0].meshes))
    check("its triangles are split across two materials",
          len({submesh.material_id for submesh in chunk.submeshes}) == 2)

    print("=== the materials say what BOB's own tables say ===")
    names = {material.material_attributes.strings[1].value for material in document.materials}
    check("bark writes rigid_material tree_branch, not tree", names == {"tree_branch", "tree_leaf"})

    bark = [m for m in document.materials if m.material_attributes.strings[1].value == "tree_branch"][0]
    slots = {texture.texture_name: texture.texture_path for texture in bark.directx_material.textures}
    check("all five samplers BOB demands are filled",
          all(slots[name] for name in
              ("t_albedo", "t_normal", "t_smoothness", "t_reflectivity", "t_specular_colour")))
    # An imported tree has no Level texture, because the compiled model carries none - t_reflectivity
    # is required by BOB but reaches no compiled slot, so the gloss map stands in for it.
    check("a re-exported game tree stands the gloss map in for the Level it never had",
          slots["t_reflectivity"] == slots["t_smoothness"])

    colours = {a.name: tuple(round(v, 4) for v in a.value) for a in bark.directx_material.vec4_attributes}
    bark_mesh = [mesh for mesh in source.lods[0].meshes if mesh.shader_flags == 74][0]
    expected = [tuple(round(v, 4) for v in p.value) for p in sorted(bark_mesh.material.vec4_params, key=lambda p: p.param_id)]
    check("the three COLOUR_ params survive the round trip ungamma'd",
          [colours["vec4_colour_0"], colours["vec4_colour_1"], colours["vec4_colour_2"]] == expected)

    print("=== the rules.bob beside it names every key a real compile needed ===")
    rules = vegetation_rules_text(*vegetation_paths_for(REPO_ROOT, result.cs2_path))
    for key in ("AnimationType = tree", "CreateRigidModelDescriptionFile = true", "IncendiaryRadius", "LODDistance4 = 500"):
        check(f"rules.bob carries '{key}'", key in rules)
    check("the billboard switch that crashes BOB is left out", "Tree = true" not in rules)

    print("=== a shrub keeps the levels its own LODs sit on ===")
    clear_scene()
    shrub_collection, _warnings, _kind = import_file(str(SHRUB), bpy.context)
    shrub_source = read_rigid_model_v2(SHRUB.read_bytes())
    rungs = [round(lod.camera_distance) for lod in shrub_source.lods if lod.meshes[0].shader_flags != 89]
    shrub, _warnings = extract_vegetation(shrub_collection, bpy.context.evaluated_depsgraph_get())
    expected_indices = [{100: 1, 200: 2, 400: 3}[rung] for rung in rungs]
    check(f"a shrub starting at {rungs[0]}m keeps that level ({expected_indices})",
          sorted(lod.lod_index for lod in shrub.lods) == sorted(expected_indices))
    shrub_document = build_vegetation_cs2_document(shrub, REPO_ROOT)
    check("so its nodes are named for the levels, not renumbered from one",
          [node.node_name for node in shrub_document.weighted_models]
          == [f"{shrub_collection.name}_lod{index:02d}" for index in sorted(expected_indices)])

    print("=== an empty model is refused rather than exported broken ===")
    clear_scene()
    empty = bpy.data.collections.new("empty_tree")
    empty.tw_role = "VEGETATION"
    bpy.context.scene.collection.children.link(empty)
    check("a model with no Display collection is blocked", has_blocking_issues(validate_vegetation(empty)))
    blocked = export_vegetation(empty, str(OUTPUT), REPO_ROOT, bpy.context)
    check("and its export fails with a message rather than a traceback",
          not blocked.success and "Display" in blocked.message)

    print("=== the per-vertex wind weight reaches the file ===")
    clear_scene()
    model_collection, _warnings, _kind = import_file(str(OAK), bpy.context)
    painted = vegetation_mesh_objects(model_collection)[0]
    attribute = painted.data.attributes["tw_tree_wind_weight"]
    for index, entry in enumerate(attribute.data):
        entry.value = 0.25 if index % 2 else 0.0
    weighted = export_vegetation(model_collection, str(OUTPUT), REPO_ROOT, bpy.context)
    check("the export still succeeds", weighted.success)
    quads = {
        tuple(round(w.weight, 3) for w in vertex.bone_weights)
        for vertex in read_cs2(weighted.cs2_path.read_bytes()).weighted_models[0].geometry_chunks[0].vertices
    }
    check("both the painted weight and the default reach the .CS2, on the right bones",
          quads == {(1.0, 0.0), (0.75, 0.25)})

    print("=== the panel's own buttons build a model the exporter accepts ===")
    clear_scene()
    bpy.ops.tw_buildings.new_vegetation(model_name="hand_made_tree")
    built = bpy.data.collections["hand_made_tree"]
    bpy.context.view_layer.active_layer_collection = (
        bpy.context.view_layer.layer_collection.children["hand_made_tree"]
    )
    display = [child for child in built.children if child.tw_role == "VEGETATION_DISPLAY"]
    check("New Vegetation Model makes the Display collection its meshes go in", len(display) == 1)

    bpy.ops.mesh.primitive_cube_add()
    cube = bpy.context.object
    for collection in list(cube.users_collection):
        collection.objects.unlink(cube)
    display[0].objects.link(cube)
    cube.data.uv_layers.new(name="UVMap")
    bpy.context.view_layer.objects.active = cube
    # The shared Make Total War Material button, not a vegetation-only one: the Materials panel
    # already offers Tree and Tree Leaf when the workflow is VEGETATION.
    cube.data.materials.append(bpy.data.materials.new("hand_made_bark"))
    bpy.ops.tw_buildings.make_material()
    bpy.ops.tw_buildings.set_shader_type(shader_type="tree")
    check("the shared material button sets a tree material up",
          cube.active_material.tw_shader_type == "tree" and cube.active_material.use_nodes)
    check("and its colour constants default to white rather than being missing",
          read_material_def(cube.active_material).tree_colours == ((1.0,) * 4,) * 3)
    check("a hand-made model is not blocked, only warned about",
          not has_blocking_issues(validate_vegetation(built)))
    check("and the warning names all five texture slots BOB refuses a tree without",
          any("Diffuse, Normal, Gloss, Level, Specular" in issue.message
              for issue in validate_vegetation(built)))
    hand_made = export_vegetation(built, str(OUTPUT), REPO_ROOT, bpy.context)
    check(f"and exports ({hand_made.message})", hand_made.success)
    hand_made_document = read_cs2(hand_made.cs2_path.read_bytes())
    check("as one weighted node named for its level",
          [node.node_name for node in hand_made_document.weighted_models] == ["hand_made_tree_lod01"])

    print("=== an authored material keeps its own Level texture ===")
    for name, node_name in (("bark_diffuse", "Diffuse"), ("bark_normal", "Normal"),
                            ("bark_gloss", "Gloss"), ("bark_level", "Level"),
                            ("bark_specular", "Specular")):
        image = bpy.data.images.new(name, 4, 4)
        image.filepath = f"//textures/{name}.tga"
        cube.active_material.node_tree.nodes[node_name].image = image
    check("a material with all five filled raises no texture warning",
          not any("texture" in issue.message for issue in validate_vegetation(built)))
    authored = export_vegetation(built, str(OUTPUT), REPO_ROOT, bpy.context)
    authored_slots = {
        texture.texture_name: Path(texture.texture_path).stem
        for texture in read_cs2(authored.cs2_path.read_bytes()).materials[0].directx_material.textures
    }
    check("Level goes to t_reflectivity and the gloss map is left where it belongs",
          authored_slots["t_reflectivity"] == "bark_level"
          and authored_slots["t_smoothness"] == "bark_gloss")

    print("=== a shader that is not a tree shader is refused ===")
    cube.active_material.tw_shader_type = "default"
    check("validation blocks it", has_blocking_issues(validate_vegetation(built)))

    print("=== the written bytes read back as themselves ===")
    check("the exported .CS2 round-trips through the reader and writer byte-exactly",
          write_cs2(read_cs2(result.cs2_path.read_bytes())) == result.cs2_path.read_bytes())

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
