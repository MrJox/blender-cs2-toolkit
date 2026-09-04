import struct


class BinaryWriter:
    def __init__(self) -> None:
        self.buffer = bytearray()

    def u16(self, value: int) -> None:
        self.buffer += struct.pack("<H", value)

    def u32(self, value: int) -> None:
        self.buffer += struct.pack("<I", value)

    def u64(self, value: int) -> None:
        self.buffer += struct.pack("<Q", value)

    def i32(self, value: int) -> None:
        self.buffer += struct.pack("<i", value)

    def f32(self, value: float) -> None:
        self.buffer += struct.pack("<f", value)

    def raw(self, data: bytes) -> None:
        self.buffer += data

    def fixed_bytes(self, data: bytes, length: int) -> None:
        if len(data) > length:
            raise ValueError(f"fixed_bytes: {len(data)} bytes does not fit in {length}")
        self.buffer += data + b"\x00" * (length - len(data))

    def utf16_string(self, value: str) -> None:
        encoded = value.encode("utf-16-le")
        char_count = len(encoded) // 2
        self.u16(char_count)
        self.buffer += encoded

    def vec3(self, xyz: tuple[float, float, float]) -> None:
        self.f32(xyz[0])
        self.f32(xyz[1])
        self.f32(xyz[2])

    def vec4(self, xyzw: tuple[float, float, float, float]) -> None:
        self.f32(xyzw[0])
        self.f32(xyzw[1])
        self.f32(xyzw[2])
        self.f32(xyzw[3])

    def bounding_box(self, min_xyz: tuple[float, float, float], max_xyz: tuple[float, float, float]) -> None:
        self.vec3(min_xyz)
        self.vec3(max_xyz)

    def float_array(self, values: list[float]) -> None:
        self.u32(len(values))
        for value in values:
            self.f32(value)

    def int_array(self, values: list[int]) -> None:
        self.u32(len(values))
        for value in values:
            self.i32(value)

    def bytes(self) -> bytes:
        return bytes(self.buffer)

    def __len__(self) -> int:
        return len(self.buffer)
