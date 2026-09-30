from dataclasses import dataclass, field
from pathlib import Path

from . import channels
from .dds import decode_dds
from .tga import write_tga


@dataclass
class DecompileResult:
    written: list[Path] = field(default_factory=list)
    warning: str | None = None


def _target(out_dir: Path, name: str) -> Path:
    return out_dir / name


def _write_if_allowed(path: Path, pixels, overwrite: bool, written: list[Path]) -> None:
    if path.exists() and not overwrite:
        return
    write_tga(path, pixels)
    written.append(path)


def decompile_texture(
    dds_path,
    output_dir=None,
    overwrite: bool = False,
    reconstruct_normal_z: bool = False,
) -> DecompileResult:
    dds_path = Path(dds_path)
    pixels = decode_dds(dds_path.read_bytes())
    stem = dds_path.stem
    out_dir = Path(output_dir) if output_dir is not None else dds_path.parent
    out_dir.mkdir(parents=True, exist_ok=True)

    result = DecompileResult()
    suffix = channels.classify(stem)

    if suffix == channels.SUFFIX_GLOSS_MAP:
        base = stem[: -len(suffix)]
        for output_suffix, plane in channels.gloss_map_outputs(pixels).items():
            _write_if_allowed(_target(out_dir, f"{base}{output_suffix}.tga"), plane, overwrite, result.written)
        return result

    if suffix == channels.SUFFIX_MASK:
        base = stem[: -len(suffix)]
        for output_suffix, plane in channels.mask_outputs(pixels).items():
            _write_if_allowed(_target(out_dir, f"{base}{output_suffix}.tga"), plane, overwrite, result.written)
        return result

    if suffix == channels.SUFFIX_NORMAL:
        rgb = channels.normal_output(pixels, reconstruct_normal_z)
        _write_if_allowed(_target(out_dir, f"{stem}.tga"), rgb, overwrite, result.written)
        return result

    if suffix == channels.SUFFIX_PARALLAX:
        rgb = channels.parallax_output(pixels)
        _write_if_allowed(_target(out_dir, f"{stem}.tga"), rgb, overwrite, result.written)
        return result

    # 3.2: unrecognised suffixes (and diffuse/specular, which need no processing beyond
    # decode-and-rewrite) convert straight through rather than being skipped.
    plane = pixels if channels.has_real_alpha(pixels) else pixels[..., :3]
    _write_if_allowed(_target(out_dir, f"{stem}.tga"), plane, overwrite, result.written)
    if not stem.endswith(("_diffuse", "_specular")):
        result.warning = f"'{dds_path.name}' does not match a known texture suffix - converted straight through."
    return result


def decompile_many(
    dds_paths,
    output_dir=None,
    overwrite: bool = False,
    reconstruct_normal_z: bool = False,
) -> tuple[list[Path], list[str]]:
    written: list[Path] = []
    warnings: list[str] = []
    for dds_path in dds_paths:
        try:
            result = decompile_texture(dds_path, output_dir, overwrite, reconstruct_normal_z)
        except Exception as error:  # noqa: BLE001
            warnings.append(f"'{Path(dds_path).name}': {error}")
            continue
        written.extend(result.written)
        if result.warning:
            warnings.append(result.warning)
    return written, warnings
