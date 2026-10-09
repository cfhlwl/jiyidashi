from __future__ import annotations

from dataclasses import dataclass


@dataclass
class _AvailableProvider:
    available: bool = True


async def test_auth_capabilities_fail_closed_without_live_provider(client):
    response = await client.get("/v1/auth/capabilities")

    assert response.status_code == 200
    assert response.json() == {
        "email": "AVAILABLE",
        "sms_otp": "UNAVAILABLE",
        "phone_one_tap": "UNAVAILABLE",
        "wechat": "DISABLED",
    }


async def test_auth_capabilities_expose_only_provider_neutral_available_state(
    client, monkeypatch
):
    import app.api.auth as auth_api

    monkeypatch.setattr(auth_api.settings, "auth_sms_otp_provider", "aliyun")
    monkeypatch.setattr(auth_api, "get_sms_otp_provider", lambda: _AvailableProvider())
    monkeypatch.setattr(
        auth_api,
        "get_phone_one_tap_provider",
        lambda: _AvailableProvider(available=False),
    )

    response = await client.get("/v1/auth/capabilities")

    assert response.status_code == 200
    assert response.json() == {
        "email": "AVAILABLE",
        "sms_otp": "AVAILABLE",
        "phone_one_tap": "UNAVAILABLE",
        "wechat": "DISABLED",
    }
    assert "aliyun" not in response.text.lower()
    assert "credential" not in response.text.lower()


async def test_auth_capabilities_never_expose_fake_provider_as_available(
    client, monkeypatch
):
    import app.api.auth as auth_api

    monkeypatch.setattr(auth_api.settings, "auth_sms_otp_provider", "fake")
    monkeypatch.setattr(auth_api, "get_sms_otp_provider", lambda: _AvailableProvider())

    response = await client.get("/v1/auth/capabilities")

    assert response.status_code == 200
    assert response.json()["sms_otp"] == "UNAVAILABLE"


async def test_auth_capabilities_provider_factory_failure_is_fail_closed(
    client, monkeypatch
):
    import app.api.auth as auth_api

    def broken_provider():
        raise RuntimeError("provider configuration must not cross the API boundary")

    monkeypatch.setattr(auth_api, "get_sms_otp_provider", broken_provider)

    response = await client.get("/v1/auth/capabilities")

    assert response.status_code == 200
    assert response.json()["sms_otp"] == "UNAVAILABLE"
    assert "provider configuration" not in response.text
