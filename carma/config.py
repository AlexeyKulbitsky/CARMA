"""Project config: .carma/config.yaml (contract 3), with defaults filled in."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path

from carma.contracts import validation_errors
from carma.model import yaml_io
from carma.model.files import write_atomic

CARMA_DIR = ".carma"
CONFIG_FILE = "config.yaml"
SCHEMA_VERSION = "config/0.1"

DEFAULT_IGNORE = ("**/third_party/**", "**/thirdparty/**", "**/external/**", "build/**", "out/**")
DEFAULT_EDITOR_URI = "vscode://file/{abs_path}:{line}"


class ConfigError(Exception):
    pass


@dataclass(frozen=True)
class Config:
    project_root: Path
    compile_commands: str | None = None
    cmake_build_dir: str | None = None
    configuration: str | None = None
    indexer: str = "libclang"
    libclang: str | None = None
    index_ignored_tus: bool = False
    source_roots: tuple[str, ...] = ()
    ignore: tuple[str, ...] = DEFAULT_IGNORE
    skeleton_depth: int = 2
    max_nodes: int = 300
    editor_uri: str = DEFAULT_EDITOR_URI
    raw: dict = field(default_factory=dict, compare=False, repr=False)

    @property
    def carma_dir(self) -> Path:
        return self.project_root / CARMA_DIR

    @property
    def cache_dir(self) -> Path:
        return self.carma_dir / "cache"

    def editor_link(self, path: str, line: int) -> str:
        """editor_uri with {abs_path} (absolute, '/' separators) and {line} (1-based) filled in.

        A '/' right before {abs_path} is not doubled: 'vscode://file/{abs_path}' works for both
        'C:/src/a.cpp' and '/home/me/src/a.cpp'.
        """
        absolute = (self.project_root / path).as_posix()
        template = self.editor_uri
        if absolute.startswith("/") and "/{abs_path}" in template:
            template = template.replace("/{abs_path}", "{abs_path}")
        return template.replace("{abs_path}", absolute).replace("{line}", str(line))


def find_project_root(start: Path) -> Path:
    """The closest folder at or above start that contains .carma/config.yaml."""
    start = start.resolve()
    for folder in (start, *start.parents):
        if (folder / CARMA_DIR / CONFIG_FILE).is_file():
            return folder
    raise ConfigError(f"no {CARMA_DIR}/{CONFIG_FILE} found in {start} or its parents")


def load_config(project_root: Path) -> Config:
    path = project_root / CARMA_DIR / CONFIG_FILE
    if not path.is_file():
        raise ConfigError(f"{path} does not exist")
    data = yaml_io.to_plain(yaml_io.load(path))
    errors = validation_errors("config", data)
    if errors:
        raise ConfigError(f"{path} is invalid:\n  " + "\n  ".join(errors))
    compile_db = data["compile_db"]
    indexer = data.get("indexer", {})
    return Config(
        project_root=project_root.resolve(),
        compile_commands=compile_db.get("compile_commands"),
        cmake_build_dir=compile_db.get("cmake_build_dir"),
        configuration=compile_db.get("configuration"),
        indexer=indexer.get("name", "libclang"),
        libclang=indexer.get("libclang"),
        index_ignored_tus=indexer.get("index_ignored_tus", False),
        source_roots=tuple(data.get("source_roots", ())),
        ignore=tuple(data.get("ignore", DEFAULT_IGNORE)),
        skeleton_depth=data.get("skeleton_depth", 2),
        max_nodes=data.get("max_nodes", 300),
        editor_uri=data.get("editor_uri", DEFAULT_EDITOR_URI),
        raw=data,
    )


# ---------------------------------------------------------------- carma init

GITIGNORE = "cache/\n"

_CONFIG_TEMPLATE = """\
schema_version: {schema_version}
compile_db:
{compile_db}
indexer:
  name: libclang
  libclang: null                  # path to the libclang library; null searches automatically
  index_ignored_tus: false        # also parse translation units under the ignore globs
source_roots: {source_roots}{source_roots_note}
ignore:                           # symbols here go to _external; extend for the project
{ignore}
skeleton_depth: 2                 # model skeleton depth, counted from each source root
max_nodes: 300                    # above this, a level groups its nodes by files or folders
editor_uri: "{editor_uri}"
"""


def detect_compile_db(project_root: Path) -> dict | None:
    """compile_commands.json in the root or in build/, then a CMake build folder build/."""
    for rel in ("compile_commands.json", "build/compile_commands.json"):
        if (project_root / rel).is_file():
            return {"compile_commands": rel}
    if (project_root / "build" / "CMakeCache.txt").is_file():
        return {"cmake_build_dir": "build", "configuration": "Debug"}
    return None


def project_relative(project_root: Path, path: Path) -> str:
    """A path given on the command line as the config stores it: relative to the project root, with '/'."""
    absolute = path if path.is_absolute() else Path.cwd() / path
    try:
        rel = os.path.relpath(absolute.resolve(), project_root.resolve())
    except ValueError as exc:  # another drive on Windows
        raise ConfigError(f"{path} must be on the same drive as the project") from exc
    return Path(rel).as_posix()


def write_config(project_root: Path, compile_db: dict, source_roots: list[str]) -> Path:
    """Create .carma/config.yaml with the defaults of the spec, and .carma/.gitignore for the cache."""
    if "compile_commands" in compile_db:
        block = f"  compile_commands: {json.dumps(compile_db['compile_commands'])}"
    else:
        block = (f"  cmake_build_dir: {json.dumps(compile_db['cmake_build_dir'])}    # read through the CMake File API\n"
                 f"  configuration: {json.dumps(compile_db.get('configuration', 'Debug'))}    # for multi-config generators")
    text = _CONFIG_TEMPLATE.format(
        schema_version=SCHEMA_VERSION,
        compile_db=block,
        source_roots=json.dumps(source_roots),
        source_roots_note="" if source_roots else "                # empty: the skeleton starts at the project root",
        ignore="\n".join(f"  - {json.dumps(glob)}" for glob in DEFAULT_IGNORE),
        editor_uri=DEFAULT_EDITOR_URI,
    )
    errors = validation_errors("config", yaml_io.to_plain(yaml_io.loads(text)))
    if errors:
        raise ConfigError("the new config.yaml would be invalid:\n  " + "\n  ".join(errors))
    carma_dir = project_root / CARMA_DIR
    write_atomic(carma_dir / CONFIG_FILE, text)
    if not (carma_dir / ".gitignore").exists():
        write_atomic(carma_dir / ".gitignore", GITIGNORE)
    return carma_dir / CONFIG_FILE
