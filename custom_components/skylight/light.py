"""Light platform for the Skylight (on/off only)."""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.light import ColorMode, LightEntity
from homeassistant.const import STATE_ON
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity

from . import SkylightConfigEntry
from .const import DOMAIN
from .coordinator import SkylightDevice

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: SkylightConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the Skylight light from a config entry."""
    async_add_entities([SkylightLight(entry.runtime_data)])


class SkylightLight(LightEntity, RestoreEntity):
    """A Philips Skylight exposed as an on/off light.

    Optimistic: the commanded state is shown immediately and restored on
    restart, so "on" is instant; the BLE write happens in the background and
    corrects the state only if the lamp reports something different.
    """

    _attr_has_entity_name = True
    _attr_name = None
    _attr_color_mode = ColorMode.ONOFF
    _attr_supported_color_modes = {ColorMode.ONOFF}
    _attr_should_poll = False

    def __init__(self, device: SkylightDevice) -> None:
        self._device = device
        self._attr_unique_id = device.mac
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, device.mac)},
            connections={("bluetooth", device.mac)},
            name="Philips Skylight",
            manufacturer="Signify",
            model="Skylight (Telink, Bluetooth SIG Mesh)",
        )
        self._attr_is_on = False

    async def async_added_to_hass(self) -> None:
        """Restore the last commanded state for an instant, correct default."""
        await super().async_added_to_hass()
        last_state = await self.async_get_last_state()
        if last_state is not None and last_state.state in ("on", "off"):
            self._attr_is_on = last_state.state == STATE_ON

    @property
    def available(self) -> bool:
        return self._device.available

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self._set(True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self._set(False)

    async def _set(self, on: bool) -> None:
        # Optimistic: reflect the command instantly, then drive the lamp.
        self._attr_is_on = on
        self.async_write_ha_state()
        try:
            actual = await self._device.async_set_power(on)
        except Exception as err:  # noqa: BLE001 - surface as a clean HA error
            self.async_write_ha_state()  # refresh availability
            raise HomeAssistantError(
                f"Failed to switch Skylight {'on' if on else 'off'}: {err}"
            ) from err
        if actual != on:
            self._attr_is_on = actual
        self.async_write_ha_state()
