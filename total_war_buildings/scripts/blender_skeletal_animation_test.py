import sys
import tempfile
import traceback
from pathlib import Path

import addon_utils
import bpy

REPO_ROOT = r"C:\Users\Khaiali\source\repos\blender_buildings_plugin"
ASSEMBLY_KIT_ROOT = r"D:\SteamLibrary\steamapps\common\Total War Attila\assembly_kit"
SKELETON_CS2 = Path(ASSEMBLY_KIT_ROOT) / "raw_data" / "animations" / "skeletons" / "rome_man_game.cs2"
CLIP_CS2 = (
    Path(ASSEMBLY_KIT_ROOT)
    / "raw_data"
    / "animations"
    / "ROME2"
    / "human"
    / "battle"
    / "sword_and_shield"
    / "locomotion"
    / "sws_run_443_cm.cs2"
)
REFERENCE_ANIM = Path(ASSEMBLY_KIT_ROOT) / "working_data" / "animations" / "skeletons" / "rome_man_game.anim"

if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

# The pose is rebuilt through float32 edit-bone head/tail/roll and a 16-bit compressed quaternion in
# the compiled .anim, so a round trip lands close rather than exact. Both are far below visible.
POSITION_TOLERANCE = 1e-3
ROTATION_TOLERANCE = 2e-3

failures = []


def check(label: str, condition: bool) -> None:
    print(("  OK   " if condition else "  FAIL ") + label)
    if not condition:
        failures.append(label)


def quaternion_distance(a, b) -> float:
    same = max(abs(x - y) for x, y in zip(a, b))
    flipped = max(abs(x + y) for x, y in zip(a, b))
    return min(same, flipped)


def reset_scene() -> None:
    for collection in list(bpy.data.collections):
        bpy.data.collections.remove(collection)
    for obj in list(bpy.data.objects):
        bpy.data.objects.remove(obj)
    for armature in list(bpy.data.armatures):
        bpy.data.armatures.remove(armature)
    for action in list(bpy.data.actions):
        bpy.data.actions.remove(action)


def main() -> None:
    for path in (SKELETON_CS2, CLIP_CS2):
        if not path.exists():
            raise RuntimeError(f"Sample not found: {path}")

    module = addon_utils.enable("total_war_buildings", default_set=True, persistent=False)
    if module is None:
        raise RuntimeError("addon_utils.enable returned failure")

    from binary.anim_reader import read_anim
    from binary.cs2_reader import read_cs2
    from bob import rules
    from extraction.animation_extract import extract_animation
    from extraction.bone_space import engine_to_blender_bone, world_engine_matrices
    from extraction.skeleton_extract import extract_skeleton_from_armature
    from importer import import_file
    from importer.anim_importer import FIRST_FRAME, apply_action, bake_clip, clip_from_anim
    from scene_model.animation_builder import (
        AnimationBuildError,
        animation_from_cs2_document,
        cs2_frame_rate,
    )
    from scene_model.animation_models import AnimationClip
    from scene_model.models import AnimationKeyframes
    from validation.rules import has_blocking_issues, validate_animation

    print("\n== registration ==")
    check("import operator registered", "import_file" in dir(bpy.ops.tw_buildings))
    for name in ("set_animation_clip", "clear_animation_clip", "delete_animation_clip", "new_animation_clip", "validate_animation", "export_animation"):
        check(f"operator {name} registered", name in dir(bpy.ops.tw_buildings))
    check("clip menu registered", hasattr(bpy.types, "TW_MT_animation_clips"))
    check("animation panel registered", hasattr(bpy.types, "TW_PT_animation_setup"))
    from ui.operators import IMPORT_FILTER_GLOB, MAX_FILTER_GLOB_PATTERN

    patterns = IMPORT_FILTER_GLOB.split(";")
    check("*.anim is offered in the file browser", "*.anim" in patterns)
    check(
        "every filter pattern is within Blender's 15-character limit",
        all(len(pattern) <= MAX_FILTER_GLOB_PATTERN for pattern in patterns),
    )

    print("\n== a clip .cs2 imports onto the skeleton it animates ==")
    reset_scene()
    collection, warnings, kind = import_file(str(SKELETON_CS2), bpy.context)
    check("skeleton imported", kind == "SKELETON")
    armature_object = next(obj for obj in collection.all_objects if obj.type == "ARMATURE")

    document = read_cs2(CLIP_CS2.read_bytes())
    expected_rate = cs2_frame_rate(document)
    check("clip .cs2 samples at 60 fps", expected_rate == 60)
    source_clip = animation_from_cs2_document(document, CLIP_CS2.stem, expected_rate)

    _collection, warnings, kind = import_file(str(CLIP_CS2), bpy.context)
    check("clip .cs2 routed as an animation", kind == "ANIMATION")
    check("workflow switched to Skeletal Animation", bpy.context.scene.tw_workflow == "SKELETAL_ANIMATION")
    action = armature_object.animation_data.action
    check("clip landed on the imported skeleton", action is not None and action.name == CLIP_CS2.stem)
    check("clip is kept in the .blend", action.use_fake_user)
    check("clip carries its own rate", action.tw_frame_rate == expected_rate)
    check(
        "scene plays the clip's own frame range",
        (bpy.context.scene.frame_start, bpy.context.scene.frame_end)
        == (FIRST_FRAME, FIRST_FRAME + source_clip.frame_count - 1),
    )
    check("scene plays at the clip's own rate", bpy.context.scene.render.fps == round(expected_rate))

    print("\n== the imported pose matches the file it came from ==")
    # The strongest available check: rebuild the source clip's own bone world transforms straight
    # from the .cs2 and compare them against what Blender is actually posed to, frame by frame.
    skeleton, _ = extract_skeleton_from_armature(armature_object, "rome_man_game")
    index_by_name = {bone.name: index for index, bone in enumerate(skeleton.bones)}
    worst_position = 0.0
    worst_rotation = 0.0
    for frame_index in (0, source_clip.frame_count // 2, source_clip.frame_count - 1):
        bpy.context.scene.frame_set(FIRST_FRAME + frame_index)
        posed = list(skeleton.bones)
        for name, keyframes in source_clip.tracks.items():
            index = index_by_name.get(name)
            if index is None:
                continue
            translation = keyframes.translations[min(frame_index, len(keyframes.translations) - 1)]
            rotation = keyframes.rotations[min(frame_index, len(keyframes.rotations) - 1)]
            posed[index] = type(posed[index])(
                name=name,
                parent_index=posed[index].parent_index,
                translation=translation,
                rotation=rotation,
            )
        expected = [engine_to_blender_bone(matrix) for matrix in world_engine_matrices(posed)]
        for index, bone in enumerate(skeleton.bones):
            actual = armature_object.matrix_world @ armature_object.pose.bones[bone.name].matrix
            worst_position = max(worst_position, (actual.translation - expected[index].translation).length)
            worst_rotation = max(
                worst_rotation,
                quaternion_distance(actual.to_quaternion(), expected[index].to_quaternion()),
            )
    print(f"       worst position {worst_position:.3e} m, worst rotation {worst_rotation:.3e}")
    check("every bone is posed where the clip says", worst_position < POSITION_TOLERANCE)
    check("every bone is rotated as the clip says", worst_rotation < ROTATION_TOLERANCE)

    print("\n== the clip survives a re-export ==")
    skeleton, clip, _warnings = extract_animation(
        armature_object, action, bpy.context.scene, bpy.context.evaluated_depsgraph_get()
    )
    check("re-extracted clip keeps its frame count", clip.frame_count == source_clip.frame_count)
    check("re-extracted clip keeps its rate", clip.frame_rate == expected_rate)
    # A clip .cs2 carries a track for every node in the animator's scene; the ones that matter are
    # those that actually move, and every one of those has to survive a round trip.
    moving = {
        name
        for name, keyframes in source_clip.tracks.items()
        if len(keyframes.translations) > 1 or len(keyframes.rotations) > 1
    }
    check("every moving bone comes back out", moving <= set(clip.tracks) | {"ref_skeleton"})
    check(
        "a statically posed bone survives too",
        "bn_lefthandindex2" in clip.tracks,
    )
    worst = 0.0
    for name, keyframes in source_clip.tracks.items():
        if name not in clip.tracks:
            continue
        rebuilt = clip.tracks[name]
        for frame_index in range(0, source_clip.frame_count, 7):
            source = keyframes.rotations[min(frame_index, len(keyframes.rotations) - 1)]
            written = rebuilt.rotations[min(frame_index, len(rebuilt.rotations) - 1)]
            worst = max(worst, quaternion_distance(source, written))
    print(f"       worst rotation drift {worst:.3e}")
    check("re-exported rotations match the source", worst < ROTATION_TOLERANCE)
    check(
        "a static bone writes no track of its own",
        len(clip.tracks) < len(skeleton.bones),
    )

    print("\n== quaternion continuity ==")
    flips = 0
    for keyframes in clip.tracks.values():
        for first, second in zip(keyframes.rotations, keyframes.rotations[1:]):
            if sum(a * b for a, b in zip(first, second)) < 0.0:
                flips += 1
    check("no track flips its quaternion sign between neighbouring keys", flips == 0)

    print("\n== the exported document ==")
    from scene_model.animation_builder import build_animation_cs2_document
    from binary.cs2_writer import write_cs2

    document = build_animation_cs2_document(skeleton, clip, output_path="test.CS2")
    written = read_cs2(write_cs2(document))
    check("the whole skeleton is written, not just the animated bones", len(written.scene_root.scene_nodes) == len(skeleton.bones))
    multi_key = [node for node in written.scene_root.scene_nodes if len(node.anim.rotations) > 1]
    check("animated bones carry multi-key tracks", len(multi_key) > 20)
    check(
        "the timeline carries the clip's own duration",
        abs(written.timeline_block.end_frame_time - clip.duration) < 1e-6,
    )
    from binary.cs2_templates import SKELETON_SCENE_ROOT_ROTATION, scene_root_rotation_of

    check(
        "the scene root keeps the skeleton's half turn",
        scene_root_rotation_of(written.scene_root.scene_hierarchy_metadata) == SKELETON_SCENE_ROOT_ROTATION,
    )

    print("\n== rules.bob ==")
    text = rules.animation_rules_text([(clip.name, skeleton.name, clip.frame_rate)])
    check("the section BOB reads is [Animation]", text.startswith("[Animation]\r\n"))
    check("core translations are suppressed as CA's own folders do", "CoreTranslations = false" in text)
    check("ExportAsReferencePose is not set - this is a clip, not a rest pose", "ExportAsReferencePose" not in text)
    check("the clip names its skeleton", f"AnimationType = {skeleton.name}" in text)
    check("the clip names its sampling rate", f"FPS={clip.frame_rate:g}" in text)
    check("the override names the file", f"<Files> = ...{clip.name}.cs2" in text)

    with tempfile.TemporaryDirectory() as directory:
        folder = Path(directory)
        (folder / "rules.bob").write_bytes(text.encode("ascii"))
        appended = rules.ensure_animation_rules(
            str(folder.parent), folder / "x.CS2", [("second_clip", "rome_man_game", 20.0)]
        )
        check("a second clip is appended rather than refused", appended is None or "second_clip" in appended.read_text())

    print("\n== a compiled .anim imports as a clip ==")
    reset_scene()
    collection, _warnings, _kind = import_file(str(SKELETON_CS2), bpy.context)
    armature_object = next(obj for obj in collection.all_objects if obj.type == "ARMATURE")
    if REFERENCE_ANIM.exists():
        animation = read_anim(REFERENCE_ANIM.read_bytes())
        compiled_clip = clip_from_anim(animation, "reference_pose")
        check("a compiled rest pose has a track per bone", len(compiled_clip.tracks) == len(animation.bones))
        baked = bake_clip(armature_object, compiled_clip, extract_skeleton_from_armature(armature_object, "rome_man_game")[0])
        bpy.context.scene.frame_set(FIRST_FRAME)
        worst = 0.0
        for bone in armature_object.data.bones:
            pose = armature_object.pose.bones[bone.name]
            worst = max(worst, (pose.matrix.translation - bone.matrix_local.translation).length)
        print(f"       worst rest-pose drift {worst:.3e} m")
        check("BOB's own compile of the rest pose reproduces the rest pose", worst < 1e-2)
        bpy.data.actions.remove(baked)
    else:
        print("       (no compiled rome_man_game.anim on disk - skipped)")

    print("\n== a clip cannot conjure a skeleton ==")
    reset_scene()
    if REFERENCE_ANIM.exists():
        try:
            import_file(str(REFERENCE_ANIM), bpy.context)
            check("a rest-pose .anim is refused as a clip", False)
        except Exception as error:
            check("a rest-pose .anim is refused as a clip", "rest pose" in str(error))

    print("\n== validation ==")
    reset_scene()
    collection, _warnings, _kind = import_file(str(SKELETON_CS2), bpy.context)
    armature_object = next(obj for obj in collection.all_objects if obj.type == "ARMATURE")
    issues = validate_animation(armature_object, None, bpy.context.scene)
    check("no clip blocks an export", has_blocking_issues(issues))
    issues = validate_animation(None, None, bpy.context.scene)
    check("no skeleton blocks an export", has_blocking_issues(issues))

    empty = bpy.data.actions.new("empty_clip")
    issues = validate_animation(armature_object, empty, bpy.context.scene)
    check("a clip that keys nothing blocks an export", has_blocking_issues(issues))

    _collection, _warnings, _kind = import_file(str(CLIP_CS2), bpy.context)
    action = armature_object.animation_data.action
    issues = validate_animation(armature_object, action, bpy.context.scene)
    check("a real clip passes validation", not has_blocking_issues(issues))
    dropped = [issue for issue in issues if "will not reach the compiled" in issue.message]
    check(
        "a translated core bone is warned about, not blocked",
        all(issue.severity == "WARNING" for issue in dropped),
    )

    print("\n== back to the rest pose, and deleting a clip ==")
    from ui import animation_operators
    from ui.animation_operators import clips_for, rest_pose, stop_playback

    bpy.context.scene.frame_set(FIRST_FRAME + 20)

    def rest_drift() -> float:
        return max(
            (armature_object.pose.bones[bone.name].matrix.translation - bone.matrix_local.translation).length
            for bone in armature_object.data.bones
        )

    check("a played clip really moves the skeleton", rest_drift() > 0.1)
    armature_object.animation_data.action = None
    bpy.context.view_layer.update()
    # Taking the Action off is not enough on its own - a pose channel keeps the last value the clip
    # drove it to, which is what made the first Rest Pose button leave the skeleton mid-stride.
    check("unassigning the clip on its own leaves the skeleton posed", rest_drift() > 0.1)
    armature_object.animation_data.action = action
    bpy.context.view_layer.update()

    # Background Blender cannot actually play, but it does carry a screen with is_animation_playing
    # false, so the guard's own path is exercised: calling it must do nothing and disturb nothing.
    before = bpy.context.scene.frame_current
    stop_playback(bpy.context)
    check("stopping playback while nothing plays changes no frame", bpy.context.scene.frame_current == before)

    # That both buttons actually ask for it is checked by standing in for it, rather than by reading
    # the source - the operators call the module-level name, so replacing it records the calls.
    calls = []
    original = animation_operators.stop_playback
    animation_operators.stop_playback = lambda context: calls.append(context)
    try:
        bpy.ops.tw_buildings.clear_animation_clip()
        check("Rest Pose stops the timeline", len(calls) == 1)
        armature_object.animation_data.action = action
        spare = bpy.data.actions.new("spare_clip")
        bpy.ops.tw_buildings.delete_animation_clip(clip=spare.name)
        check("Delete stops the timeline too", len(calls) == 2)
    finally:
        animation_operators.stop_playback = original
    armature_object.animation_data.action = action
    bpy.context.scene.frame_set(FIRST_FRAME + 20)

    rest_pose(armature_object)
    bpy.context.view_layer.update()
    check("Rest Pose takes the clip off", armature_object.animation_data.action is None)
    check("Rest Pose puts every bone back", rest_drift() < 1e-6)
    check("Rest Pose keeps the clip itself", CLIP_CS2.stem in bpy.data.actions)

    armature_object.animation_data.action = action
    bpy.context.scene.frame_set(FIRST_FRAME + 20)
    bpy.ops.tw_buildings.delete_animation_clip(clip=action.name)
    bpy.context.view_layer.update()
    check("deleting removes the clip from the file", CLIP_CS2.stem not in bpy.data.actions)
    check("deleting also puts the skeleton back", rest_drift() < 1e-6)
    # The frame keeps advancing under a cleared skeleton in a real Blender; with nothing driving the
    # pose channels it has to stay at rest wherever the playhead lands.
    for frame in (FIRST_FRAME, FIRST_FRAME + 10, FIRST_FRAME + 30):
        bpy.context.scene.frame_set(frame)
        bpy.context.view_layer.update()
        check(f"a cleared skeleton stays at rest on frame {frame}", rest_drift() < 1e-6)
    check("a deleted clip is no longer offered", CLIP_CS2.stem not in [c.name for c in clips_for(armature_object)])

    _collection, _warnings, _kind = import_file(str(CLIP_CS2), bpy.context)
    action = armature_object.animation_data.action
    check("a deleted clip can be imported again", action is not None and action.name == CLIP_CS2.stem)

    print("\n== switching clips does not leave the last one's pose behind ==")
    # The bug this pins: a clip only keys the bones it animates, and bake_clip computes each of those
    # against its ancestors sitting at rest. rome_man_game's ref_skeleton rests at identity but CA's
    # sws_run_443_cm poses it a quarter turn about X on a single key, so a second clip that does not
    # key ref_skeleton used to inherit that quarter turn - which is what tipped a .anim-imported
    # clip 90 degrees face-down, at random, depending on what had been loaded before it.
    reset_scene()
    collection, _warnings, _kind = import_file(str(SKELETON_CS2), bpy.context)
    armature_object = next(obj for obj in collection.all_objects if obj.type == "ARMATURE")
    rest_of = {bone.name: bone.matrix_local.copy() for bone in armature_object.data.bones}

    import_file(str(CLIP_CS2), bpy.context)
    posed_clip = armature_object.animation_data.action
    bpy.context.scene.frame_set(FIRST_FRAME)
    bpy.context.view_layer.update()
    helper = armature_object.pose.bones["ref_skeleton"]
    turn = (helper.matrix.to_quaternion().rotation_difference(rest_of["ref_skeleton"].to_quaternion()).angle)
    check("CA's clip really does pose ref_skeleton away from its rest", turn > 1.0)

    # A second clip that keys nothing but one bone - ref_skeleton must go back to rest under it.
    sparse = bpy.data.actions.new("sparse_clip")
    sparse.tw_frame_rate = 20.0
    armature_object.animation_data.action = sparse
    hips = armature_object.pose.bones["bn_hips"]
    hips.rotation_mode = "QUATERNION"
    hips.keyframe_insert(data_path="rotation_quaternion", frame=FIRST_FRAME)
    hips.keyframe_insert(data_path="rotation_quaternion", frame=FIRST_FRAME + 5)
    armature_object.animation_data.action = posed_clip

    apply_action(armature_object, sparse, bpy.context.scene)
    bpy.context.scene.frame_set(FIRST_FRAME)
    bpy.context.view_layer.update()
    # bn_hips' own descendants legitimately follow the one bone this clip does key, so what must be
    # back at rest is everything else - ref_skeleton, the bone the old clip turned, among them.
    keyed = armature_object.data.bones["bn_hips"]
    driven = {keyed.name} | {bone.name for bone in keyed.children_recursive}
    drift = max(
        (armature_object.pose.bones[name].matrix.translation - rest.translation).length
        for name, rest in rest_of.items()
        if name not in driven
    )
    turn = armature_object.pose.bones["ref_skeleton"].matrix.to_quaternion().rotation_difference(
        rest_of["ref_skeleton"].to_quaternion()
    ).angle
    check("a bone the new clip does not key is back at its rest transform", drift < 1e-6)
    check("ref_skeleton no longer carries the previous clip's quarter turn", turn < 1e-4)

    # This section reset the scene, so the checks below take the live clip and skeleton from it.
    apply_action(armature_object, posed_clip, bpy.context.scene)
    action = posed_clip

    print("\n== a clip for the wrong skeleton is refused ==")
    stray = bpy.data.armatures.new("stray")
    stray_object = bpy.data.objects.new("stray", stray)
    bpy.context.scene.collection.objects.link(stray_object)
    bpy.context.view_layer.objects.active = stray_object
    bpy.ops.object.mode_set(mode="EDIT")
    bone = stray.edit_bones.new("not_a_real_bone")
    bone.head = (0.0, 0.0, 0.0)
    bone.tail = (0.0, 0.2, 0.0)
    bpy.ops.object.mode_set(mode="OBJECT")
    stray_object.animation_data_create().action = action
    issues = validate_animation(stray_object, action, bpy.context.scene)
    check("a clip whose bones do not exist blocks an export", has_blocking_issues(issues))

    print("\n== the empty-clip guard ==")
    empty_clip = AnimationClip(name="nothing", skeleton_name="rome_man_game", frame_rate=20.0, frame_count=10)
    skeleton, _ = extract_skeleton_from_armature(armature_object, "rome_man_game")
    try:
        build_animation_cs2_document(skeleton, empty_clip)
        check("a clip with no tracks is refused", False)
    except AnimationBuildError:
        check("a clip with no tracks is refused", True)

    unknown = AnimationClip(
        name="unknown",
        skeleton_name="rome_man_game",
        frame_rate=20.0,
        frame_count=2,
        tracks={"no_such_bone": AnimationKeyframes([0.0], [(0.0, 0.0, 0.0)], [0.0], [(0.0, 0.0, 0.0, 1.0)])},
    )
    try:
        build_animation_cs2_document(skeleton, unknown)
        check("a clip naming a bone the skeleton lacks is refused", False)
    except AnimationBuildError:
        check("a clip naming a bone the skeleton lacks is refused", True)

    print("\n== clip picker ==")
    from ui.animation_operators import animation_armature

    bpy.context.scene.tw_workflow = "SKELETAL_ANIMATION"
    bpy.context.view_layer.objects.active = armature_object
    armature_object.select_set(True)
    check("the picker finds the skeleton", animation_armature(bpy.context) is armature_object)
    names = [clip.name for clip in clips_for(armature_object)]
    check("the imported clip is offered", CLIP_CS2.stem in names)

    # The clip menu is not a Panel, so blender_panel_draw_test's sweep does not reach it.
    listed: list[str] = []
    stub = type(
        "StubLayout",
        (),
        {
            "label": lambda self, **kwargs: None,
            "operator": lambda self, idname, **kwargs: listed.append(kwargs.get("text", ""))
            or type("Properties", (), {})(),
        },
    )()
    bpy.types.TW_MT_animation_clips.draw(type("MenuStub", (), {"layout": stub})(), bpy.context)
    check("the menu lists the clips the picker offers", listed == names)

    print()
    if failures:
        print(f"{len(failures)} CHECK(S) FAILED:")
        for failure in failures:
            print(f"  - {failure}")
        raise SystemExit(1)
    print("ALL SKELETAL ANIMATION CHECKS PASSED")


try:
    main()
except SystemExit:
    raise
except Exception:
    traceback.print_exc()
    raise SystemExit(1)
