from __future__ import annotations

from uuid import uuid4

import httpx
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec, rsa
from pydantic import ValidationError

from app.core.config import Settings
from app.notification_models import PushPlatform, PushProvider
from app.services.notification_provider import (
    APNsNotificationProvider,
    FCMNotificationProvider,
    HMSNotificationProvider,
    NotificationProviderRequest,
    provider_registration_allowed,
)


def _ec_private_key() -> str:
    key = ec.generate_private_key(ec.SECP256R1())
    return key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    ).decode("utf-8")


def _rsa_private_key() -> str:
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    return key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    ).decode("utf-8")


def _request(
    *,
    provider: PushProvider,
    token: str = "provider-token-123456789",
) -> NotificationProviderRequest:
    return NotificationProviderRequest(
        delivery_id=uuid4(),
        device_id=uuid4(),
        platform=(
            PushPlatform.IOS.value
            if provider == PushProvider.APNS
            else PushPlatform.ANDROID.value
        ),
        provider=provider.value,
        raw_token=token,
        title="通知标题",
        body="通知正文",
        payload={
            "version": 1,
            "destination": "HOME",
            "resource_id": None,
        },
    )


def _base_settings(**overrides) -> Settings:
    values = {
        "app_env": "development",
        "apns_enabled": False,
        "fcm_enabled": False,
        "hms_enabled": False,
    }
    values.update(overrides)
    return Settings(_env_file=None, **values)


def _production_settings(**overrides) -> Settings:
    values = {
        "app_env": "production",
        "jwt_secret": "prod-notification-test-secret-0123456789",
        "security_alert_human_provider": "feishu",
        "security_alert_feishu_webhook_url": (
            "https://open.feishu.cn/open-apis/bot/v2/hook/"
            "12345678-1234-1234-1234-123456789abc"
        ),
        "security_alert_feishu_secret": "prod-feishu-secret",
        "auth_email_delivery_mode": "smtp",
        "auth_public_base_url": "https://example.test",
        "auth_smtp_host": "smtp.example.test",
        "auth_smtp_from": "noreply@example.test",
        "enable_dev_auth": False,
        "push_app_identity_reviewed": True,
        "push_ios_bundle_id": "com.jiyidays",
        "push_android_application_id": "com.jiyidays",
    }
    values.update(overrides)
    return Settings(_env_file=None, **values)


def test_apns_success_uses_http2_shape_and_cached_provider_jwt():
    key = _ec_private_key()
    authorizations: list[str] = []
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        authorizations.append(request.headers["authorization"])
        return httpx.Response(200, request=request)

    settings = _base_settings(
        apns_enabled=True,
        apns_team_id="TEAM123456",
        apns_key_id="KEY1234567",
        apns_private_key=key,
        apns_topic="com.jiyidays",
        apns_environment="sandbox",
    )
    client = httpx.Client(transport=httpx.MockTransport(handler))
    provider = APNsNotificationProvider(settings, client=client, clock=lambda: 1_700_000_000.0)

    first = provider.deliver(_request(provider=PushProvider.APNS))
    second = provider.deliver(_request(provider=PushProvider.APNS))

    assert first.accepted is True
    assert second.accepted is True
    assert len(requests) == 2
    assert requests[0].url.host == "api.sandbox.push.apple.com"
    assert requests[0].headers["apns-topic"] == "com.jiyidays"
    assert requests[0].headers["apns-push-type"] == "alert"
    assert authorizations[0] == authorizations[1]
    rendered = requests[0].content.decode("utf-8")
    assert "provider-token" not in rendered
    assert '"destination":"HOME"' in rendered


@pytest.mark.parametrize(
    ("status_code", "reason", "retryable", "invalid_token"),
    [
        (410, "Unregistered", False, True),
        (400, "BadDeviceToken", False, True),
        (400, "BadTopic", False, False),
        (500, "InternalServerError", True, False),
    ],
)
def test_apns_response_classification(
    status_code: int,
    reason: str,
    retryable: bool,
    invalid_token: bool,
):
    key = _ec_private_key()

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            status_code,
            request=request,
            json={"reason": reason},
            headers={"retry-after": "17"},
        )

    settings = _base_settings(
        apns_enabled=True,
        apns_team_id="TEAM123456",
        apns_key_id="KEY1234567",
        apns_private_key=key,
        apns_topic="com.jiyidays",
    )
    provider = APNsNotificationProvider(
        settings,
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    result = provider.deliver(_request(provider=PushProvider.APNS))

    assert result.accepted is False
    assert result.retryable is retryable
    assert result.invalid_token is invalid_token
    if retryable:
        assert result.retry_after_seconds == 17


def test_apns_expired_provider_token_clears_cached_jwt_and_retries_with_fresh_authorization():
    key = _ec_private_key()
    now = [1_700_000_000.0]
    authorizations: list[str] = []
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        authorizations.append(request.headers["authorization"])
        if calls == 1:
            return httpx.Response(
                403,
                request=request,
                json={"reason": "ExpiredProviderToken"},
            )
        return httpx.Response(200, request=request)

    settings = _base_settings(
        apns_enabled=True,
        apns_team_id="TEAM123456",
        apns_key_id="KEY1234567",
        apns_private_key=key,
        apns_topic="com.jiyidays",
        apns_environment="sandbox",
    )
    provider = APNsNotificationProvider(
        settings,
        client=httpx.Client(transport=httpx.MockTransport(handler)),
        clock=lambda: now[0],
    )

    first = provider.deliver(_request(provider=PushProvider.APNS))
    assert first.accepted is False
    assert first.retryable is True
    assert first.error_code == "APNS_EXPIRED_PROVIDER_TOKEN"

    now[0] += 1
    second = provider.deliver(_request(provider=PushProvider.APNS))
    assert second.accepted is True
    assert calls == 2
    assert authorizations[0] != authorizations[1]


def test_apns_429_is_retryable_and_bounded():
    key = _ec_private_key()

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            429,
            request=request,
            json={"reason": "TooManyRequests"},
            headers={"retry-after": "999999"},
        )

    settings = _base_settings(
        apns_enabled=True,
        apns_team_id="TEAM123456",
        apns_key_id="KEY1234567",
        apns_private_key=key,
        apns_topic="com.jiyidays",
    )
    result = APNsNotificationProvider(
        settings,
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    ).deliver(_request(provider=PushProvider.APNS))

    assert result.retryable is True
    assert result.retry_after_seconds == 900


def test_fcm_success_and_unregistered_classification():
    key = _rsa_private_key()
    send_count = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal send_count
        if request.url.host == "oauth2.googleapis.com":
            return httpx.Response(
                200,
                request=request,
                json={"access_token": "oauth-access", "expires_in": 3600},
            )
        send_count += 1
        if send_count == 1:
            return httpx.Response(
                200,
                request=request,
                json={"name": "projects/p/messages/1"},
            )
        return httpx.Response(
            404,
            request=request,
            json={
                "error": {
                    "status": "NOT_FOUND",
                    "details": [
                        {
                            "@type": "type.googleapis.com/google.firebase.fcm.v1.FcmError",
                            "errorCode": "UNREGISTERED",
                        }
                    ],
                }
            },
        )

    settings = _base_settings(
        fcm_enabled=True,
        fcm_project_id="project-id",
        fcm_client_email="push@example.iam.gserviceaccount.com",
        fcm_private_key=key,
    )
    provider = FCMNotificationProvider(
        settings,
        client=httpx.Client(transport=httpx.MockTransport(handler)),
        clock=lambda: 1_700_000_000.0,
    )

    accepted = provider.deliver(_request(provider=PushProvider.FCM))
    invalid = provider.deliver(_request(provider=PushProvider.FCM))

    assert accepted.accepted is True
    assert invalid.accepted is False
    assert invalid.retryable is False
    assert invalid.invalid_token is True
    assert invalid.error_code == "FCM_UNREGISTERED"


def test_fcm_transient_failure_is_retryable():
    key = _rsa_private_key()

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "oauth2.googleapis.com":
            return httpx.Response(
                200,
                request=request,
                json={"access_token": "oauth-access", "expires_in": 3600},
            )
        return httpx.Response(
            503,
            request=request,
            json={"error": {"status": "UNAVAILABLE"}},
            headers={"retry-after": "20"},
        )

    settings = _base_settings(
        fcm_enabled=True,
        fcm_project_id="project-id",
        fcm_client_email="push@example.iam.gserviceaccount.com",
        fcm_private_key=key,
    )
    result = FCMNotificationProvider(
        settings,
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    ).deliver(_request(provider=PushProvider.FCM))

    assert result.retryable is True
    assert result.invalid_token is False
    assert result.retry_after_seconds == 20


def test_hms_success_invalid_token_and_transient_classification():
    responses = iter(
        [
            ("80000000", 200),
            ("80300007", 200),
            ("81000001", 200),
        ]
    )

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "oauth-login.cloud.huawei.com":
            return httpx.Response(
                200,
                request=request,
                json={"access_token": "hms-access", "expires_in": 3600},
            )
        code, status = next(responses)
        return httpx.Response(
            status,
            request=request,
            json={"code": code, "msg": "bounded-test"},
        )

    settings = _base_settings(
        hms_enabled=True,
        hms_app_id="123456789",
        hms_client_id="123456789",
        hms_client_secret="hms-secret",
    )
    provider = HMSNotificationProvider(
        settings,
        client=httpx.Client(transport=httpx.MockTransport(handler)),
        clock=lambda: 1_700_000_000.0,
    )

    accepted = provider.deliver(_request(provider=PushProvider.HMS))
    invalid = provider.deliver(_request(provider=PushProvider.HMS))
    transient = provider.deliver(_request(provider=PushProvider.HMS))

    assert accepted.accepted is True
    assert invalid.invalid_token is True
    assert invalid.retryable is False
    assert transient.retryable is True
    assert transient.invalid_token is False


def test_production_provider_registration_requires_reviewed_identity_and_configuration():
    unreviewed = Settings.model_construct(
        app_env="production",
        push_app_identity_reviewed=False,
        apns_enabled=True,
        apns_environment="production",
        apns_topic="com.jiyidays",
        push_ios_bundle_id="com.jiyidays",
        fcm_enabled=False,
        hms_enabled=False,
    )
    assert provider_registration_allowed(
        platform=PushPlatform.IOS.value,
        provider=PushProvider.APNS.value,
        settings=unreviewed,
    ) is False

    reviewed = Settings.model_construct(
        app_env="production",
        push_app_identity_reviewed=True,
        apns_enabled=True,
        apns_environment="production",
        apns_topic="com.jiyidays",
        push_ios_bundle_id="com.jiyidays",
        push_android_application_id="com.jiyidays",
        fcm_enabled=True,
        hms_enabled=True,
    )
    assert provider_registration_allowed(
        platform=PushPlatform.IOS.value,
        provider=PushProvider.APNS.value,
        settings=reviewed,
    ) is True
    assert provider_registration_allowed(
        platform=PushPlatform.ANDROID.value,
        provider=PushProvider.FCM.value,
        settings=reviewed,
    ) is True
    assert provider_registration_allowed(
        platform=PushPlatform.ANDROID.value,
        provider=PushProvider.HMS.value,
        settings=reviewed,
    ) is True
    assert provider_registration_allowed(
        platform=PushPlatform.ANDROID.value,
        provider=PushProvider.TEST.value,
        settings=reviewed,
    ) is False


def test_production_apns_requires_identity_review_and_topic_match():
    key = _ec_private_key()
    with pytest.raises(ValidationError, match="PUSH_APP_IDENTITY_REVIEWED"):
        _production_settings(
            push_app_identity_reviewed=False,
            apns_enabled=True,
            apns_team_id="TEAM123456",
            apns_key_id="KEY1234567",
            apns_private_key=key,
            apns_topic="com.jiyidays",
            apns_environment="production",
        )

    with pytest.raises(ValidationError, match="APNS_TOPIC"):
        _production_settings(
            apns_enabled=True,
            apns_team_id="TEAM123456",
            apns_key_id="KEY1234567",
            apns_private_key=key,
            apns_topic="com.other.app",
            apns_environment="production",
        )


def test_production_push_rejects_noncanonical_app_identity_even_when_reviewed():
    key = _ec_private_key()
    with pytest.raises(ValidationError, match="PUSH_IOS_BUNDLE_ID"):
        _production_settings(
            apns_enabled=True,
            apns_team_id="TEAM123456",
            apns_key_id="KEY1234567",
            apns_private_key=key,
            apns_topic="com.wrong.app",
            push_ios_bundle_id="com.wrong.app",
            push_android_application_id="com.wrong.app",
            apns_environment="production",
        )

    reviewed_wrong = Settings.model_construct(
        app_env="production",
        push_app_identity_reviewed=True,
        apns_enabled=True,
        apns_environment="production",
        apns_topic="com.wrong.app",
        push_ios_bundle_id="com.wrong.app",
        push_android_application_id="com.wrong.app",
        fcm_enabled=True,
        hms_enabled=True,
    )
    assert provider_registration_allowed(
        platform=PushPlatform.IOS.value,
        provider=PushProvider.APNS.value,
        settings=reviewed_wrong,
    ) is False
    assert provider_registration_allowed(
        platform=PushPlatform.ANDROID.value,
        provider=PushProvider.FCM.value,
        settings=reviewed_wrong,
    ) is False


def test_provider_request_repr_redacts_raw_token():
    raw = "super-secret-provider-token-123456"
    request = _request(provider=PushProvider.APNS, token=raw)
    assert raw not in repr(request)
