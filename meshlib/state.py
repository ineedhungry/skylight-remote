"""Load/save the mesh configuration (skylight-mesh.json).

Important: the mesh replay protection silently discards messages with a
sequence number it has already seen. So that a crashed run (sent, but not
saved) doesn't lock us out, the sequence number jumps forward by a safety
margin on every load and is written back immediately.
"""

import json

SEQ_SAFETY_JUMP = 512


def load_cfg(path: str) -> dict:
    with open(path) as f:
        cfg = json.load(f)
    cfg["seq"] = cfg.get("seq", 0) + SEQ_SAFETY_JUMP
    save_cfg(path, cfg)
    return cfg


def save_cfg(path: str, cfg: dict):
    with open(path, "w") as f:
        json.dump(cfg, f, indent=2)
