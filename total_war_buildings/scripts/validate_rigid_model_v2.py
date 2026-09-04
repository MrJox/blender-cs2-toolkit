import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from binary import rigid_model_v2_structures as s
from binary.rigid_model_v2_reader import read_rigid_model_v2


SAMPLE_ROOTS = [
    "Input/examples/working_data",
]


def check(path: Path) -> list[str]:
    data = path.read_bytes()
    model = read_rigid_model_v2(data)
    errors = []

    if model.version != s.FILE_VERSION_ATTILA:
        errors.append(f"version {model.version}")

    for lod_index, lod in enumerate(model.lods):
        vertex_bytes = 0
        index_bytes = 0
        for mesh_index, mesh in enumerate(lod.meshes):
            where = f"lod{lod_index}/mesh{mesh_index}"
            vertex_bytes += mesh.vertex_count * mesh.vertex_stride
            index_bytes += mesh.index_count * 2

            expected = (
                s.COMMON_MESH_HEADER_SIZE
                + len(mesh.material_raw)
                + mesh.vertex_count * mesh.vertex_stride
                + mesh.index_count * 2
            )
            if expected != mesh.section_size:
                errors.append(f"{where}: section size {mesh.section_size} != {expected}")

            if mesh.material is not None and len(mesh.material_raw) < s.MESH_HEADER_V5_SIZE:
                errors.append(f"{where}: MESH_HEADER_V5 shorter than {s.MESH_HEADER_V5_SIZE}")

            if mesh.vertices and len(mesh.vertices) != mesh.vertex_count:
                errors.append(f"{where}: decoded {len(mesh.vertices)} of {mesh.vertex_count} vertices")

            if mesh.index_count % 3:
                errors.append(f"{where}: index count {mesh.index_count} is not a triangle list")

            if mesh.indices and max(mesh.indices) >= mesh.vertex_count:
                errors.append(f"{where}: index {max(mesh.indices)} out of range for {mesh.vertex_count} vertices")

            if mesh.shader_flags in s.WEIGHTED_SHADERS:
                if model.bone_table_name == "":
                    errors.append(f"{where}: weighted shader with no bone table name")
                for vertex in mesh.vertices:
                    if abs(sum(vertex.bone_weights) - 1.0) > 1.5 / 255.0:
                        errors.append(f"{where}: bone weights sum to {sum(vertex.bone_weights)}")
                        break

        if vertex_bytes != lod.total_vertex_size:
            errors.append(f"lod{lod_index}: vertex payload {vertex_bytes} != declared {lod.total_vertex_size}")
        if index_bytes != lod.total_index_size:
            errors.append(f"lod{lod_index}: index payload {index_bytes} != declared {lod.total_index_size}")

    return errors


def main() -> None:
    repository_root = Path(__file__).resolve().parent.parent.parent
    extra_roots = [Path(argument) for argument in sys.argv[1:]]
    paths: list[Path] = []
    for root in [repository_root / relative for relative in SAMPLE_ROOTS] + extra_roots:
        paths += sorted(root.rglob("*.rigid_model_v2"))

    if not paths:
        raise SystemExit("no .rigid_model_v2 samples found")

    failed = 0
    for path in paths:
        errors = check(path)
        if errors:
            failed += 1
            print(f"{path.name} FAILED")
            for error in errors:
                print("   ", error)

    print(f"{len(paths) - failed}/{len(paths)} rigid_model_v2 samples structurally valid")
    if failed:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
