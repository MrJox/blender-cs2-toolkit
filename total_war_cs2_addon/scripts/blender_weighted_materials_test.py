import sys
import traceback

import addon_utils
import bpy

REPO_ROOT = r"C:\Users\Khaiali\source\repos\blender_buildings_plugin"

if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

WEIGHTED_SHADER_TYPES = (
    "weighted",
    "weighted_dirtmap",
    "weighted_skin",
    "weighted_skin_dirtmap",
    "weighted_decal",
    "weighted_decal_dirtmap",
    "weighted_skin_decal",
    "weighted_skin_decal_dirtmap",
)
BUILDING_SHADER_TYPES = ("default", "tiled_dirtmap", "ship_ambientmap", "terrain_blend")

failures = []


def check(label: str, condition: bool) -> None:
    print(("  OK   " if condition else "  FAIL ") + label)
    if not condition:
        failures.append(label)


def build(shader_type: str) -> bpy.types.Material:
    from materials.material_builder import create_total_war_material

    material = bpy.data.materials.new(shader_type)
    material.tw_shader_type = shader_type
    create_total_war_material(material)
    return material


def node_labels(material: bpy.types.Material) -> set:
    return {node.label for node in material.node_tree.nodes} | {node.name for node in material.node_tree.nodes}


def linked_from_name(socket) -> str:
    # bpy wrappers are recreated on every lookup, so compare by name rather than identity.
    return socket.links[0].from_node.name if socket.links else ""


def linked_from_label(socket) -> str:
    return socket.links[0].from_node.label if socket.links else ""


def main() -> None:
    module = addon_utils.enable("total_war_cs2_addon", default_set=True, persistent=False)
    if module is None:
        raise RuntimeError("addon_utils.enable returned failure")

    from materials.fx_nodegroup import (
        DECAL_DIRTMAP_NODE_GROUP_NAME,
        FX_NODE_GROUP_NAME,
        SKIN_NODE_GROUP_NAME,
        LIGHTING_GROUP_NAMES,
        ensure_groups,
        sync_light,
    )
    from materials.shader_types import (
        SHADER_TYPES,
        SHADER_TYPE_WORKFLOWS,
        SKIN_SHADER_TYPES,
        DECAL_DIRTMAP_SHADER_TYPES,
        DECAL_SHADER_TYPES,
        shader_types_for_workflow,
    )
    from materials.material_builder import SHADER_FEATURES, read_material_def, is_placeholder_image
    from materials.template import _TECHNIQUE_INDEX_BY_RIGID_MATERIAL

    print("=== shader type registration ===")
    identifiers = [entry[0] for entry in SHADER_TYPES]
    for shader_type in WEIGHTED_SHADER_TYPES:
        check(f"{shader_type} is a registered shader type", shader_type in identifiers)
        check(f"{shader_type} has a feature set", shader_type in SHADER_FEATURES)
        check(f"{shader_type} is offered to the unit workflow",
              shader_type in [e[0] for e in shader_types_for_workflow("UNIT")])
        check(f"{shader_type} is not offered to the building workflow",
              shader_type not in [e[0] for e in shader_types_for_workflow("BUILDING")])
    check("every shader type is mapped to workflows", set(SHADER_TYPE_WORKFLOWS) == set(identifiers))

    print("=== technique indices match standard_lighting_assembly_kit.fx ===")
    # Full_standard 0, Full_standard_decaldirt 3, Full_custom_terrain 4, Full_ao 5, Full_dirtmap 6,
    # Full_skin 7 - the 0-based order of the technique blocks in the .fx.
    expected = {
        "default": 0,
        "weighted": 0,
        "weighted_dirtmap": 3,
        "terrain_blend": 4,
        "ship_ambientmap": 5,
        "tiled_dirtmap": 6,
        "weighted_skin": 7,
        "weighted_skin_dirtmap": 7,
        "weighted_decal": 3,
        "weighted_decal_dirtmap": 3,
        "weighted_skin_decal": 7,
        "weighted_skin_decal_dirtmap": 7,
    }
    for shader_type, index in expected.items():
        check(f"{shader_type} -> technique {index}",
              _TECHNIQUE_INDEX_BY_RIGID_MATERIAL.get(shader_type, 0) == index)

    print("=== node groups ===")
    groups = ensure_groups()
    check("the skin lighting group exists", SKIN_NODE_GROUP_NAME in groups)
    check("the decal dirtmap blend group exists", DECAL_DIRTMAP_NODE_GROUP_NAME in groups)
    check("both lighting groups are synced by sync_light",
          set(LIGHTING_GROUP_NAMES) == {FX_NODE_GROUP_NAME, SKIN_NODE_GROUP_NAME})
    skin_group = groups[SKIN_NODE_GROUP_NAME]
    skin_inputs = {socket.name for socket in skin_group.interface.items_tree if socket.item_type == "SOCKET" and socket.in_out == "INPUT"}
    check("skin group exposes the SkinLightingModelMaterial fields",
          {"Diffuse Colour", "Gloss", "Specular Level", "Rim Mask", "Sub Surface Strength",
           "Back Scatter Strength", "Normal"} == skin_inputs)
    check("skin group has no specular colour input - ps30_full_skin never reads one",
          "Specular Colour" not in skin_inputs)

    print("=== built materials ===")
    for shader_type in WEIGHTED_SHADER_TYPES:
        material = build(shader_type)
        labels = node_labels(material)
        fx = material.node_tree.nodes.get("Full_skin") or material.node_tree.nodes.get("Full_standard")
        check(f"{shader_type}: builds a lighting group node", fx is not None)

        wants_skin = shader_type in SKIN_SHADER_TYPES
        check(f"{shader_type}: uses the {'skin' if wants_skin else 'standard'} lighting model",
              fx.node_tree.name == (SKIN_NODE_GROUP_NAME if wants_skin else FX_NODE_GROUP_NAME))

        wants_dirt = shader_type in DECAL_DIRTMAP_SHADER_TYPES
        check(f"{shader_type}: decal dirtmap blend {'present' if wants_dirt else 'absent'}",
              ("Decal Dirtmap Blend" in labels) == wants_dirt)
        check(f"{shader_type}: decal dirtmap textures {'present' if wants_dirt else 'absent'}",
              ("Decal Dirtmap" in labels and "Decal Dirtmask" in labels) == wants_dirt)

        wants_decal = shader_type in DECAL_SHADER_TYPES
        check(f"{shader_type}: decal blend {'present' if wants_decal else 'absent'}",
              ("decalblend" in labels) == wants_decal)
        check(f"{shader_type}: decal textures {'present' if wants_decal else 'absent'}",
              all(slot in labels for slot in ("Decal Diffuse", "Decal Normal", "Decal Mask")) == wants_decal)
        check(f"{shader_type}: no vertex alpha gate - the weighted shaders pass valpha 1.0",
              "Vertex Alpha" not in labels)

        check(f"{shader_type}: faction tint {'absent' if wants_skin else 'present'}",
              ("Faction Tint" in labels) != wants_skin)
        check(f"{shader_type}: does not use the tiled dirtmap blend", "Dirtmap Blend" not in labels)
        check(f"{shader_type}: reads no UV2 - neither ps30_full_skin nor ps_common_blend_dirtmap does",
              "UV2" not in labels)

        if wants_skin:
            for socket in ("Rim Mask", "Sub Surface Strength", "Back Scatter Strength"):
                check(f"{shader_type}: {socket} is driven by a mask", fx.inputs[socket].is_linked)
            check(f"{shader_type}: Gloss driven by the smoothness map", fx.inputs["Gloss"].is_linked)
            check(f"{shader_type}: Specular Level driven by the reflectivity map",
                  fx.inputs["Specular Level"].is_linked)
        else:
            check(f"{shader_type}: Specular Colour driven", fx.inputs["Specular Colour"].is_linked)

        if wants_decal:
            decalblend = material.node_tree.nodes["decalblend"]
            check(f"{shader_type}: decalblend is decal_mask.a * decal_diffuse.a",
                  decalblend.inputs[0].is_linked and not decalblend.inputs[1].is_linked
                  and abs(decalblend.inputs[1].default_value - 1.0) < 1e-6)
            check(f"{shader_type}: the decal lerps reflectivity toward half", "Reflectivity x Decal" in labels)
            if not wants_dirt:
                check(f"{shader_type}: the decal perturbs the normal",
                      linked_from_label(material.node_tree.nodes["Normal Map"].inputs["Color"]) == "blended normal")

        if wants_dirt:
            offset = material.node_tree.nodes["Dirt UV Offset"]
            check(f"{shader_type}: the dirt sample is offset before it is tiled",
                  abs(offset.inputs[1].default_value[0] - 0.5) < 1e-6
                  and linked_from_name(material.node_tree.nodes["Dirtmap Tiling"].inputs["Vector"]) == offset.name)
            blend = material.node_tree.nodes["Decal Dirtmap Blend"]
            check(f"{shader_type}: dirtmap alpha feeds the blend", blend.inputs["Dirtmap Alpha"].is_linked)
            check(f"{shader_type}: dirtmask alpha feeds the blend", blend.inputs["Dirtmask Alpha"].is_linked)
            check(f"{shader_type}: the blend perturbs the normal",
                  linked_from_name(material.node_tree.nodes["Normal Map"].inputs["Color"]) == blend.name)

        definition = read_material_def(material)
        check(f"{shader_type}: read_material_def round-trips the shader type",
              definition.shader_type == shader_type)
        check(f"{shader_type}: decal dirtmap paths are read back as a pair",
              len(definition.decal_dirtmap_texture_paths) == 2)

    print("=== building materials still build unchanged ===")
    for shader_type in BUILDING_SHADER_TYPES:
        material = build(shader_type)
        labels = node_labels(material)
        fx = material.node_tree.nodes.get("Full_standard")
        check(f"{shader_type}: still uses the standard lighting model",
              fx is not None and fx.node_tree.name == FX_NODE_GROUP_NAME)
        check(f"{shader_type}: no skin or decal dirt nodes leaked in",
              "Decal Dirtmap Blend" not in labels)
        if shader_type == "default":
            check("default: still tinted", "Faction Tint" in labels)
        if shader_type == "tiled_dirtmap":
            check("tiled_dirtmap: still uses the tiled blend on UV2",
                  "Dirtmap Blend" in labels and "UV2" in labels)
        if shader_type == "ship_ambientmap":
            check("ship_ambientmap: still samples the ambient map on UV2",
                  "Ambient Map" in labels and "UV2" in labels)

    print("=== placeholder textures follow the .fx defaults ===")
    material = build("weighted_dirtmap")
    for slot, expected_colour in (("Decal Dirtmap", 0.498), ("Decal Dirtmask", 0.0)):
        node = material.node_tree.nodes[slot]
        check(f"{slot} starts as a placeholder", is_placeholder_image(node.image))
        check(f"{slot} is Non-Color", node.image.colorspace_settings.name == "Non-Color")
        check(f"{slot} matches its .fx default", abs(node.image.pixels[0] - expected_colour) < 0.01)

    print("=== export carries the new textures ===")
    from materials.template import build_directx_material_node

    node = build_directx_material_node(
        node_name="probe",
        material_name="probe",
        rigid_material="weighted_dirtmap",
        assembly_kit_root="D:\\kit",
        decal_dirtmap_texture_paths=("dirt.dds", "mask.dds"),
    )
    textures = {texture.texture_name: texture.texture_path for texture in node.directx_material.textures}
    check("t_decal_dirtmap exported", textures.get("t_decal_dirtmap") == "dirt.dds")
    check("t_decal_dirtmask exported", textures.get("t_decal_dirtmask") == "mask.dds")
    integers = {attribute.name: attribute.value for attribute in node.directx_material.integer_attributes}
    check("b_do_dirt set for a dirtmap shader", integers.get("b_do_dirt") == 1)
    check("i_random_tile_u set - every real decal-dirtmap mesh carries 1", integers.get("i_random_tile_u") == 1)
    check("i_random_tile_v set", integers.get("i_random_tile_v") == 1)
    floats = {attribute.name: attribute.value for attribute in node.directx_material.float_attributes}
    check("f_uv_offset_u defaults to 0.5", abs(floats.get("f_uv_offset_u", 0.0) - 0.5) < 1e-6)
    check("f_uv_offset_v defaults to 0.5", abs(floats.get("f_uv_offset_v", 0.0) - 0.5) < 1e-6)
    check("i_bone_influences is 2 - the authored weight limit", integers.get("i_bone_influences") == 2)

    tiled = build_directx_material_node(
        node_name="tiled", material_name="tiled", rigid_material="tiled_dirtmap", assembly_kit_root="D:/kit"
    )
    tiled_integers = {a.name: a.value for a in tiled.directx_material.integer_attributes}
    check("tiled_dirtmap keeps random tile off - ps30_full_dirtmap never reads it",
          tiled_integers.get("i_random_tile_u") == 0 and tiled_integers.get("i_random_tile_v") == 0)
    check("b_do_decal left off for a dirtmap-only shader", integers.get("b_do_decal") == 0)
    check("weighted_dirtmap writes technique 3", node.directx_material.shader_technique_index == 3)

    for shader_type in ("weighted_decal", "weighted_decal_dirtmap", "weighted_skin_decal",
                        "weighted_skin_decal_dirtmap"):
        decal_node = build_directx_material_node(
            node_name=shader_type, material_name=shader_type, rigid_material=shader_type,
            assembly_kit_root="D:/kit", decal_texture_paths=("d.dds", "n.dds", "m.dds"),
        )
        decal_integers = {a.name: a.value for a in decal_node.directx_material.integer_attributes}
        decal_textures = {t.texture_name: t.texture_path for t in decal_node.directx_material.textures}
        check(f"{shader_type}: b_do_decal set", decal_integers.get("b_do_decal") == 1)
        wants_dirt = shader_type.endswith("dirtmap")
        check(f"{shader_type}: b_do_dirt {'set' if wants_dirt else 'off'}",
              decal_integers.get("b_do_dirt") == (1 if wants_dirt else 0))
        check(f"{shader_type}: random tile follows the dirt blend",
              decal_integers.get("i_random_tile_u") == (1 if wants_dirt else 0))
        check(f"{shader_type}: decal slots exported",
              [decal_textures.get(name) for name in ("t_decal_diffuse", "t_decal_normal", "t_decal_mask")]
              == ["d.dds", "n.dds", "m.dds"])

    terrain = build_directx_material_node(
        node_name="terrain", material_name="terrain", rigid_material="terrain_blend",
        assembly_kit_root="D:/kit", decal_texture_paths=("d.dds", "n.dds", "m.dds"),
    )
    terrain_integers = {a.name: a.value for a in terrain.directx_material.integer_attributes}
    check("terrain_blend keeps b_do_decal off - ps30_main_custom_terrain never reads it",
          terrain_integers.get("b_do_decal") == 0)

    print("=== i_alpha_mode and f_uv_offset are driven ===")
    from materials.shader_types import ALPHA_MODE_VALUES, DEFAULT_ALPHA_MODE

    check("alpha mode defaults to what real samples carry", DEFAULT_ALPHA_MODE == "NONE")
    default_material = build("weighted")
    check("default material does not clip - alpha_test() is a no-op unless i_alpha_mode is 1",
          default_material.node_tree.nodes.get("alpha_test") is None)
    check("default material stays fully opaque",
          abs(default_material.node_tree.nodes["Mix Shader"].inputs["Fac"].default_value - 1.0) < 1e-6)

    clipped = bpy.data.materials.new("clipped")
    clipped.tw_shader_type = "weighted"
    clipped.tw_alpha_mode = "ALPHA_TEST"
    from materials.material_builder import create_total_war_material

    create_total_war_material(clipped)
    alpha_node = clipped.node_tree.nodes.get("alpha_test")
    check("alpha test mode wires the clip", alpha_node is not None)
    check("the clip reference is the shader's fixed 0.5",
          abs(alpha_node.inputs[1].default_value - 0.5) < 1e-6)
    check("the clip drives the mix shader",
          linked_from_name(clipped.node_tree.nodes["Mix Shader"].inputs["Fac"]) == alpha_node.name)

    blended = bpy.data.materials.new("blended")
    blended.tw_shader_type = "weighted"
    blended.tw_alpha_mode = "BLEND"
    create_total_war_material(blended)
    check("blend mode drives the mix straight from the diffuse alpha",
          linked_from_name(blended.node_tree.nodes["Mix Shader"].inputs["Fac"]) == "Diffuse")
    check("blend mode does not clip", blended.node_tree.nodes.get("alpha_test") is None)
    check("blend mode asks Blender for real blending", blended.surface_render_method == "BLENDED")
    check("alpha test mode stays dithered", clipped.surface_render_method == "DITHERED")
    check("default mode stays dithered", default_material.surface_render_method == "DITHERED")

    for mode, expected in (("NONE", 0xFFFFFFFF), ("OPAQUE", 0), ("ALPHA_TEST", 1), ("BLEND", 2)):
        probe = bpy.data.materials.new(f"mode {mode}")
        probe.tw_shader_type = "weighted"
        probe.tw_alpha_mode = mode
        create_total_war_material(probe)
        definition = read_material_def(probe)
        check(f"{mode}: read back as {ALPHA_MODE_VALUES[mode]}", definition.alpha_mode == ALPHA_MODE_VALUES[mode])
        exported = build_directx_material_node(
            node_name=mode, material_name=mode, rigid_material="weighted",
            assembly_kit_root="D:/kit", alpha_mode=definition.alpha_mode,
        )
        written = {a.name: a.value for a in exported.directx_material.integer_attributes}
        check(f"{mode}: exported as i_alpha_mode {expected}", written.get("i_alpha_mode") == expected)

    dirty = build("weighted_dirtmap")
    dirty.node_tree.nodes["Dirt UV Offset"].inputs[1].default_value = (0.25, 0.75, 0.0)
    definition = read_material_def(dirty)
    check("f_uv_offset_u read back from the node", abs(definition.dirt_uv_offset_u - 0.25) < 1e-6)
    check("f_uv_offset_v read back from the node", abs(definition.dirt_uv_offset_v - 0.75) < 1e-6)
    exported = build_directx_material_node(
        node_name="dirty", material_name="dirty", rigid_material="weighted_dirtmap",
        assembly_kit_root="D:/kit",
        dirt_uv_offset_u=definition.dirt_uv_offset_u, dirt_uv_offset_v=definition.dirt_uv_offset_v,
    )
    written = {a.name: a.value for a in exported.directx_material.float_attributes}
    check("f_uv_offset_u exported", abs(written.get("f_uv_offset_u", 0.0) - 0.25) < 1e-6)
    check("f_uv_offset_v exported", abs(written.get("f_uv_offset_v", 0.0) - 0.75) < 1e-6)

    print("=== light sync reaches both lighting groups ===")
    light_data = bpy.data.lights.new("probe sun", type="SUN")
    light_object = bpy.data.objects.new("probe sun", light_data)
    bpy.context.scene.collection.objects.link(light_object)
    light_object.data.color = (0.25, 0.5, 0.75)
    sync_light(light_object)
    for name in LIGHTING_GROUP_NAMES:
        colour = bpy.data.node_groups[name].nodes["Light Colour"].outputs[0].default_value
        check(f"{name} received the light colour", abs(colour[0] - 0.25) < 1e-4)

    print()
    if failures:
        print(f"FAILED {len(failures)} check(s):")
        for failure in failures:
            print("   ", failure)
        raise SystemExit(1)
    print("=== WEIGHTED MATERIALS TEST PASSED ===")


try:
    main()
except Exception:
    traceback.print_exc()
    sys.exit(1)
