"""
onboarding.py
First-run setup wizard shown when Ollama is not detected at startup.

Guides users through:
  1. Downloading and starting Ollama
  2. Pulling llama3  (text model, ~4 GB)
  3. Pulling llava   (vision model, ~4 GB, optional)
"""

import threading
import tkinter as tk
import webbrowser
from typing import Callable, Optional

try:
    import customtkinter as ctk
except ImportError:
    raise SystemExit("customtkinter is required. Install it with: pip install customtkinter")

from src.llm.ollama_client import OllamaClient

OLLAMA_DOWNLOAD_URL = "https://ollama.com/download"
DEFAULT_TEXT_MODEL   = "llama3"
DEFAULT_VISION_MODEL = "llava"


class OllamaSetupWizard(ctk.CTkToplevel):
    """
    Modal dialog shown when Ollama is not detected at startup.

    Parameters
    ----------
    parent:     The parent CTk window.
    on_dismiss: Optional callback invoked when the wizard is closed (either
                because Ollama was confirmed ready or the user skipped).
                Receives a single bool — True if Ollama is now running.
    """

    def __init__(self, parent: ctk.CTk, on_dismiss: Optional[Callable[[bool], None]] = None):
        super().__init__(parent)

        self.title("Ollama Setup")
        self.geometry("560x560")
        self.resizable(False, True)
        self.minsize(500, 480)

        self._on_dismiss = on_dismiss
        self._pulling = False
        self._ollama_ready = False
        self._client = OllamaClient()

        self._build_ui()

        # Make modal — block input to the parent window.
        self.transient(parent)
        self.grab_set()
        self.lift()
        self.focus_force()

        # Initial status check (non-blocking).
        self._check_status()

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _build_ui(self):
        self.grid_columnconfigure(0, weight=1)

        # ── Header ──────────────────────────────────────────────────────
        ctk.CTkLabel(
            self, text="Ollama Setup",
            font=ctk.CTkFont(size=20, weight="bold"),
        ).grid(row=0, column=0, padx=24, pady=(20, 4), sticky="w")

        # ── Status row ──────────────────────────────────────────────────
        status_row = ctk.CTkFrame(self, fg_color="transparent")
        status_row.grid(row=1, column=0, padx=24, pady=(0, 6), sticky="ew")

        self._status_dot = ctk.CTkLabel(
            status_row, text="●",
            text_color="gray", font=ctk.CTkFont(size=16),
        )
        self._status_dot.grid(row=0, column=0, padx=(0, 8))

        self._status_label = ctk.CTkLabel(
            status_row, text="Checking Ollama…", text_color="gray", anchor="w",
        )
        self._status_label.grid(row=0, column=1, sticky="w")

        # ── Description ─────────────────────────────────────────────────
        ctk.CTkLabel(
            self,
            text=(
                "This app uses Ollama to run AI models locally — no cloud, no API keys.\n"
                "Follow the two steps below to get started."
            ),
            wraplength=500, justify="left", text_color="gray70",
        ).grid(row=2, column=0, padx=24, pady=(0, 6), sticky="w")

        ctk.CTkFrame(self, height=1, fg_color="gray60").grid(
            row=3, column=0, padx=24, pady=8, sticky="ew")

        # ── Step 1 — Install ────────────────────────────────────────────
        ctk.CTkLabel(
            self, text="Step 1 — Install & start Ollama",
            font=ctk.CTkFont(size=13, weight="bold"),
        ).grid(row=4, column=0, padx=24, pady=(4, 2), sticky="w")

        ctk.CTkLabel(
            self,
            text="Download Ollama, install it, then launch the app before continuing.",
            text_color="gray70", wraplength=500, justify="left",
        ).grid(row=5, column=0, padx=24, pady=(0, 8), sticky="w")

        ctk.CTkButton(
            self, text="Open  ollama.com/download  ↗",
            command=self._open_download, width=260,
        ).grid(row=6, column=0, padx=24, pady=(0, 4), sticky="w")

        ctk.CTkFrame(self, height=1, fg_color="gray60").grid(
            row=7, column=0, padx=24, pady=8, sticky="ew")

        # ── Step 2 — Pull models ─────────────────────────────────────────
        ctk.CTkLabel(
            self, text="Step 2 — Pull the required AI models",
            font=ctk.CTkFont(size=13, weight="bold"),
        ).grid(row=8, column=0, padx=24, pady=(4, 2), sticky="w")

        ctk.CTkLabel(
            self,
            text=(
                f"• {DEFAULT_TEXT_MODEL}  — text model for card generation  (~4 GB)\n"
                f"• {DEFAULT_VISION_MODEL}  — vision model for image-aware cards  (~4 GB, optional)"
            ),
            text_color="gray70", wraplength=500, justify="left",
        ).grid(row=9, column=0, padx=24, pady=(0, 10), sticky="w")

        pull_frame = ctk.CTkFrame(self, fg_color="transparent")
        pull_frame.grid(row=10, column=0, padx=24, pady=(0, 8), sticky="w")

        self._pull_text_btn = ctk.CTkButton(
            pull_frame, text=f"Pull {DEFAULT_TEXT_MODEL}  (text)",
            width=210, state="disabled",
            command=lambda: self._start_pull(DEFAULT_TEXT_MODEL),
        )
        self._pull_text_btn.grid(row=0, column=0, padx=(0, 12))

        self._pull_vision_btn = ctk.CTkButton(
            pull_frame, text=f"Pull {DEFAULT_VISION_MODEL}  (vision)",
            width=210, state="disabled",
            fg_color="gray40", hover_color="gray30",
            command=lambda: self._start_pull(DEFAULT_VISION_MODEL),
        )
        self._pull_vision_btn.grid(row=0, column=1)

        # ── Progress log ────────────────────────────────────────────────
        self._log_box = ctk.CTkTextbox(
            self, height=100,
            font=ctk.CTkFont(family="Courier", size=11),
            state="disabled",
        )
        self._log_box.grid(row=11, column=0, padx=24, pady=(0, 12), sticky="ew")

        # ── Bottom buttons ───────────────────────────────────────────────
        bottom = ctk.CTkFrame(self, fg_color="transparent")
        bottom.grid(row=12, column=0, padx=24, pady=(0, 20), sticky="ew")
        bottom.grid_columnconfigure(0, weight=1)

        self._check_btn = ctk.CTkButton(
            bottom, text="Check Again", width=130,
            command=self._check_status,
        )
        self._check_btn.grid(row=0, column=0, sticky="w")

        self._close_btn = ctk.CTkButton(
            bottom, text="Skip for Now", width=130,
            fg_color="gray40", hover_color="gray30",
            command=self._dismiss,
        )
        self._close_btn.grid(row=0, column=1, sticky="e")

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------

    def _open_download(self):
        webbrowser.open(OLLAMA_DOWNLOAD_URL)
        self._log("Opened Ollama download page in your browser.")

    def _check_status(self):
        self._status_dot.configure(text_color="gray")
        self._status_label.configure(text="Checking…", text_color="gray")
        self._check_btn.configure(state="disabled")

        def check():
            running = self._client.is_running()
            self.after(0, self._apply_status, running)

        threading.Thread(target=check, daemon=True).start()

    def _apply_status(self, running: bool):
        self._check_btn.configure(state="normal")
        self._ollama_ready = running

        if running:
            self._status_dot.configure(text_color="green")
            self._status_label.configure(
                text="Ollama is running!", text_color="green")
            self._log("✓ Ollama is running. You can now pull models or close this dialog.")
            self._pull_text_btn.configure(state="normal")
            self._pull_vision_btn.configure(state="normal")
            # Upgrade the close button to "Continue" once Ollama is confirmed.
            self._close_btn.configure(
                text="Continue", fg_color=["#3a7ebf", "#1f538d"],
                hover_color=["#325882", "#14375e"],
            )
        else:
            self._status_dot.configure(text_color="red")
            self._status_label.configure(
                text="Ollama is not running.", text_color="red")
            self._pull_text_btn.configure(state="disabled")
            self._pull_vision_btn.configure(state="disabled")
            self._close_btn.configure(
                text="Skip for Now",
                fg_color="gray40", hover_color="gray30",
            )

    def _start_pull(self, model_name: str):
        if self._pulling:
            return
        if not self._client.is_running():
            self._log("✗ Ollama is not running. Start it first, then click 'Check Again'.")
            return

        self._pulling = True
        self._pull_text_btn.configure(state="disabled")
        self._pull_vision_btn.configure(state="disabled")
        self._check_btn.configure(state="disabled")
        self._log(f"Pulling {model_name} — this may take several minutes…")

        def pull():
            try:
                self._client.pull_model(
                    model_name,
                    on_progress=lambda s: self.after(0, self._log, s),
                )
                self.after(0, self._on_pull_done, model_name, None)
            except Exception as exc:
                self.after(0, self._on_pull_done, model_name, str(exc))

        threading.Thread(target=pull, daemon=True).start()

    def _on_pull_done(self, model_name: str, error: Optional[str]):
        self._pulling = False
        self._check_btn.configure(state="normal")

        if error:
            self._log(f"✗ Error pulling {model_name}: {error}")
        else:
            self._log(f"✓ {model_name} pulled successfully.")

        # Re-enable pull buttons if Ollama is still reachable.
        if self._client.is_running():
            self._pull_text_btn.configure(state="normal")
            self._pull_vision_btn.configure(state="normal")

    def _dismiss(self):
        self.grab_release()
        self.destroy()
        if self._on_dismiss:
            self._on_dismiss(self._ollama_ready)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _log(self, msg: str):
        self._log_box.configure(state="normal")
        self._log_box.insert(tk.END, msg + "\n")
        self._log_box.see(tk.END)
        self._log_box.configure(state="disabled")
