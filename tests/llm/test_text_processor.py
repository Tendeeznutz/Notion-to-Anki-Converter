"""
Unit tests for src/llm/text_processor.py

Tests flashcard generation logic with mocked OllamaClient.
No real LLM calls are made.
"""

import pytest
from unittest.mock import MagicMock

from src.llm.ollama_client import OllamaError
from src.llm.text_processor import (
    FlashCard,
    build_cards_from_topic,
    build_cards_from_topic_with_image,
    _build_text_prompt,
    _build_image_prompt,
)


# ──────────────────────────────────────────────────────────────────────
# build_cards_from_topic (text-only)
# ──────────────────────────────────────────────────────────────────────


class TestBuildCardsFromTopic:

    def test_valid_json_produces_flashcards(self, mock_client):
        mock_client.generate_json.return_value = [
            {"front": "What is photosynthesis?", "back": "The process by which plants convert light to energy."}
        ]
        cards = build_cards_from_topic(
            topic_title="Photosynthesis",
            topic_text="Plants convert sunlight into glucose.",
            deck_path="Biology::Photosynthesis",
            client=mock_client,
        )

        assert len(cards) == 1
        assert cards[0].front == "What is photosynthesis?"
        assert cards[0].back == "The process by which plants convert light to energy."
        assert cards[0].topic_path == "Biology::Photosynthesis"
        assert cards[0].image_path is None

    def test_empty_text_returns_empty(self, mock_client):
        cards = build_cards_from_topic(
            topic_title="Empty",
            topic_text="",
            deck_path="Test",
            client=mock_client,
        )
        assert cards == []
        # Client should not have been called
        mock_client.generate_json.assert_not_called()

    def test_whitespace_only_text_returns_empty(self, mock_client):
        cards = build_cards_from_topic(
            topic_title="Spaces",
            topic_text="   \n  \t  ",
            deck_path="Test",
            client=mock_client,
        )
        assert cards == []
        mock_client.generate_json.assert_not_called()

    def test_non_list_response_returns_empty(self, mock_client):
        # LLM returns a dict instead of a list
        mock_client.generate_json.return_value = {
            "front": "Q?", "back": "A"
        }
        cards = build_cards_from_topic(
            topic_title="Topic",
            topic_text="Some content",
            deck_path="Test",
            client=mock_client,
        )
        assert cards == []

    def test_empty_front_skipped(self, mock_client):
        mock_client.generate_json.return_value = [
            {"front": "", "back": "An answer"}
        ]
        cards = build_cards_from_topic(
            topic_title="Topic",
            topic_text="Content",
            deck_path="Test",
            client=mock_client,
        )
        assert cards == []

    def test_empty_back_skipped(self, mock_client):
        mock_client.generate_json.return_value = [
            {"front": "A question?", "back": ""}
        ]
        cards = build_cards_from_topic(
            topic_title="Topic",
            topic_text="Content",
            deck_path="Test",
            client=mock_client,
        )
        assert cards == []

    def test_identical_front_back_skipped(self, mock_client):
        mock_client.generate_json.return_value = [
            {"front": "HTTP is stateless", "back": "http is stateless"}
        ]
        cards = build_cards_from_topic(
            topic_title="HTTP",
            topic_text="HTTP protocol info",
            deck_path="Test",
            client=mock_client,
        )
        assert cards == []

    def test_ollama_error_returns_empty(self, mock_client):
        mock_client.generate_json.side_effect = OllamaError("Connection timed out")
        cards = build_cards_from_topic(
            topic_title="Topic",
            topic_text="Content",
            deck_path="Test",
            client=mock_client,
        )
        assert cards == []

    def test_multiple_cards_mixed_validity(self, mock_client):
        mock_client.generate_json.return_value = [
            {"front": "Valid Q1?", "back": "Valid A1"},           # valid
            {"front": "", "back": "Orphan answer"},               # empty front
            {"front": "Same text", "back": "Same Text"},          # identical (case-insensitive)
            {"front": "Valid Q2?", "back": "Valid A2"},           # valid
        ]
        cards = build_cards_from_topic(
            topic_title="Topic",
            topic_text="Content",
            deck_path="Test",
            client=mock_client,
        )
        assert len(cards) == 2
        assert cards[0].front == "Valid Q1?"
        assert cards[1].front == "Valid Q2?"

    def test_non_dict_items_skipped(self, mock_client):
        mock_client.generate_json.return_value = [
            "just a string",
            42,
            {"front": "Real Q?", "back": "Real A"},
        ]
        cards = build_cards_from_topic(
            topic_title="Topic",
            topic_text="Content",
            deck_path="Test",
            client=mock_client,
        )
        assert len(cards) == 1
        assert cards[0].front == "Real Q?"


# ──────────────────────────────────────────────────────────────────────
# build_cards_from_topic_with_image (vision-aware)
# ──────────────────────────────────────────────────────────────────────


class TestBuildCardsFromTopicWithImage:

    def test_image_card_with_uses_image_true(self, mock_client):
        mock_client.generate_json_with_image.return_value = [
            {
                "front": "What does this diagram show?",
                "back": "The water cycle",
                "uses_image": True,
                "image_side": "front",
            }
        ]
        cards = build_cards_from_topic_with_image(
            topic_title="Water Cycle",
            topic_text="The water cycle involves evaporation...",
            deck_path="Science",
            image_path="/path/to/diagram.png",
            image_alt="Water cycle diagram",
            client=mock_client,
        )

        assert len(cards) == 1
        assert cards[0].image_path == "/path/to/diagram.png"
        assert cards[0].image_side == "front"
        assert cards[0].image_alt == "Water cycle diagram"

    def test_image_card_with_uses_image_false(self, mock_client):
        mock_client.generate_json_with_image.return_value = [
            {
                "front": "What is evaporation?",
                "back": "Evaporation is the process...",
                "uses_image": False,
            }
        ]
        cards = build_cards_from_topic_with_image(
            topic_title="Water Cycle",
            topic_text="Content",
            deck_path="Science",
            image_path="/path/to/img.png",
            image_alt="alt",
            client=mock_client,
        )

        assert len(cards) == 1
        assert cards[0].image_path is None
        assert cards[0].image_side is None

    def test_vision_fallback_on_error(self, mock_client):
        # Vision call fails → falls back to text-only
        mock_client.generate_json_with_image.side_effect = OllamaError("Vision timed out")
        mock_client.generate_json.return_value = [
            {"front": "Fallback Q?", "back": "Fallback A"}
        ]

        cards = build_cards_from_topic_with_image(
            topic_title="Topic",
            topic_text="Content for fallback",
            deck_path="Test",
            image_path="/fake/path.png",
            image_alt="alt",
            client=mock_client,
        )

        assert len(cards) == 1
        assert cards[0].front == "Fallback Q?"
        # Fallback should call generate_json (text-only)
        mock_client.generate_json.assert_called_once()

    def test_vision_non_list_returns_empty(self, mock_client):
        mock_client.generate_json_with_image.return_value = {
            "front": "Q?", "back": "A"
        }
        cards = build_cards_from_topic_with_image(
            topic_title="Topic",
            topic_text="Content",
            deck_path="Test",
            image_path="/path.png",
            image_alt="alt",
            client=mock_client,
        )
        assert cards == []

    def test_vision_identical_front_back_skipped(self, mock_client):
        mock_client.generate_json_with_image.return_value = [
            {
                "front": "Same content",
                "back": "same content",
                "uses_image": True,
                "image_side": "front",
            }
        ]
        cards = build_cards_from_topic_with_image(
            topic_title="Topic",
            topic_text="Content",
            deck_path="Test",
            image_path="/path.png",
            image_alt="alt",
            client=mock_client,
        )
        assert cards == []


# ──────────────────────────────────────────────────────────────────────
# Prompt construction
# ──────────────────────────────────────────────────────────────────────


class TestPromptConstruction:

    def test_text_prompt_contains_title_and_text(self):
        prompt = _build_text_prompt("Photosynthesis", "Plants convert light to energy", 5)
        assert "Photosynthesis" in prompt
        assert "Plants convert light to energy" in prompt
        assert "5" in prompt

    def test_image_prompt_contains_alt_text(self):
        prompt = _build_image_prompt("Topic", "Text content", "A diagram of the cell", 4)
        assert "A diagram of the cell" in prompt
        assert "Topic" in prompt
        assert "4" in prompt

    def test_image_prompt_no_alt_text(self):
        prompt = _build_image_prompt("Topic", "Text content", "", 4)
        assert "No alt text provided" in prompt
