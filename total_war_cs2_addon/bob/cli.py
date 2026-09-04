import subprocess
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from xml.sax.saxutils import escape

from . import rules

CONFIGURATION_NAME = "blender_export"
PACK_CONFIGURATION_NAME = "blender_pack"
SKELETON_CONFIGURATION_NAME = "blender_skeleton"
UNIT_CONFIGURATION_NAME = "blender_unit"
ANIMATION_CONFIGURATION_NAME = "blender_animation"
TIMEOUT_SECONDS = 900

_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
_ERROR_LOG_LINE_LIMIT = 12

# BOB rejects any bare path on its command line ("Illegal option format"), so what to build comes
# only from this file, and /configuration: takes its bare name - it is always read from
# <assembly_kit>/binaries/BOB/<name>_configuration.xml. A raw source file belongs in
# selected_consumers (the actions that consume it); selected_providers is for build targets and
# silently matches nothing here.
#
# selected_consumers takes one <entry> per file and BOB builds them all in a single run - measured
# for the Building processor with three buildings at once (exit 0, three output folders, empty
# bob_error.log). Every BOB startup costs about twenty seconds whatever it is asked to do, so a
# batch is one run, never one per building.
_CONFIGURATION_TEMPLATE = """<bob_configuration>
    <processors>
        <processor>Building</processor>
    </processors>
    <directories/>
    <global_rules/>
    <retail>0</retail>
    <silent>1</silent>
    <scan_perforce>0</scan_perforce>
    <merge_for_checkin_mode>3</merge_for_checkin_mode>
    <keep_output>1</keep_output>
    <load_asset_graph>0</load_asset_graph>
    <selected_providers/>
    <selected_consumers>
{entries}
    </selected_consumers>
</bob_configuration>
"""

# The Pack processor needs the retail tree scanned as well, because the pack it produces lives there
# and is selected as the file whose *producing* action should run. selected_providers takes one
# <entry> per pack, and rules.write_pack_rules gives the shared working_data/db folder one
# <Files>-scoped [Pack] section per building - measured with two buildings, which came out as two
# packs each holding only its own db tables and its own model.
_PACK_CONFIGURATION_TEMPLATE = """<bob_configuration>
    <processors>
        <processor>Pack</processor>
    </processors>
    <directories>
        <directory>&lt;working>/</directory>
    </directories>
    <global_rules/>
    <retail>1</retail>
    <silent>1</silent>
    <scan_perforce>0</scan_perforce>
    <merge_for_checkin_mode>3</merge_for_checkin_mode>
    <keep_output>1</keep_output>
    <load_asset_graph>0</load_asset_graph>
    <selected_providers>
{entries}
    </selected_providers>
    <selected_consumers/>
</bob_configuration>
"""


# A skeleton, a unit part and an animation clip are none of them a Building, and every part of this
# differs from the building recipe above - all found by probing BOB, not assumed:
#   - the processor is Cs2. Building, Animation, Animations, RigidModelV2, WarscapeShared and
#     ComplexAsset all make BOB write "Couldn't create all processors" into bob_plugin_error.log.
#     RigidModelV2 is a rules.bob section name, not a processor.
#   - <directories> has to name the folder. With the building configuration's empty <directories/>
#     BOB exits 0, writes no log at all and produces nothing, because the selected consumer matches
#     no action - nothing scanned it. The .CS2/.cs2 spelling makes no difference. That is also why
#     everything in one run has to share an export folder.
#   - a skeleton's output lands in working_data/animations/skeletons/ as a .anim plus a
#     .bone_inv_trans_mats, and BOB resolves the .bone_table by name out of
#     raw_data/animations/skeletons/ itself rather than from beside the .cs2 (see
#     export.skeleton_exporter, which warns when an export lands anywhere else).
# selected_consumers takes one <entry> per .CS2 and BOB builds them together - measured for unit
# parts, for three animation clips and for two skeletons, each in a single run. The three kinds
# differ only in which rules.bob covers the folder and in the configuration name, so one template
# serves all of them.
_CS2_CONFIGURATION_TEMPLATE = """<bob_configuration>
    <processors>
        <processor>Cs2</processor>
    </processors>
    <directories>
        <directory>{directory}</directory>
    </directories>
    <global_rules/>
    <retail>0</retail>
    <silent>1</silent>
    <scan_perforce>0</scan_perforce>
    <merge_for_checkin_mode>3</merge_for_checkin_mode>
    <keep_output>1</keep_output>
    <load_asset_graph>0</load_asset_graph>
    <selected_providers/>
    <selected_consumers>
{entries}
    </selected_consumers>
</bob_configuration>
"""


class BobError(Exception):
    pass


@dataclass
class BobResult:
    success: bool
    message: str


def binaries_dir(assembly_kit_root: str) -> Path:
    return Path(assembly_kit_root) / "binaries"


def working_data_output_dir(assembly_kit_root: str, cs2_path: Path) -> Path:
    # Skeletons and animation clips both compile in place: BOB mirrors the .cs2's own raw_data path
    # under working_data rather than redirecting through a rules.bob TargetPath the way units do.
    relative = Path(raw_data_logical_path(assembly_kit_root, cs2_path).removeprefix("<raw>/")).parent
    return Path(assembly_kit_root) / "working_data" / relative


def compiled_output_dir(assembly_kit_root: str, cs2_path: Path) -> Path:
    # BOB lower-cases the building's own folder name but not the path above it
    # (DamageLinkTest.CS2 -> working_data/RigidModels/Buildings/damagelinktest).
    return Path(assembly_kit_root) / "working_data" / "RigidModels" / "Buildings" / Path(cs2_path).stem.lower()


def raw_data_logical_path(assembly_kit_root: str, cs2_path: Path) -> str:
    raw_data = Path(assembly_kit_root) / "raw_data"
    try:
        relative = Path(cs2_path).resolve().relative_to(raw_data.resolve())
    except (ValueError, OSError) as error:
        raise BobError(
            f"BOB can only build files kept inside the Assembly Kit's raw_data folder:\n{raw_data}\n"
            f"'{Path(cs2_path).name}' was exported outside it, so it has to be built by hand."
        ) from error
    return "<raw>/" + relative.as_posix()


def write_configuration(
    assembly_kit_root: str,
    name: str,
    template: str,
    entries: list[str],
    **fields: str,
) -> Path:
    configuration_dir = binaries_dir(assembly_kit_root) / "BOB"
    configuration_path = configuration_dir / f"{name}_configuration.xml"
    escaped = {key: escape(value) for key, value in fields.items()}
    block = "\n".join(f"        <entry>{escape(entry)}</entry>" for entry in entries)
    try:
        configuration_dir.mkdir(parents=True, exist_ok=True)
        configuration_path.write_text(template.format(entries=block, **escaped), encoding="utf-8")
    except PermissionError as error:
        raise BobError(
            f"Windows would not let Blender write BOB's settings file:\n{configuration_path}\n"
            "An Assembly Kit under Program Files needs Blender started as administrator, or the "
            "Assembly Kit folder given write permission for your account."
        ) from error
    except OSError as error:
        raise BobError(f"BOB's settings file could not be written:\n{configuration_path}\n{error}") from error
    return configuration_path


def read_failure_summary(assembly_kit_root: str) -> str:
    try:
        text = (binaries_dir(assembly_kit_root) / "bob_error.log").read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""
    lines = [line.strip() for line in text.splitlines()]
    reported = [line for line in lines if line and not line.startswith("=====") and not line.startswith("Duration:")]
    return "\n".join(reported[:_ERROR_LOG_LINE_LIMIT])


def _executable(assembly_kit_root: str) -> Path:
    executable = binaries_dir(assembly_kit_root) / "BOB.AssemblyKit.exe"
    if not executable.is_file():
        raise BobError(
            f"Could not find BOB at:\n{executable}\n"
            "Check the Assembly Kit folder in the add-on preferences."
        )
    return executable


def is_bob_running() -> bool:
    try:
        listed = subprocess.run(
            ["tasklist", "/FI", "IMAGENAME eq BOB.AssemblyKit.exe", "/NH"],
            capture_output=True,
            text=True,
            timeout=20,
            creationflags=_NO_WINDOW,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return "BOB.AssemblyKit.exe" in listed.stdout


class BobRun:
    def __init__(
        self,
        process: subprocess.Popen,
        assembly_kit_root: str,
        cs2_paths: list[Path],
        success_message: str,
        label: str,
        on_finished: Callable[[BobResult], BobResult] | None = None,
    ) -> None:
        self._process = process
        self._assembly_kit_root = assembly_kit_root
        self._cs2_paths = [Path(path) for path in cs2_paths]
        self._success_message = success_message
        self._label = label
        self._on_finished = on_finished
        self._started_at = time.monotonic()

    @property
    def label(self) -> str:
        return self._label

    def poll(self) -> BobResult | None:
        exit_code = self._process.poll()
        if exit_code is None:
            if time.monotonic() - self._started_at < TIMEOUT_SECONDS:
                return None
            self.abort()
            return self._finish(
                BobResult(
                    success=False,
                    message=(
                        f"BOB was still running after {TIMEOUT_SECONDS // 60} minutes and has been stopped. "
                        f"{_named(self._cs2_paths)} exported successfully - you can still build "
                        "them in BOB by hand."
                    ),
                )
            )
        if exit_code == 0:
            return self._finish(BobResult(success=True, message=self._success_message))
        summary = read_failure_summary(self._assembly_kit_root)
        if summary:
            return self._finish(
                BobResult(success=False, message=f"BOB could not finish this building:\n{summary}")
            )
        return self._finish(
            BobResult(
                success=False,
                message=f"BOB stopped with error code {exit_code} without reporting a reason.",
            )
        )

    def _finish(self, result: BobResult) -> BobResult:
        if self._on_finished is None:
            return result
        callback, self._on_finished = self._on_finished, None
        return callback(result)

    def wait(self) -> BobResult:
        while True:
            result = self.poll()
            if result is not None:
                return result
            time.sleep(0.5)

    def abort(self) -> None:
        try:
            self._process.kill()
        except OSError:
            pass


class BobSequence:
    def __init__(self, run: BobRun, followers: list[Callable[[], BobRun]]) -> None:
        self._run = run
        self._followers = list(followers)

    @property
    def label(self) -> str:
        return self._run.label

    def poll(self) -> BobResult | None:
        result = self._run.poll()
        if result is None:
            return None
        if not result.success or not self._followers:
            return result
        try:
            self._run = self._followers.pop(0)()
        except BobError as error:
            return BobResult(success=False, message=str(error))
        return None

    def wait(self) -> BobResult:
        while True:
            result = self.poll()
            if result is not None:
                return result
            time.sleep(0.5)

    def abort(self) -> None:
        self._run.abort()


def _ensure_bob_free() -> None:
    if is_bob_running():
        raise BobError("BOB is already open. Close it and export again, or build these files in BOB by hand.")


def _named(cs2_paths: list[Path]) -> str:
    return ", ".join(f"'{Path(path).stem}'" for path in cs2_paths)


def _label(verb: str, noun: str, count: int) -> str:
    return f"{verb} the {noun}" if count == 1 else f"{verb} {count} {noun}s"


def _start(
    assembly_kit_root: str,
    configuration_name: str,
    template: str,
    entries: list[str],
    cs2_paths: list[Path],
    success_message: str,
    label: str,
    on_finished: Callable[[BobResult], BobResult] | None = None,
    **configuration_fields: str,
) -> BobRun:
    executable = _executable(assembly_kit_root)
    write_configuration(
        assembly_kit_root,
        configuration_name,
        template,
        entries,
        **configuration_fields,
    )
    try:
        process = subprocess.Popen(
            [
                str(executable),
                "/dont_stop_on_error",
                f"/configuration:{configuration_name}",
                "/offline",
            ],
            cwd=str(executable.parent),
            creationflags=_NO_WINDOW,
        )
    except OSError as error:
        raise BobError(f"BOB could not be started: {error}") from error
    return BobRun(process, assembly_kit_root, cs2_paths, success_message, label, on_finished)


def start_compile(assembly_kit_root: str, cs2_paths: list[Path]) -> BobRun:
    outputs = "\n".join(str(compiled_output_dir(assembly_kit_root, path)) for path in cs2_paths)
    return _start(
        assembly_kit_root,
        CONFIGURATION_NAME,
        _CONFIGURATION_TEMPLATE,
        [raw_data_logical_path(assembly_kit_root, path) for path in cs2_paths],
        cs2_paths,
        f"BOB compiled {_named(cs2_paths)} into:\n{outputs}",
        label=_label("Compiling", "building", len(cs2_paths)),
    )


def start_pack(
    assembly_kit_root: str, cs2_paths: list[Path], pack_type: str = rules.DEFAULT_PACK_TYPE
) -> BobRun:
    building_names = [rules.building_name_for(path) for path in cs2_paths]
    uncompiled = [
        f"'{Path(path).stem}'"
        for path in cs2_paths
        if not compiled_output_dir(assembly_kit_root, path).is_dir()
    ]
    if uncompiled:
        raise BobError(
            f"There is nothing compiled to pack for {', '.join(uncompiled)} - BOB has to build it first."
        )
    rules.write_pack_rules(assembly_kit_root, building_names, pack_type)
    installed = "\n".join(
        str(rules.installed_pack_path(assembly_kit_root, name)) for name in building_names
    )
    try:
        return _start(
            assembly_kit_root,
            PACK_CONFIGURATION_NAME,
            _PACK_CONFIGURATION_TEMPLATE,
            [f"<retail>/data/{name}.pack" for name in building_names],
            cs2_paths,
            f"BOB compiled {_named(cs2_paths)} and packed "
            f"{'it' if len(cs2_paths) == 1 else 'them'} into:\n{installed}"
            f"{_pack_type_note(pack_type)}",
            label=_label("Creating", "pack", len(cs2_paths)),
            on_finished=lambda result: _finish_pack(assembly_kit_root, building_names, result),
        )
    except BobError:
        rules.remove_pack_rules(assembly_kit_root, building_names)
        raise


# A mod pack lands in the same folder as a release one, but the game ignores it until it is switched
# on - so the path on its own would read as ready to play when it is not.
def _pack_type_note(pack_type: str) -> str:
    if pack_type != rules.MOD_PACK_TYPE:
        return ""
    return "\n\nEnable it in the Attila launcher's mod list before it loads in-game."


# The pack rules only exist to drive this one BOB run, so they come straight back out again whether
# it worked or not - leaving them behind would silently redirect a later working_data-wide pack.
def _finish_pack(assembly_kit_root: str, building_names: list[str], result: BobResult) -> BobResult:
    rules.remove_pack_rules(assembly_kit_root, building_names)
    if not result.success:
        return result
    for building_name in building_names:
        try:
            rules.install_pack(assembly_kit_root, building_name)
        except OSError as error:
            return BobResult(
                success=False,
                message=(
                    f"BOB built the pack, but it could not be moved to the game's data folder:\n"
                    f"{rules.pack_path(assembly_kit_root, building_name)}\n{error}"
                ),
            )
    return result


def start_build(
    assembly_kit_root: str,
    cs2_path: Path,
    create_pack: bool = False,
    pack_type: str = rules.DEFAULT_PACK_TYPE,
) -> BobRun | BobSequence:
    return start_building_batch(assembly_kit_root, [cs2_path], create_pack, pack_type)


# However many buildings, this is one BOB run to compile them all and at most one more to pack them
# - the pack has to follow the compile because it packs what the compile produced.
def start_building_batch(
    assembly_kit_root: str,
    cs2_paths: list[Path],
    create_pack: bool = False,
    pack_type: str = rules.DEFAULT_PACK_TYPE,
) -> BobRun | BobSequence:
    if not cs2_paths:
        raise BobError("There is nothing to build.")
    for cs2_path in cs2_paths:
        raw_data_logical_path(assembly_kit_root, cs2_path)
    _executable(assembly_kit_root)
    _ensure_bob_free()
    run = start_compile(assembly_kit_root, cs2_paths)
    if not create_pack:
        return run
    return BobSequence(run, [lambda: start_pack(assembly_kit_root, cs2_paths, pack_type)])


def compile_building(
    assembly_kit_root: str,
    cs2_path: Path,
    create_pack: bool = False,
    pack_type: str = rules.DEFAULT_PACK_TYPE,
) -> BobResult:
    return start_build(assembly_kit_root, cs2_path, create_pack, pack_type).wait()


def _cs2_run(
    assembly_kit_root: str,
    cs2_paths: list[Path],
    configuration_name: str,
    noun: str,
    output_dir: str,
) -> BobRun:
    if not cs2_paths:
        raise BobError("There is nothing to build.")
    entries = [raw_data_logical_path(assembly_kit_root, path) for path in cs2_paths]
    directories = {entry.rsplit("/", 1)[0] + "/" for entry in entries}
    if len(directories) > 1:
        raise BobError(f"All the {noun}s of one build have to be exported into the same folder.")
    _executable(assembly_kit_root)
    _ensure_bob_free()
    return _start(
        assembly_kit_root,
        configuration_name,
        _CS2_CONFIGURATION_TEMPLATE,
        entries,
        cs2_paths,
        f"BOB compiled {_named(cs2_paths)} into:\n{output_dir}",
        label=_label("Compiling", noun, len(cs2_paths)),
        directory=directories.pop(),
    )


def start_skeleton_build(assembly_kit_root: str, cs2_path: Path) -> BobRun:
    return start_skeleton_batch(assembly_kit_root, [cs2_path])


def start_skeleton_batch(assembly_kit_root: str, cs2_paths: list[Path]) -> BobRun:
    if not cs2_paths:
        raise BobError("There is nothing to build.")
    return _cs2_run(
        assembly_kit_root,
        cs2_paths,
        SKELETON_CONFIGURATION_NAME,
        "skeleton",
        str(working_data_output_dir(assembly_kit_root, cs2_paths[0])),
    )


def compile_skeleton(assembly_kit_root: str, cs2_path: Path) -> BobResult:
    return start_skeleton_build(assembly_kit_root, cs2_path).wait()


def unit_output_dir(assembly_kit_root: str) -> Path:
    return Path(assembly_kit_root) / "working_data" / Path(rules.UNIT_TARGET_PATH.replace(chr(92), "/"))


def start_unit_build(assembly_kit_root: str, cs2_paths: list[Path]) -> BobRun:
    return _cs2_run(
        assembly_kit_root,
        cs2_paths,
        UNIT_CONFIGURATION_NAME,
        "unit part",
        str(unit_output_dir(assembly_kit_root)),
    )


def compile_unit_parts(assembly_kit_root: str, cs2_paths: list[Path]) -> BobResult:
    return start_unit_build(assembly_kit_root, cs2_paths).wait()


def start_animation_build(assembly_kit_root: str, cs2_path: Path) -> BobRun:
    return start_animation_batch(assembly_kit_root, [cs2_path])


def start_animation_batch(assembly_kit_root: str, cs2_paths: list[Path]) -> BobRun:
    if not cs2_paths:
        raise BobError("There is nothing to build.")
    return _cs2_run(
        assembly_kit_root,
        cs2_paths,
        ANIMATION_CONFIGURATION_NAME,
        "clip",
        str(working_data_output_dir(assembly_kit_root, cs2_paths[0])),
    )


def compile_animation(assembly_kit_root: str, cs2_path: Path) -> BobResult:
    return start_animation_batch(assembly_kit_root, [cs2_path]).wait()
