import struct
from pathlib import Path

import numpy as np

_HEADER = struct.Struct("<BBBHHBHHHHBB")
_ATTRIBUTE_BITS_32BIT = 0x08


def write_tga(path, pixels: np.ndarray) -> None:
    # PLAN_textures.md 1.7: matches what CA authored - type 3 8-bit for a single channel, type 2
    # 24-bit for opaque colour, type 2 32-bit only when alpha carries real data. Bottom-left origin,
    # no RLE, no ID field, no colour map - pixels[0] here is the top row (dds.py's own convention),
    # so the row order is flipped to land the bottom row first in the file.
    pixels = np.asarray(pixels)
    if pixels.ndim == 2:
        height, width = pixels.shape
        channels = 1
    elif pixels.ndim == 3:
        height, width, channels = pixels.shape
    else:
        raise ValueError(f"expected a (h, w) or (h, w, c) array, got shape {pixels.shape}")

    if channels == 1:
        image_type, bpp, descriptor = 3, 8, 0x00
        data = np.flipud(pixels)
    elif channels == 3:
        image_type, bpp, descriptor = 2, 24, 0x00
        data = np.flipud(pixels)[..., [2, 1, 0]]
    elif channels == 4:
        image_type, bpp, descriptor = 2, 32, _ATTRIBUTE_BITS_32BIT
        flipped = np.flipud(pixels)
        data = np.concatenate([flipped[..., [2, 1, 0]], flipped[..., 3:4]], axis=-1)
    else:
        raise ValueError(f"unsupported channel count: {channels}")

    header = _HEADER.pack(0, 0, image_type, 0, 0, 0, 0, 0, width, height, bpp, descriptor)
    Path(path).write_bytes(header + np.ascontiguousarray(data, dtype=np.uint8).tobytes())


def read_tga(path) -> np.ndarray:
    # Counterpart reader, used only by scripts/validate_texture_roundtrip.py to load the real
    # raw_data .tga ground truth - not exposed to the add-on's operators, which only ever write.
    data = Path(path).read_bytes()
    id_length = data[0]
    color_map_type = data[1]
    image_type = data[2]
    color_map_first_entry, color_map_length = struct.unpack_from("<HH", data, 3)
    color_map_entry_size = data[7]
    width, height = struct.unpack_from("<HH", data, 12)
    bpp = data[16]
    descriptor = data[17]
    offset = 18 + id_length

    palette = None
    if color_map_type == 1:
        entry_bytes = color_map_entry_size // 8
        palette_size = color_map_length * entry_bytes
        palette = np.frombuffer(data, dtype=np.uint8, count=palette_size, offset=offset).reshape(
            color_map_length, entry_bytes
        )
        offset += palette_size

    pixel_bytes = bpp // 8
    raw = np.frombuffer(data, dtype=np.uint8, count=width * height * pixel_bytes, offset=offset).reshape(
        height, width, pixel_bytes
    )

    if image_type == 1 and palette is not None:
        indices = np.clip(raw[..., 0].astype(np.int32) - color_map_first_entry, 0, palette.shape[0] - 1)
        looked_up = palette[indices]
        if looked_up.shape[-1] >= 3 and np.array_equal(looked_up[..., 0], looked_up[..., 1]) and np.array_equal(
            looked_up[..., 1], looked_up[..., 2]
        ):
            # A grey ramp stored as a colour map - the real corpus does this for single-channel
            # gloss/level files (PLAN_textures.md 1.7) - collapses to one plane like a type 3 file.
            pixels = looked_up[..., 0]
        elif looked_up.shape[-1] >= 3:
            pixels = looked_up[..., [2, 1, 0]]
        else:
            pixels = looked_up[..., 0]
    elif image_type == 3:
        pixels = raw[..., 0]
    elif image_type == 2 and pixel_bytes == 4:
        pixels = raw[..., [2, 1, 0, 3]]
    elif image_type == 2 and pixel_bytes == 3:
        pixels = raw[..., [2, 1, 0]]
    else:
        raise ValueError(f"unsupported TGA image type {image_type} at {bpp}-bit")

    if not (descriptor & 0x20):
        pixels = np.flipud(pixels)
    return np.ascontiguousarray(pixels)
