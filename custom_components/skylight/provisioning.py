"""In-Home-Assistant provisioning of a fresh (unprovisioned) Skylight.

Runs the PB-GATT handshake over HA's own Bluetooth (a direct local connection
is far more reliable than provisioning through a proxy), then adds the AppKey
and binds it to the light models -- the same sequence as the repo's
provision.py, but driven from a config flow instead of the CLI.

Returns a keys dict ready to store in the config entry.
"""

from __future__ import annotations

import asyncio
import logging
import os

from bleak_retry_connector import BleakClientWithServiceCache, establish_connection

from homeassistant.components import bluetooth
from homeassistant.core import HomeAssistant

from .mesh import network, provisioner
from .mesh.client import MeshSession
from .const import REQUIRED_KEYS

_LOGGER = logging.getLogger(__name__)

LAMP_ADDR = 0x0002          # unicast we assign to the lamp
SRC_ADDR = 0x0001           # us (the HA-side element)

OP_APPKEY_ADD = 0x00
OP_APPKEY_STATUS = 0x8003
OP_MODEL_APP_BIND = 0x803D
OP_MODEL_APP_STATUS = 0x803E

# SIG models the AppKey is bound to (OnOff is the only one that really works,
# the rest are bound to mirror provision.py and stay future-proof).
BIND_MODELS = (0x1000, 0x1300, 0x1303, 0x1307)

CONNECT_ATTEMPTS = 4
PROXY_RESTART_WAIT = 5.0    # seconds for the lamp to reboot as a proxy
REDISCOVER_TIMEOUT = 20.0   # seconds to wait for the lamp to re-advertise


class ProvisioningError(Exception):
    """Provisioning could not be completed."""


def _get_device(hass: HomeAssistant, mac: str):
    return bluetooth.async_ble_device_from_address(hass, mac, connectable=True)


async def _wait_for_device(hass: HomeAssistant, mac: str, timeout: float):
    """Poll until HA has a connectable advertisement for the lamp again."""
    loop = asyncio.get_event_loop()
    deadline = loop.time() + timeout
    while loop.time() < deadline:
        device = _get_device(hass, mac)
        if device is not None:
            return device
        await asyncio.sleep(1.0)
    raise ProvisioningError(
        f"lamp {mac} did not re-appear after provisioning (out of range?)")


async def _appkey_add_and_bind(session: MeshSession, cfg: dict) -> None:
    dev_key = bytes.fromhex(cfg["dev_key"])
    app_key = bytes.fromhex(cfg["app_key"])
    lamp = cfg["unicast"]

    await session.send_access(
        dev_key, False, lamp, OP_APPKEY_ADD, b"\x00\x00\x00" + app_key)
    status = await session.wait_status(
        dev_key, False, OP_APPKEY_STATUS, timeout=8.0)
    if status[0] != 0:
        raise ProvisioningError(f"AppKey Add failed: 0x{status[0]:02x}")

    for model_id in BIND_MODELS:
        params = (lamp.to_bytes(2, "little") + b"\x00\x00"
                  + model_id.to_bytes(2, "little"))
        await session.send_access(
            dev_key, False, lamp, OP_MODEL_APP_BIND, params)
        # A failed bind on a non-OnOff model is not fatal; OnOff is what we use.
        try:
            await session.wait_status(
                dev_key, False, OP_MODEL_APP_STATUS, timeout=8.0)
        except TimeoutError:
            _LOGGER.debug("no bind status for model 0x%04x", model_id)


async def async_provision(hass: HomeAssistant, mac: str) -> dict:
    """Provision a fresh lamp and return its keys dict."""
    mac = mac.upper()
    device = _get_device(hass, mac)
    if device is None:
        raise ProvisioningError(
            f"lamp {mac} is not reachable over Bluetooth (in range? "
            "factory-reset so it advertises as unprovisioned?)")

    net_key = os.urandom(16)
    app_key = os.urandom(16)
    iv_index = 0

    # 1) PB-GATT provisioning over a direct connection.
    client = await establish_connection(
        BleakClientWithServiceCache, device, f"Skylight {mac}",
        max_attempts=CONNECT_ATTEMPTS)
    try:
        dev_key = await provisioner.provision(
            client, net_key, 0, iv_index, LAMP_ADDR, log=_LOGGER.debug)
    except Exception as err:  # noqa: BLE001
        raise ProvisioningError(f"PB-GATT provisioning failed: {err}") from err
    finally:
        try:
            await client.disconnect()
        except Exception:  # noqa: BLE001
            pass

    cfg = {
        "mac": mac,
        "net_key": net_key.hex(),
        "app_key": app_key.hex(),
        "dev_key": dev_key.hex(),
        "unicast": LAMP_ADDR,
        "src": SRC_ADDR,
        "iv_index": iv_index,
        "seq": 0,
        "tid": 0,
    }

    # 2) The lamp reboots as a proxy; wait, then bind the AppKey.
    await asyncio.sleep(PROXY_RESTART_WAIT)
    device = await _wait_for_device(hass, mac, REDISCOVER_TIMEOUT)
    client = await establish_connection(
        BleakClientWithServiceCache, device, f"Skylight {mac}",
        max_attempts=CONNECT_ATTEMPTS)
    session = MeshSession(client, cfg)
    try:
        await session.start()
        await _appkey_add_and_bind(session, cfg)
    except ProvisioningError:
        raise
    except Exception as err:  # noqa: BLE001
        raise ProvisioningError(f"AppKey/bind step failed: {err}") from err
    finally:
        await session.stop()
        try:
            await client.disconnect()
        except Exception:  # noqa: BLE001
            pass

    return {k: cfg[k] for k in REQUIRED_KEYS}
