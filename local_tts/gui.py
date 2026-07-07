from __future__ import annotations

from dataclasses import dataclass
import queue
import subprocess
import sys
import threading
import time
from pathlib import Path
from tkinter import Tk, filedialog, messagebox, ttk
from tkinter import font as tkfont
from tkinter import scrolledtext
import tkinter as tk

from .audio import (
    cleanup_device_memory,
    configure_model_cache,
    ensure_ffmpeg,
    ensure_ffplay,
    generate_one_segment,
    load_chatterbox_model,
    select_device,
    start_audio_playback,
)
from .config import RunConfig
from .errors import ConfigError, GenerationCancelledError
from .generator import ProgressEvent, generate_segments
from .gui_support import (
    SegmentDraft,
    build_segments_payload,
    default_storage_dir,
    model_cache_ready,
)
from .segments import load_json, planned_output_path


THEMES: dict[str, dict[str, str]] = {
    "light": {
        "bg": "#F4F0E8",
        "card": "#FFFDFC",
        "border": "#D7D0C4",
        "text": "#1F2421",
        "muted": "#66706A",
        "accent": "#1E7A67",
        "accent_text": "#FFFFFF",
        "surface": "#EEE7DB",
        "input_bg": "#FFFFFF",
        "input_fg": "#1F2421",
        "success_bg": "#DFF4E7",
        "success_fg": "#0F5B33",
        "warning_bg": "#FCECC8",
        "warning_fg": "#8A5A00",
        "error_bg": "#F9D7D7",
        "error_fg": "#8E1F1F",
        "shadow": "#E7E0D2",
    },
    "dark": {
        "bg": "#111513",
        "card": "#171D1A",
        "border": "#26302B",
        "text": "#E9EFE8",
        "muted": "#99A79E",
        "accent": "#55C7A8",
        "accent_text": "#0A1310",
        "surface": "#1E2622",
        "input_bg": "#101512",
        "input_fg": "#E9EFE8",
        "success_bg": "#153226",
        "success_fg": "#9DE1BF",
        "warning_bg": "#433414",
        "warning_fg": "#F6D27D",
        "error_bg": "#3E1D1D",
        "error_fg": "#FFB0B0",
        "shadow": "#0B0E0D",
    },
}


def preferred_font_family() -> str:
    platform_fonts = {
        "win32": ("Segoe UI", "Aptos", "Verdana"),
        "darwin": ("SF Pro Text", "Helvetica Neue", "Arial"),
    }
    candidates = platform_fonts.get(sys.platform, ("Noto Sans", "DejaVu Sans", "Arial"))
    available = set(tkfont.families())
    for candidate in candidates:
        if candidate in available:
            return candidate
    return "TkDefaultFont"


@dataclass
class SegmentJob:
    job_id: int
    row: "SegmentRow"
    segment: dict[str, str]
    output_dir: Path
    reference_path: Path
    force: bool
    cancel_requested: bool = False


class SegmentRow:
    def __init__(
        self,
        parent: tk.Widget,
        *,
        index: int,
        font_family: str,
        play_callback,
        generate_callback,
        cancel_callback,
        remove_callback,
    ) -> None:
        self.frame = tk.Frame(parent, highlightthickness=1, bd=0)
        self.index_label = ttk.Label(self.frame, style="Section.TLabel")
        self.status_var = tk.StringVar(value="Idle")
        self.status_label = ttk.Label(self.frame, textvariable=self.status_var, style="BadgeIdle.TLabel")
        self.detail_var = tk.StringVar(value="Ready")
        self.detail_label = ttk.Label(self.frame, textvariable=self.detail_var, style="Muted.TLabel")
        self.id_var = tk.StringVar()
        self.audio_filename_var = tk.StringVar()
        self.id_entry = ttk.Entry(self.frame, textvariable=self.id_var)
        self.file_entry = ttk.Entry(self.frame, textvariable=self.audio_filename_var)
        self.actions = ttk.Frame(self.frame, style="Card.TFrame")
        self.play_button_var = tk.StringVar(value="Play")
        self.play_button = ttk.Button(
            self.actions,
            textvariable=self.play_button_var,
            style="Ghost.TButton",
            command=lambda: play_callback(self),
        )
        self.generate_button = ttk.Button(
            self.actions,
            text="Generate",
            style="Accent.TButton",
            command=lambda: generate_callback(self),
        )
        self.text_widget = tk.Text(
            self.frame,
            height=4,
            wrap="word",
            relief="flat",
            undo=True,
            font=(font_family, 11),
        )
        self.remove_button = ttk.Button(
            self.actions,
            text="Remove",
            style="Ghost.TButton",
            command=lambda: remove_callback(self),
        )
        self.cancel_button = ttk.Button(
            self.actions,
            text="Cancel",
            style="Ghost.TButton",
            command=lambda: cancel_callback(self),
        )
        self.progress = ttk.Progressbar(self.frame, mode="determinate", maximum=100, value=0)

        self.index_label.grid(row=0, column=0, sticky="w")
        self.status_label.grid(row=0, column=1, sticky="e", padx=(10, 10))
        self.actions.grid(row=0, column=2, sticky="e")
        self.play_button.grid(row=0, column=0, sticky="e")
        self.generate_button.grid(row=0, column=1, sticky="e", padx=(8, 0))
        self.remove_button.grid(row=0, column=2, sticky="e", padx=(8, 0))
        ttk.Label(self.frame, text="Segment ID", style="Muted.TLabel").grid(row=1, column=0, sticky="w", pady=(10, 4))
        ttk.Label(self.frame, text="Output file", style="Muted.TLabel").grid(row=1, column=1, sticky="w", pady=(10, 4))
        self.id_entry.grid(row=2, column=0, sticky="ew", padx=(0, 10))
        self.file_entry.grid(row=2, column=1, sticky="ew", padx=(0, 10))
        ttk.Label(self.frame, text="Text", style="Muted.TLabel").grid(row=3, column=0, columnspan=3, sticky="w", pady=(12, 4))
        self.text_widget.grid(row=4, column=0, columnspan=3, sticky="ew")
        self.detail_label.grid(row=5, column=0, columnspan=3, sticky="w", pady=(10, 4))
        self.progress.grid(row=6, column=0, columnspan=3, sticky="ew")
        self.frame.columnconfigure(0, weight=1)
        self.frame.columnconfigure(1, weight=1)

        self.set_index(index)
        self.show_idle_controls()
        self.set_playing(False)
        self.set_progress(0)

    def apply_theme(self, colors: dict[str, str]) -> None:
        self.frame.configure(bg=colors["card"], highlightbackground=colors["border"], highlightcolor=colors["border"])
        self.actions.configure(style="Card.TFrame")
        self.text_widget.configure(
            bg=colors["input_bg"],
            fg=colors["input_fg"],
            insertbackground=colors["input_fg"],
            highlightbackground=colors["border"],
            highlightcolor=colors["accent"],
            selectbackground=colors["accent"],
            selectforeground=colors["accent_text"],
        )

    def set_index(self, index: int) -> None:
        self.index_label.configure(text=f"Segment {index:02d}")

    def set_values(self, *, segment_id: str = "", audio_filename: str = "", text: str = "") -> None:
        self.id_var.set(segment_id)
        self.audio_filename_var.set(audio_filename)
        self.text_widget.delete("1.0", "end")
        self.text_widget.insert("1.0", text)

    def apply_resolved_values(self, *, segment_id: str, audio_filename: str) -> None:
        self.id_var.set(segment_id)
        self.audio_filename_var.set(audio_filename)

    def get_draft(self) -> SegmentDraft:
        return SegmentDraft(
            segment_id=self.id_var.get(),
            audio_filename=self.audio_filename_var.get(),
            text=self.text_widget.get("1.0", "end").strip(),
        )

    def destroy(self) -> None:
        self.frame.destroy()

    def set_editor_locked(self, locked: bool) -> None:
        entry_state = "disabled" if locked else "normal"
        text_state = "disabled" if locked else "normal"
        self.id_entry.configure(state=entry_state)
        self.file_entry.configure(state=entry_state)
        self.text_widget.configure(state=text_state)

    def set_generate_enabled(self, enabled: bool) -> None:
        self.generate_button.configure(state="normal" if enabled else "disabled")

    def set_play_enabled(self, enabled: bool) -> None:
        self.play_button.configure(state="normal" if enabled else "disabled")

    def set_playing(self, playing: bool) -> None:
        self.play_button_var.set("Stop" if playing else "Play")

    def set_remove_enabled(self, enabled: bool) -> None:
        self.remove_button.configure(state="normal" if enabled else "disabled")

    def set_cancel_enabled(self, enabled: bool) -> None:
        self.cancel_button.configure(state="normal" if enabled else "disabled")

    def set_status(self, text: str, style_name: str = "BadgeIdle.TLabel") -> None:
        self.status_var.set(text)
        self.status_label.configure(style=style_name)

    def set_detail(self, text: str) -> None:
        self.detail_var.set(text)

    def set_progress(self, value: float) -> None:
        self.progress.stop()
        self.progress.configure(mode="determinate", value=max(0.0, min(100.0, value)))

    def start_progress_animation(self) -> None:
        self.progress.configure(mode="indeterminate")
        self.progress.start(10)

    def stop_progress_animation(self) -> None:
        self.progress.stop()
        self.progress.configure(mode="determinate")

    def show_idle_controls(self) -> None:
        self.cancel_button.grid_remove()
        self.remove_button.grid(row=0, column=2, sticky="e", padx=(8, 0))

    def show_cancel_controls(self) -> None:
        self.remove_button.grid_remove()
        self.cancel_button.grid(row=0, column=2, sticky="e", padx=(8, 0))


class LocalTTSApp(Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("Local TTS")
        self.geometry("1320x860")
        self.minsize(1120, 760)

        self.storage_dir = default_storage_dir().resolve()
        self.default_output_dir = (self.storage_dir / "output").resolve()
        self.default_model_cache = (self.storage_dir / "models" / "huggingface").resolve()

        self.style = ttk.Style(self)
        self.style.theme_use("clam")
        self.font_family = preferred_font_family()
        self.theme_name = "light"
        self.queue: queue.Queue[tuple[str, object]] = queue.Queue()
        self.model_task_active = False
        self.worker_thread: threading.Thread | None = None
        self.queue_lock = threading.Lock()
        self.pending_jobs: list[SegmentJob] = []
        self.row_jobs: dict[SegmentRow, SegmentJob] = {}
        self.active_job: SegmentJob | None = None
        self.playback_process: subprocess.Popen | None = None
        self.playback_row: SegmentRow | None = None
        self.worker_settings: dict[str, object] | None = None
        self.job_sequence = 0
        self.queue_session_total = 0
        self.queue_session_completed = 0
        self.segment_rows: list[SegmentRow] = []

        self.theme_button_var = tk.StringVar(value="Dark Theme")
        self.model_cache_var = tk.StringVar(value=str(self.default_model_cache))
        self.output_dir_var = tk.StringVar(value=str(self.default_output_dir))
        self.reference_var = tk.StringVar()
        self.device_var = tk.StringVar(value="auto")
        self.force_var = tk.BooleanVar(value=False)
        self.model_status_var = tk.StringVar(value="Model not installed")
        self.model_badge_var = tk.StringVar(value="NOT READY")
        self.model_detail_var = tk.StringVar()
        self.generation_status_var = tk.StringVar(value="Ready")
        self.json_status_var = tk.StringVar(value="No JSON loaded. Add segments manually or import one.")

        self._build_fonts()
        self._build_ui()
        self._apply_theme(self.theme_name)
        self.refresh_model_status()
        self.add_segment_row()
        self.after(120, self._poll_queue)

    def _build_fonts(self) -> None:
        self.title_font = tkfont.Font(family=self.font_family, size=26, weight="bold")
        self.card_title_font = tkfont.Font(family=self.font_family, size=15, weight="bold")
        self.body_font = tkfont.Font(family=self.font_family, size=11)
        self.muted_font = tkfont.Font(family=self.font_family, size=10)

    def _build_ui(self) -> None:
        self.columnconfigure(0, weight=1)
        self.rowconfigure(0, weight=1)

        self.shell = ttk.Frame(self, style="Shell.TFrame", padding=24)
        self.shell.grid(row=0, column=0, sticky="nsew")
        self.shell.columnconfigure(0, weight=3)
        self.shell.columnconfigure(1, weight=2)
        self.shell.rowconfigure(1, weight=1)

        header = ttk.Frame(self.shell, style="Shell.TFrame")
        header.grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, 18))
        header.columnconfigure(0, weight=1)

        ttk.Label(
            header,
            text="Local TTS",
            style="Title.TLabel",
            font=self.title_font,
        ).grid(row=0, column=0, sticky="w")
        ttk.Label(
            header,
            text="Import JSON, stack segments, install the model, and generate locally.",
            style="Muted.TLabel",
            font=self.body_font,
        ).grid(row=1, column=0, sticky="w", pady=(6, 0))
        ttk.Button(
            header,
            textvariable=self.theme_button_var,
            style="Ghost.TButton",
            command=self.toggle_theme,
        ).grid(row=0, column=1, rowspan=2, sticky="e")

        left_column = ttk.Frame(self.shell, style="Shell.TFrame")
        left_column.grid(row=1, column=0, sticky="nsew", padx=(0, 14))
        left_column.columnconfigure(0, weight=1)
        left_column.rowconfigure(1, weight=1)

        right_column = ttk.Frame(self.shell, style="Shell.TFrame")
        right_column.grid(row=1, column=1, sticky="nsew")
        right_column.columnconfigure(0, weight=1)
        right_column.rowconfigure(4, weight=1)

        self._build_segments_card(left_column)
        self._build_model_card(right_column)
        self._build_reference_card(right_column)
        self._build_output_card(right_column)
        self._build_action_card(right_column)
        self._build_log_card(right_column)

    def _build_segments_card(self, parent: ttk.Frame) -> None:
        card = ttk.Frame(parent, style="Card.TFrame", padding=18)
        card.grid(row=0, column=0, sticky="ew", pady=(0, 14))
        card.columnconfigure(0, weight=1)

        ttk.Label(card, text="Segments", style="CardTitle.TLabel", font=self.card_title_font).grid(
            row=0, column=0, sticky="w"
        )
        ttk.Label(
            card,
            textvariable=self.json_status_var,
            style="Muted.TLabel",
            font=self.muted_font,
            wraplength=660,
        ).grid(row=1, column=0, sticky="w", pady=(6, 14))

        toolbar = ttk.Frame(card, style="Card.TFrame")
        toolbar.grid(row=2, column=0, sticky="ew")
        toolbar.columnconfigure(4, weight=1)

        ttk.Button(toolbar, text="Load JSON", style="Ghost.TButton", command=self.load_json_file).grid(
            row=0, column=0, sticky="w"
        )
        ttk.Button(toolbar, text="+ Segment", style="Accent.TButton", command=self.add_segment_row).grid(
            row=0, column=1, sticky="w", padx=(8, 0)
        )
        ttk.Button(toolbar, text="Clear", style="Ghost.TButton", command=self.clear_segments).grid(
            row=0, column=2, sticky="w", padx=(8, 0)
        )

        editor_card = ttk.Frame(parent, style="Card.TFrame", padding=12)
        editor_card.grid(row=1, column=0, sticky="nsew")
        editor_card.columnconfigure(0, weight=1)
        editor_card.rowconfigure(0, weight=1)

        self.segment_canvas = tk.Canvas(editor_card, highlightthickness=0, bd=0)
        self.segment_scrollbar = ttk.Scrollbar(editor_card, orient="vertical", command=self.segment_canvas.yview)
        self.segment_canvas.configure(yscrollcommand=self.segment_scrollbar.set)
        self.segment_canvas.grid(row=0, column=0, sticky="nsew")
        self.segment_scrollbar.grid(row=0, column=1, sticky="ns")

        self.segment_container = tk.Frame(self.segment_canvas, bd=0)
        self.segment_window = self.segment_canvas.create_window((0, 0), window=self.segment_container, anchor="nw")
        self.segment_container.bind("<Configure>", self._update_segment_scrollregion)
        self.segment_canvas.bind("<Configure>", self._resize_segment_window)
        self.segment_canvas.bind_all("<MouseWheel>", self._on_mousewheel, add="+")

    def _build_model_card(self, parent: ttk.Frame) -> None:
        card = ttk.Frame(parent, style="Card.TFrame", padding=18)
        card.grid(row=0, column=0, sticky="ew", pady=(0, 14))
        card.columnconfigure(0, weight=1)

        title_row = ttk.Frame(card, style="Card.TFrame")
        title_row.grid(row=0, column=0, sticky="ew")
        title_row.columnconfigure(0, weight=1)

        ttk.Label(title_row, text="Model", style="CardTitle.TLabel", font=self.card_title_font).grid(
            row=0, column=0, sticky="w"
        )
        self.model_badge = ttk.Label(title_row, textvariable=self.model_badge_var, style="BadgeIdle.TLabel")
        self.model_badge.grid(row=0, column=1, sticky="e")

        ttk.Label(
            card,
            textvariable=self.model_status_var,
            style="Body.TLabel",
            font=self.body_font,
            wraplength=360,
        ).grid(row=1, column=0, sticky="w", pady=(8, 4))
        ttk.Label(
            card,
            textvariable=self.model_detail_var,
            style="Muted.TLabel",
            font=self.muted_font,
            wraplength=360,
        ).grid(row=2, column=0, sticky="w")

        cache_row = ttk.Frame(card, style="Card.TFrame")
        cache_row.grid(row=3, column=0, sticky="ew", pady=(14, 0))
        cache_row.columnconfigure(0, weight=1)
        self.model_cache_entry = ttk.Entry(cache_row, textvariable=self.model_cache_var)
        self.model_cache_entry.grid(row=0, column=0, sticky="ew", padx=(0, 8))
        self.model_cache_browse_button = ttk.Button(
            cache_row,
            text="Browse",
            style="Ghost.TButton",
            command=self.choose_model_cache,
        )
        self.model_cache_browse_button.grid(row=0, column=1, sticky="e")

        device_row = ttk.Frame(card, style="Card.TFrame")
        device_row.grid(row=4, column=0, sticky="ew", pady=(12, 0))
        ttk.Label(device_row, text="Device", style="Muted.TLabel").grid(row=0, column=0, sticky="w")
        self.device_combo = ttk.Combobox(
            device_row,
            textvariable=self.device_var,
            values=("auto", "cpu", "cuda", "mps"),
            state="readonly",
            width=12,
        )
        self.device_combo.grid(row=0, column=1, sticky="e")

        self.model_progress = ttk.Progressbar(card, mode="determinate")
        self.model_progress.grid(row=5, column=0, sticky="ew", pady=(14, 0))
        self.model_button = ttk.Button(
            card,
            text="Download / Load Model",
            style="Accent.TButton",
            command=self.start_model_task,
        )
        self.model_button.grid(row=6, column=0, sticky="ew", pady=(12, 0))

    def _build_reference_card(self, parent: ttk.Frame) -> None:
        card = ttk.Frame(parent, style="Card.TFrame", padding=18)
        card.grid(row=1, column=0, sticky="ew", pady=(0, 14))
        card.columnconfigure(0, weight=1)

        ttk.Label(card, text="Voice Sample", style="CardTitle.TLabel", font=self.card_title_font).grid(
            row=0, column=0, sticky="w"
        )
        ttk.Label(
            card,
            text="Optional until you generate. Choose a clean MP3 or WAV reference voice.",
            style="Muted.TLabel",
            font=self.muted_font,
            wraplength=360,
        ).grid(row=1, column=0, sticky="w", pady=(6, 14))

        ref_row = ttk.Frame(card, style="Card.TFrame")
        ref_row.grid(row=2, column=0, sticky="ew")
        ref_row.columnconfigure(0, weight=1)
        self.reference_entry = ttk.Entry(ref_row, textvariable=self.reference_var)
        self.reference_entry.grid(row=0, column=0, sticky="ew", padx=(0, 8))
        self.reference_browse_button = ttk.Button(
            ref_row,
            text="Browse",
            style="Ghost.TButton",
            command=self.choose_reference_audio,
        )
        self.reference_browse_button.grid(row=0, column=1, sticky="e")

    def _build_output_card(self, parent: ttk.Frame) -> None:
        card = ttk.Frame(parent, style="Card.TFrame", padding=18)
        card.grid(row=2, column=0, sticky="ew", pady=(0, 14))
        card.columnconfigure(0, weight=1)

        ttk.Label(card, text="Output", style="CardTitle.TLabel", font=self.card_title_font).grid(
            row=0, column=0, sticky="w"
        )
        ttk.Label(
            card,
            text="Generated MP3 files and the manifest will be written here.",
            style="Muted.TLabel",
            font=self.muted_font,
            wraplength=360,
        ).grid(row=1, column=0, sticky="w", pady=(6, 14))

        output_row = ttk.Frame(card, style="Card.TFrame")
        output_row.grid(row=2, column=0, sticky="ew")
        output_row.columnconfigure(0, weight=1)
        self.output_entry = ttk.Entry(output_row, textvariable=self.output_dir_var)
        self.output_entry.grid(row=0, column=0, sticky="ew", padx=(0, 8))
        self.output_browse_button = ttk.Button(
            output_row,
            text="Browse",
            style="Ghost.TButton",
            command=self.choose_output_dir,
        )
        self.output_browse_button.grid(row=0, column=1, sticky="e")

        self.force_checkbutton = ttk.Checkbutton(
            card,
            text="Force overwrite existing MP3 files",
            variable=self.force_var,
            style="TCheckbutton",
        )
        self.force_checkbutton.grid(row=3, column=0, sticky="w", pady=(12, 0))

    def _build_action_card(self, parent: ttk.Frame) -> None:
        card = ttk.Frame(parent, style="Card.TFrame", padding=18)
        card.grid(row=3, column=0, sticky="ew", pady=(0, 14))
        card.columnconfigure(0, weight=1)

        ttk.Label(card, text="Generate", style="CardTitle.TLabel", font=self.card_title_font).grid(
            row=0, column=0, sticky="w"
        )
        ttk.Label(
            card,
            textvariable=self.generation_status_var,
            style="Body.TLabel",
            font=self.body_font,
            wraplength=360,
        ).grid(row=1, column=0, sticky="w", pady=(8, 12))
        self.generation_progress = ttk.Progressbar(card, mode="determinate")
        self.generation_progress.grid(row=2, column=0, sticky="ew")
        self.generate_button = ttk.Button(
            card,
            text="Generate Audio",
            style="Accent.TButton",
            command=self.start_generation_task,
        )
        self.generate_button.grid(row=3, column=0, sticky="ew", pady=(12, 0))

    def _build_log_card(self, parent: ttk.Frame) -> None:
        card = ttk.Frame(parent, style="Card.TFrame", padding=18)
        card.grid(row=4, column=0, sticky="nsew")
        card.columnconfigure(0, weight=1)
        card.rowconfigure(1, weight=1)

        ttk.Label(card, text="Activity", style="CardTitle.TLabel", font=self.card_title_font).grid(
            row=0, column=0, sticky="w"
        )
        self.log_widget = scrolledtext.ScrolledText(card, height=14, wrap="word", relief="flat", undo=False)
        self.log_widget.grid(row=1, column=0, sticky="nsew", pady=(10, 0))
        self.log_widget.configure(state="disabled", font=(self.font_family, 10))

    def toggle_theme(self) -> None:
        self.theme_name = "dark" if self.theme_name == "light" else "light"
        self._apply_theme(self.theme_name)

    def _apply_theme(self, theme_name: str) -> None:
        colors = THEMES[theme_name]
        self.configure(bg=colors["bg"])
        self.theme_button_var.set("Light Theme" if theme_name == "dark" else "Dark Theme")

        self.style.configure("Shell.TFrame", background=colors["bg"])
        self.style.configure("Card.TFrame", background=colors["card"], borderwidth=0, relief="flat")
        self.style.configure("Title.TLabel", background=colors["bg"], foreground=colors["text"])
        self.style.configure("CardTitle.TLabel", background=colors["card"], foreground=colors["text"])
        self.style.configure("Section.TLabel", background=colors["card"], foreground=colors["text"])
        self.style.configure("Body.TLabel", background=colors["card"], foreground=colors["text"])
        self.style.configure("Muted.TLabel", background=colors["card"], foreground=colors["muted"])
        self.style.configure(
            "Accent.TButton",
            background=colors["accent"],
            foreground=colors["accent_text"],
            borderwidth=0,
            focusthickness=0,
            padding=(14, 10),
        )
        self.style.map(
            "Accent.TButton",
            background=[("active", colors["accent"]), ("pressed", colors["accent"])],
            foreground=[("disabled", colors["muted"])],
        )
        self.style.configure(
            "Ghost.TButton",
            background=colors["surface"],
            foreground=colors["text"],
            bordercolor=colors["border"],
            padding=(12, 9),
        )
        self.style.map(
            "Ghost.TButton",
            background=[("active", colors["surface"]), ("pressed", colors["surface"])],
            foreground=[("disabled", colors["muted"])],
        )
        self.style.configure(
            "TEntry",
            fieldbackground=colors["input_bg"],
            foreground=colors["input_fg"],
            bordercolor=colors["border"],
            insertcolor=colors["input_fg"],
            padding=8,
        )
        self.style.configure(
            "TCombobox",
            fieldbackground=colors["input_bg"],
            foreground=colors["input_fg"],
            background=colors["input_bg"],
            bordercolor=colors["border"],
            arrowsize=16,
            padding=6,
        )
        self.style.map("TCombobox", fieldbackground=[("readonly", colors["input_bg"])])
        self.style.configure(
            "TCheckbutton",
            background=colors["card"],
            foreground=colors["text"],
        )
        self.style.configure(
            "Horizontal.TProgressbar",
            background=colors["accent"],
            troughcolor=colors["surface"],
            bordercolor=colors["surface"],
            lightcolor=colors["accent"],
            darkcolor=colors["accent"],
        )
        self.style.configure(
            "BadgeIdle.TLabel",
            background=colors["surface"],
            foreground=colors["text"],
            padding=(10, 5),
        )
        self.style.configure(
            "BadgeReady.TLabel",
            background=colors["success_bg"],
            foreground=colors["success_fg"],
            padding=(10, 5),
        )
        self.style.configure(
            "BadgeBusy.TLabel",
            background=colors["warning_bg"],
            foreground=colors["warning_fg"],
            padding=(10, 5),
        )
        self.style.configure(
            "BadgeError.TLabel",
            background=colors["error_bg"],
            foreground=colors["error_fg"],
            padding=(10, 5),
        )

        self.segment_canvas.configure(bg=colors["card"])
        self.segment_container.configure(bg=colors["card"])
        self.log_widget.configure(
            bg=colors["input_bg"],
            fg=colors["input_fg"],
            insertbackground=colors["input_fg"],
            selectbackground=colors["accent"],
            selectforeground=colors["accent_text"],
        )
        self.log_widget.tag_configure("info", foreground=colors["input_fg"])
        self.log_widget.tag_configure("success", foreground=colors["success_fg"])
        self.log_widget.tag_configure("error", foreground=colors["error_fg"])
        self.log_widget.tag_configure("muted", foreground=colors["muted"])

        for row in self.segment_rows:
            row.apply_theme(colors)

    def add_segment_row(self, *, segment_id: str = "", audio_filename: str = "", text: str = "") -> None:
        row = SegmentRow(
            self.segment_container,
            index=len(self.segment_rows) + 1,
            font_family=self.font_family,
            play_callback=self.toggle_segment_playback,
            generate_callback=self.start_single_segment_task,
            cancel_callback=self.cancel_single_segment_task,
            remove_callback=self.remove_segment_row,
        )
        row.frame.pack(fill="x", padx=4, pady=8)
        row.set_values(segment_id=segment_id, audio_filename=audio_filename, text=text)
        row.set_status("Idle", "BadgeIdle.TLabel")
        row.apply_theme(THEMES[self.theme_name])
        self.segment_rows.append(row)
        self._refresh_playback_state(row)
        row.text_widget.focus_set()
        self._refresh_segment_labels()

    def remove_segment_row(self, row: SegmentRow) -> None:
        if self.playback_row is row:
            self._stop_active_playback()

        if len(self.segment_rows) == 1:
            row.set_values()
            row.set_status("Idle", "BadgeIdle.TLabel")
            row.set_detail("Ready")
            self._refresh_playback_state(row)
            return

        self.segment_rows.remove(row)
        row.destroy()
        self._refresh_segment_labels()
        self._refresh_all_playback_states()

    def clear_segments(self, *, confirm: bool = True) -> None:
        if self.model_task_active or self.row_jobs:
            messagebox.showerror("Queue active", "Cancel queued jobs before clearing segments.")
            return

        if confirm and self.segment_rows:
            approved = messagebox.askyesno("Clear segments", "Remove all segment rows?")
            if not approved:
                return

        for row in self.segment_rows:
            if self.playback_row is row:
                self._stop_active_playback()
            row.destroy()
        self.segment_rows.clear()
        self.json_status_var.set("No JSON loaded. Add segments manually or import one.")
        self.add_segment_row()

    def _refresh_segment_labels(self) -> None:
        for index, row in enumerate(self.segment_rows, start=1):
            row.set_index(index)

    def _update_segment_scrollregion(self, _event=None) -> None:
        self.segment_canvas.configure(scrollregion=self.segment_canvas.bbox("all"))

    def _resize_segment_window(self, event) -> None:
        self.segment_canvas.itemconfigure(self.segment_window, width=event.width)

    def _on_mousewheel(self, event) -> None:
        if self.segment_canvas.winfo_exists():
            self.segment_canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")

    def choose_reference_audio(self) -> None:
        path = filedialog.askopenfilename(
            title="Choose voice sample",
            filetypes=[("Audio files", "*.mp3 *.wav"), ("All files", "*.*")],
        )
        if path:
            self.reference_var.set(path)

    def choose_output_dir(self) -> None:
        path = filedialog.askdirectory(title="Choose output folder", initialdir=self.output_dir_var.get())
        if path:
            self.output_dir_var.set(path)
            self._refresh_all_playback_states()

    def choose_model_cache(self) -> None:
        path = filedialog.askdirectory(title="Choose model cache folder", initialdir=self.model_cache_var.get())
        if path:
            self.model_cache_var.set(path)
            self.refresh_model_status()

    def _generation_worker_running(self) -> bool:
        return self.worker_thread is not None and self.worker_thread.is_alive()

    def _set_generation_environment_locked(self, locked: bool) -> None:
        state = "disabled" if locked else "normal"
        readonly_state = "disabled" if locked else "readonly"
        self.model_button.configure(state=state)
        self.generate_button.configure(state=state)
        self.model_cache_entry.configure(state=state)
        self.model_cache_browse_button.configure(state=state)
        self.reference_entry.configure(state=state)
        self.reference_browse_button.configure(state=state)
        self.output_entry.configure(state=state)
        self.output_browse_button.configure(state=state)
        self.force_checkbutton.configure(state=state)
        self.device_combo.configure(state=readonly_state)

    def _resolve_reference_audio(self) -> Path | None:
        reference_text = self.reference_var.get().strip()
        if not reference_text:
            messagebox.showerror("Missing voice sample", "Choose a valid MP3 or WAV voice sample first.")
            return None

        try:
            reference_path = Path(reference_text).expanduser().resolve(strict=True)
        except FileNotFoundError:
            messagebox.showerror("Missing voice sample", "Choose a valid MP3 or WAV voice sample first.")
            return None

        if not reference_path.is_file():
            messagebox.showerror("Invalid voice sample", "The selected voice sample must be a file.")
            return None

        return reference_path

    def _ensure_model_ready(self) -> bool:
        if model_cache_ready(Path(self.model_cache_var.get()).expanduser()):
            return True

        messagebox.showerror(
            "Model not ready",
            "Download or load the model first so the app can verify the local cache.",
        )
        return False

    def _planned_output_path_for_row(self, row: SegmentRow) -> Path | None:
        row_index = self.segment_rows.index(row) + 1
        segment_id = row.id_var.get().strip() or f"segment_{row_index:03d}"
        raw_audio_filename = row.audio_filename_var.get().strip() or f"{segment_id}.mp3"

        try:
            output_dir = Path(self.output_dir_var.get()).expanduser().resolve()
            return planned_output_path(output_dir, raw_audio_filename)
        except ConfigError:
            return None

    def _refresh_playback_state(self, row: SegmentRow) -> None:
        output_path = self._planned_output_path_for_row(row)
        is_playing = self.playback_row is row and self.playback_process is not None and self.playback_process.poll() is None
        has_audio = output_path is not None and output_path.is_file() and output_path.stat().st_size > 0
        row.set_playing(is_playing)
        row.set_play_enabled(is_playing or has_audio)

    def _refresh_all_playback_states(self) -> None:
        for row in self.segment_rows:
            self._refresh_playback_state(row)

    def _stop_active_playback(self, *, log_message: str | None = None) -> None:
        process = self.playback_process
        row = self.playback_row
        self.playback_process = None
        self.playback_row = None

        if process is not None and process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=1)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=1)

        if row is not None:
            self._refresh_playback_state(row)
        if log_message:
            self.append_log(log_message, level="info")

    def toggle_segment_playback(self, row: SegmentRow) -> None:
        if self.playback_row is row and self.playback_process is not None and self.playback_process.poll() is None:
            self._stop_active_playback(log_message="Stopped playback.")
            return

        output_path = self._planned_output_path_for_row(row)
        if output_path is None or not output_path.is_file() or output_path.stat().st_size <= 0:
            messagebox.showerror("No audio yet", "Generate this segment first so there is an MP3 file to preview.")
            return

        try:
            ffplay = ensure_ffplay()
        except ConfigError as exc:
            messagebox.showerror("Playback unavailable", str(exc))
            return

        if self.playback_process is not None:
            self._stop_active_playback()

        try:
            self.playback_process = start_audio_playback(ffplay, output_path)
            self.playback_row = row
        except OSError as exc:
            self.playback_process = None
            self.playback_row = None
            messagebox.showerror("Playback failed", str(exc))
            return

        self._refresh_playback_state(row)
        self.append_log(f"Playing {output_path.name}", level="info")

    def _poll_playback_process(self) -> None:
        if self.playback_process is None:
            return
        if self.playback_process.poll() is None:
            return

        finished_row = self.playback_row
        self.playback_process = None
        self.playback_row = None
        if finished_row is not None:
            self._refresh_playback_state(finished_row)

    def _resolve_segment_for_row(self, row: SegmentRow) -> dict[str, str]:
        row_index = self.segment_rows.index(row) + 1
        payload = build_segments_payload(
            [row.get_draft()],
            starting_index=row_index,
        )
        if not payload["segments"]:
            raise ConfigError(f"Segment {row_index:02d} has no text.")

        segment = payload["segments"][0]
        row.apply_resolved_values(
            segment_id=segment["id"],
            audio_filename=segment["audio_filename"],
        )
        return segment

    def _set_row_idle(self, row: SegmentRow, *, detail: str = "Ready") -> None:
        row.set_status("Idle", "BadgeIdle.TLabel")
        row.set_detail(detail)
        row.stop_progress_animation()
        row.set_progress(0)
        row.set_editor_locked(False)
        row.set_generate_enabled(True)
        self._refresh_playback_state(row)
        row.set_remove_enabled(True)
        row.set_cancel_enabled(False)
        row.show_idle_controls()

    def _set_row_queued(self, row: SegmentRow, position: int, *, cancelling: bool = False) -> None:
        row.set_status("Queued", "BadgeBusy.TLabel")
        row.set_detail("Cancel requested..." if cancelling else f"In queue, position {position}")
        row.stop_progress_animation()
        row.set_progress(0)
        row.set_editor_locked(True)
        row.set_generate_enabled(False)
        self._refresh_playback_state(row)
        row.set_remove_enabled(False)
        row.set_cancel_enabled(not cancelling)
        row.show_cancel_controls()

    def _set_row_running(self, row: SegmentRow, *, detail: str = "Preparing...") -> None:
        if self.playback_row is row:
            self._stop_active_playback()
        row.set_status("Running", "BadgeBusy.TLabel")
        row.set_detail(detail)
        row.set_progress(5)
        row.set_editor_locked(True)
        row.set_generate_enabled(False)
        row.set_play_enabled(False)
        row.set_remove_enabled(False)
        row.set_cancel_enabled(True)
        row.show_cancel_controls()

    def _set_row_success(self, row: SegmentRow, *, detail: str) -> None:
        row.set_status("Done", "BadgeReady.TLabel")
        row.set_detail(detail)
        row.stop_progress_animation()
        row.set_progress(100)
        row.set_editor_locked(False)
        row.set_generate_enabled(True)
        self._refresh_playback_state(row)
        row.set_remove_enabled(True)
        row.set_cancel_enabled(False)
        row.show_idle_controls()

    def _set_row_skipped(self, row: SegmentRow, *, detail: str) -> None:
        row.set_status("Skipped", "BadgeReady.TLabel")
        row.set_detail(detail)
        row.stop_progress_animation()
        row.set_progress(100)
        row.set_editor_locked(False)
        row.set_generate_enabled(True)
        self._refresh_playback_state(row)
        row.set_remove_enabled(True)
        row.set_cancel_enabled(False)
        row.show_idle_controls()

    def _set_row_failed(self, row: SegmentRow, *, detail: str) -> None:
        row.set_status("Failed", "BadgeError.TLabel")
        row.set_detail(detail)
        row.stop_progress_animation()
        row.set_progress(0)
        row.set_editor_locked(False)
        row.set_generate_enabled(True)
        self._refresh_playback_state(row)
        row.set_remove_enabled(True)
        row.set_cancel_enabled(False)
        row.show_idle_controls()

    def _set_row_cancelled(self, row: SegmentRow, *, detail: str) -> None:
        row.set_status("Canceled", "BadgeIdle.TLabel")
        row.set_detail(detail)
        row.stop_progress_animation()
        row.set_progress(0)
        row.set_editor_locked(False)
        row.set_generate_enabled(True)
        self._refresh_playback_state(row)
        row.set_remove_enabled(True)
        row.set_cancel_enabled(False)
        row.show_idle_controls()

    def _refresh_queued_rows(self) -> None:
        with self.queue_lock:
            queued_jobs = list(self.pending_jobs)
            active_job = self.active_job

        for position, job in enumerate(queued_jobs, start=1):
            self._set_row_queued(job.row, position, cancelling=job.cancel_requested)

        if active_job is not None:
            self._set_row_running(active_job.row, detail=active_job.row.detail_var.get())

        worker_active = active_job is not None or bool(queued_jobs) or self.model_task_active or self._generation_worker_running()
        self._set_generation_environment_locked(worker_active)

    def _update_global_queue_progress(self) -> None:
        total = max(self.queue_session_total, 1)
        value = min(self.queue_session_completed, total)
        self.generation_progress.configure(mode="determinate", maximum=total, value=value)

        with self.queue_lock:
            queued = len(self.pending_jobs)
            active_job = self.active_job

        if self.model_task_active:
            self.generation_status_var.set("Downloading or loading model...")
        elif active_job is not None:
            self.generation_status_var.set(
                f"Running {active_job.segment['id']} ({self.queue_session_completed}/{self.queue_session_total} complete)"
            )
        elif queued:
            self.generation_status_var.set(f"{queued} segment(s) queued")
        elif self.queue_session_total > 0 and self.queue_session_completed >= self.queue_session_total:
            self.generation_status_var.set("Queue complete.")
        else:
            self.generation_status_var.set("Ready")

    def _start_generation_worker_if_needed(self) -> None:
        if self._generation_worker_running():
            return
        self.worker_settings = {
            "model_cache": Path(self.model_cache_var.get()).expanduser().resolve(),
            "device": self.device_var.get(),
            "multilingual": False,
            "language_id": "en",
            "exaggeration": 0.35,
            "cfg_weight": 0.3,
            "bitrate": "192k",
        }
        self.worker_thread = threading.Thread(target=self._generation_worker, daemon=True)
        self.worker_thread.start()

    def _enqueue_segment_jobs(self, rows: list[SegmentRow], *, strict: bool) -> int:
        if self.model_task_active:
            return 0

        if not self.row_jobs and self.queue_session_completed >= self.queue_session_total:
            self.queue_session_total = 0
            self.queue_session_completed = 0

        reference_path = self._resolve_reference_audio()
        if reference_path is None:
            return 0
        if not self._ensure_model_ready():
            return 0

        output_dir = Path(self.output_dir_var.get()).expanduser().resolve()
        force = self.force_var.get()
        queued_now = 0

        for row in rows:
            if row in self.row_jobs:
                continue

            try:
                segment = self._resolve_segment_for_row(row)
            except ConfigError:
                if strict:
                    raise
                continue

            job = SegmentJob(
                job_id=self.job_sequence + 1,
                row=row,
                segment=segment,
                output_dir=output_dir,
                reference_path=reference_path,
                force=force,
            )
            self.job_sequence += 1
            with self.queue_lock:
                self.pending_jobs.append(job)
                self.row_jobs[row] = job
            queued_now += 1
            self.append_log(f"Queued {segment['id']}", level="info")

        if queued_now == 0:
            if strict:
                raise ConfigError("This segment is already queued or has no valid text.")
            return 0

        self.queue_session_total += queued_now
        self._refresh_queued_rows()
        self._update_global_queue_progress()
        self._start_generation_worker_if_needed()
        return queued_now

    def _cancel_segment_job(self, row: SegmentRow) -> None:
        with self.queue_lock:
            job = self.row_jobs.get(row)
            if job is None:
                return

            if self.active_job is job:
                job.cancel_requested = True
                self.queue.put(("job_cancel_pending", job.job_id))
                return

            self.pending_jobs = [candidate for candidate in self.pending_jobs if candidate is not job]
            self.row_jobs.pop(row, None)

        self.queue_session_total = max(self.queue_session_total - 1, self.queue_session_completed)
        self._set_row_cancelled(row, detail="Removed from queue.")
        self.append_log(f"Canceled queued job for {job.segment['id']}", level="info")
        self._refresh_queued_rows()
        self._update_global_queue_progress()

    def load_json_file(self) -> None:
        if self.model_task_active or self.row_jobs:
            messagebox.showerror("Queue active", "Cancel queued jobs before loading a new JSON file.")
            return

        path = filedialog.askopenfilename(
            title="Choose segments JSON",
            filetypes=[("JSON files", "*.json"), ("All files", "*.*")],
        )
        if not path:
            return

        try:
            payload = load_json(Path(path))
            if not isinstance(payload, dict) or not isinstance(payload.get("segments"), list):
                raise ConfigError("JSON must be an object containing a 'segments' array.")
            segments = payload["segments"]
            if not segments:
                raise ConfigError("The selected JSON file has no segments.")
        except ConfigError as exc:
            messagebox.showerror("Invalid JSON", str(exc))
            return

        self._stop_active_playback()
        for row in self.segment_rows:
            row.destroy()
        self.segment_rows.clear()

        try:
            for segment in segments:
                if not isinstance(segment, dict):
                    raise ConfigError("Each segment must be an object.")
                self.add_segment_row(
                    segment_id=str(segment.get("id", "")),
                    audio_filename=str(segment.get("audio_filename", "")),
                    text=str(segment.get("text", "")),
                )
        except ConfigError as exc:
            messagebox.showerror("Invalid JSON", str(exc))
            self.clear_segments(confirm=False)
            return

        self.json_status_var.set(f"Loaded JSON: {path}")
        self.append_log(f"Loaded {len(segments)} segments from {path}", level="success")
        self._refresh_all_playback_states()

    def start_model_task(self) -> None:
        if self.model_task_active or self._generation_worker_running() or self.row_jobs:
            return

        self.model_task_active = True
        self._set_generation_environment_locked(True)
        self._set_model_badge("WORKING", "BadgeBusy.TLabel")
        self.model_status_var.set("Downloading or loading the model...")
        self.model_progress.configure(mode="indeterminate")
        self.model_progress.start(12)
        self.append_log("Starting model download/load...", level="info")
        config = self.build_run_config(download_model=True)
        threading.Thread(target=self._run_model_task, args=(config,), daemon=True).start()

    def start_generation_task(self) -> None:
        if self.model_task_active:
            messagebox.showerror("Model busy", "Wait for the model download/load task to finish first.")
            return

        try:
            queued_now = self._enqueue_segment_jobs(self.segment_rows, strict=False)
        except ConfigError as exc:
            messagebox.showerror("Invalid segments", str(exc))
            return

        if queued_now == 0 and not self.row_jobs:
            messagebox.showerror("Invalid segments", "Add at least one segment with text before generating.")

    def start_single_segment_task(self, row: SegmentRow) -> None:
        if self.model_task_active:
            messagebox.showerror("Model busy", "Wait for the model download/load task to finish first.")
            return

        try:
            self._enqueue_segment_jobs([row], strict=True)
        except ConfigError as exc:
            messagebox.showerror("Invalid segments", str(exc))
 
    def cancel_single_segment_task(self, row: SegmentRow) -> None:
        self._cancel_segment_job(row)

    def _run_model_task(self, config: RunConfig) -> None:
        try:
            exit_code = generate_segments(
                config,
                progress_callback=self._enqueue_progress,
                logger=self._enqueue_log,
                error_logger=self._enqueue_error,
            )
            self.queue.put(("done", ("model", exit_code)))
        except Exception as exc:
            self.queue.put(("exception", ("model", str(exc))))

    def _generation_worker(self) -> None:
        device = "cpu"
        model = None
        settings = dict(self.worker_settings or {})
        try:
            model_cache = Path(settings["model_cache"])
            ffmpeg = ensure_ffmpeg()
            device = select_device(str(settings["device"]))
            configure_model_cache(model_cache)
            self.queue.put(("worker_prepared", device))
            model = load_chatterbox_model(bool(settings["multilingual"]), device)
            self.queue.put(("worker_model_loaded", None))

            while True:
                with self.queue_lock:
                    if not self.pending_jobs:
                        self.active_job = None
                        break
                    job = self.pending_jobs.pop(0)
                    self.active_job = job

                self.queue.put(("job_started", job))
                output_path = planned_output_path(job.output_dir, job.segment["audio_filename"])

                try:
                    if output_path.exists() and output_path.stat().st_size > 0 and not job.force:
                        self.queue.put(
                            (
                                "job_finished",
                                (job, "skipped", f"Reused existing file {job.segment['audio_filename']}"),
                            )
                        )
                    else:
                        duration_seconds = generate_one_segment(
                            model=model,
                            segment=job.segment,
                            output_path=output_path,
                            reference_audio=job.reference_path,
                            multilingual=bool(settings["multilingual"]),
                            language_id=str(settings["language_id"]),
                            exaggeration=float(settings["exaggeration"]),
                            cfg_weight=float(settings["cfg_weight"]),
                            ffmpeg=ffmpeg,
                            bitrate=str(settings["bitrate"]),
                            progress_callback=lambda stage, current, total, job_id=job.job_id: self.queue.put(
                                ("segment_progress", (job_id, stage, current, total))
                            ),
                            cancel_callback=lambda job_ref=job: job_ref.cancel_requested,
                        )
                        detail = f"Saved {job.segment['audio_filename']}"
                        if duration_seconds is not None:
                            detail = f"{detail} ({duration_seconds:.2f}s)"
                        self.queue.put(("job_finished", (job, "generated", detail)))
                except GenerationCancelledError:
                    self.queue.put(("job_finished", (job, "cancelled", "Canceled before completion.")))
                except Exception as exc:
                    self.queue.put(("job_finished", (job, "failed", str(exc))))
                finally:
                    with self.queue_lock:
                        self.active_job = None
                        self.row_jobs.pop(job.row, None)
                    cleanup_device_memory(device)

            self.queue.put(("worker_idle", None))
        except Exception as exc:
            with self.queue_lock:
                active_job = self.active_job
                pending_jobs = list(self.pending_jobs)
                self.pending_jobs.clear()
                self.active_job = None
                if active_job is not None:
                    self.row_jobs.pop(active_job.row, None)
                for job in pending_jobs:
                    self.row_jobs.pop(job.row, None)
            failed_jobs = ([active_job] if active_job is not None else []) + pending_jobs
            self.queue.put(("worker_failed", (failed_jobs, str(exc))))
        finally:
            self.worker_settings = None
            cleanup_device_memory(device)

    def build_run_config(
        self,
        *,
        download_model: bool,
        segments_path: Path | None = None,
        reference_path: Path | None = None,
    ) -> RunConfig:
        return RunConfig(
            segments=segments_path,
            reference=reference_path,
            output_dir=Path(self.output_dir_var.get()).expanduser().resolve(),
            model_cache=Path(self.model_cache_var.get()).expanduser().resolve(),
            download_model=download_model,
            force=self.force_var.get(),
            dry_run=False,
            device=self.device_var.get(),
            multilingual=False,
            language_id="en",
            exaggeration=0.35,
            cfg_weight=0.3,
            bitrate="192k",
            env_file=None,
        )

    def refresh_model_status(self) -> None:
        cache_path = Path(self.model_cache_var.get()).expanduser()
        ready = model_cache_ready(cache_path)
        if self.model_task_active:
            self._set_model_badge("WORKING", "BadgeBusy.TLabel")
            self.model_status_var.set("Downloading or loading the model...")
        elif ready:
            self._set_model_badge("READY", "BadgeReady.TLabel")
            self.model_status_var.set("Model cache looks ready for generation.")
        else:
            self._set_model_badge("NOT READY", "BadgeIdle.TLabel")
            self.model_status_var.set("Download the Chatterbox model into the local cache.")
        self.model_detail_var.set(f"Cache: {cache_path}")

    def _set_model_badge(self, text: str, style_name: str) -> None:
        self.model_badge_var.set(text)
        self.model_badge.configure(style=style_name)

    def _enqueue_progress(self, event: ProgressEvent) -> None:
        self.queue.put(("progress", event))

    def _enqueue_log(self, message: str) -> None:
        self.queue.put(("log", message))

    def _enqueue_error(self, message: str) -> None:
        self.queue.put(("error", message))

    def _poll_queue(self) -> None:
        try:
            while True:
                kind, payload = self.queue.get_nowait()
                if kind == "progress":
                    self._handle_progress(payload)
                elif kind == "log":
                    self.append_log(str(payload), level="info")
                elif kind == "error":
                    self.append_log(str(payload), level="error")
                elif kind == "worker_prepared":
                    self._handle_worker_prepared(str(payload))
                elif kind == "worker_model_loaded":
                    self._handle_worker_model_loaded()
                elif kind == "job_started":
                    self._handle_job_started(payload)
                elif kind == "job_cancel_pending":
                    self._handle_job_cancel_pending(int(payload))
                elif kind == "segment_progress":
                    self._handle_segment_progress(*payload)
                elif kind == "job_finished":
                    self._handle_job_finished(*payload)
                elif kind == "worker_idle":
                    self._handle_worker_idle()
                elif kind == "worker_failed":
                    self._handle_worker_failed(*payload)
                elif kind == "done":
                    self._handle_task_done(*payload)
                elif kind == "exception":
                    self._handle_task_exception(*payload)
        except queue.Empty:
            pass
        finally:
            self._poll_playback_process()
            self.after(120, self._poll_queue)

    def _handle_progress(self, event: ProgressEvent) -> None:
        if event.stage == "model":
            if event.status == "working":
                self.model_status_var.set(event.message)
                self._set_model_badge("WORKING", "BadgeBusy.TLabel")
            elif event.status == "success":
                self.model_status_var.set(event.message)
                self._set_model_badge("READY", "BadgeReady.TLabel")
            elif event.status == "error":
                self.model_status_var.set(event.message)
                self._set_model_badge("ERROR", "BadgeError.TLabel")
            return

    def _handle_worker_prepared(self, device: str) -> None:
        self.generation_status_var.set(f"Preparing model on {device}...")
        self.append_log(f"Generation worker prepared on {device}", level="info")

    def _handle_worker_model_loaded(self) -> None:
        self.generation_status_var.set("Model loaded. Processing queue...")
        self.append_log("Generation model loaded.", level="success")

    def _handle_job_started(self, job: SegmentJob) -> None:
        self._set_row_running(job.row, detail="Preparing voice conditioning...")
        self.append_log(f"Started {job.segment['id']}", level="info")
        self._refresh_queued_rows()
        self._update_global_queue_progress()

    def _handle_job_cancel_pending(self, job_id: int) -> None:
        if self.active_job is None or self.active_job.job_id != job_id:
            return
        self.active_job.row.set_detail("Cancel requested...")
        self.active_job.row.set_cancel_enabled(False)

    def _handle_segment_progress(self, job_id: int, stage: str, current: int | None, total: int | None) -> None:
        job = self.active_job
        if job is None or job.job_id != job_id:
            return

        row = job.row
        if stage == "conditioning":
            row.set_status("Preparing", "BadgeBusy.TLabel")
            row.set_detail("Preparing voice conditioning...")
            row.set_progress(8)
        elif stage == "sampling":
            row.set_status("Sampling", "BadgeBusy.TLabel")
            if total and total > 0 and current is not None:
                percent = int((current / total) * 100)
                row.set_detail(f"Sampling {percent}%")
                row.set_progress(10 + (current / total) * 80)
            else:
                row.set_detail("Sampling...")
                row.start_progress_animation()
        elif stage == "encoding":
            row.stop_progress_animation()
            row.set_status("Encoding", "BadgeBusy.TLabel")
            row.set_detail("Encoding WAV...")
            row.set_progress(92)
        elif stage == "finalizing":
            row.stop_progress_animation()
            row.set_status("Finalizing", "BadgeBusy.TLabel")
            row.set_detail("Writing MP3...")
            row.set_progress(98)
        elif stage == "done":
            row.stop_progress_animation()
            row.set_progress(100)

    def _handle_job_finished(self, job: SegmentJob, result: str, detail: str) -> None:
        self.queue_session_completed += 1

        if result == "generated":
            self._set_row_success(job.row, detail=detail)
            self.append_log(f"Finished {job.segment['id']}", level="success")
        elif result == "skipped":
            self._set_row_skipped(job.row, detail=detail)
            self.append_log(f"Skipped {job.segment['id']}", level="info")
        elif result == "cancelled":
            self._set_row_cancelled(job.row, detail=detail)
            self.append_log(f"Canceled {job.segment['id']}", level="info")
        else:
            self._set_row_failed(job.row, detail=detail)
            self.append_log(f"Failed {job.segment['id']}: {detail}", level="error")

        self._refresh_queued_rows()
        self._update_global_queue_progress()

    def _handle_worker_idle(self) -> None:
        self.worker_thread = None
        self._refresh_queued_rows()
        self._update_global_queue_progress()

    def _handle_task_done(self, task_name: str, exit_code: int) -> None:
        if task_name == "model":
            self.model_progress.stop()
            self.model_progress.configure(mode="determinate", value=100, maximum=100)
            self.model_task_active = False
            self._set_generation_environment_locked(False)
            self.refresh_model_status()
            if exit_code == 0:
                self.append_log("Model is ready.", level="success")
            else:
                self._set_model_badge("ERROR", "BadgeError.TLabel")
                self.append_log("Model task finished with an error.", level="error")

    def _handle_task_exception(self, task_name: str, message: str) -> None:
        if task_name == "model":
            self.model_progress.stop()
            self._set_model_badge("ERROR", "BadgeError.TLabel")
            self.model_status_var.set(message)
        self.append_log(message, level="error")
        self.model_task_active = False
        self._set_generation_environment_locked(False)
        self._update_global_queue_progress()

    def _handle_worker_failed(self, jobs: list[SegmentJob], message: str) -> None:
        self.worker_thread = None
        for job in jobs:
            self.queue_session_completed += 1
            self._set_row_failed(job.row, detail=message)
        self.append_log(message, level="error")
        self._refresh_queued_rows()
        self._update_global_queue_progress()

    def append_log(self, message: str, *, level: str) -> None:
        timestamp = time.strftime("%H:%M:%S")
        self.log_widget.configure(state="normal")
        self.log_widget.insert("end", f"[{timestamp}] {message}\n", level)
        self.log_widget.configure(state="disabled")
        self.log_widget.see("end")


def launch_gui() -> None:
    app = LocalTTSApp()
    app.mainloop()
