"""The image studio: image-model rounds, precise edits, and vectorizing the chosen mark.

Language models cannot draw a church mark. Hand-written SVG and agent
"makers" drawing from prose produce generic clip art. What works is a raster
image model given a full editorial brief per concept, the pastor reacting
between rounds, precise edits of the chosen image for variations, and then a
vectorizer that turns the chosen raster into SVG. This module runs those
steps and keeps the record:

- ``draw`` sends a brief (and optional reference images) to an image model.
- ``edit`` asks for a precise change to one chosen image.
- ``import_images`` registers images a host made itself, with no network.
- ``vectorize`` turns the chosen raster into one even-odd path painted with
  currentColor, then runs the mark checks on it.
- ``keys_status`` and ``keys_set`` manage the per-computer service keys.

Every image is flattened onto white before anyone reviews it, laid out on
the round's contact sheet by ``explore``, and receipted with the provider,
the model, the brief's hash and path, input and output hashes, and the cost
when the service reports one.

Providers sit behind one small seam: a class per service with ``draw``,
``edit``, and ``vectorize``. HTTP uses only the standard library.
"""

from __future__ import annotations

import base64
import hashlib
import importlib.util
import io
import json
import math
import os
import re
import stat
import sys
import urllib.error
import urllib.parse
import urllib.request
import uuid
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field as dataclass_field
from pathlib import Path
from typing import Any, Callable

from . import (
    CHECKS_DIR, EXPLORATIONS_DIR, SCRATCH_DIR, SKILL_DIR, STAGING_DIR, WorkflowFailure,
    _brand_setup, _church_root, _existing, _exploration_open, _failure, _load_state,
    _receipt, _recorded, _relative, _sha256, _write_text, explore, survival,
)

IMAGES_DIR = SCRATCH_DIR / "images"
VECTOR_DIR = SCRATCH_DIR / "vectorize"
MAX_IMAGES = 8
DEFAULT_SIZE = "1024x1024"
REQUEST_TIMEOUT = 300
IMPORT_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp"}
KEY_FILE_NAME = "image-keys.json"

# Model names change; each can be set per computer without a code change.
DEFAULT_MODELS = {"openai": "gpt-image-1", "recraft": "recraftv3", "gemini": "gemini-2.5-flash-image"}
MODEL_ENVIRONMENT = {"openai": "HANDBUILT_OPENAI_IMAGE_MODEL", "recraft": "HANDBUILT_RECRAFT_IMAGE_MODEL",
                     "gemini": "HANDBUILT_GEMINI_IMAGE_MODEL"}
KEY_ENVIRONMENT = {"openai": "OPENAI_API_KEY", "recraft": "RECRAFT_API_KEY", "gemini": "GEMINI_API_KEY"}
PROVIDER_NAMES = {"openai": "OpenAI", "recraft": "Recraft", "gemini": "Gemini"}
OPENAI_BASE = "https://api.openai.com/v1"
GEMINI_BASE = "https://generativelanguage.googleapis.com/v1beta"
RECRAFT_BASE = "https://external.api.recraft.ai/v1"
RECRAFT_PROMPT_LIMIT = 1000


# ---------------------------------------------------------------- keys, kept on this computer only

def _runtime_module():
    path = SKILL_DIR.parents[1] / "tools" / "handbuilt_runtime.py"
    name = "handbuilt_runtime_for_images"
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    # Dataclasses look their module up while the module is still loading.
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def support_directory() -> Path:
    """The per-computer Handbuilt support folder: the parent of the runtime folder.

    On macOS this is ~/Library/Application Support/Handbuilt Church Labs/.
    """
    return _runtime_module().default_runtime_root().parent


def key_file() -> Path:
    return support_directory() / KEY_FILE_NAME


def _check_provider_name(provider: str) -> str:
    if provider not in KEY_ENVIRONMENT:
        raise WorkflowFailure("unknown_image_service", f"Unknown image service: {provider}. Choose one of: " + ", ".join(sorted(KEY_ENVIRONMENT)), field="provider")
    return provider


def _stored_keys() -> dict[str, str]:
    path = key_file()
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise WorkflowFailure("unreadable_key_file", f"The image service key file on this computer could not be read ({path}). Set the key again with keys set.") from exc
    return {k: v for k, v in data.items() if isinstance(v, str) and v} if isinstance(data, dict) else {}


def _key_source(provider: str) -> str | None:
    if os.environ.get(KEY_ENVIRONMENT[provider], "").strip():
        return "environment"
    if _stored_keys().get(provider):
        return "key_file"
    return None


def service_key(provider: str) -> str:
    """The key for a service: the environment first, then this computer's key file."""
    _check_provider_name(provider)
    value = os.environ.get(KEY_ENVIRONMENT[provider], "").strip() or _stored_keys().get(provider, "")
    if not value:
        raise WorkflowFailure(
            "image_key_missing",
            f"{PROVIDER_NAMES[provider]} is not set up on this computer yet, so no image was made and nothing was charged. "
            f"Whoever looks after Handbuilt here can add the key with: handbuilt.py build-my-brand keys set --provider {provider} "
            "(the key is read from the keyboard and kept on this computer, never in the church folder). "
            "Or make the images in the host's own image tool and register them with import-images.",
            field="provider")
    return value


def _outside_church(path: Path, church_folder: str | Path | None) -> None:
    if not church_folder:
        return
    church = Path(church_folder).expanduser().resolve()
    target = path.expanduser().resolve()
    if target == church or church in target.parents:
        raise WorkflowFailure("key_inside_church_folder", "Service keys are never kept in the church folder. Point the Handbuilt support folder somewhere outside it.")


def keys_status(church_folder: str | Path | None = None) -> dict[str, Any]:
    """Which services are set up on this computer. Never prints a key, or any part of one."""
    try:
        path = key_file()
        _outside_church(path, church_folder)
        providers = {}
        for name in sorted(KEY_ENVIRONMENT):
            source = _key_source(name)
            providers[name] = {"configured": bool(source), "source": source, "environment_variable": KEY_ENVIRONMENT[name],
                               "model": _model_for(name, None)}
        return {"status": "ok", "providers": providers, "key_file": str(path), "key_file_exists": path.is_file(),
                "handbuilt": "The hosted Handbuilt image service is not available yet.",
                "next_action": "Add a missing key with keys set --provider <name>; the key is read from standard input."}
    except Exception as exc:  # noqa: BLE001
        return _failure(exc)


def keys_set(provider: str, value: str, church_folder: str | Path | None = None) -> dict[str, Any]:
    """Save one service key in this computer's key file, readable only by this user (0600)."""
    try:
        _check_provider_name(provider)
        value = (value or "").strip()
        if not value or any(ch.isspace() for ch in value):
            raise WorkflowFailure("invalid_key", "Paste the key on one line, with nothing else", field="key")
        path = key_file()
        _outside_church(path, church_folder)
        keys = _stored_keys()
        keys[provider] = value
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}")
        descriptor = os.open(str(temporary), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                handle.write(json.dumps(keys, indent=2) + "\n")
            os.chmod(temporary, 0o600)
            os.replace(temporary, path)
        finally:
            if temporary.exists():
                temporary.unlink()
        os.chmod(path, 0o600)
        mode = stat.S_IMODE(path.stat().st_mode)
        return {"status": "saved", "provider": provider, "key_file": str(path), "permissions": oct(mode),
                "next_action": "Run keys status to confirm. The key is never printed."}
    except Exception as exc:  # noqa: BLE001
        return _failure(exc)


# ---------------------------------------------------------------- the provider seam

@dataclass
class Drawn:
    """What a service sent back for one request."""

    images: list[bytes]
    model: str | None
    cost: Any = None
    usage: Any = None


@dataclass
class Vectorized:
    svg: str
    model: str | None = None
    cost: Any = None
    usage: Any = None


@dataclass
class _Part:
    name: str
    value: bytes
    filename: str | None = None
    content_type: str = "application/octet-stream"


def _multipart(fields: list[_Part]) -> tuple[bytes, str]:
    boundary = f"handbuilt-{uuid.uuid4().hex}"
    body = io.BytesIO()
    for part in fields:
        body.write(f"--{boundary}\r\n".encode())
        disposition = f'form-data; name="{part.name}"'
        if part.filename:
            disposition += f'; filename="{part.filename}"'
        body.write(f"Content-Disposition: {disposition}\r\n".encode())
        if part.filename:
            body.write(f"Content-Type: {part.content_type}\r\n".encode())
        body.write(b"\r\n")
        body.write(part.value)
        body.write(b"\r\n")
    body.write(f"--{boundary}--\r\n".encode())
    return body.getvalue(), f"multipart/form-data; boundary={boundary}"


def _http(service: str, url: str, *, key: str, payload: dict[str, Any] | None = None, parts: list[_Part] | None = None,
          key_header: str = "Authorization") -> dict[str, Any]:
    if parts is not None:
        data, content_type = _multipart(parts)
    else:
        data, content_type = json.dumps(payload or {}).encode("utf-8"), "application/json"
    request = urllib.request.Request(url, data=data, method="POST", headers={
        key_header: f"Bearer {key}" if key_header == "Authorization" else key,
        "Content-Type": content_type, "Accept": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=REQUEST_TIMEOUT) as response:  # noqa: S310 (fixed https endpoints)
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        try:
            detail = json.loads(exc.read().decode("utf-8", "replace"))
            message = (detail.get("error") or {}).get("message") if isinstance(detail.get("error"), dict) else detail.get("message") or detail.get("error")
        except (ValueError, AttributeError):
            message = None
        hint = " The key may be wrong or expired; set it again with keys set." if exc.code in {401, 403} else ""
        raise WorkflowFailure("image_service_failed", f"{PROVIDER_NAMES.get(service, service)} turned the request down (HTTP {exc.code}). {str(message or '')[:300]}{hint}".strip()) from None
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise WorkflowFailure("image_service_unreachable", f"Could not reach {PROVIDER_NAMES.get(service, service)} ({getattr(exc, 'reason', exc)}). Check the internet connection and try again.") from None
    except ValueError as exc:
        raise WorkflowFailure("image_service_failed", f"{PROVIDER_NAMES.get(service, service)} sent back something that was not JSON") from exc


def _fetch(url: str) -> bytes:
    if not url.startswith("https://"):
        raise WorkflowFailure("image_service_failed", "The image service returned a link that is not https")
    try:
        with urllib.request.urlopen(url, timeout=REQUEST_TIMEOUT) as response:  # noqa: S310
            return response.read()
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise WorkflowFailure("image_service_unreachable", f"Could not download the result ({getattr(exc, 'reason', exc)})") from None


def _decode_images(service: str, response: dict[str, Any]) -> list[bytes]:
    images = []
    for item in response.get("data") or []:
        if isinstance(item, dict) and item.get("b64_json"):
            images.append(base64.b64decode(item["b64_json"]))
        elif isinstance(item, dict) and item.get("url"):
            images.append(_fetch(item["url"]))
    if not images:
        raise WorkflowFailure("image_service_failed", f"{PROVIDER_NAMES[service]} returned no images")
    return images


def _reported_cost(response: dict[str, Any]) -> Any:
    """Only a cost the service itself reports. Prices are never estimated here."""
    for key in ("cost", "credits", "cost_usd"):
        if response.get(key) is not None:
            return response[key]
    return None


def _model_for(provider: str, model: str | None) -> str | None:
    if model:
        return model
    if provider in MODEL_ENVIRONMENT:
        return os.environ.get(MODEL_ENVIRONMENT[provider], "").strip() or DEFAULT_MODELS[provider]
    return None


class OpenAIImages:
    """OpenAI images: generations for a brief, edits for references and precise changes."""

    name = "openai"

    def __init__(self, model: str | None = None, *, key: Callable[[str], str] = service_key):
        self.model = _model_for(self.name, model)
        self._key = key

    def draw(self, prompt: str, *, n: int, references: list[bytes], size: str) -> Drawn:
        key = self._key(self.name)
        if references:
            # Reference images go through the edits endpoint, which accepts several.
            return self._edit(key, references, prompt, n=n, size=size)
        response = _http(self.name, f"{OPENAI_BASE}/images/generations", key=key,
                         payload={"model": self.model, "prompt": prompt, "n": n, "size": size})
        return Drawn(_decode_images(self.name, response), self.model, _reported_cost(response), response.get("usage"))

    def edit(self, image: bytes, instruction: str, *, n: int, size: str) -> Drawn:
        return self._edit(self._key(self.name), [image], instruction, n=n, size=size)

    def _edit(self, key: str, images: list[bytes], prompt: str, *, n: int, size: str) -> Drawn:
        field_name = "image" if len(images) == 1 else "image[]"
        parts = [_Part("model", str(self.model).encode()), _Part("prompt", prompt.encode("utf-8")),
                 _Part("n", str(n).encode()), _Part("size", size.encode())]
        parts += [_Part(field_name, data, f"input-{index + 1}.png", "image/png") for index, data in enumerate(images)]
        response = _http(self.name, f"{OPENAI_BASE}/images/edits", key=key, parts=parts)
        return Drawn(_decode_images(self.name, response), self.model, _reported_cost(response), response.get("usage"))

    def vectorize(self, image: bytes) -> Vectorized:
        raise WorkflowFailure("not_supported", "OpenAI does not vectorize; use Recraft for vectorize", field="provider")


class RecraftImages:
    """Recraft: image generation from a short brief, and vectorizing a chosen raster."""

    name = "recraft"

    def __init__(self, model: str | None = None, *, key: Callable[[str], str] = service_key):
        self.model = _model_for(self.name, model)
        self._key = key

    def draw(self, prompt: str, *, n: int, references: list[bytes], size: str) -> Drawn:
        if references:
            raise WorkflowFailure("not_supported", "Recraft drawing here does not take reference images; use OpenAI for a round with references", field="reference")
        if len(prompt) > RECRAFT_PROMPT_LIMIT:
            raise WorkflowFailure("brief_too_long", f"Recraft accepts briefs up to {RECRAFT_PROMPT_LIMIT} characters and this one is {len(prompt)}. Shorten it or draw with OpenAI.", field="brief_file")
        key = self._key(self.name)
        response = _http(self.name, f"{RECRAFT_BASE}/images/generations", key=key,
                         payload={"prompt": prompt, "n": n, "model": self.model, "size": size, "response_format": "b64_json"})
        return Drawn(_decode_images(self.name, response), self.model, _reported_cost(response), response.get("usage"))

    def edit(self, image: bytes, instruction: str, *, n: int, size: str) -> Drawn:
        raise WorkflowFailure("not_supported", "Precise edits use OpenAI", field="provider")

    def vectorize(self, image: bytes) -> Vectorized:
        key = self._key(self.name)
        response = _http(self.name, f"{RECRAFT_BASE}/images/vectorize", key=key,
                         parts=[_Part("file", image, "source.png", "image/png"), _Part("response_format", b"b64_json")])
        item = response.get("image") if isinstance(response.get("image"), dict) else ((response.get("data") or [None])[0] or {})
        if item.get("b64_json"):
            svg = base64.b64decode(item["b64_json"]).decode("utf-8")
        elif item.get("url"):
            svg = _fetch(item["url"]).decode("utf-8")
        else:
            raise WorkflowFailure("image_service_failed", "Recraft returned no vector")
        return Vectorized(svg, None, _reported_cost(response), response.get("usage"))


class GeminiImages:
    """Gemini's image model: drawing from a brief and editing a chosen image.

    It returns one image per request, so several images are several requests.
    """

    name = "gemini"

    def __init__(self, model: str | None = None, *, key: Callable[[str], str] = service_key):
        self.model = _model_for(self.name, model)
        self._key = key

    def draw(self, prompt: str, *, n: int, references: list[bytes], size: str) -> Drawn:
        return self._generate(prompt, references, n=n, size=size)

    def edit(self, image: bytes, instruction: str, *, n: int, size: str) -> Drawn:
        return self._generate(instruction, [image], n=n, size=size)

    def _generate(self, prompt: str, images: list[bytes], *, n: int, size: str) -> Drawn:
        key = self._key(self.name)
        parts: list[dict[str, Any]] = [{"text": prompt}]
        parts += [{"inline_data": {"mime_type": "image/png", "data": base64.b64encode(data).decode("ascii")}} for data in images]
        payload = {"contents": [{"parts": parts}],
                   "generationConfig": {"responseModalities": ["TEXT", "IMAGE"], "imageConfig": {"aspectRatio": _aspect_ratio(size)}}}
        url = f"{GEMINI_BASE}/models/{urllib.parse.quote(str(self.model), safe='.-')}:generateContent"
        drawn, usage = [], []
        for _ in range(n):
            response = _http(self.name, url, key=key, payload=payload, key_header="x-goog-api-key")
            drawn += _gemini_images(response)
            usage.append(response.get("usageMetadata"))
        return Drawn(drawn, self.model, None, usage)

    def vectorize(self, image: bytes) -> Vectorized:
        raise WorkflowFailure("not_supported", "Gemini does not vectorize; use Recraft for vectorize", field="provider")


def _aspect_ratio(size: str) -> str:
    try:
        width, height = (int(part) for part in str(size).lower().split("x"))
    except ValueError:
        raise WorkflowFailure("invalid_size", f"Size must look like 1024x1024, not {size}", field="size") from None
    common = math.gcd(width, height) or 1
    return f"{width // common}:{height // common}"


def _gemini_images(response: dict[str, Any]) -> list[bytes]:
    images = []
    for candidate in response.get("candidates") or []:
        for part in ((candidate or {}).get("content") or {}).get("parts") or []:
            inline = (part or {}).get("inlineData") or (part or {}).get("inline_data")
            if isinstance(inline, dict) and inline.get("data"):
                images.append(base64.b64decode(inline["data"]))
    if not images:
        reason = ((response.get("promptFeedback") or {}).get("blockReason")
                  or next((c.get("finishReason") for c in response.get("candidates") or [] if isinstance(c, dict)), None))
        raise WorkflowFailure("image_service_failed", "Gemini returned no image" + (f" ({reason})" if reason else ""))
    return images


class HandbuiltImages:
    """Placeholder for a future hosted Handbuilt image service.

    When it exists it will take the same editorial brief and return the same
    shapes as the other providers, with the church's key held by Handbuilt
    instead of on this computer. No network call is made here until then.
    """

    name = "handbuilt"

    def __init__(self, model: str | None = None, **_ignored: Any):
        self.model = model

    def _unavailable(self, *_args: Any, **_kwargs: Any):
        raise WorkflowFailure("not_available_yet", "The hosted Handbuilt image service is not available yet. Use openai, gemini or recraft, or import images the host made.", field="provider")

    draw = edit = vectorize = _unavailable


PROVIDERS: dict[str, Callable[..., Any]] = {"openai": OpenAIImages, "recraft": RecraftImages, "gemini": GeminiImages,
                                            "handbuilt": HandbuiltImages}


def provider_for(provider: Any, model: str | None = None):
    """A provider by name, or an object that already has draw, edit, and vectorize (tests pass fakes)."""
    if not isinstance(provider, str):
        return provider
    if provider not in PROVIDERS:
        raise WorkflowFailure("unknown_image_service", f"Unknown image service: {provider}. Choose one of: " + ", ".join(sorted(PROVIDERS)), field="provider")
    return PROVIDERS[provider](model)


# ---------------------------------------------------------------- files

def _church_file(root: Path, raw: Any, field: str) -> Path:
    """A file inside the church folder, given relative to it or as an absolute path inside it."""
    if isinstance(raw, str) and Path(raw).is_absolute():
        try:
            raw = Path(raw).resolve().relative_to(root.resolve()).as_posix()
        except ValueError:
            raise WorkflowFailure("invalid_path", f"{field} must be inside the church folder", field=field) from None
    return _existing(root, raw, field)


def _read_text(root: Path, raw: Any, field: str) -> tuple[Path, str]:
    rel = _church_file(root, raw, field)
    text = (root / rel).read_text(encoding="utf-8")
    if not text.strip():
        raise WorkflowFailure("empty_brief", f"{field} is empty; write the brief first", field=field)
    return rel, text


def flatten_on_white(data: bytes) -> bytes:
    """Any image as an opaque PNG on white. Transparent pixels read as white, never as black."""
    from PIL import Image  # noqa: WPS433
    try:
        image = Image.open(io.BytesIO(data))
        image.load()
    except Exception as exc:  # noqa: BLE001
        raise WorkflowFailure("invalid_image", f"Not a readable image ({exc})") from None
    if image.mode in {"RGBA", "LA", "PA"} or (image.mode == "P" and "transparency" in image.info):
        rgba = image.convert("RGBA")
        ground = Image.new("RGBA", rgba.size, (255, 255, 255, 255))
        ground.alpha_composite(rgba)
        image = ground
    out = io.BytesIO()
    image.convert("RGB").save(out, format="PNG")
    return out.getvalue()


def _image_input(root: Path, raw: Any, field: str, suffixes: set[str] = frozenset({".png"})) -> tuple[Path, bytes]:
    rel = _church_file(root, raw, field)
    if rel.suffix.casefold() not in suffixes:
        raise WorkflowFailure("invalid_image", f"{field} must be one of " + ", ".join(sorted(suffixes)) + f": {rel.as_posix()}", field=field)
    return rel, (root / rel).read_bytes()


def _sha_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _open_round(root: Path, round_label: str, n: int | None = None) -> str:
    state = _load_state(root)
    _exploration_open(state)
    key = survival.slug(round_label)
    if (state["explorations"].get(key) or {}).get("redirected"):
        raise WorkflowFailure("round_redirected", f"Round {key} was redirected; open a new round under the new brief", field="round")
    if n is not None and (not isinstance(n, int) or not 1 <= n <= MAX_IMAGES):
        raise WorkflowFailure("invalid_count", f"Ask for between 1 and {MAX_IMAGES} images in one request", field="n")
    return key


def _lay_out(root: Path, key: str, operation: str, images: list[bytes], *, maker: str, receipt: dict[str, Any],
             brief_text: str, brief_name: str) -> dict[str, Any]:
    """Flatten each image on white, keep the originals privately, and add the round to the contact sheet."""
    call = uuid.uuid4().hex[:8]
    folder = root / IMAGES_DIR / key
    folder.mkdir(parents=True, exist_ok=True)
    _write_text(folder / f"{call}-{brief_name}.md", brief_text.rstrip("\n") + "\n")
    flattened = []
    originals = []
    for index, data in enumerate(images, start=1):
        flat = flatten_on_white(data)
        original = folder / f"{call}-{index:02d}-original.bin"
        original.write_bytes(data)
        originals.append({"file": original.relative_to(root).as_posix(), "sha256": _sha_bytes(data)})
        path = folder / f"{call}-{index:02d}.png"
        path.write_bytes(flat)
        flattened.append(path.relative_to(root).as_posix())
    laid = explore(root, key, flattened, maker=maker)
    if laid.get("status") != "explored":
        return laid
    outputs = [{"id": item["id"], "file": item["file"], "sha256": _sha256(root / item["file"]), "original": original}
               for item, original in zip(laid["added"], originals)]
    record = {"operation": operation, "round": key, "maker": maker, **receipt, "outputs": outputs,
              "flattened_on_white": True, "contact_sheet": laid["contact_sheet"], "explore_receipt": laid["receipt"]}
    path = _receipt(root, f"image-{operation}", record)
    return {"status": {"draw": "drawn", "edit": "edited", "import": "imported"}[operation], "round": key,
            "added": [{"id": o["id"], "file": o["file"]} for o in outputs], "files": laid["files"],
            "contact_sheet": laid["contact_sheet"], "provider": receipt.get("provider"), "model": receipt.get("model"),
            "cost": receipt.get("cost"), "receipt": str(path),
            "next_action": "Look at the contact sheet beside the direction board. Show the pastor two or three, ask for reactions, then draw again, edit the chosen one, or vectorize it."}


# ---------------------------------------------------------------- operations

def draw(church_folder: str | Path, round_label: str, brief_file: str, *, n: int = 4, references: list[str] | None = None,
         provider: Any = "openai", model: str | None = None, size: str = DEFAULT_SIZE, maker: str | None = None) -> dict[str, Any]:
    """Send one editorial brief to an image model and lay the results out for review."""
    try:
        root = _church_root(church_folder)
        key = _open_round(root, round_label, n)
        brief_rel, brief_text = _read_text(root, brief_file, "brief_file")
        inputs = []
        reference_bytes = []
        for raw in references or []:
            rel, data = _image_input(root, raw, "reference")
            inputs.append({"file": rel.as_posix(), "sha256": _sha_bytes(data), "role": "reference"})
            reference_bytes.append(flatten_on_white(data))
        service = provider_for(provider, model)
        result = service.draw(brief_text, n=n, references=reference_bytes, size=size)
        name = getattr(service, "name", str(provider))
        return _lay_out(root, key, "draw", result.images, maker=maker or f"{name}@{result.model}", brief_text=brief_text, brief_name="brief", receipt={
            "provider": name, "model": result.model, "requested": n, "size": size,
            "brief": brief_rel.as_posix(), "brief_sha256": _sha_bytes(brief_text.encode("utf-8")),
            "inputs": inputs, "cost": result.cost, "usage": result.usage})
    except Exception as exc:  # noqa: BLE001
        return _failure(exc)


def edit(church_folder: str | Path, round_label: str, source: str, instruction_file: str, *, n: int = 2,
         provider: Any = "openai", model: str | None = None, size: str = DEFAULT_SIZE, maker: str | None = None) -> dict[str, Any]:
    """A precise edit of one chosen image, for variations the pastor asked for."""
    try:
        root = _church_root(church_folder)
        key = _open_round(root, round_label, n)
        instruction_rel, instruction = _read_text(root, instruction_file, "instruction_file")
        source_rel, data = _image_input(root, source, "source")
        service = provider_for(provider, model)
        result = service.edit(flatten_on_white(data), instruction, n=n, size=size)
        name = getattr(service, "name", str(provider))
        return _lay_out(root, key, "edit", result.images, maker=maker or f"{name}@{result.model}", brief_text=instruction, brief_name="instruction", receipt={
            "provider": name, "model": result.model, "requested": n, "size": size,
            "brief": instruction_rel.as_posix(), "brief_sha256": _sha_bytes(instruction.encode("utf-8")),
            "inputs": [{"file": source_rel.as_posix(), "sha256": _sha_bytes(data), "role": "source"}],
            "cost": result.cost, "usage": result.usage})
    except Exception as exc:  # noqa: BLE001
        return _failure(exc)


def import_images(church_folder: str | Path, round_label: str, files: list[str], prompt_file: str, *, tool: str) -> dict[str, Any]:
    """Register images a host made with its own image tool. No network."""
    try:
        root = _church_root(church_folder)
        key = _open_round(root, round_label)
        tool = (tool or "").strip()
        if not tool:
            raise WorkflowFailure("missing_value", "Name the tool that made the images, for example the host's built-in image generator", field="tool")
        if not files:
            raise WorkflowFailure("files_required", "Name the image files to register", field="files")
        prompt_rel, prompt = _read_text(root, prompt_file, "prompt_file")
        inputs, images = [], []
        for raw in files:
            rel, data = _image_input(root, raw, "files", IMPORT_SUFFIXES)
            inputs.append({"file": rel.as_posix(), "sha256": _sha_bytes(data), "role": "imported"})
            images.append(data)
        return _lay_out(root, key, "import", images, maker=f"import@{tool}", brief_text=prompt, brief_name="prompt", receipt={
            "provider": "import", "tool": tool, "model": None, "brief": prompt_rel.as_posix(),
            "brief_sha256": _sha_bytes(prompt.encode("utf-8")), "inputs": inputs, "cost": None, "network": False})
    except Exception as exc:  # noqa: BLE001
        return _failure(exc)


def vectorize(church_folder: str | Path, source: str, out: str, *, provider: Any = "recraft", dark: str | None = None) -> dict[str, Any]:
    """Turn the chosen raster into one even-odd path painted with currentColor, then check it."""
    try:
        root = _church_root(church_folder)
        if not _recorded(_load_state(root), "direction"):
            raise WorkflowFailure("stage_out_of_order", "Vectorize a mark explored inside the chosen direction; record the direction first")
        source_rel, data = _image_input(root, source, "source")
        out_rel = _relative(root, out, "out")
        if out_rel.suffix.casefold() != ".svg" or not (root / out_rel).resolve().is_relative_to((root / STAGING_DIR).resolve()):
            raise WorkflowFailure("invalid_path", f"out must be an .svg under {STAGING_DIR.as_posix()}/, for example brand/staging/marks/mark.svg", field="out")
        service = provider_for(provider)
        result = service.vectorize(flatten_on_white(data))
        call = uuid.uuid4().hex[:8]
        raw_path = root / VECTOR_DIR / f"{call}-{source_rel.stem}-raw.svg"
        _write_text(raw_path, result.svg)
        svg, summary = normalize_mark_svg(result.svg)
        target = root / out_rel
        replaced = _sha256(target) if target.is_file() else None
        _write_text(target, svg)
        try:
            survival.validate_mark_svg(target, one_color=True)
            _brand_setup()._asset(root, out_rel.as_posix(), "out")
        except (ValueError, survival.SurvivalFailure) as exc:
            raise WorkflowFailure("invalid_mark", str(getattr(exc, "message", exc)), field="out") from exc
        try:
            checks = survival.run_checks(root, target, root / CHECKS_DIR / "vectorize" / out_rel.stem, which=survival.PRIMARY_CHECKS,
                                         dark=dark or survival.DEFAULT_DARK)
            survival_result: dict[str, Any] = {"passed": checks["passed"], "checks": checks["checks"], "renders": checks["renders"]}
        except survival.SurvivalFailure as exc:
            if exc.code != "renderer_unavailable":
                raise
            survival_result = {"passed": None, "skipped": exc.message}
        name = getattr(service, "name", str(provider))
        receipt = _receipt(root, "image-vectorize", {
            "operation": "vectorize", "provider": name, "model": result.model, "cost": result.cost, "usage": result.usage,
            "inputs": [{"file": source_rel.as_posix(), "sha256": _sha_bytes(data), "role": "source"}],
            "raw_svg": {"file": raw_path.relative_to(root).as_posix(), "sha256": _sha256(raw_path)},
            "outputs": [{"file": out_rel.as_posix(), "sha256": _sha256(target)}], "replaced_sha256": replaced,
            "normalized": summary, "survival": survival_result})
        failing = [c["check"] for c in survival_result.get("checks", []) if not c["passed"]]
        action = ("The mark is one path in currentColor and passes the checks. Show it to the pastor at real sizes, then derive the small variant."
                  if survival_result["passed"] else
                  "The vector is clean but fails: " + ", ".join(failing) + ". Edit the raster (bolder, simpler) and vectorize again, or clean up the construction by hand."
                  if failing else "The vector is clean. Run check-marks when the renderer is available.")
        return {"status": "vectorized", "svg": out_rel.as_posix(), "raw_svg": raw_path.relative_to(root).as_posix(),
                "normalized": summary, "survival": survival_result, "provider": name, "cost": result.cost,
                "receipt": str(receipt), "next_action": action}
    except Exception as exc:  # noqa: BLE001
        return _failure(exc)


# ---------------------------------------------------------------- normalizing a vectorizer's SVG

_PATH_ARGS = {"M": 2, "L": 2, "H": 1, "V": 1, "C": 6, "S": 4, "Q": 4, "T": 2, "A": 7, "Z": 0}
_NUMBER = re.compile(r"[-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?")
_SEPARATORS = re.compile(r"[\s,]*")
NAMED_COLORS = {"white": (255, 255, 255), "black": (0, 0, 0), "snow": (255, 250, 250), "ivory": (255, 255, 240),
                "whitesmoke": (245, 245, 245), "gray": (128, 128, 128), "grey": (128, 128, 128)}
PAPER_LUMINANCE = 200
BACKGROUND_COVER = 0.9
CROP_MARGIN = 0.04
SKIPPED_TAGS = {"defs", "clippath", "mask", "pattern", "lineargradient", "radialgradient", "filter", "symbol",
                "metadata", "title", "desc", "style", "marker"}


@dataclass
class _Shape:
    segments: list[tuple[str, list[float]]]
    paper: bool
    order: int
    box: tuple[float, float, float, float] = dataclass_field(default=(0.0, 0.0, 0.0, 0.0))


def _fail(message: str) -> WorkflowFailure:
    return WorkflowFailure("vector_not_normalized", message, field="source")


def _parse_path(d: str) -> list[tuple[str, list[float]]]:
    """Path data as absolute M, L, C, Q, A, and Z segments."""
    position, length = 0, len(d)
    out: list[tuple[str, list[float]]] = []
    command = None
    cx = cy = sx = sy = 0.0
    last_control: tuple[str, float, float] | None = None

    def skip() -> None:
        nonlocal position
        position = _SEPARATORS.match(d, position).end()

    def number() -> float:
        nonlocal position
        skip()
        match = _NUMBER.match(d, position)
        if not match:
            raise _fail(f"Could not read the path data near: {d[position:position + 20]!r}")
        position = match.end()
        return float(match.group())

    def flag() -> float:
        nonlocal position
        skip()
        if position < length and d[position] in "01":
            position += 1
            return float(d[position - 1])
        raise _fail("An arc flag in the path data is not 0 or 1")

    while True:
        skip()
        if position >= length:
            break
        char = d[position]
        if char.isalpha():
            if char.upper() not in _PATH_ARGS:
                raise _fail(f"Unknown path command: {char}")
            command = char
            position += 1
        elif command is None:
            raise _fail("Path data has numbers with no command before them")
        elif command in "Mm":
            command = "L" if command == "M" else "l"
        upper, relative = command.upper(), command.islower()
        if upper == "Z":
            out.append(("Z", []))
            cx, cy = sx, sy
            last_control = None
            command = None
            continue
        if upper == "A":
            values = [number(), number(), number(), flag(), flag(), number(), number()]
        else:
            values = [number() for _ in range(_PATH_ARGS[upper])]
        if upper == "H":
            x = values[0] + (cx if relative else 0)
            out.append(("L", [x, cy]))
            cx = x
            last_control = None
            continue
        if upper == "V":
            y = values[0] + (cy if relative else 0)
            out.append(("L", [cx, y]))
            cy = y
            last_control = None
            continue
        if upper == "A":
            x, y = values[5] + (cx if relative else 0), values[6] + (cy if relative else 0)
            out.append(("A", values[:5] + [x, y]))
            cx, cy = x, y
            last_control = None
            continue
        points = [(values[i] + (cx if relative else 0), values[i + 1] + (cy if relative else 0)) for i in range(0, len(values), 2)]
        if upper == "M":
            out.append(("M", list(points[0])))
            cx, cy = sx, sy = points[0]
            last_control = None
        elif upper == "L":
            out.append(("L", list(points[0])))
            cx, cy = points[0]
            last_control = None
        elif upper in {"C", "S"}:
            if upper == "S":
                first = (2 * cx - last_control[1], 2 * cy - last_control[2]) if last_control and last_control[0] == "C" else (cx, cy)
                points = [first, *points]
            out.append(("C", [*points[0], *points[1], *points[2]]))
            last_control = ("C", *points[1])
            cx, cy = points[2]
        else:  # Q, T
            if upper == "T":
                control = (2 * cx - last_control[1], 2 * cy - last_control[2]) if last_control and last_control[0] == "Q" else (cx, cy)
                points = [control, *points]
            out.append(("Q", [*points[0], *points[1]]))
            last_control = ("Q", *points[0])
            cx, cy = points[1]
    return out


def _parse_transform(text: str | None) -> tuple[float, ...]:
    matrix = (1.0, 0.0, 0.0, 1.0, 0.0, 0.0)
    for name, args in re.findall(r"(matrix|translate|scale|rotate|skewX|skewY)\s*\(([^)]*)\)", text or ""):
        values = [float(v) for v in _NUMBER.findall(args)]
        if name == "matrix" and len(values) == 6:
            step = tuple(values)
        elif name == "translate" and values:
            step = (1.0, 0.0, 0.0, 1.0, values[0], values[1] if len(values) > 1 else 0.0)
        elif name == "scale" and values:
            step = (values[0], 0.0, 0.0, values[1] if len(values) > 1 else values[0], 0.0, 0.0)
        elif name == "rotate" and values:
            angle = math.radians(values[0])
            cos, sin = math.cos(angle), math.sin(angle)
            ox, oy = (values[1], values[2]) if len(values) >= 3 else (0.0, 0.0)
            step = (cos, sin, -sin, cos, ox - cos * ox + sin * oy, oy - sin * ox - cos * oy)
        elif name == "skewX" and values:
            step = (1.0, 0.0, math.tan(math.radians(values[0])), 1.0, 0.0, 0.0)
        elif name == "skewY" and values:
            step = (1.0, math.tan(math.radians(values[0])), 0.0, 1.0, 0.0, 0.0)
        else:
            raise _fail(f"Could not read the transform: {name}({args})")
        matrix = _compose(matrix, step)
    return matrix


def _compose(m: tuple[float, ...], n: tuple[float, ...]) -> tuple[float, ...]:
    a, b, c, d, e, f = m
    a2, b2, c2, d2, e2, f2 = n
    return (a * a2 + c * b2, b * a2 + d * b2, a * c2 + c * d2, b * c2 + d * d2, a * e2 + c * f2 + e, b * e2 + d * f2 + f)


def _apply(matrix: tuple[float, ...], segments: list[tuple[str, list[float]]]) -> list[tuple[str, list[float]]]:
    if matrix == (1.0, 0.0, 0.0, 1.0, 0.0, 0.0):
        return segments
    a, b, c, d, e, f = matrix

    def point(x: float, y: float) -> list[float]:
        return [a * x + c * y + e, b * x + d * y + f]

    out = []
    for command, values in segments:
        if command == "Z":
            out.append((command, []))
        elif command == "A":
            rx, ry, phi, large, sweep, x, y = values
            if abs(b) < 1e-9 and abs(c) < 1e-9:
                rx, ry = rx * abs(a), ry * abs(d)
                if a * d < 0:
                    phi, sweep = -phi, 1 - sweep
            elif abs(a - d) < 1e-9 and abs(b + c) < 1e-9:
                scale = math.hypot(a, b)
                rx, ry, phi = rx * scale, ry * scale, phi + math.degrees(math.atan2(b, a))
            else:
                raise _fail("An arc sits under a skewed transform; this vector cannot be folded into one path automatically")
            out.append((command, [rx, ry, phi, large, sweep, *point(x, y)]))
        else:
            mapped: list[float] = []
            for i in range(0, len(values), 2):
                mapped += point(values[i], values[i + 1])
            out.append((command, mapped))
    return out


def _box(segments: list[tuple[str, list[float]]]) -> tuple[float, float, float, float]:
    xs: list[float] = []
    ys: list[float] = []
    for command, values in segments:
        if command == "A":
            rx, ry, x, y = values[0], values[1], values[5], values[6]
            reach = max(rx, ry)
            xs += [x - reach, x + reach]
            ys += [y - reach, y + reach]
        else:
            xs += values[0::2]
            ys += values[1::2]
    if not xs:
        return (0.0, 0.0, 0.0, 0.0)
    return (min(xs), min(ys), max(xs), max(ys))


def _shape_segments(tag: str, node: ET.Element) -> list[tuple[str, list[float]]]:
    def num(name: str, default: float = 0.0) -> float:
        match = _NUMBER.match((node.get(name) or "").strip())
        return float(match.group()) if match else default

    if tag == "path":
        return _parse_path(node.get("d") or "")
    if tag == "rect":
        x, y, w, h = num("x"), num("y"), num("width"), num("height")
        if w <= 0 or h <= 0:
            return []
        rx = min(num("rx", num("ry")), w / 2)
        ry = min(num("ry", rx), h / 2)
        if rx <= 0 or ry <= 0:
            return [("M", [x, y]), ("L", [x + w, y]), ("L", [x + w, y + h]), ("L", [x, y + h]), ("Z", [])]
        return [("M", [x + rx, y]), ("L", [x + w - rx, y]), ("A", [rx, ry, 0, 0, 1, x + w, y + ry]),
                ("L", [x + w, y + h - ry]), ("A", [rx, ry, 0, 0, 1, x + w - rx, y + h]), ("L", [x + rx, y + h]),
                ("A", [rx, ry, 0, 0, 1, x, y + h - ry]), ("L", [x, y + ry]), ("A", [rx, ry, 0, 0, 1, x + rx, y]), ("Z", [])]
    if tag in {"circle", "ellipse"}:
        cx, cy = num("cx"), num("cy")
        rx = num("r") if tag == "circle" else num("rx")
        ry = num("r") if tag == "circle" else num("ry")
        if rx <= 0 or ry <= 0:
            return []
        return [("M", [cx - rx, cy]), ("A", [rx, ry, 0, 1, 0, cx + rx, cy]), ("A", [rx, ry, 0, 1, 0, cx - rx, cy]), ("Z", [])]
    if tag in {"polygon", "polyline"}:
        values = [float(v) for v in _NUMBER.findall(node.get("points") or "")]
        points = [values[i:i + 2] for i in range(0, len(values) - 1, 2)]
        if len(points) < 3:
            return []
        return [("M", points[0]), *[("L", p) for p in points[1:]], ("Z", [])]
    return []


def _style(node: ET.Element) -> dict[str, str]:
    out = {}
    for item in (node.get("style") or "").split(";"):
        if ":" in item:
            key, value = item.split(":", 1)
            out[key.strip().casefold()] = value.strip()
    return out


def _paint(node: ET.Element, inherited: dict[str, str]) -> dict[str, str]:
    paint = dict(inherited)
    style = _style(node)
    for name in ("fill", "fill-opacity", "opacity", "display", "visibility"):
        value = style.get(name, node.get(name))
        if value is not None:
            if name == "opacity":
                paint[name] = str(float(paint.get(name, "1")) * _opacity(value))
            else:
                paint[name] = value.strip()
    return paint


def _opacity(value: str) -> float:
    match = _NUMBER.match(value.strip())
    if not match:
        return 1.0
    number = float(match.group())
    return number / 100 if value.strip().endswith("%") else number


def _rgb(value: str) -> tuple[int, int, int] | None:
    value = value.strip().casefold()
    if value in {"none", "transparent"}:
        return None
    if value.startswith("#"):
        digits = value[1:]
        if len(digits) in {3, 4}:
            return tuple(int(ch * 2, 16) for ch in digits[:3])  # type: ignore[return-value]
        if len(digits) in {6, 8}:
            return tuple(int(digits[i:i + 2], 16) for i in (0, 2, 4))  # type: ignore[return-value]
    match = re.match(r"rgba?\(([^)]*)\)", value)
    if match:
        parts = [p.strip() for p in re.split(r"[,\s/]+", match.group(1)) if p.strip()]
        channels = [round(float(p[:-1]) * 2.55) if p.endswith("%") else round(float(p)) for p in parts[:3]]
        if len(parts) > 3 and _opacity(parts[3]) <= 0:
            return None
        return tuple(channels)  # type: ignore[return-value]
    if value in NAMED_COLORS:
        return NAMED_COLORS[value]
    return (0, 0, 0)  # currentColor and unknown names paint as ink


def _collect(node: ET.Element, matrix: tuple[float, ...], paint: dict[str, str], shapes: list[_Shape], skipped: dict[str, int]) -> None:
    tag = node.tag.rsplit("}", 1)[-1].casefold()
    if tag in SKIPPED_TAGS:
        return
    if tag in {"use", "image", "text", "foreignobject"}:
        raise _fail(f"The vector contains <{tag}>, which cannot be folded into one path")
    paint = _paint(node, paint)
    if paint.get("display") == "none" or paint.get("visibility") == "hidden":
        return
    matrix = _compose(matrix, _parse_transform(node.get("transform")))
    segments = _shape_segments(tag, node)
    if segments:
        color = _rgb(paint.get("fill", "black"))
        alpha = _opacity(paint.get("fill-opacity", "1")) * float(paint.get("opacity", "1"))
        if color is None or alpha <= 0.05:
            skipped["unpainted"] = skipped.get("unpainted", 0) + 1
        else:
            luminance = 0.299 * color[0] + 0.587 * color[1] + 0.114 * color[2]
            transformed = _apply(matrix, segments)
            shapes.append(_Shape(transformed, luminance >= PAPER_LUMINANCE, len(shapes), _box(transformed)))
    for child in node:
        _collect(child, matrix, paint, shapes, skipped)


def _canvas(root: ET.Element) -> tuple[float, float, float, float]:
    box = [float(v) for v in _NUMBER.findall(root.get("viewBox") or "")]
    if len(box) == 4 and box[2] > 0 and box[3] > 0:
        return tuple(box)  # type: ignore[return-value]
    width = _NUMBER.match(root.get("width") or "")
    height = _NUMBER.match(root.get("height") or "")
    if width and height:
        return (0.0, 0.0, float(width.group()), float(height.group()))
    raise _fail("The vector has neither a viewBox nor a width and height")


def _inside_box(inner: tuple[float, ...], outer: tuple[float, ...], tolerance: float) -> bool:
    return (inner[0] >= outer[0] - tolerance and inner[1] >= outer[1] - tolerance
            and inner[2] <= outer[2] + tolerance and inner[3] <= outer[3] + tolerance)


def _format(value: float) -> str:
    text = f"{value:.2f}".rstrip("0").rstrip(".")
    return "0" if text in {"-0", ""} else text


def _serialize(segments: list[tuple[str, list[float]]]) -> str:
    parts = []
    for command, values in segments:
        if command == "A":
            rx, ry, phi, large, sweep, x, y = values
            parts.append("A" + " ".join([_format(rx), _format(ry), _format(phi), str(int(large)), str(int(sweep)), _format(x), _format(y)]))
        else:
            parts.append(command + " ".join(_format(v) for v in values))
    return "".join(parts)


def normalize_mark_svg(svg_text: str) -> tuple[str, dict[str, Any]]:
    """Fold a vectorizer's layered SVG into one mark path.

    A vectorizer traces a flattened raster as stacked color layers: a white
    ground, the dark mark on it, and white counters painted over the mark.
    The white ground is dropped. Every dark shape and every white shape that
    sits on a dark one becomes a subpath of ONE path with fill-rule evenodd,
    so each counter becomes a real hole. White specks on the ground are
    dropped. The path paints with currentColor and the viewBox is a square
    around the mark with a small margin.
    """
    text = svg_text.strip()
    lowered = text.casefold()
    if "<!doctype" in lowered or "<!entity" in lowered:
        raise _fail("The vector carries a document type declaration; refusing it")
    try:
        root = ET.fromstring(text)
    except ET.ParseError as exc:
        raise _fail(f"The vector is not valid SVG ({exc})") from None
    if root.tag.rsplit("}", 1)[-1].casefold() != "svg":
        raise _fail("The vector's root element is not <svg>")
    _minx, _miny, width, height = _canvas(root)
    shapes: list[_Shape] = []
    skipped: dict[str, int] = {}
    _collect(root, (1.0, 0.0, 0.0, 1.0, 0.0, 0.0), {}, shapes, skipped)
    if not shapes:
        raise _fail("The vector has no filled shapes")

    def covers_canvas(shape: _Shape) -> bool:
        x0, y0, x1, y1 = shape.box
        return (x1 - x0) >= width * BACKGROUND_COVER and (y1 - y0) >= height * BACKGROUND_COVER

    background = [s for s in shapes if s.paper and covers_canvas(s)]
    tolerance = max(width, height) * 0.002
    kept: list[_Shape] = []
    holes = specks = 0
    for shape in shapes:
        if shape in background:
            continue
        if not shape.paper:
            if covers_canvas(shape) and not kept:
                raise _fail("A dark shape covers the whole frame, so the image is a dark ground, not a mark on white. Brief a dark mark on a plain white ground and draw again.")
            kept.append(shape)
        elif any(not k.paper and k.order < shape.order and _inside_box(shape.box, k.box, tolerance) for k in kept):
            kept.append(shape)
            holes += 1
        else:
            specks += 1
    ink = [s for s in kept if not s.paper]
    if not ink:
        raise _fail("No dark shapes remain once the white ground is removed; the image has no mark to keep")
    x0 = min(s.box[0] for s in ink)
    y0 = min(s.box[1] for s in ink)
    x1 = max(s.box[2] for s in ink)
    y1 = max(s.box[3] for s in ink)
    side = max(x1 - x0, y1 - y0)
    side += side * CROP_MARGIN * 2
    view = ((x0 + x1 - side) / 2, (y0 + y1 - side) / 2, side, side)
    d = "".join(_serialize(s.segments) for s in kept)
    out = (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="{" ".join(_format(v) for v in view)}">'
           f'<path fill="currentColor" fill-rule="evenodd" d="{d}"/></svg>\n')
    summary = {"shapes_in": len(shapes), "background_removed": len(background), "ink_shapes": len(ink),
               "holes_folded": holes, "white_specks_dropped": specks, "unpainted_skipped": skipped.get("unpainted", 0),
               "subpaths": sum(1 for s in kept for c, _v in s.segments if c == "M"), "viewbox": [round(v, 2) for v in view],
               "fill": "currentColor", "fill_rule": "evenodd"}
    return out, summary
