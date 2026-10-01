"""
Config-Flow der Vaultwarden-Integration.

Ein Schritt: URL, optional Admin-Token, SSL-Prüfung. Beim Absenden wird die
Instanz einmal wirklich abgefragt, damit Tippfehler und ein falsches Token
sofort auffallen. Läuft das Token später ab oder wird es geändert, meldet der
Coordinator das und Home Assistant startet den Reauth-Schritt. Über
„Neu konfigurieren" lassen sich URL, Token und SSL-Prüfung nachträglich ändern.
"""

from __future__ import annotations

import logging
from typing import Any
from urllib.parse import urlparse

import aiohttp
import voluptuous as vol
from homeassistant import config_entries
from homeassistant.config_entries import ConfigFlowResult
from homeassistant.const import CONF_NAME, CONF_URL, CONF_VERIFY_SSL
from homeassistant.core import callback
from homeassistant.helpers.aiohttp_client import async_create_clientsession

from .api import (
    AdminDisabled,
    CannotConnect,
    InvalidAuth,
    RateLimited,
    VaultwardenClient,
)
from .const import (
    CONF_ADMIN_TOKEN,
    CONF_SCAN_INTERVAL_MINUTES,
    DEFAULT_NAME,
    DEFAULT_SCAN_INTERVAL_MINUTES,
    DOMAIN,
    MAX_SCAN_INTERVAL_MINUTES,
    MIN_SCAN_INTERVAL_MINUTES,
)

_LOGGER = logging.getLogger(__name__)


def _normalize_url(url: str) -> str:
    """Fehlendes Schema ergänzen und abschließende Slashes entfernen."""
    url = url.strip().rstrip("/")
    if not urlparse(url).scheme:
        url = f"http://{url}"
    return url


class VaultwardenConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Einrichtung über die Oberfläche."""

    VERSION = 1

    def __init__(self) -> None:
        self._reauth_entry: config_entries.ConfigEntry | None = None

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> "VaultwardenOptionsFlow":
        return VaultwardenOptionsFlow()

    async def _async_validate(
        self, url: str, token: str | None, verify_ssl: bool
    ) -> str | None:
        """Verbindung testen. Gibt einen Fehlerschlüssel zurück oder None."""
        session = async_create_clientsession(
            self.hass, verify_ssl=verify_ssl, cookie_jar=aiohttp.CookieJar(unsafe=True)
        )
        client = VaultwardenClient(session, url, token)

        try:
            await client.async_get_server_time()
            if token:
                await client.async_get_user_stats()
        except InvalidAuth:
            return "invalid_auth"
        except RateLimited:
            return "rate_limited"
        except AdminDisabled:
            return "admin_disabled"
        except CannotConnect:
            return "cannot_connect"
        except Exception:  # noqa: BLE001
            _LOGGER.exception("Unerwarteter Fehler beim Prüfen von %s", url)
            return "unknown"
        finally:
            # Die Prüf-Session wird nur hier gebraucht, das Session-Cookie soll
            # nicht in der laufenden Integration weiterleben.
            await session.close()
        return None

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}

        if user_input is not None:
            url = _normalize_url(user_input[CONF_URL])
            token = (user_input.get(CONF_ADMIN_TOKEN) or "").strip() or None
            verify_ssl = user_input.get(CONF_VERIFY_SSL, True)
            name = (user_input.get(CONF_NAME) or "").strip() or DEFAULT_NAME

            await self.async_set_unique_id(url)
            self._abort_if_unique_id_configured()

            error = await self._async_validate(url, token, verify_ssl)
            if error:
                errors["base"] = error
            else:
                return self.async_create_entry(
                    title=name,
                    data={
                        CONF_URL: url,
                        CONF_ADMIN_TOKEN: token,
                        CONF_VERIFY_SSL: verify_ssl,
                        CONF_NAME: name,
                    },
                    options={
                        CONF_SCAN_INTERVAL_MINUTES: DEFAULT_SCAN_INTERVAL_MINUTES
                    },
                )

        current = user_input or {}
        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_URL, default=current.get(CONF_URL, "")): str,
                    vol.Optional(
                        CONF_ADMIN_TOKEN, default=current.get(CONF_ADMIN_TOKEN, "")
                    ): str,
                    vol.Optional(
                        CONF_VERIFY_SSL, default=current.get(CONF_VERIFY_SSL, True)
                    ): bool,
                    vol.Optional(
                        CONF_NAME, default=current.get(CONF_NAME, DEFAULT_NAME)
                    ): str,
                }
            ),
            errors=errors,
        )

    async def async_step_reauth(
        self, entry_data: dict[str, Any]
    ) -> ConfigFlowResult:
        """Wird aufgerufen, wenn das Admin-Token nicht mehr akzeptiert wird."""
        self._reauth_entry = self.hass.config_entries.async_get_entry(
            self.context["entry_id"]
        )
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        entry = self._reauth_entry
        assert entry is not None

        if user_input is not None:
            token = (user_input.get(CONF_ADMIN_TOKEN) or "").strip() or None
            error = await self._async_validate(
                entry.data[CONF_URL], token, entry.data.get(CONF_VERIFY_SSL, True)
            )
            if error:
                errors["base"] = error
            else:
                self.hass.config_entries.async_update_entry(
                    entry, data={**entry.data, CONF_ADMIN_TOKEN: token}
                )
                await self.hass.config_entries.async_reload(entry.entry_id)
                return self.async_abort(reason="reauth_successful")

        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=vol.Schema({vol.Optional(CONF_ADMIN_TOKEN, default=""): str}),
            description_placeholders={"url": entry.data[CONF_URL]},
            errors=errors,
        )


    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """URL, Admin-Token und SSL-Prüfung eines bestehenden Eintrags ändern."""
        errors: dict[str, str] = {}
        entry = self._get_reconfigure_entry()

        if user_input is not None:
            url = _normalize_url(user_input[CONF_URL])
            # Leeres Feld heißt: gespeichertes Token behalten. Das Token wird
            # bewusst nicht vorausgefüllt, damit es nicht im Formular steht.
            token = (user_input.get(CONF_ADMIN_TOKEN) or "").strip() or entry.data.get(
                CONF_ADMIN_TOKEN
            )
            verify_ssl = user_input.get(CONF_VERIFY_SSL, True)

            # Die unique_id ist die URL. Gehört die neue URL schon zu einem
            # anderen Eintrag, abbrechen statt zwei Einträge gleich zu benennen.
            if any(
                other.unique_id == url and other.entry_id != entry.entry_id
                for other in self._async_current_entries(include_ignore=False)
            ):
                return self.async_abort(reason="already_configured")

            error = await self._async_validate(url, token, verify_ssl)
            if error:
                errors["base"] = error
            else:
                return self.async_update_reload_and_abort(
                    entry,
                    unique_id=url,
                    data_updates={
                        CONF_URL: url,
                        CONF_ADMIN_TOKEN: token,
                        CONF_VERIFY_SSL: verify_ssl,
                    },
                )

        current = {**entry.data, **(user_input or {})}
        return self.async_show_form(
            step_id="reconfigure",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_URL, default=current.get(CONF_URL, "")): str,
                    vol.Optional(CONF_ADMIN_TOKEN, default=""): str,
                    vol.Optional(
                        CONF_VERIFY_SSL, default=current.get(CONF_VERIFY_SSL, True)
                    ): bool,
                }
            ),
            description_placeholders={"url": entry.data[CONF_URL]},
            errors=errors,
        )


class VaultwardenOptionsFlow(config_entries.OptionsFlow):
    """Nachträglich änderbar: Abfrageintervall."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        current = self.config_entry.options.get(
            CONF_SCAN_INTERVAL_MINUTES, DEFAULT_SCAN_INTERVAL_MINUTES
        )
        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Optional(CONF_SCAN_INTERVAL_MINUTES, default=current): vol.All(
                        int,
                        vol.Range(
                            min=MIN_SCAN_INTERVAL_MINUTES,
                            max=MAX_SCAN_INTERVAL_MINUTES,
                        ),
                    )
                }
            ),
        )
