import os
import sys
import bpy

repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
plugin_dir = os.path.join(repo_root, "total_war_cs2_addon")
if plugin_dir not in sys.path:
    sys.path.insert(0, plugin_dir)

from total_war_cs2_addon.materials.material_builder import create_total_war_material
from total_war_cs2_addon.scene_model.cs2_builder import build_cs2_document
from total_war_cs2_addon.extraction.extract import extract_building
from total_war_cs2_addon.binary.cs2_writer import write_cs2
from total_war_cs2_addon.binary.cs2_reader import read_cs2

def test_multi_material_export():
    bpy.ops.wm.read_factory_settings(use_empty=True)

    try:
        bpy.ops.preferences.addon_enable(module="total_war_cs2_addon")
    except Exception:
        import total_war_cs2_addon
        total_war_cs2_addon.register()

    # 1. Setup collection structure
    building_coll = bpy.data.collections.new("MultiMatBuilding")
    building_coll.tw_role = "BUILDING"
    building_coll.tw_asset_type = "DISPLAY_BUILDING"
    bpy.context.scene.collection.children.link(building_coll)

    piece_coll = bpy.data.collections.new("Piece 1")
    piece_coll.tw_role = "PIECE"
    building_coll.children.link(piece_coll)

    destruct_coll = bpy.data.collections.new("Destruct 1")
    destruct_coll.tw_role = "DESTRUCT"
    piece_coll.children.link(destruct_coll)

    display_coll = bpy.data.collections.new("Display")
    display_coll.tw_role = "DISPLAY"
    destruct_coll.children.link(display_coll)

    collision_coll = bpy.data.collections.new("Collision")
    collision_coll.tw_role = "COLLISION"
    destruct_coll.children.link(collision_coll)

    # 2. Create mesh with 2 material slots and 2 faces
    mesh_data = bpy.data.meshes.new("DisplayMesh")
    verts = [(0, 0, 0), (1, 0, 0), (1, 1, 0), (0, 1, 0), (0, 0, 1), (1, 0, 1)]
    faces = [(0, 1, 2, 3), (0, 1, 5, 4)]
    mesh_data.from_pydata(verts, [], faces)
    mesh_data.uv_layers.new(name="UVMap")
    mesh_data.update()

    obj = bpy.data.objects.new("DisplayObj", mesh_data)
    obj.tw_lod_index = "LOD01"
    display_coll.objects.link(obj)

    # Material 1: Dirtmap Total War shader
    mat1 = bpy.data.materials.new("DirtMat1")
    mat1.tw_shader_type = "tiled_dirtmap"
    create_total_war_material(mat1)
    obj.data.materials.append(mat1)

    # Material 2: Dirtmap Total War shader
    mat2 = bpy.data.materials.new("DirtMat2")
    mat2.tw_shader_type = "tiled_dirtmap"
    create_total_war_material(mat2)
    obj.data.materials.append(mat2)

    # Assign face 0 -> Mat 1 (slot 0), face 1 -> Mat 2 (slot 1)
    mesh_data.polygons[0].material_index = 0
    mesh_data.polygons[1].material_index = 1

    # Set textures on Mat1 (Gloss, Level, Specular, Dirtmap)
    img_diff1 = bpy.data.images.new("diff1.png", width=4, height=4)
    img_diff1.filepath = r"C:\textures\diff1.png"
    mat1.node_tree.nodes["Diffuse"].image = img_diff1

    img_gloss1 = bpy.data.images.new("gloss1.png", width=4, height=4)
    img_gloss1.filepath = r"C:\textures\gloss1.png"
    mat1.node_tree.nodes["Gloss"].image = img_gloss1

    img_level1 = bpy.data.images.new("level1.png", width=4, height=4)
    img_level1.filepath = r"C:\textures\level1.png"
    mat1.node_tree.nodes["Level"].image = img_level1

    img_spec1 = bpy.data.images.new("spec1.png", width=4, height=4)
    img_spec1.filepath = r"C:\textures\spec1.png"
    mat1.node_tree.nodes["Specular"].image = img_spec1

    img_dirt1 = bpy.data.images.new("dirt1.png", width=4, height=4)
    img_dirt1.filepath = r"C:\textures\dirt1.png"
    mat1.node_tree.nodes["Dirtmap"].image = img_dirt1

    # Set textures on Mat2
    img_diff2 = bpy.data.images.new("diff2.png", width=4, height=4)
    img_diff2.filepath = r"C:\textures\diff2.png"
    mat2.node_tree.nodes["Diffuse"].image = img_diff2

    img_gloss2 = bpy.data.images.new("gloss2.png", width=4, height=4)
    img_gloss2.filepath = r"C:\textures\gloss2.png"
    mat2.node_tree.nodes["Gloss"].image = img_gloss2

    img_spec2 = bpy.data.images.new("spec2.png", width=4, height=4)
    img_spec2.filepath = r"C:\textures\spec2.png"
    mat2.node_tree.nodes["Specular"].image = img_spec2

    # Collision Box
    col_mesh = bpy.data.meshes.new("CollisionMesh")
    col_mesh.from_pydata(verts, [], [(0, 1, 2, 3)])
    col_obj = bpy.data.objects.new("CollisionObj", col_mesh)
    col_obj.tw_collision_type = "COLLISION"
    collision_coll.objects.link(col_obj)

    # 3. Extract building
    depsgraph = bpy.context.evaluated_depsgraph_get()
    building, warnings = extract_building(building_coll, depsgraph, bpy.context.scene)
    print("Extracted building warnings:", warnings)

    assert len(building.pieces[0].destruct_levels[0].lod_meshes) == 1
    lod_mesh = building.pieces[0].destruct_levels[0].lod_meshes[0]
    print("LOD Mesh materials count:", len(lod_mesh.materials))
    assert len(lod_mesh.materials) == 2, f"Expected 2 materials, got {len(lod_mesh.materials)}"

    # 4. Build CS2 Document and serialize
    doc = build_cs2_document(building, assembly_kit_root=r"D:\AK")
    print("CS2 Materials count:", len(doc.materials))
    assert len(doc.materials) == 2, f"Expected 2 CS2 materials, got {len(doc.materials)}"

    # Check submeshes on LOD rigid model node
    lod_node = doc.rigid_models[0]
    submeshes = lod_node.geometry_chunks[0].submeshes
    print("LOD RigidModel submeshes count:", len(submeshes))
    assert len(submeshes) == 2, f"Expected 2 submeshes, got {len(submeshes)}"
    assert submeshes[0].material_id == 0
    assert submeshes[1].material_id == 1

    # Serialize & deserialize byte stream
    bytes_out = write_cs2(doc)
    re_doc = read_cs2(bytes_out)

    assert len(re_doc.materials) == 2
    mat_node1 = re_doc.materials[0]
    mat_node2 = re_doc.materials[1]

    # Verify texture paths in CS2 DirectX material
    tex_dict1 = {t.texture_name: t.texture_path for t in mat_node1.directx_material.textures}
    print("Mat 1 Textures:", tex_dict1)
    assert "diff1.png" in tex_dict1["t_albedo"]
    assert "gloss1.png" in tex_dict1["t_smoothness"]
    assert "level1.png" in tex_dict1["t_reflectivity"]
    assert "spec1.png" in tex_dict1["t_specular_colour"]
    assert "dirt1.png" in tex_dict1["t_dirtmap_uv2"]

    tex_dict2 = {t.texture_name: t.texture_path for t in mat_node2.directx_material.textures}
    print("Mat 2 Textures:", tex_dict2)
    assert "diff2.png" in tex_dict2["t_albedo"]
    assert "gloss2.png" in tex_dict2["t_smoothness"]
    assert "spec2.png" in tex_dict2["t_specular_colour"]

    # Verify b_do_dirt = 1 attribute
    int_attrs1 = {ia.name: ia.value for ia in mat_node1.directx_material.integer_attributes}
    print("Mat 1 Int Attrs:", int_attrs1)
    assert int_attrs1["b_do_dirt"] == 1

    print("=== MULTI-MATERIAL TEST PASSED SUCCESSFULLY ===")

if __name__ == "__main__":
    test_multi_material_export()
