# RigidModelV2 (.rigid_model_v2) File Format Specification
**Format Version:** Version 6 (Total War: ATTILA)  
**Target Game:** Total War: ATTILA (and compatible TW engine titles)  
**Byte Ordering:** Little-Endian  

---

## 1. Overview

The `.rigid_model_v2` (RMV2) format is Creative Assembly's proprietary binary container for 3D geometry, Level of Detail (LOD) definitions, mesh hierarchy, material declarations, textures, attachment points, and skeletal binding information. 

RMV2 Version 6 is specifically used by **Total War: ATTILA**.

### Key Characteristics
- **Multiple Level-of-Detail (LOD) Groups**: Stores 1 to 4+ LOD levels, each containing 1 or more mesh models.
- **Header & Model Offset Mapping**: Uses explicit global byte offsets to locate each LOD group and its contained meshes.
- **Flexible Material & Shader Binding**: Supports weighted skinning, static meshes, decal maps, dirt maps, terrain tiles, cloth, collision shapes, and custom parameters per mesh.
- **Half-Precision & Packed Data**: Stores positions and UV coordinates as IEEE 754 16-bit half-floats, normals/tangents/binormals as normalized 8-bit bytes, and bone weights as normalized 8-bit bytes.

---

## 2. File Layout & Architecture

An RMV2 Version 6 file consists of four primary sections in sequential binary order:

```
+-------------------------------------------------------------+
| 1. File Header (RmvFileHeader / MODEL_HEADER_V5)            |
|    - 140 bytes (0x8C)                                       |
+-------------------------------------------------------------+
| 2. LOD Headers Array (RIGID_LOD_HEADER_V2 x LodCount)       |
|    - 20 bytes (0x14) per LOD                                |
+-------------------------------------------------------------+
| 3. Mesh Models (for each LOD 0..LodCount-1)                 |
|    - Mesh 0: Common Header (80B) + Material Header + Verts  |
|               + Indices                                     |
|    - Mesh 1: Common Header (80B) + Material Header + Verts  |
|               + Indices                                     |
|    - ...                                                    |
+-------------------------------------------------------------+
```

---

## 3. Data Structures Specification

### 3.1 Primitive Types Reference

| Primitive Type | C/C++ Equivalent | Size (Bytes) | Description |
| :--- | :--- | :--- | :--- |
| `byte` / `uint8` | `unsigned char` | 1 | Unsigned 8-bit integer (`0` to `255`) |
| `sbyte` / `int8` | `char` | 1 | Signed 8-bit integer (`-128` to `127`) |
| `ushort` / `uint16` | `unsigned short` | 2 | Unsigned 16-bit Little-Endian integer (`0` to `65535`) |
| `short` / `int16` | `short` | 2 | Signed 16-bit Little-Endian integer |
| `uint` / `uint32` | `unsigned int` | 4 | Unsigned 32-bit Little-Endian integer |
| `int` / `int32` | `int` | 4 | Signed 32-bit Little-Endian integer |
| `float` / `float32` | `float` | 4 | IEEE 754 32-bit single-precision floating point |
| `half` / `float16` | `half` / `ushort` | 2 | IEEE 754 16-bit half-precision floating point |
| `char[N]` / `byte[N]` | `char[N]` | `N` | Fixed-length ASCII string / byte buffer |

---

### 3.2 File Header (`RmvFileHeader` / `MODEL_HEADER_V5`)

The file header starts at byte offset `0x00000000` and has a fixed size of **140 bytes (0x8C)**.

| Offset | Field Name | C/C++ Name | Data Type | Size (Bytes) | Description |
| :--- | :--- | :--- | :--- | :--- | :--- |
| `0x00` | `FileType` | `m_file_id` | `byte[4]` | 4 | File signature string, padded with nulls (e.g. `"RMV2"` or `"RM4V"`). |
| `0x04` | `Version` | `m_version` | `uint32` | 4 | File format version. Must equal `6` for Attila (`RMV2_V6`). |
| `0x08` | `LodCount` | `m_lod_count` | `uint32` | 4 | Number of Level-of-Detail (LOD) headers contained in the file. |
| `0x0C` | `SkeletonName` | `m_bone_table_name` | `byte[128]` | 128 | Fixed-length ASCII string identifying the base skeleton (e.g. `"humanoid01"`). Null-terminated/padded. |

**Total Header Size:** 140 bytes (0x8C).

---

### 3.3 LOD Header (`Rmv2LodHeader_V6` / `RIGID_LOD_HEADER_V2`)

Immediately following `RmvFileHeader` is an array of `LodCount` LOD headers. Each LOD header in Version 6 is **20 bytes (0x14)**.

| Offset | Field Name | C/C++ Name | Data Type | Size (Bytes) | Description |
| :--- | :--- | :--- | :--- | :--- | :--- |
| `+0x00` | `MeshCount` | `m_mesh_count` | `uint32` | 4 | Number of individual mesh models contained in this LOD level. |
| `+0x04` | `TotalLodVertexSize` | `m_total_lod_vertex_size` | `uint32` | 4 | Total size in bytes of all vertex payloads across all meshes in this LOD. |
| `+0x08` | `TotalLodIndexSize` | `m_total_lod_index_size` | `uint32` | 4 | Total size in bytes of all 16-bit index payloads across all meshes in this LOD. |
| `+0x0C` | `FirstMeshOffset` | `m_first_mesh_offset` | `uint32` | 4 | Absolute byte offset from the beginning of the file to the start of the first mesh model in this LOD. |
| `+0x10` | `LodCameraDistance` | `m_lod_distance` | `float32` | 4 | Camera distance threshold at which this LOD level becomes active in-game. |

**Total LOD Array Size:** `LodCount * 20` bytes.

---

### 3.4 Model / Mesh Section Architecture

Each mesh model consists of four contiguous binary components:
1. **Common Mesh Header** (`RmvCommonHeader` / `MESH_HEADER_V3`) — 80 bytes
2. **Material Header** (`IRmvMaterial` / `MESH_HEADER_V5` or variant) — Variable size (determined by `ModelTypeFlag` / `m_shader_flags`)
3. **Vertex Payload** (`VertexList`) — `VertexCount * VertexSize` bytes
4. **Index Payload** (`IndexList`) — `IndexCount * 2` bytes (16-bit unsigned integers)

#### Offsets Calculation Rules
Let `modelStartOffset` be the absolute file offset where a mesh model begins:
- **Material Header Offset:** `modelStartOffset + 80`
- **Vertex Payload Offset:** `modelStartOffset + VertexOffset`
- **Index Payload Offset:** `modelStartOffset + IndexOffset`
- **Total Mesh Section Size:** `MeshSectionSize = (80 + MaterialHeaderSize) + (VertexCount * VertexSize) + (IndexCount * 2)`

---

### 3.5 Common Mesh Header (`RmvCommonHeader` / `MESH_HEADER_V3`)

Each mesh model begins with a fixed 80-byte header.

| Offset | Field Name | C/C++ Name | Data Type | Size (Bytes) | Description |
| :--- | :--- | :--- | :--- | :--- | :--- |
| `+0x00` | `ModelTypeFlag` | `m_shader_flags` | `uint16` | 2 | Shader flag / material type enum (`RIGID_SHADERS` / `ModelMaterialEnum`). |
| `+0x02` | `RenderFlag` | `m_render_flags` | `uint16` | 2 | Flags controlling mesh rendering behavior. |
| `+0x04` | `MeshSectionSize` | `m_mesh_section_size` | `uint32` | 4 | Total byte size of this entire mesh model section (Header + Material + Vertices + Indices). |
| `+0x08` | `VertexOffset` | `m_vertex_offset` | `uint32` | 4 | Relative byte offset from `modelStartOffset` to the start of the vertex payload. |
| `+0x0C` | `VertexCount` | `m_vertex_count` | `uint32` | 4 | Total number of vertices in the mesh vertex payload. |
| `+0x10` | `IndexOffset` | `m_index_offset` | `uint32` | 4 | Relative byte offset from `modelStartOffset` to the start of the index payload. |
| `+0x14` | `IndexCount` | `m_index_count` | `uint32` | 4 | Total number of 16-bit indices (3 indices per triangle face). |
| `+0x18` | `BoundingBox` | `m_aabb[6]` | `RvmBoundingBox` | 24 | Axis-aligned bounding box (6 x `float32`: MinX, MinY, MinZ, MaxX, MaxY, MaxZ). |
| `+0x30` | `ShaderParams` | `m_lighting_constants_name` | `RmvShaderParams` | 32 | Shader parameter block (12B name + 10B unknown + 10B zero). |

**Total Size:** 80 bytes (0x50).

#### Sub-structures in Common Mesh Header

##### 1. `RvmBoundingBox` (24 bytes)
| Field | Data Type | Size (Bytes) | Description |
| :--- | :--- | :--- | :--- |
| `MinimumX` | `float32` | 4 | Minimum bounding coordinate along X axis |
| `MinimumY` | `float32` | 4 | Minimum bounding coordinate along Y axis |
| `MinimumZ` | `float32` | 4 | Minimum bounding coordinate along Z axis |
| `MaximumX` | `float32` | 4 | Maximum bounding coordinate along X axis |
| `MaximumY` | `float32` | 4 | Maximum bounding coordinate along Y axis |
| `MaximumZ` | `float32` | 4 | Maximum bounding coordinate along Z axis |

##### 2. `RmvShaderParams` (32 bytes)
| Field | Data Type | Size (Bytes) | Description |
| :--- | :--- | :--- | :--- |
| `_shaderName` | `byte[12]` | 12 | Fixed-length ASCII shader preset string (e.g. `"default_dry "`). |
| `UnknownValues` | `byte[10]` | 10 | Engine internal flags/values. |
| `AllZeroValues` | `byte[10]` | 10 | Padding/zero buffer. |

---

## 4. Material & Shader Headers

The material header immediately follows `RmvCommonHeader`. The parser identifies the material structure based on `ModelTypeFlag` / `m_shader_flags` (`RIGID_SHADERS` enum).

### 4.1 `RIGID_SHADERS` Enum Mapping Table

| Value (Hex / Dec) | Shader Enum Name | Material Header Format | Default Vertex Format |
| :--- | :--- | :--- | :--- |
| `0x00` (0) | `RS_STANDARD` | `MESH_HEADER_V2` | `WS_VF_STANDARD_RIGID_MESH_VERTEX` |
| `0x03` (3) | `RS_GRASS` | `MESH_HEADER_V2` | `WS_VF_RIGID_GRASS_VERTEX` |
| `0x06` (6) | `RS_TREE` | `MESH_HEADER_V2` | `WS_VF_TREE_VERTEX` |
| `0x07` (7) | `RS_LEAF` | `MESH_HEADER_V2` | `WS_VF_TREE_VERTEX` |
| `0x08` (8) | `RS_CAMERA_ALIGNED_BILLBOARD` | `BILLBOARD_MESH_HEADER` | `WS_VF_BILLBOARD_VERTEX` |
| `0x1A` (26) | `RS_NO_RENDER` | `MESH_HEADER_V5` | `WS_VF_STANDARD_RIGID_MESH_VERTEX` |
| `0x1B` (27) | `RS_STANDARD_SIMPLE` | `MESH_HEADER_V5` | `WS_VF_STANDARD_RIGID_MESH_VERTEX` |
| `0x1C` (28) | `RS_POINT_LIGHT` | `RIGID_POINT_LIGHT_HEADER_V2` | `WS_VF_STANDARD_RIGID_MESH_VERTEX` |
| `0x2F` (47) | `RS_TERRAIN` | `RIGID_TERRAIN_MESH_HEADER` | `WS_VF_STANDARD_RIGID_MESH_VERTEX` |
| `0x31` (49) | `RS_TERRAIN_CUSTOM_TILE` | `CUSTOM_TILE_MESH_HEADER` | `WS_VF_STANDARD_RIGID_MESH_VERTEX` |
| `0x3A` (58) | `RS_WEIGHTED_CLOTH_V5` | `WEIGHTED_CLOTH_MESH_HEADER_V5` | `WS_VF_WEIGHTED_2_BONES_PER_VERTEX` |
| `0x3B` (59) | `RS_WEIGHTED` | `MESH_HEADER_V5` | `WS_VF_WEIGHTED_2_BONES_PER_VERTEX` |
| `0x3C` (60) | `RS_VERTEX_CLOTH_V5` | `VERTEX_CLOTH_MESH_HEADER_V5` | `WS_VF_STANDARD_RIGID_MESH_VERTEX` |
| `0x3D` (61) | `RS_COLLISION` | `MESH_HEADER_V5` | `WS_VF_RIGID_COLLISION_MESH_VERTEX` |
| `0x3E` (62) | `RS_COLLISION_SHAPE_V5` | `COLLISION_SHAPE_HEADER_V5` | `WS_VF_RIGID_COLLISION_MESH_VERTEX` |
| `0x3F` (63) | `RS_STANDARD_TILED_DIRTMAP_V5` | `MESH_HEADER_V5` | `WS_VF_STANDARD_RIGID_MESH_VERTEX` |
| `0x40` (64) | `RS_STANDARD_AMBIENT_V5` | `MESH_HEADER_V5` | `WS_VF_STANDARD_RIGID_MESH_VERTEX` |
| `0x41` (65) | `RS_WEIGHTED_V5` | `MESH_HEADER_V5` | `WS_VF_WEIGHTED_2_BONES_PER_VERTEX` |
| `0x42` (66) | `RS_TERRAIN_V2` | `RIGID_TERRAIN_MESH_HEADER_V2` | `WS_VF_STANDARD_RIGID_MESH_VERTEX` |
| `0x43` (67) | `RS_PROJECTED_DECAL` | `PROJECTED_DECAL_HEADER` | `WS_VF_STANDARD_RIGID_MESH_VERTEX` |
| `0x44` (68) | `RS_STANDARD_V5` | `MESH_HEADER_V5` | `WS_VF_STANDARD_RIGID_MESH_VERTEX` |
| `0x45` (69) | `RS_GRASS_V5` | `MESH_HEADER_V5` | `WS_VF_RIGID_GRASS_VERTEX` |
| `0x46` (70) | `RS_WEIGHTED_SKIN_V5` | `MESH_HEADER_V5` | `WS_VF_WEIGHTED_2_BONES_PER_VERTEX` |
| `0x47` (71) | `RS_STANDARD_WITH_DECAL_V5` | `MESH_HEADER_V5` | `WS_VF_STANDARD_RIGID_MESH_VERTEX` |
| `0x48` (72) | `RS_STANDARD_WITH_DECAL_DIRTMAP_V5` | `MESH_HEADER_V5` | `WS_VF_STANDARD_RIGID_MESH_VERTEX` |
| `0x49` (73) | `RS_STANDARD_WITH_DIRTMAP_V5` | `MESH_HEADER_V5` | `WS_VF_STANDARD_RIGID_MESH_VERTEX` |
| `0x4A` (74) | `RS_TREE_V5` | `MESH_HEADER_V5` | `WS_VF_TREE_VERTEX` |
| `0x4B` (75) | `RS_LEAF_V5` | `MESH_HEADER_V5` | `WS_VF_TREE_VERTEX` |
| `0x4C` (76) | `RS_CAMERA_ALIGNED_BILLBOARD_V5` | `BILLBOARD_MESH_HEADER` | `WS_VF_BILLBOARD_VERTEX` |
| `0x4D` (77) | `RS_WEIGHTED_WITH_DECAL_V5` | `MESH_HEADER_V5` | `WS_VF_WEIGHTED_2_BONES_PER_VERTEX` |
| `0x4E` (78) | `RS_WEIGHTED_WITH_DECAL_DIRTMAP_V5` | `MESH_HEADER_V5` | `WS_VF_WEIGHTED_2_BONES_PER_VERTEX` |
| `0x4F` (79) | `RS_WEIGHTED_WITH_DIRTMAP_V5` | `MESH_HEADER_V5` | `WS_VF_WEIGHTED_2_BONES_PER_VERTEX` |
| `0x50` (80) | `RS_WEIGHTED_SKIN_DECAL_V5` | `MESH_HEADER_V5` | `WS_VF_WEIGHTED_2_BONES_PER_VERTEX` |
| `0x51` (81) | `RS_WEIGHTED_SKIN_DECAL_DIRTMAP_V5` | `MESH_HEADER_V5` | `WS_VF_WEIGHTED_2_BONES_PER_VERTEX` |
| `0x52` (82) | `RS_WEIGHTED_SKIN_DIRTMAP_V5` | `MESH_HEADER_V5` | `WS_VF_WEIGHTED_2_BONES_PER_VERTEX` |
| `0x53` (83) | `RS_WATER_V5` | `MESH_HEADER_V5` | `WS_VF_STANDARD_RIGID_MESH_VERTEX` |
| `0x54` (84) | `RS_UNLIT_V5` | `MESH_HEADER_V5` | `WS_VF_STANDARD_RIGID_MESH_VERTEX` |
| `0x55` (85) | `RS_WEIGHTED_UNLIT_V5` | `MESH_HEADER_V5` | `WS_VF_WEIGHTED_2_BONES_PER_VERTEX` |
| `0x56` (86) | `RS_TERRAIN_BLEND_V5` | `MESH_HEADER_V5` | `WS_VF_STANDARD_RIGID_MESH_VERTEX` |
| `0x57` (87) | `RS_PROJECTED_DECAL_V2` | `PROJECTED_DECAL_HEADER_V2` | `WS_VF_STANDARD_RIGID_MESH_VERTEX` |
| `0x5C` (92) | `RS_ROPE_V5` | `MESH_HEADER_V5` | `WS_VF_ROPE_VERTEX` |
| `0x5E` (94) | `RS_CAMPAIGN_VEGETATION_V5` | `MESH_HEADER_V5` | `WS_VF_RIGID_CAMPAIGN_VEGETATION_VERTEX` |
| `0x5F` (95) | `RS_PROJECTED_DECAL_V3` | `PROJECTED_DECAL_HEADER_V3` | `WS_VF_STANDARD_RIGID_MESH_VERTEX` |

---

### 4.2 Standard Weighted Material Header (`WeightedMaterialStruct` / `MESH_HEADER_V5` + Dynamic Payload)

Used by all standard models (`RS_STANDARD_V5`, `RS_WEIGHTED_V5`, `RS_WEIGHTED_SKIN_V5`, etc.).

#### 4.2.1 Fixed Header Block (`MESH_HEADER_V5`) — 660 bytes (0x294)

| Offset | Field Name | C/C++ Name | Data Type | Size (Bytes) | Description |
| :--- | :--- | :--- | :--- | :--- | :--- |
| `+0x000` | `_vertexType` | `m_vertex_format` | `uint16` | 2 | Vertex format enum (`WS_VERTEX_FORMAT`). |
| `+0x002` | `_modelName` | `m_name` | `byte[32]` | 32 | Fixed-length ASCII model/mesh name string. |
| `+0x022` | `_textureDir` | `m_texture_base` | `byte[256]` | 256 | Fixed-length ASCII relative texture directory path. |
| `+0x122` | `Filters` | `m_filters` | `byte[256]` | 256 | Filter string buffer (typically zero-filled). |
| `+0x222` | `PivotX` | `m_x_delta` | `float32` | 4 | Mesh pivot offset X coordinate. |
| `+0x226` | `PivotY` | `m_y_delta` | `float32` | 4 | Mesh pivot offset Y coordinate. |
| `+0x22A` | `PivotZ` | `m_z_delta` | `float32` | 4 | Mesh pivot offset Z coordinate. |
| `+0x22E` | `Matrix1` | `m_matrix1` | `matrix_43` | 48 | Transform matrix 0 (3 rows x 4 floats). |
| `+0x25E` | `Matrix2` | `m_matrix2` | `matrix_43` | 48 | Transform matrix 1 (3 rows x 4 floats). |
| `+0x28E` | `Matrix3` | `m_matrix3` | `matrix_43` | 48 | Transform matrix 2 (3 rows x 4 floats). |
| `+0x2C0` | `MatrixIndex` | `m_matrix_index` | `uint32` | 4 | Bone matrix index for rigid attachment. |
| `+0x2C4` | `ParentMatrixIndex` | `m_parent_matrix_index` | `uint32` | 4 | Parent bone matrix index (typically `-1`). |
| `+0x2C8` | `AttachmentPointCount` | `m_num_attach_points` | `uint32` | 4 | Number of attachment points in following array. |
| `+0x2CC` | `TextureCount` | `m_num_texture_params` | `uint32` | 4 | Number of texture parameters in following array. |
| `+0x2D0` | `StringParamCount` | `m_num_string_params` | `uint32` | 4 | Number of custom string parameters in following list. |
| `+0x2D4` | `FloatParamCount` | `m_num_float_params` | `uint32` | 4 | Number of custom float parameters in following list. |
| `+0x2D8` | `IntParamCount` | `m_num_int_params` | `uint32` | 4 | Number of custom int parameters in following list. |
| `+0x2DC` | `Vec4ParamCount` | `m_num_vec4_params` | `uint32` | 4 | Number of custom Vec4 parameters in following list. |
| `+0x2E0` | `PaddingArray` | `m_unused[124]` | `byte[124]` | 124 | Padding array buffer. |

*Note on `RmvTransform`:* `PivotX, Y, Z` + `Matrix1, 2, 3` form the 156-byte `RmvTransform` block.

---

#### 4.2.2 Dynamic Material Payload Arrays

Immediately following `MESH_HEADER_V5` are six dynamic arrays stored sequentially:

##### 1. Attachment Points Array (`MESH_ATTACH_POINT` x `AttachmentPointCount`) — 84 bytes each
| Field Name | C/C++ Name | Data Type | Size (Bytes) | Description |
| :--- | :--- | :--- | :--- | :--- |
| `_name` | `m_name` | `byte[32]` | 32 | ASCII attachment point name (e.g. `"point_weapon_01"`). |
| `Matrix` | `m_transform` | `matrix_43` | 48 | 3x4 local transform matrix. |
| `_boneIndex` | `m_node_index` | `uint32` / `int32` | 4 | Target skeleton bone index. |

##### 2. Textures Array (`PARAM_TEXTURE_ENTRY` x `TextureCount`) — 260 bytes each
| Field Name | C/C++ Name | Data Type | Size (Bytes) | Description |
| :--- | :--- | :--- | :--- | :--- |
| `TexureType` | `m_texture_id` | `int32` | 4 | Texture parameter enum (`TEXTURE_PARAM`). |
| `_path` | `m_texture` | `byte[256]` | 256 | Relative file path string to the `.dds` texture map. |

###### Complete `TEXTURE_PARAM` Enum Values:
- `0x0` (0): `TEXTURE_PARAM_DIFFUSE_COLOUR`
- `0x1` (1): `TEXTURE_PARAM_NORMAL`
- `0x2` (2): `TEXTURE_PARAM_DETAIL_NORMAL`
- `0x3` (3): `TEXTURE_PARAM_FACTION_MASK`
- `0x4` (4): `TEXTURE_PARAM_MATERIAL_MAP`
- `0x5` (5): `TEXTURE_PARAM_AMBIENT_OCCLUSION_UV2`
- `0x6` (6): `TEXTURE_PARAM_DISPLACEMENT_MAP`
- `0x7` (7): `TEXTURE_PARAM_DIRTMAP_UV2`
- `0x8` (8): `TEXTURE_PARAM_ALPHA_MASK`
- `0x9` (9): `TEXTURE_PARAM_DISSOLVE`
- `0xA` (10): `TEXTURE_PARAM_SKIN_MASK`
- `0xB` (11): `TEXTURE_PARAM_SPECULAR_COLOUR`
- `0xC` (12): `TEXTURE_PARAM_GLOSS_MAP`
- `0xD` (13): `TEXTURE_PARAM_DECAL_DIRTMAP`
- `0xE` (14): `TEXTURE_PARAM_DECAL_DIRTMASK`
- `0xF` (15): `TEXTURE_PARAM_DECAL_MASK`
- `0x10` (16): `TEXTURE_PARAM_DIFFUSE_BURN`
- `0x11` (17): `TEXTURE_PARAM_DIFFUSE_DAMAGE`
- `0x12` (18): `TEXTURE_PARAM_DIFFUSE_SP`
- `0x13` (19): `TEXTURE_PARAM_DIFFUSE_SU`
- `0x14` (20): `TEXTURE_PARAM_DIFFUSE_AU`
- `0x15` (21): `TEXTURE_PARAM_DIFFUSE_WI`
- `0x16` (22): `TEXTURE_PARAM_DIFFUSE_SNOW`

##### 3. String Parameters Array (`PARAM_STRING_ENTRY` x `StringParamCount`)
- `m_id`: `int32` (`STRING_PARAM` enum: `0` = `STRING_PARAM_FIRST`)
- `m_value`: Length-prefixed string

##### 4. Float Parameters Array (`PARAM_FLOAT_ENTRY` x `FloatParamCount`)
- `m_id`: `int32` (`FLOAT_PARAM` enum)
- `m_value`: `float32` (4 bytes)

###### `FLOAT_PARAM` Enum:
- `0x0`: `FLOAT_PARAM_TILE_INTERVAL_U`
- `0x1`: `FLOAT_PARAM_TILE_INTERVAL_V`
- `0x2`: `FLOAT_PARAM_MASS`
- `0x3`: `FLOAT_PARAM_FLEX`

##### 5. Int Parameters Array (`PARAM_INT_ENTRY` x `IntParamCount`)
- `m_id`: `int32` (`INT_PARAM` enum)
- `m_value`: `int32` (4 bytes)

###### `INT_PARAM` Enum:
- `0x0`: `INT_PARAM_ALPHA_MODE` (`0` = Opaque, `1` = Transparent)
- `0x1`: `INT_PARAM_RANDOM_TILE_U`
- `0x2`: `INT_PARAM_RANDOM_TILE_V`

##### 6. Vec4 Parameters Array (`PARAM_VEC4_ENTRY` x `Vec4ParamCount`)
- `m_id`: `int32` (`VEC4_PARAM` enum)
- `m_value`: 4 x `float32` (16 bytes: `X`, `Y`, `Z`, `W`)

###### `VEC4_PARAM` Enum:
- `0x0`: `VEC4_PARAM_UV_RECT`
- `0x1`: `VEC4_PARAM_COLOUR_0`
- `0x2`: `VEC4_PARAM_COLOUR_1`
- `0x3`: `VEC4_PARAM_COLOUR_2`

---

### 4.3 Alternative Material Header Definitions

Depending on shader type, non-standard headers are used instead of `MESH_HEADER_V5`:

#### 1. Projected Decal Header (`PROJECTED_DECAL_HEADER_V2`) — 288 bytes
- `m_texture_base`: `char[256]`
- `m_decal_center`: `Vec3` (12 bytes)
- `m_decal_scale`: `Vec3` (12 bytes)
- `m_decal_type`: `uint32` (4 bytes)
- `m_parallax_scale`: `float32` (4 bytes)
- `m_tiled`: `float32` (4 bytes)

#### 2. Collision Shape Header (`COLLISION_SHAPE_HEADER_V5`) — 4 bytes
- `m_shape`: `int32` (`0` = `SPHERE`, `1` = `ELLIPSE`, `2` = `BOX`, `3` = `CYLINDER`)

#### 3. Vertex Cloth Header (`VERTEX_CLOTH_MESH_HEADER_V5`) — 12 bytes
- `m_num_constraints`: `uint32`
- `m_num_vertices`: `uint32`
- `m_total_num_triangles`: `uint32`

#### 4. Weighted Cloth Header (`WEIGHTED_CLOTH_MESH_HEADER_V5`) — 8 bytes
- `m_num_bones`: `uint32`
- `m_num_shared_bones`: `uint32`

---

## 5. Vertex Format Definitions (`WS_VERTEX_FORMAT`)

The vertex payload layout is specified by `m_vertex_format` (`WS_VERTEX_FORMAT`).

### 5.1 `WS_VERTEX_FORMAT` Enum Reference

| Enum Value | Name | Vertex Struct | Size (Bytes) |
| :--- | :--- | :--- | :--- |
| `0x0` (0) | `WS_VF_STANDARD_RIGID_MESH_VERTEX` | `STANDARD_RIGID_MESH_VERTEX` | 32 |
| `0x1` (1) | `WS_VF_RIGID_COLLISION_MESH_VERTEX` | `RIGID_COLLISION_MESH_VERTEX` | 24 |
| `0x2` (2) | `WS_VF_RIGID_TEXTURE_BLEND_MESH_VERTEX` | `RIGID_TEXTURE_BLEND_MESH_VERTEX` | 28 |
| `0x3` (3) | `WS_VF_WEIGHTED_2_BONES_PER_VERTEX` | `WEIGHTED_2_BONES_PER_VERTEX` | 28 |
| `0x4` (4) | `WS_VF_WEIGHTED_4_BONES_PER_VERTEX` | `WEIGHTED_4_BONES_PER_VERTEX` | 32 |
| `0x5` (5) | `WS_VF_RIGID_GRASS_VERTEX` | `RIGID_GRASS_VERTEX` | 32 |
| `0x6` (6) | `WS_VF_TREE_VERTEX` | `RIGID_TREE_VERTEX` | 56 |
| `0x7` (7) | `WS_VF_BILLBOARD_VERTEX` | `RIGID_BILLBOARD_VERTEX` | 12 |
| `0x8` (8) | `WS_VF_BASIC_VERTEX` | `RIGID_BASIC_VERTEX` | 12 |
| `0x9` (9) | `WS_VF_WEIGHTED_1_BONE_PER_VERTEX` | `WEIGHTED_2_BONES_PER_VERTEX` | 28 |
| `0xA` (10) | `WS_VF_WEIGHTED_3_BONES_PER_VERTEX` | `WEIGHTED_4_BONES_PER_VERTEX` | 32 |
| `0xB` (11) | `WS_VF_ROPE_VERTEX` | `RIGID_ROPE_VERTEX` | 44 |
| `0xC` (12) | `WS_VF_RIGID_CAMPAIGN_VEGETATION_VERTEX` | `RIGID_CAMPAIGN_VEGETATION_VERTEX` | 16 |

---

### 5.2 Primary Vertex Layouts

#### 1. Standard Static Mesh Vertex (`STANDARD_RIGID_MESH_VERTEX`) — 32 Bytes
| Offset | Field | Type | Description |
| :--- | :--- | :--- | :--- |
| `+0x00` | `position` | `float16[4]` | 4 x half-floats (`X, Y, Z, W`) |
| `+0x08` | `texture_uv` | `float16[2]` | 2 x half-floats (`U, V`) |
| `+0x0C` | `texture_uv1` | `float16[2]` | 2 x half-floats (`U1, V1` extra UVs) |
| `+0x10` | `normal` | `byte[4]` | 4 x packed bytes (normal $X, Y, Z, W$, $X/Z$ swapped on read) |
| `+0x14` | `tangent` | `byte[4]` | 4 x packed bytes (tangent $X, Y, Z, W$, $X/Z$ swapped on read) |
| `+0x18` | `binormal` | `byte[4]` | 4 x packed bytes (binormal $X, Y, Z, W$, $X/Z$ swapped on read) |
| `+0x1C` | `colour` | `byte[4]` | 4 x RGBA vertex color bytes |

#### 2. Weighted 2-Bone Vertex (`WEIGHTED_2_BONES_PER_VERTEX`) — 28 Bytes
| Offset | Field | Type | Description |
| :--- | :--- | :--- | :--- |
| `+0x00` | `t_pose_pos` | `float16[4]` | 4 x half-floats ($X, Y, Z, W$) in T-pose |
| `+0x08` | `bone_indices_and_weight` | `byte[4]` | `[BoneIdx0, BoneIdx1, Weight0, Unused]` (Weight1 = $255 - \text{Weight0}$) |
| `+0x0C` | `t_pose_normal` | `byte[4]` | 4 x packed byte normal vector |
| `+0x10` | `uv` | `float16[2]` | 2 x half-floats ($U, V$) |
| `+0x14` | `t_pose_binormal` | `byte[4]` | 4 x packed byte binormal vector |
| `+0x18` | `t_pose_tangent` | `byte[4]` | 4 x packed byte tangent vector |

#### 3. Weighted 4-Bone Vertex (`WEIGHTED_4_BONES_PER_VERTEX`) — 32 Bytes
| Offset | Field | Type | Description |
| :--- | :--- | :--- | :--- |
| `+0x00` | `t_pose_pos` | `float16[4]` | 4 x half-floats ($X, Y, Z, W$) |
| `+0x08` | `four_bone_indices` | `byte[4]` | 4 x bone indices `[BoneIdx0, BoneIdx1, BoneIdx2, BoneIdx3]` |
| `+0x0C` | `three_bone_weights` | `byte[4]` | 4 x weights `[Weight0, Weight1, Weight2, Weight3]` (normalized by 255.0) |
| `+0x10` | `t_pose_normal` | `byte[4]` | 4 x packed byte normal vector |
| `+0x14` | `uv` | `float16[2]` | 2 x half-floats ($U, V$) |
| `+0x18` | `t_pose_binormal` | `byte[4]` | 4 x packed byte binormal vector |
| `+0x1C` | `t_pose_tangent` | `byte[4]` | 4 x packed byte tangent vector |

---

## 6. Index Data Payload

The index buffer directly follows the vertex buffer at offset `modelStartOffset + IndexOffset`.

- **Element Type:** `ushort` (`uint16`, Little-Endian)
- **Element Size:** 2 bytes per index
- **Total Payload Size:** `IndexCount * 2` bytes
- **Primitive Topology:** Triangle List (`Triangle 0 = [Index[0], Index[1], Index[2]]`, `Triangle 1 = [Index[3], Index[4], Index[5]]`, etc.)

---

## 7. Complete Parsing Algorithm (Pseudo-Code)

```python
def parse_rmv2_v6(binary_reader):
    # 1. Read File Header (140 bytes)
    file_type = binary_reader.read_fixed_string(4)     # "RMV2"
    version = binary_reader.read_uint32()             # Must be 6
    lod_count = binary_reader.read_uint32()
    skeleton_name = binary_reader.read_fixed_string(128)
    
    assert version == 6, f"Unsupported version {version}"

    # 2. Read LOD Headers (LodCount x 20 bytes)
    lod_headers = []
    for i in range(lod_count):
        lod = {
            "mesh_count": binary_reader.read_uint32(),
            "total_vert_size": binary_reader.read_uint32(),
            "total_index_size": binary_reader.read_uint32(),
            "first_mesh_offset": binary_reader.read_uint32(),
            "camera_distance": binary_reader.read_float32()
        }
        lod_headers.append(lod)

    # 3. Read Meshes for each LOD
    lods_data = []
    for lod_idx, lod in enumerate(lod_headers):
        models = []
        current_mesh_offset = lod["first_mesh_offset"]
        
        for mesh_idx in range(lod["mesh_count"]):
            binary_reader.seek(current_mesh_offset)
            
            # 3.1 Common Mesh Header (80 bytes)
            shader_flag = binary_reader.read_uint16()
            render_flag = binary_reader.read_uint16()
            mesh_section_size = binary_reader.read_uint32()
            vertex_offset = binary_reader.read_uint32()
            vertex_count = binary_reader.read_uint32()
            index_offset = binary_reader.read_uint32()
            index_count = binary_reader.read_uint32()
            bounding_box = binary_reader.read_floats(6)
            shader_params = binary_reader.read_bytes(32)
            
            # 3.2 Read Material Header
            material_start = current_mesh_offset + 80
            vertex_start = current_mesh_offset + vertex_offset
            index_start = current_mesh_offset + index_offset
            
            # Read MESH_HEADER_V5
            vertex_format = binary_reader.read_uint16()
            model_name = binary_reader.read_fixed_string(32)
            texture_dir = binary_reader.read_fixed_string(256)
            filters = binary_reader.read_fixed_string(256)
            pivot = (binary_reader.read_float32(), binary_reader.read_float32(), binary_reader.read_float32())
            matrix1 = binary_reader.read_floats(12)
            matrix2 = binary_reader.read_floats(12)
            matrix3 = binary_reader.read_floats(12)
            matrix_idx = binary_reader.read_uint32()
            parent_matrix_idx = binary_reader.read_uint32()
            
            attachment_count = binary_reader.read_uint32()
            texture_count = binary_reader.read_uint32()
            string_param_count = binary_reader.read_uint32()
            float_param_count = binary_reader.read_uint32()
            int_param_count = binary_reader.read_uint32()
            vec4_param_count = binary_reader.read_uint32()
            binary_reader.skip(124) # PaddingArray
            
            # Read Dynamic Material Payload
            attachment_points = [binary_reader.read_attachment_point() for _ in range(attachment_count)]
            textures = [binary_reader.read_rmv_texture() for _ in range(texture_count)]
            string_params = [binary_reader.read_string_param() for _ in range(string_param_count)]
            float_params = [binary_reader.read_float_param() for _ in range(float_param_count)]
            int_params = [binary_reader.read_int_param() for _ in range(int_param_count)]
            vec4_params = [binary_reader.read_vec4_param() for _ in range(vec4_param_count)]
            
            # 3.3 Read Vertices
            binary_reader.seek(vertex_start)
            vertices = []
            for v_idx in range(vertex_count):
                if vertex_format == 0:   # WS_VF_STANDARD_RIGID_MESH_VERTEX
                    v = binary_reader.read_static_vertex()
                elif vertex_format == 3: # WS_VF_WEIGHTED_2_BONES_PER_VERTEX
                    v = binary_reader.read_weighted2_vertex()
                elif vertex_format == 4: # WS_VF_WEIGHTED_4_BONES_PER_VERTEX
                    v = binary_reader.read_weighted4_vertex()
                vertices.append(v)
                
            # 3.4 Read Indices
            binary_reader.seek(index_start)
            indices = [binary_reader.read_uint16() for _ in range(index_count)]
            
            models.append({
                "vertices": vertices,
                "indices": indices,
                "textures": textures,
                "attachment_points": attachment_points
            })
            
            current_mesh_offset += mesh_section_size
            
        lods_data.append(models)
        
    return lods_data
```
