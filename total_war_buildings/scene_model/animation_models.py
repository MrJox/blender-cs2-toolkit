from dataclasses import dataclass, field

from .models import AnimationKeyframes

DEFAULT_FRAME_RATE = 20.0


@dataclass
class AnimationClip:
    name: str
    skeleton_name: str
    frame_rate: float = DEFAULT_FRAME_RATE
    frame_count: int = 0
    # Bone name -> its local-to-parent transform track in engine space, times in seconds from the
    # clip's own start. A bone missing from this map keeps the skeleton's rest transform, which is
    # what a real clip's static nodes carry as their single key.
    tracks: dict[str, AnimationKeyframes] = field(default_factory=dict)
    # Whose frame those locals are relative to, when that is not the skeleton's own parent. A
    # compiled .anim carries the bone list collapsed to the game bones, so bn_weapon_01 is a root
    # there while the skeleton parents it under ref_weapon_01 - composing its local down the
    # skeleton's chain instead of the file's puts it metres away. An empty value means "root", and a
    # bone absent from this map follows the skeleton.
    parents: dict[str, str] = field(default_factory=dict)

    @property
    def duration(self) -> float:
        return (self.frame_count - 1) / self.frame_rate if self.frame_count > 1 else 0.0


def is_dynamic(keyframes: AnimationKeyframes) -> bool:
    return len(keyframes.translation_times) > 1 or len(keyframes.rotation_times) > 1
