import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import numpy as np

from textures import channels
from textures.dds import decode_dds
from textures.tga import read_tga

# PLAN_textures.md 1: the real Assembly Kit install this project's texture research was measured
# against - outside the repo, so this is an absolute path rather than something under Input/.
ASSEMBLY_KIT_ROOT = Path(r"D:\SteamLibrary\steamapps\common\Total War Attila\assembly_kit")
WORKING_DIR = ASSEMBLY_KIT_ROOT / "working_data" / "RigidModels" / "Buildings" / "Textures"
RAW_DIR = (
    ASSEMBLY_KIT_ROOT
    / "raw_data"
    / "art"
    / "battle"
    / "land"
    / "models"
    / "architecture"
    / "gondorean"
    / "textures"
)

# PLAN_textures.md 1.2-1.4: measured DXT block-quantisation error bounds. mask1/2/3 has no matched
# source anywhere in the corpus (1.5) so it is skipped here, not asserted against. The normal bound
# is 4.00 exactly on gondorean_reskin_new_2 by the plan's own measurement, with a 0.5 margin added
# for BC3 alpha-interpolation rounding differences between decoders (nearest-round here vs whatever
# produced the plan's numbers) rather than a real regression.
COLOUR_TOLERANCE = 6.0
SHUFFLE_TOLERANCE = 4.5


def _mean_abs_diff(got: np.ndarray, want: np.ndarray) -> float:
    return float(np.mean(np.abs(got.astype(np.int16) - want.astype(np.int16))))


def _check_plane(label: str, got: np.ndarray, want: np.ndarray, tolerance: float) -> bool:
    if got.shape != want.shape:
        print(f"  {label}: SHAPE MISMATCH {got.shape} vs {want.shape}")
        return False
    diff = _mean_abs_diff(got, want)
    ok = diff <= tolerance
    print(f"  {label}: mean|d|={diff:.2f} ({'OK' if ok else 'FAIL'}, tolerance {tolerance})")
    return ok


def check_gloss_map(dds_path: Path) -> bool | None:
    base = dds_path.stem[: -len(channels.SUFFIX_GLOSS_MAP)]
    gloss_tga = RAW_DIR / f"{base}_gloss.tga"
    level_tga = RAW_DIR / f"{base}_level.tga"
    if not gloss_tga.exists() or not level_tga.exists():
        return None
    outputs = channels.gloss_map_outputs(decode_dds(dds_path.read_bytes()))
    ok = _check_plane(f"{dds_path.name} R vs {gloss_tga.name}", outputs["_gloss"], read_tga(gloss_tga), COLOUR_TOLERANCE)
    ok &= _check_plane(f"{dds_path.name} G vs {level_tga.name}", outputs["_level"], read_tga(level_tga), COLOUR_TOLERANCE)
    return ok


def check_normal(dds_path: Path) -> bool | None:
    raw_tga = RAW_DIR / f"{dds_path.stem}.tga"
    if not raw_tga.exists():
        return None
    got = channels.normal_output(decode_dds(dds_path.read_bytes()), reconstruct_z=False)
    want = read_tga(raw_tga)
    ok = _check_plane(f"{dds_path.name} R (A->R)", got[..., 0], want[..., 0], SHUFFLE_TOLERANCE)
    ok &= _check_plane(f"{dds_path.name} G", got[..., 1], want[..., 1], SHUFFLE_TOLERANCE)
    return ok


def check_straight(dds_path: Path) -> bool | None:
    raw_tga = RAW_DIR / f"{dds_path.stem}.tga"
    if not raw_tga.exists():
        return None
    pixels = decode_dds(dds_path.read_bytes())
    want = read_tga(raw_tga)
    want_rgb = want[..., :3] if want.ndim == 3 else want
    return _check_plane(f"{dds_path.name} RGB", pixels[..., :3], want_rgb, COLOUR_TOLERANCE)


def main() -> None:
    if not WORKING_DIR.is_dir() or not RAW_DIR.is_dir():
        print(f"Corpus not found - checked:\n  {WORKING_DIR}\n  {RAW_DIR}")
        raise SystemExit(1)

    all_ok = True
    checked = 0
    for dds_path in sorted(WORKING_DIR.glob("*.dds")):
        stem = dds_path.stem
        if stem.endswith(channels.SUFFIX_GLOSS_MAP):
            result = check_gloss_map(dds_path)
        elif stem.endswith(channels.SUFFIX_NORMAL):
            result = check_normal(dds_path)
        elif stem.endswith(channels.SUFFIX_MASK):
            result = None
        elif stem.endswith(("_diffuse", "_specular")):
            result = check_straight(dds_path)
        else:
            result = None
        if result is None:
            continue
        checked += 1
        all_ok = all_ok and result

    print(f"\n{checked} matched pairs checked.")
    if checked == 0:
        print("No matched pairs found - the corpus may have moved.")
        raise SystemExit(1)
    if not all_ok:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
