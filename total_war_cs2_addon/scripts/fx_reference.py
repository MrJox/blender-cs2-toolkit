import math

SUN_ANGULAR_RADIUS = math.radians(0.5)
DIFFUSE_SCALE_FACTOR = 0.004
HDR_LIGHTING_MULTIPLIER = 5000.0
MAX_FRACTION_OF_FACETS = 0.9999
TONE_MAP_BLACK = 0.001
TONE_MAP_WHITE = 10.0
LOW_TONES_SCURVE_BIAS = 0.33
HIGH_TONES_SCURVE_BIAS = 0.66
REAL_APPROX_ZERO = 0.001
ERF_A = (8.0 * (math.pi - 3.0)) / (3.0 * math.pi * (4.0 - math.pi))


def _dot(a, b):
    return sum(x * y for x, y in zip(a, b))


def _norm(v):
    length = math.sqrt(_dot(v, v))
    return tuple(x / length for x in v)


def _neg(v):
    return tuple(-x for x in v)


def _reflect(i, n):
    d = 2.0 * _dot(i, n)
    return tuple(a - d * b for a, b in zip(i, n))


def _sat(x):
    return min(1.0, max(0.0, x))


def erf(x):
    x2 = x * x
    ax2 = ERF_A * x2
    numerator = (4.0 / math.pi) + ax2
    main_term = -x2 * (numerator / (1.0 + ax2))
    return math.copysign(math.sqrt(1.0 - math.exp(main_term)), x)


def erfinv(x):
    one_over_a = 1.0 / ERF_A
    log_1_minus_x_squared = math.log(1.0 - x * x)
    root_of_first_term = (2.0 / math.pi) * one_over_a + log_1_minus_x_squared * 0.5
    first_term = root_of_first_term * root_of_first_term
    second_term = log_1_minus_x_squared * one_over_a
    return math.copysign(math.sqrt(math.sqrt(first_term - second_term) - root_of_first_term), x)


def determine_fraction_of_facets(smoothness, angle):
    fraction = MAX_FRACTION_OF_FACETS * smoothness * smoothness + DIFFUSE_SCALE_FACTOR * (1.0 - smoothness * smoothness)
    sigma = max(SUN_ANGULAR_RADIUS / (erfinv(fraction) * math.sqrt(2.0)), 0.0001)
    k = 1.0 / (sigma * math.sqrt(2.0))
    return 0.5 * (erf((angle + SUN_ANGULAR_RADIUS) * k) - erf((angle - SUN_ANGULAR_RADIUS) * k))


def determine_facet_visibility(roughness, normal_vec, light_vec):
    n_dot_l = _sat(_dot(normal_vec, light_vec))
    towards_diffuse = math.sin(roughness * math.pi * 0.5)
    return 1.0 + (n_dot_l - 1.0) * towards_diffuse


def determine_surface_reflectivity(reflectivity, roughness, light_vec, view_vec):
    val1 = max(0.0, _dot(light_vec, _neg(view_vec)))
    val2 = val1 ** 10.0
    smoothness_val = math.cos(roughness * 0.98 * math.pi * 0.5) ** 0.5
    t = val2 * smoothness_val
    return reflectivity + (_sat(60.0 * reflectivity) - reflectivity) * t


def get_luminance(colour):
    return _sat(_dot(colour, (0.299, 0.587, 0.114)))


def get_adjusted_faction_colour(colour):
    scale = 1.5 + (0.5 - 1.5) * get_luminance(colour)
    return tuple(c * scale for c in colour)


def apply_tint(diffuse, tint, mask):
    return tuple(d + (d * t - d) * mask for d, t in zip(diffuse, tint))


def standard_lighting_model_directional_light(light_colour, light_vec, eye_vector, diffuse, specular, normal, smoothness, reflectivity, ambient, environment):
    light_colour = tuple(c * HDR_LIGHTING_MULTIPLIER for c in light_colour)
    roughness = 1.0 - smoothness
    view_dir = _neg(eye_vector)

    normal_dot_light = max(0.0, _dot(normal, light_vec))
    reflected_view_vec = _reflect(_neg(view_dir), normal)

    angle = math.acos(min(1.0, max(-1.0, _dot(light_vec, reflected_view_vec))))
    if _dot(light_vec, normal) <= 0.0:
        dlight_reflectivity = 0.0
    else:
        dlight_reflectivity = (
            determine_fraction_of_facets(smoothness, angle)
            * determine_facet_visibility(roughness, normal, light_vec)
            * determine_surface_reflectivity(reflectivity, roughness, light_vec, view_dir)
        )

    dlight_specular = tuple(dlight_reflectivity * s * l for s, l in zip(specular, light_colour))
    scattering = 1.0 - max(dlight_reflectivity, reflectivity)

    env_reflectivity = max(reflectivity, determine_surface_reflectivity(reflectivity, roughness, reflected_view_vec, view_dir))
    env_specular = tuple(e * env_reflectivity * s for e, s in zip(environment, specular))

    dlight_diffuse = tuple(d * normal_dot_light * l * scattering * DIFFUSE_SCALE_FACTOR for d, l in zip(diffuse, light_colour))
    env_diffuse = tuple(a * d * (1.0 - reflectivity) for a, d in zip(ambient, diffuse))

    return tuple(ed + es + ds + dd for ed, es, ds, dd in zip(env_diffuse, env_specular, dlight_specular, dlight_diffuse))


def get_scurve_y_pos(x, low_bias=LOW_TONES_SCURVE_BIAS, high_bias=HIGH_TONES_SCURVE_BIAS):
    gy = 3.0 * x * x * x - 6.0 * x * x + 3.0 * x
    gz = -3.0 * x * x * x + 3.0 * x * x
    gw = x * x * x
    return low_bias * gy + high_bias * gz + gw


def tone_map_linear_hdr_pixel_value(rgb, low_bias=LOW_TONES_SCURVE_BIAS, high_bias=HIGH_TONES_SCURVE_BIAS):
    cie_x = _dot(rgb, (0.4124, 0.3576, 0.1805))
    cie_y = _dot(rgb, (0.2126, 0.7152, 0.0722))
    cie_z = _dot(rgb, (0.0193, 0.1192, 0.9505))

    denominator = max(cie_x + cie_y + cie_z, REAL_APPROX_ZERO)
    x = cie_x / denominator
    y = cie_y / denominator
    log_y = math.log10(max(cie_y, REAL_APPROX_ZERO))

    log_y_black = math.log10(TONE_MAP_BLACK)
    log_y_white = math.log10(TONE_MAP_WHITE)
    log_y = max(log_y, log_y_black)
    display_range = log_y_white - log_y_black

    biased_log_y = log_y_black + get_scurve_y_pos((log_y - log_y_black) / display_range, low_bias, high_bias) * display_range
    ldr_y = (10.0 ** biased_log_y - TONE_MAP_BLACK) / (TONE_MAP_WHITE - TONE_MAP_BLACK)

    safe_y = max(y, REAL_APPROX_ZERO)
    xyz = (x * ldr_y / safe_y, ldr_y, (1.0 - x - y) * ldr_y / safe_y)

    r = _dot(xyz, (+3.2405, -1.5372, -0.4985))
    g = _dot(xyz, (-0.9693, +1.8760, +0.0416))
    b = _dot(xyz, (+0.0556, -0.2040, +1.0572))
    return tuple(max(0.0, c) for c in (r, g, b))


def ps30_main(
    diffuse,
    specular,
    smoothness,
    reflectivity,
    normal,
    view_dir,
    sun_dir,
    light_colour=(1.0, 1.0, 1.0),
    ambient=(0.5, 0.5, 0.5),
    environment=(0.5, 0.5, 0.5),
    masks=(0.0, 0.0, 0.0),
    tints=((0.2176, 0.0063, 0.0063), (0.0704, 0.3250, 0.2176), (0.2176, 0.0290, 0.0063)),
    faction_colouring=True,
    low_bias=LOW_TONES_SCURVE_BIAS,
    high_bias=HIGH_TONES_SCURVE_BIAS,
):
    for tint, mask in zip(tints, masks):
        resolved = get_adjusted_faction_colour(tint) if faction_colouring else tint
        diffuse = apply_tint(diffuse, resolved, mask)

    return _shade(
        diffuse, specular, smoothness, reflectivity, normal, view_dir, sun_dir,
        light_colour, ambient, environment, low_bias, high_bias,
    )


def _shade(diffuse, specular, smoothness, reflectivity, normal, view_dir, sun_dir, light_colour, ambient, environment, low_bias, high_bias):
    hdr = standard_lighting_model_directional_light(
        light_colour, _norm(sun_dir), _neg(_norm(view_dir)), diffuse, specular, _norm(normal), smoothness, reflectivity, ambient, environment
    )
    return tuple(_sat(c) for c in tone_map_linear_hdr_pixel_value(hdr, low_bias, high_bias))


def ps_common_blend_decal(diffuse, specular, reflectivity, decal_diffuse, decal_alpha, decal_mask, vertex_alpha):
    blend = decal_mask * decal_alpha * (1.0 - vertex_alpha)
    return (
        tuple(d + (c - d) * blend for d, c in zip(diffuse, decal_diffuse)),
        tuple(s + (c - s) * blend for s, c in zip(specular, decal_diffuse)),
        reflectivity + (reflectivity * 0.5 - reflectivity) * blend,
        blend,
    )


def ps30_main_custom_terrain(
    diffuse,
    specular,
    smoothness,
    reflectivity,
    decal_diffuse,
    decal_alpha,
    decal_mask,
    vertex_alpha,
    normal,
    view_dir,
    sun_dir,
    light_colour=(1.0, 1.0, 1.0),
    ambient=(0.5, 0.5, 0.5),
    environment=(0.5, 0.5, 0.5),
    low_bias=LOW_TONES_SCURVE_BIAS,
    high_bias=HIGH_TONES_SCURVE_BIAS,
):
    diffuse, specular, reflectivity, _ = ps_common_blend_decal(
        diffuse, specular, reflectivity, decal_diffuse, decal_alpha, decal_mask, vertex_alpha
    )
    return _shade(
        diffuse, specular, smoothness, reflectivity, normal, view_dir, sun_dir,
        light_colour, ambient, environment, low_bias, high_bias,
    )


def ps30_full_ao(
    diffuse,
    specular,
    smoothness,
    reflectivity,
    ambient_occlusion,
    normal,
    view_dir,
    sun_dir,
    light_colour=(1.0, 1.0, 1.0),
    ambient=(0.5, 0.5, 0.5),
    environment=(0.5, 0.5, 0.5),
    low_bias=LOW_TONES_SCURVE_BIAS,
    high_bias=HIGH_TONES_SCURVE_BIAS,
):
    diffuse = tuple(d * a for d, a in zip(diffuse, ambient_occlusion))
    specular = tuple(s * a for s, a in zip(specular, ambient_occlusion))
    return _shade(
        diffuse, specular, smoothness, reflectivity, normal, view_dir, sun_dir,
        light_colour, ambient, environment, low_bias, high_bias,
    )


def dirtmap_tint(dirtmap_rgb, dirtmap_alpha, alpha_mask):
    blend_2 = alpha_mask * (1.0 + (dirtmap_alpha - 1.0) * alpha_mask)
    blend_amount = _sat(blend_2)
    return tuple(d + (1.0 - d) * blend_amount for d in dirtmap_rgb)


def ps30_full_dirtmap(
    diffuse,
    specular,
    smoothness,
    reflectivity,
    dirtmap_rgb,
    dirtmap_alpha,
    alpha_mask,
    normal,
    view_dir,
    sun_dir,
    light_colour=(1.0, 1.0, 1.0),
    ambient=(0.5, 0.5, 0.5),
    environment=(0.5, 0.5, 0.5),
    low_bias=LOW_TONES_SCURVE_BIAS,
    high_bias=HIGH_TONES_SCURVE_BIAS,
):
    tint = dirtmap_tint(dirtmap_rgb, dirtmap_alpha, alpha_mask)
    diffuse = tuple(d * t for d, t in zip(diffuse, tint))
    specular = tuple(s * t for s, t in zip(specular, tint))
    return _shade(
        diffuse, specular, smoothness, reflectivity, normal, view_dir, sun_dir,
        light_colour, ambient, environment, low_bias, high_bias,
    )
