"""Bluetooth helpers: prefer HA's local adapter over remote (proxy) scanners.

ESPHome Bluetooth proxies can fail to fully enumerate a mesh device's GATT
table (the provisioning characteristics in particular). When HA's own adapter
is in range of the lamp, a direct local connection discovers everything
correctly, so we route through it in preference to a proxy.
"""

from __future__ import annotations

import logging

from homeassistant.components import bluetooth
from homeassistant.core import HomeAssistant

_LOGGER = logging.getLogger(__name__)

try:  # habluetooth is where the scanner base classes live
    from habluetooth import BaseHaRemoteScanner
except Exception:  # noqa: BLE001 - be resilient across HA versions
    try:
        from homeassistant.components.bluetooth import BaseHaRemoteScanner
    except Exception:  # noqa: BLE001
        BaseHaRemoteScanner = None  # type: ignore[assignment]


def _is_remote(scanner) -> bool:
    """Whether a scanner is a remote proxy (ESPHome/Shelly/etc.)."""
    if BaseHaRemoteScanner is not None:
        try:
            return isinstance(scanner, BaseHaRemoteScanner)
        except Exception:  # noqa: BLE001
            pass
    return "remote" in type(scanner).__name__.lower()


def local_ble_device(hass: HomeAssistant, mac: str, prefer_local: bool = True):
    """Return a connectable BLEDevice, preferring HA's own adapter over proxies.

    Falls back to whatever HA considers the best connectable path (which may be
    a proxy) when no local adapter currently sees the device.
    """
    mac = (mac or "").upper()
    if prefer_local:
        try:
            devices = bluetooth.async_scanner_devices_by_address(
                hass, mac, connectable=True)
        except Exception as err:  # noqa: BLE001
            _LOGGER.debug("async_scanner_devices_by_address failed: %s", err)
            devices = []
        local = [d for d in devices if not _is_remote(d.scanner)]
        if local:
            best = max(
                local,
                key=lambda d: (
                    d.advertisement.rssi if d.advertisement else -999))
            _LOGGER.debug("using local adapter for %s (rssi %s)", mac,
                          best.advertisement.rssi if best.advertisement else "?")
            return best.ble_device
    return bluetooth.async_ble_device_from_address(hass, mac, connectable=True)
