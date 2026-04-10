#!/usr/bin/env python3

from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
CONFIG_DIR = ROOT / "docker" / "data"
CONFIG_PATH = CONFIG_DIR / "config.json"
WORKSPACE_DIR = CONFIG_DIR / "workspace"
LMSTUDIO_MODELS_URL = "http://127.0.0.1:1234/api/v0/models"
MODEL_ALIAS = "lmstudio-current"
API_BASE = "http://host.docker.internal:1234/v1"


def load_current_model() -> str:
    try:
        with urllib.request.urlopen(LMSTUDIO_MODELS_URL, timeout=5) as response:
            payload = json.load(response)
    except urllib.error.URLError as exc:
        raise SystemExit(f"LM Studio is not reachable at {LMSTUDIO_MODELS_URL}: {exc}") from exc

    models = payload.get("data", [])
    loaded = [model for model in models if model.get("state") == "loaded"]
    if not loaded:
        raise SystemExit(
            "No model is currently loaded in LM Studio. Load a model in LM Studio first, then run picoclaw_on."
        )

    return str(loaded[0]["id"])


def load_config() -> dict:
    if not CONFIG_PATH.exists():
        return {}
    with CONFIG_PATH.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def ensure_defaults(config: dict, current_model: str) -> dict:
    agents = config.setdefault("agents", {})
    defaults = agents.setdefault("defaults", {})
    defaults.setdefault("workspace", "~/.picoclaw/workspace")
    defaults.setdefault("max_tokens", 4096)
    defaults.setdefault("temperature", 0.2)
    defaults.setdefault("max_tool_iterations", 20)
    defaults["model_name"] = MODEL_ALIAS

    model_list = config.setdefault("model_list", [])
    filtered = [entry for entry in model_list if entry.get("model_name") != MODEL_ALIAS]
    filtered.append(
        {
            "model_name": MODEL_ALIAS,
            "model": f"lmstudio/{current_model}",
            "api_base": API_BASE,
        }
    )
    config["model_list"] = filtered

    tools = config.setdefault("tools", {})
    exec_cfg = tools.setdefault("exec", {})
    exec_cfg["enabled"] = True
    exec_cfg["enable_deny_patterns"] = False
    exec_cfg["allow_remote"] = True
    exec_cfg.setdefault("timeout_seconds", 120)
    exec_cfg["custom_deny_patterns"] = None

    host_exec_cfg = tools.setdefault("host_exec", {})
    host_exec_cfg["enabled"] = True
    root_exec_cfg = tools.setdefault("root_exec", {})
    root_exec_cfg["enabled"] = True
    return config


def main() -> int:
    current_model = load_current_model()
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    WORKSPACE_DIR.mkdir(parents=True, exist_ok=True)

    config = load_config()
    config = ensure_defaults(config, current_model)
    with CONFIG_PATH.open("w", encoding="utf-8") as handle:
        json.dump(config, handle, indent=2, ensure_ascii=True)
        handle.write("\n")

    print(current_model)
    return 0


if __name__ == "__main__":
    sys.exit(main())
