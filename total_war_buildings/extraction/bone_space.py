import math

import mathutils

# Same Z-up <-> Y-up basis swap as extraction._to_engine_space, as a matrix because the swap is a
# reflection and so has no quaternion of its own. Conjugating a 4x4 by it converts both the
# rotation and the translation at once, and it is its own inverse.
ENGINE_SPACE_MATRIX = mathutils.Matrix(
    ((1.0, 0.0, 0.0, 0.0), (0.0, 0.0, 1.0, 0.0), (0.0, 1.0, 0.0, 0.0), (0.0, 0.0, 0.0, 1.0))
)

# 3ds Max runs a bone's local +X axis down the bone; Blender's armatures run +Y down it. Measured on
# rome_man_game.cs2, whose local +X points at the node's first child on 120 of the 124 nodes that
# have one (the four exceptions are branch points, where no single axis could). Applying this fixed
# quarter turn on import - and undoing it on export - makes imported bones point the way a Blender
# artist expects without altering a single stored rotation.
BONE_AXIS_CORRECTION = mathutils.Matrix.Rotation(math.radians(-90.0), 4, "Z")

Vec3 = tuple[float, float, float]
Vec4 = tuple[float, float, float, float]


def local_engine_matrix(translation: Vec3, rotation: Vec4) -> mathutils.Matrix:
    # The CS2 stores rotations x,y,z,w and composes row-vector style as R x T, which transposes to
    # Blender's own T @ R (PLAN_units.md 1.4).
    x, y, z, w = rotation
    return mathutils.Matrix.Translation(translation) @ mathutils.Quaternion((w, x, y, z)).to_matrix().to_4x4()


def world_engine_matrices(bones) -> list[mathutils.Matrix]:
    matrices: list[mathutils.Matrix] = []
    for bone in bones:
        local = local_engine_matrix(bone.translation, bone.rotation)
        matrices.append(local if bone.parent_index < 0 else matrices[bone.parent_index] @ local)
    return matrices


def engine_to_blender_bone(world_engine: mathutils.Matrix) -> mathutils.Matrix:
    return ENGINE_SPACE_MATRIX @ world_engine @ ENGINE_SPACE_MATRIX @ BONE_AXIS_CORRECTION


def blender_bone_to_engine(blender_bone: mathutils.Matrix) -> mathutils.Matrix:
    return ENGINE_SPACE_MATRIX @ (blender_bone @ BONE_AXIS_CORRECTION.inverted()) @ ENGINE_SPACE_MATRIX


def local_translation_rotation(
    world_engine: mathutils.Matrix, parent_world_engine: mathutils.Matrix | None
) -> tuple[Vec3, Vec4]:
    local = world_engine if parent_world_engine is None else parent_world_engine.inverted() @ world_engine
    translation, rotation, _scale = local.decompose()
    # q and -q are the same rotation, and which of the two a matrix decomposes to is not something
    # the matrix records - so the sign a real file happens to carry cannot be recovered here. Pin it
    # to w >= 0 explicitly rather than leaning on mathutils happening to do that, so an imported
    # skeleton and one built in Blender always write the same representative.
    if rotation.w < 0.0:
        rotation.negate()
    return tuple(translation), (rotation.x, rotation.y, rotation.z, rotation.w)


def blender_object_to_engine(blender_world: mathutils.Matrix) -> mathutils.Matrix:
    # An attachment point is a plain object, not a bone, so it takes only the basis swap -
    # BONE_AXIS_CORRECTION exists to make Blender draw bones the right way and has nothing to undo
    # here.
    return ENGINE_SPACE_MATRIX @ blender_world @ ENGINE_SPACE_MATRIX
