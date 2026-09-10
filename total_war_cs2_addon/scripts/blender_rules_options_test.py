import sys
import tempfile
from pathlib import Path

import bpy

ADDON = "total_war_cs2_addon"
sys.path.insert(0, str(Path(bpy.utils.user_resource("SCRIPTS")) / "addons" / ADDON))

failures: list[str] = []


def check(label: str, condition: bool) -> None:
    print(("  OK   " if condition else "  FAIL ") + label)
    if not condition:
        failures.append(label)


bpy.ops.preferences.addon_enable(module=ADDON)

from bob import rules  # noqa: E402
from export.exporter import export_building  # noqa: E402
from export.skeleton_exporter import export_skeleton  # noqa: E402
from props.properties import get_always_overwrite_rules  # noqa: E402


def property_names(idname: str) -> set[str]:
    operator = getattr(bpy.ops.tw_buildings, idname)
    return {
        name
        for name in operator.get_rna_type().properties.keys()
        if name.startswith("rules_") and name not in ("rules_overwrite_confirmed", "rules_show_advanced")
    }


def build_building(name: str) -> bpy.types.Collection:
    building = bpy.data.collections.new(name)
    building.tw_role = "BUILDING"
    bpy.context.scene.collection.children.link(building)
    piece = bpy.data.collections.new(f"{name}_piece")
    piece.tw_role = "PIECE"
    building.children.link(piece)
    destruct = bpy.data.collections.new(f"{name}_destruct")
    destruct.tw_role = "DESTRUCT"
    piece.children.link(destruct)
    display = bpy.data.collections.new(f"{name}_display")
    display.tw_role = "DISPLAY"
    destruct.children.link(display)
    collision = bpy.data.collections.new(f"{name}_collision")
    collision.tw_role = "COLLISION"
    destruct.children.link(collision)

    for target, lod in ((display, "LOD01"), (collision, None)):
        bpy.ops.mesh.primitive_cube_add(size=1.0)
        cube = bpy.context.active_object
        for existing in list(cube.users_collection):
            existing.objects.unlink(cube)
        target.objects.link(cube)
        if lod is not None:
            cube.tw_lod_index = lod
            cube.data.materials.append(bpy.data.materials.new(f"{name}_material"))
        else:
            cube.tw_collision_type = "COLLISION"
    return building


print("=== each workflow's dialog carries its own settings and no other's ===")
building_props = property_names("export_building")
unit_props = property_names("export_units")
animation_props = property_names("export_animation")
vegetation_props = property_names("export_vegetation")
skeleton_props = property_names("export_skeleton")

check("the building dialog offers HitPoints", "rules_hit_points" in building_props)
check("the building dialog does not offer a unit's TargetPath", "rules_target_path" not in building_props)
check("the unit dialog offers the skeleton", "rules_animation_type" in unit_props)
check("the unit dialog offers TargetPath", "rules_target_path" in unit_props)
check("the unit dialog does not offer a building's HitPoints", "rules_hit_points" not in unit_props)
check("the clip dialog offers the skeleton", "rules_animation_type" in animation_props)
check("the clip dialog offers the channel flags", "rules_core_translations" in animation_props)
check("the clip dialog offers nothing about textures", not any("texture" in name for name in animation_props))
check("the tree dialog offers the LOD ladder", "rules_lod_distance_4" in vegetation_props)
check("the tree dialog does not offer SaveAGF", "rules_save_agf" not in vegetation_props)
check("the skeleton dialog offers only its target path", skeleton_props == {"rules_target_path"})

print("=== every key BOB documents for a section is reachable from its dialog ===")
DOCUMENTED = {
    "building": (
        building_props,
        {
            "rules_texture_path", "rules_capacity", "rules_hit_points", "rules_audio_material",
            "rules_category", "rules_can_burn", "rules_auxiliary", "rules_joiner",
            "rules_collision_3d", "rules_gun_type", "rules_incendiary_radius",
            "rules_animation_fps", "rules_animation_type", "rules_multiple_buildings",
        },
    ),
    "unit": (
        unit_props,
        {
            "rules_target_path", "rules_target_filename", "rules_target_extension",
            "rules_texture_folder", "rules_texture_subfolder", "rules_animation_type",
            "rules_rigid_category", "rules_update_database", "rules_single_lod",
            "rules_variable_bones_per_vert", "rules_disable_alpha_test", "rules_save_agf",
            "rules_lod_distance_1", "rules_lod_distance_2", "rules_lod_distance_3",
            "rules_lod_distance_4",
        },
    ),
    "animation": (
        animation_props,
        {
            "rules_animation_type", "rules_target_path", "rules_ignore_metadata",
            "rules_core_translations", "rules_face_translations", "rules_face_rotations",
            "rules_left_hand_translations", "rules_left_hand_rotations",
            "rules_right_hand_translations", "rules_right_hand_rotations",
            "rules_cinematic_animation_type", "rules_cinematic_core_translations",
            "rules_cinematic_face_translations", "rules_cinematic_face_rotations",
            "rules_cinematic_left_hand_translations", "rules_cinematic_left_hand_rotations",
            "rules_cinematic_right_hand_translations", "rules_cinematic_right_hand_rotations",
        },
    ),
}
for label, (offered, documented) in DOCUMENTED.items():
    missing = sorted(documented - offered)
    check(f"the {label} dialog reaches every documented key", not missing)
    for name in missing:
        print("          missing:", name)

print("=== the skeleton is pre-filled from the scene ===")
from extraction.unit_extract import skeleton_name_for  # noqa: E402
from ui.unit_operators import _bound_skeleton_name  # noqa: E402


def build_skeleton(name: str) -> bpy.types.Object:
    collection = bpy.data.collections.new(name)
    collection.tw_role = "SKELETON"
    bpy.context.scene.collection.children.link(collection)
    armature_object = bpy.data.objects.new(name, bpy.data.armatures.new(name))
    collection.objects.link(armature_object)
    return armature_object


def build_unit(name: str, armature_object: bpy.types.Object | None) -> bpy.types.Collection:
    unit = bpy.data.collections.new(name)
    unit.tw_role = "UNIT"
    bpy.context.scene.collection.children.link(unit)
    models = bpy.data.collections.new(f"{name}_models")
    models.tw_role = "UNIT_MESH"
    unit.children.link(models)
    mesh = bpy.data.objects.new(f"{name}_lod1", bpy.data.meshes.new(f"{name}_lod1"))
    models.objects.link(mesh)
    if armature_object is not None:
        mesh.modifiers.new(name="Armature", type="ARMATURE").object = armature_object
    return unit


rome = build_skeleton("prefill_rome_man_game")
other = build_skeleton("prefill_other_skeleton")
bound = build_unit("prefill_body", rome)
also_bound = build_unit("prefill_helmet", rome)
differently_bound = build_unit("prefill_horse", other)
rigid = build_unit("prefill_shield", None)

check("the skeleton's name is its collection's", skeleton_name_for(rome) == "prefill_rome_man_game")
check("one bound asset fills the skeleton in", _bound_skeleton_name([bound]) == "prefill_rome_man_game")
check(
    "a batch sharing one skeleton fills it in too",
    _bound_skeleton_name([bound, also_bound]) == "prefill_rome_man_game",
)
check("a batch of two skeletons fills in nothing", _bound_skeleton_name([bound, differently_bound]) == "")
check("an unbound asset fills in nothing", _bound_skeleton_name([rigid]) == "")
check("a rigid asset alongside a bound one does not confuse it",
      _bound_skeleton_name([bound, rigid]) == "prefill_rome_man_game")
check(
    "what is pre-filled is what the per-file line will say",
    _bound_skeleton_name([bound]) == skeleton_name_for(rome),
)
check(
    "and it reaches the file",
    "\tAnimationType = prefill_rome_man_game\r\n"
    in rules.unit_rules_base(rules.UnitRules(animation_type=_bound_skeleton_name([bound]))),
)

print("=== the two building enums are the game's own tables, offered as dropdowns ===")
building_rna = bpy.ops.tw_buildings.export_building.get_rna_type().properties
for name, expected in (
    ("rules_category", rules.BUILDING_CATEGORIES),
    ("rules_audio_material", rules.AUDIO_MATERIALS),
):
    prop = building_rna[name]
    check(f"{name} is a dropdown", prop.type == "ENUM")
    offered = tuple(item.identifier for item in prop.enum_items)
    check(f"{name} offers every value the game's table carries", offered == expected)
    check(f"{name} defaults to a member", prop.default in offered)
check("nine categories", len(rules.BUILDING_CATEGORIES) == 9)
check("twenty-eight audio materials", len(rules.AUDIO_MATERIALS) == 28)

print("=== the LOD ladder is pre-filled with what BOB does anyway ===")
from ui.rules_options import _lod_ladder  # noqa: E402

unit_rna = bpy.ops.tw_buildings.export_units.get_rna_type().properties
tree_rna = bpy.ops.tw_buildings.export_vegetation.get_rna_type().properties
check("BOB's ladder is 100/200/400/500", rules.DEFAULT_LOD_DISTANCES == (100, 200, 400, 500))
for index, expected in enumerate(rules.DEFAULT_LOD_DISTANCES, start=1):
    check(f"the unit dialog shows {expected} for LOD{index}", unit_rna[f"rules_lod_distance_{index}"].default == expected)
    check(f"the tree dialog shows {expected} for LOD{index}", tree_rna[f"rules_lod_distance_{index}"].default == expected)

check("an untouched ladder writes nothing", _lod_ladder(rules.DEFAULT_LOD_DISTANCES) == (None, None, None, None))
check("a moved rung writes all four", _lod_ladder((100, 200, 300, 500)) == (100, 200, 300, 500))
check(
    "so a defaulted unit rules.bob still names no LODDistance",
    "LODDistance" not in rules.unit_rules_base(rules.UnitRules(*(), **{})),
)
moved = rules.unit_rules_base(
    rules.UnitRules(lod_distance_1=100, lod_distance_2=200, lod_distance_3=300, lod_distance_4=500)
)
check("and a moved one names the whole ladder", all(f"LODDistance{i}" in moved for i in (1, 2, 3, 4)))
check("with the rung the artist moved", "\tLODDistance3 = 300\r\n" in moved)

print("=== a key left at BOB's own default is not written to the file ===")
OPTIONAL_KEYS = (
    "CanBurn", "Auxiliary", "Joiner", "Collision3D", "GunType", "TargetFilename",
    "TargetExtension", "RigidCategory", "UpdateDatabase", "SingleLOD", "VariableBonesPerVert",
    "DisableAlphaTest", "CinematicAnimationType", "CinematicCoreTranslations",
)
for label, text in (
    ("building", rules.building_rules_text()),
    ("unit", rules.unit_rules_base()),
    ("clip", rules.animation_rules_base()),
    ("tree", rules.vegetation_rules_base("T\\", "F\\", "sub")),
    ("skeleton", rules.skeleton_rules_text()),
):
    written = [key for key in OPTIONAL_KEYS if key in text]
    check(f"a defaulted {label} rules.bob carries no optional key", not written)
    for key in written:
        print("          written:", key)
check("and a set one is written", "\tCanBurn = false\r\n" in rules.building_rules_text(rules.BuildingRules(can_burn=False)))

print("=== every export dialog draws its panel without raising ===")


# Same stand-in as blender_panel_draw_test.py, for the same reason: a background Blender has no
# region to build a real UILayout in, and a mistyped prop name only shows when the dialog opens.
class StubLayout:
    def __init__(self, problems):
        self._problems = problems

    def _sub(self, *args, **kwargs):
        return StubLayout(self._problems)

    row = column = box = split = _sub

    def label(self, *args, **kwargs):
        icon = kwargs.get("icon")
        if icon is not None and icon not in ICONS:
            self._problems.append(f"icon '{icon}' does not exist")

    def separator(self, *args, **kwargs):
        return None

    def operator(self, idname, **kwargs):
        return type("OperatorProperties", (), {})()

    def prop(self, data, name, **kwargs):
        if data is None or name not in data.bl_rna.properties:
            self._problems.append(f"prop '{name}' does not exist")


ICONS = set(
    bpy.types.UILayout.bl_rna.functions["label"].parameters["icon"].enum_items.keys()
)


class OperatorStub:
    def __init__(self, cls, rna, problems):
        self.bl_rna = rna
        self.layout = StubLayout(problems)
        self.targets = []
        self.clips = []
        for name, prop in rna.properties.items():
            if name == "rna_type" or hasattr(self, name):
                continue
            setattr(self, name, getattr(prop, "default", ""))
        self.compile_with_bob = True
        # The add-on's own methods, bound to this stand-in. Everything above bpy.types.Operator in
        # the MRO is skipped - draw() only ever calls what the mixins define.
        for base in reversed(cls.__mro__):
            if base in set(bpy.types.Operator.__mro__):
                continue
            for name, attr in vars(base).items():
                if name.startswith("__") or name in rna.properties or name == "bl_rna":
                    continue
                setattr(self, name, attr.__get__(self) if callable(attr) else attr)


for idname, cls_name in (
    ("export_building", "TW_OT_export_building"),
    ("export_units", "TW_OT_export_units"),
    ("export_animation", "TW_OT_export_animation"),
    ("export_vegetation", "TW_OT_export_vegetation"),
    ("export_skeleton", "TW_OT_export_skeleton"),
):
    rna = getattr(bpy.ops.tw_buildings, idname).get_rna_type()
    problems: list[str] = []
    stub = OperatorStub(getattr(bpy.types, f"TW_BUILDINGS_OT_{idname}"), rna, problems)
    try:
        getattr(bpy.types, f"TW_BUILDINGS_OT_{idname}").draw(stub, bpy.context)
    except Exception as error:  # noqa: BLE001 - the whole point of the check
        problems.append(f"raised {type(error).__name__}: {error}")
    check(f"{cls_name} draws cleanly", not problems)
    for problem in problems:
        print("         ", problem)

print("=== a defaulted export writes exactly what shipped before ===")
with tempfile.TemporaryDirectory() as temporary:
    kit = Path(temporary) / "kit"
    export_dir = kit / "raw_data" / "art" / "buildings"
    export_dir.mkdir(parents=True)
    building = build_building("rulesopt_default")
    result = export_building(building, str(export_dir), str(kit), bpy.context)
    check("the export succeeded", result.success)
    written = (export_dir / rules.RULES_FILENAME).read_bytes()
    check("the rules.bob is byte-identical to the defaults", written == rules.building_rules_text().encode("ascii"))

print("=== the settings reach the file ===")
with tempfile.TemporaryDirectory() as temporary:
    kit = Path(temporary) / "kit"
    export_dir = kit / "raw_data" / "art" / "buildings"
    export_dir.mkdir(parents=True)
    building = build_building("rulesopt_custom")
    settings = rules.BuildingRules(hit_points=2400, category="fortification", audio_material="stone")
    export_building(building, str(export_dir), str(kit), bpy.context, settings)
    text = (export_dir / rules.RULES_FILENAME).read_bytes().decode("ascii")
    check("HitPoints is the artist's", "\tHitPoints = 2400\r\n" in text)
    check("Category is the artist's", "\tCategory = fortification\r\n" in text)
    check("AudioMaterial is the artist's", "\tAudioMaterial = stone\r\n" in text)
    check("animation_type is still fixed at building", "\tanimation_type = building\r\n" in text)

print("=== no rules.bob is written when BOB is not going to run ===")
with tempfile.TemporaryDirectory() as temporary:
    kit = Path(temporary) / "kit"
    export_dir = kit / "raw_data" / "art" / "buildings"
    export_dir.mkdir(parents=True)
    building = build_building("rulesopt_norules")
    result = export_building(building, str(export_dir), str(kit), bpy.context, None)
    check("the .CS2 is still written", result.success and result.cs2_path.is_file())
    check("no rules.bob is left behind", not (export_dir / rules.RULES_FILENAME).exists())

    skeleton = bpy.data.collections.new("rulesopt_skeleton")
    skeleton.tw_role = "SKELETON"
    bpy.context.scene.collection.children.link(skeleton)
    armature = bpy.data.armatures.new("rulesopt_skeleton")
    armature_object = bpy.data.objects.new("rulesopt_skeleton", armature)
    skeleton.objects.link(armature_object)
    bpy.context.view_layer.objects.active = armature_object
    bpy.ops.object.mode_set(mode="EDIT")
    bone = armature.edit_bones.new("bn_root")
    bone.head = (0.0, 0.0, 0.0)
    bone.tail = (0.0, 0.0, 1.0)
    bpy.ops.object.mode_set(mode="OBJECT")
    skeleton_dir = kit / "raw_data" / "animations" / "skeletons"
    skeleton_dir.mkdir(parents=True)
    export_skeleton(skeleton, str(skeleton_dir), str(kit), None)
    check("a skeleton export writes none either", not (skeleton_dir / rules.RULES_FILENAME).exists())
    export_skeleton(skeleton, str(skeleton_dir), str(kit))
    check("and writes one when BOB will run", (skeleton_dir / rules.RULES_FILENAME).is_file())

print("=== an existing rules.bob is not replaced without confirmation ===")
with tempfile.TemporaryDirectory() as temporary:
    kit = Path(temporary) / "kit"
    export_dir = kit / "raw_data" / "art" / "buildings"
    export_dir.mkdir(parents=True)
    rules_path = export_dir / rules.RULES_FILENAME
    theirs = rules.building_rules_text(rules.BuildingRules(hit_points=99)) + "\r\n[Texture]\r\n\tCompress = true\r\n"
    rules_path.write_bytes(theirs.encode("ascii"))

    building = build_building("rulesopt_conflict")
    mine = rules.BuildingRules(hit_points=2400)
    conflict = rules.rules_conflict(
        str(kit), export_dir, rules.BUILDING_SECTION, rules.building_rules_text(mine), mine
    )
    check("the difference is spotted", "HitPoints: 99 -> 2400" in conflict)
    check(
        "defaults raise no conflict at all",
        rules.rules_conflict(
            str(kit), export_dir, rules.BUILDING_SECTION, rules.building_rules_text(), rules.BuildingRules()
        )
        == [],
    )

    result = export_building(building, str(export_dir), str(kit), bpy.context, mine, False)
    check("the file is untouched without confirmation", rules_path.read_bytes() == theirs.encode("ascii"))
    check(
        "and the artist is told their settings did not reach BOB",
        any("left alone" in warning for warning in result.warnings),
    )

    export_building(building, str(export_dir), str(kit), bpy.context, mine, True)
    text = rules_path.read_bytes().decode("ascii")
    check("confirmed, the settings land", "\tHitPoints = 2400\r\n" in text)
    check("the other section survives the overwrite", "[Texture]\r\n\tCompress = true\r\n" in text)

print("=== a customised export overrides a rule inherited from a parent folder ===")
with tempfile.TemporaryDirectory() as temporary:
    kit = Path(temporary) / "kit"
    parent = kit / "raw_data" / "art"
    export_dir = parent / "buildings"
    export_dir.mkdir(parents=True)
    (parent / rules.RULES_FILENAME).write_bytes(rules.building_rules_text().encode("ascii"))

    building = build_building("rulesopt_inherited")
    export_building(building, str(export_dir), str(kit), bpy.context, rules.BuildingRules())
    check(
        "an untouched export still leaves the parent's rule to do its job",
        not (export_dir / rules.RULES_FILENAME).exists(),
    )
    export_building(
        building, str(export_dir), str(kit), bpy.context, rules.BuildingRules(hit_points=2400)
    )
    check("a customised one writes its own", (export_dir / rules.RULES_FILENAME).is_file())

print("=== a unit re-export keeps every part's skeleton through an overwrite ===")
with tempfile.TemporaryDirectory() as temporary:
    kit = Path(temporary) / "kit"
    export_dir = kit / "raw_data" / "variantmeshes" / "test"
    export_dir.mkdir(parents=True)
    rules_path = export_dir / rules.RULES_FILENAME
    rules_path.write_bytes(
        rules.unit_rules_text([("older_part", "rome_man_game"), ("a_weapon", "")]).encode("ascii")
    )
    written = rules.ensure_unit_rules(
        str(kit),
        export_dir / "new_part.CS2",
        [("new_part", "rome_man_game")],
        rules.UnitRules(texture_subfolder="art"),
        True,
    )
    text = rules_path.read_bytes().decode("ascii")
    check("the file was rewritten", written is not None)
    check("the new sub-folder landed", "\tTextureSubFolder=art\r\n" in text)
    check("the older part kept its skeleton", "<Files> = ...older_part.cs2\r\n\tAnimationType = rome_man_game" in text)
    check("the rigid part kept its empty one", "<Files> = ...a_weapon.cs2\r\n\tAnimationType = \r\n" in text)
    check("the part being exported got its own", "<Files> = ...new_part.cs2" in text)

print("=== a tree's derived paths are not disturbed by its settings ===")
with tempfile.TemporaryDirectory() as temporary:
    kit = Path(temporary) / "kit"
    export_dir = kit / "raw_data" / "battleterrain" / "vegetation" / "trees" / "oak"
    export_dir.mkdir(parents=True)
    rules.ensure_vegetation_rules(
        str(kit), export_dir / "oak.CS2", rules.VegetationRules(incendiary_radius=5.0, lod_distance_1=60)
    )
    text = (export_dir / rules.RULES_FILENAME).read_bytes().decode("ascii")
    expected = rules.vegetation_paths_for(str(kit), export_dir / "oak.CS2")
    check("the target path still mirrors raw_data", f"\tTargetPath = {expected[0]}\r\n" in text)
    check("the settings landed", "\tIncendiaryRadius = 5.0\r\n" in text and "\tLODDistance1 = 60\r\n" in text)
    check("AnimationType is still fixed at tree", "\tAnimationType = tree\r\n" in text)

print("=== the confirmation restarts the same export, with everything it was carrying ===")
with tempfile.TemporaryDirectory() as temporary:
    kit = Path(temporary) / "kit"
    export_dir = kit / "raw_data" / "art" / "buildings"
    export_dir.mkdir(parents=True)
    rules_path = export_dir / rules.RULES_FILENAME
    rules_path.write_bytes(rules.building_rules_text(rules.BuildingRules(hit_points=99)).encode("ascii"))

    building = build_building("rulesopt_restart")
    for obj in bpy.context.selected_objects:
        obj.select_set(False)
    # The operator resolves the kit from the add-on preferences, not from its arguments.
    preferences = bpy.context.preferences.addons[ADDON].preferences
    real_kit, preferences.assembly_kit_root = preferences.assembly_kit_root, str(kit)

    # Exactly the call TW_OT_confirm_rules_overwrite makes: no selection to read, the batch carried
    # in target_names, and the answer folded in as rules_overwrite_confirmed.
    result = bpy.ops.tw_buildings.export_building(
        "EXEC_DEFAULT",
        directory=str(export_dir),
        compile_with_bob=True,
        create_pack=False,
        target_names=building.name,
        rules_hit_points=2400,
        rules_overwrite_confirmed=True,
    )
    check("the restarted export ran", result == {"FINISHED"})
    check("it found its batch without a selection", (export_dir / f"{building.name}.CS2").is_file())
    text = rules_path.read_bytes().decode("ascii")
    check("and it wrote the settings it was restarted with", "\tHitPoints = 2400\r\n" in text)
    preferences.assembly_kit_root = real_kit

print("=== the add-on preference can stand in for the confirmation ===")
check("it is off out of the box", preferences.always_overwrite_rules is False)
preferences.always_overwrite_rules = True
check("and the export layer reads it", get_always_overwrite_rules(bpy.context) is True)
preferences.always_overwrite_rules = False

print("\n" + ("ALL RULES OPTION CHECKS PASSED" if not failures else f"{len(failures)} FAILED: {failures}"))
if failures:
    sys.exit(1)
