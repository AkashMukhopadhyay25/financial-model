"""Shared helpers for every notebook: find and load the config, name Unity Catalog objects.

A plain Python file (not a notebook) so it can be imported on Databricks and locally:

    import sys, os
    sys.path.insert(0, <repo root>/00_setup)   # see the bootstrap cell in each notebook
    from ifc_common import load_config, T

Rules:
- Settings live in config/pipeline_config.yml only.
- Table names come from T(cfg, "raw_projects") -> "ifc_challenge.portfolio.raw_projects".
"""
import os
from pathlib import Path

import yaml

CONFIG_RELATIVE = Path("config") / "pipeline_config.yml"


def find_repo_root(start=None):
    """Walk up from `start` (default: current directory) to the folder that holds config/pipeline_config.yml."""
    here = Path(start or os.getcwd()).resolve()
    for folder in [here, *here.parents]:
        if (folder / CONFIG_RELATIVE).is_file():
            return folder
    return None


def resolve_config_path(widget_value=None, repo_root=None):
    """Config path, in order: env var IFC_PIPELINE_CONFIG -> widget -> <repo root>/config/pipeline_config.yml."""
    env = os.environ.get("IFC_PIPELINE_CONFIG")
    if env:
        return str(Path(env).resolve())
    if widget_value:
        return str(Path(widget_value).resolve())
    root = Path(repo_root) if repo_root else find_repo_root()
    if root and (root / CONFIG_RELATIVE).is_file():
        return str(root / CONFIG_RELATIVE)
    raise FileNotFoundError(
        "Could not find config/pipeline_config.yml. Set the notebook widget `config_path`, "
        "or the environment variable IFC_PIPELINE_CONFIG, to its full path.")


def _deep_merge(base: dict, override: dict) -> dict:
    out = dict(base)
    for k, v in override.items():
        out[k] = _deep_merge(out[k], v) if isinstance(v, dict) and isinstance(out.get(k), dict) else v
    return out


def _read_yaml(config_path: Path) -> dict:
    """Read one config file. `extends: <file>` (relative to this file) starts from that file and overrides only the
    keys given here, so e.g. a development config can change the schema and nothing else."""
    with open(config_path) as f:
        cfg = yaml.safe_load(f) or {}
    parent = cfg.pop("extends", None)
    if parent:
        cfg = _deep_merge(_read_yaml((config_path.parent / parent).resolve()), cfg)
    return cfg


def load_config(config_path):
    """Read the YAML and add derived values:
    _config_path, _contracts_dir, environment.landing_root (if not set)."""
    config_path = Path(config_path).resolve()
    cfg = _read_yaml(config_path)
    env = cfg["environment"]
    if not env.get("landing_root"):
        env["landing_root"] = f"/Volumes/{env['catalog']}/{env['schema']}/{env['volume']}"
    contracts_dir = Path(env["contracts_dir"])
    if not contracts_dir.is_absolute():
        contracts_dir = (config_path.parent / contracts_dir).resolve()
    cfg["_config_path"] = str(config_path)
    cfg["_contracts_dir"] = contracts_dir
    return cfg


def T(cfg, name):
    """Fully-qualified Unity Catalog name: {catalog}.{schema}.{name}."""
    env = cfg["environment"]
    return f"{env['catalog']}.{env['schema']}.{name}"


def load_contracts(contracts_dir):
    """All contracts, keyed by contract name."""
    contracts = {}
    for path in sorted(Path(contracts_dir).glob("*.yml")):
        with open(path) as f:
            c = yaml.safe_load(f)
        c["_path"] = str(path)
        contracts[c["contract"]["name"]] = c
    if not contracts:
        raise RuntimeError(f"No contracts found in {contracts_dir}")
    return contracts


def load_order(contracts):
    """Sources a contract depends on come first (projects before monitoring)."""
    ordered, seen = [], set()

    def visit(name):
        if name in seen:
            return
        seen.add(name)
        dep = contracts[name]["contract"].get("depends_on")
        if dep and dep in contracts:
            visit(dep)
        ordered.append(name)

    for name in sorted(contracts):
        visit(name)
    return ordered
