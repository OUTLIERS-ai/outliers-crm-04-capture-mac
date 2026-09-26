"""
settings.py -- the handful of numbers this layer needs, held as data.

Same idea as the record contract in Layer 2: a setting lives in a file you own, not
buried in code, so you can change it without editing anything and so there is one
place to look when you want to know what the system currently believes.

The file is `_engine/settings.json` inside your CRM. If it is missing, the defaults
below are used, so nothing breaks.

Use:
    import settings
    s = settings.load()
    s["park_after_days"]
"""

import json
import os
from pathlib import Path

DEFAULTS = {
    "park_after_days": 30,
    "refresh_days": {"active": 0, "warm": 30, "cold": 90},
    "events": {},
}


def vault_root():
    """Where your CRM lives.

    The engine sits inside the CRM folder, so the folder above this file is the CRM
    itself. Setting OUTLIERS_CRM_VAULT overrides that, which is what the tests use so
    they never touch your real records.
    """
    env = os.environ.get("OUTLIERS_CRM_VAULT")
    if env:
        return Path(env)
    return Path(__file__).resolve().parent.parent


def path(root=None):
    return Path(root or vault_root()) / "_engine" / "settings.json"


def load(root=None):
    """The settings, with anything missing filled in from the defaults."""
    out = json.loads(json.dumps(DEFAULTS))          # a fresh copy every call
    p = path(root)
    if p.exists():
        try:
            got = json.loads(p.read_text(encoding="utf-8"))
        except ValueError:
            return out
        for k, v in got.items():
            if k.startswith("_"):
                continue
            if isinstance(v, dict) and isinstance(out.get(k), dict):
                out[k].update(v)
            else:
                out[k] = v
    return out
