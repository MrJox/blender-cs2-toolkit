import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from binary import anim_structures as s
from binary.anim_reader import read_anim


SAMPLE_ROOTS = [
    "Input/examples/working_data",
]


def check(path: Path) -> list[str]:
    animation = read_anim(path.read_bytes())
    errors = []

    bone_count = len(animation.bones)
    for index, bone in enumerate(animation.bones):
        if bone.parent_id >= index:
            errors.append(f"bone {index} ({bone.name}) has forward parent {bone.parent_id}")
        if bone.parent_id < -1:
            errors.append(f"bone {index} ({bone.name}) has parent {bone.parent_id}")

    for label, mappings in (
        ("translation", animation.translation_mappings),
        ("rotation", animation.rotation_mappings),
    ):
        if len(mappings) != bone_count:
            errors.append(f"{label} mappings {len(mappings)} != {bone_count} bones")
        used = [value for value in mappings if 0 <= value < s.STATIC_TRACK_BASE]
        if len(set(used)) != len(used):
            errors.append(f"{label} mappings reuse a dynamic track index")
        if used and sorted(used) != list(range(len(used))):
            errors.append(f"{label} dynamic track indices are not a dense 0..n-1 range")

    if animation.frames:
        expected_frames = round(animation.duration * animation.frame_rate) + 1
        if abs(len(animation.frames) - expected_frames) > 1:
            errors.append(
                f"{len(animation.frames)} frames but duration {animation.duration}s "
                f"at {animation.frame_rate}fps implies {expected_frames}"
            )
        for frame in animation.frames:
            for rotation in frame.rotations:
                length = sum(component * component for component in rotation) ** 0.5
                if abs(length - 1.0) > 0.01:
                    errors.append(f"rotation quaternion not unit length ({length})")
                    break
            else:
                continue
            break

    return errors


def main() -> None:
    repository_root = Path(__file__).resolve().parent.parent.parent
    extra_roots = [Path(argument) for argument in sys.argv[1:]]
    paths: list[Path] = []
    for root in [repository_root / relative for relative in SAMPLE_ROOTS] + extra_roots:
        paths += sorted(root.rglob("*.anim"))

    if not paths:
        raise SystemExit("no .anim samples found")

    failed = 0
    for path in paths:
        errors = check(path)
        if errors:
            failed += 1
            print(f"{path.name} FAILED")
            for error in errors:
                print("   ", error)

    print(f"{len(paths) - failed}/{len(paths)} anim samples structurally valid")
    if failed:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
