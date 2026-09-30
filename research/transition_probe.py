#!/usr/bin/env python3
"""
Question: can the lamp's fade be turned off over mesh?

The lamp doesn't switch, it ramps up. Measured at the bathroom's brightness
sensor (2026-08-09): after the acknowledged "on", the illuminance rose from 0
to 65 lx over about 3 s. The switching chain before it needs only ~170 ms --
so the fade is practically the entire noticeable wait.

A Generic OnOff Set may carry two OPTIONAL bytes after OnOff and TID:
Transition Time and Delay. If they are omitted -- as until now -- the server
uses its own Default Transition Time.

That the firmware knows transitions at all, it says itself: the acknowledgment
to a SET is [present, target, remaining], and remaining is 0x41 --
resolution 1 s, 1 step. This byte is the measuring instrument here:

    remaining == 0x00  ->  no more transition, the field takes effect
    remaining == 0x41  ->  unchanged, the firmware ignores the field

NOTE: the README notes under "On/off path in every variant
(... transition bytes) -> nothing". That was a different question: there we
looked at whether the extra bytes switch a MODE, with the values 0x01-0x06 and
by visual inspection. The value 0x00 never came up, and the transition time as
a transition time was never measured. This script does both.

The bridge must be stopped -- otherwise it holds the BLE connection:
    sudo systemctl stop skylight-bridge
    python3 research/transition_probe.py
    sudo systemctl start skylight-bridge

The lamp switches on and off several times during this.
"""

# --- Path bootstrap: this tool lives in research/, while the stack + the
# config (skylight-mesh.json) live in the repo root one level up. ---
import os as _os, sys as _sys
_ROOT = _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))
_sys.path.insert(0, _ROOT)

import asyncio
import time

from meshlib import skylight as sky_mod
from meshlib.skylight import SkylightClient, transition_wire

# (label, value for SKYLIGHT_TRANSITION_MS)
CASES = [
    ("until now (fields omitted)", "default"),
    ("immediate (0 ms)", "0"),
    ("short fade (300 ms)", "300"),
]


def interpret(b):
    """Transition Time byte -> readable."""
    if b is None:
        return "not given (acknowledgment was shorter than 3 bytes)"
    steps = b & 0x3F
    ms = {0b00: 100, 0b01: 1000, 0b10: 10_000, 0b11: 600_000}[b >> 6]
    if steps == 0x3F:
        return f"0x{b:02x} = unknown"
    return f"0x{b:02x} = {steps} x {ms} ms = {steps * ms / 1000:g} s"


async def main():
    print("Bridge stopped? The lamp is about to switch several times.\n")
    async with SkylightClient() as sky:
        for label, value in CASES:
            sky_mod.TRANSITION_MS = value
            sent = sky_mod.transition_params()
            print(f"=== {label} ===")
            print(f"    appended bytes: "
                  f"{sent.hex() if sent else '(none)'}")
            if value not in ("default",):
                print(f"    of which Transition Time: "
                      f"{interpret(transition_wire(int(value)))}")

            for target in (True, False):
                t0 = time.monotonic()
                sky.last_remaining = None
                await sky.set_power(target)
                dt = (time.monotonic() - t0) * 1000
                print(f"    {'ON ' if target else 'OFF'} acknowledged after "
                      f"{dt:.0f} ms | remaining: {interpret(sky.last_remaining)}")
                # Let the transition finish, otherwise the next case measures
                # into a ramp that is still running.
                await asyncio.sleep(4)
            print()

    print("Analysis: if remaining drops to 0x00 at '0 ms', the field takes "
          "effect and the fade can be turned off.\nIf it stays at 0x41, the "
          "firmware ignores it -- then the fade is not reachable over mesh.")


if __name__ == "__main__":
    asyncio.run(main())
