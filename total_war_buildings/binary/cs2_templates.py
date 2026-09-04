# Most byte-for-byte constants in this file are copied verbatim from
# Input/examples/raw_data/gondor_building_5/gondor_building_5.CS2, a real cas2_exporter-authored
# file at exporter tool version 1.16 (Header.feature_flags, misleadingly named - it is a float32
# version stamp, not a bitmask: 1066695393 -> 1.16), for fields whose exact semantics are not fully
# documented. This add-on targets v1.16 specifically because that is the current tool version - the
# one every recent ground-truth sample and the currently installed Assembly Kit's BOB both use - not
# v1.15 (bridge_stone_1/eastern_new_1, this project's two oldest samples). See the implementation
# plan for the full version audit and why this distinction matters (it is not cosmetic - see
# TIMELINE_TRACK_METADATA below, which is a different length between the two versions).

ADDON_VERSION = (0, 1, 0)


def get_plugin_header_string() -> str:
    addon_ver_str = ".".join(str(x) for x in ADDON_VERSION)
    try:
        import bpy
        bl_ver_str = ".".join(str(x) for x in bpy.app.version)
    except ImportError:
        bl_ver_str = "4.0.0"
    return f"Blender v{bl_ver_str} Cas2 Exporter v{addon_ver_str}"


import struct

FILE_FORMAT_MAGIC = b"\x01\x32\x53\x43"
EXPORTER_VERSION = 0.0
FEATURE_FLAGS = 1066695393
FORMAT_COMPATIBILITY_VERSION = 1
OBJECT_TYPES_COUNT = 23

SCENE_BBOX_AND_WORLD_MATRIX = bytes(44)

TIMELINE_FRAME_RATE_FPS = 2
TIMELINE_START_FRAME_TIME = 0.0
TIMELINE_END_FRAME_TIME = 3.3333332538604736
# 56 bytes at v1.16 vs 48 at v1.15 (8 extra trailing zero bytes) - a genuine structural difference
# between the two tool versions, not just a data difference. Confirmed identical byte-for-byte
# across all 5 v1.16 ground-truth samples, so this is a real format constant, not per-file noise.
TIMELINE_TRACK_METADATA = (
    b"\x01\x00\x00\x00\x02\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00"
    b"\x01\x00\x00\x00\x00\x00\x00\x00\x01\x00\x00\x00\x00\x00\x00\x00"
    b"\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x80?\x00\x00\x00\x00"
    b"\x00\x00\x00\x00\x00\x00\x00\x00"
)

MORPH_TRACK_FLAGS = 22

SCENE_ROOT_UP_AXIS_ORIENTATION = -1
SCENE_ROOT_UNIT_SCALE = 1
SCENE_ROOT_HIERARCHY_METADATA = (
    b"\x03\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x01\x00\x00\x00"
    b"\x00\x00\x00\x00\x01\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00"
    b"\x00\x00\x00\x00\x01\x00\x00\x00\x06\x00\x00\x00\x00\x00\x00\x00"
    b"\x00\x00\x00\x00\x01\x00\x00\x00\x00\x00\x00\x00\x01\x00\x00\x00"
    b"\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x80?"
    b"\x00\x00\x00\x00"
)
SCENE_ROOT_END_PADDING = bytes(12)

# Bytes 64..80 of SceneHierarchyMetadata are the scene root's own rotation, as a (x, y, z, w)
# quaternion. Buildings carry identity; rome_man_game carries (0, 1, 0, -0) - a half turn about Y.
# Found by splicing the two real blocks range by range and re-compiling each result: with the
# building block a skeleton's bn_hips and its five floating weapon bones (exactly the bones BOB
# stores in world space rather than relative to a parent bone) come out up to 90 degrees and 5cm
# wrong, and taking these 16 bytes alone from the skeleton puts all 50 bones back on BOB's own
# compile of CA's file. The other two differing words (offsets 24 and 32, -0.0 against +0.0) were
# spliced in on their own and changed nothing.
SCENE_ROOT_ROTATION_RANGE = (64, 80)
SCENE_ROOT_IDENTITY_ROTATION = (0.0, 0.0, 0.0, 1.0)
# The half turn about Y that PLAN_units.md 1.4 measured between skeleton space and compiled
# rigid_model_v2 T-pose space. It is authored here, in the skeleton's own file - not applied by BOB.
SKELETON_SCENE_ROOT_ROTATION = (0.0, 1.0, 0.0, -0.0)


def scene_root_hierarchy_metadata(rotation: tuple[float, float, float, float]) -> bytes:
    start, end = SCENE_ROOT_ROTATION_RANGE
    return SCENE_ROOT_HIERARCHY_METADATA[:start] + struct.pack("<4f", *rotation) + SCENE_ROOT_HIERARCHY_METADATA[end:]


def scene_root_rotation_of(metadata: bytes) -> tuple[float, float, float, float]:
    start, end = SCENE_ROOT_ROTATION_RANGE
    return struct.unpack("<4f", metadata[start:end])

SCENE_NODE_DEFAULT_SCALE_OR_PIVOT = (1.401298464324817e-45, 4.203895392974451e-45, 0.0, 0.0)
SCENE_NODE_SCALE_TRACK_OR_BBOX = b"\x01\x00\x00\x00\x06\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00"

GEOMETRY_CHUNK_HEADER_PADDING = b"\x0b\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00"
GEOMETRY_CHUNK_BOUNDING_BOX_EXTENT_FLOATS = [0.0]
# Not a designed constant - this is genuinely uninitialized memory in the real exporter. Checked
# across every "sentinel" chunk in the v1.16 ground-truth corpus and the exact bits drift run to
# run (observed range ~2.5399994e28 to 1.97e29, one axis at a time), so no single bit pattern is
# "the" real value to match. This one is gondor_building_5's own piece01_destruct01_lod01, picked
# only for internal consistency with the v1.16 stamp above - any value with this magnitude and
# inverted min/max sign would be equally faithful to what real exporters actually produce.
GEOMETRY_CHUNK_BOUNDING_BOX_SENTINEL = (
    (2.5399998984385163e28, 2.5399998984385163e28, 2.5399998984385163e28),
    (-2.5399998984385163e28, -2.5399998984385163e28, -2.5399998984385163e28),
)
DISPLAY_VERTEX_COLOR_CHANNEL_FLAGS = 8
DISPLAY_UVW_CHANNEL_IDS = [1]
LINE_VERTEX_COLOR_CHANNEL_FLAGS = 0

assert len(TIMELINE_TRACK_METADATA) == 56
assert len(SCENE_ROOT_HIERARCHY_METADATA) == 84
assert len(SCENE_NODE_SCALE_TRACK_OR_BBOX) == 16
assert len(GEOMETRY_CHUNK_HEADER_PADDING) == 12
assert scene_root_hierarchy_metadata(SCENE_ROOT_IDENTITY_ROTATION) == SCENE_ROOT_HIERARCHY_METADATA

SCENE_ROOT_NODE_NAME = "Scene Root"


def build_details_string(username: str, export_timestamp: str, cas_name_path: str, max_file_path: str = "") -> str:
    # Header.Details and SceneRoot.Info both use this exact tagged, tab-delimited format in every
    # real sample. A crash was traced to using a plain free-text string here instead - something in
    # BOB's building processor appears to parse the CAS_NAME line (the file's own absolute path).
    return (
        f"USERNAME:\t{username}\r\n"
        f"LAST_EXPORT:\t{export_timestamp}\r\n"
        f"CAS_NAME:\t{cas_name_path}\r\n"
        f"MAX_FILE:\t{max_file_path}\r\n\r\n\r\n"
    )
