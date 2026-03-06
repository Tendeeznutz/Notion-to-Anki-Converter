"""
main.py
Entry point — launches the CustomTkinter GUI.

Layout:
    ┌─────────────────────────────────────────┐
    │  Notion → Anki Converter                │
    ├─────────────────────────────────────────┤
    │  Export Folder:  [____________] [Browse]│
    │  Output File:    [____________] [Browse]│
    ├─────────────────────────────────────────┤
    │  Text Model:  [llama3    ▼]             │
    │  Vision Model:[llava     ▼]             │
    │  [ ] Skip images                        │
    ├─────────────────────────────────────────┤
    │  Ollama Status: ● Running               │
    ├─────────────────────────────────────────┤
    │    [  Convert  ]  [  Open in Anki  ]    │
    ├─────────────────────────────────────────┤
    │  ░░░░░░░░░░░░░░░░░░░   3/10 — ~2m30s   │
    │  Log output...                          │
    └─────────────────────────────────────────┘
"""

import os
import subprocess
import sys
import threading
import time
import tkinter as tk
from tkinter import filedialog, messagebox
from typing import Optional

# Add the project root (parent of src/) to path so `src` is importable as a package.
# This makes relative imports within src/ work when running `python src/main.py` directly.
_src_dir = os.path.dirname(os.path.abspath(__file__))
_project_root = os.path.dirname(_src_dir)
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

try:
    import customtkinter as ctk
except ImportError:
    print("CustomTkinter not found. Install with: pip install customtkinter")
    sys.exit(1)

from src.converter import Converter
from src.llm.ollama_client import OllamaClient
from src.llm.card_styles import get_style_names, get_style, DEFAULT_STYLE
from src.onboarding import OllamaSetupWizard

ctk.set_appearance_mode("System")
ctk.set_default_color_theme("blue")


class App(ctk.CTk):
    def __init__(self):
        super().__init__()

        self.title("Notion → Anki Converter")
        self.geometry("700x640")
        self.resizable(True, True)
        self.minsize(600, 580)

        self._last_output_path: str = ""
        self._conversion_start: float = 0.0
        self._wizard_shown: bool = False   # only pop the wizard once per session

        # Card style / prompt state
        default = get_style(DEFAULT_STYLE)
        self._custom_system_prompt: str = default.system_prompt
        self._custom_image_prompt: str = default.image_system_prompt

        self._build_ui()
        self._check_ollama_status()

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _build_ui(self):
        self.grid_columnconfigure(0, weight=1)

        pad = {"padx": 20, "pady": 6}

        # Title
        title = ctk.CTkLabel(self, text="Notion → Anki Converter",
                              font=ctk.CTkFont(size=22, weight="bold"))
        title.grid(row=0, column=0, padx=20, sticky="w", pady=(20, 4))

        # Separator
        sep1 = ctk.CTkFrame(self, height=2, fg_color="gray70")
        sep1.grid(row=1, column=0, padx=20, sticky="ew")

        # File selection frame
        file_frame = ctk.CTkFrame(self, fg_color="transparent")
        file_frame.grid(row=2, column=0, **pad, sticky="ew")
        file_frame.grid_columnconfigure(1, weight=1)

        ctk.CTkLabel(file_frame, text="Export Folder:").grid(
            row=0, column=0, sticky="w", pady=4, padx=(0, 10))
        self.export_var = tk.StringVar()
        self.export_entry = ctk.CTkEntry(file_frame, textvariable=self.export_var,
                                         placeholder_text="Select Notion export folder...")
        self.export_entry.grid(row=0, column=1, sticky="ew", padx=(0, 8))
        ctk.CTkButton(file_frame, text="Browse", width=80,
                      command=self._browse_export).grid(row=0, column=2)

        ctk.CTkLabel(file_frame, text="Output Folder:").grid(
            row=1, column=0, sticky="w", pady=4, padx=(0, 10))
        self.output_var = tk.StringVar(value=os.path.expanduser("~/Desktop"))
        self.output_entry = ctk.CTkEntry(file_frame, textvariable=self.output_var,
                                          placeholder_text="Folder where the .apkg will be saved...")
        self.output_entry.grid(row=1, column=1, sticky="ew", padx=(0, 8))
        ctk.CTkButton(file_frame, text="Browse", width=80,
                      command=self._browse_output).grid(row=1, column=2)

        # Settings frame
        settings_frame = ctk.CTkFrame(self)
        settings_frame.grid(row=3, column=0, **pad, sticky="ew")
        settings_frame.grid_columnconfigure((1, 3), weight=1)

        ctk.CTkLabel(settings_frame, text="Text Model:").grid(
            row=0, column=0, padx=(12, 8), pady=8, sticky="w")
        self.text_model_var = tk.StringVar(value="llama3")
        self.text_model_combo = ctk.CTkComboBox(
            settings_frame, variable=self.text_model_var,
            values=["llama3"], width=140,
        )
        self.text_model_combo.grid(row=0, column=1, sticky="w", padx=(0, 20))

        ctk.CTkLabel(settings_frame, text="Vision Model:").grid(
            row=0, column=2, padx=(0, 8), sticky="w")
        self.vision_model_var = tk.StringVar(value="llava")
        self.vision_model_combo = ctk.CTkComboBox(
            settings_frame, variable=self.vision_model_var,
            values=["llava"], width=140,
        )
        self.vision_model_combo.grid(row=0, column=3, sticky="w", padx=(0, 12))

        ctk.CTkLabel(settings_frame, text="Card Style:").grid(
            row=1, column=0, padx=(12, 8), pady=8, sticky="w")
        self.card_style_var = tk.StringVar(value=DEFAULT_STYLE)
        self.card_style_combo = ctk.CTkComboBox(
            settings_frame, variable=self.card_style_var,
            values=get_style_names(), width=140,
            command=self._on_card_style_changed,
        )
        self.card_style_combo.grid(row=1, column=1, sticky="w", padx=(0, 20))

        ctk.CTkButton(settings_frame, text="Edit Prompt", width=110,
                      command=self._open_prompt_editor).grid(
            row=1, column=2, columnspan=2, padx=(0, 12), sticky="w")

        self.skip_images_var = tk.BooleanVar(value=False)
        ctk.CTkCheckBox(settings_frame, text="Skip images (faster, text-only)",
                        variable=self.skip_images_var).grid(
            row=2, column=0, columnspan=4, padx=12, pady=(0, 10), sticky="w")

        # Ollama status
        status_frame = ctk.CTkFrame(self, fg_color="transparent")
        status_frame.grid(row=4, column=0, padx=20, pady=(0, 4), sticky="ew")
        ctk.CTkLabel(status_frame, text="Ollama:").grid(row=0, column=0, padx=(0, 8))
        self.status_label = ctk.CTkLabel(status_frame, text="Checking...", text_color="gray")
        self.status_label.grid(row=0, column=1, sticky="w")
        ctk.CTkButton(status_frame, text="Refresh", width=70, height=24,
                      command=self._check_ollama_status).grid(row=0, column=2, padx=(20, 0))

        # Action buttons row — Convert + Open in Anki side by side
        btn_frame = ctk.CTkFrame(self, fg_color="transparent")
        btn_frame.grid(row=5, column=0, padx=20, pady=8, sticky="ew")
        btn_frame.grid_columnconfigure(0, weight=3)
        btn_frame.grid_columnconfigure(1, weight=2)

        self.convert_btn = ctk.CTkButton(
            btn_frame, text="Convert", height=40,
            font=ctk.CTkFont(size=15, weight="bold"),
            command=self._start_conversion,
        )
        self.convert_btn.grid(row=0, column=0, sticky="ew", padx=(0, 8))

        self.open_anki_btn = ctk.CTkButton(
            btn_frame, text="Show in Folder", height=40,
            state="disabled",
            command=self._show_in_folder,
        )
        self.open_anki_btn.grid(row=0, column=1, sticky="ew")

        # Progress bar + ETA label side by side
        progress_frame = ctk.CTkFrame(self, fg_color="transparent")
        progress_frame.grid(row=6, column=0, padx=20, pady=(0, 2), sticky="ew")
        progress_frame.grid_columnconfigure(0, weight=1)

        self.progress = ctk.CTkProgressBar(progress_frame)
        self.progress.set(0)
        self.progress.grid(row=0, column=0, sticky="ew", padx=(0, 10))

        self.progress_label = ctk.CTkLabel(
            progress_frame, text="", text_color="gray",
            font=ctk.CTkFont(size=11), width=160, anchor="e",
        )
        self.progress_label.grid(row=0, column=1)

        # Log area
        self.log_box = ctk.CTkTextbox(self, height=180, font=ctk.CTkFont(family="Courier", size=12))
        self.log_box.grid(row=7, column=0, padx=20, pady=(0, 20), sticky="nsew")
        self.grid_rowconfigure(7, weight=1)

    # ------------------------------------------------------------------
    # Card style
    # ------------------------------------------------------------------

    def _on_card_style_changed(self, style_name: str):
        """Load the selected preset's prompts into the instance state."""
        style = get_style(style_name)
        self._custom_system_prompt = style.system_prompt
        self._custom_image_prompt = style.image_system_prompt

    def _open_prompt_editor(self):
        """Open a modal dialog for editing the system prompts."""
        if hasattr(self, "_prompt_editor") and self._prompt_editor.winfo_exists():
            self._prompt_editor.lift()
            return
        self._prompt_editor = _PromptEditorDialog(
            self,
            current_style=self.card_style_var.get(),
            system_prompt=self._custom_system_prompt,
            image_system_prompt=self._custom_image_prompt,
            on_apply=self._apply_custom_prompts,
        )

    def _apply_custom_prompts(self, system_prompt: str, image_prompt: str):
        """Callback from the prompt editor dialog."""
        self._custom_system_prompt = system_prompt
        self._custom_image_prompt = image_prompt

    # ------------------------------------------------------------------
    # File dialogs
    # ------------------------------------------------------------------

    def _browse_export(self):
        path = filedialog.askdirectory(title="Select Notion Export Folder")
        if path:
            self.export_var.set(path)

    def _browse_output(self):
        path = filedialog.askdirectory(title="Select Output Folder")
        if path:
            self.output_var.set(path)

    # ------------------------------------------------------------------
    # Ollama status + model dropdown population
    # ------------------------------------------------------------------

    def _check_ollama_status(self, _ollama_ready: Optional[bool] = None):
        """
        Non-blocking status check that also populates model dropdowns.

        May be called directly OR used as the on_dismiss callback from
        OllamaSetupWizard (which passes a bool indicating whether Ollama
        was confirmed ready before the wizard was closed).
        """
        self.status_label.configure(text="Checking...", text_color="gray")

        def check():
            client = OllamaClient(
                text_model=self.text_model_var.get(),
                vision_model=self.vision_model_var.get(),
            )

            if not client.is_running():
                self.after(0, self._update_status, False,
                           "Ollama is not running. Please start Ollama and try again.")
                # Show the setup wizard the very first time we detect Ollama is absent.
                if not self._wizard_shown:
                    self._wizard_shown = True
                    self.after(0, self._show_setup_wizard)
                return

            # Populate dropdowns with all installed models
            try:
                models = client.list_models()
                if models:
                    self.after(0, self._populate_model_dropdowns, models)
            except Exception:
                pass  # Non-fatal — dropdowns keep their defaults

            # Check that the selected models are actually installed
            if not client.is_model_available(client.text_model):
                self.after(0, self._update_status, False,
                           f"Text model '{client.text_model}' not installed. "
                           f"Run: ollama pull {client.text_model}")
                return

            if not self.skip_images_var.get() and \
                    not client.is_model_available(client.vision_model):
                self.after(0, self._update_status, False,
                           f"Vision model '{client.vision_model}' not installed. "
                           f"Run: ollama pull {client.vision_model}")
                return

            self.after(0, self._update_status, True, "Ollama is ready.")

        threading.Thread(target=check, daemon=True).start()

    def _show_setup_wizard(self):
        """Open the first-run Ollama setup wizard as a modal dialog."""
        # Guard: don't stack multiple wizards (e.g. rapid Refresh clicks).
        if hasattr(self, "_wizard") and self._wizard.winfo_exists():
            self._wizard.lift()
            return
        self._wizard = OllamaSetupWizard(
            self,
            on_dismiss=self._check_ollama_status,   # re-check when wizard closes
        )

    def _populate_model_dropdowns(self, models: list[str]):
        """Update both ComboBoxes with the list of installed Ollama models."""
        self.text_model_combo.configure(values=models)
        self.vision_model_combo.configure(values=models)

    def _update_status(self, ok: bool, msg: str):
        if ok:
            self.status_label.configure(text="● Running", text_color="green")
        else:
            self.status_label.configure(text="● Not ready — " + msg.split('\n')[0], text_color="red")

    # ------------------------------------------------------------------
    # Conversion
    # ------------------------------------------------------------------

    def _start_conversion(self):
        export_dir = self.export_var.get().strip()
        output_folder = self.output_var.get().strip()

        if not export_dir:
            messagebox.showerror("Missing Input", "Please select a Notion export folder.")
            return
        if not os.path.isdir(export_dir):
            messagebox.showerror("Invalid Folder", f"Folder not found:\n{export_dir}")
            return
        if not output_folder:
            messagebox.showerror("Missing Output", "Please specify an output folder.")
            return
        if not os.path.isdir(output_folder):
            messagebox.showerror("Invalid Folder", f"Output folder not found:\n{output_folder}")
            return

        # Build the output filename from the export folder name
        deck_name = os.path.basename(os.path.normpath(export_dir))
        output_path = os.path.join(output_folder, f"{deck_name}.apkg")

        self.convert_btn.configure(state="disabled", text="Converting...")
        self.open_anki_btn.configure(state="disabled")
        self.log_box.delete("1.0", tk.END)
        self.progress.set(0)
        self.progress_label.configure(text="")
        self._conversion_start = time.time()

        def run():
            converter = Converter(
                export_dir=export_dir,
                output_path=output_path,
                text_model=self.text_model_var.get(),
                vision_model=self.vision_model_var.get(),
                skip_images=self.skip_images_var.get(),
                system_prompt=self._custom_system_prompt,
                image_system_prompt=self._custom_image_prompt,
            )
            result = converter.run(
                on_progress=lambda msg: self.after(0, self._log, msg),
                on_step=lambda cur, tot: self.after(0, self._update_progress, cur, tot),
            )
            self.after(0, self._on_complete, result)

        threading.Thread(target=run, daemon=True).start()

    def _log(self, msg: str):
        self.log_box.insert(tk.END, msg + "\n")
        self.log_box.see(tk.END)

    def _update_progress(self, current: int, total: int):
        """Advance the progress bar and show deck count + ETA."""
        if total == 0:
            return
        fraction = current / total
        self.progress.set(fraction)

        elapsed = time.time() - self._conversion_start
        if fraction > 0:
            remaining = (elapsed / fraction) - elapsed
            mins, secs = divmod(int(remaining), 60)
            eta = f"{mins}m {secs:02d}s" if mins else f"{secs}s"
            self.progress_label.configure(text=f"{current}/{total}  —  ~{eta} left")
        else:
            self.progress_label.configure(text=f"{current}/{total}")

    def _on_complete(self, result):
        self.progress.set(1 if result.total_cards > 0 else 0)
        self.progress_label.configure(text="")
        self.convert_btn.configure(state="normal", text="Convert")

        if result.total_cards > 0:
            self._last_output_path = result.output_path
            self.open_anki_btn.configure(state="normal")
            messagebox.showinfo(
                "Done!",
                f"✅ Conversion complete!\n\n"
                f"Cards:  {result.total_cards}\n"
                f"Decks:  {result.total_decks}\n"
                f"Output: {result.output_path}\n\n"
                f"Click 'Show in Folder' to locate the file, then\n"
                f"double-click it to import into Anki."
            )
        else:
            errors_text = '\n'.join(result.errors[:5]) if result.errors else "No cards generated."
            messagebox.showerror("Conversion Failed", f"No cards were created.\n\n{errors_text}")

    def _show_in_folder(self):
        """Open the output folder with the .apkg file selected."""
        if not self._last_output_path or not os.path.isfile(self._last_output_path):
            messagebox.showerror("File Not Found", "The output file no longer exists.")
            return
        try:
            if sys.platform == "win32":
                # /select highlights the file in Explorer
                subprocess.run(["explorer", f"/select,{self._last_output_path}"])
            elif sys.platform == "darwin":
                # -R reveals the file in Finder
                subprocess.run(["open", "-R", self._last_output_path], check=True)
            else:
                subprocess.run(["xdg-open", os.path.dirname(self._last_output_path)], check=True)
        except Exception as e:
            messagebox.showerror("Could not open folder", str(e))


class _PromptEditorDialog(ctk.CTkToplevel):
    """Modal dialog for editing card generation system prompts."""

    def __init__(
        self,
        parent,
        current_style: str,
        system_prompt: str,
        image_system_prompt: str,
        on_apply,
    ):
        super().__init__(parent)
        self.title("Edit Card Generation Prompt")
        self.geometry("720x620")
        self.resizable(True, True)
        self.minsize(500, 400)
        self.transient(parent)
        self.grab_set()

        self._on_apply = on_apply
        self.grid_columnconfigure(0, weight=1)

        pad = {"padx": 16, "pady": 4}

        # Preset selector row
        preset_frame = ctk.CTkFrame(self, fg_color="transparent")
        preset_frame.grid(row=0, column=0, padx=16, pady=(16, 4), sticky="ew")
        preset_frame.grid_columnconfigure(1, weight=1)

        ctk.CTkLabel(preset_frame, text="Load Preset:").grid(
            row=0, column=0, padx=(0, 8), sticky="w")
        self._preset_var = tk.StringVar(value=current_style)
        self._preset_combo = ctk.CTkComboBox(
            preset_frame, variable=self._preset_var,
            values=get_style_names(), width=160,
            command=self._load_preset,
        )
        self._preset_combo.grid(row=0, column=1, sticky="w")

        # Description label
        style = get_style(current_style)
        self._desc_label = ctk.CTkLabel(
            self, text=style.description,
            text_color="gray", font=ctk.CTkFont(size=12),
        )
        self._desc_label.grid(row=1, column=0, **pad, sticky="w")

        # Text prompt label + textbox
        ctk.CTkLabel(self, text="Text Card System Prompt:",
                     font=ctk.CTkFont(weight="bold")).grid(
            row=2, column=0, **pad, sticky="w")
        self._text_prompt_box = ctk.CTkTextbox(
            self, height=160, font=ctk.CTkFont(family="Courier", size=12))
        self._text_prompt_box.grid(row=3, column=0, padx=16, pady=(0, 8), sticky="nsew")
        self._text_prompt_box.insert("1.0", system_prompt)

        # Image prompt label + textbox
        ctk.CTkLabel(self, text="Image Card System Prompt:",
                     font=ctk.CTkFont(weight="bold")).grid(
            row=4, column=0, **pad, sticky="w")
        self._image_prompt_box = ctk.CTkTextbox(
            self, height=160, font=ctk.CTkFont(family="Courier", size=12))
        self._image_prompt_box.grid(row=5, column=0, padx=16, pady=(0, 8), sticky="nsew")
        self._image_prompt_box.insert("1.0", image_system_prompt)

        # Let textboxes expand
        self.grid_rowconfigure(3, weight=1)
        self.grid_rowconfigure(5, weight=1)

        # Bottom buttons
        btn_frame = ctk.CTkFrame(self, fg_color="transparent")
        btn_frame.grid(row=6, column=0, padx=16, pady=(4, 16), sticky="ew")
        btn_frame.grid_columnconfigure(0, weight=1)

        ctk.CTkButton(btn_frame, text="Reset to Preset", width=130,
                      command=self._reset_to_preset).grid(row=0, column=0, sticky="w")
        ctk.CTkButton(btn_frame, text="Cancel", width=90,
                      command=self.destroy).grid(row=0, column=1, padx=(8, 8))
        ctk.CTkButton(btn_frame, text="Apply", width=90,
                      command=self._apply).grid(row=0, column=2)

    def _load_preset(self, style_name: str):
        """Load a preset's prompts into the text boxes."""
        style = get_style(style_name)
        self._desc_label.configure(text=style.description)
        self._text_prompt_box.delete("1.0", tk.END)
        self._text_prompt_box.insert("1.0", style.system_prompt)
        self._image_prompt_box.delete("1.0", tk.END)
        self._image_prompt_box.insert("1.0", style.image_system_prompt)

    def _reset_to_preset(self):
        """Reset text boxes to the currently selected preset."""
        self._load_preset(self._preset_var.get())

    def _apply(self):
        """Save the custom prompts and close the dialog."""
        system = self._text_prompt_box.get("1.0", tk.END).strip()
        image = self._image_prompt_box.get("1.0", tk.END).strip()
        self._on_apply(system, image)
        self.destroy()


def main():
    app = App()
    app.mainloop()


if __name__ == "__main__":
    main()
