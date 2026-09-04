# Total War *.CS2 File Format Specification

**Format Version:** Intermediate Model/Scene Asset Format  
**Target Engine:** Total War (Creative Assembly 3ds Max / Intermediate Exporter Format)  
**Byte Ordering:** Little-Endian  
**String Encoding:** Length-Prefixed UTF-16 Unicode (`uint16` character count followed by UTF-16LE characters)

---

## 1. Overview & Toolchain Context

The `.CS2` file format is Creative Assembly's intermediate binary scene, mesh, and animation export format. It serves as the primary bridge between 3D authoring applications (such as 3ds Max via `cas2_exporter.dle`) and Creative Assembly's model compilation pipeline (processed via Assembly Kit tools such as `BOB_Cs2.AssemblyKit.dll`).

```
+--------------------------+        +-----------------------------------+        +--------------------------------+
|      3ds Max Exporter    |        |        Intermediate Format        |        |    CA Assembly Kit (BOB_Cs2)   |
|   (cas2_exporter.dle)    | =====> |             *.CS2                 | =====> | Converts to game runtime formats|
|  [CAS2_LOADER Namespace] |        | (Header + Metadata + Node Arrays) |        | (.rigid_model_v2, .cs2.parsed) |
+--------------------------+        +-----------------------------------+        +--------------------------------+
```

### Key Toolchain References & Native C++ Architecture
- **3ds Max Exporter Plugin (`cas2_exporter.dle`)**: Defines the source C++ object model under the `CAS2_LOADER` namespace.
- **Assembly Kit Processor (`BOB_Cs2.AssemblyKit.dll`)**: Validates binary structure using internal assertion tags (`&CAS`, `&GEOM`, `&TRI_OBJ`, `&MATERIALS`, `&BONE_MAPPINGS`) during conversion.
- **Attila Engine Runtime (`Attila.h`)**: Consumes compiled outputs into `EMPIREUTILITY` building descriptors (`BUILDING_PIECE_DESCR`, `DESTRUCTION_LEVEL`) and `WARSCAPE` scene nodes (`WS_SCENE_NODE_RIGID_V2`, `WS_SCENE_NODE_VARIANT_MESH`).

---

## 2. High-Level File Architecture

A `.CS2` file consists of a main binary header, global metadata blocks, and sequential arrays of scene nodes ordered by their node types.

```
+-------------------------------------------------------------+
| 1. Header (HEADER)                                          |
|    - Magic File Format Signature (4 chars)                  |
|    - Header Size                                            |
|    - Exporter Version Number (float32)                      |
|    - Feature Flags Bitmask (uint32)                         |
|    - Exporter Plugin Identifier String (UTF-16)             |
|    - Export Details String (UTF-16)                         |
+-------------------------------------------------------------+
| 2. Global Metadata Block (GLOBAL_METADATA_BLOCK)            |
|    - Scene Info & Node Counts (SCENE_BLOCK_DATA)            |
|    - Timeline & FPS Data (TIMELINE_BLOCK_DATA)              |
|    - Morph & Spline Keyframe Data (MORPH_AND_SPLINE_BLOCK)  |
+-------------------------------------------------------------+
| 3. Camera Nodes Array (NODE x CamerasCount)                 |
+-------------------------------------------------------------+
| 4. Rigid Model Nodes Array (NODE x RigidModelsCount)        |
+-------------------------------------------------------------+
| 5. Skinned Weighted Model Nodes Array (NODE x WeightedCount)|
+-------------------------------------------------------------+
| 6. Vector Line Nodes Array (NODE x LinesCount)              |
+-------------------------------------------------------------+
| 7. Dummy Nodes Array (NODE x DummiesCount)                  |
+-------------------------------------------------------------+
| 8. Scene Root Node (NODE)                                   |
+-------------------------------------------------------------+
| 9. Material Nodes Array (NODE x MaterialsCount)             |
+-------------------------------------------------------------+
| 10. Instance Nodes Array (NODE x InstancesCount)            |
+-------------------------------------------------------------+
```

---

## 3. Enumerations & Exporter Class Mappings

### 3.1 Node Types (`NODE_TYPE`) & C++ Class Mappings
| Value | Enum Identifier | Exporter C++ Class (`cas2_exporter.dle`) | Description |
| :--- | :--- | :--- | :--- |
| `5` | `LIGHT` | `CAS2_LOADER::CAS2_LIGHT` | Light source node (Ambient, Directional, Point, Spot) |
| `6` | `CAMERA` | `CAS2_LOADER::CAS2_CAMERA` | Camera node with FOV, DOF, and motion blur parameters |
| `7` | `RIGID_MODEL` | `CAS2_LOADER::CAS2_RIGID` / `CAS2_GEOM_OBJECT` | Static rigid geometry mesh node |
| `10` | `WEIGHTED_MODEL` | `CAS2_LOADER::CAS2_WEIGHTED_MESH` | Skinned mesh node with vertex bone weights |
| `11` | `LINE` | `CAS2_LOADER::CAS2_BEZIER_SPLINE_OBJECT` | 3D vector spline / line path node |
| `12` | `SCENE_ROOT` | `CAS2_LOADER::CAS2_MATRIX_HIERARCHY` | Hierarchy tree root node & keyframe animation tracks |
| `13` | `MATERIAL` | `CAS2_LOADER::CAS2_MATERIAL` | Surface material definition node |
| `16` | `INSTANCE_NO_MATERIAL` | `CAS2_LOADER::CAS2_GEOM_INSTANCE` | Geometry instance reusing an existing mesh node |
| `17` | `DUMMY` | `CAS2_LOADER::CAS2_HELPER` / `CAS2_ENTITY` | Pivot / helper / anchor dummy node |
| `18` | `INSTANCE_OVERRIDE_MATERIAL` | `CAS2_GEOM_INSTANCE_DIFFERING_MATERIALS` | Geometry instance with custom material override |

### 3.2 Material Types (`MATERIAL_TYPE`) & C++ Class Mappings
| Value | Enum Identifier | Exporter C++ Class | Description |
| :--- | :--- | :--- | :--- |
| `0` | `MATERIAL_TYPE_DEFAULT` | `CAS2_LOADER::CAS2_STANDARD_MATERIAL` | Legacy 3ds Max standard fixed-function material |
| `1` | `MATERIAL_TYPE_DIRECTX` | `CAS2_LOADER::CAS2_SHADER_MATERIAL` | Modern HLSL FX shader-driven material |

### 3.3 Attribute Data Types (`ATTRIBUTE_TYPE`)
| Value | Enum Identifier | Exporter Animatable Type | Description |
| :--- | :--- | :--- | :--- |
| `0` | `ATTRIBUTE_TYPE_FLOAT` | `CAS2_ANIMATABLE_FLOAT32` | 32-bit single-precision float |
| `1` | `ATTRIBUTE_TYPE_STRING` | `CAS2_NAMED_STRING_ARRAY` | Length-prefixed UTF-16 string |
| `3` | `ATTRIBUTE_TYPE_VEC3` | `CAS2_ANIMATABLE_VECTOR_3` | 3D Vector (`x, y, z` floats) |
| `8` | `ATTRIBUTE_TYPE_INT` | `CAS2_ANIMATABLE_INT32` | 32-bit integer |
| `9` | `ATTRIBUTE_TYPE_VEC4` | `CAS2_ANIMATABLE_VECTOR_4` | 4D Vector / Quaternion (`x, y, z, w`) |

---

## 4. Fundamental & Helper Data Structures

### 4.1 `UTF16_STRING`
Binary length-prefixed UTF-16 string:
| Offset | Field Name | Data Type | Size (Bytes) | Description |
| :--- | :--- | :--- | :--- | :--- |
| `+0x00` | `Length` | `uint16` | 2 | Character count (`Length`). |
| `+0x02` | `Data` | `wchar_t[Length]` | `Length * 2` | Little-Endian UTF-16 character buffer. |

### 4.2 Vectors & Bounding Boxes
- **`VEC3`** (12 bytes): `float32 X`, `float32 Y`, `float32 Z`
- **`VEC4`** (16 bytes): `float32 X`, `float32 Y`, `float32 Z`, `float32 W`
- **`NODE_BOUNDING_BOX`** (`CAS2_LOADER::CAS2_BOUNDING_BOX`, 24 bytes):
  - `MinX`, `MinY`, `MinZ` (`float32[3]`, 12 bytes)
  - `MaxX`, `MaxY`, `MaxZ` (`float32[3]`, 12 bytes)

### 4.3 Geometry & Line Primitives
- **`TRIANGLE`** (`CAS2_LOADER::CAS2_CARD32_TRIPLE`, 12 bytes): `uint32 Index1`, `uint32 Index2`, `uint32 Index3`
- **`LINE_SEGMENT`** (8 bytes): `uint32 StartVertexIndex`, `uint32 EndVertexIndex`
- **`BONE_WEIGHT`** (`CAS2_LOADER::CAS2_BONE_WEIGHT_DATA`, 8 bytes): `uint32 BoneId`, `float32 Weight`
- **`FLOAT_ARRAY`**: `uint32 ArraySize` + `float32 ArrayItem[ArraySize]`
- **`INT_ARRAY`**: `uint32 ArraySize` + `int32 ArrayItem[ArraySize]`

---

## 5. Header & Global Metadata Specification

### 5.1 `HEADER` Structure (`CAS2_LOADER::CAS2`)
| Offset | Field Name | Data Type | Size (Bytes) | Description |
| :--- | :--- | :--- | :--- | :--- |
| `+0x00` | `FileFormat` | `char[4]` | 4 | Magic signature bytes (`"CS2 "` / `"CAS2"`) |
| `+0x04` | `HeaderSize` | `uint32` | 4 | Total size of header block |
| `+0x08` | `ExporterVersion` | `float32` | 4 | Exporter Format Version (`VERSION_NUMBER` e.g. `1.0` / `0.02f`) |
| `+0x0C` | `FeatureFlags` | `uint32` | 4 | Format Feature Flags Bitmask (Skinned flags, Anim flags, Up-Axis) |
| `+0x10` | `Plugin` | `UTF16_STRING` | Variable | Exporter plugin string (e.g. `"cas2_exporter"`) |
| Variable | `Details` | `UTF16_STRING` | Variable | Exporter details & timestamp string |

### 5.2 `GLOBAL_METADATA_BLOCK` Assembly
Contains three sequential metadata chunks describing scene composition, bounds, and global animation sequences.

#### 1. `SCENE_BLOCK_DATA` (Scene Info Table)
| Field Name | Data Type | Size (Bytes) | Description |
| :--- | :--- | :--- | :--- |
| `BlockSize` | `uint32` | 4 | Total size of scene block |
| `FormatCompatibilityVersion` | `uint32` | 4 | Format compatibility version integer |
| `ObjectTypesCount` | `uint32` | 4 | Number of unique object types |
| `LightsCount` | `uint32` | 4 | Number of light nodes (`CAS2_LIGHT`) |
| `CamerasCount` | `uint32` | 4 | Number of camera nodes (`CAS2_CAMERA`) |
| `RigidModelsCount` | `uint32` | 4 | Number of rigid model nodes (`CAS2_RIGID`) |
| `TotalSceneVertexCount` | `uint64` | 8 | Total scene vertex count summary (`&NVIDIA_VERTS`) |
| `WeightedModelsCount` | `uint32` | 4 | Number of weighted/skinned model nodes (`CAS2_WEIGHTED_MESH`) |
| `LinesCount` | `uint32` | 4 | Number of vector line nodes (`CAS2_BEZIER_SPLINE_OBJECT`) |
| `DummiesCount` | `uint32` | 4 | Number of dummy/pivot nodes (`CAS2_HELPER`) |
| `MaterialsCount` | `uint32` | 4 | Number of material nodes (`CAS2_MATERIAL`) |
| `TotalSceneTriangleCount` | `uint64` | 8 | Total scene triangle count summary (`&NVIDIA_TRIS`) |
| `InstancesCount` | `uint32` | 4 | Number of instanced nodes (`CAS2_GEOM_INSTANCE`) |
| `SceneBBoxAndWorldMatrix` | `byte[44]` | 44 | Global Scene BBOX (24B) + Up-Axis Transform Matrix (20B) |

#### 2. `TIMELINE_BLOCK_DATA` (`UNKNOWN_BLOCK2_DATA`)
| Field Name | Data Type | Size (Bytes) | Description |
| :--- | :--- | :--- | :--- |
| `BlockSize` | `uint32` | 4 | Total byte length of block 2 |
| `FrameRate_FPS` | `uint32` | 4 | Timeline frame rate / FPS resolution ticks |
| `StartFrameTime` | `float32` | 4 | Start timeline frame / animation timestamp (`&ANIM_TIME_RANGE`) |
| `EndFrameTime` | `float32` | 4 | End timeline frame / animation timestamp (`&DURATION`) |
| `TimelineTrackMetadata` | `byte[BlockSize - 16]` | `BlockSize - 16` | Global timeline track metadata |

#### 3. `MORPH_AND_SPLINE_BLOCK_DATA` (`UNKNOWN_BLOCK3_DATA`)
| Field Name | Data Type | Size (Bytes) | Description |
| :--- | :--- | :--- | :--- |
| `BlockSize` | `uint32` | 4 | Total byte length of block 3 |
| `MorphTrackFlags` | `uint32` | 4 | Morph target & spline track flags |
| `MorphSplineTrackCount` | `uint32` | 4 | Count of animation sub-elements / morph target tracks |
| *Track Items Loop* | — | Variable | `MorphSplineTrackCount` entries: 3 x `int32` (`TrackId1..3`), `MorphKeyframeValues` (`FLOAT_ARRAY`), `MorphVertexIndices` (`INT_ARRAY`). |

---

## 6. Node Attributes System (`NODE_ATTRIBUTES_ARRAY`)

Nodes store user-defined properties in a structured attributes array (`NODE_ATTRIBUTES_ARRAY`). The block contains 5 sub-arrays parsed sequentially:

```
NODE_ATTRIBUTES_ARRAY
├── StringAttributes  (uint32 AttributesCount + NODE_ATTRIBUTE_STRING[])
├── IntegerAttributes (uint32 AttributesCount + NODE_ATTRIBUTE_INTEGER[])
├── FloatAttributes   (uint32 AttributesCount + NODE_ATTRIBUTE_FLOAT[])
├── Vec3Attributes    (uint32 AttributesCount + NODE_ATTRIBUTE_VEC3[])
└── Vec4Attributes    (uint32 AttributesCount + NODE_ATTRIBUTE_VEC4[])
```

### Attribute Structure Breakdown

1. **`NODE_ATTRIBUTE_STRING`**:
   - `Name`: `UTF16_STRING`
   - `DataType`: `ATTRIBUTE_TYPE` (`uint32` = 1)
   - `Value`: `UTF16_STRING`

2. **`NODE_ATTRIBUTE_INTEGER`**:
   - `Name`: `UTF16_STRING`
   - `InterpolationMode`: `uint32` (`0`=Static, `1`=Linear, `2`=Slerp, `5`=RLE)
   - `AttributeType`: `ATTRIBUTE_TYPE` (`uint32` = 8)
   - `NumKeys`: `uint32` (Keyframe count in track)
   - `StartFrame`: `uint32` (Track start frame timestamp)
   - `EndFrame`: `uint32` (Track end frame timestamp)
   - `LoopFlags`: `uint32` (Looping & extrapolation flags)
   - `ReservedFlags`: `uint32` (Quality & compression flags)
   - `Value`: `uint32`

3. **`NODE_ATTRIBUTE_FLOAT`**:
   - `Name`: `UTF16_STRING`
   - `InterpolationMode`: `uint32`
   - `AttributeType`: `ATTRIBUTE_TYPE` (`uint32` = 0)
   - `NumKeys`: `uint32`
   - `StartFrame`: `uint32`
   - `EndFrame`: `uint32`
   - `LoopFlags`: `uint32`
   - `ReservedFlags`: `uint32`
   - `Value`: `float32`

4. **`NODE_ATTRIBUTE_VEC3`**:
   - `Name`: `UTF16_STRING`
   - `InterpolationMode`: `uint32`
   - `AttributeType`: `ATTRIBUTE_TYPE` (`uint32` = 3)
   - `NumKeys`: `uint32`
   - `StartFrame`: `uint32`
   - `EndFrame`: `uint32`
   - `LoopFlags`: `uint32`
   - `ReservedFlags`: `uint32`
   - `ValueX`, `ValueY`, `ValueZ`: 3 x `float32` (12 bytes)

5. **`NODE_ATTRIBUTE_VEC4`**:
   - `Name`: `UTF16_STRING`
   - `InterpolationMode`: `uint32`
   - `AttributeType`: `ATTRIBUTE_TYPE` (`uint32` = 9)
   - `NumKeys`: `uint32`
   - `StartFrame`: `uint32`
   - `EndFrame`: `uint32`
   - `LoopFlags`: `uint32`
   - `ReservedFlags`: `uint32`
   - `ValueX`, `ValueY`, `ValueZ`, `ValueW`: 4 x `float32` (16 bytes)

---

## 7. Node Structures (`NODE`)

Every node begins with a uniform 8-byte header:
| Offset | Field Name | Data Type | Size (Bytes) | Description |
| :--- | :--- | :--- | :--- | :--- |
| `+0x00` | `NodeDataLength` | `uint32` | 4 | Total byte payload length of node |
| `+0x04` | `NodeType` | `NODE_TYPE` | 4 | Type of node |

### 7.1 Rigid Model Node (`NodeType == RIGID_MODEL` / `7`)
Static 3D mesh node (`CAS2_LOADER::CAS2_RIGID`).

| Field Name | Data Type | Description |
| :--- | :--- | :--- |
| `NodeName` | `UTF16_STRING` | Name of model node |
| `NodeMetadataString` | `UTF16_STRING` | Model metadata string |
| `UserDefinedProperties` | `UTF16_STRING` | User UDP property block |
| `NodeIndex` | `uint32` | Unique index of node |
| `Attributes` | `NODE_ATTRIBUTES_ARRAY` | Node attributes block |
| `GeometryDataCount` | `uint32` | Number of geometry data chunks |

#### Inside Each Geometry Data Chunk (`GeometryDataCount` iterations):
1. `GeometryHeaderPadding`: `byte[12]` (12 bytes alignment padding)
2. `BoundingBoxExtentFloats`: `FLOAT_ARRAY`
3. `BoundingBoxCount`: `uint32`
4. `BoundingBox`: `NODE_BOUNDING_BOX[BoundingBoxCount]`
5. `LinesCount`: `uint32`
6. `LineData`: `LINE_DATA[LinesCount]`
7. `UVWChannelCount`: `uint32`
8. `UVWChannelId`: `uint32[UVWChannelCount]`
9. `Vertices`: `VERTEX_DATA_RIGID_ARRAY`:
   - `vertexCount`: `uint32`
   - `vertex`: Array of `VERTEX_DATA_RIGID`:
     - `Position`: `VEC3` (12 bytes)
     - `Normal`: `VEC3` (12 bytes)
     - `Color`: `VEC4` (16 bytes)
     - `TexCoordCount`: `uint32`
     - `TexCoords`: `VEC3[TexCoordCount]` (12 bytes per UV channel)
     - `VertexAO_Or_MorphWeight`: `float32` (Vertex AO scalar / Morph weight)
10. `SubMeshArray`: `SUBMESH_ARRAY`:
    - `SubMeshesCount`: `uint32`
    - `SubMesh`: Array of `SUBMESH` (`CAS2_TRI_SUB_OBJECT`):
      - `Triangles`: `TRIANGLE_ARRAY` (`uint32 triangleCount` + `TRIANGLE[triangleCount]`)
      - `MaterialId`: `int32`
11. `VertexColorChannelFlags`: `int32` (Vertex color / alpha channel configuration flags)

---

### 7.2 Weighted Model Node (`NodeType == WEIGHTED_MODEL` / `10`)
Skinned mesh node (`CAS2_LOADER::CAS2_WEIGHTED_MESH`).

Same structure as `RIGID_MODEL`, except the vertex array uses **`VERTEX_DATA_WEIGHTED_ARRAY`** (`CAS2_WEIGHTED_MESH_VERT`):
- `vertexCount`: `uint32`
- `vertex`: Array of `VERTEX_DATA_WEIGHTED`:
  - `Position`: `VEC3`
  - `Normal`: `VEC3`
  - `Color`: `VEC4`
  - `TexCoordCount`: `uint32`
  - `TexCoords`: `VEC3[TexCoordCount]`
  - `VertexAO_Or_MorphWeight`: `float32`
  - `BonesCount`: `uint32`
  - `BoneWeight`: Array of `BONE_WEIGHT[BonesCount]` (`uint32 BoneId`, `float32 Weight`)
  - `Position2`: `VEC3` (Unskinned base-pose position)
  - `Normal2`: `VEC3` (Unskinned base-pose normal)

---

### 7.3 Line Node (`NodeType == LINE` / `11`)
Vector spline node (`CAS2_LOADER::CAS2_BEZIER_SPLINE_OBJECT`).

| Field Name | Data Type | Description |
| :--- | :--- | :--- |
| `NodeName` | `UTF16_STRING` | Name of line node |
| `NodeMetadataString` | `UTF16_STRING` | Metadata string |
| `UserDefinedProperties` | `UTF16_STRING` | UDP string |
| `NodeIndex` | `uint32` | Node index |
| `Attributes` | `NODE_ATTRIBUTES_ARRAY` | Node attributes |
| `GeometryDataCount` | `uint32` | Count of line geometry chunks |
| *Geometry Chunk Loop* | — | Contains `GeometryHeaderPadding[12]`, `BoundingBoxExtentFloats`, `BoundingBox` array, `LinesCount`, `LINE_DATA[LinesCount]`, and `VertexColorChannelFlags`. |

#### `LINE_DATA` Structure:
- `LineVertices`: `VERTEX_DATA_LINE_ARRAY` (`uint32 VertexCount` + `VEC3 Position[VertexCount]`)
- `LineSegments`: `LINE_SEGMENTS_ARRAY` (`uint32 LineSegmentsCount` + `LINE_SEGMENT[LineSegmentsCount]`)

---

### 7.4 Scene Root Node (`NodeType == SCENE_ROOT` / `12`)
Transformation hierarchy & skeletal keyframe track root (`CAS2_LOADER::CAS2_MATRIX_HIERARCHY`).

| Field Name | Data Type | Size (Bytes) | Description |
| :--- | :--- | :--- | :--- |
| `NodesCount` | `uint32` | 4 | Number of nodes in hierarchy |
| `NodeName` | `UTF16_STRING` | Variable | Root node name |
| `UpAxisOrientation` | `int32` | 4 | World Up-Axis enum (`0`=Z-Up, `1`=Y-Up) |
| `SceneUnitScale` | `int32` | 4 | Scene measurement scale units |
| `SceneHierarchyMetadata` | `byte[84]` | 84 | Extended scene matrix & environment header |
| `Info` | `UTF16_STRING` | Variable | Scene info description string |
| `ActiveCameraIndex` | `int32` | 4 | Active viewport camera node index |
| `ActiveLightIndex` | `int32` | 4 | Primary directional light node index |
| `RootEndPadding` | `byte[12]` | 12 | Hierarchy root trailing padding |
| `SceneNodes` | `SCENE_NODE[NodesCount - 1]` | Variable | Array of hierarchy nodes |

#### `SCENE_NODE` Structure (`CAS2_LOADER::CAS2_MATRIX_NODE`):
- `Name`: `UTF16_STRING`
- `ParentIndex`: `uint32`
- `DefaultScale_Or_Pivot`: `VEC4` (Default scale `(Sx, Sy, Sz, Sw)` or pivot offset vector)
- `AnimData`: `ANIM_DATA`:
  - `TranslationFrames`: `FRAMES_ARRAY` (`uint32 FramesCount` + `float32 FrameTime[FramesCount]`)
  - `Translations`: `FRAME_TRANSLATIONS_ARRAY` (`uint32 TranslationsCount` + `VEC3 Translation[TranslationsCount]`)
  - `ScaleTrack_Or_BBox`: `byte[16]` (Animatable scale track / bounding box track)
  - `RotationFrames`: `FRAMES_ARRAY` (`uint32 FramesCount` + `float32 FrameTime[FramesCount]`)
  - `Rotations`: `FRAME_ROTATIONS_ARRAY` (`uint32 RotationsCount` + `VEC4 Rotation[RotationsCount]`)
- `ParentNodeIndex`: `int32` (Linkage parent node index)
- `TargetLinkageName`: `UTF16_STRING` (Target parent linkage name string)
- `Attributes`: `NODE_ATTRIBUTES_ARRAY`

---

### 7.5 Material Node (`NodeType == MATERIAL` / `13`)
Surface material node (`CAS2_LOADER::CAS2_MATERIAL`).

| Field Name | Data Type | Description |
| :--- | :--- | :--- |
| `MaterialType` | `MATERIAL_TYPE` | `0` = DEFAULT (Standard Max), `1` = DIRECTX (HLSL FX Shader) |
| `NodeName` | `UTF16_STRING` | Node identifier |
| `MaterialName` | `UTF16_STRING` | Material identifier |
| `MaterialAttributes` | `NODE_ATTRIBUTES_ARRAY` | Material attributes block |

#### A. If `MaterialType == MATERIAL_TYPE_DEFAULT` (`0`):
Uses `DEFAULT_MATERIAL` (`CAS2_LOADER::CAS2_STANDARD_MATERIAL`):
- `Ambient`, `Diffuse`, `Specular`, `SelfIllumination`: `DEFAULT_MATERIAL_COLOR_PROPERTY` (Color track animatable: `InterpolationMode`, `NumKeys`, `StartFrame`, `EndFrame`, `LoopFlags`, `ReservedFlags`, `TrackType` + `VEC4 ColorValue`)
- `Opacity`, `Glossiness`, `SpecularLevel`, `SelfIllumination`: `DEFAULT_MATERIAL_FLOAT_PROPERTY` (Float track animatable: `InterpolationMode`, `NumKeys`, `StartFrame`, `EndFrame`, `LoopFlags`, `ReservedFlags`, `TrackType` + `float32 FloatValue`)
- `bWire`: `uint32` (Wireframe flag)
- `Unknown`: `uint32`
- `TexturesArray`: `DEFAULT_MATERIAL_TEXTURES_ARRAY` (`uint32 Count` + `BITMAP_TEXTURE[Count]`):
  - `BITMAP_TEXTURE` (`CAS2_LOADER::CAS2_BITMAP_MATERIAL_MAP`): 2 x `uint32 Unknown`, `TextureSlotName` (`UTF16_STRING`), `ComponentName` (`UTF16_STRING`), `UVCoordinates_AndTime` (`byte[160]`), `TexturePath` (`UTF16_STRING`), `CropAndAlphaSettings` (`byte[72]`).

#### B. If `MaterialType == MATERIAL_TYPE_DIRECTX` (`1`):
Uses `DIRECTX_MATERIAL` (`CAS2_LOADER::CAS2_SHADER_MATERIAL`):
- `ShaderFxPath`: `UTF16_STRING` (Path to `.fx` / `.fxo` shader)
- `ShaderTechniqueIndex`: `uint32`
- `Textures`: `MATERIAL_TEXTURES_ARRAY` (`uint32 TexturesCount` + `MATERIAL_TEXTURE[TexturesCount]`):
  - `MATERIAL_TEXTURE`: `TextureName` (`UTF16_STRING`), `TexturePath` (`UTF16_STRING`)
- `LightProperties`: `MATERIAL_LIGHT_PROPERTIES` (`uint32 PropertiesCount` + `MATERIAL_LIGHT_PROPERTY[PropertiesCount]`):
  - `MATERIAL_LIGHT_PROPERTY` (`CAS2_LOADER::CAS2_SHADER_LIGHT_PARAM`): `PropertyName` (`UTF16_STRING`), `ParameterType` (`int32`), `ParameterFlags` (`int32`)
- `FloatAttributes`: `FLOAT_ATTRIBUTES_ARRAY`
- `IntegerAttributes`: `INTEGER_ATTRIBUTES_ARRAY`
- `ShaderPassIndex`: `int32`
- `Vec4Attributes`: `VEC4_ATTRIBUTES_ARRAY`
- `ShaderFlags`: `int32`

---

### 7.6 Instance Nodes
Reuses geometry from a previously parsed node.

#### `INSTANCE_NO_MATERIAL` (`16`) — `CAS2_LOADER::CAS2_GEOM_INSTANCE`
- `Unknown`: `uint32`
- `NodeName`, `NodeMetadataString`, `UserDefinedProperties`: `UTF16_STRING`
- `NodeIndex`: `uint32`
- `Attributes`: `NODE_ATTRIBUTES_ARRAY`
- `GeometryDataCount`: `uint32`
- Geometry Chunks containing `GeometryHeaderPadding[12]`, `BoundingBoxExtentFloats`, `BoundingBox` array, `OriginalNodeIndex` (`uint32`), and `VertexColorChannelFlags`.

#### `INSTANCE_OVERRIDE_MATERIAL` (`18`) — `CAS2_GEOM_INSTANCE_DIFFERING_MATERIALS`
- Same as `INSTANCE_NO_MATERIAL`, plus `MaterialId` (`uint32`) at the end of each geometry chunk.

---

### 7.7 Helper Dummy Node (`17`) & Camera Node (`6`)
- **`DUMMY` (`17`)**: `CAS2_LOADER::CAS2_HELPER` (Standard node header: `NodeName`, `NodeMetadataString`, `UserDefinedProperties`, `NodeIndex`, `Attributes`, `GeometryDataCount`).
- **`CAMERA` (`6`)**: `CAS2_LOADER::CAS2_CAMERA` (Standard node header + `CameraParameters[144]` 144-byte camera FOV, lens, and projection parameter block).

---

## 8. CA Assembly Kit Tag Validation (`BOB_Cs2.AssemblyKit.dll`)

When `BOB_Cs2.AssemblyKit.dll` parses and compiles a `.CS2` intermediate file into binary game models, it validates structure integrity using tagged assertion blocks:

| Validation Tag | Validated CS2 Structural Block | Description |
| :--- | :--- | :--- |
| `&CAS` / `&cs2` | `HEADER` | Top-level format signature and version |
| `&INPUT_CAS_MATRIX_HIERARCHY` | `SCENE_ROOT` (`12`) | Scene tree root matrix hierarchy |
| `&MATRIX_NODES` / `&CHILD_NODE_INDICES` | `SCENE_NODE` | Child transformation node linkages |
| `&GEOM` / `&GEOMS` | Geometry Chunks | Mesh geometry container |
| `&TRI_OBJ` / `&TRI_OBJS` | `SUBMESH` | Triangle mesh payload |
| `&VERTS` / `&CAS_VERTS` | Vertex Buffers | Vertex position and normal arrays |
| `&BONE_MAPPINGS` / `&INV_BONE_MATS` | Bone Weights (`BONE_WEIGHT`) | Skeletal skinning bone index mapping & inverse bind matrices |
| `&MATERIALS` / `&USED_MATERIALS` | `MATERIAL` (`13`) | Material assignment and active texture channels |
| `&BEZIER_SPLINE_OBJECT` | `LINE` (`11`) | 3D vector spline path object |

---

## 9. Complete CS2 Binary Parser (Python Pseudo-Code)

```python
import struct

class CS2BinaryReader:
    def __init__(self, buffer):
        self.buffer = buffer
        self.offset = 0

    def read_uint16(self):
        val = struct.unpack_from('<H', self.buffer, self.offset)[0]
        self.offset += 2
        return val

    def read_uint32(self):
        val = struct.unpack_from('<I', self.buffer, self.offset)[0]
        self.offset += 4
        return val

    def read_uint64(self):
        val = struct.unpack_from('<Q', self.buffer, self.offset)[0]
        self.offset += 8
        return val

    def read_int32(self):
        val = struct.unpack_from('<i', self.buffer, self.offset)[0]
        self.offset += 4
        return val

    def read_float(self):
        val = struct.unpack_from('<f', self.buffer, self.offset)[0]
        self.offset += 4
        return val

    def read_utf16_string(self):
        length = self.read_uint16()
        if length == 0:
            return ""
        raw_bytes = self.buffer[self.offset : self.offset + length * 2]
        self.offset += length * 2
        return raw_bytes.decode('utf-16-le', errors='replace')

    def read_vec3(self):
        return (self.read_float(), self.read_float(), self.read_float())

    def read_vec4(self):
        return (self.read_float(), self.read_float(), self.read_float(), self.read_float())

def parse_cs2(filepath):
    with open(filepath, 'rb') as f:
        reader = CS2BinaryReader(f.read())

    # 1. Header (CAS2_LOADER::CAS2)
    magic = reader.buffer[reader.offset : reader.offset + 4]
    reader.offset += 4
    header_size = reader.read_uint32()
    exporter_version = reader.read_float()   # Renamed from Unknown2
    feature_flags = reader.read_uint32()      # Renamed from Unknown3
    plugin = reader.read_utf16_string()
    details = reader.read_utf16_string()

    # 2. Scene Block Data (SCENE_BLOCK_DATA)
    scene_block_size = reader.read_uint32()
    format_compat_ver = reader.read_uint32() # Renamed from Unknown1
    obj_types_cnt = reader.read_uint32()
    lights_cnt = reader.read_uint32()
    cameras_cnt = reader.read_uint32()
    rigid_cnt = reader.read_uint32()
    total_scene_verts = reader.read_uint64() # Renamed from UnknownData1[8]
    weighted_cnt = reader.read_uint32()
    lines_cnt = reader.read_uint32()
    dummies_cnt = reader.read_uint32()
    materials_cnt = reader.read_uint32()
    total_scene_tris = reader.read_uint64()  # Renamed from UnknownData2[8]
    instances_cnt = reader.read_uint32()
    scene_bbox_and_matrix = reader.buffer[reader.offset : reader.offset + 44] # Renamed from UnknownData3[44]
    reader.offset += 44

    # 3. Timeline Data (TIMELINE_BLOCK_DATA / UNKNOWN_BLOCK2_DATA)
    timeline_block_size = reader.read_uint32()
    framerate_fps = reader.read_uint32()      # Renamed from unknown_block2_value1
    start_frame_time = reader.read_float()    # Renamed from unknown_block2_float1_start
    end_frame_time = reader.read_float()      # Renamed from unknown_block2_float2_end
    reader.offset += (timeline_block_size - 16)

    # 4. Morph & Spline Data (MORPH_AND_SPLINE_BLOCK_DATA / UNKNOWN_BLOCK3_DATA)
    morph_block_size = reader.read_uint32()
    morph_track_flags = reader.read_uint32()  # Renamed from unknown_block3_value1
    morph_spline_track_cnt = reader.read_uint32() # Renamed from unknown_block3_array_size
    for _ in range(morph_spline_track_cnt):
        track_id1 = reader.read_int32()
        track_id2 = reader.read_int32()
        track_id3 = reader.read_int32()
        
        # Read Morph / Spline float keyframe values (FLOAT_ARRAY)
        float_sz = reader.read_uint32()
        reader.offset += float_sz * 4
        
        # Read Morph / Spline vertex indices (INT_ARRAY)
        int_sz = reader.read_uint32()
        reader.offset += int_sz * 4

    # 5. Node Reading Loops
    cameras = [read_node(reader) for _ in range(cameras_cnt)]
    rigid_models = [read_node(reader) for _ in range(rigid_cnt)]
    weighted_models = [read_node(reader) for _ in range(weighted_cnt)]
    lines = [read_node(reader) for _ in range(lines_cnt)]
    dummies = [read_node(reader) for _ in range(dummies_cnt)]
    scene_root = read_node(reader)
    materials = [read_node(reader) for _ in range(materials_cnt)]
    instances = [read_node(reader) for _ in range(instances_cnt)]

    return {
        "plugin": plugin,
        "details": details,
        "version": exporter_version,
        "flags": feature_flags,
        "counts": {
            "rigid": rigid_cnt,
            "weighted": weighted_cnt,
            "materials": materials_cnt,
            "instances": instances_cnt,
        }
    }

def read_node(reader):
    node_length = reader.read_uint32()
    node_type = reader.read_uint32()
    # Execute node-type specific parsing logic...
    return {"type": node_type, "length": node_length}
```
