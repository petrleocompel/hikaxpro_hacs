"""Tests for the ISAPI bypass primitives."""

from __future__ import annotations

import pytest

from custom_components.hikvision_axpro.isapi_bypass import (
    AxProBypassClient,
    BypassCommandError,
    BypassUnsupportedError,
    BypassVerifyError,
)

from .conftest import MockAxPro, MockResponse, zone_payload


def make_client(panel: MockAxPro, **kwargs) -> AxProBypassClient:
    kwargs.setdefault("backoff_base", 0)
    return AxProBypassClient(panel, **kwargs)


def test_bypass_success_verified():
    """Command + verification via state re-read."""
    panel = MockAxPro(zones=[zone_payload(1)])
    client = make_client(panel)
    client.bypass(1)
    assert panel.zones[1]["bypassed"] is True
    assert panel.bypass_calls == [1]

    client.unbypass(1)
    assert panel.zones[1]["bypassed"] is False


def test_bypass_verify_mismatch_raises():
    """The panel accepted the command but did not apply it."""
    panel = MockAxPro(zones=[zone_payload(1)])

    original = panel.make_request

    def lying_make_request(endpoint, method, data=None, is_json=False):
        response = original(endpoint, method, data, is_json)
        if "control/bypass/" in endpoint:
            panel.zones[1]["bypassed"] = False  # panel silently ignored it
        return response

    panel.make_request = lying_make_request
    client = make_client(panel)
    with pytest.raises(BypassVerifyError):
        client.bypass(1)


def test_bypass_4xx_fails_fast():
    """Client errors are not retried."""
    panel = MockAxPro(zones=[zone_payload(1)])
    panel.fail_bypass_zones.add(1)
    client = make_client(panel, max_retries=3)
    with pytest.raises(BypassCommandError):
        client.bypass(1)
    assert panel.bypass_calls == [1]


def test_unsupported_endpoint_raises_dedicated_error():
    """404 means the firmware lacks the endpoint."""
    panel = MockAxPro(zones=[zone_payload(1)])

    def gone(endpoint, method, data=None, is_json=False):
        return MockResponse(status_code=404, text="not found")

    panel.make_request = gone
    client = make_client(panel)
    with pytest.raises(BypassUnsupportedError):
        client.bypass(1)


def test_transient_errors_retried_with_limit():
    """Retries on 5xx, then a clear error."""
    panel = MockAxPro(zones=[zone_payload(1)])
    attempts = []

    def flaky(endpoint, method, data=None, is_json=False):
        attempts.append(endpoint)
        return MockResponse(status_code=500, text="busy")

    panel.make_request = flaky
    client = make_client(panel, max_retries=3)
    with pytest.raises(BypassCommandError):
        client.bypass(1)
    assert len(attempts) == 3


def test_transient_error_then_success():
    """A transient failure recovers on retry."""
    panel = MockAxPro(zones=[zone_payload(1)])
    original = panel.make_request
    state = {"failed": False}

    def flaky_once(endpoint, method, data=None, is_json=False):
        if "control/bypass/" in endpoint and not state["failed"]:
            state["failed"] = True
            raise ConnectionError("blip")
        return original(endpoint, method, data, is_json)

    panel.make_request = flaky_once
    client = make_client(panel, max_retries=3)
    client.bypass(1)
    assert panel.zones[1]["bypassed"] is True


def test_detect_support():
    """Feature detection from the zone status payload."""
    with_bypass = {"ZoneList": [{"Zone": zone_payload(1)}]}
    without = {"ZoneList": [{"Zone": {"id": 1, "name": "x", "armed": False}}]}
    assert AxProBypassClient.detect_support(with_bypass) is True
    assert AxProBypassClient.detect_support(without) is False
    assert AxProBypassClient.detect_support(None) is False
    assert AxProBypassClient.detect_support({}) is False


def test_get_zone_raw():
    panel = MockAxPro(zones=[zone_payload(1), zone_payload(2)])
    client = make_client(panel)
    assert client.get_zone_raw(2)["id"] == 2
    assert client.get_zone_raw(99) is None
