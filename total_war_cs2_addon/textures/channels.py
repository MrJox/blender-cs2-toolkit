import numpy as np

# PLAN_textures.md 1.1 and 3.2: the suffixes BOB's combiner actions produce, and how to undo each
# one. Order matters for classify() - "_gloss_map" must be checked before a bare "_mask" style
# check would ever be tried, though none of these four currently overlap.
SUFFIX_GLOSS_MAP = "_gloss_map"
SUFFIX_MASK = "_mask"
SUFFIX_NORMAL = "_normal"
SUFFIX_PARALLAX = "_parallax"

KNOWN_SUFFIXES = (SUFFIX_GLOSS_MAP, SUFFIX_MASK, SUFFIX_NORMAL, SUFFIX_PARALLAX)


def classify(stem: str) -> str:
    for suffix in KNOWN_SUFFIXES:
        if stem.endswith(suffix):
            return suffix
    return ""


def gloss_map_outputs(pixels: np.ndarray) -> dict[str, np.ndarray]:
    # 1.4: gloss_map.R = gloss, gloss_map.G = level, both greyscale.
    return {"_gloss": pixels[..., 0], "_level": pixels[..., 1]}


def mask_outputs(pixels: np.ndarray) -> dict[str, np.ndarray]:
    # 1.5: mask.R/G/B = mask1/2/3, order corroborated but not yet ground-truthed against BOB.
    return {"_mask1": pixels[..., 0], "_mask2": pixels[..., 1], "_mask3": pixels[..., 2]}


def normal_output(pixels: np.ndarray, reconstruct_z: bool = False) -> np.ndarray:
    # 1.3: compiled.R=255 constant, compiled.G=source.G, compiled.B=0 constant, compiled.A=source.R
    # (the DXT5n convention). Undoing it: raw.R=compiled.A, raw.G=compiled.G. The source blue
    # channel is destroyed by compilation; fill 255 matches what most of the real corpus contains,
    # reconstructing Z from R/G is the higher-fidelity alternative.
    x = pixels[..., 3]
    y = pixels[..., 1]
    if reconstruct_z:
        nx = x.astype(np.float32) / 127.5 - 1.0
        ny = y.astype(np.float32) / 127.5 - 1.0
        nz = np.sqrt(np.clip(1.0 - nx * nx - ny * ny, 0.0, 1.0))
        b = np.clip(np.round(nz * 255.0), 0, 255).astype(np.uint8)
    else:
        b = np.full_like(x, 255)
    return np.stack([x, y, b], axis=-1)


def parallax_output(pixels: np.ndarray) -> np.ndarray:
    # 2.1 / 1.6: BOB's own help text for ParallaxMap - "A->B, R->A, 255->R" - one asset in the
    # corpus, no matched source to measure against. raw.R=compiled.A, raw.G=compiled.G (unshuffled),
    # raw.B=compiled.B.
    return np.stack([pixels[..., 3], pixels[..., 1], pixels[..., 2]], axis=-1)


def has_real_alpha(pixels: np.ndarray) -> bool:
    return pixels.ndim == 3 and pixels.shape[-1] == 4 and not bool(np.all(pixels[..., 3] == 255))


# The raw-side suffixes a BOB combiner action reads (1.4, 1.5) - the compile direction's mirror of
# SUFFIX_GLOSS_MAP/SUFFIX_MASK above, which instead name the *compiled* output.
RAW_GLOSS_MAP_SUFFIXES = ("_gloss", "_level")
RAW_MASK_SUFFIXES = ("_mask1", "_mask2", "_mask3")


def combiner_group(stem: str) -> tuple[str, tuple[str, ...]] | None:
    # 3.3: selecting one half of a combiner pulls in the rest - BOB errors with
    # "Couldn't find <base>_mask1.tga!" when a member is missing, so the compile operator resolves
    # the full group itself rather than handing BOB a partial one.
    for suffix in RAW_GLOSS_MAP_SUFFIXES:
        if stem.endswith(suffix):
            return stem[: -len(suffix)], RAW_GLOSS_MAP_SUFFIXES
    for suffix in RAW_MASK_SUFFIXES:
        if stem.endswith(suffix):
            return stem[: -len(suffix)], RAW_MASK_SUFFIXES
    return None
