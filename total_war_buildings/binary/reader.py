import struct


class BinaryReader:
    def __init__(self, data: bytes) -> None:
        self.data = data
        self.offset = 0

    def u8(self) -> int:
        value = self.data[self.offset]
        self.offset += 1
        return value

    def i16(self) -> int:
        value = struct.unpack_from("<h", self.data, self.offset)[0]
        self.offset += 2
        return value

    def f16(self) -> float:
        value = struct.unpack_from("<e", self.data, self.offset)[0]
        self.offset += 2
        return value

    def u16(self) -> int:
        value = struct.unpack_from("<H", self.data, self.offset)[0]
        self.offset += 2
        return value

    def u32(self) -> int:
        value = struct.unpack_from("<I", self.data, self.offset)[0]
        self.offset += 4
        return value

    def u64(self) -> int:
        value = struct.unpack_from("<Q", self.data, self.offset)[0]
        self.offset += 8
        return value

    def i32(self) -> int:
        value = struct.unpack_from("<i", self.data, self.offset)[0]
        self.offset += 4
        return value

    def f32(self) -> float:
        value = struct.unpack_from("<f", self.data, self.offset)[0]
        self.offset += 4
        return value

    def raw(self, length: int) -> bytes:
        value = self.data[self.offset : self.offset + length]
        self.offset += length
        return value

    def fixed_string(self, length: int) -> str:
        return self.raw(length).split(b"\x00", 1)[0].decode("latin-1")

    def length_prefixed_ascii(self) -> str:
        return self.raw(self.i16()).decode("latin-1")

    def utf16_string(self) -> str:
        char_count = self.u16()
        if char_count == 0:
            return ""
        value = self.raw(char_count * 2).decode("utf-16-le")
        return value

    def vec3(self) -> tuple[float, float, float]:
        return (self.f32(), self.f32(), self.f32())

    def vec4(self) -> tuple[float, float, float, float]:
        return (self.f32(), self.f32(), self.f32(), self.f32())

    def bounding_box(self) -> tuple[tuple[float, float, float], tuple[float, float, float]]:
        return (self.vec3(), self.vec3())

    def float_array(self) -> list[float]:
        count = self.u32()
        return [self.f32() for _ in range(count)]

    def int_array(self) -> list[int]:
        count = self.u32()
        return [self.i32() for _ in range(count)]

    def at_end(self) -> bool:
        return self.offset >= len(self.data)

    def remaining(self) -> int:
        return len(self.data) - self.offset
