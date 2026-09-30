"""Config flow for the Skylight integration."""

from __future__ import annotations

import json
from typing import Any

import voluptuous as vol

from homeassistant.components.bluetooth import BluetoothServiceInfoBleak
from homeassistant.config_entries import ConfigFlow, ConfigFlowResult

from .const import CONF_MAC, DOMAIN, REQUIRED_KEYS

CONF_CONFIG_JSON = "config_json"


def _parse_keys(raw: str) -> dict:
    """Parse and validate a provisioned skylight-mesh.json blob.

    Raises ValueError with a translation key on any problem.
    """
    try:
        data = json.loads(raw)
    except (json.JSONDecodeError, TypeError) as err:
        raise ValueError("invalid_json") from err
    if not isinstance(data, dict):
        raise ValueError("invalid_json")
    missing = [k for k in REQUIRED_KEYS if k not in data]
    if missing:
        raise ValueError("missing_keys")
    # Keep only the static keys; runtime seq/tid are managed separately.
    keys = {k: data[k] for k in REQUIRED_KEYS}
    keys[CONF_MAC] = str(keys[CONF_MAC]).upper()
    # carry initial counters through as a starting point if present
    for opt in ("seq", "tid"):
        if opt in data:
            keys[opt] = data[opt]
    return keys


class SkylightConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Skylight."""

    VERSION = 1

    def __init__(self) -> None:
        self._discovered_mac: str | None = None

    async def async_step_bluetooth(
        self, discovery_info: BluetoothServiceInfoBleak
    ) -> ConfigFlowResult:
        """Handle a Bluetooth discovery of the lamp."""
        await self.async_set_unique_id(discovery_info.address)
        self._abort_if_unique_id_configured()
        self._discovered_mac = discovery_info.address
        self.context["title_placeholders"] = {"name": "Philips Skylight"}
        return await self.async_step_keys()

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle a user-initiated setup (manual, no discovery)."""
        return await self.async_step_keys(user_input)

    async def async_step_keys(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Ask for the provisioned mesh keys (paste skylight-mesh.json)."""
        errors: dict[str, str] = {}
        if user_input is not None:
            try:
                keys = _parse_keys(user_input[CONF_CONFIG_JSON])
            except ValueError as err:
                errors["base"] = str(err)
            else:
                mac = keys[CONF_MAC]
                if self._discovered_mac and mac != self._discovered_mac.upper():
                    errors["base"] = "mac_mismatch"
                else:
                    await self.async_set_unique_id(mac, raise_on_progress=False)
                    self._abort_if_unique_id_configured()
                    return self.async_create_entry(
                        title="Philips Skylight", data=keys)

        return self.async_show_form(
            step_id="keys",
            data_schema=vol.Schema({vol.Required(CONF_CONFIG_JSON): str}),
            errors=errors,
            description_placeholders={
                "mac": self._discovered_mac or "the lamp"},
        )
