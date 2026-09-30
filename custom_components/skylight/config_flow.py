"""Config flow for the Skylight integration."""

from __future__ import annotations

import json
import logging
from typing import Any

import voluptuous as vol

from homeassistant.components import bluetooth
from homeassistant.components.bluetooth import BluetoothServiceInfoBleak
from homeassistant.config_entries import ConfigFlow, ConfigFlowResult

from .const import CONF_MAC, DOMAIN, REQUIRED_KEYS
from .provisioning import ProvisioningError, async_provision

_LOGGER = logging.getLogger(__name__)

CONF_CONFIG_JSON = "config_json"

# Advertised while the lamp is unprovisioned / provisioned.
UNPROVISIONED_UUID = "00001827-0000-1000-8000-00805f9b34fb"
PROXY_UUID = "00001828-0000-1000-8000-00805f9b34fb"
LAMP_NAME = "BK_MESH_light"


def _parse_keys(raw: str) -> dict:
    """Parse and validate a provisioned skylight-mesh.json blob."""
    try:
        data = json.loads(raw)
    except (json.JSONDecodeError, TypeError) as err:
        raise ValueError("invalid_json") from err
    if not isinstance(data, dict):
        raise ValueError("invalid_json")
    missing = [k for k in REQUIRED_KEYS if k not in data]
    if missing:
        raise ValueError("missing_keys")
    keys = {k: data[k] for k in REQUIRED_KEYS}
    keys[CONF_MAC] = str(keys[CONF_MAC]).upper()
    return keys


def _find_lamp(hass) -> str | None:
    """Look for a Skylight in the current Bluetooth advertisements."""
    for info in bluetooth.async_discovered_service_info(hass, connectable=True):
        uuids = {u.lower() for u in info.service_uuids}
        if info.name == LAMP_NAME or UNPROVISIONED_UUID in uuids or PROXY_UUID in uuids:
            return info.address
    return None


class SkylightConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Skylight."""

    VERSION = 1

    def __init__(self) -> None:
        self._mac: str | None = None

    async def async_step_bluetooth(
        self, discovery_info: BluetoothServiceInfoBleak
    ) -> ConfigFlowResult:
        """Handle a Bluetooth discovery of the lamp."""
        await self.async_set_unique_id(discovery_info.address)
        self._abort_if_unique_id_configured()
        self._mac = discovery_info.address
        self.context["title_placeholders"] = {"name": "Philips Skylight"}
        return await self.async_step_choose()

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle a user-initiated setup (no discovery)."""
        if self._mac is None:
            self._mac = _find_lamp(self.hass)
        return await self.async_step_choose()

    async def async_step_choose(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Let the user provision a fresh lamp or paste existing keys."""
        return self.async_show_menu(
            step_id="choose",
            menu_options=["provision", "keys"],
        )

    async def async_step_provision(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Provision a fresh, factory-reset lamp over HA's Bluetooth."""
        errors: dict[str, str] = {}
        if self._mac is None:
            self._mac = _find_lamp(self.hass)

        if user_input is not None:
            if self._mac is None:
                return self.async_abort(reason="no_device")
            try:
                keys = await async_provision(self.hass, self._mac)
            except ProvisioningError as err:
                _LOGGER.warning("Skylight provisioning failed: %s", err)
                errors["base"] = "provision_failed"
            except Exception:  # noqa: BLE001
                _LOGGER.exception("Unexpected error provisioning Skylight")
                errors["base"] = "provision_failed"
            else:
                await self.async_set_unique_id(
                    keys[CONF_MAC], raise_on_progress=False)
                self._abort_if_unique_id_configured()
                return self.async_create_entry(
                    title="Philips Skylight", data=keys)

        return self.async_show_form(
            step_id="provision",
            data_schema=vol.Schema({}),
            errors=errors,
            description_placeholders={"mac": self._mac or "the lamp"},
        )

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
                if self._mac and mac != self._mac.upper():
                    errors["base"] = "mac_mismatch"
                else:
                    await self.async_set_unique_id(
                        mac, raise_on_progress=False)
                    self._abort_if_unique_id_configured()
                    return self.async_create_entry(
                        title="Philips Skylight", data=keys)

        return self.async_show_form(
            step_id="keys",
            data_schema=vol.Schema({vol.Required(CONF_CONFIG_JSON): str}),
            errors=errors,
            description_placeholders={"mac": self._mac or "the lamp"},
        )
