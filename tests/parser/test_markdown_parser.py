"""
Unit tests for src/parser/markdown_parser.py

Tests the Notion-exported Markdown parser: heading hierarchy, image extraction,
Notion-specific noise filtering, and edge cases.
"""

import os
import pytest
from src.parser.markdown_parser import parse_markdown_file, TopicNode


# ──────────────────────────────────────────────────────────────────────
# Heading hierarchy
# ──────────────────────────────────────────────────────────────────────


class TestHeadingHierarchy:

    def test_single_h1(self, tmp_md_file):
        path = tmp_md_file("# Title\nSome text about the topic")
        root = parse_markdown_file(path)

        assert len(root.children) == 1
        child = root.children[0]
        assert child.title == "Title"
        assert child.level == 1
        assert "Some text about the topic" in child.full_text

    def test_nested_h1_h2_h3(self, tmp_md_file):
        content = (
            "# Chapter\n"
            "Chapter intro\n"
            "## Section\n"
            "Section content\n"
            "### Subsection\n"
            "Subsection detail\n"
        )
        path = tmp_md_file(content)
        root = parse_markdown_file(path)

        # H1 is child of root
        assert len(root.children) == 1
        h1 = root.children[0]
        assert h1.title == "Chapter"
        assert h1.level == 1

        # H2 is child of H1
        assert len(h1.children) == 1
        h2 = h1.children[0]
        assert h2.title == "Section"
        assert h2.level == 2
        assert h2.parent is h1

        # H3 is child of H2
        assert len(h2.children) == 1
        h3 = h2.children[0]
        assert h3.title == "Subsection"
        assert h3.level == 3
        assert h3.parent is h2
        assert "Subsection detail" in h3.full_text

    def test_skipped_levels_h1_then_h3(self, tmp_md_file):
        content = "# Top\nIntro\n### Deep\nDeep text"
        path = tmp_md_file(content)
        root = parse_markdown_file(path)

        h1 = root.children[0]
        assert h1.title == "Top"
        # H3 should nest under H1 (skipping H2)
        assert len(h1.children) == 1
        h3 = h1.children[0]
        assert h3.title == "Deep"
        assert h3.level == 3
        assert h3.parent is h1

    def test_sibling_headings_same_level(self, tmp_md_file):
        content = "## A\nText A\n## B\nText B"
        path = tmp_md_file(content)
        root = parse_markdown_file(path)

        # Both H2s should be direct children of root (siblings)
        assert len(root.children) == 2
        assert root.children[0].title == "A"
        assert root.children[1].title == "B"
        assert "Text A" in root.children[0].full_text
        assert "Text B" in root.children[1].full_text


# ──────────────────────────────────────────────────────────────────────
# Bold headings (Notion quirk)
# ──────────────────────────────────────────────────────────────────────


class TestBoldHeadings:

    def test_bold_heading_treated_as_h2(self, tmp_md_file):
        content = "**Section Title**\nSome text under the bold section"
        path = tmp_md_file(content)
        root = parse_markdown_file(path)

        assert len(root.children) == 1
        child = root.children[0]
        assert child.title == "Section Title"
        assert child.level == 2
        assert "Some text under the bold section" in child.full_text

    def test_bold_heading_nesting_under_h1(self, tmp_md_file):
        content = "# Main\n**Bold Sub**\nSub content"
        path = tmp_md_file(content)
        root = parse_markdown_file(path)

        h1 = root.children[0]
        assert h1.title == "Main"
        # Bold heading (level 2) should nest under H1
        assert len(h1.children) == 1
        bold = h1.children[0]
        assert bold.title == "Bold Sub"
        assert bold.level == 2
        assert "Sub content" in bold.full_text


# ──────────────────────────────────────────────────────────────────────
# Image extraction
# ──────────────────────────────────────────────────────────────────────


class TestImageExtraction:

    def test_image_extraction_basic(self, tmp_md_file):
        content = "## Topic\n![diagram](photo.png)"
        path = tmp_md_file(content)
        root = parse_markdown_file(path)

        topic = root.children[0]
        assert len(topic.images) == 1
        img = topic.images[0]
        assert img["alt"] == "diagram"
        assert img["path"] == "photo.png"
        # Image doesn't exist on disk — that's fine, we're testing parsing
        assert img["exists"] is False

    def test_image_url_decoded_paths(self, tmp_md_file):
        content = "## Topic\n![img](my%20photo%20100.png)"
        path = tmp_md_file(content)
        root = parse_markdown_file(path)

        topic = root.children[0]
        img = topic.images[0]
        assert img["path"] == "my photo 100.png"

    def test_multiple_images_same_topic(self, tmp_md_file):
        content = (
            "## Topic\n"
            "![first](a.png)\n"
            "Some text\n"
            "![second](b.png)\n"
        )
        path = tmp_md_file(content)
        root = parse_markdown_file(path)

        topic = root.children[0]
        assert len(topic.images) == 2
        assert topic.images[0]["alt"] == "first"
        assert topic.images[1]["alt"] == "second"

    def test_image_with_existing_file(self, tmp_md_file, tmp_path):
        # Create the actual image file so exists=True
        img_file = tmp_path / "real_image.png"
        img_file.write_bytes(b"\x89PNG\r\n")
        content = f"## Topic\n![photo](real_image.png)"
        path = tmp_md_file(content)
        root = parse_markdown_file(path)

        topic = root.children[0]
        assert topic.images[0]["exists"] is True


# ──────────────────────────────────────────────────────────────────────
# Line cleaning (_clean_line exercised via parse_markdown_file)
# ──────────────────────────────────────────────────────────────────────


class TestLineCleaning:

    def test_horizontal_rule_removed(self, tmp_md_file):
        content = "## Topic\n---\nText after rule"
        path = tmp_md_file(content)
        root = parse_markdown_file(path)

        topic = root.children[0]
        assert "---" not in topic.full_text
        assert "Text after rule" in topic.full_text

    def test_table_separator_removed(self, tmp_md_file):
        content = "## Topic\n| --- | :---: |\nActual content"
        path = tmp_md_file(content)
        root = parse_markdown_file(path)

        topic = root.children[0]
        assert "---" not in topic.full_text
        assert "Actual content" in topic.full_text

    def test_empty_table_row_removed(self, tmp_md_file):
        # Parser regex handles 2-column empty rows: "| |"
        content = "## Topic\n| |\nReal data"
        path = tmp_md_file(content)
        root = parse_markdown_file(path)

        topic = root.children[0]
        assert "| |" not in topic.full_text
        assert "Real data" in topic.full_text

    def test_blockquote_stripped(self, tmp_md_file):
        content = "## Topic\n> Important callout text"
        path = tmp_md_file(content)
        root = parse_markdown_file(path)

        topic = root.children[0]
        assert "Important callout text" in topic.full_text
        assert topic.full_text.strip().startswith("Important")  # no '>' prefix

    def test_nested_blockquote_stripped(self, tmp_md_file):
        content = "## Topic\n>> Nested callout"
        path = tmp_md_file(content)
        root = parse_markdown_file(path)

        topic = root.children[0]
        assert "Nested callout" in topic.full_text
        assert ">" not in topic.full_text

    def test_latex_passthrough(self, tmp_md_file):
        content = "## Math\nThe formula is $E = mc^2$ and more"
        path = tmp_md_file(content)
        root = parse_markdown_file(path)

        topic = root.children[0]
        assert "$E = mc^2$" in topic.full_text


# ──────────────────────────────────────────────────────────────────────
# Edge cases
# ──────────────────────────────────────────────────────────────────────


class TestEdgeCases:

    def test_empty_file(self, tmp_md_file):
        path = tmp_md_file("")
        root = parse_markdown_file(path)

        assert len(root.children) == 0
        assert root.has_content is False

    def test_content_before_any_heading(self, tmp_md_file):
        content = "Some intro text\n# Heading\nHeading text"
        path = tmp_md_file(content)
        root = parse_markdown_file(path)

        # Text before any heading goes to root
        assert len(root.text_blocks) > 0
        assert "Some intro text" in root.full_text
        # Heading is still parsed as child
        assert len(root.children) == 1
        assert root.children[0].title == "Heading"

    def test_all_nodes_traversal(self, tmp_md_file):
        content = (
            "# A\n"
            "Text A\n"
            "## B\n"
            "Text B\n"
            "## C\n"
            "Text C\n"
            "### D\n"
            "Text D\n"
        )
        path = tmp_md_file(content)
        root = parse_markdown_file(path)

        nodes = list(root.all_nodes())
        # root + A + B + C + D = 5
        assert len(nodes) == 5
        titles = [n.title for n in nodes]
        # Depth-first: root, A, B, C, D
        assert titles[0] == os.path.splitext(os.path.basename(path))[0]  # root title = filename stem
        assert "A" in titles
        assert "B" in titles
        assert "C" in titles
        assert "D" in titles

    def test_has_content_with_only_images(self, tmp_md_file, tmp_path):
        # A topic with only an image (no text) should still have content
        img_file = tmp_path / "chart.png"
        img_file.write_bytes(b"\x89PNG\r\n")
        content = "## Chart Topic\n![chart](chart.png)"
        path = tmp_md_file(content)
        root = parse_markdown_file(path)

        topic = root.children[0]
        assert topic.has_content is True
        assert len(topic.text_blocks) == 0
        assert len(topic.images) == 1
