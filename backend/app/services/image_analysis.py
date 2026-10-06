from __future__ import annotations

from dataclasses import dataclass
from io import BytesIO

from PIL import Image, ImageOps, UnidentifiedImageError

_SUPPORTED_SOURCE_FORMATS = {
    "image/jpeg": "JPEG",
    "image/png": "PNG",
    "image/webp": "WEBP",
}
_DERIVATIVE_CONTENT_TYPE = "image/jpeg"


class AnalysisImageError(RuntimeError):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class AnalysisImage:
    image_bytes: bytes
    content_type: str
    width: int
    height: int


def _target_size(
    width: int,
    height: int,
    *,
    max_dimension: int,
    max_pixels: int,
) -> tuple[int, int]:
    if width <= 0 or height <= 0:
        raise AnalysisImageError("AI_IMAGE_DECODE_INVALID")

    scale = min(1.0, max_dimension / max(width, height))
    if width * height * scale * scale > max_pixels:
        scale = min(scale, (max_pixels / (width * height)) ** 0.5)
    if scale >= 1.0:
        return width, height
    return max(1, int(width * scale)), max(1, int(height * scale))


def build_analysis_image(
    source: bytes,
    *,
    declared_content_type: str,
    max_bytes: int,
    max_dimension: int,
    max_pixels: int,
) -> AnalysisImage:
    if not source:
        raise AnalysisImageError("AI_IMAGE_EMPTY")

    expected_format = _SUPPORTED_SOURCE_FORMATS.get(declared_content_type)
    if expected_format is None:
        raise AnalysisImageError("AI_IMAGE_TYPE_UNSUPPORTED")

    try:
        with Image.open(BytesIO(source)) as opened:
            if opened.format != expected_format:
                raise AnalysisImageError("AI_IMAGE_TYPE_MISMATCH")
            if getattr(opened, "n_frames", 1) != 1:
                raise AnalysisImageError("AI_IMAGE_MULTIFRAME_UNSUPPORTED")

            width, height = opened.size
            source_pixels = width * height
            # Header-level bomb guard before full decode. The multiplier permits normal
            # large originals to be reduced while rejecting pathological dimensions.
            source_pixel_guard = max(max_pixels * 4, max_dimension * max_dimension * 4)
            if source_pixels <= 0 or source_pixels > source_pixel_guard:
                raise AnalysisImageError("AI_IMAGE_SOURCE_DIMENSIONS_UNSAFE")

            opened.load()
            image = ImageOps.exif_transpose(opened)
            target = _target_size(
                image.width,
                image.height,
                max_dimension=max_dimension,
                max_pixels=max_pixels,
            )
            if image.size != target:
                image.thumbnail(target, Image.Resampling.LANCZOS)

            if image.mode not in {"RGB", "L"}:
                if "A" in image.getbands():
                    rgba = image.convert("RGBA")
                    background = Image.new("RGB", rgba.size, "white")
                    background.paste(rgba, mask=rgba.getchannel("A"))
                    image = background
                else:
                    image = image.convert("RGB")
            elif image.mode == "L":
                image = image.convert("RGB")

            current = image
            for shrink_round in range(10):
                for quality in (85, 75, 65, 55, 45):
                    output = BytesIO()
                    current.save(
                        output,
                        format="JPEG",
                        quality=quality,
                        optimize=True,
                        progressive=False,
                    )
                    derivative = output.getvalue()
                    if len(derivative) <= max_bytes:
                        out_width, out_height = current.size
                        if (
                            max(out_width, out_height) > max_dimension
                            or out_width * out_height > max_pixels
                        ):
                            raise AnalysisImageError("AI_IMAGE_DERIVATIVE_POLICY_BREACH")
                        return AnalysisImage(
                            image_bytes=derivative,
                            content_type=_DERIVATIVE_CONTENT_TYPE,
                            width=out_width,
                            height=out_height,
                        )
                if shrink_round == 9 or current.width == 1 or current.height == 1:
                    break
                next_size = (
                    max(1, int(current.width * 0.8)),
                    max(1, int(current.height * 0.8)),
                )
                current = current.resize(next_size, Image.Resampling.LANCZOS)

    except AnalysisImageError:
        raise
    except (UnidentifiedImageError, OSError, ValueError) as exc:
        raise AnalysisImageError("AI_IMAGE_DECODE_INVALID") from exc
    except Image.DecompressionBombError as exc:
        raise AnalysisImageError("AI_IMAGE_SOURCE_DIMENSIONS_UNSAFE") from exc

    raise AnalysisImageError("AI_IMAGE_DERIVATIVE_TOO_LARGE")
