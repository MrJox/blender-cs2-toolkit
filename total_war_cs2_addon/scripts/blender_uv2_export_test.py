import os
import sys
import bpy

repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
plugin_dir = os.path.join(repo_root, "total_war_cs2_addon")
if plugin_dir not in sys.path:
    sys.path.insert(0, plugin_dir)

from total_war_cs2_addon.materials.material_builder import create_total_war_material
from total_war_cs2_addon.materials.template import build_directx_material_node
from total_war_cs2_addon.scene_model.cs2_builder import build_cs2_document
from total_war_cs2_addon.extraction.extract import extract_building
from total_war_cs2_addon.binary.cs2_writer import write_cs2
from total_war_cs2_addon.binary.cs2_reader import read_cs2
from total_war_cs2_addon.validation.rules import validate_building


def _make_building(name):
    building_coll = bpy.data.collections.new(name)
    building_coll.tw_role = "BUILDING"
    building_coll.tw_asset_type = "DISPLAY_BUILDING"
    bpy.context.scene.collection.children.link(building_coll)

    piece_coll = bpy.data.collections.new(f"{name}_Piece1")
    piece_coll.tw_role = "PIECE"
    building_coll.children.link(piece_coll)

    destruct_coll = bpy.data.collections.new(f"{name}_Destruct1")
    destruct_coll.tw_role = "DESTRUCT"
    piece_coll.children.link(destruct_coll)

    display_coll = bpy.data.collections.new(f"{name}_Display")
    display_coll.tw_role = "DISPLAY"
    destruct_coll.children.link(display_coll)

    collision_coll = bpy.data.collections.new(f"{name}_Collision")
    collision_coll.tw_role = "COLLISION"
    destruct_coll.children.link(collision_coll)

    verts = [(0, 0, 0), (1, 0, 0), (1, 1, 0), (0, 1, 0)]
    col_mesh = bpy.data.meshes.new(f"{name}_CollisionMesh")
    col_mesh.from_pydata(verts, [], [(0, 1, 2, 3)])
    col_obj = bpy.data.objects.new(f"{name}_CollisionObj", col_mesh)
    col_obj.tw_collision_type = "COLLISION"
    collision_coll.objects.link(col_obj)

    return building_coll, display_coll


def test_two_uv_layers_exported_as_two_channels():
    bpy.ops.wm.read_factory_settings(use_empty=True)
    try:
        bpy.ops.preferences.addon_enable(module="total_war_cs2_addon")
    except Exception:
        import total_war_cs2_addon
        total_war_cs2_addon.register()

    building_coll, display_coll = _make_building("UV2Building")

    mesh_data = bpy.data.meshes.new("DisplayMesh")
    verts = [(0, 0, 0), (1, 0, 0), (1, 1, 0), (0, 1, 0)]
    mesh_data.from_pydata(verts, [], [(0, 1, 2, 3)])

    uv1 = mesh_data.uv_layers.new(name="UVMap")
    for i, loop_uv in enumerate(uv1.data):
        loop_uv.uv = (float(i), 0.0)

    uv2 = mesh_data.uv_layers.new(name="UVMap2")
    for i, loop_uv in enumerate(uv2.data):
        loop_uv.uv = (0.0, float(i) * 10.0)

    mesh_data.update()

    obj = bpy.data.objects.new("DisplayObj", mesh_data)
    obj.tw_lod_index = "LOD01"
    display_coll.objects.link(obj)

    mat = bpy.data.materials.new("UV2Mat")
    mat.tw_shader_type = "tiled_dirtmap"
    create_total_war_material(mat)
    mat.node_tree.nodes["UV2"].uv_map = "UVMap2"
    obj.data.materials.append(mat)

    depsgraph = bpy.context.evaluated_depsgraph_get()
    building, warnings = extract_building(building_coll, depsgraph, bpy.context.scene)
    print("warnings:", warnings)

    lod_mesh = building.pieces[0].destruct_levels[0].lod_meshes[0]
    assert all(v.uv2 is not None for v in lod_mesh.mesh.vertices), "expected uv2 populated on every vertex"

    doc = build_cs2_document(building, assembly_kit_root=r"D:\AK")
    bytes_out = write_cs2(doc)
    re_doc = read_cs2(bytes_out)

    lod_node = next(n for n in re_doc.rigid_models if n.node_name == "piece01_destruct01_lod01")
    chunk = lod_node.geometry_chunks[0]
    print("uvw_channel_ids:", chunk.uvw_channel_ids)
    assert chunk.uvw_channel_ids == [1, 2], f"expected [1, 2], got {chunk.uvw_channel_ids}"

    for v in chunk.vertices:
        assert len(v.tex_coords) == 2, f"expected 2 tex coord entries, got {len(v.tex_coords)}"
        u1, v1, _ = v.tex_coords[0]
        u2, v2, _ = v.tex_coords[1]
        assert v1 == 1.0, f"channel 1 V should be 1 (Blender 0 flipped to CS2's top origin), got {v1}"
        assert u2 == 0.0, f"channel 2 U should be 0, got {u2}"
        assert v2 == 1.0 - u1 * 10.0, f"channel 2 V should track 1 - channel 1's U*10, got u1={u1} v2={v2}"

    print("=== UV2 (two real UV layers) TEST PASSED ===")


def test_single_uv_layer_stays_single_channel():
    bpy.ops.wm.read_factory_settings(use_empty=True)
    try:
        bpy.ops.preferences.addon_enable(module="total_war_cs2_addon")
    except Exception:
        import total_war_cs2_addon
        total_war_cs2_addon.register()

    building_coll, display_coll = _make_building("UV1Building")

    mesh_data = bpy.data.meshes.new("DisplayMesh")
    verts = [(0, 0, 0), (1, 0, 0), (1, 1, 0), (0, 1, 0)]
    mesh_data.from_pydata(verts, [], [(0, 1, 2, 3)])
    mesh_data.uv_layers.new(name="UVMap")
    mesh_data.update()

    obj = bpy.data.objects.new("DisplayObj", mesh_data)
    obj.tw_lod_index = "LOD01"
    display_coll.objects.link(obj)

    mat = bpy.data.materials.new("UV1Mat")
    mat.tw_shader_type = "default"
    create_total_war_material(mat)
    obj.data.materials.append(mat)

    depsgraph = bpy.context.evaluated_depsgraph_get()
    building, warnings = extract_building(building_coll, depsgraph, bpy.context.scene)
    print("warnings:", warnings)

    lod_mesh = building.pieces[0].destruct_levels[0].lod_meshes[0]
    assert all(v.uv2 is None for v in lod_mesh.mesh.vertices), "expected no uv2 with a single UV layer / unset UV2 node"

    doc = build_cs2_document(building, assembly_kit_root=r"D:\AK")
    bytes_out = write_cs2(doc)
    re_doc = read_cs2(bytes_out)

    lod_node = next(n for n in re_doc.rigid_models if n.node_name == "piece01_destruct01_lod01")
    chunk = lod_node.geometry_chunks[0]
    print("uvw_channel_ids:", chunk.uvw_channel_ids)
    assert chunk.uvw_channel_ids == [1], f"expected [1] (no regression), got {chunk.uvw_channel_ids}"
    for v in chunk.vertices:
        assert len(v.tex_coords) == 1

    print("=== single UV layer (no regression) TEST PASSED ===")



def test_ui_added_uv_layer_does_not_hijack_the_diffuse_channel():
    bpy.ops.wm.read_factory_settings(use_empty=True)
    try:
        bpy.ops.preferences.addon_enable(module="total_war_cs2_addon")
    except Exception:
        import total_war_cs2_addon
        total_war_cs2_addon.register()

    building_coll, display_coll = _make_building("UVActiveBuilding")

    mesh_data = bpy.data.meshes.new("DisplayMesh")
    verts = [(0, 0, 0), (1, 0, 0), (1, 1, 0), (0, 1, 0)]
    mesh_data.from_pydata(verts, [], [(0, 1, 2, 3)])
    uv1 = mesh_data.uv_layers.new(name="UVMap")
    for i, loop_uv in enumerate(uv1.data):
        loop_uv.uv = (float(i), 0.0)
    mesh_data.update()

    obj = bpy.data.objects.new("DisplayObj", mesh_data)
    obj.tw_lod_index = "LOD01"
    display_coll.objects.link(obj)

    # The UV Maps panel's + button, which is how an artist actually adds a second UV set - it leaves
    # the new layer selected in the list while active_render stays on the first.
    bpy.context.view_layer.objects.active = obj
    bpy.ops.mesh.uv_texture_add()
    mesh_data.uv_layers[1].name = "UVMap2"
    for i, loop_uv in enumerate(mesh_data.uv_layers["UVMap2"].data):
        loop_uv.uv = (0.0, float(i) * 10.0)
    mesh_data.update()
    assert mesh_data.uv_layers.active.name == "UVMap2", "expected the UI-added layer to be selected"

    mat = bpy.data.materials.new("UVActiveMat")
    mat.tw_shader_type = "tiled_dirtmap"
    create_total_war_material(mat)
    mat.node_tree.nodes["UV2"].uv_map = "UVMap2"
    obj.data.materials.append(mat)

    depsgraph = bpy.context.evaluated_depsgraph_get()
    building, warnings = extract_building(building_coll, depsgraph, bpy.context.scene)
    print("warnings:", warnings)

    doc = build_cs2_document(building, assembly_kit_root=r"D:\AK")
    re_doc = read_cs2(write_cs2(doc))
    chunk = next(n for n in re_doc.rigid_models if n.node_name == "piece01_destruct01_lod01").geometry_chunks[0]
    print("uvw_channel_ids:", chunk.uvw_channel_ids)
    assert chunk.uvw_channel_ids == [1, 2], f"expected [1, 2], got {chunk.uvw_channel_ids}"

    for v in chunk.vertices:
        u1, v1, _ = v.tex_coords[0]
        u2, v2, _ = v.tex_coords[1]
        assert v1 == 1.0, f"channel 1 must carry UVMap (V=1 after the flip), got {v1} - UI-selected layer hijacked it"
        assert u2 == 0.0, f"channel 2 must carry UVMap2 (U=0), got {u2}"
        assert v2 == 1.0 - u1 * 10.0, f"channel 2 V should track 1 - channel 1's U*10, got u1={u1} v2={v2}"

    print("=== UI-added UV layer does not hijack channel 1 TEST PASSED ===")


def test_uv2_node_pointing_at_primary_layer_stays_single_channel():
    bpy.ops.wm.read_factory_settings(use_empty=True)
    try:
        bpy.ops.preferences.addon_enable(module="total_war_cs2_addon")
    except Exception:
        import total_war_cs2_addon
        total_war_cs2_addon.register()

    building_coll, display_coll = _make_building("UVSameBuilding")

    mesh_data = bpy.data.meshes.new("DisplayMesh")
    verts = [(0, 0, 0), (1, 0, 0), (1, 1, 0), (0, 1, 0)]
    mesh_data.from_pydata(verts, [], [(0, 1, 2, 3)])
    mesh_data.uv_layers.new(name="UVMap")
    mesh_data.update()

    obj = bpy.data.objects.new("DisplayObj", mesh_data)
    obj.tw_lod_index = "LOD01"
    display_coll.objects.link(obj)

    mat = bpy.data.materials.new("UVSameMat")
    mat.tw_shader_type = "tiled_dirtmap"
    create_total_war_material(mat)
    mat.node_tree.nodes["UV2"].uv_map = "UVMap"
    obj.data.materials.append(mat)

    depsgraph = bpy.context.evaluated_depsgraph_get()
    building, warnings = extract_building(building_coll, depsgraph, bpy.context.scene)
    print("warnings:", warnings)

    lod_mesh = building.pieces[0].destruct_levels[0].lod_meshes[0]
    assert all(v.uv2 is None for v in lod_mesh.mesh.vertices), "UV2 naming the primary layer is not a second set"

    doc = build_cs2_document(building, assembly_kit_root=r"D:\AK")
    re_doc = read_cs2(write_cs2(doc))
    chunk = next(n for n in re_doc.rigid_models if n.node_name == "piece01_destruct01_lod01").geometry_chunks[0]
    print("uvw_channel_ids:", chunk.uvw_channel_ids)
    assert chunk.uvw_channel_ids == [1], f"expected [1], got {chunk.uvw_channel_ids}"
    for v in chunk.vertices:
        assert len(v.tex_coords) == 1, f"expected 1 tex coord entry, got {len(v.tex_coords)}"

    print("=== UV2 node naming the primary layer stays single-channel TEST PASSED ===")


def test_shader_technique_index_matches_rigid_material():
    for shader_type, expected in (("default", 0), ("ship_ambientmap", 5), ("tiled_dirtmap", 6)):
        node = build_directx_material_node(
            node_name="n", material_name="m", rigid_material=shader_type, assembly_kit_root=r"D:\AK"
        )
        got = node.directx_material.shader_technique_index
        assert got == expected, f"{shader_type}: expected technique {expected}, got {got}"
        print(f"  {shader_type} -> technique {got}")

    print("=== shader technique index TEST PASSED ===")



def test_untouched_uv2_node_still_exports_the_meshs_second_layer():
    bpy.ops.wm.read_factory_settings(use_empty=True)
    try:
        bpy.ops.preferences.addon_enable(module="total_war_cs2_addon")
    except Exception:
        import total_war_cs2_addon
        total_war_cs2_addon.register()

    building_coll, display_coll = _make_building("UVDefaultBuilding")

    mesh_data = bpy.data.meshes.new("DisplayMesh")
    verts = [(0, 0, 0), (1, 0, 0), (1, 1, 0), (0, 1, 0)]
    mesh_data.from_pydata(verts, [], [(0, 1, 2, 3)])
    # Blender's own default layer names - the artist never renames these to "UV2".
    uv1 = mesh_data.uv_layers.new(name="UVMap")
    for i, loop_uv in enumerate(uv1.data):
        loop_uv.uv = (float(i), 0.0)
    uv2 = mesh_data.uv_layers.new(name="UVMap.001")
    for i, loop_uv in enumerate(uv2.data):
        loop_uv.uv = (0.0, float(i) * 10.0)
    mesh_data.update()

    obj = bpy.data.objects.new("DisplayObj", mesh_data)
    obj.tw_lod_index = "LOD01"
    display_coll.objects.link(obj)

    for shader_type in ("tiled_dirtmap", "ship_ambientmap"):
        mat = bpy.data.materials.new(f"UVDefaultMat_{shader_type}")
        mat.tw_shader_type = shader_type
        create_total_war_material(mat)
        assert mat.node_tree.nodes["UV2"].uv_map == "UV2", "expected the untouched node default"
        obj.data.materials.clear()
        obj.data.materials.append(mat)

        depsgraph = bpy.context.evaluated_depsgraph_get()
        building, warnings = extract_building(building_coll, depsgraph, bpy.context.scene)
        print("warnings:", warnings)

        doc = build_cs2_document(building, assembly_kit_root=r"D:\AK")
        re_doc = read_cs2(write_cs2(doc))
        chunk = next(n for n in re_doc.rigid_models if n.node_name == "piece01_destruct01_lod01").geometry_chunks[0]
        print(f"  {shader_type} uvw_channel_ids:", chunk.uvw_channel_ids)
        assert chunk.uvw_channel_ids == [1, 2], f"{shader_type}: expected [1, 2], got {chunk.uvw_channel_ids}"
        for v in chunk.vertices:
            u1, v1, _ = v.tex_coords[0]
            u2, v2, _ = v.tex_coords[1]
            assert v1 == 1.0, f"channel 1 must carry UVMap (V=1 after the flip), got {v1}"
            assert u2 == 0.0, f"channel 2 must carry UVMap.001 (U=0), got {u2}"
            assert v2 == 1.0 - u1 * 10.0, f"channel 2 V should track 1 - channel 1's U*10, got u1={u1} v2={v2}"

    print("=== untouched UV2 node still exports the second layer TEST PASSED ===")


def _uv2_validation_warnings(building_coll):
    return [
        i for i in validate_building(building_coll)
        if "UV channel 2" in i.message and "preview only" not in i.message
    ]


def _uv2_preview_warnings(building_coll):
    return [i for i in validate_building(building_coll) if "preview only" in i.message]


def _uv2_validation_case(name, shader_type, second_layer_name, uv2_node_name):
    bpy.ops.wm.read_factory_settings(use_empty=True)
    try:
        bpy.ops.preferences.addon_enable(module="total_war_cs2_addon")
    except Exception:
        import total_war_cs2_addon
        total_war_cs2_addon.register()

    building_coll, display_coll = _make_building(name)

    mesh_data = bpy.data.meshes.new("DisplayMesh")
    mesh_data.from_pydata([(0, 0, 0), (1, 0, 0), (1, 1, 0), (0, 1, 0)], [], [(0, 1, 2, 3)])
    mesh_data.uv_layers.new(name="UVMap")
    if second_layer_name:
        mesh_data.uv_layers.new(name=second_layer_name)
    mesh_data.update()

    obj = bpy.data.objects.new("DisplayObj", mesh_data)
    obj.tw_lod_index = "LOD01"
    display_coll.objects.link(obj)

    mat = bpy.data.materials.new(f"{name}Mat")
    mat.tw_shader_type = shader_type
    create_total_war_material(mat)
    if uv2_node_name is not None:
        mat.node_tree.nodes["UV2"].uv_map = uv2_node_name
    obj.data.materials.append(mat)

    return building_coll


def test_uv2_shader_without_a_second_uv_layer_warns():
    for shader_type, texture_slot in (("tiled_dirtmap", "Dirtmask"), ("ship_ambientmap", "Ambient Map")):
        building_coll = _uv2_validation_case(f"UV2Warn_{shader_type}", shader_type, None, None)
        issues = _uv2_validation_warnings(building_coll)
        print(f"  {shader_type}:", [i.message for i in issues])
        assert len(issues) == 1, f"{shader_type}: expected one UV2 warning, got {len(issues)}"
        assert issues[0].severity == "WARNING", f"{shader_type}: expected WARNING, got {issues[0].severity}"
        assert texture_slot in issues[0].message, f"{shader_type}: message should name the {texture_slot} slot"
        assert issues[0].object_name == "DisplayObj"

    print("=== UV2 shader without a second UV layer warns TEST PASSED ===")


def test_uv2_validation_matches_what_the_export_actually_writes():
    # Each case is (second UV layer, the material UV2 node's uv_map, whether channel 2 is exported,
    # whether the preview-only warning fires).
    cases = [
        (None, None, False, False),
        ("UVMap2", None, True, True),
        ("UVMap2", "UVMap2", True, False),
        ("UVMap2", "UVMap", False, False),
        (None, "UVMap", False, False),
    ]
    for index, (second_layer_name, uv2_node_name, expect_channel2, expect_preview) in enumerate(cases):
        building_coll = _uv2_validation_case(f"UV2Match{index}", "tiled_dirtmap", second_layer_name, uv2_node_name)

        depsgraph = bpy.context.evaluated_depsgraph_get()
        building, _ = extract_building(building_coll, depsgraph, bpy.context.scene)
        lod_mesh = building.pieces[0].destruct_levels[0].lod_meshes[0]
        exported_channel2 = all(v.uv2 is not None for v in lod_mesh.mesh.vertices)
        warned = bool(_uv2_validation_warnings(building_coll))
        preview_warned = bool(_uv2_preview_warnings(building_coll))

        print(
            f"  layer={second_layer_name} node={uv2_node_name} exported_uv2={exported_channel2} "
            f"warned={warned} preview_warned={preview_warned}"
        )
        assert exported_channel2 == expect_channel2, f"case {index}: export disagrees with the expectation"
        assert warned != exported_channel2, f"case {index}: validation and export disagree"
        assert preview_warned == expect_preview, f"case {index}: preview warning disagrees with the expectation"

    print("=== UV2 validation matches the export TEST PASSED ===")


def test_make_material_points_the_uv2_node_at_the_meshs_second_layer():
    building_coll = _uv2_validation_case("UV2Bind", "tiled_dirtmap", "UVMap2", None)
    obj = bpy.data.objects["DisplayObj"]
    assert obj.active_material.node_tree.nodes["UV2"].uv_map == "UV2"
    assert _uv2_preview_warnings(building_coll)

    bpy.context.view_layer.objects.active = obj
    bpy.ops.tw_buildings.make_material()

    assert obj.active_material.node_tree.nodes["UV2"].uv_map == "UVMap2"
    assert not _uv2_preview_warnings(building_coll)

    depsgraph = bpy.context.evaluated_depsgraph_get()
    building, _ = extract_building(building_coll, depsgraph, bpy.context.scene)
    lod_mesh = building.pieces[0].destruct_levels[0].lod_meshes[0]
    assert all(v.uv2 is not None for v in lod_mesh.mesh.vertices)

    print("=== Make Total War Material binds the UV2 node TEST PASSED ===")


def test_non_uv2_shader_never_warns():
    for shader_type in ("default", "terrain_blend"):
        building_coll = _uv2_validation_case(f"UV2Quiet_{shader_type}", shader_type, None, None)
        issues = _uv2_validation_warnings(building_coll)
        assert not issues, f"{shader_type}: expected no UV2 warning, got {[i.message for i in issues]}"

    print("=== non-UV2 shaders never warn TEST PASSED ===")


if __name__ == "__main__":
    test_two_uv_layers_exported_as_two_channels()
    test_single_uv_layer_stays_single_channel()
    test_ui_added_uv_layer_does_not_hijack_the_diffuse_channel()
    test_uv2_node_pointing_at_primary_layer_stays_single_channel()
    test_untouched_uv2_node_still_exports_the_meshs_second_layer()
    test_shader_technique_index_matches_rigid_material()
    test_uv2_shader_without_a_second_uv_layer_warns()
    test_uv2_validation_matches_what_the_export_actually_writes()
    test_make_material_points_the_uv2_node_at_the_meshs_second_layer()
    test_non_uv2_shader_never_warns()
