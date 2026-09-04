import math
import os
import sys
import tempfile

import bpy

repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
plugin_dir = os.path.join(repo_root, "total_war_buildings")
for path in (plugin_dir, os.path.dirname(__file__)):
    if path not in sys.path:
        sys.path.insert(0, path)

import fx_reference as fx
from materials import environment as env
from materials.fx_nodegroup import FX_NODE_GROUP_NAME, build_faction_tint_group, build_full_standard_group
from props.properties import get_assembly_kit_root_or_empty
from materials.material_builder import create_total_war_material, read_material_def
from materials.template import build_directx_material_node
from extraction import extract

TOLERANCE = 2.0e-3


# Cycles hands back render data in the scene working space, which is not the EXR file space, so a
# raw pixel read is not the emission value that went in. Every case therefore renders the node graph
# and a plain Emission node holding the reference value side by side in one frame - both take the
# identical path out, so the comparison is independent of colour management entirely.
def _setup_scene():
    bpy.ops.wm.read_factory_settings(use_empty=True)
    scene = bpy.context.scene
    scene.render.engine = "CYCLES"
    scene.cycles.samples = 1
    scene.cycles.pixel_filter_type = "BOX"
    scene.cycles.filter_width = 0.01
    scene.render.resolution_x = 2
    scene.render.resolution_y = 2
    scene.render.image_settings.file_format = "OPEN_EXR"
    scene.render.image_settings.color_depth = "32"
    scene.view_settings.view_transform = "Standard"

    camera_data = bpy.data.cameras.new("Camera")
    camera_data.type = "ORTHO"
    camera_data.ortho_scale = 1.0
    camera = bpy.data.objects.new("Camera", camera_data)
    camera.location = (0.0, 0.0, 5.0)
    scene.collection.objects.link(camera)
    scene.camera = camera

    bpy.ops.mesh.primitive_plane_add(size=20.0)
    plane = bpy.context.active_object
    plane.data.materials.append(bpy.data.materials.new("Slot"))

    control_material, _, control_emission = _emission_material("Reference")
    return plane, control_material, control_emission


def _render(plane, material):
    plane.data.materials[0] = material
    scene = bpy.context.scene
    path = os.path.join(tempfile.gettempdir(), "tw_fx_probe.exr")
    scene.render.filepath = path[:-4]
    bpy.ops.render.render(write_still=True)
    image = bpy.data.images.load(path, check_existing=False)
    pixel = tuple(image.pixels[:3])
    bpy.data.images.remove(image)
    return pixel


def _render_pair(plane, subject_material, control, expected):
    control_material, control_emission = control
    control_emission.inputs["Color"].default_value = tuple(expected) + (1.0,)
    return _render(plane, subject_material), _render(plane, control_material)


def _emission_material(name: str):
    material = bpy.data.materials.new(name)
    material.use_nodes = True
    tree = material.node_tree
    tree.nodes.clear()
    output = tree.nodes.new("ShaderNodeOutputMaterial")
    emission = tree.nodes.new("ShaderNodeEmission")
    tree.links.new(emission.outputs["Emission"], output.inputs["Surface"])
    return material, tree, emission


def _white_environment_image():
    existing = bpy.data.images.get("tw_test_white_env")
    if existing is not None:
        return existing
    image = bpy.data.images.new("tw_test_white_env", width=4, height=4, alpha=True)
    image.colorspace_settings.name = "Non-Color"
    image.pixels = [1.0] * (4 * 4 * 4)
    return image


def _configure_scene_nodes(group, sun_direction, ambient, environment) -> None:
    # The cubemaps vary with direction, so every comparison against the flat-colour reference has to
    # neutralise them: a white environment image turns the Ambient/Environment tints back into the
    # plain colours fx_reference expects.
    white = _white_environment_image()
    for node in group.nodes:
        if node.type == "TEX_ENVIRONMENT":
            node.image = white

    for index, component in enumerate(sun_direction):
        group.nodes["Sun Direction"].inputs[index].default_value = component
    group.nodes["Point Light"].outputs[0].default_value = 0.0
    group.nodes["Ambient Colour"].outputs[0].default_value = tuple(ambient) + (1.0,)
    group.nodes["Environment Colour"].outputs[0].default_value = tuple(environment) + (1.0,)


def _compare(label: str, rendered, expected, failures: list[str]):
    deltas = [abs(a - b) for a, b in zip(rendered, expected)]
    status = "OK  " if max(deltas) <= TOLERANCE else "FAIL"
    print(f"  [{status}] {label}: rendered={tuple(round(c, 5) for c in rendered)} expected={tuple(round(c, 5) for c in expected)} max_delta={max(deltas):.2e}")
    if max(deltas) > TOLERANCE:
        failures.append(label)


CASES = [
    ("untouched placeholder", (0.6038, 0.6038, 0.6038), (1.0, 1.0, 1.0), 0.2140, 0.2140, (0.0, 0.0, 1.0)),
    ("normal facing sun", (0.6038, 0.6038, 0.6038), (1.0, 1.0, 1.0), 0.2140, 0.2140, fx._norm((-0.5, 2.0, 1.25))),
    ("facing away from sun", (0.6038, 0.6038, 0.6038), (1.0, 1.0, 1.0), 0.2140, 0.2140, (0.5, -2.0, -1.25)),
    ("glossy metal-ish", (0.05, 0.04, 0.03), (0.95, 0.9, 0.6), 0.9, 0.8, (0.0, 0.0, 1.0)),
    ("rough dark", (0.02, 0.02, 0.05), (0.2, 0.2, 0.2), 0.05, 0.02, (0.3, 0.2, 0.9)),
    ("half-lit saturated", (0.4, 0.1, 0.05), (1.0, 0.8, 0.7), 0.55, 0.35, (0.8, 0.1, 0.6)),
]

VIEW_DIR = (0.0, 0.0, 1.0)
SUN_DIR = (-0.5, 2.0, 1.25)
_HALF_VECTOR = fx._norm(tuple(a + b for a, b in zip(fx._norm(SUN_DIR), VIEW_DIR)))
CASES.append(("half vector, near mirror angle", (0.3, 0.3, 0.3), (1.0, 1.0, 1.0), 0.75, 0.5, _HALF_VECTOR))
AMBIENT = (0.5, 0.5, 0.5)
ENVIRONMENT = (0.5, 0.5, 0.5)


def test_full_standard_group(plane, control) -> list[str]:
    print("Full_standard lighting group vs. ps30_main_UPDATED reference")
    failures: list[str] = []
    group = build_full_standard_group()
    material, tree, emission = _emission_material("FxProbe")
    node = tree.nodes.new("ShaderNodeGroup")
    node.node_tree = group
    tree.links.new(node.outputs["Colour"], emission.inputs["Color"])

    # Sun/ambient/environment are scene state and now live inside the group, shared by every material.
    # View Direction is the group's own Geometry node: the ortho camera sits at +Z looking down, so
    # the real Incoming vector is VIEW_DIR, which this test now exercises rather than overrides.
    _configure_scene_nodes(group, SUN_DIR, AMBIENT, ENVIRONMENT)

    for label, diffuse, specular, smoothness, reflectivity, normal in CASES:
        node.inputs["Diffuse Colour"].default_value = diffuse + (1.0,)
        node.inputs["Specular Colour"].default_value = specular + (1.0,)
        node.inputs["Smoothness"].default_value = smoothness
        node.inputs["Reflectivity"].default_value = reflectivity
        node.inputs["Normal"].default_value = normal
        expected = fx.ps30_main(
            diffuse, specular, smoothness, reflectivity, normal, VIEW_DIR, SUN_DIR,
            ambient=AMBIENT, environment=ENVIRONMENT,
        )
        _compare(label, *_render_pair(plane, material, control, expected), failures)

    bpy.data.materials.remove(material)
    return failures


TINT_CASES = [
    ("no masks", (0.0, 0.0, 0.0), True),
    ("mask 1 full", (1.0, 0.0, 0.0), True),
    ("all masks partial", (0.4, 0.7, 0.25), True),
    ("all masks partial, no faction adjust", (0.4, 0.7, 0.25), False),
]


def test_faction_tint_group(plane, control) -> list[str]:
    print("Faction tint group vs. ps30_main_UPDATED reference")
    failures: list[str] = []
    group = build_faction_tint_group()
    material, tree, emission = _emission_material("TintProbe")
    node = tree.nodes.new("ShaderNodeGroup")
    node.node_tree = group
    tree.links.new(node.outputs["Diffuse"], emission.inputs["Color"])

    diffuse = (0.55, 0.45, 0.3)
    colours = ((0.2176, 0.0063, 0.0063), (0.0704, 0.3250, 0.2176), (0.2176, 0.0290, 0.0063))
    node.inputs["Diffuse"].default_value = diffuse + (1.0,)
    for index, colour in enumerate(colours, start=1):
        node.inputs[f"Colour {index}"].default_value = colour + (1.0,)

    for label, masks, faction in TINT_CASES:
        for index, mask in enumerate(masks, start=1):
            node.inputs[f"Mask {index}"].default_value = mask
        node.inputs["Faction Colouring"].default_value = 1.0 if faction else 0.0
        expected = diffuse
        for colour, mask in zip(colours, masks):
            resolved = fx.get_adjusted_faction_colour(colour) if faction else colour
            expected = fx.apply_tint(expected, resolved, mask)
        _compare(label, *_render_pair(plane, material, control, expected), failures)

    bpy.data.materials.remove(material)
    return failures


def _srgb_to_linear(value: float) -> float:
    return value / 12.92 if value <= 0.04045 else ((value + 0.055) / 1.055) ** 2.4


def test_material_end_to_end(plane, control) -> list[str]:
    print("create_total_war_material end to end vs. ps30_main_UPDATED reference")
    failures: list[str] = []
    material = bpy.data.materials.new("EndToEnd")
    material.tw_shader_type = "default"
    create_total_war_material(material)
    tree = material.node_tree
    _neutralise_scene(tree)
    fx_node = tree.nodes["Full_standard"]

    # Placeholder values are authored in the slot colorspace the .fx sampler declares, so what the
    # lighting model actually receives is the decoded value, not the stored one.
    diffuse, specular, smoothness, reflectivity = _base_channels(tree)
    expected = fx.ps30_main(
        diffuse,
        specular,
        smoothness,
        reflectivity,
        (0.0, 0.0, 1.0),
        VIEW_DIR,
        SUN_DIR,
        ambient=AMBIENT,
        environment=ENVIRONMENT,
    )

    # Measured with the tangent-space normal fed in directly, then again through the real Normal Map
    # chain. The .fx placeholder flatnormal.tga is (128, 128, 255), which decodes to a normal tilted
    # by half a bit per axis rather than exactly flat, so the second measurement carries a tolerance
    # sized for that. It is still two orders of magnitude tighter than the all-black placeholder bug
    # this check exists to catch, which came in at 6.3e-1.
    normal_link = next(link for link in tree.links if link.to_socket == fx_node.inputs["Normal"])
    tree.links.remove(normal_link)
    fx_node.inputs["Normal"].default_value = (0.0, 0.0, 1.0)
    _compare("untouched standard material", *_render_pair(plane, material, control, expected), failures)

    tree.links.new(tree.nodes["Normal Map"].outputs["Normal"], fx_node.inputs["Normal"])
    rendered, reference = _render_pair(plane, material, control, expected)
    deltas = [abs(a - b) for a, b in zip(rendered, reference)]
    half_bit_tilt_tolerance = 2.0e-2
    status = "OK  " if max(deltas) <= half_bit_tilt_tolerance else "FAIL"
    print(f"  [{status}] placeholder normal map decodes to near-flat: max_delta={max(deltas):.2e}")
    if max(deltas) > half_bit_tilt_tolerance:
        failures.append("placeholder normal map does not decode to a near-flat normal")

    bpy.data.materials.remove(material)
    return failures


def _solid_image(name: str, rgba, non_color: bool = False, float_buffer: bool = False) -> bpy.types.Image:
    image = bpy.data.images.new(name, width=4, height=4, alpha=True, float_buffer=float_buffer)
    if non_color:
        image.colorspace_settings.name = "Non-Color"
    image.pixels = list(rgba) * (4 * 4)
    return image


def _base_channels(tree):
    stored = {slot: tree.nodes[slot].image.pixels[0] for slot in ("Diffuse", "Gloss", "Level", "Specular")}
    return (
        (_srgb_to_linear(stored["Diffuse"]),) * 3,
        (_srgb_to_linear(stored["Specular"]),) * 3,
        _srgb_to_linear(stored["Gloss"]),
        _srgb_to_linear(stored["Level"]),
    )


def _neutralise_scene(tree) -> None:
    _configure_scene_nodes(tree.nodes["Full_standard"].node_tree, SUN_DIR, AMBIENT, ENVIRONMENT)


def _pin_flat_normal(tree) -> None:
    fx_node = tree.nodes["Full_standard"]
    link = next((l for l in tree.links if l.to_socket == fx_node.inputs["Normal"]), None)
    if link is not None:
        tree.links.remove(link)
    fx_node.inputs["Normal"].default_value = (0.0, 0.0, 1.0)


AO_CASES = [
    ("neutral white AO collapses to Full_standard", (1.0, 1.0, 1.0)),
    ("uniform mid AO", (0.4, 0.4, 0.4)),
    ("coloured AO", (0.4, 0.6, 0.2)),
]


def test_ao_variant(plane, control) -> list[str]:
    print("Ship Ambientmap material vs. ps30_full_ao reference")
    failures: list[str] = []
    material = bpy.data.materials.new("AoVariant")
    material.tw_shader_type = "ship_ambientmap"
    create_total_war_material(material)
    tree = material.node_tree
    _neutralise_scene(tree)
    _pin_flat_normal(tree)
    diffuse, specular, smoothness, reflectivity = _base_channels(tree)

    for label, ao in AO_CASES:
        image = _solid_image(f"ao_{label}", tuple(ao) + (1.0,), non_color=True)
        tree.nodes["Ambient Map"].image = image
        expected = fx.ps30_full_ao(
            diffuse, specular, smoothness, reflectivity, tuple(image.pixels[:3]),
            (0.0, 0.0, 1.0), VIEW_DIR, SUN_DIR, ambient=AMBIENT, environment=ENVIRONMENT,
        )
        _compare(label, *_render_pair(plane, material, control, expected), failures)
        bpy.data.images.remove(image)

    bpy.data.materials.remove(material)
    return failures


DIRTMAP_CASES = [
    ("clean dirtmask collapses to Full_standard", (1.0, 1.0, 1.0, 1.0), 1.0),
    ("fully dirty", (0.4, 0.2, 0.2, 1.0), 0.0),
    ("partial dirt, opaque dirtmap", (0.4, 0.2, 0.2, 1.0), 0.4),
    ("partial dirt, translucent dirtmap", (0.4, 0.2, 0.2, 0.6), 0.4),
    ("dirtmap alpha fully masks the dirt out", (0.2, 0.6, 0.8, 1.0), 0.6),
]


def test_dirtmap_variant(plane, control) -> list[str]:
    print("Tiled Dirtmap material vs. ps30_full_dirtmap reference")
    failures: list[str] = []
    material = bpy.data.materials.new("DirtmapVariant")
    material.tw_shader_type = "tiled_dirtmap"
    create_total_war_material(material)
    tree = material.node_tree
    _neutralise_scene(tree)
    _pin_flat_normal(tree)
    diffuse, specular, smoothness, reflectivity = _base_channels(tree)

    for label, dirtmap, dirtmask in DIRTMAP_CASES:
        dirt_image = _solid_image(f"dirt_{label}", dirtmap)
        mask_image = _solid_image(f"mask_{label}", (dirtmask,) * 3 + (1.0,), non_color=True)
        tree.nodes["Dirtmap"].image = dirt_image
        tree.nodes["Dirtmask"].image = mask_image
        expected = fx.ps30_full_dirtmap(
            diffuse, specular, smoothness, reflectivity,
            tuple(_srgb_to_linear(c) for c in dirt_image.pixels[:3]),
            dirt_image.pixels[3],
            mask_image.pixels[0],
            (0.0, 0.0, 1.0), VIEW_DIR, SUN_DIR, ambient=AMBIENT, environment=ENVIRONMENT,
        )
        _compare(label, *_render_pair(plane, material, control, expected), failures)
        bpy.data.images.remove(dirt_image)
        bpy.data.images.remove(mask_image)

    bpy.data.materials.remove(material)
    return failures


def _split_image(name: str, left, right, non_color: bool = False) -> bpy.types.Image:
    image = bpy.data.images.new(name, width=2, height=1, alpha=True)
    if non_color:
        image.colorspace_settings.name = "Non-Color"
    image.pixels = list(left) + list(right)
    return image


def _split_uvs(plane) -> None:
    # UV1 samples the left half of every split texture, UV2 the right half. The UI-active layer is
    # deliberately set to the second one: an empty UV Map node has to follow active_render, which is
    # the same layer extraction._primary_uv_layer exports as channel 1.
    mesh = plane.data
    primary = mesh.uv_layers[0]
    primary.name = "UVMap"
    secondary = mesh.uv_layers.get("UV2") or mesh.uv_layers.new(name="UV2")
    for datum in primary.data:
        datum.uv = (0.25, 0.5)
    for datum in secondary.data:
        datum.uv = (0.75, 0.5)
    primary.active_render = True
    secondary.active = True


def test_uv_channel_routing(plane, control) -> list[str]:
    print("UV channel routing: dirtmap on UV1, dirtmask and AO on UV2")
    failures: list[str] = []
    _split_uvs(plane)
    left_rgb, right_rgb = (0.4, 0.4, 0.4), (0.8, 0.8, 0.8)
    left_mask, right_mask = 0.2, 0.6

    material = bpy.data.materials.new("DirtmapRouting")
    material.tw_shader_type = "tiled_dirtmap"
    create_total_war_material(material)
    tree = material.node_tree
    _neutralise_scene(tree)
    _pin_flat_normal(tree)
    tree.nodes["Dirtmap Tiling"].inputs["Scale"].default_value = (1.0, 1.0, 1.0)
    diffuse, specular, smoothness, reflectivity = _base_channels(tree)

    dirt_image = _split_image("routing_dirt", left_rgb + (1.0,), right_rgb + (1.0,))
    mask_image = _split_image(
        "routing_mask", (left_mask,) * 3 + (1.0,), (right_mask,) * 3 + (1.0,), non_color=True
    )
    for label, node in (("Dirtmap", dirt_image), ("Dirtmask", mask_image)):
        tex = tree.nodes[label]
        tex.image = node
        tex.interpolation = "Closest"
        tex.extension = "EXTEND"

    expected = fx.ps30_full_dirtmap(
        diffuse, specular, smoothness, reflectivity,
        tuple(_srgb_to_linear(c) for c in dirt_image.pixels[:3]),
        1.0,
        mask_image.pixels[4],
        (0.0, 0.0, 1.0), VIEW_DIR, SUN_DIR, ambient=AMBIENT, environment=ENVIRONMENT,
    )
    _compare("dirtmap reads UV1, dirtmask reads UV2", *_render_pair(plane, material, control, expected), failures)
    bpy.data.materials.remove(material)

    material = bpy.data.materials.new("AoRouting")
    material.tw_shader_type = "ship_ambientmap"
    create_total_war_material(material)
    tree = material.node_tree
    _neutralise_scene(tree)
    _pin_flat_normal(tree)
    diffuse, specular, smoothness, reflectivity = _base_channels(tree)
    ao_image = _split_image("routing_ao", left_rgb + (1.0,), right_rgb + (1.0,), non_color=True)
    ao_tex = tree.nodes["Ambient Map"]
    ao_tex.image = ao_image
    ao_tex.interpolation = "Closest"
    ao_tex.extension = "EXTEND"

    expected = fx.ps30_full_ao(
        diffuse, specular, smoothness, reflectivity, tuple(ao_image.pixels[4:7]),
        (0.0, 0.0, 1.0), VIEW_DIR, SUN_DIR, ambient=AMBIENT, environment=ENVIRONMENT,
    )
    _compare("ambient occlusion reads UV2", *_render_pair(plane, material, control, expected), failures)

    for image in (dirt_image, mask_image, ao_image):
        bpy.data.images.remove(image)
    bpy.data.materials.remove(material)
    return failures


def test_directx_normal_convention(plane) -> list[str]:
    print("Normal map convention: DirectX green-down by default")
    failures: list[str] = []
    material = bpy.data.materials.new("NormalConvention")
    material.tw_shader_type = "default"
    create_total_war_material(material)
    tree = material.node_tree
    _neutralise_scene(tree)
    normal_map = tree.nodes["Normal Map"]
    normal_tex = tree.nodes["Normal"]

    # 0.8 and 0.2 are both exact in 8 bits and are each other's complement, so a correct green flip
    # maps one onto the other with no quantisation slack.
    directx = _solid_image("nrm_directx", (0.6, 0.8, 1.0, 1.0), non_color=True)
    opengl = _solid_image("nrm_opengl", (0.6, 0.2, 1.0, 1.0), non_color=True)

    if normal_map.convention != "DIRECTX":
        failures.append(f"Normal Map convention is {normal_map.convention}, expected DIRECTX")

    normal_tex.image = directx
    directx_mode = _render(plane, material)

    normal_map.convention = "OPENGL"
    opengl_same_map = _render(plane, material)
    normal_tex.image = opengl
    opengl_mirrored_map = _render(plane, material)
    normal_map.convention = "DIRECTX"

    deltas = [abs(a - b) for a, b in zip(directx_mode, opengl_mirrored_map)]
    status = "OK  " if max(deltas) <= TOLERANCE else "FAIL"
    print(f"  [{status}] DIRECTX on green=0.8 matches OPENGL on green=0.2: max_delta={max(deltas):.2e}")
    if max(deltas) > TOLERANCE:
        failures.append("the DIRECTX convention is not a plain green-channel flip")

    # Without this the check above would also pass if green had no effect on shading at all.
    control = [abs(a - b) for a, b in zip(directx_mode, opengl_same_map)]
    status = "OK  " if max(control) > TOLERANCE else "FAIL"
    print(f"  [{status}] switching convention changes shading (control): max_delta={max(control):.2e}")
    if max(control) <= TOLERANCE:
        failures.append("green channel has no effect on shading, so the convention check proves nothing")

    for image in (directx, opengl):
        bpy.data.images.remove(image)
    bpy.data.materials.remove(material)
    return failures


# ps30_main_UPDATED derives its light vector per pixel as normalize(light_position0 - Wpos), so the
# expected value depends on which surface point the probe pixel actually is. Rather than derive that
# from the frame layout, this test collapses the ortho frame to a point around the origin, so every
# pixel sits at PROBE_SURFACE_POINT to within 1e-4. Getting this wrong is not a silent failure: with
# the light close to the surface the result swings by more than 1.0.
PROBE_SURFACE_POINT = (0.0, 0.0, 0.0)
PROBE_ORTHO_SCALE = 1.0e-4

POINT_LIGHT_CASES = [
    ("light overhead", (0.0, 0.0, 6.0)),
    ("light low and to one side", (4.0, -3.0, 1.0)),
    ("light close to the surface", (-0.2, -0.2, 0.6)),
]


def test_point_light(plane, control) -> list[str]:
    print("Point light vs. ps30_main_UPDATED's normalize(light_position0 - Wpos)")
    failures: list[str] = []
    material = bpy.data.materials.new("PointLight")
    material.tw_shader_type = "default"
    create_total_war_material(material)
    tree = material.node_tree
    _neutralise_scene(tree)
    _pin_flat_normal(tree)
    diffuse, specular, smoothness, reflectivity = _base_channels(tree)

    camera = bpy.context.scene.camera.data
    original_scale = camera.ortho_scale
    camera.ortho_scale = PROBE_ORTHO_SCALE

    group = tree.nodes["Full_standard"].node_tree
    group.nodes["Point Light"].outputs[0].default_value = 1.0
    rendered_by_case = {}
    for label, position in POINT_LIGHT_CASES:
        for index, component in enumerate(position):
            group.nodes["Light Position"].inputs[index].default_value = component
        light_vector = tuple(p - s for p, s in zip(position, PROBE_SURFACE_POINT))
        expected = fx.ps30_main(
            diffuse, specular, smoothness, reflectivity, (0.0, 0.0, 1.0), VIEW_DIR, light_vector,
            ambient=AMBIENT, environment=ENVIRONMENT,
        )
        rendered, reference = _render_pair(plane, material, control, expected)
        rendered_by_case[label] = rendered
        _compare(label, rendered, reference, failures)

    # A directional light would give the same answer for all three positions.
    spread = max(
        abs(a - b)
        for first in rendered_by_case.values()
        for second in rendered_by_case.values()
        for a, b in zip(first, second)
    )
    status = "OK  " if spread > TOLERANCE else "FAIL"
    print(f"  [{status}] moving the light changes shading (control): max_delta={spread:.2e}")
    if spread <= TOLERANCE:
        failures.append("point light position has no effect, so the position math is not being used")

    group.nodes["Point Light"].outputs[0].default_value = 0.0
    camera.ortho_scale = original_scale
    bpy.data.materials.remove(material)
    return failures


ENVIRONMENT_PROBE_PIXELS = ((3, 5), (200, 100), (511, 256), (900, 40), (640, 400), (1023, 511))


def test_environment_cubemap(plane, control) -> list[str]:
    print("Environment cubemap: Blender's equirectangular lookup vs. the cube conversion")
    failures: list[str] = []
    images = env.ensure_environment_images(get_assembly_kit_root_or_empty())
    reflection = images[env.image_name("Reflection")]
    if reflection.size[0] <= 4:
        print("  [SKIP] Assembly Kit cubemaps not found, running on the flat fallback")
        return failures

    width, height = reflection.size
    stored = list(reflection.pixels)
    x, y, z = env._equirectangular_directions(width, height)

    material, tree, emission = _emission_material("EnvProbe")
    texture = tree.nodes.new("ShaderNodeTexEnvironment")
    texture.image = reflection
    vector = tree.nodes.new("ShaderNodeCombineXYZ")
    tree.links.new(vector.outputs["Vector"], texture.inputs["Vector"])
    tree.links.new(texture.outputs["Color"], emission.inputs["Color"])

    for column, row in ENVIRONMENT_PROBE_PIXELS:
        direction = (float(x[row, column]), float(y[row, column]), float(z[row, column]))
        for index, component in enumerate(direction):
            vector.inputs[index].default_value = component
        offset = (row * width + column) * 4
        expected = tuple(stored[offset : offset + 3])
        _compare(f"pixel ({column}, {row})", *_render_pair(plane, material, control, expected), failures)

    bpy.data.materials.remove(material)

    group = bpy.data.node_groups[FX_NODE_GROUP_NAME]
    cubemap_nodes = [n for n in group.nodes if n.type == "TEX_ENVIRONMENT"]
    expected_nodes = 1 + len(env.ENVIRONMENT_MIP_LADDER)
    status = "OK  " if len(cubemap_nodes) == expected_nodes else "FAIL"
    print(f"  [{status}] lighting group carries {len(cubemap_nodes)} cubemap nodes (expected {expected_nodes})")
    if len(cubemap_nodes) != expected_nodes:
        failures.append(f"expected {expected_nodes} cubemap nodes in the lighting group")
    return failures


def _set_vertex_alpha(plane, alpha: float) -> None:
    mesh = plane.data
    attribute = mesh.color_attributes.get("Color")
    if attribute is None:
        attribute = mesh.color_attributes.new(name="Color", type="FLOAT_COLOR", domain="POINT")
    for datum in attribute.data:
        datum.color = (1.0, 1.0, 1.0, alpha)
    mesh.color_attributes.active_color = attribute
    mesh.color_attributes.render_color_index = mesh.color_attributes.find(attribute.name)


# decal diffuse rgb, decal diffuse alpha, decal mask alpha, vertex alpha
TERRAIN_CASES = [
    ("vertex alpha 1 leaves the asset's own material", (0.4, 0.25, 0.15), 1.0, 1.0, 1.0),
    ("vertex alpha 0 is fully the terrain side", (0.4, 0.25, 0.15), 1.0, 1.0, 0.0),
    ("vertex alpha 0.6 is a partial blend", (0.4, 0.25, 0.15), 1.0, 1.0, 0.6),
    ("decal mask alpha 0 suppresses the blend", (0.4, 0.25, 0.15), 1.0, 0.0, 0.0),
    ("decal diffuse alpha scales the blend", (0.8, 0.2, 0.6), 0.4, 1.0, 0.0),
]


def test_terrain_blend(plane, control) -> list[str]:
    print("Terrain Blend material vs. ps30_main_custom_terrain reference")
    failures: list[str] = []
    material = bpy.data.materials.new("TerrainBlend")
    material.tw_shader_type = "terrain_blend"
    create_total_war_material(material)
    tree = material.node_tree
    _neutralise_scene(tree)
    _pin_flat_normal(tree)

    for name in ("Diffuse", "Normal", "Gloss", "Level", "Specular", "Decal Diffuse", "Decal Normal", "Decal Mask", "Vertex Alpha"):
        if tree.nodes.get(name) is None:
            failures.append(f"terrain_blend missing '{name}' node")
    # The technique has no tint layers and samples no UV2.
    unwanted = [n.name for n in tree.nodes if n.name.startswith("Tint Mask") or n.type in ("UVMAP", "MAPPING", "TEX_ENVIRONMENT")]
    status = "OK  " if not unwanted else "FAIL"
    print(f"  [{status}] no tint or UV2 nodes built: {sorted(unwanted) if unwanted else 'none'}")
    if unwanted:
        failures.append(f"terrain_blend built nodes the technique never samples: {unwanted}")

    diffuse, specular, smoothness, reflectivity = _base_channels(tree)
    for label, decal_rgb, decal_alpha, mask_alpha, vertex_alpha in TERRAIN_CASES:
        # Float, Non-Color buffers: an 8-bit straight-alpha image loses about a bit of colour through
        # Blender's premultiply round-trip whenever alpha < 1, which is Blender's image storage rather
        # than anything in the blend under test here. The sRGB decode path is covered by the base slots.
        decal_image = _solid_image(f"decal_{label}", tuple(decal_rgb) + (decal_alpha,), non_color=True, float_buffer=True)
        mask_image = _solid_image(f"decalmask_{label}", (0.0, 0.0, 0.0, mask_alpha), non_color=True, float_buffer=True)
        tree.nodes["Decal Diffuse"].image = decal_image
        tree.nodes["Decal Mask"].image = mask_image
        _set_vertex_alpha(plane, vertex_alpha)
        expected = fx.ps30_main_custom_terrain(
            diffuse, specular, smoothness, reflectivity,
            tuple(decal_image.pixels[:3]),
            decal_image.pixels[3],
            mask_image.pixels[3],
            vertex_alpha,
            (0.0, 0.0, 1.0), VIEW_DIR, SUN_DIR, ambient=AMBIENT, environment=ENVIRONMENT,
        )
        _compare(label, *_render_pair(plane, material, control, expected), failures)
        bpy.data.images.remove(decal_image)
        bpy.data.images.remove(mask_image)

    definition = read_material_def(material)
    if any(definition.decal_texture_paths):
        failures.append("untouched decal slots read back as real paths")
    node = build_directx_material_node(
        node_name="t", material_name="t", rigid_material="terrain_blend", assembly_kit_root="C:/kit"
    )
    index = node.directx_material.shader_technique_index
    status = "OK  " if index == 4 else "FAIL"
    print(f"  [{status}] exports Full_custom_terrain technique index: {index} (expected 4)")
    if index != 4:
        failures.append(f"terrain_blend technique index is {index}, expected 4")

    for slot, path in zip(("Decal Diffuse", "Decal Normal", "Decal Mask"), ("//d.dds", "//n.dds", "//m.dds")):
        image = bpy.data.images.new(f"fake_{slot}", width=4, height=4)
        image.filepath = path
        tree.nodes[slot].image = image
    definition = read_material_def(material)
    exported = build_directx_material_node(
        node_name="t", material_name="t", rigid_material="terrain_blend", assembly_kit_root="C:/kit",
        decal_texture_paths=definition.decal_texture_paths,
    )
    written = {t.texture_name: t.texture_path for t in exported.directx_material.textures}
    ok = all(written[name].endswith(tail) for name, tail in (("t_decal_diffuse", "d.dds"), ("t_decal_normal", "n.dds"), ("t_decal_mask", "m.dds")))
    status = "OK  " if ok else "FAIL"
    print(f"  [{status}] decal slots reach the CS2: {[written[n] for n in ('t_decal_diffuse', 't_decal_normal', 't_decal_mask')]}")
    if not ok:
        failures.append("decal texture paths are not exported")

    # The preview reads the render colour attribute, so the export must read the same one.
    mesh = plane.data
    spare = mesh.color_attributes.new(name="Unused", type="FLOAT_COLOR", domain="POINT")
    for datum in spare.data:
        datum.color = (1.0, 1.0, 1.0, 0.9)
    mesh.color_attributes.active_color_index = mesh.color_attributes.find("Unused")
    mesh.color_attributes.render_color_index = mesh.color_attributes.find("Color")
    _set_vertex_alpha(plane, 0.1)
    picked = extract._colour_attribute(mesh)
    status = "OK  " if picked.name == "Color" else "FAIL"
    print(f"  [{status}] extraction follows the render colour attribute, not the active one: picked '{picked.name}'")
    if picked.name != "Color":
        failures.append(f"extraction picked '{picked.name}', but the preview renders the render attribute")
    mesh.color_attributes.remove(spare)

    # Vertex alpha is the blend control, so it has to survive extraction.
    _set_vertex_alpha(plane, 0.25)
    mesh_data = extract._convert_mesh(plane, bpy.context.evaluated_depsgraph_get())
    alphas = {round(v.color[3], 3) for v in mesh_data.vertices}
    status = "OK  " if alphas == {0.25} else "FAIL"
    print(f"  [{status}] vertex alpha survives extraction: {sorted(alphas)}")
    if alphas != {0.25}:
        failures.append(f"vertex alpha not exported, got {sorted(alphas)}")
    _set_vertex_alpha(plane, 1.0)

    bpy.data.materials.remove(material)
    return failures


def test_material_wiring() -> list[str]:
    print("create_total_war_material wiring")
    failures: list[str] = []
    for shader_type, expected_nodes in (
        ("default", ("Diffuse", "Normal", "Gloss", "Level", "Specular", "Tint Mask 1", "Tint Mask 2", "Tint Mask 3", "Faction Tint", "Normal Map", "Full_standard")),
        ("tiled_dirtmap", ("Diffuse", "Dirtmap", "Dirtmask", "Dirtmap Tiling", "Dirtmap Blend", "UV1", "UV2", "Normal Map", "Full_standard")),
        ("ship_ambientmap", ("Diffuse", "Ambient Map", "UV2", "Normal Map", "Full_standard")),
    ):
        material = bpy.data.materials.new(f"Wiring_{shader_type}")
        material.tw_shader_type = shader_type
        create_total_war_material(material)
        tree = material.node_tree
        for name in expected_nodes:
            if tree.nodes.get(name) is None:
                failures.append(f"{shader_type}: missing node '{name}'")
        fx_node = tree.nodes.get("Full_standard")
        if fx_node is not None:
            for socket in ("Diffuse Colour", "Specular Colour", "Smoothness", "Reflectivity", "Normal"):
                if not fx_node.inputs[socket].is_linked:
                    failures.append(f"{shader_type}: Full_standard input '{socket}' not linked")
        if not material.use_backface_culling:
            failures.append(f"{shader_type}: backface culling off (technique sets CullMode = CW)")

        definition = read_material_def(material)
        if definition.shader_type != shader_type:
            failures.append(f"{shader_type}: read_material_def shader_type mismatch")
        if any(definition.tint_mask_texture_paths):
            failures.append(f"{shader_type}: untouched tint masks read back as real paths")
        bpy.data.materials.remove(material)

    material = bpy.data.materials.new("Wiring_paths")
    material.tw_shader_type = "default"
    create_total_war_material(material)
    for index in range(1, 4):
        image = bpy.data.images.new(f"fake_mask_{index}", width=4, height=4)
        image.filepath = f"//textures/mask{index}.dds"
        material.node_tree.nodes[f"Tint Mask {index}"].image = image
    material.node_tree.nodes["Faction Tint"].inputs["Colour 1"].default_value = (0.25, 0.5, 0.75, 1.0)
    material.node_tree.nodes["Faction Tint"].inputs["Faction Colouring"].default_value = 0.0
    definition = read_material_def(material)
    for index in range(1, 4):
        if not definition.tint_mask_texture_paths[index - 1].endswith(f"mask{index}.dds"):
            failures.append(f"tint mask {index} path not read back: {definition.tint_mask_texture_paths[index - 1]}")
    if definition.faction_colouring:
        failures.append("faction_colouring not read back")
    if max(abs(a - b) for a, b in zip(definition.tint_colours[0], (0.25, 0.5, 0.75))) > 1e-6:
        failures.append(f"tint colour 1 not read back: {definition.tint_colours[0]}")
    if definition.diffuse_texture_path or definition.mask_texture_path:
        failures.append("tint mask images leaked into the Diffuse/Mask slots")
    bpy.data.materials.remove(material)
    return failures


def main():
    plane, control_material, control_emission = _setup_scene()
    control = (control_material, control_emission)
    try:
        bpy.ops.preferences.addon_enable(module="total_war_buildings")
    except Exception:
        import total_war_buildings

        total_war_buildings.register()

    failures = (
        test_full_standard_group(plane, control)
        + test_faction_tint_group(plane, control)
        + test_material_end_to_end(plane, control)
        + test_ao_variant(plane, control)
        + test_dirtmap_variant(plane, control)
        + test_terrain_blend(plane, control)
        + test_point_light(plane, control)
        + test_environment_cubemap(plane, control)
        + test_directx_normal_convention(plane)
        + test_material_wiring()
        + test_uv_channel_routing(plane, control)
    )
    print()
    if failures:
        print(f"FAILED ({len(failures)}):")
        for failure in failures:
            print(f"  - {failure}")
        sys.exit(1)
    print("All FX shader checks passed.")


main()
