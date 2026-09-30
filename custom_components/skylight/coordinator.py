"""Connect-on-demand device controller for the Skylight."""

from __future__ import annotations

import asyncio
import logging

from bleak_retry_connector import BleakClientWithServiceCache, establish_connection

from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store

from .bt import local_ble_device
from .const import (
    CONF_SEQ,
    CONF_TID,
    DOMAIN,
    REQUIRED_KEYS,
    SEQ_SAFETY_JUMP,
    STORAGE_VERSION,
)
from .mesh.client import MeshSession

_LOGGER = logging.getLogger(__name__)

CONNECT_ATTEMPTS = 3


class SkylightDevice:
    """Owns the mesh keys + seq counter and runs one command at a time.

    Each command opens a GATT connection (routed by HA through whichever
    Bluetooth proxy has the best signal), does the mesh exchange, persists the
    advanced sequence number, and disconnects.
    """

    def __init__(self, hass: HomeAssistant, entry_id: str, keys: dict) -> None:
        self.hass = hass
        self._keys = {k: keys[k] for k in REQUIRED_KEYS}
        self.mac: str = str(self._keys["mac"]).upper()
        self.name = f"Skylight {self.mac}"
        self._store: Store = Store(hass, STORAGE_VERSION, f"{DOMAIN}_{entry_id}")
        self._cfg: dict | None = None
        self._lock = asyncio.Lock()
        self.available = True

    async def async_load(self) -> None:
        """Load runtime counters and apply the safety jump once."""
        stored = await self._store.async_load() or {}
        seq = int(stored.get(CONF_SEQ, self._keys.get(CONF_SEQ, 0)))
        tid = int(stored.get(CONF_TID, self._keys.get(CONF_TID, 0)))
        self._cfg = {**self._keys, CONF_SEQ: seq + SEQ_SAFETY_JUMP, CONF_TID: tid}
        await self._save_counters()

    async def _save_counters(self) -> None:
        assert self._cfg is not None
        await self._store.async_save(
            {CONF_SEQ: self._cfg[CONF_SEQ], CONF_TID: self._cfg[CONF_TID]})

    async def async_remove_storage(self) -> None:
        await self._store.async_remove()

    async def _run(self, action: str, on: bool | None = None) -> bool:
        assert self._cfg is not None
        ble_device = local_ble_device(self.hass, self.mac)
        if ble_device is None:
            self.available = False
            raise RuntimeError(
                f"Skylight {self.mac} not reachable through any Bluetooth "
                "proxy/adapter (out of range or asleep)")

        client = await establish_connection(
            BleakClientWithServiceCache, ble_device, self.name,
            max_attempts=CONNECT_ATTEMPTS)
        session = MeshSession(client, self._cfg)
        try:
            await session.start()
            if action == "set":
                assert on is not None
                result = await session.set_power(on)
            else:
                result = await session.get_power()
        finally:
            await session.stop()
            # Persist the advanced seq even if the exchange failed mid-way.
            await self._save_counters()
            try:
                await client.disconnect()
            except Exception:  # noqa: BLE001 - best effort
                pass
        self.available = True
        return result

    async def async_set_power(self, on: bool) -> bool:
        async with self._lock:
            try:
                return await self._run("set", on)
            except Exception:
                self.available = False
                raise

    async def async_get_power(self) -> bool:
        async with self._lock:
            try:
                return await self._run("get")
            except Exception:
                self.available = False
                raise
