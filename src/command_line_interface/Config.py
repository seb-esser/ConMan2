"""
`conman2.py config` - show and change the base configuration.

    conman2.py config                  interactive menu (falls back to 'show' if stdin is not a terminal)
    conman2.py config menu             interactive menu (always)
    conman2.py config show
    conman2.py config get <key>
    conman2.py config set <key> <value>
    conman2.py config reset
"""
import json
import os
import sys

from cli_config import ConMan2Config as cfgmod

TIMELINE_FILE = os.path.join("timeline_data", "timeline.json")


def _tracked_projects() -> list:
    if not os.path.exists(TIMELINE_FILE):
        return []
    with open(TIMELINE_FILE, encoding="utf-8") as f:
        return list(json.load(f))


def _change_warnings(key: str, old: str, new: str) -> list:
    warnings = []
    if key == "graph_backend" and old != new and _tracked_projects():
        warnings.append(
            f"Warning: tracked projects exist. Graph versions stored in '{old}' are not migrated to '{new}'. "
            f"Patches and the timeline are backend-independent: add the current version of each project again "
            f"with the new backend, or switch back.")
    if key == "increment_representation" and new == "rdf-patch":
        warnings.append("Note: rdf-patch applies to RDF projects only; IFC and GeoJSON commits keep using conman patches.")
    if key == "rdf_tbox" and old != new and _tracked_projects():
        warnings.append("Note: changing rdf_tbox affects new versions only; commits made before keep their setting.")
    return warnings


def _menu(input_fn, output):
    cfg = cfgmod.stored()
    original = dict(cfg)
    keys = list(cfgmod.SCHEMA)
    while True:
        output("")
        output(cfgmod.format_config(cfg))
        output("")
        for i, key in enumerate(keys, 1):
            output(f"  {i}) change {key}")
        output("  s) save and exit    q) quit without saving    r) reset to defaults")
        choice = input_fn("Select: ").strip().lower()
        if choice == "q":
            output("No changes saved." if cfg != original else "Unchanged.")
            return original
        if choice == "s":
            cfgmod.save(cfg)
            for key in keys:
                for warning in _change_warnings(key, original[key], cfg[key]):
                    output(warning)
            output(f"Saved to {os.path.abspath(cfgmod.config_path())}.")
            return cfg
        if choice == "r":
            cfg = cfgmod.defaults()
            continue
        if not choice.isdigit() or not 1 <= int(choice) <= len(keys):
            output(f"Invalid selection {choice!r}.")
            continue
        key = keys[int(choice) - 1]
        spec = cfgmod.SCHEMA[key]
        output(f"\n{key}: {spec['help']}")
        if spec["choices"]:
            for i, option in enumerate(spec["choices"], 1):
                output(f"  {i}) {option}{'  (current)' if option == cfg[key] else ''}")
            value = input_fn("Select value [Enter = keep]: ").strip()
            if not value:
                continue
            if value.isdigit() and 1 <= int(value) <= len(spec["choices"]):
                value = spec["choices"][int(value) - 1]
        else:
            value = input_fn(f"New value [Enter = keep '{cfg[key]}']: ").strip()
            if not value:
                continue
        try:
            cfg[key] = cfgmod.validate(key, value)
        except cfgmod.ConfigError as e:
            output(str(e))


def config_command(action: str = None, key: str = None, value: str = None, input_fn=input, output=print,
                   interactive: bool = None):
    if interactive is None:
        interactive = sys.stdin is not None and sys.stdin.isatty()
    if action == "menu" or (action is None and interactive):
        return _menu(input_fn, output)
    if action is None:
        action = "show"
    if action == "show":
        cfg = cfgmod.load()
        output(cfgmod.format_config(cfg))
        return cfg
    if action == "get":
        if not key:
            raise cfgmod.ConfigError("Usage: config get <key>")
        output(cfgmod.get(key))
        return cfgmod.load()
    if action == "set":
        if not key or value is None:
            raise cfgmod.ConfigError("Usage: config set <key> <value>")
        old = cfgmod.stored()[key] if key in cfgmod.SCHEMA else cfgmod.get(key)
        cfg = cfgmod.set_value(key, value)
        for warning in _change_warnings(key, old, value):
            output(warning)
        output(cfgmod.format_config(cfg))
        return cfg
    if action == "reset":
        cfg = cfgmod.reset()
        output(cfgmod.format_config(cfg))
        return cfg
    raise cfgmod.ConfigError(f"Unknown config action {action!r}. Use menu, show, get, set or reset.")
