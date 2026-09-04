# Building Technical (.cs2.parsed) File Format Specification
**Format Versions:** Version 11 and Version 13 (Total War: ATTILA)  
**Target Game:** Total War: ATTILA (and Shogun 2 / Rome II)  
**Byte Ordering:** Little-Endian  

---

## 1. Overview

The `.cs2.parsed` file format is Creative Assembly's binary building tech layout container. It defines building geometry, destruction levels (`DestructLevel`), placement nodes, collision hulls (3D meshes and soft cylinders), AI pathfinding lines, siege engine mounts (cannons, arrow emitters), docking points, platform faces, and VFX attachment anchors for battle maps and siege environments.

### Key Characteristics
- **Multi-Level Destruction Hierarchy**: Buildings consist of multiple pieces (`BuildingPiece`), each containing sequential destruction stages (`DestructLevel`).
- **Binary Strings**: Strings are length-prefixed UTF-16 Unicode strings (`unicode_string`).
- **Mixed Tech Geometry**: Combines 3D collision meshes, 2D no-go pathfinding zones, platform ground surfaces, vector lines, and spatial transformation matrices.
- **Engine Versioning**: Version `11` (Rome II / Shogun 2) and Version `13` (Attila Total War). Version `13` adds extended VFX action attachments and secondary VFX node arrays.

---

## 2. High-Level File Architecture

A `.cs2.parsed` file consists of top-level building metadata followed by a array of building pieces:

```
+-------------------------------------------------------------+
| 1. File Version (uint32 = 11 or 13)                         |
+-------------------------------------------------------------+
| 2. Building Bounding Box (24 bytes: 6 x float32)            |
+-------------------------------------------------------------+
| 3. Building Flag Node (TechNode: name + 4x4 matrix)         |
+-------------------------------------------------------------+
| 4. Reserved Array Size (uint32, expected 0)                 |
+-------------------------------------------------------------+
| 5. Building Pieces Count (uint32)                           |
+-------------------------------------------------------------+
| 6. Building Pieces Array (BuildingPiece x PieceCount)       |
|    - Piece Name (unicode_string)                            |
|    - Placement Node (TechNode: name + 4x4 matrix)           |
|    - Parent Index (uint32)                                  |
|    - Destruct Count (uint32)                                |
|    - Destruct Levels Array (DestructLevel x DestructCount)  |
|      * 3D Collision Mesh & Sub-Hulls (Windows, Doors, etc)  |
|      * Pathfinding Outlines, Pipes & No-Go Zones            |
|      * Platforms & Ground Polygons                          |
|      * Siege Cannons, Arrow Emitters & Docking Nodes        |
|      * Soft Collision Cylinders & File References           |
|      * EF Lines & Action VFX (Version 13 extensions)        |
+-------------------------------------------------------------+
```

---

## 3. Data Structures Specification

### 3.1 Primitive & Helper Data Structures

#### 1. `unicode_string`
Binary UTF-16 Unicode string format:
| Offset | Field Name | Data Type | Size (Bytes) | Description |
| :--- | :--- | :--- | :--- | :--- |
| `+0x00` | `length` | `uint16` | 2 | Number of UTF-16 characters (`length`). |
| `+0x02` | `data` | `byte[length * 2]` | `length * 2` | Little-Endian UTF-16 string data. |

#### 2. `matrix_4x4` (`TransformMatrix`)
64-byte $4 \times 4$ transformation matrix stored in column-major order:
| Field Name | Data Type | Size (Bytes) | Description |
| :--- | :--- | :--- | :--- |
| `row0_col0..3` | `float32[4]` | 16 | Matrix Row 0 components |
| `row1_col0..3` | `float32[4]` | 16 | Matrix Row 1 components |
| `row2_col0..3` | `float32[4]` | 16 | Matrix Row 2 components |
| `row3_col0..3` | `float32[4]` | 16 | Matrix Row 3 components (Translation $X, Y, Z, W$) |

#### 3. `bounding_box` (`BoundingBox`)
24-byte axis-aligned bounding box:
| Field Name | Data Type | Size (Bytes) | Description |
| :--- | :--- | :--- | :--- |
| `min_x`, `min_y`, `min_z` | `float32[3]` | 12 | Minimum corner bounding coordinates |
| `max_x`, `max_y`, `max_z` | `float32[3]` | 12 | Maximum corner bounding coordinates |

#### 4. `vec2` & `vert` (`vec3`)
- `vec2`: 2 x `float32` (8 bytes: `x, y`).
- `vert` / `vec3`: 3 x `float32` (12 bytes: `x, y, z`).

#### 5. `node` (`TechNode`)
Spatial anchor node containing an identifier and a 64-byte matrix transform:
| Field Name | Data Type | Size (Bytes) | Description |
| :--- | :--- | :--- | :--- |
| `node_name` | `unicode_string` | Variable | Anchor node identifier string. |
| `node_transform` | `matrix_4x4` | 64 | $4 \times 4$ transform matrix. |

---

### 3.2 3D Geometry & Collision Structures

#### 1. `edge` (`FaceEdge`) — 16 Bytes
| Field Name | Data Type | Size (Bytes) | Description |
| :--- | :--- | :--- | :--- |
| `vertex_index_0` | `uint32` | 4 | First vertex index |
| `vertex_index_1` | `uint32` | 4 | Second vertex index |
| `edge_index` | `uint32` | 4 | Edge index identifier |
| `unknown` | `uint32` | 4 | Internal flag/ID |

#### 2. `edge_data` (`FaceEdgeData`) — 64 Bytes
Contains 4 x `edge` structures (`edge0`, `edge1`, `edge2`, `edge3`).

#### 3. `face` (`Face`) — 77 Bytes
| Field Name | Data Type | Size (Bytes) | Description |
| :--- | :--- | :--- | :--- |
| `face_index` | `uint32` | 4 | Unique face ID |
| `padding` | `byte` | 1 | Alignment byte |
| `vert_index_0` | `uint32` | 4 | Triangle vertex index 0 |
| `vert_index_1` | `uint32` | 4 | Triangle vertex index 1 |
| `vert_index_2` | `uint32` | 4 | Triangle vertex index 2 |
| `edge_data` | `edge_data` | 64 | Face edge definitions |

#### 4. `collision3d` (`Collision3D`)
3D collision mesh representation:
| Field Name | Data Type | Size (Bytes) | Description |
| :--- | :--- | :--- | :--- |
| `collision_name` | `unicode_string` | Variable | Name of the collision mesh. |
| `node_index` | `uint32` | 4 | Attached node index. |
| `unknown2` | `uint32` | 4 | Flags/reserved field. |
| `num_verts` | `uint32` | 4 | Number of 3D vertices. |
| `data_vertices` | `vert[num_verts]` | `num_verts * 12` | Vertex array (3 x float32 per vertex). |
| `num_faces` | `uint32` | 4 | Number of polygon faces. |
| `data_faces` | `face[num_faces]` | `num_faces * 77` | Face definitions array. |

---

### 3.3 Pathfinding & Platform Structures

#### 1. `line` (`LineNode`)
Vector line definition (used for AI pathing outlines and pipes):
| Field Name | Data Type | Size (Bytes) | Description |
| :--- | :--- | :--- | :--- |
| `line_name` | `unicode_string` | Variable | Name of the line feature. |
| `num_verts` | `uint32` | 4 | Number of vertices in line spline. |
| `data_verts` | `vert[num_verts]` | `num_verts * 12` | Array of 3D vertex points. |
| `line_type` | `uint32` | 4 | Line behavior type enum (hard obstacle, ground ad, pipe, etc.). |

#### 2. `nogo_zone` (`NogoZone`)
2D pathfinding obstacle boundaries:
| Field Name | Data Type | Size (Bytes) | Description |
| :--- | :--- | :--- | :--- |
| `num_lines` | `uint32` | 4 | Number of 2D line segments. |
| `data_nogo_lines` | Array of `num_lines` | Variable | Array of 2D vertices (`vec2`) + `num_connected_lines` (`uint32`). |

#### 3. `platform_face` / `polygon` (`Polygon`)
Walkable platform and wall polygon definitions:
| Field Name | Data Type | Size (Bytes) | Description |
| :--- | :--- | :--- | :--- |
| `normal` | `vert` | 12 | Normal vector (3 x float32). |
| `num_verts` | `uint32` | 4 | Number of vertices in polygon. |
| `data_verts` | `vert[num_verts]` | `num_verts * 12` | Polygon vertex array. |
| `flag1` | `byte` | 1 | Surface flag 1. |
| `is_platform_ground` | `byte` | 1 | Surface flag 2 (`0` = wall/platform, `!=0` = walkable platform ground). |
| `flag3` | `byte` | 1 | Surface flag 3. |

#### 4. `platform` (`Platform`)
| Field Name | Data Type | Size (Bytes) | Description |
| :--- | :--- | :--- | :--- |
| `num_polygons` | `uint32` | 4 | Number of polygons in platform. |
| `data_polygons` | `polygon[num_polygons]` | Variable | Array of platform polygons. |
| `parent_node_index` | `uint32` | 4 | Parent node index. |

---

### 3.4 Anchors, Soft Collisions & References

#### 1. `soft_collision` (`SoftCollision`)
Cylindrical soft collision volumes for pathfinding avoidance:
| Field Name | Data Type | Size (Bytes) | Description |
| :--- | :--- | :--- | :--- |
| `node_name` | `unicode_string` | Variable | Identifier string. |
| `node_transform` | `matrix_4x4` | 64 | Transform matrix. |
| `id_or_unknown` | `uint16` | 2 | Cylinder ID / unknown uint16. |
| `radius` | `float32` | 4 | Cylinder radius. |
| `height` | `float32` | 4 | Cylinder height. |

#### 2. `file_ref` (`FileRef`)
External asset/sub-file reference node:
| Field Name | Data Type | Size (Bytes) | Description |
| :--- | :--- | :--- | :--- |
| `file_key` | `unicode_string` | Variable | Resource key string. |
| `file_name` | `unicode_string` | Variable | External file path string. |
| `file_transform` | `matrix_4x4` | 64 | Transform matrix. |
| `unknown` | `uint16` | 2 | Unknown uint16. |

#### 3. `ef_line` (`EFLine`)
Entity/Effect action line definition:
| Field Name | Data Type | Size (Bytes) | Description |
| :--- | :--- | :--- | :--- |
| `line_name` | `unicode_string` | Variable | EF line identifier string. |
| `line_action` | `uint32` | 4 | Action enum (`enum_efline_action`). |
| `line_start` | `vec3` | 12 | Line starting position. |
| `line_end` | `vec3` | 12 | Line ending position. |
| `line_dir` | `vec3` | 12 | Line direction vector. |
| `parent_index` | `uint32` | 4 | Parent platform / node index. |

#### 4. `action_vfx_attachment` (`VFXAttachment`)
VFX surface attachment indices:
| Field Name | Data Type | Size (Bytes) | Description |
| :--- | :--- | :--- | :--- |
| `num_indices` | `uint32` | 4 | Number of attached face indices. |
| `data_indices` | `uint16[num_indices]` | `num_indices * 2` | Array of 16-bit face index references. |

---

## 4. Destruction Level (`DestructLevel` / `EMPIREUTILITY::DESTRUCTION_LEVEL`)

Each building piece contains one or more `DestructLevel` instances detailing geometry and tech nodes for that state of destruction.

### Parsing Order of `DestructLevel`:

| Step | Field Name | Engine C++ Equivalent | Data Type | Description |
| :--- | :--- | :--- | :--- | :--- |
| 1 | `destruct_name` | `name` | `unicode_string` | Destruction stage name (e.g. `"destruct_01"`). |
| 2 | `destruct_index` | `destruction_level_id` | `uint32` | Destruction stage index (`0` = intact, `1+` = damaged). |
| 3 | `collision3d` | `collision` | `collision3d` | Base 3D collision mesh. |
| 4 | `num_windows` | `collision_windows` | `uint32` | Number of window collision meshes. |
| 5 | `data_windows` | — | `collision3d[num_windows]` | Array of window collision meshes. |
| 6 | `num_doors` | `collision_doors` | `uint32` | Number of door collision meshes. |
| 7 | `data_doors` | — | `collision3d[num_doors]` | Array of door collision meshes. |
| 8 | `num_special` | `toggle_items` | `uint32` | Number of special item pairs. |
| 9 | `data_special` | — | `(collision3d x 2)[num_special]` | Array of paired toggle collision meshes (2 meshes per special item). |
| 10 | `num_lines` | `outlines` | `uint32` | Number of outline vector lines. |
| 11 | `data_lines` | — | `line[num_lines]` | Array of outline vector lines. |
| 12 | `num_pipes` | `pipes` | `uint32` | Number of pipe vector lines. |
| 13 | `data_pipes` | — | `line[num_pipes]` | Array of pipe vector lines. |
| 14 | `num_nogo_zones` | `hard_collisions` | `uint32` | Number of 2D no-go pathfinding zones. |
| 15 | `data_nogo_zones` | — | `nogo_zone[num_nogo_zones]` | Array of 2D no-go zones. |
| 16 | `platforms` | `platform_descr_list` | `platform` | Building platform & ground polygons. |
| 17 | `hit_points_threshold` | `hit_points_threshold` | `uint32` | Destruction HP threshold trigger. |
| 18 | `destruct_bbox` | `extents` | `bounding_box` | Bounding box of destruction stage (24 bytes). |
| 19 | `num_cannons` | `cannons` | `uint32` | Number of siege cannon mount nodes. |
| 20 | `data_cannons` | — | `node[num_cannons]` | Array of cannon mount nodes (`node`). |
| 21 | `num_arrow_emitters` | `arrow_emitters` | `uint32` | Number of arrow emitter nodes. |
| 22 | `data_arrow_emitters` | — | `node[num_arrow_emitters]` | Array of arrow emitter nodes (`node`). |
| 23 | `num_docking_points` | `docking_points` | `uint32` | Number of siege ladder docking nodes. |
| 24 | `data_docking_points` | — | `node[num_docking_points]` | Array of docking nodes (`node`). |
| 25 | `num_soft_collisions` | `soft_collision_objects` | `uint32` | Number of soft collision cylinders. |
| 26 | `data_soft_collisions` | — | `soft_collision[num_soft_collisions]` | Array of soft collision objects. |
| 27 | `unknown_array_1` | — | `uint32` | Reserved array size (expected `0`). |
| 28 | `num_file_refs` | `emitter_points` | `uint32` | Number of external file references. |
| 29 | `data_file_refs` | — | `file_ref[num_file_refs]` | Array of file reference nodes. |
| 30 | `num_eflines` | `efline_platform_pairs` | `uint32` | Number of EF action lines. |
| 31 | `data_eflines` | — | `ef_line[num_eflines]` | Array of EF action lines. |
| 32 | `unknown_array_2` | — | `uint32` | Reserved array size (expected `0`). |

#### Version 13 Extensions (Attila Total War Only):
If the file version is `13`, the following four fields follow `unknown_array_2`:

| Step | Field Name | Data Type | Description |
| :--- | :--- | :--- | :--- |
| 33 | `num_action_vfx` | `uint32` | Number of primary action VFX nodes. |
| 34 | `data_action_vfx` | `node[num_action_vfx]` | Array of primary action VFX nodes (`node`). |
| 35 | `num_second_action_vfx` | `uint32` | Number of secondary action VFX nodes. |
| 36 | `data_second_action_vfx` | `node[num_second_action_vfx]` | Array of secondary action VFX nodes (`node`). |
| 37 | `num_att_action_vfx` | `uint32` | Number of primary VFX surface attachment mappings. |
| 38 | `data_att_action_vfx` | `action_vfx_attachment[...]` | Array of VFX attachment index mappings. |
| 39 | `num_second_att_action_vfx` | `uint32` | Number of secondary VFX surface attachment mappings. |
| 40 | `data_second_att_action_vfx` | `action_vfx_attachment[...]` | Array of secondary VFX attachment index mappings. |

---

## 5. Building Piece Structure (`BuildingPiece` / `EMPIREUTILITY::BUILDING_PIECE_DESCR`)

Each building piece represents a structural sub-component of the building:

| Field Name | Engine C++ Equivalent | Data Type | Description |
| :--- | :--- | :--- | :--- |
| `piece_name` | `name` | `unicode_string` | Name of the building piece (e.g. `"piece_wall_01"`). |
| `placement_node` | `piece_placement` | `node` | World placement anchor node (`node`: name + 4x4 matrix). |
| `parent_index` | `piece_id` | `uint32` | Parent building piece index (`0xFFFFFFFF` / `-1` if top-level). |
| `destruct_count` | `destruction_levels` | `uint32` | Number of destruction levels. |
| `destructs` | — | `DestructLevel[destruct_count]` | Array of destruction levels. |
| `unknown_array` | — | `uint32` | Reserved array size (expected `0`). |

---

## 6. Complete Parsing Algorithm (Pseudo-Code)

```python
def parse_cs2_parsed(binary_reader):
    # 1. Read Version
    version = binary_reader.read_uint32()
    assert version in (11, 13), f"Unsupported version: {version}"

    # 2. Read Building Bounding Box (24 bytes)
    building_bbox = {
        "min_x": binary_reader.read_float32(),
        "min_y": binary_reader.read_float32(),
        "min_z": binary_reader.read_float32(),
        "max_x": binary_reader.read_float32(),
        "max_y": binary_reader.read_float32(),
        "max_z": binary_reader.read_float32(),
    }

    # 3. Read Building Flag Node
    flag_name = binary_reader.read_unicode_string()
    flag_transform = binary_reader.read_matrix_4x4()
    
    # 4. Unknown Reserved Array
    reserved_size = binary_reader.read_uint32()
    assert reserved_size == 0, f"Unexpected data in reserved array at {binary_reader.tell()}"

    # 5. Read Building Pieces Count
    piece_count = binary_reader.read_uint32()
    pieces = []
    
    for i in range(piece_count):
        piece_name = binary_reader.read_unicode_string()
        placement_name = binary_reader.read_unicode_string()
        placement_transform = binary_reader.read_matrix_4x4()
        
        parent_index = binary_reader.read_uint32()
        destruct_count = binary_reader.read_uint32()
        
        destructs = []
        for d in range(destruct_count):
            destruct = parse_destruct_level(binary_reader, version)
            destructs.append(destruct)
            
        piece_reserved = binary_reader.read_uint32()
        assert piece_reserved == 0
        
        pieces.append({
            "name": piece_name,
            "placement": {"name": placement_name, "transform": placement_transform},
            "parent_index": parent_index,
            "destructs": destructs
        })
        
    return {
        "version": version,
        "bbox": building_bbox,
        "flag": {"name": flag_name, "transform": flag_transform},
        "pieces": pieces
    }

def parse_destruct_level(binary_reader, version):
    destruct_name = binary_reader.read_unicode_string()
    destruct_index = binary_reader.read_uint32()
    
    base_collision = binary_reader.read_collision3d()
    
    windows_count = binary_reader.read_uint32()
    windows = [binary_reader.read_collision3d() for _ in range(windows_count)]
    
    doors_count = binary_reader.read_uint32()
    doors = [binary_reader.read_collision3d() for _ in range(doors_count)]
    
    special_count = binary_reader.read_uint32()
    specials = []
    for _ in range(special_count):
        mesh1 = binary_reader.read_collision3d()
        mesh2 = binary_reader.read_collision3d()
        specials.append((mesh1, mesh2))
        
    lines_count = binary_reader.read_uint32()
    lines = [binary_reader.read_line_node() for _ in range(lines_count)]
    
    pipes_count = binary_reader.read_uint32()
    pipes = [binary_reader.read_line_node() for _ in range(pipes_count)]
    
    nogo_count = binary_reader.read_uint32()
    nogos = [binary_reader.read_nogo_zone() for _ in range(nogo_count)]
    
    platform = binary_reader.read_platform()
    hit_points_threshold = binary_reader.read_uint32()
    destruct_bbox = binary_reader.read_bounding_box()
    
    cannons_count = binary_reader.read_uint32()
    cannons = [binary_reader.read_tech_node() for _ in range(cannons_count)]
    
    arrow_emitters_count = binary_reader.read_uint32()
    arrow_emitters = [binary_reader.read_tech_node() for _ in range(arrow_emitters_count)]
    
    docking_count = binary_reader.read_uint32()
    docking_points = [binary_reader.read_tech_node() for _ in range(docking_count)]
    
    soft_coll_count = binary_reader.read_uint32()
    soft_collisions = [binary_reader.read_soft_collision() for _ in range(soft_coll_count)]
    
    reserved_1 = binary_reader.read_uint32()
    assert reserved_1 == 0
    
    file_refs_count = binary_reader.read_uint32()
    file_refs = [binary_reader.read_file_ref() for _ in range(file_refs_count)]
    
    ef_lines_count = binary_reader.read_uint32()
    ef_lines = [binary_reader.read_ef_line() for _ in range(ef_lines_count)]
    
    reserved_2 = binary_reader.read_uint32()
    assert reserved_2 == 0
    
    vfx_nodes = []
    if version == 13:
        num_action_vfx = binary_reader.read_uint32()
        action_vfx = [binary_reader.read_tech_node() for _ in range(num_action_vfx)]
        
        num_second_action_vfx = binary_reader.read_uint32()
        second_action_vfx = [binary_reader.read_tech_node() for _ in range(num_second_action_vfx)]
        
        num_att_vfx = binary_reader.read_uint32()
        att_vfx = [binary_reader.read_vfx_attachment() for _ in range(num_att_vfx)]
        
        num_second_att_vfx = binary_reader.read_uint32()
        second_att_vfx = [binary_reader.read_vfx_attachment() for _ in range(num_second_att_vfx)]
        
    return {
        "name": destruct_name,
        "index": destruct_index,
        "collision": base_collision,
        "windows": windows,
        "doors": doors,
        "specials": specials,
        "lines": lines,
        "pipes": pipes,
        "nogo": nogos,
        "platform": platform,
        "hp_threshold": hit_points_threshold,
        "bbox": destruct_bbox,
        "cannons": cannons,
        "arrow_emitters": arrow_emitters,
        "docking_points": docking_points,
        "soft_collisions": soft_collisions,
        "file_refs": file_refs,
        "ef_lines": ef_lines,
    }
```
