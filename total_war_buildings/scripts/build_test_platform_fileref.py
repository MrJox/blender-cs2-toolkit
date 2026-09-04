import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scene_model.models import (
    BuildingAsset,
    Piece,
    DestructLevel,
    LodMesh,
    CollisionMesh,
    PlatformMesh,
    FileReference,
    MaterialDef,
    MeshData,
    MeshVertex,
    MeshTriangle,
)
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
        (0, 1, 2), (0, 2, 3), (4, 6, 5), (4, 7, 6),
        (0, 4, 5), (0, 5, 1), (1, 5, 6), (1, 6, 2),
        (2, 6, 7), (2, 7, 3), (3, 7, 4), (3, 4, 0),
    ]
    return MeshData(vertices=vertices, triangles=[MeshTriangle(indices=f) for f in faces])


def make_quad_mesh() -> MeshData:
    positions = [(-1, -1, 0), (1, -1, 0), (1, 1, 0), (-1, 1, 0)]
    vertices = [MeshVertex(position=p, normal=(0.0, 0.0, 1.0), uv=(0.0, 0.0)) for p in positions]
    faces = [(0, 1, 2), (0, 2, 3)]
    return MeshData(vertices=vertices, triangles=[MeshTriangle(indices=f) for f in faces])


def main() -> None:
    material = MaterialDef(name="TestMaterial", shader_type="default")
    lod = LodMesh(lod_index=1, mesh=make_box_mesh(), material=material)
    collision = CollisionMesh(mesh=make_box_mesh())
    platform = PlatformMesh(variation_index=1, mesh=make_quad_mesh())
    file_ref = FileReference(reference_name="torch_sconce", mesh=make_box_mesh(), material=material)

    destruct = DestructLevel(
        destruct_index=1,
        lod_meshes=[lod],
        collision_mesh=collision,
        platform_meshes=[platform],
        file_references=[file_ref],
    )
    piece = Piece(piece_index=1, destruct_levels=[destruct])
    building = BuildingAsset(name="PlatformFileRefTest", asset_type="display_building", pieces=[piece])

    out_path = Path(__file__).resolve().parent / "PlatformFileRefTest.CS2"
    doc = build_cs2_document(building, ASSEMBLY_KIT_ROOT, output_path=str(out_path))
    data = write_cs2(doc)
    print("Wrote", len(data), "bytes")

    reparsed = read_cs2(data)
    print("Re-parsed OK:", reparsed.scene_block.rigid_models_count, "rigid,", reparsed.scene_block.materials_count, "materials")
    for rm in reparsed.rigid_models:
        matids = [sm.material_id for sm in rm.geometry_chunks[0].submeshes]
        rigid_object = next((a.value for a in rm.attributes.strings if a.name == "rigid_OBJECT"), None)
        print(" ", rm.node_name, "matids:", matids, "rigid_OBJECT:", repr(rigid_object))

    out_path.write_bytes(data)
    print("Wrote", out_path)


if __name__ == "__main__":
    main()
