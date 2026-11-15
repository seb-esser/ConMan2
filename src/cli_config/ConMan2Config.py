"""
Persistent base configuration of the ConMan2 CLI.

Stored as JSON in ./conman2_config.json (like timeline_data/ and patch_data/ it lives in the working
directory of the repository being versioned). The path can be overridden with the environment variable
CONMAN2_CONFIG.

Options (see SCHEMA):
  graph_backend             neo4j | networkx
  increment_representation  conman | rdf-patch   (rdf-patch is used for RDF projects only)
  rdf_tbox                  exclude | include    (exclude: only the ABox is versioned, the TBox is pinned by hash)
  networkx_data_dir         directory of the NetworkX graph files
"""
import json
import os

CONFIG_ENV = "CONMAN2_CONFIG"
DEFAULT_CONFIG_FILE = "conman2_config.json"

SCHEMA = {
    "graph_backend": {
        "default": "neo4j",
        "choices": ["neo4j", "networkx"],
        "help": "Where graph versions are stored. neo4j: Neo4j database (connection from .env or "
                "localhost:7687). networkx: JSON graph files in networkx_data_dir, no database needed.",
    },
    "increment_representation": {
        "default": "conman",
        "choices": ["conman", "rdf-patch"],
        "help": "How increments between two commits are represented. conman: graph-based topological + "
                "semantic patch (all formats). rdf-patch: RDF Patch (A/D triples) - only for RDF projects; "
                "IFC/GeoJSON projects always use conman.",
    },
    "rdf_tbox": {
        "default": "exclude",
        "choices": ["exclude", "include"],
        "help": "RDF only. exclude: only ABox statements are versioned; the TBox is not stored but pinned "
                "by a canonical hash (RDFC-style). include: version all statements.",
    },
    "networkx_data_dir": {
        "default": "graph_data",
        "choices": None,
        "help": "Directory for NetworkX graph files (graph_backend = networkx).",
    },
}


class ConfigError(ValueError):
    pass


# Per-invocation overrides (conman2.py --backend / --increment). Not persisted.
OVERRIDES = {}


def config_path() -> str:
    return os.environ.get(CONFIG_ENV, DEFAULT_CONFIG_FILE)


def defaults() -> dict:
    return {key: spec["default"] for key, spec in SCHEMA.items()}


def validate(key: str, value: str) -> str:
    if key not in SCHEMA:
        raise ConfigError(f"Unknown config key {key!r}. Known keys: {', '.join(SCHEMA)}")
    choices = SCHEMA[key]["choices"]
    if choices is not None and value not in choices:
        raise ConfigError(f"Invalid value {value!r} for {key}. Choices: {', '.join(choices)}")
    if choices is None and not str(value).strip():
        raise ConfigError(f"{key} must not be empty.")
    return value


def load() -> dict:
    cfg = defaults()
    path = config_path()
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            stored = json.load(f)
        for key, value in stored.items():
            if key in SCHEMA:
                cfg[key] = validate(key, value)
    for key, value in OVERRIDES.items():
        cfg[key] = validate(key, value)
    return cfg


def save(cfg: dict):
    for key, value in cfg.items():
        validate(key, value)
    with open(config_path(), "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=4)


def get(key: str) -> str:
    if key not in SCHEMA:
        raise ConfigError(f"Unknown config key {key!r}. Known keys: {', '.join(SCHEMA)}")
    return load()[key]


def stored() -> dict:
    """Configuration as stored on disk (without per-invocation overrides)."""
    saved = dict(OVERRIDES)
    OVERRIDES.clear()
    try:
        return load()
    finally:
        OVERRIDES.update(saved)


def set_value(key: str, value: str) -> dict:
    cfg = stored()
    cfg[key] = validate(key, value)
    save(cfg)
    return cfg


def reset() -> dict:
    cfg = defaults()
    save(cfg)
    return cfg


def format_config(cfg: dict) -> str:
    width = max(len(k) for k in SCHEMA)
    lines = [f"ConMan2 configuration ({os.path.abspath(config_path())})"]
    for key, spec in SCHEMA.items():
        marker = "" if cfg[key] == spec["default"] else "   (changed)"
        lines.append(f"  {key:<{width}}  {cfg[key]}{marker}")
    return "\n".join(lines)
