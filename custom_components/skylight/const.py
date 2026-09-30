"""Constants for the Skylight integration."""

from __future__ import annotations

DOMAIN = "skylight"

PLATFORMS = ["light"]

# Static mesh keys live in the config entry; these are the required fields of a
# provisioned skylight-mesh.json.
CONF_MAC = "mac"
CONF_NET_KEY = "net_key"
CONF_APP_KEY = "app_key"
CONF_DEV_KEY = "dev_key"
CONF_UNICAST = "unicast"
CONF_SRC = "src"
CONF_IV_INDEX = "iv_index"

REQUIRED_KEYS = (
    CONF_MAC,
    CONF_NET_KEY,
    CONF_APP_KEY,
    CONF_DEV_KEY,
    CONF_UNICAST,
    CONF_SRC,
    CONF_IV_INDEX,
)

# Runtime counters (persisted separately from the entry, they change often).
CONF_SEQ = "seq"
CONF_TID = "tid"

# On load, jump the sequence number forward so a crashed/unsaved run can't fall
# behind the lamp's replay-protection window. Mirrors meshlib/state.py.
SEQ_SAFETY_JUMP = 512

STORAGE_VERSION = 1
