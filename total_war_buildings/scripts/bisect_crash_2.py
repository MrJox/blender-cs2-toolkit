import copy
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from binary.cs2_reader import read_cs2
from binary.cs2_writer import write_cs2
from binary import cs2_structures as s
from scene_model.models import BuildingAsset, Piece, DestructLevel, LodMesh, CollisionMesh, MaterialDef, MeshData, MeshVertex, MeshTriangle
from scene_model.cs2_builder import build_cs2_document

SAMPLE_PATH = Path(__file__).resolve().parent.parent.parent / "Input/examples/raw_data/gondor_building_5/gondor_building_5.CS2"
OUT_DIR = Path(__file__).resolve().parent
ASSEMBLY_KIT_ROOT = r"D:\SteamLibrary\steamapps\common\Total War Attila\assembly_kit"


def make_box_mesh() -> MeshData:
    positions = [
        (-1, -1, -1), (1, -1, -1), (1, 1, -1), (-1, 1, -1),
        (-1, -1, 1), (1, -1, 1), (1, 1, 1), (-1, 1, 1),
    ]
    faces = [
        (0, 1, 2), (0, 2, 3), (4, 6, 5), (4, 7, 6),
        (0, 4, 5), (0, 5, 1), (1, 5, 6), (1, 6, 2),
        (2, 6, 7), (2, 7, 3), (3, 7, 4), (3, 4, 0),
    ]
    vertices = [MeshVertex(position=p, normal=(0.0, 0.0, 1.0), uv=(0.0, 0.0)) for p in positions]
    triangles = [MeshTriangle(indices=f) for f in faces]
    return MeshData(vertices=vertices, triangles=triangles)


def our_building_asset() -> BuildingAsset:
    material = MaterialDef(name="TestBoxMaterial", shader_type="default")
    lod = LodMesh(lod_index=1, mesh=make_box_mesh(), material=material)
    collision = CollisionMesh(mesh=make_box_mesh())
    destruct = DestructLevel(destruct_index=1, lod_meshes=[lod], collision_mesh=collision)
    piece = Piece(piece_index=1, destruct_levels=[destruct])
    return BuildingAsset(name="Building", asset_type="display_building", pieces=[piece])


def save(doc: s.CS2Document, name: str) -> None:
    data = write_cs2(doc)
    out_path = OUT_DIR / name
    out_path.write_bytes(data)
    reread = read_cs2(data)
    print(f"{name}: wrote {len(data)} bytes, self-reparse OK ({reread.scene_block.rigid_models_count} rigid, {reread.scene_block.materials_count} materials)")


def variant_our_globals_real_nodes() -> s.CS2Document:
    """Our header/scene_block/timeline/morph/scene_root, but the REAL file's rigid+material nodes."""
    fake_output_path = str(OUT_DIR / "bisect_04_our_globals_real_nodes.CS2")
    our_doc = build_cs2_document(our_building_asset(), ASSEMBLY_KIT_ROOT, output_path=fake_output_path)
    real_doc = read_cs2(SAMPLE_PATH.read_bytes())

    doc = copy.deepcopy(our_doc)
    doc.rigid_models = copy.deepcopy(real_doc.rigid_models)
    doc.materials = copy.deepcopy(real_doc.materials)
    doc.scene_block.rigid_models_count = len(doc.rigid_models)
    doc.scene_block.materials_count = len(doc.materials)

    doc.scene_root.scene_nodes = [
        sn for sn in our_doc.scene_root.scene_nodes  # placeholder, replaced below
    ]
    # Rebuild scene nodes to match the real rigid node names exactly, using OUR scene-node template.
    from scene_model.cs2_builder import _scene_node_for

    doc.scene_root.scene_nodes = [_scene_node_for(rm.node_name, rm.attributes) for rm in doc.rigid_models]
    return doc


def variant_real_globals_our_nodes() -> s.CS2Document:
    """The REAL file's header/scene_block/timeline/morph/scene_root, but OUR rigid+material nodes."""
    fake_output_path = str(OUT_DIR / "bisect_05_real_globals_our_nodes.CS2")
    our_doc = build_cs2_document(our_building_asset(), ASSEMBLY_KIT_ROOT, output_path=fake_output_path)
    real_doc = read_cs2(SAMPLE_PATH.read_bytes())

    doc = copy.deepcopy(real_doc)
    doc.rigid_models = copy.deepcopy(our_doc.rigid_models)
    doc.materials = copy.deepcopy(our_doc.materials)
    doc.scene_block.rigid_models_count = len(doc.rigid_models)
    doc.scene_block.materials_count = len(doc.materials)

    doc.scene_root.scene_nodes = [copy.deepcopy(sn) for sn in real_doc.scene_root.scene_nodes[: len(doc.rigid_models)]]
    for sn, rm in zip(doc.scene_root.scene_nodes, doc.rigid_models):
        sn.name = rm.node_name
    return doc


def main() -> None:
    save(variant_our_globals_real_nodes(), "bisect_04_our_globals_real_nodes.CS2")
    save(variant_real_globals_our_nodes(), "bisect_05_real_globals_our_nodes.CS2")


if __name__ == "__main__":
    main()
