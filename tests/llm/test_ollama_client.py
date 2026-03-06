"""
Unit tests for retry logic in src/llm/ollama_client.py

Tests that transient failures are retried and permanent failures are raised immediately.
All tests mock HTTP calls — no real Ollama server is needed.
"""

import pytest
from unittest.mock import patch, MagicMock

from src.llm.ollama_client import OllamaClient, OllamaError, _is_retryable


# ──────────────────────────────────────────────────────────────────────
# _is_retryable classification
# ──────────────────────────────────────────────────────────────────────


class TestIsRetryable:

    def test_connection_error_not_retryable(self):
        err = OllamaError("Cannot connect to Ollama. Is it running?")
        assert _is_retryable(err) is False

    def test_image_not_found_not_retryable(self):
        err = OllamaError("Image not found: /path/to/missing.png")
        assert _is_retryable(err) is False

    def test_timeout_is_retryable(self):
        err = OllamaError("Ollama timed out. Try a smaller model or shorter input.")
        assert _is_retryable(err) is True

    def test_invalid_json_is_retryable(self):
        err = OllamaError("LLM returned invalid JSON: Expecting value")
        assert _is_retryable(err) is True

    def test_generic_ollama_error_is_retryable(self):
        err = OllamaError("Ollama error: model busy")
        assert _is_retryable(err) is True


# ──────────────────────────────────────────────────────────────────────
# Retry logic in generate_json
# ──────────────────────────────────────────────────────────────────────


class TestRetryLogic:

    def _make_client(self, max_retries=2, retry_delay=0.0):
        """Create an OllamaClient with zero delay for fast tests."""
        return OllamaClient(
            max_retries=max_retries,
            retry_delay=retry_delay,
        )

    @patch.object(OllamaClient, 'generate_text')
    def test_retry_on_json_parse_failure(self, mock_gen):
        """First call returns garbage, second returns valid JSON → succeeds."""
        mock_gen.side_effect = [
            "not valid json at all",
            '[{"front": "Q?", "back": "A"}]',
        ]
        client = self._make_client(max_retries=2)
        result = client.generate_json("test prompt")

        assert isinstance(result, list)
        assert result[0]["front"] == "Q?"
        assert mock_gen.call_count == 2

    @patch.object(OllamaClient, 'generate_text')
    def test_no_retry_on_connection_error(self, mock_gen):
        """Connection error is permanent — should raise immediately."""
        mock_gen.side_effect = OllamaError("Cannot connect to Ollama. Is it running?")
        client = self._make_client(max_retries=2)

        with pytest.raises(OllamaError, match="Cannot connect"):
            client.generate_json("test prompt")

        # Should only be called once (no retries)
        assert mock_gen.call_count == 1

    @patch.object(OllamaClient, 'generate_text')
    def test_retry_exhausted_raises(self, mock_gen):
        """All retries fail → raises the last error."""
        mock_gen.return_value = "still not json"
        client = self._make_client(max_retries=2)

        with pytest.raises(OllamaError, match="invalid JSON"):
            client.generate_json("test prompt")

        # 1 initial + 2 retries = 3 total
        assert mock_gen.call_count == 3

    @patch.object(OllamaClient, 'generate_text')
    def test_retry_on_timeout_then_success(self, mock_gen):
        """Timeout on first call, success on second."""
        mock_gen.side_effect = [
            OllamaError("Ollama timed out. Try a smaller model or shorter input."),
            '[{"front": "Q?", "back": "A"}]',
        ]
        client = self._make_client(max_retries=2)
        result = client.generate_json("test prompt")

        assert isinstance(result, list)
        assert mock_gen.call_count == 2

    @patch('time.sleep')
    @patch.object(OllamaClient, 'generate_text')
    def test_retry_delay_respected(self, mock_gen, mock_sleep):
        """Verify time.sleep is called between retries with correct delay."""
        mock_gen.side_effect = [
            "bad json",
            '[{"front": "Q?", "back": "A"}]',
        ]
        client = self._make_client(max_retries=2, retry_delay=1.5)
        client.generate_json("test prompt")

        mock_sleep.assert_called_once_with(1.5)

    @patch.object(OllamaClient, 'generate_with_image')
    def test_retry_on_vision_json_failure(self, mock_gen):
        """generate_json_with_image also retries on parse failure."""
        mock_gen.side_effect = [
            "not json",
            '[{"front": "Q?", "back": "A"}]',
        ]
        client = self._make_client(max_retries=2)
        result = client.generate_json_with_image("prompt", "/fake/img.png")

        assert isinstance(result, list)
        assert mock_gen.call_count == 2

    @patch.object(OllamaClient, 'generate_with_image')
    def test_vision_image_not_found_no_retry(self, mock_gen):
        """Image not found is permanent — no retry."""
        mock_gen.side_effect = OllamaError("Image not found: /missing.png")
        client = self._make_client(max_retries=2)

        with pytest.raises(OllamaError, match="Image not found"):
            client.generate_json_with_image("prompt", "/missing.png")

        assert mock_gen.call_count == 1
