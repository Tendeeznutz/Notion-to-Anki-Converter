# Notion → Anki Converter

Convert your Notion notes into Anki flashcards automatically using a local AI — no subscription, no cloud, runs entirely on your machine.

---

## Download

> **No Python required.** Just download and run.

| Platform | Download |
|----------|----------|
| Windows  | [NotionToAnki-windows.exe](#) ← *Release link goes here* |
| macOS    | [NotionToAnki-mac.app](#)     ← *Release link goes here* |

---

## Setup Guide

### Step 1 — Export your notes from Notion

1. Open Notion and go to the page (or workspace) you want to export
2. Click the **`...`** menu in the top-right corner
3. Select **Export**
4. Choose these settings:
   - Format: **Markdown & CSV**
   - ✅ Include subpages
   - ✅ Create folders for subpages
5. Click **Export** and save the ZIP file
6. **Unzip** the downloaded file — you'll point the app at this folder

---

### Step 2 — Install Ollama (the local AI)

Ollama runs AI models on your own computer. It's free and nothing leaves your machine.

1. Go to [ollama.com](https://ollama.com) and download the installer for your OS
2. Install it (like any normal app)
3. Open a terminal and run:

```bash
ollama pull llama3
ollama pull llava
```

- `llama3` is the text model (~4GB) — reads your notes and writes questions
- `llava` is the vision model (~4GB) — understands images/diagrams in your notes

> **Don't have much disk space?** You can skip images in the app settings, then you only need `llama3`.

> **Slow computer?** Try `ollama pull llama3:8b` for a smaller, faster model.

4. Verify Ollama is running — open your browser and go to `http://localhost:11434`. You should see `Ollama is running`.

---

### Step 3 — Run the converter

1. Open **NotionToAnki** (the app you downloaded in Step 1)
2. Check the **Ollama status** at the bottom — it should say `● Running`
3. Click **Browse** next to *Export Folder* and select your unzipped Notion export
4. Choose where to save the output `.apkg` file
5. Click **Convert**
6. Wait for it to finish — this can take a few minutes depending on how many notes you have

---

### Step 4 — Import into Anki

1. Make sure [Anki](https://apps.ankiweb.net/) is installed
2. **Double-click** the `.apkg` file that was created
3. Anki will open and import all your cards automatically
4. Your cards will be organized into decks that mirror your Notion folder structure

---

## Frequently Asked Questions

**Q: The Ollama status shows "Not ready" even though I installed it.**
A: Make sure Ollama is actually running. On Mac/Windows it should appear in your system tray. You can also start it manually by running `ollama serve` in a terminal.

**Q: The conversion is very slow.**
A: The AI processes each topic one at a time. Larger exports will take longer. You can speed it up by using a smaller model (`llama3:8b` instead of `llama3`) or by enabling **Skip images** in settings.

**Q: My images aren't showing up on the cards.**
A: Make sure you exported from Notion with *Create folders for subpages* enabled — this is what keeps images bundled with their notes. Also check that `llava` is installed (`ollama pull llava`).

**Q: I get an error about "invalid JSON".**
A: This occasionally happens when the AI gives a malformed response. Try running the conversion again — it's usually a one-off issue. If it keeps happening, try switching to `llama3:8b` as it tends to follow JSON instructions more reliably.

**Q: Can I use a different AI model?**
A: Yes! In the app settings, type any model name from [ollama.com/library](https://ollama.com/library). Just make sure you've pulled it first with `ollama pull <model-name>`.

---

## For Developers

```bash
git clone https://github.com/yourusername/notion-to-anki
cd notion-to-anki
pip install -r requirements.txt
python src/main.py
```

### Project Structure

```
notion-to-anki/
├── src/
│   ├── main.py                      # GUI entry point (CustomTkinter)
│   ├── converter.py                 # Main orchestration pipeline
│   ├── parser/
│   │   ├── file_walker.py           # Walk Notion export folder structure
│   │   └── markdown_parser.py       # Parse .md files into topic trees
│   ├── llm/
│   │   ├── ollama_client.py         # Ollama REST API wrapper
│   │   └── text_processor.py        # Flashcard generation prompts
│   ├── anki/
│   │   └── deck_builder.py          # genanki .apkg assembly
│   └── utils/
│       └── image_utils.py           # Image hashing, renaming, registry
├── requirements.txt
└── README.md
```

### Building Distributables

```bash
pip install pyinstaller
pyinstaller --onefile --windowed --name NotionToAnki src/main.py
```

Output will be in `dist/`.

---

## License

MIT
