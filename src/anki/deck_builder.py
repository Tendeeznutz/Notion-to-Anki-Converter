"""
deck_builder.py
Takes a list of FlashCard objects and builds a .apkg file using genanki.

Deck hierarchy mirrors the Notion folder structure:
    My Notes::Biology::Photosynthesis → Anki subdeck

Cards with images embed them as HTML <img> tags in the card fields.
All image files are bundled into the .apkg media collection.
"""

import hashlib
import os
import tempfile
import shutil
from typing import Optional

import genanki

from ..llm.text_processor import FlashCard
from ..utils.image_utils import ImageRegistry


# ------------------------------------------------------------------
# Anki model (card template)
# ------------------------------------------------------------------

# IDs must be stable — changing them breaks existing Anki collections
MODEL_ID = 1_607_392_319   # Arbitrary fixed int
CLOZE_MODEL_ID = 1_607_392_320
DECK_ID_BASE = 1_000_000_000

_CARD_CSS = """
    .card {
        font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
        font-size: 18px;
        line-height: 1.6;
        color: #1a1a1a;
        background: #ffffff;
        padding: 20px;
        max-width: 700px;
        margin: 0 auto;
    }
    img {
        max-width: 100%;
        border-radius: 8px;
        margin: 12px 0;
        display: block;
    }
    hr#answer {
        border: none;
        border-top: 2px solid #e5e7eb;
        margin: 16px 0;
    }
    .topic-tag {
        font-size: 12px;
        color: #9ca3af;
        margin-bottom: 10px;
    }
    .cloze {
        font-weight: bold;
        color: #2563eb;
    }
"""

NOTE_MODEL = genanki.Model(
    MODEL_ID,
    'NotionToAnki',
    fields=[
        {'name': 'Front'},
        {'name': 'Back'},
    ],
    templates=[
        {
            'name': 'Card 1',
            'qfmt': '{{Front}}',
            'afmt': '{{FrontSide}}<hr id=answer>{{Back}}',
        },
    ],
    css=_CARD_CSS,
)

CLOZE_MODEL = genanki.Model(
    CLOZE_MODEL_ID,
    'NotionToAnki-Cloze',
    fields=[
        {'name': 'Text'},
    ],
    templates=[
        {
            'name': 'Cloze',
            'qfmt': '{{cloze:Text}}',
            'afmt': '{{cloze:Text}}',
        },
    ],
    model_type=1,  # cloze model type
    css=_CARD_CSS,
)


# ------------------------------------------------------------------
# Deck ID generation
# ------------------------------------------------------------------

def _stable_deck_id(deck_path: str) -> int:
    """
    Generate a stable integer ID for a deck path.
    Uses MD5 so the same deck path always produces the same ID across
    processes and machines, preventing Anki duplicates on re-import.
    (Python's built-in hash() is randomised per-process since Python 3.3
    and must not be used for persistent identifiers.)
    """
    digest = hashlib.md5(deck_path.encode()).hexdigest()
    return DECK_ID_BASE + int(digest[:8], 16)


# ------------------------------------------------------------------
# Main builder
# ------------------------------------------------------------------

class DeckBuilder:
    def __init__(self, root_deck_name: str):
        self.root_deck_name = root_deck_name
        self.image_registry = ImageRegistry()
        # deck_path (str) → genanki.Deck
        self._decks: dict[str, genanki.Deck] = {}

    def _get_or_create_deck(self, deck_path: str) -> genanki.Deck:
        if deck_path not in self._decks:
            deck_id = _stable_deck_id(deck_path)
            self._decks[deck_path] = genanki.Deck(deck_id, deck_path)
        return self._decks[deck_path]

    def add_card(self, card: FlashCard) -> None:
        """Convert a FlashCard to a genanki Note and add it to the correct deck."""
        deck = self._get_or_create_deck(card.topic_path)

        if card.card_type == "cloze":
            self._add_cloze_card(deck, card)
        else:
            self._add_basic_card(deck, card)

    def _add_basic_card(self, deck: genanki.Deck, card: FlashCard) -> None:
        """Add a basic front/back card to the deck."""
        front_html = _text_to_html(card.front)
        back_html = _text_to_html(card.back)

        if card.image_path and card.image_side:
            safe_name = self.image_registry.register(card.image_path)
            if safe_name:
                img_tag = f'<img src="{safe_name}" alt="{card.image_alt or ""}">'
                if card.image_side == "front":
                    front_html = img_tag + "<br>" + front_html
                else:
                    back_html = back_html + "<br>" + img_tag

        note = genanki.Note(
            model=NOTE_MODEL,
            fields=[front_html, back_html],
        )
        deck.add_note(note)

    def _add_cloze_card(self, deck: genanki.Deck, card: FlashCard) -> None:
        """Add a cloze deletion card to the deck."""
        text_html = _text_to_html(card.front)  # cloze text is stored in front

        if card.image_path and card.image_side:
            safe_name = self.image_registry.register(card.image_path)
            if safe_name:
                img_tag = f'<img src="{safe_name}" alt="{card.image_alt or ""}">'
                text_html = img_tag + "<br>" + text_html

        note = genanki.Note(
            model=CLOZE_MODEL,
            fields=[text_html],
        )
        deck.add_note(note)

    def add_cards(self, cards: list[FlashCard]) -> None:
        for card in cards:
            self.add_card(card)

    def write_package(self, output_path: str) -> str:
        """
        Write the complete .apkg file to output_path.
        Returns the absolute path of the written file.
        """
        if not self._decks:
            raise ValueError("No cards have been added — cannot write empty package.")

        output_path = os.path.abspath(output_path)
        os.makedirs(os.path.dirname(output_path), exist_ok=True)

        # Copy images to a temp dir for genanki to bundle
        with tempfile.TemporaryDirectory() as tmp_dir:
            media_files = self.image_registry.copy_all_to(tmp_dir)

            package = genanki.Package(list(self._decks.values()))
            package.media_files = media_files
            package.write_to_file(output_path)

        return output_path

    @property
    def deck_count(self) -> int:
        return len(self._decks)

    @property
    def card_count(self) -> int:
        return sum(len(d.notes) for d in self._decks.values())


# ------------------------------------------------------------------
# HTML helpers
# ------------------------------------------------------------------

def _text_to_html(text: str) -> str:
    """
    Convert plain text to safe HTML for Anki card fields.
    Preserves newlines as <br> tags.
    """
    import html
    escaped = html.escape(text)
    return escaped.replace('\n', '<br>')
