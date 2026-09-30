import struct

import numpy as np

MAGIC = b"DDS "
_HEADER_SIZE = 128
_PF_FOURCC = 0x4
_CAPS2_CUBEMAP = 0x200

_UNSUPPORTED_FOURCC = {
    b"ATI1": "BC4 (ATI1)",
    b"ATI2": "BC5 (ATI2)",
    b"BC4U": "BC4",
    b"BC4S": "BC4",
    b"BC5U": "BC5",
    b"BC5S": "BC5",
}


def decode_dds(data: bytes) -> np.ndarray:
    # PLAN_textures.md 1.8: the corpus is DXT1/DXT3/DXT5/uncompressed 32-bit BGRA only, mip 0, no
    # DX10 header, no cube or volume flags - anything else raises rather than guessing.
    if len(data) < _HEADER_SIZE or data[:4] != MAGIC:
        raise ValueError("not a DDS file")

    height, width = struct.unpack_from("<II", data, 12)
    pf_flags = struct.unpack_from("<I", data, 80)[0]
    fourcc = bytes(data[84:88])
    rgb_bit_count = struct.unpack_from("<I", data, 88)[0]
    caps2 = struct.unpack_from("<I", data, 112)[0]

    if caps2 & _CAPS2_CUBEMAP:
        raise ValueError("cubemap DDS files are not supported")
    if fourcc == b"DX10":
        raise ValueError("DX10-header DDS files (e.g. BC7) are not supported")

    if pf_flags & _PF_FOURCC:
        if fourcc == b"DXT1":
            return _decode_bc1(data, _HEADER_SIZE, width, height)
        if fourcc == b"DXT3":
            return _decode_bc23(data, _HEADER_SIZE, width, height, explicit_alpha=True)
        if fourcc == b"DXT5":
            return _decode_bc23(data, _HEADER_SIZE, width, height, explicit_alpha=False)
        if fourcc in _UNSUPPORTED_FOURCC:
            raise ValueError(f"{_UNSUPPORTED_FOURCC[fourcc]} compressed DDS files are not supported")
        raise ValueError(f"unsupported DDS FourCC: {fourcc!r}")

    if rgb_bit_count == 32:
        return _decode_bgra32(data, _HEADER_SIZE, width, height)
    raise ValueError(f"unsupported uncompressed DDS pixel format ({rgb_bit_count}-bit)")


def _decode_bgra32(data: bytes, offset: int, width: int, height: int) -> np.ndarray:
    count = width * height * 4
    raw = np.frombuffer(data, dtype=np.uint8, count=count, offset=offset).reshape(height, width, 4)
    out = np.empty_like(raw)
    out[..., 0] = raw[..., 2]
    out[..., 1] = raw[..., 1]
    out[..., 2] = raw[..., 0]
    out[..., 3] = raw[..., 3]
    return out


def _rgb565_to_888(c: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    c = c.astype(np.uint32)
    r5 = (c >> 11) & 0x1F
    g6 = (c >> 5) & 0x3F
    b5 = c & 0x1F
    r = ((r5 << 3) | (r5 >> 2)).astype(np.uint8)
    g = ((g6 << 2) | (g6 >> 4)).astype(np.uint8)
    b = ((b5 << 3) | (b5 >> 2)).astype(np.uint8)
    return r, g, b


def _block_grid(width: int, height: int) -> tuple[int, int]:
    return (width + 3) // 4, (height + 3) // 4


def _assemble(blocks: np.ndarray, bw: int, bh: int, width: int, height: int) -> np.ndarray:
    # blocks is (bw*bh, 4, 4) in row-major block order; DXT block texels are also row-major within
    # the block, so a straight reshape + transpose lays every block back into its place.
    full = blocks.reshape(bh, bw, 4, 4).transpose(0, 2, 1, 3).reshape(bh * 4, bw * 4)
    return full[:height, :width]


def _lerp_2_1(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    return ((2 * a.astype(np.int32) + b.astype(np.int32) + 1) // 3).astype(np.uint8)


def _mid(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    return ((a.astype(np.int32) + b.astype(np.int32) + 1) // 2).astype(np.uint8)


def _select_indices(n: int, raw_indices: np.ndarray, bits_per_index: int) -> np.ndarray:
    shifts = np.arange(16, dtype=raw_indices.dtype) * bits_per_index
    mask = (1 << bits_per_index) - 1
    return ((raw_indices[:, None] >> shifts[None, :]) & mask).astype(np.intp)


def _color_block_rgb(color0: np.ndarray, color1: np.ndarray, four_color: np.ndarray):
    r0, g0, b0 = _rgb565_to_888(color0)
    r1, g1, b1 = _rgb565_to_888(color1)

    r2 = np.where(four_color, _lerp_2_1(r0, r1), _mid(r0, r1))
    g2 = np.where(four_color, _lerp_2_1(g0, g1), _mid(g0, g1))
    b2 = np.where(four_color, _lerp_2_1(b0, b1), _mid(b0, b1))
    r3 = np.where(four_color, _lerp_2_1(r1, r0), 0)
    g3 = np.where(four_color, _lerp_2_1(g1, g0), 0)
    b3 = np.where(four_color, _lerp_2_1(b1, b0), 0)

    palette_r = np.stack([r0, r1, r2, r3], axis=1)
    palette_g = np.stack([g0, g1, g2, g3], axis=1)
    palette_b = np.stack([b0, b1, b2, b3], axis=1)
    return palette_r, palette_g, palette_b


def _decode_bc1(data: bytes, offset: int, width: int, height: int) -> np.ndarray:
    bw, bh = _block_grid(width, height)
    n = bw * bh
    blocks = np.frombuffer(data, dtype=np.uint8, count=n * 8, offset=offset).reshape(n, 8)
    color0 = blocks[:, 0].astype(np.uint16) | (blocks[:, 1].astype(np.uint16) << 8)
    color1 = blocks[:, 2].astype(np.uint16) | (blocks[:, 3].astype(np.uint16) << 8)
    raw_indices = (
        blocks[:, 4].astype(np.uint32)
        | (blocks[:, 5].astype(np.uint32) << 8)
        | (blocks[:, 6].astype(np.uint32) << 16)
        | (blocks[:, 7].astype(np.uint32) << 24)
    )
    four_color = color0 > color1
    palette_r, palette_g, palette_b = _color_block_rgb(color0, color1, four_color)
    opaque = np.full(n, 255, dtype=np.uint8)
    a3 = np.where(four_color, 255, 0).astype(np.uint8)
    palette_a = np.stack([opaque, opaque, opaque, a3], axis=1)

    idx16 = _select_indices(n, raw_indices, 2)

    def select(palette: np.ndarray) -> np.ndarray:
        return np.take_along_axis(palette, idx16, axis=1).reshape(n, 4, 4)

    r_img = _assemble(select(palette_r), bw, bh, width, height)
    g_img = _assemble(select(palette_g), bw, bh, width, height)
    b_img = _assemble(select(palette_b), bw, bh, width, height)
    a_img = _assemble(select(palette_a), bw, bh, width, height)
    return np.stack([r_img, g_img, b_img, a_img], axis=-1)


def _decode_bc23(data: bytes, offset: int, width: int, height: int, explicit_alpha: bool) -> np.ndarray:
    bw, bh = _block_grid(width, height)
    n = bw * bh
    blocks = np.frombuffer(data, dtype=np.uint8, count=n * 16, offset=offset).reshape(n, 16)
    alpha_block = blocks[:, 0:8]
    color_block = blocks[:, 8:16]

    color0 = color_block[:, 0].astype(np.uint16) | (color_block[:, 1].astype(np.uint16) << 8)
    color1 = color_block[:, 2].astype(np.uint16) | (color_block[:, 3].astype(np.uint16) << 8)
    raw_indices = (
        color_block[:, 4].astype(np.uint32)
        | (color_block[:, 5].astype(np.uint32) << 8)
        | (color_block[:, 6].astype(np.uint32) << 16)
        | (color_block[:, 7].astype(np.uint32) << 24)
    )
    # BC2/BC3 colour blocks always interpolate as four colours - unlike BC1 there is no
    # punch-through-alpha mode to select between, since alpha comes from the block above.
    always_four = np.ones(n, dtype=bool)
    palette_r, palette_g, palette_b = _color_block_rgb(color0, color1, always_four)
    idx16 = _select_indices(n, raw_indices, 2)

    def select(palette: np.ndarray) -> np.ndarray:
        return np.take_along_axis(palette, idx16, axis=1).reshape(n, 4, 4)

    r_img = _assemble(select(palette_r), bw, bh, width, height)
    g_img = _assemble(select(palette_g), bw, bh, width, height)
    b_img = _assemble(select(palette_b), bw, bh, width, height)

    alpha16 = _decode_alpha_block(alpha_block, n, explicit_alpha)
    a_img = _assemble(alpha16.reshape(n, 4, 4), bw, bh, width, height)
    return np.stack([r_img, g_img, b_img, a_img], axis=-1)


def _decode_alpha_block(alpha_block: np.ndarray, n: int, explicit_alpha: bool) -> np.ndarray:
    if explicit_alpha:
        # BC2: sixteen 4-bit alpha values, low nibble of each byte is the even texel.
        nibble_lo = alpha_block & 0x0F
        nibble_hi = (alpha_block >> 4) & 0x0F
        alpha16 = np.empty((n, 16), dtype=np.uint8)
        alpha16[:, 0::2] = nibble_lo
        alpha16[:, 1::2] = nibble_hi
        return (alpha16.astype(np.uint16) * 17).astype(np.uint8)

    # BC3: two reference alphas, then sixteen 3-bit indices packed into 48 bits.
    alpha0 = alpha_block[:, 0]
    alpha1 = alpha_block[:, 1]
    index_bytes = alpha_block[:, 2:8].astype(np.uint64)
    bits = (
        index_bytes[:, 0]
        | (index_bytes[:, 1] << 8)
        | (index_bytes[:, 2] << 16)
        | (index_bytes[:, 3] << 24)
        | (index_bytes[:, 4] << 32)
        | (index_bytes[:, 5] << 40)
    )
    shifts = np.arange(16, dtype=np.uint64) * 3
    aidx = ((bits[:, None] >> shifts[None, :]) & 7).astype(np.intp)

    eight_mode = alpha0 > alpha1
    a0f = alpha0.astype(np.float32)
    a1f = alpha1.astype(np.float32)

    def step(wa: int, wb: int, denom: int) -> np.ndarray:
        return np.round((wa * a0f + wb * a1f) / denom).astype(np.uint8)

    pal8 = np.stack(
        [alpha0, alpha1, step(6, 1, 7), step(5, 2, 7), step(4, 3, 7), step(3, 4, 7), step(2, 5, 7), step(1, 6, 7)],
        axis=1,
    )
    pal6 = np.stack(
        [
            alpha0,
            alpha1,
            step(4, 1, 5),
            step(3, 2, 5),
            step(2, 3, 5),
            step(1, 4, 5),
            np.zeros(n, dtype=np.uint8),
            np.full(n, 255, dtype=np.uint8),
        ],
        axis=1,
    )
    palette_a = np.where(eight_mode[:, None], pal8, pal6)
    return np.take_along_axis(palette_a, aidx, axis=1)
