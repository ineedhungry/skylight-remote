"""The Philips Skylight (BLE Mesh) integration."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import DOMAIN, PLATFORMS
from .coordinator import SkylightDevice

SkylightConfigEntry = ConfigEntry[SkylightDevice]


async def async_setup_entry(hass: HomeAssistant, entry: SkylightConfigEntry) -> bool:
    """Set up Skylight from a config entry."""
    device = SkylightDevice(hass, entry.entry_id, dict(entry.data))
    await device.async_load()
    entry.runtime_data = device

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: SkylightConfigEntry) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def async_remove_entry(hass: HomeAssistant, entry: SkylightConfigEntry) -> None:
    """Clean up the persisted sequence counter when the entry is removed."""
    device = SkylightDevice(hass, entry.entry_id, dict(entry.data))
    await device.async_remove_storage()
