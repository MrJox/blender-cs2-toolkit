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
    LineFeature,
    RegionZone,
    EFLine,
    DockingLine,
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


def make_square_loop(size: float = 5.0) -> list[tuple[float, float, float]]:
    points = [(-size, 0.0, -size), (size, 0.0, -size), (size, 0.0, size), (-size, 0.0, size)]
    return points + [points[0]]


def make_quad_mesh(size: float = 4.0) -> MeshData:
    # Engine (Y-up) space: a flat quad on the ground plane, big enough to contain both the
    # EFLine and DockingLine test edges below - BOB requires EFLines/DockingLines to sit within a
    # platform's bounds ("couldn't find platform for efline").
    positions = [(-size, 0.0, -size), (size, 0.0, -size), (size, 0.0, size), (-size, 0.0, size)]
    vertices = [MeshVertex(position=p, normal=(0.0, 1.0, 0.0), uv=(0.0, 0.0)) for p in positions]
    faces = [(0, 1, 2), (0, 2, 3)]
    return MeshData(vertices=vertices, triangles=[MeshTriangle(indices=f) for f in faces])


def main() -> None:
    material = MaterialDef(name="TestMaterial", shader_type="default")
    lod = LodMesh(lod_index=1, mesh=make_box_mesh(), material=material)
    collision = CollisionMesh(mesh=make_box_mesh())
    platform = PlatformMesh(variation_index=1, mesh=make_quad_mesh(4.0))

    outline = LineFeature(line_type="OUTLINE", variation_index=1, points=make_square_loop(6.0), closed=True)
    ground_ad = LineFeature(line_type="GROUND_AD", variation_index=1, points=[(-2.0, 0.0, 0.0), (2.0, 0.0, 0.0)], closed=False)
    pipe = LineFeature(line_type="PIPE_LADDER", variation_index=1, points=[(0.0, 0.0, 0.0), (0.0, 3.0, 0.0)], closed=False)

    ef_line = EFLine(variation_index=1, action="Low wall", start=(-1.0, 0.0, 0.0), end=(1.0, 0.0, 0.0), direction=(0.0, 0.0, 1.0))
    docking_line = DockingLine(variation_index=1, start=(-1.0, 0.0, 2.0), end=(1.0, 0.0, 2.0), direction=(0.0, 0.0, 1.0))

    destruct = DestructLevel(
        destruct_index=1,
        lod_meshes=[lod],
        collision_mesh=collision,
        platform_meshes=[platform],
        line_features=[outline, ground_ad, pipe],
        ef_lines=[ef_line],
        docking_lines=[docking_line],
    )
    piece = Piece(piece_index=1, destruct_levels=[destruct])

    region_zone_points = make_square_loop(10.0)
    region_zone = RegionZone(variation_index=1, points=region_zone_points, corner_points=region_zone_points[:-1])
    building = BuildingAsset(name="LinesEFDockingTest", asset_type="display_building", pieces=[piece], region_zones=[region_zone])

    out_path = Path(__file__).resolve().parent / "LinesEFDockingTest.CS2"
    doc = build_cs2_document(building, ASSEMBLY_KIT_ROOT, output_path=str(out_path))
    data = write_cs2(doc)
    print("Wrote", len(data), "bytes")

    reparsed = read_cs2(data)
    print(
        "Re-parsed OK:",
        reparsed.scene_block.rigid_models_count, "rigid,",
        reparsed.scene_block.lines_count, "lines,",
        reparsed.scene_block.materials_count, "materials",
    )

    print("Lines:")
    for ln in reparsed.lines:
        verts = ln.geometry_chunks[0].lines[0].vertices
        class_rigid_info = next((a.value for a in ln.attributes.strings if a.name == "class_rigidINFO"), None)
        print(" ", ln.node_name, "class_rigidINFO:", class_rigid_info, "verts:", len(verts), "first==last:", verts[0] == verts[-1])

    print("Zero-geometry rigid nodes (EFLine/DockingLine):")
    for rm in reparsed.rigid_models:
        if rm.node_name.startswith("EFline_") or rm.node_name.startswith("DockingLine_"):
            chunk = rm.geometry_chunks[0]
            print(" ", rm.node_name, "verts:", len(chunk.vertices), "tris:", len(chunk.submeshes[0].triangles))
            print("    user_defined_properties:")
            for line in rm.user_defined_properties.splitlines():
                print("     ", line)

    out_path.write_bytes(data)
    print("Wrote", out_path)


if __name__ == "__main__":
    main()
