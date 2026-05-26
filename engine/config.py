"""Configuration management for Qiang Backup."""
import sys
import json
from pathlib import Path

DEFAULT_CONFIG = {
    "config_version": 2,
    "source_folders": [],
    "backup_root": "D:/强哥备份",
    "extensions": [
        ".GBQ7", ".GSH7", ".GSC7", ".GPV7", ".GEPC7", ".GPB7", ".GTJ",
        ".GPB6", ".GPB5", ".GBG9", ".GPE9", ".GBQ6", ".GBQ5", ".GBQ4",
        ".GZB4", ".GTB4", ".GPB9", ".GEPC6", ".GPV6", ".GPV5", ".GSC6",
        ".GSC5", ".GSH6", ".GSH5", ".GBQSH4", ".GBGSH4", ".GXMSH4",
        ".GDBSH4", ".GXMDBSH4", ".GPC5", ".GBQPC4", ".GBGPC9", ".GZBPC4",
        ".GTBPC4", ".GPBPC9", ".GPBEC9", ".GEC5",
    ],
    "password": "强哥备份",
    "debounce_seconds": 3,
    "max_versions": 5,
    "anomaly_threshold": 3,
    "autostart": False,
    "monitor_was_running": False,
}


def _get_app_dir():
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    else:
        return Path(__file__).resolve().parent.parent


CONFIG_PATH = _get_app_dir() / "config.json"


def load_config(config_path=CONFIG_PATH):
    if not config_path.exists():
        return dict(DEFAULT_CONFIG)
    try:
        with open(config_path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError):
        return dict(DEFAULT_CONFIG)
    merged = dict(DEFAULT_CONFIG)
    merged.update({k: v for k, v in data.items() if k in merged})
    return merged


def save_config(config, config_path=CONFIG_PATH):
    config_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = config_path.with_suffix(".tmp")
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(config, f, ensure_ascii=False, indent=2)
        tmp.replace(config_path)
    except OSError:
        try:
            tmp.unlink(missing_ok=True)
        except OSError:
            pass
