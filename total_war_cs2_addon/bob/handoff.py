from pathlib import Path


def build_handoff_message(cs2_path: Path) -> str:
    return (
        f"Exported '{cs2_path.name}' to:\n{cs2_path}\n\n"
        "Next step: open BOB (Assembly Kit), locate this file, and click Build to "
        "compile it into game-ready files."
    )
