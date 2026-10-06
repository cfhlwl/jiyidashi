from __future__ import annotations

from io import BytesIO

import pytest
from PIL import Image

from app.core.config import Settings
from app.services.ai_gateway import (
    AIGateway,
    AIImageInferenceRequest,
    AIPolicyError,
    DeterministicAIProvider,
)
from app.services.image_analysis import AnalysisImageError, build_analysis_image


def _jpeg(
    width: int,
    height: int,
    *,
    exif_gps: bool = False,
) -> bytes:
    image = Image.new("RGB", (width, height), (120, 80, 40))
    output = BytesIO()
    exif = Image.Exif()
    if exif_gps:
        exif[0x010E] = "private description"
        exif[0x8825] = {1: "N"}
    image.save(output, format="JPEG", quality=95, exif=exif)
    return output.getvalue()


@pytest.mark.parametrize("content_type,fmt", [
    ("image/jpeg", "JPEG"),
    ("image/png", "PNG"),
    ("image/webp", "WEBP"),
])
def test_supported_images_build_bounded_jpeg_derivative(content_type: str, fmt: str):
    image = Image.new("RGB", (2200, 1600), (20, 40, 60))
    source = BytesIO()
    image.save(source, format=fmt)

    derivative = build_analysis_image(
        source.getvalue(),
        declared_content_type=content_type,
        max_bytes=512 * 1024,
        max_dimension=1024,
        max_pixels=800_000,
    )

    assert derivative.content_type == "image/jpeg"
    assert len(derivative.image_bytes) <= 512 * 1024
    assert max(derivative.width, derivative.height) <= 1024
    assert derivative.width * derivative.height <= 800_000


def test_small_image_is_not_upscaled_and_metadata_is_stripped():
    source = _jpeg(320, 240, exif_gps=True)
    derivative = build_analysis_image(
        source,
        declared_content_type="image/jpeg",
        max_bytes=512 * 1024,
        max_dimension=2048,
        max_pixels=4_000_000,
    )

    assert (derivative.width, derivative.height) == (320, 240)
    with Image.open(BytesIO(derivative.image_bytes)) as decoded:
        assert decoded.getexif() == {}


def test_forged_mime_and_excessive_source_dimensions_fail_closed():
    png = BytesIO()
    Image.new("RGB", (32, 32)).save(png, format="PNG")
    with pytest.raises(AnalysisImageError, match="AI_IMAGE_TYPE_MISMATCH"):
        build_analysis_image(
            png.getvalue(),
            declared_content_type="image/jpeg",
            max_bytes=1024 * 1024,
            max_dimension=2048,
            max_pixels=4_000_000,
        )

    bomb = _jpeg(4096, 4096)
    with pytest.raises(AnalysisImageError, match="AI_IMAGE_SOURCE_DIMENSIONS_UNSAFE"):
        build_analysis_image(
            bomb,
            declared_content_type="image/jpeg",
            max_bytes=1024 * 1024,
            max_dimension=512,
            max_pixels=250_000,
        )





def test_exif_orientation_is_applied_deterministically():
    image = Image.new("RGB", (120, 240), (10, 20, 30))
    exif = Image.Exif()
    exif[0x0112] = 6
    source = BytesIO()
    image.save(source, format="JPEG", quality=90, exif=exif)

    derivative = build_analysis_image(
        source.getvalue(),
        declared_content_type="image/jpeg",
        max_bytes=512 * 1024,
        max_dimension=2048,
        max_pixels=4_000_000,
    )

    assert (derivative.width, derivative.height) == (240, 120)


def test_multiframe_and_unreducible_output_fail_closed():
    first = Image.new("RGB", (32, 32), (255, 0, 0))
    second = Image.new("RGB", (32, 32), (0, 255, 0))
    animated = BytesIO()
    first.save(
        animated,
        format="WEBP",
        save_all=True,
        append_images=[second],
        duration=100,
        loop=0,
    )
    with pytest.raises(AnalysisImageError, match="AI_IMAGE_MULTIFRAME_UNSUPPORTED"):
        build_analysis_image(
            animated.getvalue(),
            declared_content_type="image/webp",
            max_bytes=512 * 1024,
            max_dimension=2048,
            max_pixels=4_000_000,
        )

    with pytest.raises(AnalysisImageError, match="AI_IMAGE_DERIVATIVE_TOO_LARGE"):
        build_analysis_image(
            _jpeg(32, 32),
            declared_content_type="image/jpeg",
            max_bytes=1,
            max_dimension=2048,
            max_pixels=4_000_000,
        )


def test_gateway_independently_rejects_analysis_bytes_over_ceiling():
    settings = Settings(
        app_env="test",
        media_max_image_bytes=20 * 1024 * 1024,
        ai_image_max_bytes=128 * 1024,
        ai_image_max_dimension=2048,
        ai_image_max_pixels=4_000_000,
    )
    gateway = AIGateway(settings, DeterministicAIProvider())
    request = AIImageInferenceRequest(
        purpose="vision.observe",
        system_instruction="classify",
        input_text="image",
        image_bytes=b"x" * (128 * 1024 + 1),
        content_type="image/jpeg",
    )

    with pytest.raises(AIPolicyError, match="AI_IMAGE_TOO_LARGE"):
        gateway._validate_image_request(request)


def test_production_analysis_bytes_must_be_lower_than_original_media_limit():
    with pytest.raises(ValueError, match="AI_IMAGE_MAX_BYTES"):
        Settings(
            app_env="production",
            enable_dev_auth=False,
            jwt_secret="x" * 32,
            auth_rate_limit_enabled=True,
            api_rate_limit_enabled=True,
            auth_email_delivery_mode="smtp",
            auth_public_base_url="https://app.example.test/auth",
            auth_smtp_host="smtp.example.test",
            auth_smtp_from="accounts@example.test",
            security_alert_human_provider="feishu",
            security_alert_feishu_webhook_url=(
                "https://open.feishu.cn/open-apis/bot/v2/hook/test-not-live-token"
            ),
            security_alert_feishu_secret="test-sec017-signing-secret",
            media_max_image_bytes=2 * 1024 * 1024,
            ai_image_max_bytes=2 * 1024 * 1024,
        )
