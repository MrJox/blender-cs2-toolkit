import copy
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from binary.cs2_reader import read_cs2
from binary.cs2_writer import write_cs2
from binary import cs2_structures as s
from materials.template import build_directx_material_node
from naming.naming import lod_attributes, collision_attributes

SAMPLE_PATH = Path(__file__).resolve().parent.parent.parent / "Input/examples/raw_data/gondor_building_5/gondor_building_5.CS2"
OUT_DIR = Path(__file__).resolve().parent
ASSEMBLY_KIT_ROOT = r"D:\SteamLibrary\steamapps\common\Total War Attila\assembly_kit"


def make_our_cube_geometry_chunk(include_uv: bool, material_id: int) -> s.RigidGeometryChunk:
    positions = [
        (-1, -1, -1), (1, -1, -1), (1, 1, -1), (-1, 1, -1),
        (-1, -1, 1), (1, -1, 1), (1, 1, 1), (-1, 1, 1),
    ]
    faces = [
        (0, 1, 2), (0, 2, 3), (4, 6, 5), (4, 7, 6),
        (0, 4, 5), (0, 5, 1), (1, 5, 6), (1, 6, 2),
        (2, 6, 7), (2, 7, 3), (3, 7, 4), (3, 4, 0),
    ]
    vertices = []
    triangles = []
    for face in faces:
        idxs = []
        for vi in face:
            p = positions[vi]
            vertices.append(
                s.RigidVertex(
                    position=p,
                    normal=(0.0, 0.0, 1.0),
                    color=(1.0, 1.0, 1.0, 1.0),
                    tex_coords=[(0.0, 0.0, 0.0)] if include_uv else [],
                    vertex_ao_or_morph_weight=0.0,
                )
            )
            idxs.append(len(vertices) - 1)
        triangles.append(tuple(idxs))

    return s.RigidGeometryChunk(
        header_padding=b"\x0b\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00",
        bounding_box_extent_floats=[0.0],
        bounding_boxes=[((1.0, 1.0, 1.0), (-1.0, -1.0, -1.0))],
        lines=[],
        uvw_channel_ids=[1] if include_uv else [],
        vertices=vertices,
        submeshes=[s.SubMesh(triangles=triangles, material_id=material_id)],
        vertex_color_channel_flags=3,
    )


def save(doc: s.CS2Document, name: str) -> None:
    data = write_cs2(doc)
    out_path = OUT_DIR / name
    out_path.write_bytes(data)
    reread = read_cs2(data)
    print(f"{name}: wrote {len(data)} bytes, self-reparse OK ({reread.scene_block.rigid_models_count} rigid, {reread.scene_block.materials_count} materials)")


def variant_geometry_swap(base: s.CS2Document) -> s.CS2Document:
    doc = copy.deepcopy(base)
    for rm in doc.rigid_models:
        is_collision = "collision3d" in rm.node_name
        include_uv = True
        material_id = -1 if is_collision else rm.geometry_chunks[0].submeshes[0].material_id
        rm.geometry_chunks = [make_our_cube_geometry_chunk(include_uv, material_id)]
    return doc


def variant_material_swap(base: s.CS2Document) -> s.CS2Document:
    doc = copy.deepcopy(base)
    doc.materials = [
        build_directx_material_node(
            node_name="OurMaterial",
            material_name="OurMaterial",
            rigid_material="default",
            assembly_kit_root=ASSEMBLY_KIT_ROOT,
        )
    ]
    doc.scene_block.materials_count = len(doc.materials)
    for rm in doc.rigid_models:
        if "collision3d" not in rm.node_name:
            for chunk in rm.geometry_chunks:
                for sm in chunk.submeshes:
                    sm.material_id = 0
    return doc


def variant_attributes_swap(base: s.CS2Document) -> s.CS2Document:
    doc = copy.deepcopy(base)
    for rm in doc.rigid_models:
        if "collision3d" in rm.node_name:
            rm.attributes = collision_attributes(1, 1, "gondor_building_5")
        else:
            rm.attributes = lod_attributes(1, 1, 1, "gondor_building_5")
    return doc


def main() -> None:
    base = read_cs2(SAMPLE_PATH.read_bytes())

    save(base, "bisect_00_baseline_copy.CS2")
    save(variant_geometry_swap(base), "bisect_01_our_geometry.CS2")
    save(variant_material_swap(base), "bisect_02_our_material.CS2")
    save(variant_attributes_swap(base), "bisect_03_our_attributes.CS2")


if __name__ == "__main__":
    main()
