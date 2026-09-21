"""Restricted media worker subprocess. Never accepts URLs or user paths."""

import json
import resource
import sys
import warnings
from pathlib import Path

from PIL import Image, ImageOps


def process(path: Path, max_pixels: int) -> dict:
    resource.setrlimit(resource.RLIMIT_CPU, (20, 20))
    resource.setrlimit(resource.RLIMIT_AS, (1536 * 1024**2, 1536 * 1024**2))
    resource.setrlimit(resource.RLIMIT_FSIZE, (100 * 1024**2, 100 * 1024**2))
    Image.MAX_IMAGE_PIXELS = max_pixels
    warnings.simplefilter("error", Image.DecompressionBombWarning)
    with Image.open(path, formats=["JPEG", "PNG", "WEBP"]) as source:
        media_format = source.format
        if media_format not in {"JPEG", "PNG", "WEBP"}:
            raise ValueError("unsupported image format")
        assert isinstance(media_format, str)
        if (
            getattr(source, "n_frames", 1) != 1
            or source.width * source.height > max_pixels
            or max(source.size) > 20000
        ):
            raise ValueError("image limits")
        source.verify()
    with Image.open(path, formats=["JPEG", "PNG", "WEBP"]) as source:
        image = ImageOps.exif_transpose(source)
        image.load()
        normalized = image.convert("RGB")
        width, height = normalized.size
        for kind, edge in (("display", 2048), ("thumbnail", 480)):
            derivative = normalized.copy()
            derivative.thumbnail((edge, edge), Image.Resampling.LANCZOS)
            derivative.save(
                path.with_suffix(f".{kind}.webp"),
                format="WEBP",
                quality=85,
                method=4,
                exif=b"",
                icc_profile=b"",
            )
        return {
            "media_type": {"JPEG": "image/jpeg", "PNG": "image/png", "WEBP": "image/webp"}[media_format],
            "extension": {"JPEG": "jpg", "PNG": "png", "WEBP": "webp"}[media_format],
            "width": width,
            "height": height,
        }


if __name__ == "__main__":
    try:
        result = process(Path(sys.argv[1]), int(sys.argv[2]))
        sys.stdout.write(json.dumps(result))
    except Exception:
        sys.stderr.write("image.invalid\n")
        sys.exit(2)
