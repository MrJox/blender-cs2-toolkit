import os
import xml.etree.ElementTree as ET
from pathlib import Path

# Fallback pyramid geometry matching arrow_emitter_proxy.DAE (5 vertices, 6 faces)
_FALLBACK_VERTICES: list[tuple[float, float, float]] = [
    (-0.301669, -0.29518, 0.0),
    (0.301669, -0.29518, 0.0),
    (-0.301669, 0.29518, 0.0),
    (0.301669, 0.29518, 0.0),
    (0.0, 0.0, 0.1038),
]

_FALLBACK_TRIANGLES: list[tuple[int, int, int]] = [
    (1, 0, 3),
    (0, 2, 3),
    (0, 1, 4),
    (1, 3, 4),
    (3, 2, 4),
    (2, 0, 4),
]

_cached_proxy: tuple[list[tuple[float, float, float]], list[tuple[int, int, int]]] | None = None

# The flag node's own geometry, read out of both real samples that have one and converted from the
# CS2 file's engine (Y-up) space to Blender's Z-up: a 0.5 x 0.5 x 1.0 box standing on the object
# origin. Both samples carry this identical local shape and differ only in the node's transform.
FLAG_VERTICES: list[tuple[float, float, float]] = [
    (-0.25, -0.25, 0.0),
    (0.25, -0.25, 0.0),
    (0.25, 0.25, 0.0),
    (-0.25, 0.25, 0.0),
    (-0.25, -0.25, 1.0),
    (0.25, -0.25, 1.0),
    (0.25, 0.25, 1.0),
    (-0.25, 0.25, 1.0),
]

FLAG_FACES: list[tuple[int, int, int, int]] = [
    (0, 3, 2, 1),
    (4, 5, 6, 7),
    (0, 1, 5, 4),
    (1, 2, 6, 5),
    (2, 3, 7, 6),
    (3, 0, 4, 7),
]


def load_dae_proxy(filepath: str) -> tuple[list[tuple[float, float, float]], list[tuple[int, int, int]]] | None:
    if not os.path.exists(filepath):
        return None
    try:
        tree = ET.parse(filepath)
        root = tree.getroot()

        unit_elem = root.find('.//{http://www.collada.org/2005/11/COLLADASchema}unit')
        scale = float(unit_elem.attrib.get('meter', 1.0)) if unit_elem is not None else 1.0

        pos_elem = root.find('.//{http://www.collada.org/2005/11/COLLADASchema}float_array')
        if pos_elem is None or not pos_elem.text:
            return None
        positions = [float(x) for x in pos_elem.text.split()]

        tri_elem = root.find('.//{http://www.collada.org/2005/11/COLLADASchema}triangles')
        if tri_elem is None:
            tri_elem = root.find('.//{http://www.collada.org/2005/11/COLLADASchema}polylist')
        if tri_elem is None:
            return None

        inputs = tri_elem.findall('{http://www.collada.org/2005/11/COLLADASchema}input')
        stride = len(inputs) if inputs else 1
        pos_offset = 0
        for inp in inputs:
            if inp.attrib.get('semantic') == 'POSITION':
                pos_offset = int(inp.attrib.get('offset', 0))

        p_elem = tri_elem.find('{http://www.collada.org/2005/11/COLLADASchema}p')
        if p_elem is None or not p_elem.text:
            return None
        raw_indices = [int(x) for x in p_elem.text.split()]

        pos_indices = [raw_indices[i + pos_offset] for i in range(0, len(raw_indices), stride)]

        verts = []
        for i in range(0, len(positions), 3):
            x, y, z = positions[i] * scale, positions[i + 1] * scale, positions[i + 2] * scale
            verts.append((round(x, 6), round(y, 6), round(z, 6)))

        unique_verts: list[tuple[float, float, float]] = []
        vert_map: dict[int, int] = {}
        for i, v in enumerate(verts):
            if v not in unique_verts:
                vert_map[i] = len(unique_verts)
                unique_verts.append(v)
            else:
                vert_map[i] = unique_verts.index(v)

        triangles: list[tuple[int, int, int]] = []
        for i in range(0, len(pos_indices), 3):
            t = (vert_map[pos_indices[i]], vert_map[pos_indices[i + 1]], vert_map[pos_indices[i + 2]])
            triangles.append(t)

        return unique_verts, triangles
    except Exception:
        return None


def get_arrow_emitter_proxy_geometry() -> tuple[list[tuple[float, float, float]], list[tuple[int, int, int]]]:
    global _cached_proxy
    if _cached_proxy is not None:
        return _cached_proxy

    possible_paths = [
        Path(__file__).resolve().parent.parent.parent / "Input/examples/proxies/arrow_emitter_proxy.DAE",
        Path(__file__).resolve().parent.parent / "proxies/arrow_emitter_proxy.DAE",
    ]

    for path in possible_paths:
        res = load_dae_proxy(str(path))
        if res is not None:
            _cached_proxy = res
            return _cached_proxy

    _cached_proxy = (_FALLBACK_VERTICES, _FALLBACK_TRIANGLES)
    return _cached_proxy
