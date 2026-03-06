"""
markdown_parser.py
Parses a Notion-exported Markdown file into a structured topic tree.

Each heading becomes a TopicNode. Text and images that appear under a heading
are attached to that node. This lets us associate images with their topic
confidently before sending anything to the LLM.

Example input:
    # Biology Notes
    ## Photosynthesis
    Plants convert sunlight into glucose.
    ![diagram](photosynthesis.png)
    ### Light Reactions
    Occur in the thylakoid membrane.

Example output:
    TopicNode("Biology Notes")
    └── TopicNode("Photosynthesis")
            text: "Plants convert sunlight into glucose."
            images: ["photosynthesis.png"]
        └── TopicNode("Light Reactions")
                text: "Occur in the thylakoid membrane."
"""

import os
import re
from dataclasses import dataclass, field
from typing import Optional
from urllib.parse import unquote


IMAGE_RE = re.compile(r'!\[([^\]]*)\]\(([^)]+)\)')
HEADING_RE = re.compile(r'^(#{1,6})\s+(.*)')
# Notion often exports section titles as a standalone bold paragraph (**text**)
# rather than a Markdown heading.  Treat these as level-2 headings so each
# section becomes its own TopicNode instead of all content collapsing into root.
BOLD_HEADING_RE = re.compile(r'^\*\*(.+?)\*\*\s*$')


@dataclass
class TopicNode:
    """One heading-level topic with associated content."""
    title: str
    level: int                                  # 1-6 (H1-H6)
    text_blocks: list[str] = field(default_factory=list)   # Raw text paragraphs
    images: list[dict] = field(default_factory=list)       # [{"alt": ..., "path": ..., "abs_path": ...}]
    children: list['TopicNode'] = field(default_factory=list)
    parent: Optional['TopicNode'] = field(default=None, repr=False)

    @property
    def full_text(self) -> str:
        return '\n\n'.join(self.text_blocks)

    @property
    def has_content(self) -> bool:
        return bool(self.text_blocks or self.images)

    def all_nodes(self):
        """Yield self and all descendants depth-first."""
        yield self
        for child in self.children:
            yield from child.all_nodes()

    def __repr__(self):
        return (f"TopicNode(level={self.level}, title={self.title!r}, "
                f"text_blocks={len(self.text_blocks)}, images={len(self.images)}, "
                f"children={len(self.children)})")


def parse_markdown_file(md_path: str) -> TopicNode:
    """
    Parse a Markdown file and return a root TopicNode.
    The root node title is the filename stem; all headings become children.
    """
    md_path = os.path.abspath(md_path)
    base_dir = os.path.dirname(md_path)
    stem = os.path.splitext(os.path.basename(md_path))[0]

    with open(md_path, 'r', encoding='utf-8') as f:
        content = f.read()

    root = TopicNode(title=stem, level=0)
    _parse_content(content, base_dir, root)
    return root


def _parse_content(content: str, base_dir: str, root: TopicNode) -> None:
    """
    Walk through lines and build the topic tree.
    Text and images are attached to the most recently seen heading.
    """
    lines = content.splitlines()

    # Stack tracks the current ancestor chain by heading level
    # stack[-1] is always the current node we're appending content to
    stack: list[TopicNode] = [root]
    current_text_lines: list[str] = []

    def flush_text():
        """Commit buffered text lines to the current node."""
        text = '\n'.join(current_text_lines).strip()
        if text:
            stack[-1].text_blocks.append(text)
        current_text_lines.clear()

    for line in lines:
        stripped = line.strip()
        heading_match = HEADING_RE.match(line)
        bold_match = None if heading_match else BOLD_HEADING_RE.match(stripped)

        if heading_match:
            flush_text()
            level = len(heading_match.group(1))
            title = heading_match.group(2).strip()

            new_node = TopicNode(title=title, level=level)

            # Pop stack until we find the right parent
            while len(stack) > 1 and stack[-1].level >= level:
                stack.pop()

            parent = stack[-1]
            new_node.parent = parent
            parent.children.append(new_node)
            stack.append(new_node)

        elif bold_match:
            # Standalone **bold** line — treat as a level-2 section heading.
            # Notion frequently exports section titles this way instead of using #.
            flush_text()
            title = bold_match.group(1).strip()
            level = 2  # Equivalent to H2 within the page

            new_node = TopicNode(title=title, level=level)

            while len(stack) > 1 and stack[-1].level >= level:
                stack.pop()

            parent = stack[-1]
            new_node.parent = parent
            parent.children.append(new_node)
            stack.append(new_node)

        else:
            # Check for inline images
            image_matches = IMAGE_RE.findall(line)
            if image_matches:
                flush_text()
                for alt, img_path in image_matches:
                    # Decode URL-encoded paths (Notion uses %20 for spaces)
                    img_path_decoded = unquote(img_path)
                    abs_path = os.path.normpath(os.path.join(base_dir, img_path_decoded))
                    stack[-1].images.append({
                        "alt": alt,
                        "path": img_path_decoded,         # Relative as written in .md
                        "abs_path": abs_path,             # Absolute path on disk
                        "exists": os.path.isfile(abs_path)
                    })
            else:
                # Regular text line — strip Notion-specific noise
                cleaned = _clean_line(line)
                if cleaned is not None:
                    current_text_lines.append(cleaned)

    flush_text()


def _clean_line(line: str) -> Optional[str]:
    """
    Remove or normalise Notion-specific Markdown noise.
    Returns None to drop the line entirely.

    Handled cases:
    - Horizontal rules (---) → dropped
    - Empty table rows (| | |) → dropped
    - Table separator rows (| --- | :---: |) → dropped
    - Callout/blockquote lines (> text) → '>' prefix stripped, content kept
    - Toggle lists → already plain list items in Notion export, no change needed
    - Inline LaTeX ($...$) → passed through as-is for the LLM to handle
    """
    stripped = line.strip()

    # Drop horizontal rules
    if re.match(r'^-{3,}$', stripped):
        return None

    # Drop empty table rows (e.g. "| | |")
    if re.match(r'^\|\s*\|\s*$', stripped):
        return None

    # Drop table separator rows (e.g. "| --- | :---: | ---: |")
    if re.match(r'^\|(\s*:?-+:?\s*\|)+$', stripped):
        return None

    # Strip callout/blockquote prefix — Notion exports callout blocks as "> text".
    # We keep the content but discard the marker so it reads as plain text.
    if stripped.startswith('>'):
        inner = re.sub(r'^>+\s*', '', stripped)
        return inner if inner else None

    return line


def summarise_tree(node: TopicNode, indent: int = 0) -> str:
    """Debug helper — pretty-print the topic tree."""
    prefix = '  ' * indent
    lines = [f"{prefix}H{node.level} {node.title!r}  "
             f"(text_blocks={len(node.text_blocks)}, images={len(node.images)})"]
    for child in node.children:
        lines.append(summarise_tree(child, indent + 1))
    return '\n'.join(lines)
