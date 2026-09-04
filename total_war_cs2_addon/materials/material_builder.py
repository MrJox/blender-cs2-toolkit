import bpy

from materials.fx_nodegroup import (
    DECAL_DIRTMAP_NODE_GROUP_NAME,
    DEFAULT_TINT_COLOURS,
    DIRTMAP_NODE_GROUP_NAME,
    FX_NODE_GROUP_NAME,
    SKIN_NODE_GROUP_NAME,
    TINT_NODE_GROUP_NAME,
    ensure_groups,
)
from materials.shader_types import (
    DEFAULT_SHADER_TYPE,
    DIRT_UV_OFFSET,
    ALPHA_MODE_VALUES,
    DEFAULT_ALPHA_MODE,
    ALPHA_TEST_ALPHA_MODE,
    BLEND_ALPHA_MODE,
)
from scene_model.models import MaterialDef

TEXTURE_SLOT_LABELS = (
    "Diffuse",
    "Normal",
    "Mask",
    "Ambient Map",
    "Dirtmap",
    "Dirtmask",
    "Gloss",
    "Level",
    "Specular",
    "Tint Mask 1",
    "Tint Mask 2",
    "Tint Mask 3",
    "Decal Diffuse",
    "Decal Normal",
    "Decal Mask",
    "Decal Dirtmap",
    "Decal Dirtmask",
)

# An unassigned ShaderNodeTexImage doesn't render as its output socket's default_value (that only
# matters for an unconnected socket being read directly) - Cycles/EEVEE both evaluate it as a real
# "missing texture" node and show magenta, confirmed by rendering it directly. Every texture slot
# therefore gets a real generated placeholder image at creation time instead of being left
# `image = None`, tagged with this custom property so validation/export can tell "still just the
# placeholder" apart from "the artist assigned something".
TW_PLACEHOLDER_MARKER = "tw_placeholder"

# Every placeholder reproduces the slot's own default texture in standard_lighting_assembly_kit.fx -
# the `string name` annotation on each `texture` block - using the real pixel values read out of the
# Assembly Kit's own max_exporter/max_shader folder. Note this means the AO, dirtmap and dirtmask
# slots default to black, exactly as the unconfigured Max shader does, so those variants render black
# until the artist assigns a texture.
_FX_DEFAULT_TEXTURES = {
    "test_gray.tga": (0.498, 0.498, 0.498, 1.0),
    "test_white.tga": (1.0, 1.0, 1.0, 1.0),
    "test_black.tga": (0.0, 0.0, 0.0, 1.0),
    # flatnormal.tga's own alpha is 220/255, but no technique samples the normal map's alpha.
    "flatnormal.tga": (0.502, 0.502, 1.0, 1.0),
}

_FX_DEFAULT_TEXTURE_BY_SLOT = {
    "Diffuse": "test_gray.tga",
    "Normal": "flatnormal.tga",
    "Mask": "test_black.tga",
    "Ambient Map": "test_black.tga",
    "Dirtmap": "test_black.tga",
    "Dirtmask": "test_black.tga",
    "Gloss": "test_gray.tga",
    "Level": "test_gray.tga",
    "Specular": "test_gray.tga",
    "Tint Mask 1": "test_black.tga",
    "Tint Mask 2": "test_black.tga",
    "Tint Mask 3": "test_black.tga",
    "Decal Diffuse": "test_gray.tga",
    # The .fx annotates t_decal_normal as test_gray.tga too. That looks like a slip next to
    # flatnormal.tga, but it is harmless and in fact neutral here: the blend adds (Cd - 0.5), so a
    # 0.498 grey contributes essentially nothing, exactly like a flat normal would.
    "Decal Normal": "test_gray.tga",
    "Decal Mask": "test_white.tga",
    "Decal Dirtmap": "test_gray.tga",
    "Decal Dirtmask": "test_black.tga",
}

_PLACEHOLDER_COLORS = {
    slot: _FX_DEFAULT_TEXTURES[texture] for slot, texture in _FX_DEFAULT_TEXTURE_BY_SLOT.items()
}

# SRGBTexture in each slot's sampler_state block: TRUE means the sampler linearises, which is what
# Blender's sRGB colorspace does, so only the FALSE ones become Non-Color.
_NON_COLOR_SLOTS = frozenset(
    {
        "Normal",
        "Mask",
        "Ambient Map",
        "Dirtmask",
        "Tint Mask 1",
        "Tint Mask 2",
        "Tint Mask 3",
        "Decal Normal",
        "Decal Mask",
        "Decal Dirtmap",
        "Decal Dirtmask",
    }
)

# f_uv2_tile_interval_u/v's default in materials/template.py's float attribute template - reused
# here as the "Dirtmap Tiling" Mapping node's own default Scale so the Blender preview and the
# exported CS2 attribute start in agreement (see read_material_def, which reads the Scale back).
DEFAULT_DIRTMAP_TILE = 4.0

# ALPHAREF 128 in the Full_standard technique block, i.e. texture_alpha_ref.
ALPHA_TEST_REF = 0.5


def _placeholder_image(slot_label: str) -> bpy.types.Image:
    name = f"TW_Placeholder_{slot_label}"
    existing = bpy.data.images.get(name)
    if existing is not None and existing.get(TW_PLACEHOLDER_MARKER):
        return existing
    # Non-Color slots get a float buffer so the value written is the value sampled, with no 8-bit
    # rounding in between. sRGB slots stay byte buffers so they go through the same decode a real
    # texture would.
    non_color = slot_label in _NON_COLOR_SLOTS
    image = bpy.data.images.new(name, width=4, height=4, alpha=False, float_buffer=non_color)
    # Assigning colorspace_settings discards the image buffer, so it has to happen before the pixels
    # are written - doing it the other way round leaves every Non-Color slot solid black.
    if non_color:
        try:
            image.colorspace_settings.name = "Non-Color"
        except Exception:
            pass
    image.pixels = list(_PLACEHOLDER_COLORS[slot_label]) * (4 * 4)
    image[TW_PLACEHOLDER_MARKER] = True
    return image


def is_placeholder_image(image: bpy.types.Image | None) -> bool:
    if image is None:
        return True
    if not image.get(TW_PLACEHOLDER_MARKER):
        return False
    path = image.filepath or getattr(image, "filepath_raw", "")
    if path and image.source != "GENERATED":
        return False
    return True


def _texture_node(node_tree: bpy.types.NodeTree, label: str, location: tuple[float, float]):
    node = node_tree.nodes.new("ShaderNodeTexImage")
    node.label = label
    node.name = label
    node.location = location
    node.image = _placeholder_image(label)
    return node


def _red_channel(node_tree: bpy.types.NodeTree, source, location: tuple[float, float]):
    node = node_tree.nodes.new("ShaderNodeSeparateColor")
    node.location = location
    node_tree.links.new(source, node.inputs["Color"])
    return node.outputs["Red"]


def _vec(node_tree: bpy.types.NodeTree, operation: str, location, label: str = ""):
    node = node_tree.nodes.new("ShaderNodeVectorMath")
    node.operation = operation
    node.location = location
    node.label = label
    node.name = label or node.name
    return node


def _multiply(node_tree: bpy.types.NodeTree, a, b, location, label: str = ""):
    node = _vec(node_tree, "MULTIPLY", location, label)
    node_tree.links.new(a, node.inputs[0])
    node_tree.links.new(b, node.inputs[1])
    return node


def _lerp(node_tree, a, b, factor, location, label: str = ""):
    node = node_tree.nodes.new("ShaderNodeMix")
    node.data_type = "FLOAT"
    node.location = location
    node.label = label
    node_tree.links.new(factor, node.inputs["Factor"])
    node_tree.links.new(a, node.inputs[2])
    node_tree.links.new(b, node.inputs[3])
    return node.outputs["Result"]


def _vlerp(node_tree, a, b, factor, location, label: str = ""):
    difference = _vec(node_tree, "SUBTRACT", (location[0] - 300, location[1]), f"{label} delta")
    node_tree.links.new(b, difference.inputs[0])
    node_tree.links.new(a, difference.inputs[1])
    node = _vec(node_tree, "MULTIPLY_ADD", location, label)
    node_tree.links.new(difference.outputs["Vector"], node.inputs[0])
    node_tree.links.new(factor, node.inputs[1])
    node_tree.links.new(a, node.inputs[2])
    return node.outputs["Vector"]


def _build_decal(node_tree, diffuse, specular, reflectivity, normal_colour, vertex_alpha: bool, dy: int):
    # ps_common_blend_decal blends the asset's own material toward the decal set:
    #   decalblend   = decal_mask.a * decal_diffuse.a * valpha
    #   diffuse      = lerp(diffuse,      decal_diffuse.rgb, decalblend)
    #   specular     = lerp(specular,     decal_diffuse.rgb, decalblend)
    #   reflectivity = lerp(reflectivity, reflectivity * 0.5, decalblend)
    #   normal.xy   += lerp((0,0,1), decal_normal, decalblend).xy
    # ps30_main_custom_terrain passes valpha = 1 - vertex alpha so the mesh can paint the decal out
    # per vertex; ps30_main_decaldirt and ps30_full_skin both pass a literal 1.0 instead.
    # In game the decal side is the battlefield terrain projected onto the asset; in the Max preview,
    # and here, it is whatever the decal slots hold. vec4_uv_rect is (0,0,1,1) in every real sample and
    # the exporter writes that, so the decal samples the same UV as everything else.
    decal_diffuse_node = _texture_node(node_tree, "Decal Diffuse", (-1400, -550 + dy))
    decal_normal_node = _texture_node(node_tree, "Decal Normal", (-1400, -900 + dy))
    decal_mask_node = _texture_node(node_tree, "Decal Mask", (-1400, -1250 + dy))

    masked = node_tree.nodes.new("ShaderNodeMath")
    masked.operation = "MULTIPLY"
    masked.location = (-700, -1250 + dy)
    node_tree.links.new(decal_mask_node.outputs["Alpha"], masked.inputs[0])
    node_tree.links.new(decal_diffuse_node.outputs["Alpha"], masked.inputs[1])

    decalblend = node_tree.nodes.new("ShaderNodeMath")
    decalblend.operation = "MULTIPLY"
    decalblend.name = decalblend.label = "decalblend"
    decalblend.location = (-350, -1250 + dy)
    node_tree.links.new(masked.outputs["Value"], decalblend.inputs[0])
    if vertex_alpha:
        vertex_colour = node_tree.nodes.new("ShaderNodeVertexColor")
        vertex_colour.name = vertex_colour.label = "Vertex Alpha"
        vertex_colour.location = (-1400, -1600 + dy)

        one_minus_alpha = node_tree.nodes.new("ShaderNodeMath")
        one_minus_alpha.operation = "SUBTRACT"
        one_minus_alpha.label = "1 - vertex alpha"
        one_minus_alpha.location = (-1050, -1600 + dy)
        one_minus_alpha.inputs[0].default_value = 1.0
        node_tree.links.new(vertex_colour.outputs["Alpha"], one_minus_alpha.inputs[1])
        node_tree.links.new(one_minus_alpha.outputs["Value"], decalblend.inputs[1])
    else:
        decalblend.inputs[1].default_value = 1.0
    blend = decalblend.outputs["Value"]

    diffuse = _vlerp(
        node_tree, diffuse, decal_diffuse_node.outputs["Color"], blend, (300, 1200 + dy), "Diffuse x Decal"
    )
    specular = _vlerp(
        node_tree, specular, decal_diffuse_node.outputs["Color"], blend, (300, -200 + dy), "Specular x Decal"
    )

    half_reflectivity = node_tree.nodes.new("ShaderNodeMath")
    half_reflectivity.operation = "MULTIPLY"
    half_reflectivity.location = (-350, dy)
    half_reflectivity.inputs[1].default_value = 0.5
    node_tree.links.new(reflectivity, half_reflectivity.inputs[0])
    reflectivity = _lerp(
        node_tree, reflectivity, half_reflectivity.outputs["Value"], blend, (0, dy), "Reflectivity x Decal"
    )

    # The shader adds the decal normal's xy onto the base normal's and keeps the base z. Working in
    # texture-colour space that is C = (Cn.xy + blend * (Cd.xy - 0.5), Cn.z), which stays valid ahead
    # of the Normal Map node's own DirectX green flip because the flip is affine in green.
    offset = _vec(node_tree, "SUBTRACT", (-1050, -900 + dy), "decal normal - 0.5")
    node_tree.links.new(decal_normal_node.outputs["Color"], offset.inputs[0])
    offset.inputs[1].default_value = (0.5, 0.5, 0.5)

    combined = _vec(node_tree, "MULTIPLY_ADD", (-700, -900 + dy), "normal + decal normal")
    node_tree.links.new(offset.outputs["Vector"], combined.inputs[0])
    node_tree.links.new(blend, combined.inputs[1])
    node_tree.links.new(normal_colour, combined.inputs[2])

    base_channels = node_tree.nodes.new("ShaderNodeSeparateXYZ")
    base_channels.location = (-700, -1050 + dy)
    node_tree.links.new(normal_colour, base_channels.inputs["Vector"])
    blended_channels = node_tree.nodes.new("ShaderNodeSeparateXYZ")
    blended_channels.location = (-350, -900 + dy)
    node_tree.links.new(combined.outputs["Vector"], blended_channels.inputs["Vector"])
    normal_colour = node_tree.nodes.new("ShaderNodeCombineXYZ")
    normal_colour.label = "blended normal"
    normal_colour.location = (0, -900 + dy)
    node_tree.links.new(blended_channels.outputs["X"], normal_colour.inputs["X"])
    node_tree.links.new(blended_channels.outputs["Y"], normal_colour.inputs["Y"])
    node_tree.links.new(base_channels.outputs["Z"], normal_colour.inputs["Z"])

    return diffuse, specular, reflectivity, normal_colour.outputs["Vector"]


def _build_custom_terrain_material(node_tree, diffuse, specular, reflectivity, normal_colour):
    # ps30_main_custom_terrain is ps30_main_UPDATED without the three tint layers, plus
    # ps_common_blend_decal - which it calls unconditionally, never reading b_do_decal.
    return _build_decal(node_tree, diffuse, specular, reflectivity, normal_colour, vertex_alpha=True, dy=0)


# Which pieces of the .fx each shader type turns on, applied in the order ps30_main_decaldirt and
# ps30_full_skin apply them: base surface, then the tint lerps, then the decal blend, then the dirt
# blend. "skin" is not a surface feature - it swaps the whole lighting model for ps30_full_skin.
SHADER_FEATURES = {
    "default": ("tint",),
    "tiled_dirtmap": ("tiled_dirtmap",),
    "ship_ambientmap": ("ambient_map",),
    "terrain_blend": ("terrain",),
    "weighted": ("tint",),
    "weighted_dirtmap": ("tint", "decal_dirtmap"),
    "weighted_skin": ("skin",),
    "weighted_skin_dirtmap": ("skin", "decal_dirtmap"),
    "weighted_decal": ("tint", "decal"),
    "weighted_decal_dirtmap": ("tint", "decal", "decal_dirtmap"),
    "weighted_skin_decal": ("skin", "decal"),
    "weighted_skin_decal_dirtmap": ("skin", "decal", "decal_dirtmap"),
    # No tint layer: a vegetation mesh carries no faction mask texture at all, and its three
    # COLOUR_ vec4 params are shader constants rather than the mask-driven layers "tint" builds.
    "tree": (),
    "tree_leaf": (),
}


def _build_decal_dirtmap(node_tree, groups, diffuse, specular, normal_colour):
    # ps_common_blend_dirtmap samples both of its maps from TexCoord.xy - UV1 - despite the tile
    # interval being named f_uv2_tile_interval_*. Nothing here reads UV2, unlike tiled_dirtmap.
    # decal_dirtmap only ever appears in SHADER_FEATURES alongside "tint" or "skin", which already
    # occupy the -900..-1600 band of this column (see the tint/skin mask loops below), so this band
    # continues that column's -350-per-slot pattern from -1600 instead of reusing -600/-950 - those
    # coordinates used to collide with "Tint Mask 1"/"Rim Mask" and produced overlapping nodes.
    uv1_node = node_tree.nodes.new("ShaderNodeUVMap")
    uv1_node.label = uv1_node.name = "UV1"
    uv1_node.location = (-2100, -1950)

    # (uv + uv_offset) * tile_interval, in that order - a Mapping node alone would scale first.
    # UV1's own node width (160) is wider than the 150 that separated these columns, which used to
    # overlap it into this node - columns are now spaced past the widest node that occupies them.
    offset_node = _vec(node_tree, "ADD", (-1900, -1950), "Dirt UV Offset")
    offset_node.name = "Dirt UV Offset"
    offset_node.inputs[1].default_value = (DIRT_UV_OFFSET, DIRT_UV_OFFSET, 0.0)
    node_tree.links.new(uv1_node.outputs["UV"], offset_node.inputs[0])

    tiling_node = node_tree.nodes.new("ShaderNodeMapping")
    tiling_node.label = tiling_node.name = "Dirtmap Tiling"
    tiling_node.location = (-1700, -1950)
    tiling_node.inputs["Scale"].default_value = (DEFAULT_DIRTMAP_TILE, DEFAULT_DIRTMAP_TILE, 1.0)
    node_tree.links.new(offset_node.outputs["Vector"], tiling_node.inputs["Vector"])

    dirtmap_node = _texture_node(node_tree, "Decal Dirtmap", (-1400, -1950))
    node_tree.links.new(tiling_node.outputs["Vector"], dirtmap_node.inputs["Vector"])
    dirtmask_node = _texture_node(node_tree, "Decal Dirtmask", (-1400, -2300))

    blend = node_tree.nodes.new("ShaderNodeGroup")
    blend.node_tree = groups[DECAL_DIRTMAP_NODE_GROUP_NAME]
    blend.name = blend.label = "Decal Dirtmap Blend"
    blend.location = (300, 600)
    blend.width = 240
    node_tree.links.new(diffuse, blend.inputs["Diffuse"])
    node_tree.links.new(specular, blend.inputs["Specular"])
    node_tree.links.new(normal_colour, blend.inputs["Normal"])
    node_tree.links.new(dirtmap_node.outputs["Color"], blend.inputs["Dirtmap"])
    node_tree.links.new(dirtmap_node.outputs["Alpha"], blend.inputs["Dirtmap Alpha"])
    node_tree.links.new(dirtmask_node.outputs["Alpha"], blend.inputs["Dirtmask Alpha"])
    return blend.outputs["Diffuse"], blend.outputs["Specular"], blend.outputs["Normal"]


def create_total_war_material(material: bpy.types.Material) -> None:
    material.use_nodes = True
    material.use_backface_culling = True
    node_tree = material.node_tree
    node_tree.nodes.clear()
    groups = ensure_groups()

    output = node_tree.nodes.new("ShaderNodeOutputMaterial")
    output.location = (2000, 600)

    shader_type = getattr(material, "tw_shader_type", "default").lower()
    features = SHADER_FEATURES.get(shader_type, SHADER_FEATURES[DEFAULT_SHADER_TYPE])
    lighting_group = SKIN_NODE_GROUP_NAME if "skin" in features else FX_NODE_GROUP_NAME

    fx = node_tree.nodes.new("ShaderNodeGroup")
    fx.node_tree = groups[lighting_group]
    fx.name = fx.label = lighting_group.removeprefix("TW ")
    fx.location = (1000, 600)
    fx.width = 260

    emission = node_tree.nodes.new("ShaderNodeEmission")
    emission.location = (1400, 700)
    node_tree.links.new(fx.outputs["Colour"], emission.inputs["Color"])

    transparent = node_tree.nodes.new("ShaderNodeBsdfTransparent")
    transparent.location = (1400, 900)

    mix_shader = node_tree.nodes.new("ShaderNodeMixShader")
    mix_shader.location = (1700, 600)
    node_tree.links.new(transparent.outputs["BSDF"], mix_shader.inputs[1])
    node_tree.links.new(emission.outputs["Emission"], mix_shader.inputs[2])
    node_tree.links.new(mix_shader.outputs["Shader"], output.inputs["Surface"])

    diffuse_node = _texture_node(node_tree, "Diffuse", (-1400, 1200))
    normal_tex_node = _texture_node(node_tree, "Normal", (-1400, 850))
    gloss_node = _texture_node(node_tree, "Gloss", (-1400, 500))
    level_node = _texture_node(node_tree, "Level", (-1400, 150))
    specular_node = _texture_node(node_tree, "Specular", (-1400, -200))

    # alpha_test() is a no-op for every i_alpha_mode except 1, so the clip is only wired up when the
    # material asks for it. Blend has no .fx equivalent to copy - the Max preview cannot show it -
    # so the diffuse alpha drives the mix directly, which is what the engine's BLEND mode means.
    alpha_mode = getattr(material, "tw_alpha_mode", DEFAULT_ALPHA_MODE)
    if alpha_mode == ALPHA_TEST_ALPHA_MODE:
        alpha_test = node_tree.nodes.new("ShaderNodeMath")
        alpha_test.operation = "GREATER_THAN"
        alpha_test.label = alpha_test.name = "alpha_test"
        alpha_test.location = (1400, 1100)
        alpha_test.inputs[1].default_value = ALPHA_TEST_REF
        node_tree.links.new(diffuse_node.outputs["Alpha"], alpha_test.inputs[0])
        node_tree.links.new(alpha_test.outputs["Value"], mix_shader.inputs["Fac"])
    elif alpha_mode == BLEND_ALPHA_MODE:
        node_tree.links.new(diffuse_node.outputs["Alpha"], mix_shader.inputs["Fac"])
    else:
        mix_shader.inputs["Fac"].default_value = 1.0
    material.surface_render_method = "BLENDED" if alpha_mode == BLEND_ALPHA_MODE else "DITHERED"

    normal_map_node = node_tree.nodes.new("ShaderNodeNormalMap")
    normal_map_node.location = (-1000, 850)
    # The 3ds Max pipeline these assets come from authors DirectX-convention normal maps (green down).
    # The .fx itself cannot settle this - it maps red/green/blue straight onto Max's own
    # tangent/bitangent/normal with no sign flip - so the convention lives in the texture.
    normal_map_node.convention = "DIRECTX"
    node_tree.links.new(normal_map_node.outputs["Normal"], fx.inputs["Normal"])

    smoothness = _red_channel(node_tree, gloss_node.outputs["Color"], (-1000, 500))
    reflectivity = _red_channel(node_tree, level_node.outputs["Color"], (-1000, 150))
    diffuse = diffuse_node.outputs["Color"]
    specular = specular_node.outputs["Color"]
    normal_colour = normal_tex_node.outputs["Color"]

    if "terrain" in features:
        diffuse, specular, reflectivity, normal_colour = _build_custom_terrain_material(
            node_tree, diffuse, specular, reflectivity, normal_colour
        )
    if "tiled_dirtmap" in features:
        # ps30_full_dirtmap samples the dirtmap from TexCoord.xy (UV1) scaled by the tile interval and
        # the dirtmask from TexCoord.zw (UV2) unscaled - the two come from different channels.
        uv1_node = node_tree.nodes.new("ShaderNodeUVMap")
        uv1_node.label = "UV1"
        uv1_node.name = "UV1"
        uv1_node.location = (-2100, -600)

        dirtmap_tiling_node = node_tree.nodes.new("ShaderNodeMapping")
        dirtmap_tiling_node.label = "Dirtmap Tiling"
        dirtmap_tiling_node.name = "Dirtmap Tiling"
        dirtmap_tiling_node.location = (-1800, -600)
        dirtmap_tiling_node.inputs["Scale"].default_value = (DEFAULT_DIRTMAP_TILE, DEFAULT_DIRTMAP_TILE, 1.0)
        node_tree.links.new(uv1_node.outputs["UV"], dirtmap_tiling_node.inputs["Vector"])

        dirtmap_node = _texture_node(node_tree, "Dirtmap", (-1400, -600))
        node_tree.links.new(dirtmap_tiling_node.outputs["Vector"], dirtmap_node.inputs["Vector"])

        uv2_node = node_tree.nodes.new("ShaderNodeUVMap")
        uv2_node.label = "UV2"
        uv2_node.name = "UV2"
        uv2_node.uv_map = "UV2"
        uv2_node.location = (-1800, -950)

        dirtmask_node = _texture_node(node_tree, "Dirtmask", (-1400, -950))
        node_tree.links.new(uv2_node.outputs["UV"], dirtmask_node.inputs["Vector"])

        blend = node_tree.nodes.new("ShaderNodeGroup")
        blend.node_tree = groups[DIRTMAP_NODE_GROUP_NAME]
        blend.name = "Dirtmap Blend"
        blend.label = "Dirtmap Blend"
        blend.location = (300, 1200)
        blend.width = 240
        node_tree.links.new(diffuse, blend.inputs["Diffuse"])
        node_tree.links.new(specular, blend.inputs["Specular"])
        node_tree.links.new(dirtmap_node.outputs["Color"], blend.inputs["Dirtmap"])
        node_tree.links.new(dirtmap_node.outputs["Alpha"], blend.inputs["Dirtmap Alpha"])
        node_tree.links.new(
            _red_channel(node_tree, dirtmask_node.outputs["Color"], (-1000, -950)), blend.inputs["Dirtmask"]
        )
        diffuse = blend.outputs["Diffuse"]
        specular = blend.outputs["Specular"]
    if "ambient_map" in features:
        # ps30_full_ao: a UV2 ambient-occlusion map multiplied into both diffuse and specular.
        uv2_node = node_tree.nodes.new("ShaderNodeUVMap")
        uv2_node.label = "UV2"
        uv2_node.name = "UV2"
        uv2_node.uv_map = "UV2"
        uv2_node.location = (-1800, -600)

        ao_node = _texture_node(node_tree, "Ambient Map", (-1400, -600))
        node_tree.links.new(uv2_node.outputs["UV"], ao_node.inputs["Vector"])

        diffuse = _multiply(node_tree, diffuse, ao_node.outputs["Color"], (300, 1200), "Diffuse x AO").outputs["Vector"]
        specular = _multiply(node_tree, specular, ao_node.outputs["Color"], (300, -200), "Specular x AO").outputs["Vector"]
    if "tint" in features:
        # ps30_main_UPDATED: three mask-driven tint layers, optionally luminance-adjusted as faction
        # colours. Every mask defaults to test_black.tga, so an untouched material is untinted.
        tint = node_tree.nodes.new("ShaderNodeGroup")
        tint.node_tree = groups[TINT_NODE_GROUP_NAME]
        tint.name = "Faction Tint"
        tint.label = "Faction Tint"
        tint.location = (300, 1200)
        tint.width = 240
        node_tree.links.new(diffuse, tint.inputs["Diffuse"])
        for index in range(1, 4):
            mask_node = _texture_node(node_tree, f"Tint Mask {index}", (-1400, -550 - 350 * index))
            node_tree.links.new(
                _red_channel(node_tree, mask_node.outputs["Color"], (-1000, -550 - 350 * index)),
                tint.inputs[f"Mask {index}"],
            )
            tint.inputs[f"Colour {index}"].default_value = DEFAULT_TINT_COLOURS[index - 1]
        diffuse = tint.outputs["Diffuse"]

    if "decal" in features:
        # Below the tint/skin masks and, when present, the decal-dirtmap band above, which between
        # them occupy the -550..-2300 range of the same column.
        diffuse, specular, reflectivity, normal_colour = _build_decal(
            node_tree, diffuse, specular, reflectivity, normal_colour, vertex_alpha=False, dy=-2400
        )

    if "decal_dirtmap" in features:
        diffuse, specular, normal_colour = _build_decal_dirtmap(
            node_tree, groups, diffuse, specular, normal_colour
        )

    if "skin" in features:
        # create_skin_lighting_material reads mask1/2/3 as rim / subsurface / backscatter instead of
        # as faction tint masks, and never reads the specular colour map at all - which is why a real
        # RS_WEIGHTED_SKIN_V5 mesh carries no specular texture (PLAN_units.md 1.2).
        node_tree.links.new(diffuse, fx.inputs["Diffuse Colour"])
        node_tree.links.new(smoothness, fx.inputs["Gloss"])
        node_tree.links.new(reflectivity, fx.inputs["Specular Level"])
        for index, socket in enumerate(("Rim Mask", "Sub Surface Strength", "Back Scatter Strength"), start=1):
            mask_node = _texture_node(node_tree, f"Tint Mask {index}", (-1400, -550 - 350 * index))
            node_tree.links.new(
                _red_channel(node_tree, mask_node.outputs["Color"], (-1000, -550 - 350 * index)),
                fx.inputs[socket],
            )
    else:
        node_tree.links.new(diffuse, fx.inputs["Diffuse Colour"])
        node_tree.links.new(specular, fx.inputs["Specular Colour"])
        node_tree.links.new(smoothness, fx.inputs["Smoothness"])
        node_tree.links.new(reflectivity, fx.inputs["Reflectivity"])
    node_tree.links.new(normal_colour, normal_map_node.inputs["Color"])


def apply_standard_view_transform(scene: bpy.types.Scene) -> bool:
    # The technique's own _gamma() is the last step of ps30_main_UPDATED, so the node group hands
    # back linear LDR and lets Blender's Standard view transform encode it. Any other view transform
    # (AgX is the factory default) applies a second, different curve on top and the preview stops
    # matching the game.
    if scene.view_settings.view_transform == "Standard":
        return False
    scene.view_settings.view_transform = "Standard"
    return True


def _find_node_by_label_or_name(node_tree: bpy.types.NodeTree, target: str) -> bpy.types.Node | None:
    n = node_tree.nodes.get(target)
    if n is not None:
        return n
    target_lower = target.lower()
    for n in node_tree.nodes:
        if n.label.lower() == target_lower or n.name.lower() == target_lower:
            return n
    return None


def _find_tex_node_for_socket(socket: bpy.types.NodeSocket | None) -> bpy.types.Node | None:
    if socket is None or not socket.is_linked:
        return None
    for link in socket.links:
        from_node = link.from_node
        if from_node.type == "TEX_IMAGE":
            return from_node
        if from_node.type in (
            "INVERT",
            "NORMAL_MAP",
            "CURVE_RGB",
            "MIX_RGB",
            "CLAMP",
            "MATH",
            "MIX",
            "MAPPING",
            "VECT_MATH",
            "SEPARATE_COLOR",
        ):
            for inp in from_node.inputs:
                res = _find_tex_node_for_socket(inp)
                if res is not None:
                    return res
    return None


def _claimed_by_another_slot(node: bpy.types.Node, label: str) -> bool:
    for other in TEXTURE_SLOT_LABELS:
        if other != label and (node.name == other or node.label == other):
            return True
    return False


def _texture_path(node_tree: bpy.types.NodeTree, label: str) -> str:
    candidate_nodes: list[bpy.types.Node] = []

    # 1. Check exact node name or label
    node_by_name = _find_node_by_label_or_name(node_tree, label)
    if node_by_name is not None and node_by_name.type == "TEX_IMAGE":
        candidate_nodes.append(node_by_name)

    # 2. Check substring matching in node name or label (e.g. Dirtmap.001, t_dirtmap_uv2), skipping
    # anything that is exactly another slot - "Mask" is a substring of "Dirtmask"/"Tint Mask 1".
    label_lower = label.lower()
    for n in node_tree.nodes:
        if n.type != "TEX_IMAGE" or n in candidate_nodes or _claimed_by_another_slot(n, label):
            continue
        n_name = n.name.lower()
        n_label = n.label.lower()
        if label_lower in n_name or label_lower in n_label:
            candidate_nodes.append(n)
        elif label_lower == "dirtmask" and ("alpha_mask" in n_name or "alpha_mask" in n_label):
            candidate_nodes.append(n)
        elif label_lower == "dirtmap" and ("t_dirtmap" in n_name or "t_dirtmap" in n_label):
            candidate_nodes.append(n)
        elif label_lower.startswith("tint mask ") and f"t_mask{label_lower[-1]}" in f"{n_name} {n_label}":
            candidate_nodes.append(n)

    # 3. Trace socket connections from shader tree
    bsdf = _find_node_by_label_or_name(node_tree, "Principled BSDF")
    if bsdf is not None:
        traced_node = None
        if label == "Gloss":
            gloss_inv = _find_node_by_label_or_name(node_tree, "Smoothness -> Roughness") or _find_node_by_label_or_name(node_tree, "Invert Color")
            if gloss_inv is not None:
                traced_node = _find_tex_node_for_socket(gloss_inv.inputs.get("Color"))
            if traced_node is None:
                traced_node = _find_tex_node_for_socket(bsdf.inputs.get("Roughness")) or _find_tex_node_for_socket(bsdf.inputs.get("Coat Roughness"))
        elif label == "Level":
            traced_node = (
                _find_tex_node_for_socket(bsdf.inputs.get("Specular IOR Level"))
                or _find_tex_node_for_socket(bsdf.inputs.get("Coat Weight"))
                or _find_tex_node_for_socket(bsdf.inputs.get("Specular"))
                or _find_tex_node_for_socket(bsdf.inputs.get("Clearcoat"))
            )
        elif label == "Specular":
            traced_node = _find_tex_node_for_socket(bsdf.inputs.get("Specular Tint")) or _find_tex_node_for_socket(bsdf.inputs.get("Coat Tint"))
        elif label == "Normal":
            normal_map = _find_node_by_label_or_name(node_tree, "Normal Map")
            if normal_map is not None:
                traced_node = _find_tex_node_for_socket(normal_map.inputs.get("Color"))
            if traced_node is None:
                traced_node = _find_tex_node_for_socket(bsdf.inputs.get("Normal"))
        elif label == "Diffuse":
            traced_node = _find_tex_node_for_socket(bsdf.inputs.get("Base Color"))
        elif label in ("Mask", "Ambient Map"):
            ao_mix = _find_node_by_label_or_name(node_tree, "Diffuse x AO")
            if ao_mix is not None:
                traced_node = _find_tex_node_for_socket(ao_mix.inputs[1])

        if traced_node is not None and traced_node not in candidate_nodes:
            candidate_nodes.append(traced_node)

    for node in candidate_nodes:
        if node.type == "TEX_IMAGE" and node.image is not None and not is_placeholder_image(node.image):
            path = node.image.filepath or getattr(node.image, "filepath_raw", "") or node.image.name
            if path:
                return bpy.path.abspath(path)
    return ""


def _tint_settings(node_tree: bpy.types.NodeTree):
    tint = node_tree.nodes.get("Faction Tint")
    if tint is None or tint.type != "GROUP":
        return list(DEFAULT_TINT_COLOURS), True
    colours = [tuple(tint.inputs[f"Colour {index}"].default_value)[:4] for index in range(1, 4)]
    return colours, tint.inputs["Faction Colouring"].default_value >= 0.5


def bind_uv2_layer(material: bpy.types.Material, layer_name: str) -> bool:
    # create_total_war_material names the node's layer "UV2", which matches no layer Blender itself
    # ever creates, so the viewport silently falls back to channel 1 while the exporter reads the
    # mesh's real second layer - the preview and the game disagree. Pointing the node at that layer
    # is what makes them agree; the exporter's own fallback behaves the same either way.
    if not layer_name or not material.use_nodes or material.node_tree is None:
        return False
    uv2_node = material.node_tree.nodes.get("UV2")
    if uv2_node is None or uv2_node.type != "UVMAP" or uv2_node.uv_map == layer_name:
        return False
    uv2_node.uv_map = layer_name
    return True


def read_uv2_layer_name(material: bpy.types.Material) -> str:
    # An empty uv_map means the "UV2" node defaults to whichever UV layer is active - i.e. the
    # artist never pointed it at a real second UV layer, so there's no distinct UV2 data to
    # export (see the export-side gap this closes in extraction.extract._convert_mesh).
    if not material.use_nodes or material.node_tree is None:
        return ""
    uv2_node = material.node_tree.nodes.get("UV2")
    return uv2_node.uv_map if uv2_node is not None and uv2_node.type == "UVMAP" else ""


def read_material_def(material: bpy.types.Material) -> MaterialDef:
    shader_type = getattr(material, "tw_shader_type", "default")
    uv2_layer_name = read_uv2_layer_name(material)
    if material.use_nodes and material.node_tree is not None:
        node_tree = material.node_tree
        diffuse_path = _texture_path(node_tree, "Diffuse")
        normal_path = _texture_path(node_tree, "Normal")
        mask_path = _texture_path(node_tree, "Ambient Map") or _texture_path(node_tree, "Mask")
        dirtmap_path = _texture_path(node_tree, "Dirtmap")
        dirtmask_path = _texture_path(node_tree, "Dirtmask")
        gloss_path = _texture_path(node_tree, "Gloss")
        level_path = _texture_path(node_tree, "Level")
        specular_path = _texture_path(node_tree, "Specular")
        tint_mask_paths = tuple(_texture_path(node_tree, f"Tint Mask {index}") for index in range(1, 4))
        decal_paths = tuple(_texture_path(node_tree, slot) for slot in ("Decal Diffuse", "Decal Normal", "Decal Mask"))
        decal_dirtmap_paths = tuple(_texture_path(node_tree, slot) for slot in ("Decal Dirtmap", "Decal Dirtmask"))
        tint_colours, faction_colouring = _tint_settings(node_tree)

        tiling_node = node_tree.nodes.get("Dirtmap Tiling")
        if tiling_node is not None and tiling_node.type == "MAPPING":
            scale = tiling_node.inputs["Scale"].default_value
            dirtmap_tile_u, dirtmap_tile_v = scale[0], scale[1]
        else:
            dirtmap_tile_u = dirtmap_tile_v = DEFAULT_DIRTMAP_TILE

        offset_node = node_tree.nodes.get("Dirt UV Offset")
        if offset_node is not None and offset_node.type == "VECT_MATH":
            offset = offset_node.inputs[1].default_value
            dirt_uv_offset_u, dirt_uv_offset_v = offset[0], offset[1]
        else:
            dirt_uv_offset_u = dirt_uv_offset_v = DIRT_UV_OFFSET
    else:
        diffuse_path = normal_path = mask_path = dirtmap_path = dirtmask_path = ""
        gloss_path = level_path = specular_path = ""
        tint_mask_paths = ("", "", "")
        decal_paths = ("", "", "")
        decal_dirtmap_paths = ("", "")
        tint_colours, faction_colouring = list(DEFAULT_TINT_COLOURS), True
        dirtmap_tile_u = dirtmap_tile_v = DEFAULT_DIRTMAP_TILE
        dirt_uv_offset_u = dirt_uv_offset_v = DIRT_UV_OFFSET

    return MaterialDef(
        name=material.name,
        shader_type=shader_type,
        diffuse_texture_path=diffuse_path,
        normal_texture_path=normal_path,
        mask_texture_path=mask_path,
        dirtmap_texture_path=dirtmap_path,
        dirtmask_texture_path=dirtmask_path,
        gloss_texture_path=gloss_path,
        level_texture_path=level_path,
        specular_texture_path=specular_path,
        tint_mask_texture_paths=tint_mask_paths,
        decal_texture_paths=decal_paths,
        decal_dirtmap_texture_paths=decal_dirtmap_paths,
        tint_colours=tuple(tuple(c[:3]) for c in tint_colours),
        faction_colouring=faction_colouring,
        dirtmap_tile_u=dirtmap_tile_u,
        dirtmap_tile_v=dirtmap_tile_v,
        dirt_uv_offset_u=dirt_uv_offset_u,
        dirt_uv_offset_v=dirt_uv_offset_v,
        alpha_mode=ALPHA_MODE_VALUES[getattr(material, "tw_alpha_mode", DEFAULT_ALPHA_MODE)],
        uv2_layer_name=uv2_layer_name,
    )
