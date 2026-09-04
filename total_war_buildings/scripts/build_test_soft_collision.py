import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scene_model.models import (
    BuildingAsset,
    Piece,
    DestructLevel,
    LodMesh,
    CollisionMesh,
    SoftCollisionMesh,
    MaterialDef,
    MeshData,
    MeshVertex,
    MeshTriangle,
)
from scene_model.cs2_builder import build_cs2_document
from binary.cs2_writer import write_cs2
from binary.cs2_reader import read_cs2

ASSEMBLY_KIT_ROOT = r"D:\SteamLibrary\steamapps\common\Total War Attila\assembly_kit"


def make_box_mesh(half_width: float = 1.0, half_depth: float = 1.0, height: float = 2.0) -> MeshData:
    positions = [
        (-half_width, -half_depth, 0), (half_width, -half_depth, 0), (half_width, half_depth, 0), (-half_width, half_depth, 0),
        (-half_width, -half_depth, height), (half_width, -half_depth, height), (half_width, half_depth, height), (-half_width, half_depth, height),
    ]
    vertices = [MeshVertex(position=p, normal=(0.0, 0.0, 1.0), uv=(0.0, 0.0)) for p in positions]
    faces = [
        (0, 1, 2), (0, 2, 3), (4, 6, 5), (4, 7, 6),
        (0, 4, 5), (0, 5, 1), (1, 5, 6), (1, 6, 2),
        (2, 6, 7), (2, 7, 3), (3, 7, 4), (3, 4, 0),
    ]
    return MeshData(vertices=vertices, triangles=[MeshTriangle(indices=f) for f in faces])


def main() -> None:
    material = MaterialDef(name="TestMaterial", shader_type="default")
    lod = LodMesh(lod_index=1, mesh=make_box_mesh(), material=material)
    collision = CollisionMesh(mesh=make_box_mesh())
    # Same authoring shape confirmed against real BOB output (gondorean_marchingcamp_table /
    # _equipment01): a plain box whose horizontal half-extent becomes BOB's cylinder radius and
    # whose vertical extent becomes its height.
    soft_collision = SoftCollisionMesh(mesh=make_box_mesh(half_width=1.5, half_depth=1.5, height=2.0))

    destruct = DestructLevel(
        destruct_index=1,
        lod_meshes=[lod],
        collision_mesh=collision,
        soft_collision_mesh=soft_collision,
    )
    piece = Piece(piece_index=1, destruct_levels=[destruct])
    building = BuildingAsset(name="SoftCollisionTest", asset_type="display_building", pieces=[piece])

    out_path = Path(__file__).resolve().parent / "SoftCollisionTest.CS2"
    doc = build_cs2_document(building, ASSEMBLY_KIT_ROOT, output_path=str(out_path))
    data = write_cs2(doc)
    print("Wrote", len(data), "bytes")

    reparsed = read_cs2(data)
    print("Re-parsed OK:", reparsed.scene_block.rigid_models_count, "rigid models")
    for rm in reparsed.rigid_models:
        matids = [sm.material_id for sm in rm.geometry_chunks[0].submeshes]
        class_rigid_info = next((a.value for a in rm.attributes.strings if a.name == "class_rigidINFO"), None)
        print(" ", rm.node_name, "matids:", matids, "class_rigidINFO:", repr(class_rigid_info))
        if rm.node_name.endswith("soft_collision"):
            positions = [v.position for v in rm.geometry_chunks[0].vertices]
            xs = [p[0] for p in positions]
            ys = [p[1] for p in positions]
            zs = [p[2] for p in positions]
            print("    bounds x:", (min(xs), max(xs)), "y:", (min(ys), max(ys)), "z:", (min(zs), max(zs)))

    out_path.write_bytes(data)
    print("Wrote", out_path)


if __name__ == "__main__":
    main()
