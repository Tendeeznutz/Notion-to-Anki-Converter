"""
ollama_client.py
Thin wrapper around Ollama's local REST API.

Ollama exposes:
    POST http://localhost:11434/api/generate   — text generation
    POST http://localhost:11434/api/generate   — vision (with images: [...])
    GET  http://localhost:11434/api/tags       — list installed models
"""

import base64
import json
import logging
import os
import time
import requests
from typing import Optional


OLLAMA_BASE = "http://localhost:11434"
DEFAULT_TEXT_MODEL = "llama3"
DEFAULT_VISION_MODEL = "llava"

logger = logging.getLogger(__name__)


class OllamaError(Exception):
    pass


# Error messages that indicate permanent failures — never retry these.
_PERMANENT_ERROR_PATTERNS = (
    "Cannot connect",
    "Image not found",
    "not running",
)


def _is_retryable(error: OllamaError) -> bool:
    """Return True if the error is transient and worth retrying."""
    msg = str(error)
    return not any(pattern in msg for pattern in _PERMANENT_ERROR_PATTERNS)


class OllamaClient:
    def __init__(
        self,
        text_model: str = DEFAULT_TEXT_MODEL,
        vision_model: str = DEFAULT_VISION_MODEL,
        base_url: str = OLLAMA_BASE,
        timeout: int = 120,
        vision_timeout: int = 120,
        max_retries: int = 2,
        retry_delay: float = 1.5,
    ):
        self.text_model = text_model
        self.vision_model = vision_model
        self.base_url = base_url.rstrip('/')
        self.timeout = timeout
        self.vision_timeout = vision_timeout
        self.max_retries = max_retries
        self.retry_delay = retry_delay

    # ------------------------------------------------------------------
    # Health & model management
    # ------------------------------------------------------------------

    def is_running(self) -> bool:
        """Return True if Ollama is reachable."""
        try:
            r = requests.get(f"{self.base_url}/api/tags", timeout=5)
            return r.status_code == 200
        except requests.exceptions.ConnectionError:
            return False

    def list_models(self) -> list[str]:
        """Return names of all locally installed models."""
        r = requests.get(f"{self.base_url}/api/tags", timeout=10)
        r.raise_for_status()
        return [m["name"] for m in r.json().get("models", [])]

    def is_model_available(self, model_name: str) -> bool:
        """Check if a specific model is installed."""
        try:
            models = self.list_models()
            # Ollama model names can have :latest suffix — normalise
            normalised = [m.split(':')[0] for m in models]
            return model_name.split(':')[0] in normalised
        except Exception:
            return False

    def pull_model(self, model_name: str, on_progress=None) -> None:
        """
        Pull a model from Ollama's registry. Streams progress.
        on_progress: optional callable(status: str) for UI updates.
        """
        r = requests.post(
            f"{self.base_url}/api/pull",
            json={"name": model_name, "stream": True},
            stream=True,
            timeout=600,  # pulls can take a while
        )
        r.raise_for_status()
        for line in r.iter_lines():
            if line:
                data = json.loads(line)
                status = data.get("status", "")
                if on_progress:
                    on_progress(status)
                if data.get("error"):
                    raise OllamaError(f"Pull error: {data['error']}")

    # ------------------------------------------------------------------
    # Text generation
    # ------------------------------------------------------------------

    def generate_text(self, prompt: str, system: str = "", temperature: float = 0.3) -> str:
        """
        Send a text prompt and return the response string.
        Temperature is low by default for more deterministic JSON output.
        """
        payload = {
            "model": self.text_model,
            "prompt": prompt,
            "stream": False,
            "options": {"temperature": temperature},
        }
        if system:
            payload["system"] = system

        try:
            r = requests.post(
                f"{self.base_url}/api/generate",
                json=payload,
                timeout=self.timeout,
            )
            r.raise_for_status()
        except requests.exceptions.ConnectionError:
            raise OllamaError("Cannot connect to Ollama. Is it running?")
        except requests.exceptions.Timeout:
            raise OllamaError("Ollama timed out. Try a smaller model or shorter input.")

        data = r.json()
        if "error" in data:
            raise OllamaError(f"Ollama error: {data['error']}")

        return data.get("response", "").strip()

    # ------------------------------------------------------------------
    # Vision generation
    # ------------------------------------------------------------------

    def generate_with_image(
        self,
        prompt: str,
        image_path: str,
        system: str = "",
        temperature: float = 0.3,
    ) -> str:
        """
        Send a prompt alongside an image (base64-encoded) to a vision model.
        """
        if not os.path.isfile(image_path):
            raise OllamaError(f"Image not found: {image_path}")

        with open(image_path, "rb") as f:
            b64 = base64.b64encode(f.read()).decode("utf-8")

        payload = {
            "model": self.vision_model,
            "prompt": prompt,
            "images": [b64],
            "stream": False,
            "options": {"temperature": temperature},
        }
        if system:
            payload["system"] = system

        try:
            r = requests.post(
                f"{self.base_url}/api/generate",
                json=payload,
                timeout=self.vision_timeout,
            )
            r.raise_for_status()
        except requests.exceptions.ConnectionError:
            raise OllamaError("Cannot connect to Ollama. Is it running?")
        except requests.exceptions.Timeout:
            raise OllamaError(
                f"Vision model timed out after {self.vision_timeout}s — "
                "the image may be too complex or your hardware too slow. "
                "Try enabling 'Skip images' if this keeps happening."
            )

        data = r.json()
        if "error" in data:
            raise OllamaError(f"Ollama vision error: {data['error']}")

        return data.get("response", "").strip()

    # ------------------------------------------------------------------
    # JSON helpers
    # ------------------------------------------------------------------

    def generate_json(self, prompt: str, system: str = "") -> dict | list:
        """
        Generate text and parse it as JSON.
        Strips markdown code fences if the model wraps output in ```json ... ```

        Retries on transient failures (timeouts, malformed JSON) up to
        self.max_retries times. Permanent failures (connection refused,
        missing image) are raised immediately.
        """
        last_error = None
        for attempt in range(self.max_retries + 1):
            try:
                raw = self.generate_text(prompt, system=system)
                return _parse_json_response(raw)
            except OllamaError as e:
                last_error = e
                if not _is_retryable(e) or attempt == self.max_retries:
                    raise
                logger.warning(
                    "Retry %d/%d for generate_json: %s",
                    attempt + 1, self.max_retries, e,
                )
                time.sleep(self.retry_delay)
        raise last_error  # unreachable, satisfies type checkers

    def generate_json_with_image(
        self, prompt: str, image_path: str, system: str = ""
    ) -> dict | list:
        """
        Generate text with an image and parse it as JSON.
        Retries on transient failures up to self.max_retries times.
        """
        last_error = None
        for attempt in range(self.max_retries + 1):
            try:
                raw = self.generate_with_image(prompt, image_path, system=system)
                return _parse_json_response(raw)
            except OllamaError as e:
                last_error = e
                if not _is_retryable(e) or attempt == self.max_retries:
                    raise
                logger.warning(
                    "Retry %d/%d for generate_json_with_image: %s",
                    attempt + 1, self.max_retries, e,
                )
                time.sleep(self.retry_delay)
        raise last_error  # unreachable, satisfies type checkers


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------

def _parse_json_response(raw: str) -> dict | list:
    """Strip markdown fences and parse JSON. Raises OllamaError on failure."""
    # Strip ```json ... ``` or ``` ... ``` wrappers
    cleaned = raw.strip()
    if cleaned.startswith("```"):
        lines = cleaned.splitlines()
        # Drop first and last fence lines
        cleaned = '\n'.join(lines[1:-1] if lines[-1].strip() == '```' else lines[1:])

    try:
        return json.loads(cleaned)
    except json.JSONDecodeError as e:
        raise OllamaError(
            f"LLM returned invalid JSON: {e}\n\nRaw response:\n{raw[:500]}"
        )
