# Bone Inverse Transform Matrices (.bone_inv_trans_mats) File Format Specification
**Format Name:** Bone Inverse Transformation Matrices  
**File Extension:** `.bone_inv_trans_mats`  
**Target Games:** Total War Engine (Total War: ATTILA, Rome II, Warhammer series)  
**File Location Path:** `animations\skeletons\<skeleton_name>.bone_inv_trans_mats`  
**Byte Ordering:** Little-Endian  

---

## 1. Overview

The `.bone_inv_trans_mats` file format is Creative Assembly's binary matrix container used to store **Inverse Bind Pose Transformation Matrices** ($\mathbf{M}_{\text{inv\_bind}}$) for each bone in a skeleton hierarchy.

In the Total War engine (`Attila.exe`), these matrices are loaded into the skeleton structure (`m_tpose_inv_trans_matrices` of type `UTILITYLIB::ANIMATION_MATRIX_ARRAY`) and are crucial for GPU vertex skinning.

### Purpose in Skeletal Animation & Mesh Skinning
When rendering a skinned 3D mesh bound to a skeleton, each vertex position $\mathbf{V}_{\text{mesh}}$ is converted from mesh space to bone space using the inverse bind pose matrix, and then transformed by the current animated bone world matrix $\mathbf{M}_{\text{anim\_world}}$:

$$\mathbf{V}_{\text{final}} = \sum_{i=1}^{K} w_i \cdot \mathbf{M}_{\text{anim\_world}, i} \cdot \mathbf{M}_{\text{inv\_bind}, i} \cdot \mathbf{V}_{\text{mesh}}$$

Where:
- $\mathbf{M}_{\text{inv\_bind}, i}$ is the inverse bind pose matrix read from `.bone_inv_trans_mats` for bone index $i$.
- $\mathbf{M}_{\text{anim\_world}, i}$ is the world space matrix of bone $i$ evaluated at the current animation keyframe.
- $w_i$ is the vertex skinning weight for bone influence $i$.

---

## 2. File Architecture

The file consists of a 8-byte header followed by a contiguous array of 48-byte matrix structures:

```
+-------------------------------------------------------------+
| 1. Header (8 bytes)                                         |
|    - Version (uint32)                                       |
|    - MatrixCount / BoneCount (uint32)                       |
+-------------------------------------------------------------+
| 2. Matrix Payload Array (MatrixCount x 48 bytes)            |
|    - Matrix 0 (12 x float32: 3 rows x 4 columns)            |
|    - Matrix 1 (12 x float32: 3 rows x 4 columns)            |
|    - ...                                                    |
|    - Matrix N-1 (12 x float32: 3 rows x 4 columns)          |
+-------------------------------------------------------------+
```

---

## 3. Data Structures Specification

### 3.1 Primitive Types Reference

| Primitive Type | Size (Bytes) | Description |
| :--- | :--- | :--- |
| `uint32` | 4 | Unsigned 32-bit Little-Endian integer |
| `float32` | 4 | IEEE 754 32-bit single-precision floating point |

---

### 3.2 File Header

The file header starts at byte offset `0x00000000` and has a fixed size of **8 bytes**.

| Offset | Field Name | Data Type | Size (Bytes) | Description |
| :--- | :--- | :--- | :--- | :--- |
| `0x00` | `Version` | `uint32` | 4 | Format version number (typically `1` or `7`). |
| `0x04` | `MatrixCount` | `uint32` | 4 | Number of inverse bind pose matrices contained in the payload array (equals skeleton bone count). |

**Total Header Size:** 8 bytes.

---

### 3.3 Matrix Entry Payload (`MATRIX_43` / 3x4 Matrix)

Immediately following `MatrixCount` is an array of `MatrixCount` matrix structures. Each matrix is stored as **12 x float32** (**48 bytes total**).

The 12 float values represent a $3 \times 4$ matrix stored in column-major order:

| Offset | Field Name | Data Type | Size (Bytes) | Description |
| :--- | :--- | :--- | :--- | :--- |
| `+0x00` | `M11` | `float32` | 4 | Matrix Row 1, Column 1 |
| `+0x04` | `M21` | `float32` | 4 | Matrix Row 2, Column 1 |
| `+0x08` | `M31` | `float32` | 4 | Matrix Row 3, Column 1 |
| `+0x0C` | `M12` | `float32` | 4 | Matrix Row 1, Column 2 |
| `+0x10` | `M22` | `float32` | 4 | Matrix Row 2, Column 2 |
| `+0x14` | `M32` | `float32` | 4 | Matrix Row 3, Column 2 |
| `+0x18` | `M13` | `float32` | 4 | Matrix Row 1, Column 3 |
| `+0x1C` | `M23` | `float32` | 4 | Matrix Row 2, Column 3 |
| `+0x20` | `M33` | `float32` | 4 | Matrix Row 3, Column 3 |
| `+0x24` | `M14` | `float32` | 4 | Matrix Row 1, Column 4 (Translation X) |
| `+0x28` | `M24` | `float32` | 4 | Matrix Row 2, Column 4 (Translation Y) |
| `+0x2C` | `M34` | `float32` | 4 | Matrix Row 3, Column 4 (Translation Z) |

**Total Matrix Size:** 48 bytes (0x30) per bone matrix.

---

### 3.4 4x4 Matrix Reconstruction Rules

To expand the binary 3x4 matrix into a standard 4x4 homogenous transform matrix:

$$\mathbf{M}_{4 \times 4} = \begin{bmatrix} 
M_{11} & M_{12} & M_{13} & M_{14} \\
M_{21} & M_{22} & M_{23} & M_{24} \\
M_{31} & M_{32} & M_{33} & M_{34} \\
0.0 & 0.0 & 0.0 & 1.0 
\end{bmatrix}$$

- Row 4 is implicitly defined as `[0.0, 0.0, 0.0, 1.0]`.

---

## 4. Engine C++ Integration (`Attila.h`)

In `Attila.h`, inverse bind matrices are held in the skeleton container:
- `m_tpose_inv_trans_matrices`: Type `UTILITYLIB::ANIMATION_MATRIX_ARRAY` (alias for `CA_STD::VECTOR<UTILITYLIB::MATRIX_43>`).
- Each matrix maps directly to a skeleton bone index (`0` to `MatrixCount - 1`).

---

## 5. Complete Parsing & Writing Algorithms (Pseudo-Code)

### 5.1 Reader Algorithm (Python)
```python
import struct

def parse_bone_inv_trans_mats(file_bytes):
    # 1. Read Header (8 bytes)
    version, matrix_count = struct.unpack("<II", file_bytes[:8])
    
    matrices = []
    offset = 8
    
    # 2. Read Matrix Array (MatrixCount x 48 bytes)
    for i in range(matrix_count):
        # Read 12 floats (48 bytes)
        m = struct.unpack("<12f", file_bytes[offset:offset + 48])
        
        # Build 4x4 matrix (Row-major layout)
        matrix_4x4 = [
            [m[0], m[3], m[6], m[9]],   # Row 1 (M11, M12, M13, M14)
            [m[1], m[4], m[7], m[10]],  # Row 2 (M21, M22, M23, M24)
            [m[2], m[5], m[8], m[11]],  # Row 3 (M31, M32, M33, M34)
            [0.0,  0.0,  0.0,  1.0]     # Row 4 (Implicit)
        ]
        
        matrices.append(matrix_4x4)
        offset += 48
        
    assert offset == len(file_bytes), f"Unread trailing bytes: {len(file_bytes) - offset}"
    
    return {
        "version": version,
        "matrix_count": matrix_count,
        "matrices": matrices
    }
```

### 5.2 Writer Algorithm (Python)
```python
import struct

def write_bone_inv_trans_mats(version, matrices_4x4):
    matrix_count = len(matrices_4x4)
    out_bytes = bytearray()
    
    # Write Header (8 bytes)
    out_bytes.extend(struct.pack("<II", version, matrix_count))
    
    # Write Matrices (48 bytes each)
    for mat in matrices_4x4:
        # Extract M11..M34 in column-major binary sequence
        m11, m12, m13, m14 = mat[0][0], mat[0][1], mat[0][2], mat[0][3]
        m21, m22, m23, m24 = mat[1][0], mat[1][1], mat[1][2], mat[1][3]
        m31, m32, m33, m34 = mat[2][0], mat[2][1], mat[2][2], mat[2][3]
        
        packed_matrix = struct.pack("<12f", 
            m11, m21, m31, 
            m12, m22, m32, 
            m13, m23, m33, 
            m14, m24, m34
        )
        out_bytes.extend(packed_matrix)
        
    return bytes(out_bytes)
```
