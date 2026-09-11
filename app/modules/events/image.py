"""Normalize an uploaded event cover image to a single fixed rendition.

Every accepted image is center-cropped to 16:9, resized to 1200x675, and
re-encoded as a metadata-stripped JPEG. This keeps the Console card, the
Mobile App card, and the detail hero visually consistent regardless of
what was uploaded, and keeps stored objects small.
"""
from __future__ import annotations

import io

from PIL import Image, ImageOps, UnidentifiedImageError

from app.modules.events.exceptions import InvalidEventImageError

TARGET_WIDTH = 1200
TARGET_HEIGHT = 675
TARGET_RATIO = TARGET_WIDTH / TARGET_HEIGHT
JPEG_QUALITY = 85

ACCEPTED_CONTENT_TYPES = {"image/jpeg", "image/pjpeg", "image/png", "image/webp"}


def process_event_image(raw: bytes) -> bytes:
    try:
        with Image.open(io.BytesIO(raw)) as image:
            image = ImageOps.exif_transpose(image)
            image = image.convert("RGB")

            width, height = image.size
            if width <= 0 or height <= 0:
                raise InvalidEventImageError("The uploaded image is empty.")

            current_ratio = width / height
            if current_ratio > TARGET_RATIO:
                # Too wide — crop the sides.
                new_width = round(height * TARGET_RATIO)
                left = (width - new_width) // 2
                box = (left, 0, left + new_width, height)
            else:
                # Too tall — crop top and bottom.
                new_height = round(width / TARGET_RATIO)
                top = (height - new_height) // 2
                box = (0, top, width, top + new_height)

            image = image.crop(box).resize(
                (TARGET_WIDTH, TARGET_HEIGHT), Image.Resampling.LANCZOS
            )

            out = io.BytesIO()
            image.save(out, format="JPEG", quality=JPEG_QUALITY, optimize=True)
            return out.getvalue()
    except InvalidEventImageError:
        raise
    except (UnidentifiedImageError, OSError, ValueError) as exc:
        raise InvalidEventImageError(
            "The uploaded file could not be read as a JPEG, PNG, or WebP image."
        ) from exc
