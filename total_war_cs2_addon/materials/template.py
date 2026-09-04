from materials.shader_types import DECAL_DIRTMAP_SHADER_TYPES, DECAL_SHADER_TYPES, ALPHA_MODE_VALUES
from binary.cs2_structures import (
    NodeAttributes,
    NodeAttributeString,
    NodeAttributeFloat,
    NodeAttributeInteger,
    NodeAttributeVec4,
    MaterialTexture,
    MaterialLightProperty,
    DirectXMaterial,
    MaterialNode,
    MATERIAL_TYPE_DIRECTX,
)

TW_MATERIAL_ATTRIBUTES_VERSION = "TW Material Attributes Version 1.6"

_PLACEHOLDER_TEXTURE_SLOTS = [
    ("t_albedo", "test_gray.tga"),
    ("t_normal", "flatnormal.tga"),
    ("t_detail_normal", "flatnormal.tga"),
    ("t_smoothness", "test_gray.tga"),
    ("t_reflectivity", "test_gray.tga"),
    ("t_specular_colour", "test_white.tga"),
    ("t_mask1", "test_black.tga"),
    ("t_mask2", "test_black.tga"),
    ("t_mask3", "test_black.tga"),
    ("t_ambient_occlusion_uv2", "test_white.tga"),
    ("t_environment_map", "test_cubemap.dds"),
    ("AmbiTexture", "test_cubemap_blurry.dds"),
    ("t_displacement", "test_black.tga"),
    ("t_dirtmap_uv2", "test_white.tga"),
    ("t_alpha_mask", "test_white.tga"),
    ("t_decal_diffuse", "test_white.tga"),
    ("t_decal_normal", "flatnormal.tga"),
    ("t_decal_mask", "test_black.tga"),
    ("t_decal_dirtmap", "test_black.tga"),
    ("t_decal_dirtmask", "test_black.tga"),
]

def _float_attribute_template(
    dirtmap_tile_u: float, dirtmap_tile_v: float, uv_offset_u: float, uv_offset_v: float
) -> list[tuple[str, float]]:
    return [
        ("ambient_strength", 1.0),
        ("Smoothness_boost", 0.0),
        ("Reflectivity_boost", 0.0),
        ("Magic_Curve", 60.0),
        ("f_uv2_tile_interval_u", dirtmap_tile_u),
        ("f_uv2_tile_interval_v", dirtmap_tile_v),
        ("f_dirtmap_hardness", 0.0),
        ("f_shadow_strength", 0.75),
        ("f_uv_offset_u", uv_offset_u),
        ("f_uv_offset_v", uv_offset_v),
    ]

_INTEGER_ATTRIBUTE_TEMPLATE = [
    ("b_alpha_off", 1),
    ("b_shadows", 0),
    ("i_alpha_mode", 4294967295),
    ("b_faction_colouring", 1),
    ("i_bone_influences", 2),
    ("i_random_tile_u", 0),
    ("i_random_tile_v", 0),
    ("b_do_dirt", 0),
    ("b_do_decal", 0),
    ("b_light1_omni", 0),
]

_VEC4_ATTRIBUTE_TEMPLATE = [
    ("vec4_colour_0", (0.3921569287776947, 0.2352941483259201, 0.1568627506494522, 1.0)),
    ("vec4_colour_1", (0.2352941483259201, 0.3921569287776947, 0.1568627506494522, 1.0)),
    ("vec4_colour_2", (0.1568627506494522, 0.2352941483259201, 0.3921569287776947, 1.0)),
    ("vec4_uv_rect", (0.0, 0.0, 1.0, 1.0)),
]

# 0-based position of the `technique` block in standard_lighting_assembly_kit.fx: Full_custom_terrain
# is 4, Full_ao is 5 and Full_dirtmap is 6. Confirmed against every real sample - Full_standard (0)
# samples no UV2 at all, so leaving these at 0 silently drops the AO/dirtmap channel. The one real
# terrain_blend sample (bridge_stone_1) carries index 0, but against a different, Rome 2 era .fx
# (standard_lighting_R2_3.fx) whose ordering is its own; this add-on always writes the Attila kit's
# standard_lighting_assembly_kit.fx, so the index has to be the one valid in that file.
_TECHNIQUE_INDEX_BY_RIGID_MATERIAL = {
    # weighted itself is Full_standard, i.e. index 0, so it needs no entry. weighted_dirtmap ->
    # Full_standard_decaldirt (3) and weighted_skin_dirtmap -> Full_skin (7) were both read off real
    # CA-authored .CS2 files; weighted_skin has no sample, but Full_skin is the only skin technique
    # in the file, so 7 is the only candidate (PLAN_units.md §1.2). The four *_decal* variants land
    # on those same two techniques: ps30_main_decaldirt and ps30_full_skin are the only pixel
    # shaders that read b_do_decal at all, and Full_standard's ps30_main_UPDATED has no decal path.
    "weighted_dirtmap": 3,
    "weighted_skin": 7,
    "weighted_skin_dirtmap": 7,
    "weighted_decal": 3,
    "weighted_decal_dirtmap": 3,
    "weighted_skin_decal": 7,
    "weighted_skin_decal_dirtmap": 7,
    "terrain_blend": 4,
    "ship_ambientmap": 5,
    "tiled_dirtmap": 6,
}

_LIGHT_PROPERTIES = [
    MaterialLightProperty("light_position0", 2, -1),
    MaterialLightProperty("light_color0", 0, -1),
]


def shader_fx_path(assembly_kit_root: str) -> str:
    return f"{assembly_kit_root.rstrip(chr(92)).rstrip('/')}\\max_exporter\\max_shader\\standard_lighting_assembly_kit.fx"


def _placeholder_path(assembly_kit_root: str, filename: str) -> str:
    return f"{assembly_kit_root.rstrip(chr(92)).rstrip('/')}\\max_exporter\\max_shader\\{filename}"


def build_directx_material_node(
    node_name: str,
    material_name: str,
    rigid_material: str,
    assembly_kit_root: str,
    diffuse_texture_path: str = "",
    normal_texture_path: str = "",
    mask_texture_path: str = "",
    dirtmap_texture_path: str = "",
    gloss_texture_path: str = "",
    level_texture_path: str = "",
    specular_texture_path: str = "",
    dirtmask_texture_path: str = "",
    tint_mask_texture_paths: tuple[str, str, str] = ("", "", ""),
    decal_texture_paths: tuple[str, str, str] = ("", "", ""),
    decal_dirtmap_texture_paths: tuple[str, str] = ("", ""),
    tint_colours: tuple[tuple[float, float, float], ...] = (),
    faction_colouring: bool = True,
    dirtmap_tile_u: float = 4.0,
    dirtmap_tile_v: float = 4.0,
    dirt_uv_offset_u: float = 0.5,
    dirt_uv_offset_v: float = 0.5,
    alpha_mode: int = ALPHA_MODE_VALUES["NONE"],
) -> MaterialNode:
    overrides = {
        "t_albedo": diffuse_texture_path,
        "t_normal": normal_texture_path,
        "t_smoothness": gloss_texture_path,
        "t_reflectivity": level_texture_path,
        "t_specular_colour": specular_texture_path,
        "t_ambient_occlusion_uv2": mask_texture_path,
        "t_dirtmap_uv2": dirtmap_texture_path,
        "t_alpha_mask": dirtmask_texture_path,
        "t_mask1": tint_mask_texture_paths[0],
        "t_mask2": tint_mask_texture_paths[1],
        "t_mask3": tint_mask_texture_paths[2],
        "t_decal_diffuse": decal_texture_paths[0],
        "t_decal_normal": decal_texture_paths[1],
        "t_decal_mask": decal_texture_paths[2],
        "t_decal_dirtmap": decal_dirtmap_texture_paths[0],
        "t_decal_dirtmask": decal_dirtmap_texture_paths[1],
    }

    textures = []
    for slot_name, _ in _PLACEHOLDER_TEXTURE_SLOTS:
        path = overrides.get(slot_name, "")
        textures.append(MaterialTexture(texture_name=slot_name, texture_path=path))

    float_attributes = [
        NodeAttributeFloat(name, value)
        for name, value in _float_attribute_template(
            dirtmap_tile_u, dirtmap_tile_v, dirt_uv_offset_u, dirt_uv_offset_v
        )
    ]
    do_dirt = 1 if (
        dirtmap_texture_path
        or dirtmask_texture_path
        or any(decal_dirtmap_texture_paths)
        or "dirtmap" in rigid_material.lower()
    ) else 0
    # The random-tile flags are what switch f_uv_offset_* on inside ps_common_blend_dirtmap.
    # Only the decal-dirtmap shaders reach that function; ps30_full_dirtmap, which tiled_dirtmap
    # compiles to, ignores both, so buildings keep writing 0.
    random_tile = 1 if rigid_material.lower() in DECAL_DIRTMAP_SHADER_TYPES else 0
    integer_overrides = {
        "b_do_dirt": do_dirt,
        "b_do_decal": 1 if rigid_material.lower() in DECAL_SHADER_TYPES else 0,
        "b_faction_colouring": 1 if faction_colouring else 0,
        "i_random_tile_u": random_tile,
        "i_random_tile_v": random_tile,
        # NodeAttributeInteger is written as a uint32, so a negative mode goes out as its
        # two's complement - which is exactly the 4294967295 real -1 samples carry.
        "i_alpha_mode": alpha_mode & 0xFFFFFFFF,
    }
    integer_attributes = [
        NodeAttributeInteger(name, integer_overrides.get(name, value))
        for name, value in _INTEGER_ATTRIBUTE_TEMPLATE
    ]

    # The shader runs vec4_colour_N through _linear(), so the CS2 stores the gamma-space swatch
    # while a Blender colour socket holds the linear one.
    vec4_overrides = {
        f"vec4_colour_{index}": tuple(max(c, 0.0) ** (1.0 / 2.2) for c in colour) + (1.0,)
        for index, colour in enumerate(tint_colours)
    }
    vec4_attributes = [
        NodeAttributeVec4(name, vec4_overrides.get(name, value)) for name, value in _VEC4_ATTRIBUTE_TEMPLATE
    ]

    directx_material = DirectXMaterial(
        shader_fx_path=shader_fx_path(assembly_kit_root),
        shader_technique_index=_TECHNIQUE_INDEX_BY_RIGID_MATERIAL.get(rigid_material, 0),
        textures=textures,
        light_properties=list(_LIGHT_PROPERTIES),
        float_attributes=float_attributes,
        integer_attributes=integer_attributes,
        shader_pass_index=0,
        vec4_attributes=vec4_attributes,
        shader_flags=0,
    )

    material_attributes = NodeAttributes(
        strings=[
            NodeAttributeString("TWMatAtt_Version", TW_MATERIAL_ATTRIBUTES_VERSION),
            NodeAttributeString("rigid_material", rigid_material),
        ]
    )

    return MaterialNode(
        material_type=MATERIAL_TYPE_DIRECTX,
        node_name=node_name,
        material_name=material_name,
        material_attributes=material_attributes,
        default_material=None,
        directx_material=directx_material,
    )
