from .reader import BinaryReader
from . import anim_structures as s


def read_anim(data: bytes) -> s.Animation:
    r = BinaryReader(data)
    version = r.u32()
    if version != s.FILE_VERSION_ATTILA:
        raise ValueError(f"unsupported anim version {version}")
    bone_name_table_version = r.u32()
    frame_rate = r.f32()
    skeleton_name = r.length_prefixed_ascii()
    duration = r.f32()

    bone_count = r.u32()
    bones = [s.AnimBone(name=r.length_prefixed_ascii(), parent_id=r.i32()) for _ in range(bone_count)]
    translation_mappings = [r.i32() for _ in range(bone_count)]
    rotation_mappings = [r.i32() for _ in range(bone_count)]

    translation_track_count = r.i32()
    rotation_track_count = r.i32()
    frame_count = r.i32()

    frames = []
    if translation_track_count > 0 or rotation_track_count > 0:
        for _ in range(frame_count):
            translations = [r.vec3() for _ in range(translation_track_count)]
            rotations = [
                (
                    r.i16() * s.QUATERNION_SCALE,
                    r.i16() * s.QUATERNION_SCALE,
                    r.i16() * s.QUATERNION_SCALE,
                    r.i16() * s.QUATERNION_SCALE,
                )
                for _ in range(rotation_track_count)
            ]
            frames.append(s.AnimFrame(translations=translations, rotations=rotations))

    if not r.at_end():
        raise ValueError(f"anim parse left {r.remaining()} trailing bytes")

    return s.Animation(
        version=version,
        bone_name_table_version=bone_name_table_version,
        frame_rate=frame_rate,
        skeleton_name=skeleton_name,
        duration=duration,
        bones=bones,
        translation_mappings=translation_mappings,
        rotation_mappings=rotation_mappings,
        frames=frames,
    )


def bone_local_transform(animation: s.Animation, bone_index: int, frame_index: int) -> tuple[s.Vec3, s.Vec4]:
    frame = animation.frames[frame_index]
    translation_track = animation.translation_mappings[bone_index]
    rotation_track = animation.rotation_mappings[bone_index]
    translation = (0.0, 0.0, 0.0)
    if 0 <= translation_track < s.STATIC_TRACK_BASE:
        translation = frame.translations[translation_track]
    rotation = (0.0, 0.0, 0.0, 1.0)
    if 0 <= rotation_track < s.STATIC_TRACK_BASE:
        rotation = frame.rotations[rotation_track]
    return translation, rotation
