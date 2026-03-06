"""
Shared test fixtures for the Notion → Anki converter test suite.
"""

import pytest
from unittest.mock import MagicMock

from src.llm.ollama_client import OllamaClient


@pytest.fixture
def tmp_md_file(tmp_path):
    """
    Factory fixture: call with markdown content string, returns the file path.

    Usage:
        def test_something(tmp_md_file):
            path = tmp_md_file("# Heading\\nSome text")
            root = parse_markdown_file(path)
    """
    def _create(content: str, name: str = "test_notes.md") -> str:
        md_file = tmp_path / name
        md_file.write_text(content, encoding="utf-8")
        return str(md_file)
    return _create


@pytest.fixture
def mock_client():
    """A mock OllamaClient with all methods stubbed."""
    client = MagicMock(spec=OllamaClient)
    return client
