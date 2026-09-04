import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from binary.cs2_reader import read_cs2
from binary.bone_table import read_bone_table, write_bone_table
from binary.cs2_templates import scene_root_rotation_of
from scene_model.skeleton_builder import (
    build_bone_table,
    build_skeleton_cs2_document,
    skeleton_from_cs2_document,
)

DEFAULT_SKELETON_ROOTS = [
    r"D:\SteamLibrary\steamapps\common\Total War Attila\assembly_kit\raw_data\animations\skeletons",
]


def _node_shape(document) -> list[tuple[str, int]]:
    return [(node.name, node.parent_index) for node in document.scene_root.scene_nodes]


def _rest_pose(document) -> list[tuple]:
    return [(node.anim.translations[0], node.anim.rotations[0]) for node in document.scene_root.scene_nodes]


def check(cs2_path: Path) -> bool:
    name = cs2_path.stem
    document = read_cs2(cs2_path.read_bytes())

    bone_table_path = cs2_path.with_suffix(".bone_table")
    original_table = bone_table_path.read_bytes() if bone_table_path.exists() else None
    bone_table = read_bone_table(original_table, name) if original_table is not None else None

    skeleton = skeleton_from_cs2_document(document, name, bone_table)
    rebuilt = build_skeleton_cs2_document(skeleton, output_path=str(cs2_path))

    errors = []
    # The rotation, not the whole 84-byte block: real skeletons also carry -0.0 where the shared
    # constant has +0.0 at offsets 24 and 32, and splicing those in on their own was shown to change
    # nothing BOB compiles.
    rebuilt_rotation = scene_root_rotation_of(rebuilt.scene_root.scene_hierarchy_metadata)
    source_rotation = scene_root_rotation_of(document.scene_root.scene_hierarchy_metadata)
    if rebuilt_rotation != source_rotation:
        errors.append(f"scene root rotation differs - {rebuilt_rotation} vs {source_rotation}")
    if _node_shape(rebuilt) != _node_shape(document):
        errors.append("scene node names/hierarchy differ")
    if _rest_pose(rebuilt) != _rest_pose(document):
        errors.append("rest-pose translations/rotations differ")
    for original_node, rebuilt_node in zip(document.scene_root.scene_nodes, rebuilt.scene_root.scene_nodes):
        if original_node.attributes != rebuilt_node.attributes:
            errors.append(f"node attributes differ on '{original_node.name}'")
            break

    if original_table is not None:
        if write_bone_table(build_bone_table(skeleton)) != original_table:
            errors.append("bone_table is not byte-identical")
        listed = sum(1 for bone in skeleton.bones if bone.bone_type)
        if listed != len(bone_table.entries):
            errors.append(f"{listed} bones matched the table's {len(bone_table.entries)} entries")

    if errors:
        print(f"{name}: FAIL")
        for error in errors:
            print(f"  - {error}")
        return False

    table_note = f", bone_table {len(bone_table.entries)} entries byte-exact" if bone_table else ", no bone_table"
    print(f"{name}: OK - {len(skeleton.bones)} bones{table_note}")
    return True


def main() -> None:
    roots = [Path(root) for root in (sys.argv[1:] or DEFAULT_SKELETON_ROOTS)]
    paths = sorted({path for root in roots for path in root.rglob("*.cs2")})
    if not paths:
        print("No skeleton .cs2 files found in:", ", ".join(str(root) for root in roots))
        raise SystemExit(1)

    if not all([check(path) for path in paths]):
        raise SystemExit(1)
    print(f"\n{len(paths)} skeleton(s) round-tripped.")


if __name__ == "__main__":
    main()
