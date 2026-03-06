"""
file_walker.py
Walks a Notion export directory and builds a hierarchical deck structure.

Notion exports look like this:
    My Notes/
    ├── Topic A abc123.md
    ├── Topic A abc123/
    │   ├── Sub Topic abc456.md
    │   └── image.png
    └── Topic B abc789.md

We clean up the Notion ID suffixes and mirror the folder structure
as Anki subdecks (e.g. "My Notes::Topic A::Sub Topic")
"""

import os
import re
from dataclasses import dataclass, field
from typing import Optional


# Notion appends a 32-char hex ID to every file/folder name on export
NOTION_ID_PATTERN = re.compile(r'\s+[a-f0-9]{32}$', re.IGNORECASE)


def clean_notion_name(name: str) -> str:
    """Strip the Notion ID suffix from a file or folder name."""
    # Remove extension first if present
    stem, *ext = name.rsplit('.', 1)
    clean = NOTION_ID_PATTERN.sub('', stem).strip()
    return clean if not ext else f"{clean}.{ext[0]}"


def clean_deck_name(name: str) -> str:
    """Return a clean deck name (no extension, no Notion ID)."""
    stem = name.rsplit('.', 1)[0]
    return NOTION_ID_PATTERN.sub('', stem).strip()


@dataclass
class DeckNode:
    """Represents one deck or subdeck, containing notes and child decks."""
    name: str                          # Clean human-readable name
    deck_path: str                     # Full Anki deck path e.g. "Root::Child::Grandchild"
    fs_path: str                       # Absolute filesystem path to this folder
    markdown_files: list[str] = field(default_factory=list)   # Absolute paths to .md files
    image_files: list[str] = field(default_factory=list)      # Absolute paths to images
    children: list['DeckNode'] = field(default_factory=list)  # Sub-decks

    def all_nodes(self):
        """Yield self and all descendants (depth-first)."""
        yield self
        for child in self.children:
            yield from child.all_nodes()


IMAGE_EXTENSIONS = {'.png', '.jpg', '.jpeg', '.gif', '.webp', '.svg'}

# Anki doesn't publish a hard limit but deeply nested decks cause UI problems.
# Stop recursing beyond this many levels below the root.
MAX_DECK_DEPTH = 8


def walk_export(root_dir: str) -> DeckNode:
    """
    Entry point. Given the root of a Notion export, return the root DeckNode
    with the full hierarchy populated.
    """
    root_dir = os.path.abspath(root_dir)
    root_name = clean_deck_name(os.path.basename(root_dir))
    return _build_node(root_dir, root_name, root_name, depth=0)


def _build_node(fs_path: str, name: str, deck_path: str, depth: int = 0) -> DeckNode:
    node = DeckNode(name=name, deck_path=deck_path, fs_path=fs_path)

    try:
        entries = sorted(os.listdir(fs_path))
    except PermissionError:
        return node

    # First pass: collect files in this folder
    subdirs = []
    for entry in entries:
        full_path = os.path.join(fs_path, entry)
        if os.path.isfile(full_path):
            ext = os.path.splitext(entry)[1].lower()
            if ext == '.md':
                node.markdown_files.append(full_path)
            elif ext in IMAGE_EXTENSIONS:
                node.image_files.append(full_path)
        elif os.path.isdir(full_path):
            subdirs.append((entry, full_path))

    # Second pass: recurse into subdirectories (subject to depth cap)
    if depth < MAX_DECK_DEPTH:
        for dir_name, dir_path in subdirs:
            child_name = clean_deck_name(dir_name)
            child_deck_path = f"{deck_path}::{child_name}"
            child_node = _build_node(dir_path, child_name, child_deck_path, depth + 1)
            node.children.append(child_node)

    return node


def summarise_tree(node: DeckNode, indent: int = 0) -> str:
    """Debug helper — pretty-print the deck tree."""
    prefix = '  ' * indent
    lines = [f"{prefix}[{node.deck_path}]"]
    lines.append(f"{prefix}  .md files : {len(node.markdown_files)}")
    lines.append(f"{prefix}  images    : {len(node.image_files)}")
    for child in node.children:
        lines.append(summarise_tree(child, indent + 1))
    return '\n'.join(lines)
