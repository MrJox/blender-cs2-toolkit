# Animation (.anim) File Format Specification
**Format Version:** Version 5 (Total War: ATTILA)  
**Target Game:** Total War: ATTILA  
**Byte Ordering:** Little-Endian  

---

## 1. Overview

The `.anim` file format is Creative Assembly's binary skeletal animation container. It stores keyframe bone transformations (translations and rotation quaternions) for characters, creatures, warmachines, and animated props.

In the Total War engine (`Attila.exe`), animation data is processed via `UTILITYLIB::ANIMATION` and initialized from binary `.anim` data blocks.

Animation Version 5 is used by **Total War: ATTILA**.

### Key Features of Version 5
- **Bone Hierarchy Table**: Defines the skeleton's bone names and parent-child parentage indices.
- **Track Mapping Tables**: Maps each bone index to dynamic translation and rotation track indices (channel remapping), allowing unneeded/static channels to be omitted.
- **Compressed Rotation Quaternions**: Quaternion components ($X, Y, Z, W$) are stored as signed 16-bit integers compressed by a factor of $32767$.
- **Full Precision Translations**: Translation vectors ($X, Y, Z$) are stored as standard 32-bit single-precision IEEE 754 floats.

---

## 2. High-Level File Architecture

An `.anim` Version 5 file contains four sequential binary sections:

```
+-------------------------------------------------------------+
| 1. Animation Header (UTILITYLIB::ANIMATION_HEADER)          |
|    - Version (uint32 = 5)                                   |
|    - Header metadata, FPS, Skeleton Name, Total Duration    |
+-------------------------------------------------------------+
| 2. Bone Hierarchy Table                                     |
|    - BoneCount / m_num_nodes (uint32)                       |
|    - Bone Name (length-prefixed ASCII) + ParentId (int32)   |
+-------------------------------------------------------------+
| 3. Channel Remapping Tables                                 |
|    - Translation Mappings Array (BoneCount x int32)         |
|    - Rotation Mappings Array (BoneCount x int32)            |
+-------------------------------------------------------------+
| 4. Dynamic Keyframe Payload                                 |
|    - animPosCount (int32), animRotCount (int32), frameCount |
|    - Frame 0 .. Frame N-1 Payload                           |
|      * Translation Vectors (animPosCount x 12 bytes)        |
|      * Rotation Quaternions (animRotCount x 8 bytes)        |
+-------------------------------------------------------------+
```

---

## 3. Data Structures Specification

### 3.1 Primitive Types Reference

| Primitive Type | C/C++ Engine Equivalent | Size (Bytes) | Description |
| :--- | :--- | :--- | :--- |
| `short` / `int16` | `short` | 2 | Signed 16-bit Little-Endian integer (`-32768` to `32767`) |
| `ushort` / `uint16` | `unsigned short` | 2 | Unsigned 16-bit Little-Endian integer |
| `int` / `int32` | `int` / `CA::card32` | 4 | Signed 32-bit Little-Endian integer |
| `uint` / `uint32` | `CA::card32` | 4 | Unsigned 32-bit Little-Endian integer |
| `float` / `float32` | `float` / `CA::float32` | 4 | IEEE 754 32-bit single-precision floating point |
| `string` | `CA::String` | Variable | String encoded as `int16` length prefix followed by UTF-8 / ASCII bytes |

---

### 3.2 Animation Header (`UTILITYLIB::ANIMATION_HEADER`)

The animation header starts at byte offset `0x00000000`.

| Field Name | Engine C++ Field Name | Data Type | Size (Bytes) | Description |
| :--- | :--- | :--- | :--- | :--- |
| `Version` | `m_version` | `uint32` | 4 | Animation format version. Must equal `5` for Attila. |
| `BoneNameTableVersion` | `m_bone_name_table_version_number` | `uint32` | 4 | Skeleton bone table schema version (typically `1`). |
| `FrameRate` | `m_key_frames_per_second` | `float32` | 4 | Animation playback speed in frames per second (typically `20.0`). |
| `SkeletonNameLength` | — | `int16` | 2 | Character byte length of `SkeletonName`. |
| `SkeletonName` | `m_skeleton_name` | `byte[NameLen]` | Variable | ASCII/UTF-8 string specifying the target skeleton (e.g. `"humanoid01"`). |
| `AnimationTotalPlayTimeInSec` | `m_duration` | `float32` | 4 | Total duration of the animation clip in seconds. |

*Note on Engine C++ Struct Layout (`UTILITYLIB::ANIMATION_HEADER`):*
```cpp
struct UTILITYLIB::ANIMATION_HEADER
{
  CA::card32 m_version;
  CA::card32 m_bone_name_table_version_number;
  float m_key_frames_per_second;
  CA::String m_skeleton_name;
  float m_duration;
  CA::card32 m_num_nodes;
};
```

*Note on Flags:* Variable flag declarations (`FlagCount` and `FlagVariables`) were introduced in Version 7. They are **NOT** present in Version 5.

---

### 3.3 Bone Hierarchy Table

Directly follows `AnimationTotalPlayTimeInSec`.

| Field Name | Engine C++ Field Name | Data Type | Size (Bytes) | Description |
| :--- | :--- | :--- | :--- | :--- |
| `BoneCount` | `m_num_nodes` | `uint32` | 4 | Number of bones defined in the animation skeleton hierarchy. |

Following `BoneCount` is an array of `BoneCount` bone definition blocks:

#### Bone Definition Entry Layout
| Field Name | Data Type | Size (Bytes) | Description |
| :--- | :--- | :--- | :--- |
| `NameLength` | `int16` | 2 | Character byte length of bone name string. |
| `Name` | `byte[NameLength]` | Variable | ASCII string for the bone name (e.g. `"bn_head"`). |
| `ParentId` | `int32` | 4 | Parent bone index in hierarchy (`-1` indicates root bone with no parent). |

---

### 3.4 Channel Remapping Tables

Following the bone hierarchy table are two channel remapping arrays, each containing `BoneCount` elements (`int32`).

#### 1. Translation Mappings Array (`BoneCount` x `int32`)
Maps each bone index (`0` to `BoneCount - 1`) to its corresponding position track in the keyframe payload.

#### 2. Rotation Mappings Array (`BoneCount` x `int32`)
Maps each bone index (`0` to `BoneCount - 1`) to its corresponding rotation track in the keyframe payload.

#### Mapping Value Encoding Rules
For any bone index `i`:
- **Value == -1**: Bone has **no animation data** (remains in rest pose / identity).
- **Value < 10000**: Bone has a **dynamic animation track** at track index `Value` in each keyframe.
- **Value >= 10000**: Bone has a **static track** at index `Value - 10000` (used in higher versions).

---

### 3.5 Dynamic Keyframe Payload

#### 3.5.1 Keyframe Payload Header
Immediately following the rotation remapping array:

| Field Name | Data Type | Size (Bytes) | Description |
| :--- | :--- | :--- | :--- |
| `animPosCount` | `int32` | 4 | Number of dynamic translation vectors present per keyframe. |
| `animRotCount` | `int32` | 4 | Number of dynamic rotation quaternions present per keyframe. |
| `frameCount` | `int32` | 4 | Total number of dynamic keyframes in the animation. |

*Note:* If an animation has no motion data (`animPosCount == 0` and `animRotCount == 0`), `frameCount` is written as `3` by convention, but no keyframe payload bytes follow.

#### 3.5.2 Keyframe Payload Data
If `animPosCount > 0` or `animRotCount > 0`, the stream contains `frameCount` consecutive keyframe payloads.

Each keyframe contains:
1. **Translation Vectors Payload**: `animPosCount` x `RmvVector3` (`UTILITYLIB::VECTOR_3`, 12 bytes per vector).
2. **Rotation Quaternions Payload**: `animRotCount` x Compressed Quaternion (8 bytes per quaternion).

##### 1. Translation Vector Structure (`RmvVector3` / `UTILITYLIB::VECTOR_3`) — 12 Bytes
| Field | Data Type | Size (Bytes) | Description |
| :--- | :--- | :--- | :--- |
| `X` | `float32` | 4 | Local X translation coordinate |
| `Y` | `float32` | 4 | Local Y translation coordinate |
| `Z` | `float32` | 4 | Local Z translation coordinate |

##### 2. Compressed Rotation Quaternion Structure — 8 Bytes
| Field | Data Type | Size (Bytes) | Description |
| :--- | :--- | :--- | :--- |
| `qx_raw` | `int16` | 2 | Signed 16-bit compressed quaternion X component |
| `qy_raw` | `int16` | 2 | Signed 16-bit compressed quaternion Y component |
| `qz_raw` | `int16` | 2 | Signed 16-bit compressed quaternion Z component |
| `qw_raw` | `int16` | 2 | Signed 16-bit compressed quaternion W component |

---

## 4. Quaternion Compression & Decompression Formulas

### Decompressing Quaternion (File -> Float)
To convert signed 16-bit integer raw values back into unit floating-point quaternion components ($X, Y, Z, W$):

$$\text{scale} = \frac{1.0}{32767.0}$$

$$Q_x = \text{qx\_raw} \times \text{scale}$$
$$Q_y = \text{qy\_raw} \times \text{scale}$$
$$Q_z = \text{qz\_raw} \times \text{scale}$$
$$Q_w = \text{qw\_raw} \times \text{scale}$$

### Compressing Quaternion (Float -> File)
To compress normalized float quaternion components into 16-bit integers:

$$\text{qx\_raw} = \text{round}(Q_x \times 32767.0)$$
$$\text{qy\_raw} = \text{round}(Q_y \times 32767.0)$$
$$\text{qz\_raw} = \text{round}(Q_z \times 32767.0)$$
$$\text{qw\_raw} = \text{round}(Q_w \times 32767.0)$$

---

## 5. Reconstructing Bone Transformations per Frame

To evaluate the local transformation for bone `boneIndex` at keyframe index `frameIndex`:

1. **Translation Retrieval**:
   - `lookup = TranslationMappings[boneIndex]`
   - If `lookup.IsDynamic` (`lookup >= 0` and `lookup < 10000`):  
     $$\text{Position} = \text{Keyframes}[\text{frameIndex}].\text{Transforms}[\text{lookup}]$$
   - Else:  
     $$\text{Position} = (0.0, 0.0, 0.0)$$

2. **Rotation Retrieval**:
   - `lookup = RotationMappings[boneIndex]`
   - If `lookup.IsDynamic` (`lookup >= 0` and `lookup < 10000`):  
     $$\text{Rotation} = \text{Keyframes}[\text{frameIndex}].\text{Quaternions}[\text{lookup}]$$
   - Else:  
     $$\text{Rotation} = (0.0, 0.0, 0.0, 1.0)$$ (Identity Quaternion)

3. **Local Matrix Composition**:
   $$\mathbf{M}_{\text{local}} = \mathbf{M}_{\text{rotation}}(Q) \times \mathbf{M}_{\text{translation}}(P)$$

4. **World Matrix Hierarchy Propagation**:
   $$\mathbf{M}_{\text{world}}(\text{bone}) = \mathbf{M}_{\text{local}}(\text{bone}) \times \mathbf{M}_{\text{world}}(\text{ParentId})$$

---

## 6. Complete Parsing Algorithm (Pseudo-Code)

```python
def parse_anim_v5(binary_reader):
    # 1. Read Header (UTILITYLIB::ANIMATION_HEADER)
    version = binary_reader.read_uint32()
    assert version == 5, f"Expected anim version 5, got {version}"
    
    bone_name_table_version = binary_reader.read_uint32() # m_bone_name_table_version_number (1)
    framerate = binary_reader.read_float32()             # m_key_frames_per_second
    
    skel_name_len = binary_reader.read_int16()
    skeleton_name = binary_reader.read_string(skel_name_len) # m_skeleton_name
    
    total_play_time = binary_reader.read_float32()        # m_duration
    
    # 2. Read Bone Hierarchy Table
    bone_count = binary_reader.read_uint32()             # m_num_nodes
    bones = []
    for i in range(bone_count):
        name_len = binary_reader.read_int16()
        name = binary_reader.read_string(name_len)
        parent_id = binary_reader.read_int32()
        bones.append({
            "id": i,
            "name": name,
            "parent_id": parent_id
        })
        
    # 3. Read Remapping Tables
    translation_mappings = [binary_reader.read_int32() for _ in range(bone_count)]
    rotation_mappings = [binary_reader.read_int32() for _ in range(bone_count)]
    
    # 4. Read Dynamic Keyframe Payload Header
    anim_pos_count = binary_reader.read_int32()
    anim_rot_count = binary_reader.read_int32()
    frame_count = binary_reader.read_int32()
    
    frames = []
    if anim_pos_count > 0 or anim_rot_count > 0:
        for f in range(frame_count):
            # Read translations (12 bytes each)
            transforms = []
            for t in range(anim_pos_count):
                x = binary_reader.read_float32()
                y = binary_reader.read_float32()
                z = binary_reader.read_float32()
                transforms.append((x, y, z))
                
            # Read rotations (8 bytes each)
            quaternions = []
            scale = 1.0 / 32767.0
            for r in range(anim_rot_count):
                qx_raw = binary_reader.read_int16()
                qy_raw = binary_reader.read_int16()
                qz_raw = binary_reader.read_int16()
                qw_raw = binary_reader.read_int16()
                
                qx = qx_raw * scale
                qy = qy_raw * scale
                qz = qz_raw * scale
                qw = qw_raw * scale
                quaternions.append((qx, qy, qz, qw))
                
            frames.append({
                "transforms": transforms,
                "quaternions": quaternions
            })
            
    return {
        "version": version,
        "bone_name_table_version": bone_name_table_version,
        "framerate": framerate,
        "skeleton": skeleton_name,
        "play_time": total_play_time,
        "bones": bones,
        "translation_mappings": translation_mappings,
        "rotation_mappings": rotation_mappings,
        "frames": frames
    }
```
