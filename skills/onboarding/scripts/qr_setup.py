#!/usr/bin/env python3
"""Plan or install one private bulletin QR asset during onboarding."""

from __future__ import annotations

import argparse
import json
import shutil
import tempfile
from pathlib import Path
from urllib.parse import urlparse

from PIL import Image


KINDS = ("connect", "give")
RASTER_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp"}


def _destination_url(raw: str) -> str:
    value = raw.strip()
    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("QR destination must be a complete http or https URL")
    return value


def _source_image(raw: str | None) -> Path | None:
    if not raw:
        return None
    path = Path(raw).expanduser().resolve()
    if not path.is_file() or path.suffix.lower() not in RASTER_SUFFIXES:
        raise ValueError("Supplied QR image must be an existing PNG, JPG, or WEBP file")
    with Image.open(path) as image:
        image.verify()
    return path


def _write_brand(brand_path: Path, brand: dict) -> None:
    with tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", dir=brand_path.parent, delete=False
    ) as handle:
        json.dump(brand, handle, indent=2, ensure_ascii=False)
        handle.write("\n")
        temporary = Path(handle.name)
    temporary.replace(brand_path)


def install_qr(
    church_folder: str | Path,
    kind: str,
    url: str,
    *,
    image: str | None = None,
    apply: bool = False,
) -> dict:
    root = Path(church_folder).expanduser().resolve()
    brand_path = root / "brand.json"
    if not brand_path.is_file():
        raise ValueError("The church folder must contain brand.json")
    if kind not in KINDS:
        raise ValueError(f"QR kind must be one of: {', '.join(KINDS)}")
    destination = _destination_url(url)
    source = _source_image(image)
    suffix = source.suffix.lower() if source else ".png"
    relative = Path("brand") / "qr" / f"{kind}{suffix}"
    target = root / relative
    result = {
        "status": "planned" if not apply else "updated",
        "kind": kind,
        "url": destination,
        "image": relative.as_posix(),
        "action": "copy supplied image" if source else "create image from confirmed URL",
    }
    if not apply:
        return result

    target.parent.mkdir(parents=True, exist_ok=True)
    if source:
        shutil.copy2(source, target)
    else:
        try:
            import qrcode
        except ImportError as exc:
            raise RuntimeError(
                "QR generation needs the qrcode package; install requirements.txt first"
            ) from exc
        qr = qrcode.QRCode(error_correction=qrcode.constants.ERROR_CORRECT_M, border=4)
        qr.add_data(destination)
        qr.make(fit=True)
        qr.make_image(fill_color="black", back_color="white").save(target)

    brand = json.loads(brand_path.read_text(encoding="utf-8"))
    qr_config = brand.setdefault("qr", {})
    entry = qr_config.setdefault(kind, {})
    if not isinstance(entry, dict):
        entry = {}
        qr_config[kind] = entry
    entry["image"] = relative.as_posix()
    entry["url"] = destination
    _write_brand(brand_path, brand)
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--church-folder", required=True)
    parser.add_argument("--kind", required=True, choices=KINDS)
    parser.add_argument("--url", required=True)
    parser.add_argument("--image", help="Existing QR image to copy into the church folder")
    parser.add_argument("--apply", action="store_true", help="Install the asset after pastor read-back")
    args = parser.parse_args()
    try:
        result = install_qr(
            args.church_folder,
            args.kind,
            args.url,
            image=args.image,
            apply=args.apply,
        )
    except (OSError, ValueError, RuntimeError, json.JSONDecodeError) as exc:
        print(json.dumps({"status": "blocked", "message": str(exc)}))
        return 2
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
