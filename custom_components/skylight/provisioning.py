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

from .bt import local_ble_device
from .mesh import network, provisioner
from .mesh.client import MeshSession, PROXY_DATA_OUT
from .mesh.provisioner import PROV_DATA_OUT
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
    return local_ble_device(hass, mac)


def _has_char(client, uuid: str) -> bool:
    """Whether the connected client's discovered GATT has this characteristic."""
    try:
        if client.services.get_characteristic(uuid) is not None:
            return True
    except Exception:  # noqa: BLE001 - fall back to a manual scan
        pass
    target = uuid.lower()
    return any(
        c.uuid.lower() == target
        for s in client.services
        for c in s.characteristics
    )


async def _connect(hass: HomeAssistant, mac: str, need_uuid: str):
    """Connect and guarantee `need_uuid` is present, busting a stale GATT cache.

    Proxy connections sometimes return an incomplete/cached service table that
    is missing the mesh characteristics; clearing the cache and rediscovering
    fixes it.
    """
    last_missing = False
    for attempt in range(3):
        device = _get_device(hass, mac)
        if device is None:
            raise ProvisioningError(
                f"lamp {mac} is not reachable over Bluetooth (in range of a "
                "proxy/adapter?)")
        client = await establish_connection(
            BleakClientWithServiceCache, device, f"Skylight {mac}",
            max_attempts=CONNECT_ATTEMPTS)
        if _has_char(client, need_uuid):
            return client
        last_missing = True
        _LOGGER.debug(
            "char %s missing on attempt %d; clearing GATT cache and retrying",
            need_uuid, attempt + 1)
        clear = getattr(client, "clear_cache", None)
        if clear is not None:
            try:
                await clear()
            except Exception:  # noqa: BLE001
                pass
        try:
            await client.disconnect()
        except Exception:  # noqa: BLE001
            pass
        await asyncio.sleep(1.5)

    if last_missing:
        short = need_uuid[4:8]
        raise ProvisioningError(
            f"the mesh characteristic 0x{short} was not found on the lamp's "
            "GATT table even after clearing the cache. This is almost always a "
            "stale service cache on the ESPHome Bluetooth proxy. Restart the "
            "ESP proxy (or move the lamp near HA's built-in adapter) and retry.")
    raise ProvisioningError("could not connect to the lamp")


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

    net_key = os.urandom(16)
    app_key = os.urandom(16)
    iv_index = 0

    # 1) PB-GATT provisioning over a direct connection. Ensure the provisioning
    #    data-out characteristic is actually present (busting a stale cache).
    client = await _connect(hass, mac, PROV_DATA_OUT)
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

    # 2) The lamp reboots as a proxy; wait, then bind the AppKey. This is
    #    best-effort: PB-GATT already minted the keys and the lamp is now in OUR
    #    network, so we must NEVER lose them here -- otherwise the lamp would be
    #    stranded in a network we can't talk to (and can't reset without the
    #    remote). If binding fails we keep the keys and surface a warning; the
    #    entry is still created so we can retry/recover with the DevKey we hold.
    try:
        await asyncio.sleep(PROXY_RESTART_WAIT)
        await _wait_for_device(hass, mac, REDISCOVER_TIMEOUT)
        client = await _connect(hass, mac, PROXY_DATA_OUT)
        try:
            session = MeshSession(client, cfg)
            await session.start()
            await _appkey_add_and_bind(session, cfg)
            await session.stop()
        finally:
            try:
                await client.disconnect()
            except Exception:  # noqa: BLE001
                pass
    except Exception as err:  # noqa: BLE001
        _LOGGER.warning(
            "Skylight PB-GATT provisioning succeeded but AppKey/bind did not "
            "complete (%s). Keeping the keys so the lamp isn't stranded; on/off "
            "may not work until it is re-bound.", err)

    return {k: cfg[k] for k in REQUIRED_KEYS}
