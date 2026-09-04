import math
import os
import struct

import bpy
import numpy as np

TW_ENVIRONMENT_MARKER = "tw_environment_map"

ENVIRONMENT_CUBEMAP = "test_cubemap.dds"
AMBIENT_CUBEMAP = "test_cubemap_blurry.dds"

# s_environment_map is sampled at texCUBElod(..., roughness * (texture_num_lods - 1)) with
# texture_num_lods = 10, and test_cubemap.dds really does carry 10 mips. Blender has no per-sample
# LOD control, so four rungs of that chain are converted separately and blended by the same
# roughness, which is what the hardware mip lookup interpolates between anyway.
ENVIRONMENT_MIP_LADDER = (0, 3, 6, 9)

_FALLBACK_GREY = 0.5


def _dds_cube_face(raw: bytes, mip: int) -> np.ndarray:
    _, _, height, width, _, _, mip_count = struct.unpack_from("<7I", raw, 4)
    bits_per_pixel = struct.unpack_from("<I", raw, 88)[0]
    if bits_per_pixel != 32 or struct.unpack_from("<I", raw, 84)[0] != 0:
        raise ValueError("expected an uncompressed 32-bit DDS")

    sizes = []
    w, h = width, height
    for _ in range(max(mip_count, 1)):
        sizes.append((w, h))
        w, h = max(1, w // 2), max(1, h // 2)
    if mip >= len(sizes):
        mip = len(sizes) - 1

    face_stride = sum(w * h * 4 for w, h in sizes)
    mip_offset = sum(w * h * 4 for w, h in sizes[:mip])
    mip_w, mip_h = sizes[mip]

    faces = np.empty((6, mip_h, mip_w, 4), dtype=np.float32)
    for face in range(6):
        start = 128 + face * face_stride + mip_offset
        block = np.frombuffer(raw, dtype=np.uint8, count=mip_w * mip_h * 4, offset=start)
        # A8R8G8B8 little-endian puts the bytes down as B, G, R, A.
        bgra = block.reshape(mip_h, mip_w, 4)
        faces[face, ..., 0] = bgra[..., 2]
        faces[face, ..., 1] = bgra[..., 1]
        faces[face, ..., 2] = bgra[..., 0]
        faces[face, ..., 3] = bgra[..., 3]
    return faces / 255.0


def _equirectangular_directions(width: int, height: int):
    # Blender's environment texture lookup is u = -atan2(y, x) / 2pi + 0.5 and
    # v = atan2(z, hypot(x, y)) / pi + 0.5, so this inverts it. Row 0 is the bottom of the image,
    # matching how Blender stores pixels.
    u = (np.arange(width, dtype=np.float32) + 0.5) / width
    v = (np.arange(height, dtype=np.float32) + 0.5) / height
    phi = (0.5 - u)[None, :] * (2.0 * math.pi)
    theta = (v - 0.5)[:, None] * math.pi
    radius = np.cos(theta)
    return radius * np.cos(phi), radius * np.sin(phi), np.broadcast_to(np.sin(theta), (height, width))


def _sample_cube(faces: np.ndarray, x, y, z) -> np.ndarray:
    size = faces.shape[1]
    ax, ay, az = np.abs(x), np.abs(y), np.abs(z)
    out = np.zeros(x.shape + (4,), dtype=np.float32)

    major_x = (ax >= ay) & (ax >= az)
    major_y = (~major_x) & (ay >= az)
    major_z = (~major_x) & (~major_y)

    # Standard cube face parameterisation: face index, then (sc, tc, ma) per face.
    selections = (
        (0, major_x & (x > 0), -z, -y, ax),
        (1, major_x & (x <= 0), z, -y, ax),
        (2, major_y & (y > 0), x, z, ay),
        (3, major_y & (y <= 0), x, -z, ay),
        (4, major_z & (z > 0), x, -y, az),
        (5, major_z & (z <= 0), -x, -y, az),
    )
    for face, mask, sc, tc, ma in selections:
        if not mask.any():
            continue
        safe = np.where(ma == 0.0, 1.0, ma)
        s = 0.5 * (np.asarray(sc, dtype=np.float32) / safe + 1.0)
        t = 0.5 * (np.asarray(tc, dtype=np.float32) / safe + 1.0)
        col = np.clip((s * size).astype(np.int32), 0, size - 1)
        # Cube face rows run top-down, unlike Blender's bottom-up image rows.
        row = np.clip((t * size).astype(np.int32), 0, size - 1)
        out[mask] = faces[face][row[mask], col[mask]]
    return out


def _cube_to_equirectangular(faces: np.ndarray) -> tuple[int, int, np.ndarray]:
    size = faces.shape[1]
    width = max(size * 2, 8)
    height = max(size, 4)
    x, y, z = _equirectangular_directions(width, height)
    return width, height, _sample_cube(faces, x, y, np.asarray(z, dtype=np.float32))


def _store_image(name: str, width: int, height: int, pixels: np.ndarray) -> bpy.types.Image:
    existing = bpy.data.images.get(name)
    if existing is not None:
        bpy.data.images.remove(existing)
    image = bpy.data.images.new(name, width=width, height=height, alpha=True)
    # Both cubemap samplers declare SRGBTexture = FALSE, so the stored values are already linear.
    # Colorspace has to be set before the pixels, or assigning it discards them.
    image.colorspace_settings.name = "Non-Color"
    image.pixels.foreach_set(np.ascontiguousarray(pixels, dtype=np.float32).ravel())
    image[TW_ENVIRONMENT_MARKER] = True
    return image


def _fallback_image(name: str) -> bpy.types.Image:
    existing = bpy.data.images.get(name)
    if existing is not None and existing.get(TW_ENVIRONMENT_MARKER):
        return existing
    pixels = np.full((4, 4, 4), _FALLBACK_GREY, dtype=np.float32)
    pixels[..., 3] = 1.0
    return _store_image(name, 4, 4, pixels)


def _shader_folder(assembly_kit_root: str) -> str:
    return os.path.join(assembly_kit_root, "max_exporter", "max_shader")


def _convert(name: str, path: str, mip: int) -> bpy.types.Image | None:
    try:
        with open(path, "rb") as handle:
            raw = handle.read()
        width, height, pixels = _cube_to_equirectangular(_dds_cube_face(raw, mip))
    except Exception:
        return None
    return _store_image(name, width, height, pixels)


def image_name(slot: str, mip: int = 0) -> str:
    return f"TW_Environment_{slot}" if mip == 0 else f"TW_Environment_{slot}_lod{mip}"


def ensure_environment_images(assembly_kit_root: str = "") -> dict[str, bpy.types.Image]:
    wanted = [("Ambient", AMBIENT_CUBEMAP, 0)] + [
        ("Reflection", ENVIRONMENT_CUBEMAP, mip) for mip in ENVIRONMENT_MIP_LADDER
    ]
    folder = _shader_folder(assembly_kit_root) if assembly_kit_root else ""

    images: dict[str, bpy.types.Image] = {}
    for slot, filename, mip in wanted:
        name = image_name(slot, mip)
        existing = bpy.data.images.get(name)
        if existing is not None and existing.get(TW_ENVIRONMENT_MARKER):
            images[name] = existing
            continue
        converted = _convert(name, os.path.join(folder, filename), mip) if folder else None
        images[name] = converted if converted is not None else _fallback_image(name)
    return images
