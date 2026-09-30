"""Project config: .carma/config.yaml (contract 3), with defaults filled in."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from carma.contracts import validation_errors
from carma.model import yaml_io

CARMA_DIR = ".carma"
CONFIG_FILE = "config.yaml"

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
