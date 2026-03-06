# Notion → Anki Converter — Project Briefing

## What This Project Is
A cross-platform desktop application (Windows + Mac) that converts Notion note exports into Anki flashcard packages (`.apkg`). It runs entirely locally — no cloud APIs, no subscriptions. The AI layer is powered by **Ollama**, which runs LLMs on the user's own machine.

---

## How It Works (Pipeline)
1. User exports their Notion workspace as **Markdown & CSV** (with subpages + folders)
2. The app walks the export folder — each subfolder becomes an **Anki subdeck**
3. Each `.md` file is parsed into a **topic tree** based on heading hierarchy (`#`, `##`, `###`)
4. Images in the Markdown are **positionally associated** to their nearest heading/topic
5. Each topic's text is sent to **Ollama (llama3)** → generates Q&A flashcards as JSON
6. Topics with images are sent to **Ollama (llava, a vision model)** → decides if the image goes on the front or back of the card
7. Everything is assembled into a `.apkg` file using **genanki**, with images bundled inside
8. User double-clicks the `.apkg` → Anki imports all cards with deck structure intact

---

## Tech Stack
| Concern | Choice |
|---|---|
| Language | Python 3.11+ |
| GUI | CustomTkinter |
| Anki output | `genanki` |
| Markdown parsing | Custom parser (stdlib only) |
| LLM (text) | Ollama local API → `llama3` |
| LLM (vision/images) | Ollama local API → `llava` |
| Distribution | PyInstaller → `.exe` / `.app` |

---

## Current File Structure
```
notion-to-anki/
├── src/
│   ├── main.py                  # CustomTkinter GUI entry point
│   ├── converter.py             # Main orchestration pipeline
│   ├── parser/
│   │   ├── __init__.py
│   │   ├── file_walker.py       # Walk export folder → DeckNode tree
│   │   └── markdown_parser.py   # Parse .md files → TopicNode tree
│   ├── llm/
│   │   ├── __init__.py
│   │   ├── ollama_client.py     # Ollama REST API wrapper (text + vision)
│   │   └── text_processor.py   # Prompt logic → returns FlashCard objects
│   ├── anki/
│   │   ├── __init__.py
│   │   └── deck_builder.py     # genanki assembly → writes .apkg
│   └── utils/
│       ├── __init__.py
│       └── image_utils.py      # Image dedup, hashing, safe renaming
├── requirements.txt             # genanki, customtkinter, requests
└── README.md                    # User-facing setup guide
```

---

## What Still Needs To Be Done

### 1. Fix `__init__.py` files
The `src/` package init files were created incorrectly (one file with a bad name instead of one per directory). Create empty `__init__.py` files in:
- `src/`
- `src/parser/`
- `src/llm/`
- `src/anki/`
- `src/utils/`

### 2. Fix imports in `converter.py`
Currently uses relative imports (e.g. `from .parser.file_walker import ...`). These need to be verified and corrected so the app runs both as a package and as a standalone PyInstaller binary.

### 3. End-to-end integration test
Run the full pipeline against a real Notion Markdown export and verify:
- Folder structure correctly becomes Anki subdeck hierarchy
- Images found in Markdown are correctly paired to their topic
- Ollama returns valid JSON for both text and vision prompts
- `.apkg` file opens correctly in Anki with cards and images intact

### 4. Prompt tuning (`text_processor.py`)
The system prompts in `text_processor.py` need real-world testing. Key things to validate:
- Cards are atomic (one concept per card)
- JSON output is consistent and parseable (models sometimes wrap in markdown fences — already handled, but needs stress testing)
- Vision prompt correctly identifies when an image should be front vs back
- Graceful fallback when `llava` gives a bad response (falls back to text-only — already coded, verify it works)

### 5. Handle Notion export edge cases in the parser
Notion exports have quirks that will surface with real data:
- **Database pages** export with extra CSV files and property rows — these should be skipped
- **Callout blocks** export as blockquotes (`> text`) — strip or handle them
- **Toggle lists** export as nested lists — should be treated as regular text
- **Inline equations** export as LaTeX — decide whether to pass through or strip
- **Nested pages** can be very deeply nested — verify the deck path doesn't get too long for Anki

### 6. GUI polish (`main.py`)
- Add a model **auto-detect dropdown** — ping `ollama /api/tags` on startup and populate available models
- Show a **per-file progress indicator** not just a spinner
- Add an **estimated time remaining** display
- Add a **"Open in Anki"** button after successful conversion (uses `os.startfile` on Windows, `open` on Mac)

### 7. PyInstaller build + GitHub Actions
- Write a `build.spec` file for PyInstaller that correctly bundles CustomTkinter assets
- Create `.github/workflows/build.yml` that:
  - Triggers on version tags (`v*`)
  - Builds on `windows-latest` and `macos-latest` runners
  - Attaches the `.exe` and `.app` as release assets

### 8. Onboarding flow for first-time users
If Ollama is not detected on startup, show a **setup wizard** modal that:
- Links to the Ollama download page
- Has a "Check Again" button that re-pings `localhost:11434`
- Offers to run `ollama pull llama3` and `ollama pull llava` automatically via `subprocess`, with a live progress stream in the UI

---

## Key Design Decisions to Keep In Mind
- **Images are associated by position in the Markdown**, not by LLM — the LLM only decides how to *use* the image on a card, not which topic it belongs to
- **All image filenames are renamed** to a safe slug + MD5 hash before bundling — this handles Notion's duplicate image exports and special characters
- **Deck IDs are hash-stable** — re-importing an updated `.apkg` updates existing cards rather than creating duplicates in Anki
- **Errors are non-fatal** — if one topic fails (bad LLM response, missing image), the rest of the conversion continues and errors are logged
- **`skip_images` toggle** exists for users with weaker hardware who don't want to run `llava`