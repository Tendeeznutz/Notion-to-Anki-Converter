"""
text_processor.py
Sends topic text to Ollama and receives structured flashcard data back.

Each TopicNode with text gets converted into one or more FlashCard objects.
The LLM decides how many cards to generate based on content density.
"""

import json
from dataclasses import dataclass, field
from typing import Callable, Optional

from .ollama_client import OllamaClient, OllamaError

LogCallback = Optional[Callable[[str], None]]


@dataclass
class FlashCard:
    """Intermediate representation of a single flashcard before Anki packaging."""
    front: str
    back: str
    topic_path: str                         # e.g. "Biology::Photosynthesis::Light Reactions"
    image_path: Optional[str] = None        # Absolute path to image file, if any
    image_side: Optional[str] = None        # "front" | "back" | None
    image_alt: Optional[str] = None         # Alt text / description of the image
    card_type: str = "basic"                # "basic" | "cloze"


SYSTEM_PROMPT = """You are an expert study assistant that converts lecture notes into \
Anki flashcards.

RULES (follow every one):
1. "front" MUST be a question or prompt — never a statement or the answer itself.
2. "back" MUST be the answer to that question — never repeat the front text.
3. front and back must always be DIFFERENT from each other.
4. Test ONE specific concept per card (atomic cards).
5. Answers should be 1–3 sentences maximum.
6. Avoid yes/no questions — prefer "What is…", "How does…", "Why…", "Explain…"
7. For definitions: front = term, back = definition.
8. For processes: front = "What are the steps of X?", back = the steps.
9. For comparisons: create one card per concept being compared.

BAD example (DO NOT do this):
  front: "HTTP is a stateless protocol."
  back:  "HTTP is a stateless protocol."

GOOD example:
  front: "What does it mean that HTTP is stateless?"
  back:  "The server does not retain any information about previous client requests; \
each request is independent."

Always respond with valid JSON only — no explanation, no markdown fences."""


def build_cards_from_topic(
    topic_title: str,
    topic_text: str,
    deck_path: str,
    client: OllamaClient,
    max_cards: int = 8,
    log: LogCallback = None,
    system_prompt: str = "",
) -> list[FlashCard]:
    """
    Ask Ollama to generate flashcards from a block of topic text.
    Returns a list of FlashCard objects.

    If system_prompt is provided, it overrides the built-in SYSTEM_PROMPT.
    """
    def _log(msg: str):
        if log:
            log(msg)

    if not topic_text.strip():
        return []

    prompt = _build_text_prompt(topic_title, topic_text, max_cards)
    effective_system = system_prompt if system_prompt else SYSTEM_PROMPT

    try:
        result = client.generate_json(prompt, system=effective_system)
    except OllamaError as e:
        _log(f"    ⚠ Skipping '{topic_title}': {e}")
        return []

    if not isinstance(result, list):
        _log(f"    ⚠ Unexpected response format for '{topic_title}' — skipping")
        return []

    cards = []
    for item in result:
        if not isinstance(item, dict):
            continue

        # Cloze card: {"type": "cloze", "text": "{{c1::...}} ..."}
        if item.get("type") == "cloze":
            cloze_text = item.get("text", "").strip()
            if cloze_text:
                cards.append(FlashCard(
                    front=cloze_text,
                    back="",
                    topic_path=deck_path,
                    card_type="cloze",
                ))
            continue

        # Basic card: {"front": "...", "back": "..."}
        front = item.get("front", "").strip()
        back = item.get("back", "").strip()
        if not front or not back:
            continue
        # Reject cards where the model mirrored the same text into both fields.
        if front.lower() == back.lower():
            if log:
                log(f"    ⚠ Dropped card with identical front/back in '{topic_title}'")
            continue
        cards.append(FlashCard(
            front=front,
            back=back,
            topic_path=deck_path,
        ))

    return cards


def _build_text_prompt(title: str, text: str, max_cards: int) -> str:
    return f"""Convert the following study notes into Anki flashcards.

Topic: {title}

Notes:
{text}

Instructions:
- Generate between 1 and {max_cards} flashcards based on how much testable content exists.
- Each "front" must be a QUESTION. Each "back" must be the ANSWER to that question.
- front and back must NEVER contain the same text.
- Do not create trivial or duplicate cards.

Respond ONLY with a JSON array — no other text:
[
  {{
    "front": "Question about one concept from the notes",
    "back": "Concise answer, 1-3 sentences"
  }}
]"""


# ------------------------------------------------------------------
# Image-aware card generation
# ------------------------------------------------------------------

IMAGE_SYSTEM_PROMPT = """You are an expert study assistant converting notes and diagrams \
into Anki flashcards.

RULES (follow every one):
1. "front" MUST be a question or prompt — never a statement.
2. "back" MUST be the answer — it must be DIFFERENT from the front text.
3. front and back must NEVER contain the same text.
4. Test ONE concept per card.
5. When the image adds educational value, set "uses_image": true and pick \
"image_side": "front" (image IS the question) or "back" (image illustrates the answer).

BAD example (DO NOT do this):
  front: "HTTP GET retrieves static or dynamic content."
  back:  "HTTP GET retrieves static or dynamic content."

GOOD example:
  front: "What is the purpose of the HTTP GET method?"
  back:  "GET retrieves static or dynamic content from the server; \
arguments for dynamic content are passed in the URI."

Respond ONLY with valid JSON — no explanation, no markdown fences."""


def build_cards_from_topic_with_image(
    topic_title: str,
    topic_text: str,
    deck_path: str,
    image_path: str,
    image_alt: str,
    client: OllamaClient,
    max_cards: int = 8,
    log: LogCallback = None,
    system_prompt: str = "",
    image_system_prompt: str = "",
) -> list[FlashCard]:
    """
    Generate flashcards for a topic that has an associated image.
    Uses the vision model to understand the image's educational role.

    If image_system_prompt is provided, it overrides the built-in IMAGE_SYSTEM_PROMPT.
    If system_prompt is provided, it's used for the text-only fallback path.
    """
    def _log(msg: str):
        if log:
            log(msg)

    prompt = _build_image_prompt(topic_title, topic_text, image_alt, max_cards)
    effective_image_system = image_system_prompt if image_system_prompt else IMAGE_SYSTEM_PROMPT

    try:
        result = client.generate_json_with_image(
            prompt, image_path, system=effective_image_system
        )
    except OllamaError as e:
        _log(f"    ⚠ Vision failed for '{topic_title}', falling back to text-only: {e}")
        return build_cards_from_topic(
            topic_title, topic_text, deck_path, client, max_cards,
            log=log, system_prompt=system_prompt,
        )

    if not isinstance(result, list):
        _log(f"    ⚠ Unexpected image response for '{topic_title}' — skipping")
        return []

    cards = []
    for item in result:
        if not isinstance(item, dict):
            continue

        # Cloze card with image
        if item.get("type") == "cloze":
            cloze_text = item.get("text", "").strip()
            if not cloze_text:
                continue
            uses_image = item.get("uses_image", False)
            img_side = item.get("image_side") if uses_image else None
            cards.append(FlashCard(
                front=cloze_text,
                back="",
                topic_path=deck_path,
                image_path=image_path if uses_image else None,
                image_side=img_side,
                image_alt=image_alt,
                card_type="cloze",
            ))
            continue

        # Basic card with image
        front = item.get("front", "").strip()
        back = item.get("back", "").strip()
        if not front or not back:
            continue
        if front.lower() == back.lower():
            if log:
                log(f"    ⚠ Dropped card with identical front/back in '{topic_title}'")
            continue

        uses_image = item.get("uses_image", False)
        image_side = item.get("image_side") if uses_image else None

        cards.append(FlashCard(
            front=front,
            back=back,
            topic_path=deck_path,
            image_path=image_path if uses_image else None,
            image_side=image_side,
            image_alt=image_alt,
        ))

    return cards


def _build_image_prompt(title: str, text: str, image_alt: str, max_cards: int) -> str:
    alt_hint = f'The image is described as: "{image_alt}"' if image_alt else "No alt text provided."
    return f"""Convert the following study notes into Anki flashcards.
The notes include an image (diagram, chart, or illustration).

Topic: {title}
{alt_hint}

Notes:
{text}

Instructions:
- Generate between 1 and {max_cards} flashcards based on testable content.
- Each "front" must be a QUESTION. Each "back" must be the ANSWER. They must be DIFFERENT.
- For cards that use the image: set "uses_image": true.
  - "image_side": "front"  → the image IS the question (e.g. "What does this diagram show?")
  - "image_side": "back"   → the image illustrates the answer
- For text-only cards: set "uses_image": false (omit image_side).

Respond ONLY with a JSON array — no other text:
[
  {{
    "front": "Question about one concept",
    "back": "Concise answer, 1-3 sentences",
    "uses_image": false
  }}
]"""
