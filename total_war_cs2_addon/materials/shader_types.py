SHADER_TYPES = [
    ("default", "Standard", "Plain opaque surface - the everyday building and prop material"),
    (
        "tiled_dirtmap",
        "Tiled Dirtmap",
        "Standard surface with tiled weathering grime laid over it. Best on seamless pieces that "
        "repeat along a run, fort wall segments above all - the grime tiles at its own scale, so it "
        "carries across the joins instead of repeating with the base texture",
    ),
    (
        "ship_ambientmap",
        "Ship Ambientmap",
        "Standard surface with a baked ambient-occlusion map, read from the mesh's second UV map",
    ),
    (
        "terrain_blend",
        "Terrain Blend",
        "An untextured surface the battlefield ground is projected onto in game, so the mesh takes on "
        "whatever terrain it sits in",
    ),
    ("weighted", "Weighted", "Skinned surface, lit exactly like Standard - armour, cloth, equipment"),
    (
        "weighted_dirtmap",
        "Weighted Dirtmap",
        "Skinned surface with the decal dirtmap overlay blended over it - the grime pass on armour and clothing",
    ),
    (
        "weighted_skin",
        "Weighted Skin",
        "Skinned surface lit as skin rather than cloth - light scatters through it and catches at the edges. For faces, hands and bare limbs",
    ),
    (
        "weighted_skin_dirtmap",
        "Weighted Skin Dirtmap",
        "Bare skin with the decal dirtmap overlay blended over it",
    ),
    (
        "weighted_decal",
        "Weighted Decal",
        "Skinned surface with a projected decal set blended over it - insignia, banners and unit markings",
    ),
    (
        "weighted_decal_dirtmap",
        "Weighted Decal Dirtmap",
        "Skinned surface carrying both the projected decal set and the dirtmap grime pass",
    ),
    (
        "weighted_skin_decal",
        "Weighted Skin Decal",
        "Bare skin with a projected decal set blended over it - tattoos and war paint",
    ),
    (
        "weighted_skin_decal_dirtmap",
        "Weighted Skin Decal Dirtmap",
        "Bare skin carrying both the projected decal set and the dirtmap grime pass",
    ),
    (
        "tree",
        "Tree",
        "Trunk and branch bark, and solid vegetation props like stones. The game sways it in the wind",
    ),
    (
        "tree_leaf",
        "Tree Leaf",
        "Leaf and frond cards, and whole shrubs - the cut-out half of a tree, drawn with its alpha "
        "clipped. The game sways it in the wind",
    ),
]

DEFAULT_SHADER_TYPE = "default"

# Which workflows each shader is offered in. A material datablock is shared - the same one can be
# used from more than one workflow - so this filters what the Materials panel offers, and never
# restricts tw_shader_type itself: importing a building into a scene left in another workflow must
# still be able to set that building's shader.
#
# "default" covers rigid unit parts as well as buildings (a real crest prop,
# raw_data/variantmeshes/VariantModels/man/crests/ridge_crest_tall.CS2, is authored with it). The
# other three are building-only: tiled_dirtmap and terrain_blend are battlefield-surface shaders,
# and ship_ambientmap belongs to the not-yet-implemented ship workflow rather than to units.
SHADER_TYPE_WORKFLOWS = {
    "default": frozenset({"BUILDING", "UNIT"}),
    "tiled_dirtmap": frozenset({"BUILDING"}),
    "ship_ambientmap": frozenset({"BUILDING"}),
    "terrain_blend": frozenset({"BUILDING"}),
    "weighted": frozenset({"UNIT"}),
    "weighted_dirtmap": frozenset({"UNIT"}),
    "weighted_skin": frozenset({"UNIT"}),
    "weighted_skin_dirtmap": frozenset({"UNIT"}),
    "weighted_decal": frozenset({"UNIT"}),
    "weighted_decal_dirtmap": frozenset({"UNIT"}),
    "weighted_skin_decal": frozenset({"UNIT"}),
    "weighted_skin_decal_dirtmap": frozenset({"UNIT"}),
    "tree": frozenset({"VEGETATION"}),
    "tree_leaf": frozenset({"VEGETATION"}),
}

# The two rigid_material names BOB maps onto RS_TREE_V5 and RS_LEAF_V5, from its own
# material-name table (PLAN_vegetation.md 5). They happen to match the add-on's identifiers, and
# this mapping exists so a future exporter does not have to rediscover that.
VEGETATION_SHADER_TYPES = frozenset({"tree", "tree_leaf"})

# ps30_full_skin swaps the whole lighting model, not just a texture blend: mask1/2/3 stop being
# faction tint masks and become rim / subsurface / backscatter strengths, and the specular colour
# map goes unread. Corroborated by the compiled samples - RS_WEIGHTED_SKIN_V5 carries no specular
# texture at all (PLAN_units.md §1.2).
SKIN_SHADER_TYPES = frozenset(
    {"weighted_skin", "weighted_skin_dirtmap", "weighted_skin_decal", "weighted_skin_decal_dirtmap"}
)

# The shader types that read per-vertex bone weights, i.e. the ones a WEIGHTED unit part must use
# and a RIGID_ATTACHMENT one must not.
WEIGHTED_SHADER_TYPES = frozenset(
    {
        "weighted",
        "weighted_dirtmap",
        "weighted_skin",
        "weighted_skin_dirtmap",
        "weighted_decal",
        "weighted_decal_dirtmap",
        "weighted_skin_decal",
        "weighted_skin_decal_dirtmap",
    }
)

# ps_common_blend_dirtmap, reached through b_do_dirt. Distinct from "tiled_dirtmap", which is
# ps30_full_dirtmap's own inline blend against different samplers on a different UV channel.
DECAL_DIRTMAP_SHADER_TYPES = frozenset(
    {
        "weighted_dirtmap",
        "weighted_skin_dirtmap",
        "weighted_decal_dirtmap",
        "weighted_skin_decal_dirtmap",
    }
)

# ps_common_blend_decal, reached through b_do_decal. terrain_blend is deliberately absent:
# ps30_main_custom_terrain calls the same function unconditionally, without consulting the flag.
DECAL_SHADER_TYPES = frozenset(
    {
        "weighted_decal",
        "weighted_decal_dirtmap",
        "weighted_skin_decal",
        "weighted_skin_decal_dirtmap",
    }
)

# ps_common_blend_dirtmap offsets its dirt sample by
# float2(f_uv_offset_u, f_uv_offset_v) * float2(i_random_tile_u, i_random_tile_v), so the
# offset only exists when the random-tile flags are on. Every real decal-dirtmap mesh in the
# sample corpus carries INT_PARAM_RANDOM_TILE_U/V = 1 (PLAN_units.md 1.2), against the
# f_uv_offset default of 0.5 that this add-on writes.
DIRT_UV_OFFSET = 0.5

# alpha_test() in the .fx clips against a fixed 0.5 reference, but only when i_alpha_mode is
# exactly 1 - every other value skips the test entirely. -1 is what every real sample this
# add-on was built against carries, which is why it stays the default.
ALPHA_MODE_ITEMS = [
    ("NONE", "None", "No alpha handling at all - what nearly every building and unit in the game uses"),
    ("OPAQUE", "Opaque", "Explicitly opaque. Looks identical to None in game"),
    (
        "ALPHA_TEST",
        "Alpha Test",
        "Hide pixels where the diffuse texture's alpha is below half - for foliage, grilles, rope and other cut-out surfaces",
    ),
    (
        "BLEND",
        "Blend (unverified)",
        "Genuinely see-through rather than cut out. The game defines it, but no shipped asset uses it and "
        "it has never been tested through a build - expect to have to check the result in game",
    ),
]

# WARSCAPE::IP_ALPHA_MODE in Attila.h: OPAQUE 0, TEST 1, BLEND 2, read into
# MESH_V5_PARAMS::m_param_alpha_mode. BLEND is the only route to real semi-transparency - it is a
# parameter, not a shader or technique, so any of the weighted shaders can carry it.
ALPHA_MODE_VALUES = {"NONE": -1, "OPAQUE": 0, "ALPHA_TEST": 1, "BLEND": 2}
DEFAULT_ALPHA_MODE = "NONE"
ALPHA_TEST_ALPHA_MODE = "ALPHA_TEST"
BLEND_ALPHA_MODE = "BLEND"


def shader_types_for_workflow(workflow: str) -> list[tuple[str, str, str]]:
    return [entry for entry in SHADER_TYPES if workflow in SHADER_TYPE_WORKFLOWS.get(entry[0], frozenset())]

SHADER_TYPE_IDENTIFIERS = [entry[0] for entry in SHADER_TYPES]

SHADER_TYPE_LABELS = {identifier: label for identifier, label, _description in SHADER_TYPES}

# Menu entries take their tooltip from the operator that sets the shader, not from the enum item,
# so TW_OT_set_shader_type reads the per-shader text back out of here.
SHADER_TYPE_DESCRIPTIONS = {identifier: description for identifier, _label, description in SHADER_TYPES}

# The texture each technique samples from TEXCOORD1 (ps30_full_ao's AO map, ps30_full_dirtmap's
# dirtmask). No other technique this add-on writes reads channel 2 at all.
UV2_TEXTURE_SLOT_BY_SHADER_TYPE = {
    "ship_ambientmap": "Ambient Map",
    "tiled_dirtmap": "Dirtmask",
}
