import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scene_model.models import BuildingAsset, Piece, DestructLevel, LodMesh, MaterialDef, MeshData, MeshVertex, MeshTriangle
from scene_model.cs2_builder import build_cs2_document
from binary.cs2_writer import write_cs2
from binary.cs2_reader import read_cs2

ASSEMBLY_KIT_ROOT = r"D:\SteamLibrary\steamapps\common\Total War Attila\assembly_kit"


def make_box_mesh() -> MeshData:
    positions = [
        (-1, -1, -1), (1, -1, -1), (1, 1, -1), (-1, 1, -1),
        (-1, -1, 1), (1, -1, 1), (1, 1, 1), (-1, 1, 1),
    ]
    vertices = [MeshVertex(position=p, normal=(0.0, 0.0, 1.0), uv=(0.0, 0.0)) for p in positions]
    faces = [
        (0, 1, 2), (0, 2, 3),
        (4, 6, 5), (4, 7, 6),
        (0, 4, 5), (0, 5, 1),
        (1, 5, 6), (1, 6, 2),
        (2, 6, 7), (2, 7, 3),
        (3, 7, 4), (3, 4, 0),
    ]
    triangles = [MeshTriangle(indices=f) for f in faces]
    return MeshData(vertices=vertices, triangles=triangles)


def main() -> None:
    material = MaterialDef(name="TestBoxMaterial", shader_type="default")
    lod = LodMesh(lod_index=1, mesh=make_box_mesh(), material=material)
    destruct = DestructLevel(destruct_index=1, lod_meshes=[lod], collision_mesh=None)
    piece = Piece(piece_index=1, destruct_levels=[destruct])
    building = BuildingAsset(name="test_box", asset_type="display_building", pieces=[piece])

    out_path = Path(__file__).resolve().parent / "test_box.CS2"
    doc = build_cs2_document(building, ASSEMBLY_KIT_ROOT, output_path=str(out_path))
    data = write_cs2(doc)
    print("Wrote", len(data), "bytes")

    reparsed = read_cs2(data)
    print("Re-parsed OK:", reparsed.scene_block.rigid_models_count, "rigid,", reparsed.scene_block.materials_count, "materials")

    out_path.write_bytes(data)
    print("Wrote", out_path)


if __name__ == "__main__":
    main()
