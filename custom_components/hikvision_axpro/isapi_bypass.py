"""ISAPI zone bypass primitives for Hikvision AX Pro panels.

Self-contained wrapper around the ``hikaxpro`` client implementing zone
bypass/restore with outcome verification, limited retries on transient
errors and firmware feature detection. It deliberately has no Home
Assistant imports so it can be proposed upstream to the ``hikaxpro``
library with minimal rework.

All methods are synchronous (the underlying client is ``requests``
based); callers are expected to wrap them with an executor.
"""

from __future__ import annotations

import logging
import time
from typing import Any

import hikaxpro

_LOGGER = logging.getLogger(__name__)

BYPASS_ENDPOINT = "/ISAPI/SecurityCP/control/bypass/"
RECOVER_BYPASS_ENDPOINT = "/ISAPI/SecurityCP/control/Recoverbypass/"
ZONE_STATUS_ENDPOINT = "/ISAPI/SecurityCP/status/zones"


class BypassError(Exception):
    """Base error for bypass operations."""


class BypassUnsupportedError(BypassError):
    """The panel firmware does not support the bypass endpoint."""


class BypassCommandError(BypassError):
    """The panel rejected the bypass command or it kept failing."""


class BypassVerifyError(BypassError):
    """The panel accepted the command but the re-read state disagrees."""


class AxProBypassClient:
    """Zone bypass primitives with verification and retries."""

    def __init__(
        self,
        axpro: hikaxpro.HikAxPro,
        max_retries: int = 3,
        backoff_base: float = 0.5,
    ) -> None:
        """Wrap an already authenticated HikAxPro client."""
        self._axpro = axpro
        self._max_retries = max_retries
        self._backoff_base = backoff_base

    @staticmethod
    def detect_support(zone_status: dict[str, Any] | None) -> bool:
        """Return True if the panel reports zone bypass states.

        A firmware that exposes the ``bypassed`` field in the zone status
        payload supports the bypass control endpoint. Works on data that
        is already fetched during setup, so no extra request is needed.
        """
        if not zone_status:
            return False
        for wrap in zone_status.get("ZoneList") or []:
            zone = wrap.get("Zone") or {}
            if zone.get("bypassed") is not None:
                return True
        return False

    def fetch_zone_status(self) -> dict[str, Any]:
        """Fetch a fresh zone status payload from the panel."""
        response = self._request("GET", ZONE_STATUS_ENDPOINT)
        return response.json()

    def get_zone_raw(self, zone_id: int) -> dict[str, Any] | None:
        """Fetch a fresh status dict of a single zone, or None if unknown."""
        for wrap in self.fetch_zone_status().get("ZoneList") or []:
            zone = wrap.get("Zone") or {}
            if zone.get("id") == zone_id:
                return zone
        return None

    def bypass(self, zone_id: int) -> None:
        """Bypass a zone and verify the panel applied it."""
        self._control(BYPASS_ENDPOINT, zone_id)
        self._verify(zone_id, expected_bypassed=True)

    def unbypass(self, zone_id: int) -> None:
        """Restore (unbypass) a zone and verify the panel applied it."""
        self._control(RECOVER_BYPASS_ENDPOINT, zone_id)
        self._verify(zone_id, expected_bypassed=False)

    def _control(self, endpoint: str, zone_id: int) -> None:
        response = self._request("PUT", f"{endpoint}{zone_id}")
        _LOGGER.debug("Bypass control %s%s -> %s", endpoint, zone_id, response.text)

    def _verify(self, zone_id: int, expected_bypassed: bool) -> None:
        zone = self.get_zone_raw(zone_id)
        if zone is None:
            raise BypassVerifyError(
                f"Zone {zone_id} not found in status re-read after bypass command"
            )
        if zone.get("bypassed") is not expected_bypassed:
            raise BypassVerifyError(
                f"Zone {zone_id} bypass state is {zone.get('bypassed')}, "
                f"expected {expected_bypassed}"
            )

    def _request(self, method: str, path: str):
        """Perform a JSON ISAPI request with limited retries on transient errors."""
        url = self._axpro.build_url(f"http://{self._axpro.host}{path}", True)
        last_error: Exception | None = None
        for attempt in range(self._max_retries):
            if attempt:
                time.sleep(self._backoff_base * (2 ** (attempt - 1)))
            try:
                response = self._axpro.make_request(url, method, None, True)
            except (ConnectionError, OSError) as err:
                last_error = err
                _LOGGER.debug("Transient error on %s %s: %s", method, path, err)
                continue
            if response is None:
                raise BypassCommandError(f"Unsupported HTTP method {method}")
            if response.status_code == 200:
                return response
            if response.status_code in (403, 404):
                raise BypassUnsupportedError(
                    f"{method} {path} returned {response.status_code}: {response.text}"
                )
            if response.status_code >= 500:
                last_error = BypassCommandError(
                    f"{method} {path} returned {response.status_code}: {response.text}"
                )
                _LOGGER.debug("Transient HTTP %s on %s %s", response.status_code, method, path)
                continue
            raise BypassCommandError(
                f"{method} {path} returned {response.status_code}: {response.text}"
            )
        raise BypassCommandError(
            f"{method} {path} failed after {self._max_retries} attempts: {last_error}"
        )
