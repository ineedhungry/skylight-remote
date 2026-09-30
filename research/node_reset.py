#!/usr/bin/env python3
"""
Config Node Reset (0x8049): removes the lamp from OUR mesh - it discards
NetKey/AppKey/DevKey and goes back to the unprovisioned state (afterwards it
advertises 0x1827 again, i.e. pairable for the remote).

Recoverable: re-adopt it into your own network any time with provision.py.

Prerequisite: lamp powered + reachable, bridge stopped.

    sudo systemctl stop skylight-bridge
    python3 research/node_reset.py
"""

import os as _os
import sys as _sys
_ROOT = _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))
_sys.path.insert(0, _ROOT)

import asyncio

from meshlib import network
from meshlib.skylight import CONFIG_FILE
from meshlib.state import load_cfg, save_cfg
from meshlib.proxy import MeshProxy

OP_NODE_RESET = 0x8049
OP_NODE_RESET_STATUS = 0x804A


async def main():
    cfg = load_cfg(CONFIG_FILE)
    ctx = network.NetContext(bytes.fromhex(cfg["net_key"]), cfg["iv_index"])
    dev = bytes.fromhex(cfg["dev_key"])
    lamp = cfg["unicast"]

    async with MeshProxy(cfg["mac"], ctx, cfg["src"], log=lambda *_: None) as proxy:
        print("# Sending Config Node Reset (0x8049) to the lamp ...", flush=True)
        got = False
        for i in range(3):
            await proxy.send_access(cfg, dev, False, lamp, OP_NODE_RESET, b"")
            try:
                await proxy.wait_status(dev, False, OP_NODE_RESET_STATUS,
                                        timeout=4.0)
                got = True
                break
            except TimeoutError:
                print(f"#   attempt {i + 1}: no status response", flush=True)
        save_cfg(CONFIG_FILE, cfg)

    if got:
        print("# >>> Node reset confirmed. The lamp is now UNPROVISIONED.",
              flush=True)
    else:
        print("# No confirmation - the lamp often resets WITHOUT still "
              "responding (by the time it sends the status it is already off "
              "the network). Check with scan.py whether it advertises 0x1827 "
              "again.", flush=True)
    print("# Then: hold ON for 10s on the remote (to pair). To bring it back "
          "into our network: provision.py.", flush=True)


if __name__ == "__main__":
    asyncio.run(main())
