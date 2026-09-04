from pathlib import Path

import bpy

from binary.cs2_reader import read_cs2
from binary.rigid_model_v2_reader import read_rigid_model_v2
from binary.vegetation_tech_reader import is_vegetation_tech
from scene_model.skeleton_builder import is_animation_document, is_skeleton_document
from .anim_importer import AnimImportError, import_anim, import_animation_cs2
from .cs2_importer import import_cs2
from .cs2_parsed_importer import import_cs2_parsed
from .rigid_model_v2_importer import import_rigid_model_v2
from .skeleton_importer import import_skeleton
from .vegetation_importer import import_vegetation, import_vegetation_tech, is_vegetation_model
from .vmd_importer import import_vmd

# Which workflow each kind of file belongs to, so importing one leaves the sidebar showing the
# panels that can actually edit what just arrived.
WORKFLOW_BY_KIND = {
    "SKELETON": "SKELETON",
    "BUILDING": "BUILDING",
    "UNIT PART": "UNIT",
    "VARIANT MESH": "UNIT",
    "ANIMATION": "SKELETAL_ANIMATION",
    # A debris bundle is a building's compiled output brought back in for reference, so it belongs
    # with the workflow that authors buildings rather than with the skeletal clips.
    "DEBRIS ANIMATION": "BUILDING",
    "VEGETATION": "VEGETATION",
}


class UnsupportedFileError(Exception):
    pass


def _import_cs2_document(filepath: str, context: bpy.types.Context):
    document = read_cs2(Path(bpy.path.abspath(filepath)).read_bytes())

    if is_animation_document(document):
        try:
            return import_animation_cs2(filepath, context, document)
        except AnimImportError as error:
            raise UnsupportedFileError(str(error)) from error
    # A weighted unit part is structurally a building plus a WEIGHTED_MODEL node, so the building
    # importer would happily read one and produce a mesh-less mess. Say so instead: this add-on
    # reads unit parts back from their compiled .rigid_model_v2, not from the authored .cs2.
    if document.weighted_models:
        raise UnsupportedFileError(
            "This .cs2 is an authored unit part - it holds weighted models. Import the compiled "
            ".rigid_model_v2 instead; reading a unit part back from its .cs2 source is not "
            "implemented."
        )

    kind = "SKELETON" if is_skeleton_document(document) else "BUILDING"
    importer = import_skeleton if kind == "SKELETON" else import_cs2
    collection, warnings = importer(filepath, context, document)
    return collection, warnings, kind


# One entry per supported file type, longest suffix first so ".cs2.parsed" is never taken for a
# ".cs2". This is the whole dispatch: there is deliberately one import operator, and what a file
# actually is comes from its own name and contents rather than from which menu entry was used.
def import_file(filepath: str, context: bpy.types.Context) -> tuple[bpy.types.Collection, list[str], str]:
    name = Path(bpy.path.abspath(filepath)).name.lower()

    if name.endswith(".anim"):
        try:
            collection, warnings, kind = import_anim(filepath, context)
        except AnimImportError as error:
            raise UnsupportedFileError(str(error)) from error
    elif name.endswith(".rigid_model_v2"):
        # What a compiled model is comes from the shaders inside it, not from where it sits: a tree
        # and a unit part share the extension, and the unit importer would read a tree as a rigid
        # attachment with no material it can author.
        if is_vegetation_model(read_rigid_model_v2(Path(bpy.path.abspath(filepath)).read_bytes())):
            collection, warnings = import_vegetation(filepath, context)
            kind = "VEGETATION"
        else:
            collection, warnings = import_rigid_model_v2(filepath, context)
            kind = "UNIT PART"
    elif name.endswith(".variantmeshdefinition"):
        collection, warnings = import_vmd(filepath, context)
        kind = "VARIANT MESH"
    elif name.endswith(".cs2.parsed"):
        # Vegetation's sidecar shares the extension but is version 0 - a bare hull with no building
        # header at all - so the building reader cannot even open it.
        if is_vegetation_tech(Path(bpy.path.abspath(filepath)).read_bytes()):
            collection, warnings = import_vegetation_tech(filepath, context)
            kind = "VEGETATION"
        else:
            collection, warnings = import_cs2_parsed(filepath, context)
            kind = "BUILDING"
    elif name.endswith(".cs2"):
        collection, warnings, kind = _import_cs2_document(filepath, context)
    else:
        raise UnsupportedFileError(
            f"'{Path(filepath).name}' is not a file type this add-on reads. It imports .cs2, "
            ".cs2.parsed, .anim, .rigid_model_v2 and .variantmeshdefinition files."
        )

    context.scene.tw_workflow = WORKFLOW_BY_KIND[kind]
    return collection, warnings, kind
