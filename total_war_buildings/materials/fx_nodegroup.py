import math
from dataclasses import dataclass

import bpy
import mathutils

from materials.environment import ENVIRONMENT_MIP_LADDER, ensure_environment_images, image_name
from props.properties import get_assembly_kit_root_or_empty

FX_NODE_GROUP_NAME = "TW Full_standard"
SKIN_NODE_GROUP_NAME = "TW Full_skin"
TINT_NODE_GROUP_NAME = "TW Faction Tint"
DIRTMAP_NODE_GROUP_NAME = "TW Dirtmap Blend"
DECAL_DIRTMAP_NODE_GROUP_NAME = "TW Decal Dirtmap Blend"

SUN_ANGULAR_RADIUS = math.radians(0.5)
DIFFUSE_SCALE_FACTOR = 0.004
HDR_LIGHTING_MULTIPLIER = 5000.0
MAX_FRACTION_OF_FACETS = 0.9999
TONE_MAP_BLACK = 0.001
TONE_MAP_WHITE = 10.0
REAL_APPROX_ZERO = 0.001
ERF_A = (8.0 * (math.pi - 3.0)) / (3.0 * math.pi * (4.0 - math.pi))
SQRT_2 = math.sqrt(2.0)

# light_position0 default in standard_lighting_assembly_kit.fx, used here as a direction: the
# technique only ever feeds it to standard_lighting_model_directional_light_UPDATED.
_SUN_LENGTH = math.sqrt(0.5 * 0.5 + 2.0 * 2.0 + 1.25 * 1.25)
DEFAULT_SUN_DIRECTION = (-0.5 / _SUN_LENGTH, 2.0 / _SUN_LENGTH, 1.25 / _SUN_LENGTH)

# vec4_colour_0/1/2 defaults are gamma-space values and the shader runs them through _linear();
# a Blender colour socket already holds linear, so pre-converting keeps the swatch itself identical.
DEFAULT_TINT_COLOURS = (
    (0.5**2.2, 0.1**2.2, 0.1**2.2, 1.0),
    (0.3**2.2, 0.6**2.2, 0.5**2.2, 1.0),
    (0.5**2.2, 0.2**2.2, 0.1**2.2, 1.0),
)

DEFAULT_LIGHT_POSITION = (-0.5, 2.0, 1.25)

_VECTOR_MATH_SCALAR_OPS = {"DOT_PRODUCT", "LENGTH", "DISTANCE"}


class _Builder:
    def __init__(self, tree: bpy.types.NodeTree, columns: int = 14):
        self.tree = tree
        self.columns = columns
        self._placed = 0

    def place(self, node: bpy.types.Node) -> bpy.types.Node:
        column, row = divmod(self._placed, self.columns)
        node.location = (column * 240, -row * 175)
        self._placed += 1
        return node

    def _feed(self, node: bpy.types.Node, index: int, value) -> None:
        if value is None:
            return
        if isinstance(value, bpy.types.NodeSocket):
            self.tree.links.new(value, node.inputs[index])
        else:
            node.inputs[index].default_value = value

    def math(self, operation: str, a=None, b=None, c=None, label: str = "", clamp: bool = False):
        node = self.place(self.tree.nodes.new("ShaderNodeMath"))
        node.operation = operation
        node.use_clamp = clamp
        node.label = label
        for index, value in enumerate((a, b, c)):
            self._feed(node, index, value)
        return node.outputs[0]

    def vmath(self, operation: str, a=None, b=None, c=None, label: str = ""):
        node = self.place(self.tree.nodes.new("ShaderNodeVectorMath"))
        node.operation = operation
        node.label = label
        for index, value in enumerate((a, b, c)):
            self._feed(node, index, value)
        return node.outputs["Value" if operation in _VECTOR_MATH_SCALAR_OPS else "Vector"]

    def scale(self, vector, factor, label: str = ""):
        # ShaderNodeVectorMath SCALE takes its scalar on input 3, not input 1.
        node = self.place(self.tree.nodes.new("ShaderNodeVectorMath"))
        node.operation = "SCALE"
        node.label = label
        self._feed(node, 0, vector)
        self._feed(node, 3, factor)
        return node.outputs["Vector"]

    def combine_xyz(self, x, y, z):
        node = self.place(self.tree.nodes.new("ShaderNodeCombineXYZ"))
        for index, value in enumerate((x, y, z)):
            self._feed(node, index, value)
        return node.outputs["Vector"]

    def combine_colour(self, r, g, b):
        node = self.place(self.tree.nodes.new("ShaderNodeCombineColor"))
        node.mode = "RGB"
        for index, value in enumerate((r, g, b)):
            self._feed(node, index, value)
        return node.outputs["Color"]

    def lerp(self, a, b, factor, label: str = ""):
        return self.math("MULTIPLY_ADD", self.math("SUBTRACT", b, a), factor, a, label=label)

    def vlerp(self, a, b, factor, label: str = ""):
        return self.vmath("MULTIPLY_ADD", self.vmath("SUBTRACT", b, a), factor, a, label=label)


def _vector_node(b: _Builder, name: str, value):
    node = b.place(b.tree.nodes.new("ShaderNodeCombineXYZ"))
    node.name = node.label = name
    for index, component in enumerate(value):
        node.inputs[index].default_value = component
    return node.outputs["Vector"]


def _value_node(b: _Builder, name: str, value: float):
    node = b.place(b.tree.nodes.new("ShaderNodeValue"))
    node.name = node.label = name
    node.outputs[0].default_value = value
    return node.outputs[0]


def _env_swizzle(b: _Builder, vector, label: str):
    # texcoordEnvSwizzle: -float3(ref.x, -ref.z, ref.y), i.e. (-x, z, -y).
    separate = b.place(b.tree.nodes.new("ShaderNodeSeparateXYZ"))
    separate.label = label
    b.tree.links.new(vector, separate.inputs["Vector"])
    return b.combine_xyz(
        b.math("MULTIPLY", separate.outputs["X"], -1.0),
        separate.outputs["Z"],
        b.math("MULTIPLY", separate.outputs["Y"], -1.0),
    )


def _environment_texture(b: _Builder, name: str, vector, image):
    node = b.place(b.tree.nodes.new("ShaderNodeTexEnvironment"))
    node.name = node.label = name
    node.image = image
    b.tree.links.new(vector, node.inputs["Vector"])
    return node.outputs["Color"]


@dataclass
class _SceneLighting:
    normal: object
    view_dir: object
    negated_view_dir: object
    light_vec: object
    light_colour: object
    ambient_tint: object
    environment_tint: object
    low_bias: object
    high_bias: object


def _scene_lighting(b: _Builder, normal_input) -> _SceneLighting:
    # Scene state, not material state, so it lives inside the group rather than on its input
    # sockets: every material instances one node tree, so setting it here sets it for all of them.
    # sync_light() writes these back by node name, so the names are part of the contract.
    group = b.tree
    geometry = b.place(group.nodes.new("ShaderNodeNewGeometry"))
    light_position = _vector_node(b, "Light Position", DEFAULT_LIGHT_POSITION)
    sun_direction = _vector_node(b, "Sun Direction", DEFAULT_SUN_DIRECTION)
    light_colour_node = b.place(group.nodes.new("ShaderNodeRGB"))
    light_colour_node.name = light_colour_node.label = "Light Colour"
    light_colour_node.outputs[0].default_value = (1.0, 1.0, 1.0, 1.0)
    point_light = _value_node(b, "Point Light", 0.0)
    ambient_colour = b.place(group.nodes.new("ShaderNodeRGB"))
    ambient_colour.name = ambient_colour.label = "Ambient Colour"
    ambient_colour.outputs[0].default_value = (1.0, 1.0, 1.0, 1.0)
    environment_colour = b.place(group.nodes.new("ShaderNodeRGB"))
    environment_colour.name = environment_colour.label = "Environment Colour"
    environment_colour.outputs[0].default_value = (1.0, 1.0, 1.0, 1.0)
    low_bias = _value_node(b, "Low Tones Bias", 0.33)
    high_bias = _value_node(b, "High Tones Bias", 0.66)

    normal = b.vmath("NORMALIZE", normal_input)
    view_dir = b.vmath("NORMALIZE", geometry.outputs["Incoming"], label="surface -> camera")

    # Both pixel shaders derive their light vector per pixel from a light *position*:
    # normalize(light_position0.xyz - input.Wpos). A Blender Sun lamp has no meaningful position,
    # so Point Light selects between that and a plain direction.
    to_point_light = b.vmath(
        "NORMALIZE",
        b.vmath("SUBTRACT", light_position, geometry.outputs["Position"]),
        label="surface -> point light",
    )
    to_sun = b.vmath("NORMALIZE", sun_direction, label="surface -> sun")
    light_vec = b.vmath(
        "NORMALIZE", b.vlerp(to_sun, to_point_light, point_light), label="light_vector"
    )
    negated_view_dir = b.vmath(
        "MULTIPLY", view_dir, (-1.0, -1.0, -1.0), label="camera -> surface"
    )
    light_colour = b.vmath(
        "MULTIPLY", light_colour_node.outputs[0], (HDR_LIGHTING_MULTIPLIER,) * 3, label="hdr light"
    )
    return _SceneLighting(
        normal=normal,
        view_dir=view_dir,
        negated_view_dir=negated_view_dir,
        light_vec=light_vec,
        light_colour=light_colour,
        ambient_tint=ambient_colour.outputs[0],
        environment_tint=environment_colour.outputs[0],
        low_bias=low_bias,
        high_bias=high_bias,
    )


def _cube_ambient(b: _Builder, name: str, vector, tint, label: str):
    images = ensure_environment_images(get_assembly_kit_root_or_empty())
    return b.vmath(
        "MULTIPLY",
        _environment_texture(b, name, _env_swizzle(b, vector, f"texcoordEnvSwizzle({label})"), images[image_name("Ambient")]),
        tint,
        label="cube_ambient",
    )


def _erf(b: _Builder, x):
    x_squared = b.math("MULTIPLY", x, x)
    a_times_x_squared = b.math("MULTIPLY", x_squared, ERF_A)
    numerator = b.math("ADD", a_times_x_squared, 4.0 / math.pi)
    denominator = b.math("ADD", a_times_x_squared, 1.0)
    main_term = b.math(
        "MULTIPLY", b.math("DIVIDE", numerator, denominator), b.math("MULTIPLY", x_squared, -1.0)
    )
    magnitude = b.math("SQRT", b.math("SUBTRACT", 1.0, b.math("EXPONENT", main_term)))
    return b.math("MULTIPLY", magnitude, b.math("SIGN", x), label="erf")


def _erfinv(b: _Builder, x):
    one_over_a = 1.0 / ERF_A
    log_1_minus_x_squared = b.math(
        "LOGARITHM", b.math("SUBTRACT", 1.0, b.math("MULTIPLY", x, x)), math.e
    )
    root_of_first_term = b.math(
        "MULTIPLY_ADD", log_1_minus_x_squared, 0.5, (2.0 / math.pi) * one_over_a
    )
    first_term = b.math("MULTIPLY", root_of_first_term, root_of_first_term)
    second_term = b.math("MULTIPLY", log_1_minus_x_squared, one_over_a)
    inner = b.math("SQRT", b.math("SUBTRACT", first_term, second_term))
    return b.math("SQRT", b.math("SUBTRACT", inner, root_of_first_term), label="erfinv")


def _determine_fraction_of_facets(b: _Builder, smoothness, angle):
    smoothness_squared = b.math("MULTIPLY", smoothness, smoothness)
    fraction = b.math(
        "MULTIPLY_ADD",
        smoothness_squared,
        MAX_FRACTION_OF_FACETS - DIFFUSE_SCALE_FACTOR,
        DIFFUSE_SCALE_FACTOR,
        label="fraction_of_facets",
    )
    sigma = b.math(
        "MAXIMUM",
        b.math("DIVIDE", SUN_ANGULAR_RADIUS, b.math("MULTIPLY", _erfinv(b, fraction), SQRT_2)),
        0.0001,
        label="sigma",
    )
    scale = b.math("DIVIDE", 1.0, b.math("MULTIPLY", sigma, SQRT_2))
    upper = _erf(b, b.math("MULTIPLY", b.math("ADD", angle, SUN_ANGULAR_RADIUS), scale))
    lower = _erf(b, b.math("MULTIPLY", b.math("SUBTRACT", angle, SUN_ANGULAR_RADIUS), scale))
    return b.math("MULTIPLY", b.math("SUBTRACT", upper, lower), 0.5, label="proportion_of_facets")


def _determine_surface_reflectivity(b: _Builder, reflectivity, roughness, light_vec, negated_view_dir):
    val1 = b.math("MAXIMUM", b.vmath("DOT_PRODUCT", light_vec, negated_view_dir), 0.0)
    val2 = b.math("POWER", val1, 10.0)
    smoothness_val = b.math(
        "SQRT", b.math("COSINE", b.math("MULTIPLY", roughness, 0.98 * math.pi * 0.5))
    )
    boosted = b.math("MULTIPLY", reflectivity, 60.0, clamp=True)
    return b.lerp(
        reflectivity, boosted, b.math("MULTIPLY", val2, smoothness_val), label="surface_reflectivity"
    )


def _tone_map(b: _Builder, hdr, low_bias, high_bias):
    cie_x = b.vmath("DOT_PRODUCT", hdr, (0.4124, 0.3576, 0.1805))
    cie_y = b.vmath("DOT_PRODUCT", hdr, (0.2126, 0.7152, 0.0722))
    cie_z = b.vmath("DOT_PRODUCT", hdr, (0.0193, 0.1192, 0.9505))

    denominator = b.math(
        "MAXIMUM", b.math("ADD", b.math("ADD", cie_x, cie_y), cie_z), REAL_APPROX_ZERO
    )
    x = b.math("DIVIDE", cie_x, denominator)
    y = b.math("DIVIDE", cie_y, denominator)

    log_y_black = math.log10(TONE_MAP_BLACK)
    display_range = math.log10(TONE_MAP_WHITE) - log_y_black
    log_y = b.math(
        "MAXIMUM",
        b.math("LOGARITHM", b.math("MAXIMUM", cie_y, REAL_APPROX_ZERO), 10.0),
        log_y_black,
    )
    t = b.math("DIVIDE", b.math("SUBTRACT", log_y, log_y_black), display_range)

    t_squared = b.math("MULTIPLY", t, t)
    t_cubed = b.math("MULTIPLY", t_squared, t)
    cubic = b.math("MULTIPLY_ADD", low_bias, 3.0, b.math("MULTIPLY_ADD", high_bias, -3.0, 1.0))
    quadratic = b.math("MULTIPLY_ADD", low_bias, -6.0, b.math("MULTIPLY", high_bias, 3.0))
    linear = b.math("MULTIPLY", t, b.math("MULTIPLY", low_bias, 3.0))
    scurve = b.math(
        "MULTIPLY_ADD",
        t_cubed,
        cubic,
        b.math("MULTIPLY_ADD", t_squared, quadratic, linear),
        label="scurve",
    )

    biased_log_y = b.math("MULTIPLY_ADD", scurve, display_range, log_y_black)
    ldr_y = b.math(
        "DIVIDE",
        b.math("SUBTRACT", b.math("POWER", 10.0, biased_log_y), TONE_MAP_BLACK),
        TONE_MAP_WHITE - TONE_MAP_BLACK,
        label="ldr_y",
    )

    ratio = b.math("DIVIDE", ldr_y, b.math("MAXIMUM", y, REAL_APPROX_ZERO))
    cie_xyz = b.combine_xyz(
        b.math("MULTIPLY", x, ratio),
        ldr_y,
        b.math("MULTIPLY", b.math("SUBTRACT", b.math("SUBTRACT", 1.0, x), y), ratio),
    )

    rows = ((3.2405, -1.5372, -0.4985), (-0.9693, 1.8760, 0.0416), (0.0556, -0.2040, 1.0572))
    channels = [
        b.math("MAXIMUM", b.vmath("DOT_PRODUCT", cie_xyz, row), 0.0, clamp=True) for row in rows
    ]
    return b.combine_colour(*channels)


FX_GROUP_VERSION = 5
_VERSION_KEY = "tw_fx_group_version"


def _new_group(name: str) -> bpy.types.NodeTree:
    # Rebuilt in place rather than removed and recreated: every material already using this group
    # holds a pointer to the datablock, and removing it would blank their group nodes.
    group = bpy.data.node_groups.get(name)
    if group is None:
        return bpy.data.node_groups.new(name, "ShaderNodeTree")
    group.nodes.clear()
    group.interface.clear()
    return group


def _add_socket(group: bpy.types.NodeTree, name: str, socket_type: str, default=None, **kwargs):
    socket = group.interface.new_socket(name=name, in_out="INPUT", socket_type=socket_type)
    if default is not None:
        socket.default_value = default
    for key, value in kwargs.items():
        setattr(socket, key, value)
    return socket


def build_faction_tint_group() -> bpy.types.NodeTree:
    group = _new_group(TINT_NODE_GROUP_NAME)
    _add_socket(group, "Diffuse", "NodeSocketColor", (0.8, 0.8, 0.8, 1.0))
    for index in range(3):
        _add_socket(group, f"Mask {index + 1}", "NodeSocketFloat", 0.0, min_value=0.0, max_value=1.0)
        _add_socket(group, f"Colour {index + 1}", "NodeSocketColor", DEFAULT_TINT_COLOURS[index])
    _add_socket(group, "Faction Colouring", "NodeSocketFloat", 1.0, min_value=0.0, max_value=1.0)
    group.interface.new_socket(name="Diffuse", in_out="OUTPUT", socket_type="NodeSocketColor")

    b = _Builder(group, columns=8)
    group_input = b.place(group.nodes.new("NodeGroupInput"))
    group_output = b.place(group.nodes.new("NodeGroupOutput"))
    inputs = group_input.outputs
    faction = inputs["Faction Colouring"]

    diffuse = inputs["Diffuse"]
    for index in range(3):
        colour = inputs[f"Colour {index + 1}"]
        luminance = b.math(
            "MAXIMUM", b.vmath("DOT_PRODUCT", colour, (0.299, 0.587, 0.114)), 0.0, clamp=True
        )
        adjusted = b.vmath(
            "MULTIPLY", colour, b.math("MULTIPLY_ADD", luminance, -1.0, 1.5), label="faction colour"
        )
        tint = b.vlerp(colour, adjusted, faction)
        diffuse = b.vlerp(
            diffuse,
            b.vmath("MULTIPLY", diffuse, tint),
            inputs[f"Mask {index + 1}"],
            label=f"tint {index + 1}",
        )

    group.links.new(diffuse, group_output.inputs["Diffuse"])
    group[_VERSION_KEY] = FX_GROUP_VERSION
    return group


def build_dirtmap_blend_group() -> bpy.types.NodeTree:
    group = _new_group(DIRTMAP_NODE_GROUP_NAME)
    _add_socket(group, "Diffuse", "NodeSocketColor", (0.8, 0.8, 0.8, 1.0))
    _add_socket(group, "Specular", "NodeSocketColor", (1.0, 1.0, 1.0, 1.0))
    _add_socket(group, "Dirtmap", "NodeSocketColor", (1.0, 1.0, 1.0, 1.0))
    _add_socket(group, "Dirtmap Alpha", "NodeSocketFloat", 1.0, min_value=0.0, max_value=1.0)
    _add_socket(group, "Dirtmask", "NodeSocketFloat", 1.0, min_value=0.0, max_value=1.0)
    group.interface.new_socket(name="Diffuse", in_out="OUTPUT", socket_type="NodeSocketColor")
    group.interface.new_socket(name="Specular", in_out="OUTPUT", socket_type="NodeSocketColor")

    b = _Builder(group, columns=6)
    group_input = b.place(group.nodes.new("NodeGroupInput"))
    group_output = b.place(group.nodes.new("NodeGroupOutput"))
    inputs = group_input.outputs
    dirtmap = inputs["Dirtmap"]
    dirtmask = inputs["Dirtmask"]

    # ps30_full_dirtmap fixes hardness at 1.0, which collapses its contrast step to a plain saturate.
    blend_2 = b.math(
        "MULTIPLY",
        b.math("MULTIPLY_ADD", b.math("SUBTRACT", inputs["Dirtmap Alpha"], 1.0), dirtmask, 1.0),
        dirtmask,
        label="blend_amount",
        clamp=True,
    )
    tint = b.vlerp(dirtmap, (1.0, 1.0, 1.0), blend_2, label="lerp(dirtmap, white, blend_amount)")
    group.links.new(b.vmath("MULTIPLY", inputs["Diffuse"], tint), group_output.inputs["Diffuse"])
    group.links.new(b.vmath("MULTIPLY", inputs["Specular"], tint), group_output.inputs["Specular"])
    group[_VERSION_KEY] = FX_GROUP_VERSION
    return group


def build_full_standard_group() -> bpy.types.NodeTree:
    group = _new_group(FX_NODE_GROUP_NAME)
    _add_socket(group, "Diffuse Colour", "NodeSocketColor", (0.8, 0.8, 0.8, 1.0))
    _add_socket(group, "Specular Colour", "NodeSocketColor", (1.0, 1.0, 1.0, 1.0))
    _add_socket(group, "Smoothness", "NodeSocketFloat", 0.5, min_value=0.0, max_value=1.0)
    _add_socket(group, "Reflectivity", "NodeSocketFloat", 0.5, min_value=0.0, max_value=1.0)
    _add_socket(group, "Normal", "NodeSocketVector", (0.0, 0.0, 1.0))
    group.interface.new_socket(name="Colour", in_out="OUTPUT", socket_type="NodeSocketColor")

    b = _Builder(group)
    group_input = b.place(group.nodes.new("NodeGroupInput"))
    group_output = b.place(group.nodes.new("NodeGroupOutput"))
    inputs = group_input.outputs

    diffuse = inputs["Diffuse Colour"]
    specular = inputs["Specular Colour"]
    smoothness = inputs["Smoothness"]
    reflectivity = inputs["Reflectivity"]

    # The group's remaining inputs are exactly the fields of the shader's own
    # StandardLightingModelMaterial_UPDATED struct.
    scene = _scene_lighting(b, inputs["Normal"])
    normal = scene.normal
    light_vec = scene.light_vec
    negated_view_dir = scene.negated_view_dir
    light_colour = scene.light_colour
    low_bias, high_bias = scene.low_bias, scene.high_bias

    roughness = b.math("SUBTRACT", 1.0, smoothness)

    normal_dot_light = b.vmath("DOT_PRODUCT", normal, light_vec)
    clamped_normal_dot_light = b.math("MAXIMUM", normal_dot_light, 0.0)
    reflected_view_vec = b.vmath("REFLECT", negated_view_dir, normal)

    # cube_ambient(N) and get_environment_colour_UPDATED(R, roughness * (texture_num_lods - 1)).
    # The Ambient/Environment Colour nodes above are tints over the sampled cubemap, white by default.
    images = ensure_environment_images(get_assembly_kit_root_or_empty())
    ambient = _cube_ambient(b, "Ambient Cubemap", normal, scene.ambient_tint, "N")

    reflection_vector = _env_swizzle(b, reflected_view_vec, "texcoordEnvSwizzle(R)")
    env_map_lod = b.math("MULTIPLY", roughness, float(ENVIRONMENT_MIP_LADDER[-1]), label="env_map_lod")
    samples = [
        _environment_texture(b, f"Environment Cubemap lod{mip}", reflection_vector, images[image_name("Reflection", mip)])
        for mip in ENVIRONMENT_MIP_LADDER
    ]
    blended = samples[0]
    for index in range(1, len(ENVIRONMENT_MIP_LADDER)):
        lower, upper = ENVIRONMENT_MIP_LADDER[index - 1], ENVIRONMENT_MIP_LADDER[index]
        factor = b.math(
            "DIVIDE", b.math("SUBTRACT", env_map_lod, float(lower)), float(upper - lower), clamp=True
        )
        blended = b.vlerp(blended, samples[index], factor, label=f"lod {lower} -> {upper}")
    environment = b.vmath("MULTIPLY", blended, scene.environment_tint, label="environment_colour")

    angle = b.math(
        "ARCCOSINE",
        b.math(
            "MAXIMUM",
            b.math("MINIMUM", b.vmath("DOT_PRODUCT", light_vec, reflected_view_vec), 1.0),
            -1.0,
        ),
    )
    facet_visibility = b.lerp(
        1.0,
        clamped_normal_dot_light,
        b.math("SINE", b.math("MULTIPLY", roughness, math.pi * 0.5)),
        label="facet_visibility",
    )
    dlight_reflectivity = b.math(
        "MULTIPLY",
        b.math(
            "MULTIPLY",
            b.math("MULTIPLY", _determine_fraction_of_facets(b, smoothness, angle), facet_visibility),
            _determine_surface_reflectivity(b, reflectivity, roughness, light_vec, negated_view_dir),
        ),
        b.math("GREATER_THAN", normal_dot_light, 0.0),
        label="dlight_pixel_reflectivity",
    )

    dlight_specular = b.vmath(
        "MULTIPLY",
        b.vmath("MULTIPLY", specular, light_colour),
        dlight_reflectivity,
        label="dlight_specular_colour",
    )
    scattering = b.math("SUBTRACT", 1.0, b.math("MAXIMUM", dlight_reflectivity, reflectivity))
    dlight_diffuse = b.vmath(
        "MULTIPLY",
        b.vmath("MULTIPLY", diffuse, light_colour),
        b.math(
            "MULTIPLY",
            b.math("MULTIPLY", clamped_normal_dot_light, scattering),
            DIFFUSE_SCALE_FACTOR,
        ),
        label="dlight_diffuse",
    )

    env_reflectivity = b.math(
        "MAXIMUM",
        reflectivity,
        _determine_surface_reflectivity(
            b, reflectivity, roughness, reflected_view_vec, negated_view_dir
        ),
        label="env_light_pixel_reflectivity",
    )
    env_specular = b.vmath(
        "MULTIPLY",
        b.vmath("MULTIPLY", environment, specular),
        env_reflectivity,
        label="env_light_specular_colour",
    )
    env_diffuse = b.vmath(
        "MULTIPLY",
        b.vmath("MULTIPLY", ambient, diffuse),
        b.math("SUBTRACT", 1.0, reflectivity),
        label="env_light_diffuse",
    )

    hdr = b.vmath(
        "ADD",
        b.vmath("ADD", env_diffuse, env_specular),
        b.vmath("ADD", dlight_specular, dlight_diffuse),
        label="hdr_linear_col",
    )
    tone_mapped = _tone_map(b, hdr, low_bias, high_bias)
    group.links.new(tone_mapped, group_output.inputs["Colour"])
    group[_VERSION_KEY] = FX_GROUP_VERSION
    return group


SKIN_SHADING_COLOUR_1 = (0.612066, 0.456263, 0.05)
SKIN_SHADING_COLOUR_2 = (0.32, 0.05, 0.006)
SKIN_DIFFUSE_SCALER = 0.9
SKIN_SPECULAR_SCALER = 2.0
SKIN_RIM_SCALER = 1.0
SKIN_BACKSCATTER_TINT = (0.7, 0.0, 0.0)
SKIN_RIM_BRIGHTNESS = 1.5
DIRT_COLOUR = (0.03, 0.03, 0.02)


def _saturate(b: _Builder, vector, label: str = ""):
    return b.vmath("MINIMUM", b.vmath("MAXIMUM", vector, (0.0, 0.0, 0.0)), (1.0, 1.0, 1.0), label=label)


def _skin_shading(b: _Builder, normal, to_light, sub_surface):
    normal_dot_light = b.vmath("DOT_PRODUCT", normal, to_light, label="ndotl")
    diff1 = b.math(
        "MULTIPLY",
        normal_dot_light,
        b.math("DIVIDE", b.math("MULTIPLY_ADD", normal_dot_light, 0.8, 0.3), 1.44, clamp=True),
        label="diff1",
    )
    diff2 = b.vmath(
        "MULTIPLY",
        b.scale(SKIN_SHADING_COLOUR_1,
            b.math("DIVIDE", b.math("MULTIPLY_ADD", normal_dot_light, 0.9, 0.5), 1.44, clamp=True),
        ),
        b.math("SUBTRACT", 1.0, b.math("ADD", diff1, 0.3), clamp=True),
        label="diff2",
    )
    diff3 = b.vmath(
        "MULTIPLY",
        b.scale(SKIN_SHADING_COLOUR_2,
            b.math("DIVIDE", b.math("MULTIPLY_ADD", normal_dot_light, 0.3, 0.3), 2.25, clamp=True),
        ),
        b.vmath(
            "MULTIPLY",
            b.scale((1.0, 1.0, 1.0), b.math("SUBTRACT", 1.0, diff1)),
            b.vmath("SUBTRACT", (1.0, 1.0, 1.0), diff2),
        ),
        label="diff3",
    )
    mixed = b.vmath("ADD", b.vmath("ADD", b.scale((1.0, 1.0, 1.0), diff1), diff2), diff3, label="mix")
    blended = b.vlerp(
        b.scale((1.0, 1.0, 1.0), normal_dot_light), mixed, sub_surface, label="blendedDiff"
    )
    return _saturate(b, blended, "skin_shading")


def build_full_skin_group() -> bpy.types.NodeTree:
    group = _new_group(SKIN_NODE_GROUP_NAME)
    _add_socket(group, "Diffuse Colour", "NodeSocketColor", (0.8, 0.8, 0.8, 1.0))
    _add_socket(group, "Gloss", "NodeSocketFloat", 0.5, min_value=0.0, max_value=1.0)
    _add_socket(group, "Specular Level", "NodeSocketFloat", 0.5, min_value=0.0, max_value=1.0)
    _add_socket(group, "Rim Mask", "NodeSocketFloat", 0.0, min_value=0.0, max_value=1.0)
    _add_socket(group, "Sub Surface Strength", "NodeSocketFloat", 0.0, min_value=0.0, max_value=1.0)
    _add_socket(group, "Back Scatter Strength", "NodeSocketFloat", 0.0, min_value=0.0, max_value=1.0)
    _add_socket(group, "Normal", "NodeSocketVector", (0.0, 0.0, 1.0))
    group.interface.new_socket(name="Colour", in_out="OUTPUT", socket_type="NodeSocketColor")

    b = _Builder(group)
    group_input = b.place(group.nodes.new("NodeGroupInput"))
    group_output = b.place(group.nodes.new("NodeGroupOutput"))
    inputs = group_input.outputs

    diffuse = inputs["Diffuse Colour"]
    gloss = inputs["Gloss"]
    specular_level = inputs["Specular Level"]
    rim_mask = inputs["Rim Mask"]
    sub_surface = inputs["Sub Surface Strength"]
    back_scatter = inputs["Back Scatter Strength"]

    scene = _scene_lighting(b, inputs["Normal"])
    normal = scene.normal
    to_light = scene.light_vec
    light_colour = scene.light_colour
    from_light = b.vmath("MULTIPLY", to_light, (-1.0, -1.0, -1.0), label="normalised_light_dir")

    skin = _skin_shading(b, normal, to_light, sub_surface)
    dlight_diffuse = b.scale(b.vmath("MULTIPLY", b.vmath("MULTIPLY", diffuse, skin), light_colour),
        DIFFUSE_SCALE_FACTOR * SKIN_DIFFUSE_SCALER,
        label="dlight_diffuse",
    )

    backscatter = b.math(
        "MULTIPLY",
        b.math(
            "MULTIPLY",
            b.math("POWER", b.math("MAXIMUM", b.vmath("DOT_PRODUCT", normal, from_light), 0.0), 2.0),
            b.math("POWER", b.math("MAXIMUM", b.vmath("DOT_PRODUCT", scene.negated_view_dir, to_light), 0.0), 4.0),
        ),
        back_scatter,
        label="backscatter",
    )
    backscatter_colour = b.scale(b.vlerp(light_colour, b.vmath("MULTIPLY", light_colour, SKIN_BACKSCATTER_TINT), sub_surface),
        b.math("MULTIPLY", backscatter, DIFFUSE_SCALE_FACTOR),
        label="backscatter_colour",
    )
    dlight_diffuse = b.vmath(
        "ADD",
        dlight_diffuse,
        b.scale(b.vmath("MULTIPLY", diffuse, backscatter_colour), SKIN_DIFFUSE_SCALER),
    )

    env_light_diffuse = b.vmath(
        "MULTIPLY",
        diffuse,
        _cube_ambient(b, "Ambient Cubemap", normal, scene.ambient_tint, "N"),
        label="env_light_diffuse",
    )

    # phong_specular(I, N, shininess, L) = saturate(pow(max(0, dot(reflect(L, N), -I)), shininess)).
    # I is the camera -> surface eye vector, so -I is scene.view_dir.
    shininess = b.lerp(1.0, 128.0, b.math("MULTIPLY", gloss, gloss), label="shininess")
    kspec = b.math(
        "POWER",
        b.math("MAXIMUM", b.vmath("DOT_PRODUCT", b.vmath("REFLECT", from_light, normal), scene.view_dir), 0.0),
        shininess,
        label="kspec",
        clamp=True,
    )
    dlight_specular = b.scale(b.scale(light_colour, b.math("MULTIPLY", specular_level, kspec)),
        DIFFUSE_SCALE_FACTOR * SKIN_SPECULAR_SCALER,
        label="dlight_specular",
    )

    reflected_view_vec = b.vmath("REFLECT", scene.view_dir, normal, label="reflected_view_vec")
    rim_env_colour = _cube_ambient(b, "Rim Cubemap", reflected_view_vec, scene.ambient_tint, "R")
    rim_fresnel = b.math("SUBTRACT", 1.0, b.vmath("DOT_PRODUCT", scene.view_dir, normal), clamp=True)
    riml = b.math(
        "MULTIPLY",
        b.math("MULTIPLY", b.math("POWER", rim_fresnel, 2.0, clamp=True), rim_mask),
        SKIN_RIM_BRIGHTNESS * SKIN_RIM_SCALER,
        label="riml",
    )
    # The .fx measures upness against float3(0,1,0) in the shader's own world space, which in
    # 3ds Max - and so in Blender, which shares its Z-up convention - is not the up axis. Kept
    # literal so the preview matches what an artist sees in Max rather than being quietly corrected.
    upness = b.math(
        "MAXIMUM",
        b.vmath(
            "DOT_PRODUCT",
            b.vmath("NORMALIZE", b.vmath("ADD", normal, (0.0, 0.75, 0.0))),
            (0.0, 1.0, 0.0),
        ),
        0.0,
        label="upness",
    )
    env_light_specular = b.scale(rim_env_colour, b.math("MULTIPLY", riml, upness), label="env_light_specular"
    )

    hdr = b.vmath(
        "ADD",
        b.vmath("ADD", env_light_diffuse, env_light_specular),
        b.vmath("ADD", dlight_specular, dlight_diffuse),
        label="hdr_linear_col",
    )
    tone_mapped = _tone_map(b, hdr, scene.low_bias, scene.high_bias)
    group.links.new(tone_mapped, group_output.inputs["Colour"])
    group[_VERSION_KEY] = FX_GROUP_VERSION
    return group


def build_decal_dirtmap_blend_group() -> bpy.types.NodeTree:
    group = _new_group(DECAL_DIRTMAP_NODE_GROUP_NAME)
    _add_socket(group, "Diffuse", "NodeSocketColor", (0.8, 0.8, 0.8, 1.0))
    _add_socket(group, "Specular", "NodeSocketColor", (1.0, 1.0, 1.0, 1.0))
    _add_socket(group, "Normal", "NodeSocketColor", (0.5, 0.5, 1.0, 1.0))
    _add_socket(group, "Dirtmap", "NodeSocketColor", (0.0, 0.0, 0.0, 1.0))
    _add_socket(group, "Dirtmap Alpha", "NodeSocketFloat", 0.0, min_value=0.0, max_value=1.0)
    _add_socket(group, "Dirtmask Alpha", "NodeSocketFloat", 0.0, min_value=0.0, max_value=1.0)
    group.interface.new_socket(name="Diffuse", in_out="OUTPUT", socket_type="NodeSocketColor")
    group.interface.new_socket(name="Specular", in_out="OUTPUT", socket_type="NodeSocketColor")
    group.interface.new_socket(name="Normal", in_out="OUTPUT", socket_type="NodeSocketColor")

    b = _Builder(group)
    group_input = b.place(group.nodes.new("NodeGroupInput"))
    group_output = b.place(group.nodes.new("NodeGroupOutput"))
    inputs = group_input.outputs

    mask_alpha = inputs["Dirtmask Alpha"]
    blend = b.math("MULTIPLY", mask_alpha, inputs["Dirtmap Alpha"], label="dirt_alpha_blend")
    group.links.new(
        b.vlerp(inputs["Diffuse"], DIRT_COLOUR, blend, label="ocolour"), group_output.inputs["Diffuse"]
    )
    group.links.new(
        b.vlerp(inputs["Specular"], DIRT_COLOUR, blend, label="ospecular"), group_output.inputs["Specular"]
    )

    # onormal.xz += (dirtmap.xy * 2 - 1) * mask_alpha. normalSwizzle_UPDATED puts the geometric
    # normal in .y, so .xz carry the tangent and bitangent - X and Y of an ordinary Blender
    # tangent-space normal. Blended in signed space, then re-encoded for the Normal Map node.
    base = b.vmath(
        "MULTIPLY_ADD", inputs["Normal"], (2.0, 2.0, 2.0), (-1.0, -1.0, -1.0), label="signed normal"
    )
    perturb = b.scale(b.vmath("MULTIPLY_ADD", inputs["Dirtmap"], (2.0, 2.0, 0.0), (-1.0, -1.0, 0.0), label="dirt_normal"),
        mask_alpha,
    )
    perturbed = b.vmath("NORMALIZE", b.vmath("ADD", base, perturb), label="onormal")
    group.links.new(
        b.vmath("MULTIPLY_ADD", perturbed, (0.5, 0.5, 0.5), (0.5, 0.5, 0.5), label="re-encoded"),
        group_output.inputs["Normal"],
    )
    group[_VERSION_KEY] = FX_GROUP_VERSION
    return group


def _write_vector(group: bpy.types.NodeTree, name: str, value) -> bool:
    node = group.nodes.get(name)
    if node is None:
        return False
    changed = False
    for index, component in enumerate(value):
        if abs(node.inputs[index].default_value - component) > 1e-6:
            node.inputs[index].default_value = component
            changed = True
    return changed


def _write_value(group: bpy.types.NodeTree, name: str, value: float) -> bool:
    node = group.nodes.get(name)
    if node is None or abs(node.outputs[0].default_value - value) <= 1e-6:
        return False
    node.outputs[0].default_value = value
    return True


def _write_colour(group: bpy.types.NodeTree, name: str, value) -> bool:
    node = group.nodes.get(name)
    if node is None:
        return False
    current = node.outputs[0].default_value
    if all(abs(current[i] - value[i]) <= 1e-6 for i in range(3)):
        return False
    node.outputs[0].default_value = (value[0], value[1], value[2], 1.0)
    return True


def sync_light(light_object) -> bool:
    # light_color0 in the .fx is a colour, not an intensity - the exposure comes from the technique's
    # own fixed 5000x HDR multiplier - so a Blender light's energy is deliberately not folded in.
    if light_object is None or light_object.type != "LIGHT":
        return False

    matrix = light_object.matrix_world
    is_sun = light_object.data.type == "SUN"
    changed = False
    for name in LIGHTING_GROUP_NAMES:
        group = bpy.data.node_groups.get(name)
        if group is None:
            continue
        changed |= _write_value(group, "Point Light", 0.0 if is_sun else 1.0)
        if is_sun:
            # A Blender sun emits along its local -Z, so the direction from a surface toward it is +Z.
            axis = matrix.to_3x3().normalized() @ mathutils.Vector((0.0, 0.0, 1.0))
            changed |= _write_vector(group, "Sun Direction", axis.normalized())
        else:
            changed |= _write_vector(group, "Light Position", matrix.translation)
        changed |= _write_colour(group, "Light Colour", light_object.data.color)
    return changed


def find_preview_light(scene: bpy.types.Scene):
    chosen = getattr(scene, "tw_preview_light", None)
    if chosen is not None and chosen.type == "LIGHT":
        return chosen
    lights = [obj for obj in scene.objects if obj.type == "LIGHT"]
    for light in lights:
        if light.data.type == "SUN":
            return light
    return lights[0] if lights else None


def _up_to_date(name: str) -> bpy.types.NodeTree | None:
    group = bpy.data.node_groups.get(name)
    return group if group is not None and group.get(_VERSION_KEY) == FX_GROUP_VERSION else None


_GROUP_BUILDERS = {
    FX_NODE_GROUP_NAME: build_full_standard_group,
    SKIN_NODE_GROUP_NAME: build_full_skin_group,
    TINT_NODE_GROUP_NAME: build_faction_tint_group,
    DIRTMAP_NODE_GROUP_NAME: build_dirtmap_blend_group,
    DECAL_DIRTMAP_NODE_GROUP_NAME: build_decal_dirtmap_blend_group,
}

# Both lighting groups carry their own copy of the scene-state nodes sync_light writes to.
LIGHTING_GROUP_NAMES = (FX_NODE_GROUP_NAME, SKIN_NODE_GROUP_NAME)


def ensure_groups() -> dict[str, bpy.types.NodeTree]:
    return {name: _up_to_date(name) or build() for name, build in _GROUP_BUILDERS.items()}
