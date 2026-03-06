"""
image_utils.py
Utilities for handling images before they go into an Anki package.

Anki's media folder has strict rules:
  - No subdirectories (all files must be flat in the media folder)
  - Filenames must be unique
  - Special characters can cause issues on some platforms

We solve this by renaming every image to a deterministic slug based on its
content hash. This also handles Notion's habit of exporting duplicate images
with different names.
"""

import hashlib
import os
import re
import shutil
from typing import Optional


# Characters that are safe in Anki media filenames
SAFE_CHARS = re.compile(r'[^a-zA-Z0-9_\-]')

# Image extensions Anki supports
SUPPORTED_EXTENSIONS = {'.png', '.jpg', '.jpeg', '.gif', '.webp'}


def get_image_hash(image_path: str, length: int = 12) -> str:
    """Return a short MD5 hash of the image file contents."""
    h = hashlib.md5()
    with open(image_path, 'rb') as f:
        for chunk in iter(lambda: f.read(8192), b''):
            h.update(chunk)
    return h.hexdigest()[:length]


def safe_anki_filename(image_path: str) -> Optional[str]:
    """
    Generate a safe, unique filename for an image to use inside Anki's media folder.
    Returns None if the file doesn't exist or has an unsupported extension.

    Example:
        /path/to/Photosynthesis Diagram abc123.png
        → photosynthesis_diagram_a1b2c3d4e5f6.png
    """
    if not os.path.isfile(image_path):
        return None

    ext = os.path.splitext(image_path)[1].lower()
    if ext not in SUPPORTED_EXTENSIONS:
        return None

    stem = os.path.splitext(os.path.basename(image_path))[0]

    # Slugify the stem
    slug = stem.lower()
    slug = SAFE_CHARS.sub('_', slug)
    slug = re.sub(r'_+', '_', slug).strip('_')
    slug = slug[:40]  # Keep it reasonably short

    content_hash = get_image_hash(image_path)
    return f"{slug}_{content_hash}{ext}"


class ImageRegistry:
    """
    Tracks all images that will be bundled into the .apkg file.

    Maps original absolute paths → safe Anki media filenames.
    Deduplicates by content hash so the same image exported multiple times
    by Notion only appears once in the package.
    """

    def __init__(self):
        # abs_path → safe_filename
        self._path_to_filename: dict[str, str] = {}
        # content_hash → safe_filename (for deduplication)
        self._hash_to_filename: dict[str, str] = {}

    def register(self, abs_path: str) -> Optional[str]:
        """
        Register an image and return its Anki-safe filename.
        Returns None if the image is invalid or unsupported.
        """
        if abs_path in self._path_to_filename:
            return self._path_to_filename[abs_path]

        if not os.path.isfile(abs_path):
            print(f"[ImageRegistry] File not found: {abs_path}")
            return None

        ext = os.path.splitext(abs_path)[1].lower()
        if ext not in SUPPORTED_EXTENSIONS:
            print(f"[ImageRegistry] Unsupported extension: {abs_path}")
            return None

        content_hash = get_image_hash(abs_path)

        # Deduplication: if we've seen this content before, reuse the filename
        if content_hash in self._hash_to_filename:
            safe_name = self._hash_to_filename[content_hash]
            self._path_to_filename[abs_path] = safe_name
            return safe_name

        safe_name = safe_anki_filename(abs_path)
        if safe_name is None:
            return None

        self._path_to_filename[abs_path] = safe_name
        self._hash_to_filename[content_hash] = safe_name
        return safe_name

    def copy_all_to(self, dest_dir: str) -> list[str]:
        """
        Copy all registered images to dest_dir with their safe filenames.
        Returns a list of destination file paths (for genanki media_files).
        """
        os.makedirs(dest_dir, exist_ok=True)
        copied = []
        seen_hashes = set()

        for abs_src, safe_name in self._path_to_filename.items():
            # Avoid copying the same content twice
            content_hash = get_image_hash(abs_src)
            if content_hash in seen_hashes:
                continue
            seen_hashes.add(content_hash)

            dest = os.path.join(dest_dir, safe_name)
            shutil.copy2(abs_src, dest)
            copied.append(dest)

        return copied

    def get_filename(self, abs_path: str) -> Optional[str]:
        """Retrieve the registered safe filename for an original path."""
        return self._path_to_filename.get(abs_path)

    @property
    def count(self) -> int:
        return len(self._hash_to_filename)
