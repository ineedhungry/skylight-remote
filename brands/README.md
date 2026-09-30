# Skylight brand images

Home Assistant does **not** load an integration's icon from this repo — it
serves brand images from the separate [`home-assistant/brands`][brands]
repository (`https://brands.home-assistant.io/<domain>/icon.png`). So these
files live here only as the source; they take effect once they're merged into
the brands repo. Until then the integration shows the default placeholder icon
(purely cosmetic).

These are **original** artwork (a framed skylight window over a daylight sky
with a warm sun) — deliberately not the Philips/Signify logo, which is
trademarked and would be rejected for an unofficial community integration.

## Files

| File | Size | Purpose |
|---|---|---|
| `icon.png` | 256×256 | square icon (1x) |
| `icon@2x.png` | 512×512 | square icon (2x) |
| `logo.png` | 256×78 | horizontal wordmark (1x) |
| `logo@2x.png` | 512×156 | horizontal wordmark (2x) |

Regenerate them with `python3 brands/make_icon.py` (needs only Pillow).

## Submitting to home-assistant/brands

1. Fork and clone [`home-assistant/brands`][brands].
2. Create `custom_integrations/skylight/` and copy the four PNGs into it:
   ```
   custom_integrations/skylight/icon.png
   custom_integrations/skylight/icon@2x.png
   custom_integrations/skylight/logo.png
   custom_integrations/skylight/logo@2x.png
   ```
   The folder name **must** equal the integration domain (`skylight`).
3. Open a pull request. CI checks dimensions, that images are trimmed and are
   valid PNGs, and that `<domain>` matches an integration.
4. After it merges, restart HA (and clear the browser cache) — the icon then
   appears on the integration and its device.

[brands]: https://github.com/home-assistant/brands
