"""Thin Google Gemini image client for the LinkedIn Skills project.

Image layer, Google edition. Same job as `pixfaro_client`: turn a prompt into an
image for a post. Verified against the live API 2026-10-07.

Auth: GEMINI_API_KEY env var (Google AI Studio key; `AIza...` or `AQ....`).
Image models have NO free tier: the AI Studio project needs billing linked.

Endpoint (classic, stateless; nothing is stored on Google's side):
  POST https://generativelanguage.googleapis.com/v1beta/models/<model>:generateContent
    header: x-goog-api-key
    body: {contents: [{role, parts: [{text} | {inlineData: {mimeType, data}}]}],
           generationConfig: {responseModalities: ["IMAGE"],
                              imageConfig: {aspectRatio "w:h", imageSize "1K|2K|4K"}}}
    resp: candidates[0].content.parts[].inlineData {mimeType, data (base64)}
  GET  /v1beta/models  — free; lists the models this key can call. The way to
    verify a key (it does not prove billing: only a generation does).

The newer Interactions API also does images, but it keeps every interaction on
Google's servers for 55 days to make edits work. Here an edit sends the saved
image back instead, so a client's draft visuals are never retained.

What Gemini does NOT do, and where it lives instead:
  - hosted URL     -> images are saved locally; `lib.publish` uploads local files
                      through Publora's upload flow (see publora_client).
  - logo overlay   -> `lib.brand_compose` (Pillow), pixel-exact.
  - exact text     -> `lib.brand_compose` typesets it; `lib.text_check` OCR-verifies
                      text the model drew itself.
  - balance        -> not exposed by Google; results carry an estimated `cost`
                      from PRICES below. Real spend: AI Studio -> Spend.

Models (id / $ per image at 1K, 2K, 4K; ai.google.dev/gemini-api/docs/pricing):
  gemini-nano-banana-2.1       0.0336 / 0.0504 / 0.113   (default: newest, best type)
  gemini-3.1-flash-lite-image  0.0336 / 0.0336 / -       (fastest)
  gemini-3.1-flash-image       0.067  / 0.101  / 0.151   (Pixfaro's old default)
  gemini-3-pro-image           0.134  / 0.134  / 0.24    (premium: ask first)

Caching: in-process LRU (128 entries, 6h TTL), `force_refresh=True` to bypass.
Retries on transient 408/429/5xx and network errors (3 attempts, backoff).
"""
from __future__ import annotations
import base64
import hashlib
import json
import os
import random
import time
from collections import OrderedDict
from pathlib import Path
from typing import Any, Iterable, Optional

import requests

from ._env import load_env


class GeminiError(RuntimeError):
    def __init__(self, message: str, status_code: Optional[int] = None, retryable: bool = False):
        super().__init__(message)
        self.status_code = status_code
        self.retryable = retryable


BASE_URL = "https://generativelanguage.googleapis.com/v1beta"
DEFAULT_MODEL = "gemini-nano-banana-2.1"
PREMIUM_MODELS = {"gemini-3-pro-image"}

#: $ per image by model and size. Estimates for the approval card; Google bills
#: by output tokens and reports no balance.
PRICES: dict[str, dict[str, float]] = {
    "gemini-nano-banana-2.1": {"1K": 0.0336, "2K": 0.0504, "4K": 0.113},
    "gemini-3.1-flash-lite-image": {"1K": 0.0336, "2K": 0.0336},
    "gemini-3.1-flash-image": {"1K": 0.067, "2K": 0.101, "4K": 0.151},
    "gemini-3-pro-image": {"1K": 0.134, "2K": 0.134, "4K": 0.24},
    "gemini-2.5-flash-image": {"1K": 0.039},
}

ASPECT_RATIOS = {"1:1", "3:2", "2:3", "3:4", "4:3", "4:5", "5:4", "9:16", "16:9", "21:9"}
IMAGE_SIZES = {"1K", "2K", "4K"}

RETRYABLE_STATUSES = {408, 429, 500, 502, 503, 504}
CACHE_MAX_ENTRIES = 128
CACHE_TTL_SECONDS = 6 * 60 * 60

#: Where generated images land. `output/` is gitignored: drafts are client work.
OUTPUT_DIR = Path(__file__).resolve().parents[1] / "output" / "images"

_MIME_EXT = {"image/png": ".png", "image/jpeg": ".jpg", "image/webp": ".webp"}


def estimate_cost(model: str, image_size: str = "1K") -> Optional[float]:
    return PRICES.get(model, {}).get(image_size)


def image_path_for(image_id: str) -> Optional[Path]:
    """Resolve a `gimg_...` id to its saved file, or None."""
    for p in OUTPUT_DIR.glob(f"{image_id}.*"):
        return p
    return None


def _retry(attempts: int = 3, base_delay: float = 0.8):
    def decorator(fn):
        def wrapper(*args, **kwargs):
            for attempt in range(attempts):
                try:
                    return fn(*args, **kwargs)
                except GeminiError as e:
                    if not e.retryable or attempt == attempts - 1:
                        raise
                    time.sleep(base_delay * (2 ** attempt) + random.uniform(0, 0.3))
        return wrapper
    return decorator


class GeminiImageClient:
    """`generate` and `edit` return {id, path, mime_type, model, image_size, cost}."""

    def __init__(self, api_key: Optional[str] = None, timeout: float = 180.0,
                 output_dir: Optional[Path] = None):
        load_env()
        self.api_key = (api_key or os.getenv("GEMINI_API_KEY") or "").strip()
        if not self.api_key:
            raise GeminiError(
                "No Gemini API key. Set GEMINI_API_KEY in .env (Google AI Studio -> "
                "API Keys), and link billing: image models have no free tier."
            )
        self.timeout = timeout
        self.output_dir = Path(output_dir) if output_dir else OUTPUT_DIR
        self._session = requests.Session()
        self._cache: "OrderedDict[str, tuple[float, dict]]" = OrderedDict()

    # ---- cache helpers (mirror pixfaro_client) ----
    def _cache_get(self, key: str) -> Optional[dict]:
        hit = self._cache.get(key)
        if not hit:
            return None
        ts, val = hit
        if time.time() - ts > CACHE_TTL_SECONDS or not Path(val["path"]).is_file():
            self._cache.pop(key, None)
            return None
        self._cache.move_to_end(key)
        return val

    def _cache_put(self, key: str, val: dict) -> None:
        self._cache[key] = (time.time(), val)
        self._cache.move_to_end(key)
        while len(self._cache) > CACHE_MAX_ENTRIES:
            self._cache.popitem(last=False)

    # ---- public ----
    def generate(
        self,
        prompt: str,
        *,
        model: str = DEFAULT_MODEL,
        aspect_ratio: str = "4:5",
        image_size: str = "1K",
        reference_images: Optional[Iterable[str]] = None,
        force_refresh: bool = False,
    ) -> dict[str, Any]:
        """Generate one image. `reference_images` are local file paths (style or
        brand references, up to 14) sent alongside the prompt."""
        if not prompt or not prompt.strip():
            raise GeminiError("prompt cannot be empty")
        parts: list[dict[str, Any]] = [{"text": prompt}]
        for ref in reference_images or ():
            parts.append(_inline_part(Path(ref)))
        return self._run(parts, model, aspect_ratio, image_size, force_refresh)

    def edit(
        self,
        image: str,
        instruction: str,
        *,
        model: str = DEFAULT_MODEL,
        aspect_ratio: Optional[str] = None,
        image_size: str = "1K",
        force_refresh: bool = False,
    ) -> dict[str, Any]:
        """Edit a prior image. `image` is a `gimg_...` id or a local file path.
        The source image is re-sent (stateless); `aspect_ratio` defaults to the
        source's own shape."""
        if not instruction or not instruction.strip():
            raise GeminiError("instruction cannot be empty")
        src = image_path_for(image) if str(image).startswith("gimg_") else Path(image)
        if not src or not src.is_file():
            raise GeminiError(f"source image not found: {image!r} (pass a gimg_ id or a file path)")
        ar = aspect_ratio or _closest_ratio(src)
        parts = [_inline_part(src), {"text": instruction}]
        return self._run(parts, model, ar, image_size, force_refresh)

    def list_models(self) -> list[dict[str, Any]]:
        """Image-capable models this key can call (free endpoint)."""
        r = self._get("/models", params={"pageSize": 1000})
        return [m for m in r.get("models", [])
                if any(s in m.get("name", "") for s in ("image", "banana"))]

    def whoami(self) -> dict[str, Any]:
        """Key check: {ok, image_models}. Proves the key, not billing."""
        models = self.list_models()
        return {"ok": True, "image_models": [m["name"].split("/", 1)[-1] for m in models]}

    # ---- internals ----
    def _run(self, parts, model, aspect_ratio, image_size, force_refresh) -> dict[str, Any]:
        if aspect_ratio not in ASPECT_RATIOS:
            raise GeminiError(f"aspect_ratio {aspect_ratio!r} not supported; use one of {sorted(ASPECT_RATIOS)}")
        if image_size not in IMAGE_SIZES:
            raise GeminiError(f"image_size must be one of {sorted(IMAGE_SIZES)}")
        body = {
            "contents": [{"role": "user", "parts": parts}],
            "generationConfig": {
                "responseModalities": ["IMAGE"],
                "imageConfig": {"aspectRatio": aspect_ratio, "imageSize": image_size},
            },
        }
        key = hashlib.sha256((model + json.dumps(body, sort_keys=True)).encode()).hexdigest()
        if not force_refresh:
            cached = self._cache_get(key)
            if cached is not None:
                return cached
        data = self._post(f"/models/{model}:generateContent", body)
        raw, mime = _extract_image(data)
        image_id = "gimg_" + hashlib.sha256(raw).hexdigest()[:16]
        self.output_dir.mkdir(parents=True, exist_ok=True)
        path = self.output_dir / f"{image_id}{_MIME_EXT.get(mime, '.png')}"
        path.write_bytes(raw)
        result = {
            "id": image_id,
            "path": str(path),
            "mime_type": mime,
            "model": data.get("modelVersion") or model,
            "image_size": image_size,
            "aspect_ratio": aspect_ratio,
            "cost": estimate_cost(model, image_size),
        }
        self._cache_put(key, result)
        return result

    @_retry()
    def _post(self, path: str, body: dict[str, Any]) -> dict[str, Any]:
        try:
            r = self._session.post(BASE_URL + path, json=body, headers=self._headers(), timeout=self.timeout)
        except requests.RequestException as e:
            raise GeminiError(f"request failed: {e}", retryable=True) from e
        return _handle(r)

    @_retry()
    def _get(self, path: str, params: Optional[dict] = None) -> dict[str, Any]:
        try:
            r = self._session.get(BASE_URL + path, params=params, headers=self._headers(), timeout=self.timeout)
        except requests.RequestException as e:
            raise GeminiError(f"request failed: {e}", retryable=True) from e
        return _handle(r)

    def _headers(self) -> dict[str, str]:
        return {"x-goog-api-key": self.api_key, "Content-Type": "application/json"}


def _inline_part(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise GeminiError(f"image not found: {path}")
    ext = path.suffix.lower()
    mime = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".webp": "image/webp"}.get(ext)
    if not mime:
        raise GeminiError(f"unsupported image type {ext!r}; use PNG, JPEG or WebP")
    return {"inlineData": {"mimeType": mime, "data": base64.b64encode(path.read_bytes()).decode("ascii")}}


def _closest_ratio(path: Path) -> str:
    try:
        from PIL import Image
        with Image.open(path) as im:
            w, h = im.size
    except Exception:
        return "1:1"
    def val(r: str) -> float:
        a, b = r.split(":")
        return int(a) / int(b)
    return min(ASPECT_RATIOS, key=lambda r: abs(val(r) - w / h))


def _extract_image(data: dict[str, Any]) -> tuple[bytes, str]:
    """Pull the image bytes out of a generateContent response, or explain why
    there are none (safety block, text-only answer)."""
    cands = data.get("candidates") or []
    if not cands:
        block = (data.get("promptFeedback") or {}).get("blockReason")
        raise GeminiError(f"no image returned{f' (prompt blocked: {block})' if block else ''}")
    for part in (cands[0].get("content") or {}).get("parts") or []:
        inline = part.get("inlineData") or part.get("inline_data")
        if inline and inline.get("data"):
            return base64.b64decode(inline["data"]), inline.get("mimeType") or inline.get("mime_type") or "image/png"
    reason = cands[0].get("finishReason")
    texts = " ".join(p.get("text", "") for p in (cands[0].get("content") or {}).get("parts") or [])
    raise GeminiError(f"no image returned (finishReason={reason}){': ' + texts[:200] if texts else ''}")


def _handle(r: requests.Response) -> dict[str, Any]:
    if r.status_code >= 400:
        try:
            err = r.json().get("error", {})
            detail = f"{err.get('status', '')}: {err.get('message', '')}".strip(": ")
        except Exception:
            detail = r.text[:300]
        hint = ""
        if r.status_code in (401, 403):
            hint = " - check GEMINI_API_KEY in .env"
        elif r.status_code == 429:
            hint = " - rate limit or no billing on the AI Studio project (image models have no free tier)"
        raise GeminiError(f"HTTP {r.status_code}: {detail}{hint}",
                          status_code=r.status_code, retryable=r.status_code in RETRYABLE_STATUSES)
    try:
        return r.json()
    except ValueError as e:
        raise GeminiError(f"non-JSON response: {r.text[:300]}") from e
