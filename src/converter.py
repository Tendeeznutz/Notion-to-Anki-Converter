"""
converter.py
Main orchestration pipeline.

Ties together:
  file_walker → markdown_parser → text_processor (LLM) → deck_builder → .apkg

Usage:
    converter = Converter(
        export_dir="~/Downloads/My Notion Export",
        output_path="~/Desktop/my_notes.apkg",
        text_model="llama3",
        vision_model="llava",
    )
    converter.run(on_progress=print)
"""

import concurrent.futures
import os
import threading
from dataclasses import dataclass, field
from typing import Callable, Optional

from .parser.file_walker import walk_export, DeckNode
from .parser.markdown_parser import parse_markdown_file, TopicNode
from .llm.ollama_client import OllamaClient, OllamaError
from .llm.text_processor import (
    FlashCard,
    build_cards_from_topic,
    build_cards_from_topic_with_image,
)
from .anki.deck_builder import DeckBuilder


ProgressCallback = Callable[[str], None]
StepCallback = Callable[[int, int], None]   # (current, total)

MAX_IMAGE_SIZE_MB = 5   # Images larger than this skip the vision call


@dataclass
class ConversionResult:
    output_path: str
    total_cards: int
    total_decks: int
    skipped_topics: int
    errors: list[str] = field(default_factory=list)


class Converter:
    def __init__(
        self,
        export_dir: str,
        output_path: str,
        text_model: str = "llama3",
        vision_model: str = "llava",
        max_cards_per_topic: int = 60,
        skip_images: bool = False,
        max_retries: int = 2,
        max_workers: int = 3,
        system_prompt: str = "",
        image_system_prompt: str = "",
    ):
        self.export_dir = os.path.expanduser(export_dir)
        self.output_path = os.path.expanduser(output_path)
        self.max_cards_per_topic = max_cards_per_topic
        self.skip_images = skip_images
        self.max_workers = max_workers
        self.system_prompt = system_prompt
        self.image_system_prompt = image_system_prompt

        self.client = OllamaClient(
            text_model=text_model,
            vision_model=vision_model,
            max_retries=max_retries,
        )

    # ------------------------------------------------------------------
    # Pre-flight checks
    # ------------------------------------------------------------------

    def check_ollama(self) -> tuple[bool, str]:
        """Returns (ok, message). Call this before run() to give the user early feedback."""
        if not self.client.is_running():
            return False, "Ollama is not running. Please start Ollama and try again."

        if not self.client.is_model_available(self.client.text_model):
            return False, (
                f"Text model '{self.client.text_model}' is not installed.\n"
                f"Run: ollama pull {self.client.text_model}"
            )

        if not self.skip_images and not self.client.is_model_available(self.client.vision_model):
            return False, (
                f"Vision model '{self.client.vision_model}' is not installed.\n"
                f"Run: ollama pull {self.client.vision_model}\n"
                f"Or enable 'Skip images' in settings."
            )

        return True, "Ollama is ready."

    # ------------------------------------------------------------------
    # Main pipeline
    # ------------------------------------------------------------------

    def run(
        self,
        on_progress: Optional[ProgressCallback] = None,
        on_step: Optional[StepCallback] = None,
    ) -> ConversionResult:
        def log(msg: str):
            if on_progress:
                on_progress(msg)

        errors: list[str] = []
        skipped = 0

        # Step 1: Walk the export directory
        log(f"Scanning export directory: {self.export_dir}")
        root_node = walk_export(self.export_dir)
        log(f"Found deck structure with root: '{root_node.name}'")

        builder = DeckBuilder(root_deck_name=root_node.name)

        # Step 2: Process each deck node
        all_nodes = list(root_node.all_nodes())
        total_nodes = len(all_nodes)

        for i, deck_node in enumerate(all_nodes, 1):
            log(f"[{i}/{total_nodes}] Processing deck: {deck_node.deck_path}")

            # Step 3: Parse each markdown file in this deck
            for md_path in deck_node.markdown_files:
                log(f"  Parsing: {os.path.basename(md_path)}")
                try:
                    topic_tree = parse_markdown_file(md_path)
                except Exception as e:
                    msg = f"  Error parsing {md_path}: {e}"
                    log(msg)
                    errors.append(msg)
                    continue

                # Step 4: Generate cards for each topic node
                cards = self._process_topic_tree(
                    topic_tree, deck_node.deck_path, log, errors
                )
                skipped += sum(
                    1 for node in topic_tree.all_nodes()
                    if node.has_content and not any(
                        c.topic_path.endswith(node.title) for c in cards
                    )
                )
                builder.add_cards(cards)

            if on_step:
                on_step(i, total_nodes)

        log(f"Generated {builder.card_count} cards across {builder.deck_count} decks.")

        # Step 5: Write .apkg
        log(f"Writing package to: {self.output_path}")
        try:
            output = builder.write_package(self.output_path)
        except ValueError as e:
            errors.append(str(e))
            log(f"Error: {e}")
            return ConversionResult(
                output_path="",
                total_cards=0,
                total_decks=0,
                skipped_topics=skipped,
                errors=errors,
            )

        log("Done!")
        return ConversionResult(
            output_path=output,
            total_cards=builder.card_count,
            total_decks=builder.deck_count,
            skipped_topics=skipped,
            errors=errors,
        )

    # ------------------------------------------------------------------
    # Topic processing
    # ------------------------------------------------------------------

    def _process_topic_tree(
        self,
        root: TopicNode,
        deck_path: str,
        log: ProgressCallback,
        errors: list[str],
    ) -> list[FlashCard]:
        """Process all nodes in a topic tree with concurrent LLM calls."""
        # Collect all content-bearing nodes with their deck paths and original order
        work_items: list[tuple[int, TopicNode, str]] = []
        for idx, node in enumerate(root.all_nodes()):
            if not node.has_content:
                continue
            topic_deck = f"{deck_path}::{node.title}" if node.title != root.title else deck_path
            work_items.append((idx, node, topic_deck))

        if not work_items:
            return []

        # Collect results in a thread-safe manner, preserving document order
        results: list[tuple[int, list[FlashCard]]] = []
        results_lock = threading.Lock()
        errors_lock = threading.Lock()

        def process_one(item: tuple[int, TopicNode, str]) -> None:
            idx, node, topic_deck = item
            local_errors: list[str] = []
            cards = self._process_single_topic(node, topic_deck, log, local_errors)
            with results_lock:
                results.append((idx, cards))
            if local_errors:
                with errors_lock:
                    errors.extend(local_errors)

        with concurrent.futures.ThreadPoolExecutor(
            max_workers=self.max_workers
        ) as executor:
            futures = {
                executor.submit(process_one, item): item
                for item in work_items
            }
            for future in concurrent.futures.as_completed(futures):
                try:
                    future.result()
                except Exception as exc:
                    _, node, _ = futures[future]
                    msg = f"    Unexpected error processing '{node.title}': {exc}"
                    log(msg)
                    with errors_lock:
                        errors.append(msg)

        # Sort by original document order and flatten
        results.sort(key=lambda r: r[0])
        all_cards: list[FlashCard] = []
        for _, cards in results:
            all_cards.extend(cards)

        return all_cards

    def _process_single_topic(
        self,
        node: TopicNode,
        deck_path: str,
        log: ProgressCallback,
        errors: list[str],
    ) -> list[FlashCard]:
        """Process one TopicNode — either text-only or with image."""
        cards = []

        # Case 1: Node has text AND an image
        if node.text_blocks and node.images and not self.skip_images:
            # Use the first valid image associated with this topic
            for img in node.images:
                if not img.get("exists"):
                    continue

                img_path = img['abs_path']
                size_mb = os.path.getsize(img_path) / (1024 * 1024)

                if size_mb > MAX_IMAGE_SIZE_MB:
                    log(f"    ⚠ Skipping vision for '{node.title}': "
                        f"{os.path.basename(img_path)} is {size_mb:.1f} MB "
                        f"(limit {MAX_IMAGE_SIZE_MB} MB) — using text-only")
                    try:
                        cards = build_cards_from_topic(
                            topic_title=node.title,
                            topic_text=node.full_text,
                            deck_path=deck_path,
                            client=self.client,
                            max_cards=self.max_cards_per_topic,
                            log=log,
                            system_prompt=self.system_prompt,
                        )
                    except OllamaError as e:
                        msg = f"    LLM error for '{node.title}': {e}"
                        log(msg)
                        errors.append(msg)
                else:
                    log(f"    → Generating cards with image: {os.path.basename(img_path)}")
                    try:
                        cards = build_cards_from_topic_with_image(
                            topic_title=node.title,
                            topic_text=node.full_text,
                            deck_path=deck_path,
                            image_path=img_path,
                            image_alt=img.get('alt', ''),
                            client=self.client,
                            max_cards=self.max_cards_per_topic,
                            log=log,
                            system_prompt=self.system_prompt,
                            image_system_prompt=self.image_system_prompt,
                        )
                    except OllamaError as e:
                        msg = f"    Vision error for '{node.title}': {e}"
                        log(msg)
                        errors.append(msg)
                break  # Only process the first image per topic for now

        # Case 2: Text only (or images skipped)
        elif node.text_blocks:
            log(f"    → Generating cards for: {node.title}")
            try:
                cards = build_cards_from_topic(
                    topic_title=node.title,
                    topic_text=node.full_text,
                    deck_path=deck_path,
                    client=self.client,
                    max_cards=self.max_cards_per_topic,
                    log=log,
                    system_prompt=self.system_prompt,
                )
            except OllamaError as e:
                msg = f"    LLM error for '{node.title}': {e}"
                log(msg)
                errors.append(msg)

        return cards
