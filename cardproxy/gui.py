import argparse
import os
import queue
import shutil
import threading
import tkinter as tk
import traceback
from itertools import batched
from math import ceil
from tempfile import mkdtemp
from tkinter import filedialog, messagebox, ttk

from PIL import Image, ImageTk
from pyfiglet import figlet_format
from yaml import safe_load

from .core import (
    AppConfig,
    Canvas,
    CardModel,
    CardProxyError,
    FABProxifier,
    MTGProxifier,
    filter_fab_deck_lines,
    is_fab_collection_outdated,
    normalize_config_paths,
    parse_decklist,
    refresh_fab_collection,
)

_HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_GUI_CONFIG_PATH = os.path.join(
    _HERE,
    "config",
    "gui",
    "default_config.yaml",
)
ICON_PATH = os.path.join(_HERE, "assets", "icon.png")

# --- Dark palette ---
BG = "#0f172a"  # base background
ELEV = "#1f2937"  # elevated / input surface
BORDER = "#334155"  # subtle border
FG = "#e5e7eb"  # primary text
FG_MUTED = "#94a3b8"  # secondary text
ACCENT = "#3b82f6"  # brand blue
ACCENT_FG = "#ffffff"  # text on accent backgrounds
ACCENT_HOVER = "#2563eb"
ACCENT_ACTIVE = "#1d4ed8"
VIEWER_BG = "#0b1220"  # preview canvas background

# --- Fonts ---
FONT_UI = ("Segoe UI", 10)
FONT_UI_BOLD = ("Segoe UI", 10, "bold")
FONT_HEADING = ("Segoe UI", 11, "bold")
FONT_MONO = ("Cascadia Mono", 10)
FONT_MONO_SMALL = ("Cascadia Mono", 8)


class CardProxyPrinterGUI:
    def __init__(self, root: tk.Tk, default_config_path: str | None = None) -> None:
        self.root = root
        self.root.title("Card Proxy Printer")
        self.root.geometry("1280x820")

        # Ship the package icon as the window / taskbar icon.
        self._app_icon: ImageTk.PhotoImage | None = None
        if os.path.exists(ICON_PATH):
            try:
                self._app_icon = ImageTk.PhotoImage(Image.open(ICON_PATH))
            except (OSError, tk.TclError):
                self._app_icon = None
        self._apply_icon(self.root)

        # Cached ASCII banner used as the empty-preview placeholder.
        try:
            self._ascii_art = figlet_format(
                "CARD PROXY PRINTER", font="slant", width=150
            )
        except Exception:
            self._ascii_art = ""

        self.event_queue: queue.Queue = queue.Queue()
        self.render_thread: threading.Thread | None = None
        self.save_thread: threading.Thread | None = None
        self._save_dialog: tk.Toplevel | None = None
        self.collection_check_thread: threading.Thread | None = None
        self.collection_regen_thread: threading.Thread | None = None
        self._collection_regen_dialog: tk.Toplevel | None = None
        self._collection_check_started: bool = False
        self.raw_config: AppConfig | None = None
        self.render_tmpdir: str | None = None
        self.render_canvas: Canvas | None = None
        self.page_paths: list[str] = []
        self.current_page: int = 0
        self._photo: ImageTk.PhotoImage | None = None
        self._current_img: Image.Image | None = None
        self._current_page_path: str | None = None
        self.zoom: float = 1.0
        self._zoom_min: float = 0.1
        self._zoom_max: float = 4.0

        self._build_ui()
        self.root.after(50, self._force_visible)
        self.root.after(100, self._process_queue)
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

        if default_config_path and os.path.exists(default_config_path):
            self._load_config(default_config_path)

        # Runs once mainloop starts pumping, after the window has been drawn.
        self.root.after(100, self._start_collection_update_check)

    def _force_visible(self) -> None:
        # WSLg/Tk sometimes maps the window off-screen; re-applying geometry
        # after mapping and lifting the window makes it visible.
        self.root.geometry("1280x820+100+100")
        self.root.deiconify()
        self.root.lift()
        self.root.focus_force()

    def _apply_icon(self, win: tk.Misc) -> None:
        # WSLg / some WMs don't reliably inherit the root's default icon.
        if self._app_icon is None:
            return
        try:
            win.iconphoto(False, self._app_icon)
        except tk.TclError:
            pass

    def _build_ui(self) -> None:
        self.root.configure(background=BG)
        # Style the ttk.Combobox popup Listbox (not a ttk widget itself).
        self.root.option_add("*TCombobox*Listbox.background", ELEV)
        self.root.option_add("*TCombobox*Listbox.foreground", FG)
        self.root.option_add("*TCombobox*Listbox.selectBackground", ACCENT)
        self.root.option_add("*TCombobox*Listbox.selectForeground", ACCENT_FG)
        self.root.option_add("*TCombobox*Listbox.font", FONT_UI)
        self.root.option_add("*TCombobox*Listbox.borderWidth", 0)

        style = ttk.Style()
        # 'clam' honors color overrides on ttk widgets; native themes ignore them.
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass

        style.configure(".", background=BG, foreground=FG, font=FONT_UI)
        style.configure("TFrame", background=BG)
        style.configure("TLabel", background=BG, foreground=FG)
        style.configure("Heading.TLabel", font=FONT_HEADING, foreground=FG)
        style.configure("Muted.TLabel", foreground=FG_MUTED)
        style.configure(
            "PageBadge.TLabel",
            background=ELEV,
            foreground=FG,
            padding=(12, 4),
            font=FONT_UI_BOLD,
        )

        style.configure(
            "TButton",
            background=ELEV,
            foreground=FG,
            borderwidth=0,
            focusthickness=0,
            padding=(14, 7),
        )
        style.map(
            "TButton",
            background=[("active", BORDER), ("pressed", BORDER)],
            foreground=[("disabled", FG_MUTED)],
        )
        style.configure(
            "Accent.TButton",
            background=ACCENT,
            foreground=ACCENT_FG,
            borderwidth=0,
            padding=(14, 7),
            font=FONT_UI_BOLD,
        )
        style.map(
            "Accent.TButton",
            background=[
                ("disabled", BORDER),
                ("pressed", ACCENT_ACTIVE),
                ("active", ACCENT_HOVER),
            ],
            foreground=[("disabled", FG_MUTED)],
        )
        style.configure(
            "Nav.TButton",
            background=ELEV,
            foreground=FG,
            borderwidth=0,
            padding=(10, 6),
            font=FONT_UI_BOLD,
        )
        style.map(
            "Nav.TButton",
            background=[("active", BORDER), ("pressed", BORDER)],
        )

        style.configure(
            "TCombobox",
            fieldbackground=ELEV,
            background=ELEV,
            foreground=FG,
            arrowcolor=FG,
            bordercolor=BORDER,
            lightcolor=BORDER,
            darkcolor=BORDER,
            borderwidth=0,
            padding=(8, 4),
        )
        style.map(
            "TCombobox",
            fieldbackground=[("readonly", ELEV)],
            foreground=[("readonly", FG)],
            selectbackground=[("readonly", ELEV)],
            selectforeground=[("readonly", FG)],
        )

        style.configure(
            "Modern.Horizontal.TProgressbar",
            troughcolor=ELEV,
            background=ACCENT,
            bordercolor=ELEV,
            lightcolor=ACCENT,
            darkcolor=ACCENT,
            thickness=14,
        )

        footer = ttk.Frame(self.root, padding=(16, 8, 16, 14))
        footer.pack(side="bottom", fill="x")

        status_row = ttk.Frame(footer)
        status_row.pack(fill="x", pady=(0, 6))
        self.status_var = tk.StringVar(value="Ready.")
        ttk.Label(
            status_row,
            textvariable=self.status_var,
            anchor="w",
            style="Muted.TLabel",
        ).pack(side="left", fill="x", expand=True)
        self.progress_pct_var = tk.StringVar(value="")
        ttk.Label(
            status_row,
            textvariable=self.progress_pct_var,
            anchor="e",
            width=6,
            style="Muted.TLabel",
        ).pack(side="right")

        self.progress_var = tk.DoubleVar(value=0.0)
        self.progress = ttk.Progressbar(
            footer,
            orient="horizontal",
            mode="determinate",
            maximum=100,
            variable=self.progress_var,
            style="Modern.Horizontal.TProgressbar",
        )
        self.progress.pack(fill="x")

        left = ttk.Frame(self.root, padding=(16, 16, 8, 8))
        left.pack(side="left", fill="y")

        game_row = ttk.Frame(left)
        game_row.grid(row=0, column=0, sticky="w")
        ttk.Label(game_row, text="Game", style="Muted.TLabel").pack(side="left")
        self.game_var = tk.StringVar(value="fab")
        ttk.Combobox(
            game_row,
            textvariable=self.game_var,
            values=["fab", "mtg"],
            state="readonly",
            width=8,
        ).pack(side="left", padx=(6, 16))
        ttk.Label(game_row, text="Cards grid", style="Muted.TLabel").pack(side="left")
        self.grid_w_var = tk.IntVar(value=1)
        self.grid_h_var = tk.IntVar(value=1)
        spin_opts = {
            "bg": ELEV,
            "fg": FG,
            "buttonbackground": BORDER,
            "insertbackground": FG,
            "highlightthickness": 0,
            "relief": "flat",
            "font": FONT_UI,
        }
        tk.Spinbox(
            game_row, from_=1, to=5, textvariable=self.grid_w_var, width=3, **spin_opts
        ).pack(side="left", padx=(6, 4))
        tk.Spinbox(
            game_row, from_=1, to=5, textvariable=self.grid_h_var, width=3, **spin_opts
        ).pack(side="left")

        sizes_row = ttk.Frame(left)
        sizes_row.grid(row=1, column=0, sticky="w", pady=(12, 0))
        self.paper_size_display_var = tk.StringVar(value="210 × 297 mm")
        _card_defaults = CardModel()
        _sizes = (
            (
                "Card",
                f"{_card_defaults.width_mm:g} × {_card_defaults.height_mm:g} mm",
                None,
            ),
            ("Paper", None, self.paper_size_display_var),
            ("Bleed", f"{_card_defaults.bleed_mm:g} mm", None),
            ("DPI", f"{_card_defaults.dpi:g}", None),
        )
        for i, (label, static_text, var) in enumerate(_sizes):
            r, c = divmod(i, 2)
            pad_top = 0 if r == 0 else 2
            pad_left = 0 if c == 0 else 24
            ttk.Label(sizes_row, text=label, style="Muted.TLabel").grid(
                row=r,
                column=c * 2,
                sticky="w",
                padx=(pad_left, 14),
                pady=(pad_top, 0),
            )
            if var is not None:
                ttk.Label(sizes_row, textvariable=var).grid(
                    row=r, column=c * 2 + 1, sticky="w", pady=(pad_top, 0)
                )
            else:
                ttk.Label(sizes_row, text=static_text).grid(
                    row=r, column=c * 2 + 1, sticky="w", pady=(pad_top, 0)
                )

        ttk.Label(left, text="Decklist", style="Heading.TLabel").grid(
            row=2, column=0, sticky="w", pady=(16, 6)
        )
        self.deck_text = tk.Text(
            left,
            width=52,
            height=28,
            undo=True,
            bg=ELEV,
            fg=FG,
            insertbackground=FG,
            selectbackground=ACCENT,
            selectforeground=ACCENT_FG,
            highlightthickness=1,
            highlightbackground=BORDER,
            highlightcolor=ACCENT,
            relief="flat",
            padx=10,
            pady=10,
            font=FONT_MONO,
        )
        self.deck_text.grid(row=3, column=0, sticky="nsew")
        left.rowconfigure(3, weight=1)
        self._bind_paste_normalize(self.deck_text)

        deck_row = ttk.Frame(left)
        deck_row.grid(row=4, column=0, sticky="ew", pady=(10, 0))
        # 'uniform' forces equal column widths regardless of button text length.
        deck_row.columnconfigure(0, weight=1, uniform="btncol")
        deck_row.columnconfigure(1, weight=1, uniform="btncol")
        ttk.Button(
            deck_row, text="Load Decklist", command=self._open_paste_deck_dialog
        ).grid(row=0, column=0, sticky="ew", padx=(0, 4))
        ttk.Button(
            deck_row,
            text="Clear",
            command=self._clear_deck,
        ).grid(row=0, column=1, sticky="ew", padx=(4, 0))

        action_row = ttk.Frame(left)
        action_row.grid(row=5, column=0, sticky="ew", pady=(16, 0))
        action_row.columnconfigure(0, weight=1, uniform="btncol")
        action_row.columnconfigure(1, weight=1, uniform="btncol")
        self.render_btn = ttk.Button(
            action_row, text="Render", command=self._render, style="Accent.TButton"
        )
        self.render_btn.grid(row=0, column=0, sticky="ew", padx=(0, 4))
        self.save_btn = ttk.Button(
            action_row, text="Save PDF", command=self._save_pdf, state="disabled"
        )
        self.save_btn.grid(row=0, column=1, sticky="ew", padx=(4, 0))

        right = ttk.Frame(self.root, padding=(8, 16, 16, 8))
        right.pack(side="right", fill="both", expand=True)

        # Canvas (not Label): drawing an image doesn't grow the widget, so the
        # <Configure> → resize → <Configure> feedback loop can't happen.
        self.viewer = tk.Canvas(
            right,
            background=VIEWER_BG,
            highlightthickness=1,
            highlightbackground=BORDER,
        )
        self.viewer.pack(fill="both", expand=True)
        self.viewer.bind("<Configure>", lambda _e: self._refresh_viewer())
        # Wheel = zoom (Linux uses Button-4/5, Windows/macOS use MouseWheel).
        self.viewer.bind("<Button-4>", lambda _e: self._zoom_in())
        self.viewer.bind("<Button-5>", lambda _e: self._zoom_out())
        self.viewer.bind(
            "<MouseWheel>",
            lambda e: self._zoom_in() if e.delta > 0 else self._zoom_out(),
        )
        # Left-drag pans when zoomed beyond the viewer.
        self.viewer.bind("<ButtonPress-1>", lambda e: self.viewer.scan_mark(e.x, e.y))
        self.viewer.bind(
            "<B1-Motion>", lambda e: self.viewer.scan_dragto(e.x, e.y, gain=1)
        )

        nav_row = ttk.Frame(right)
        nav_row.pack(pady=(10, 0))
        ttk.Button(
            nav_row, text="◀", width=3, command=self._prev_page, style="Nav.TButton"
        ).pack(side="left")
        self.page_label = ttk.Label(
            nav_row,
            text="0 / 0",
            width=10,
            anchor="center",
            style="PageBadge.TLabel",
        )
        self.page_label.pack(side="left", padx=8)
        ttk.Button(
            nav_row, text="▶", width=3, command=self._next_page, style="Nav.TButton"
        ).pack(side="left")

        ttk.Frame(nav_row, width=32).pack(side="left")

        ttk.Button(
            nav_row, text="−", width=3, command=self._zoom_out, style="Nav.TButton"
        ).pack(side="left")
        self.zoom_var = tk.StringVar(value="100%")
        ttk.Label(
            nav_row,
            textvariable=self.zoom_var,
            width=7,
            anchor="center",
            style="PageBadge.TLabel",
        ).pack(side="left", padx=8)
        ttk.Button(
            nav_row, text="+", width=3, command=self._zoom_in, style="Nav.TButton"
        ).pack(side="left")
        ttk.Frame(nav_row, width=8).pack(side="left")
        ttk.Button(
            nav_row, text="Fit", command=self._zoom_fit, style="Nav.TButton"
        ).pack(side="left")

    def _load_config(self, path: str) -> None:
        try:
            with open(path, encoding="utf-8") as f:
                raw = safe_load(f) or {}
        except Exception as e:
            messagebox.showerror("Config error", str(e))
            return

        required = ("card_game_alias", "path_to_database")
        missing = [k for k in required if k not in raw]
        if missing:
            messagebox.showerror(
                "Config error", f"Missing keys in {path}: {', '.join(missing)}"
            )
            return

        normalize_config_paths(raw)

        try:
            cfg = AppConfig.model_validate(raw)
        except Exception as e:
            messagebox.showerror("Config error", f"Invalid config: {e}")
            return

        self.raw_config = cfg
        self.game_var.set(cfg.card_game_alias)
        self.grid_w_var.set(cfg.cards_per_page_width)
        self.grid_h_var.set(cfg.cards_per_page_height)
        self.paper_size_display_var.set(
            f"{cfg.paper_width_mm:g} × {cfg.paper_height_mm:g} mm"
        )

    def _bind_paste_normalize(self, widget: tk.Text) -> None:
        # Rewrite pasted CRLF/CR into LF so Windows-copied text doesn't leave
        # stray '\r' characters in the widget.
        def _on_paste(_event: tk.Event) -> str:
            try:
                content = widget.clipboard_get()
            except tk.TclError:
                return "break"
            content = content.replace("\r\n", "\n").replace("\r", "\n")
            if widget.tag_ranges("sel"):
                widget.delete("sel.first", "sel.last")
            widget.insert("insert", content)
            widget.see("insert")
            return "break"

        widget.bind("<<Paste>>", _on_paste)

    def _open_paste_deck_dialog(self) -> None:
        dialog = tk.Toplevel(self.root)
        dialog.title("Load Decklist")
        dialog.transient(self.root)
        dialog.resizable(True, True)
        dialog.configure(background=BG)
        self._apply_icon(dialog)

        w, h = 620, 520
        self._center_dialog_on_root(dialog, w, h)

        body = ttk.Frame(dialog, padding=20)
        body.pack(fill="both", expand=True)

        ttk.Label(body, text="Load Decklist", style="Heading.TLabel").pack(anchor="w")
        ttk.Label(
            body,
            text="Supports Fabrary text exports and plain 'count name (pitch)' lines.",
            style="Muted.TLabel",
        ).pack(anchor="w", pady=(4, 12))

        text = tk.Text(
            body,
            width=70,
            height=20,
            undo=True,
            bg=ELEV,
            fg=FG,
            insertbackground=FG,
            selectbackground=ACCENT,
            selectforeground=ACCENT_FG,
            highlightthickness=1,
            highlightbackground=BORDER,
            highlightcolor=ACCENT,
            relief="flat",
            padx=10,
            pady=10,
            font=FONT_MONO,
        )
        text.pack(fill="both", expand=True)
        self._bind_paste_normalize(text)

        btn_row = ttk.Frame(body)
        btn_row.pack(anchor="e", pady=(12, 0))

        def dismiss() -> None:
            try:
                dialog.grab_release()
            except tk.TclError:
                pass
            dialog.destroy()

        def on_load() -> None:
            content = (
                text.get("1.0", "end").replace("\r\n", "\n").replace("\r", "\n").strip()
            )
            dismiss()
            if not content:
                return
            cleaned = filter_fab_deck_lines(content)
            if not cleaned:
                return
            self.deck_text.delete("1.0", "end")
            self.deck_text.insert("1.0", cleaned)
            self.status_var.set("Loaded pasted decklist.")
            self._maybe_auto_render()

        ttk.Button(btn_row, text="Cancel", command=dismiss).pack(
            side="right", padx=(8, 0)
        )
        ttk.Button(
            btn_row,
            text="Load",
            command=on_load,
            style="Accent.TButton",
        ).pack(side="right")

        dialog.protocol("WM_DELETE_WINDOW", dismiss)
        dialog.grab_set()
        dialog.lift()
        dialog.focus_force()
        text.focus_set()

    def _clear_deck(self) -> None:
        self.deck_text.delete("1.0", "end")
        self._reset_preview()
        self.status_var.set("Ready.")

    def _reset_preview(self) -> None:
        self._cleanup_render_tmpdir()
        self.page_paths = []
        self.current_page = 0
        self.render_canvas = None
        self._update_page_label()
        self.viewer.delete("all")
        self._photo = None
        self._current_img = None
        self._current_page_path = None
        self.zoom = 1.0
        self.zoom_var.set("100%")
        self.save_btn.configure(state="disabled")
        self.progress_var.set(0.0)
        self.progress_pct_var.set("")

    def _maybe_auto_render(self) -> None:
        # Skip silently if we don't yet have both a config and a decklist.
        if not self.raw_config:
            return
        if not self.deck_text.get("1.0", "end").strip():
            return
        self._render()

    def _render(self) -> None:
        if self.render_thread and self.render_thread.is_alive():
            return
        if not self.raw_config:
            messagebox.showwarning("No config", "Load a config file first.")
            return

        deck_text = self.deck_text.get("1.0", "end").strip()
        if not deck_text:
            messagebox.showwarning("Empty deck", "Enter or load a decklist.")
            return

        try:
            grid_w = int(self.grid_w_var.get())
            grid_h = int(self.grid_h_var.get())
        except tk.TclError:
            messagebox.showerror(
                "Cards layout", "Cards layout dimensions must be integers."
            )
            return

        self._reset_preview()
        self.progress_pct_var.set("0%")
        self.render_btn.configure(state="disabled")
        self.status_var.set("Rendering...")

        try:
            cfg = self.raw_config.model_copy(
                update={
                    "card_game_alias": self.game_var.get(),
                    "cards_per_page_width": grid_w,
                    "cards_per_page_height": grid_h,
                }
            )
        except Exception as e:
            messagebox.showerror("Config error", str(e))
            return

        self.render_thread = threading.Thread(
            target=self._render_worker,
            args=(deck_text, cfg),
            daemon=True,
        )
        self.render_thread.start()

    def _render_worker(self, deck_text: str, cfg: AppConfig) -> None:
        deck_dir = None
        try:
            game = cfg.card_game_alias
            data_root = cfg.path_to_database

            deck_dir = mkdtemp(prefix="cpp_gui_deck_")
            with open(os.path.join(deck_dir, "deck.txt"), "w", encoding="utf-8") as f:
                f.write(deck_text)

            collection_input = cfg.path_to_collection_input or ""
            # Match parse_config: append the game alias if not already there.
            if collection_input and os.path.basename(collection_input) != game:
                collection_input = os.path.join(collection_input, game)
            collection_output = os.path.join(data_root, game, "collection")

            if game == "fab":
                proxifier = FABProxifier(
                    sr_weights_path=cfg.path_to_sr_weights,
                    denoise_weights_path=cfg.path_to_denoise_weights,
                    collection_input_path=collection_input,
                    collection_output_path=collection_output,
                    interactive=False,
                )
            elif game == "mtg":
                proxifier = MTGProxifier(
                    sr_weights_path=cfg.path_to_sr_weights,
                    denoise_weights_path=cfg.path_to_denoise_weights,
                )
            else:
                raise CardProxyError(f"Unsupported game alias: {game}")

            canvas_obj = Canvas(
                dpi=cfg.dpi,
                cards_per_page_width=cfg.cards_per_page_width,
                cards_per_page_height=cfg.cards_per_page_height,
                paper_width_mm=cfg.paper_width_mm,
                paper_height_mm=cfg.paper_height_mm,
            )

            decklist = parse_decklist(deck_dir, game)
            total = len(decklist)

            main_cards: list = []
            main_tokens: list = []
            processed_token_names: list[str] = []
            for idx, entry in enumerate(decklist, start=1):
                self.event_queue.put(("status", f"Fetching {idx}/{total}..."))
                payload = proxifier.generate_card(
                    entry.first_part,
                    entry.second_part,
                    canvas_obj.on_canvas_card_width_pixels,
                    canvas_obj.on_canvas_card_height_pixels,
                )
                self.event_queue.put(("progress", (idx, total)))
                if payload is None:
                    continue
                cards, tokens = payload
                for card in cards:
                    for _ in range(entry.count):
                        main_cards.append(card)
                for tok_name, tok in tokens.items():
                    if tok_name not in processed_token_names:
                        main_tokens.append(tok)
                        processed_token_names.append(tok_name)

            all_items = main_cards + main_tokens
            per_page = (
                canvas_obj.num_cards_per_page_width
                * canvas_obj.num_cards_per_page_height
            )
            num_pages = ceil(len(all_items) / per_page) if all_items else 0

            page_dir = mkdtemp(prefix="cpp_gui_pages_")
            for batch_index, batch_cards in enumerate(batched(all_items, per_page)):
                canvas_obj.new_page(batch_index + 1, num_pages)
                canvas_obj.fill_page(batch_cards)
                canvas_obj.save_page(page_dir)
                page_path = os.path.join(
                    page_dir,
                    f"{str(batch_index + 1).zfill(2)}.{canvas_obj.image_ext}",
                )
                self.event_queue.put(("page", page_path))

            self.event_queue.put(("done", (canvas_obj, page_dir)))
        except Exception as e:
            self.event_queue.put(
                ("error", f"{type(e).__name__}: {e}\n{traceback.format_exc()}")
            )
        finally:
            if deck_dir and os.path.exists(deck_dir):
                shutil.rmtree(deck_dir, ignore_errors=True)

    def _process_queue(self) -> None:
        try:
            while True:
                kind, payload = self.event_queue.get_nowait()
                if kind == "status":
                    self.status_var.set(payload)
                elif kind == "progress":
                    current, total = payload
                    pct = 100.0 * current / total if total else 0.0
                    self.progress_var.set(pct)
                    self.progress_pct_var.set(f"{int(pct)}%")
                elif kind == "page":
                    self.page_paths.append(payload)
                    if len(self.page_paths) == 1:
                        self.current_page = 0
                        self._refresh_viewer()
                    self._update_page_label()
                elif kind == "done":
                    self.render_canvas, self.render_tmpdir = payload
                    self.render_btn.configure(state="normal")
                    self.save_btn.configure(
                        state="normal" if self.page_paths else "disabled"
                    )
                    self.progress_var.set(100.0)
                    self.progress_pct_var.set("100%")
                    self.status_var.set(f"Rendered {len(self.page_paths)} page(s).")
                elif kind == "error":
                    self.render_btn.configure(state="normal")
                    self.progress_var.set(0.0)
                    self.progress_pct_var.set("")
                    self.status_var.set("Render failed.")
                    messagebox.showerror("Render error", payload)
                elif kind == "save_done":
                    self._close_saving_dialog()
                    self.save_btn.configure(state="normal")
                    self.status_var.set(f"Saved PDF to {payload}.")
                elif kind == "save_error":
                    self._close_saving_dialog()
                    self.save_btn.configure(state="normal")
                    self.status_var.set("Save failed.")
                    messagebox.showerror("Save error", payload)
                elif kind == "collection_update":
                    self._prompt_collection_update(*payload)
                elif kind == "collection_regen_done":
                    self._close_regen_dialog()
                    self.status_var.set("Card collection regenerated.")
                elif kind == "collection_regen_error":
                    self._close_regen_dialog()
                    self.status_var.set("Card collection regeneration failed.")
                    messagebox.showerror("Regeneration error", payload)
        except queue.Empty:
            pass
        self.root.after(100, self._process_queue)

    def _refresh_viewer(self) -> None:
        if not self.page_paths:
            self._draw_placeholder()
            return
        page_path = self.page_paths[self.current_page]
        if page_path != self._current_page_path:
            try:
                self._current_img = Image.open(page_path).copy()
            except (OSError, ValueError):
                return
            self._current_page_path = page_path
        img = self._current_img
        if img is None:
            return
        vw = max(1, self.viewer.winfo_width())
        vh = max(1, self.viewer.winfo_height())
        # Fit-to-view baseline scaled by the user's zoom multiplier.
        fit = min(vw / img.width, vh / img.height)
        scale = fit * self.zoom
        new_w = max(1, int(img.width * scale))
        new_h = max(1, int(img.height * scale))
        resized = img.resize((new_w, new_h), Image.LANCZOS)
        self._photo = ImageTk.PhotoImage(resized)
        self.viewer.delete("all")
        canvas_w = max(new_w, vw)
        canvas_h = max(new_h, vh)
        self.viewer.configure(scrollregion=(0, 0, canvas_w, canvas_h))
        self.viewer.create_image(
            canvas_w // 2, canvas_h // 2, image=self._photo, anchor="center"
        )

    def _draw_placeholder(self) -> None:
        vw = max(1, self.viewer.winfo_width())
        vh = max(1, self.viewer.winfo_height())
        self.viewer.delete("all")
        self.viewer.configure(scrollregion=(0, 0, vw, vh))
        if not self._ascii_art:
            return
        self.viewer.create_text(
            vw // 2,
            vh // 2,
            text=self._ascii_art,
            font=FONT_MONO_SMALL,
            fill=BORDER,
            anchor="center",
            justify="left",
        )

    def _zoom_in(self) -> None:
        self._set_zoom(self.zoom * 1.25)

    def _zoom_out(self) -> None:
        self._set_zoom(self.zoom / 1.25)

    def _zoom_fit(self) -> None:
        self._set_zoom(1.0)

    def _set_zoom(self, factor: float) -> None:
        self.zoom = max(self._zoom_min, min(self._zoom_max, factor))
        self.zoom_var.set(f"{round(self.zoom * 100)}%")
        self._refresh_viewer()

    def _update_page_label(self) -> None:
        total = len(self.page_paths)
        current = self.current_page + 1 if total else 0
        self.page_label.configure(text=f"{current} / {total}")

    def _prev_page(self) -> None:
        if not self.page_paths:
            return
        self.current_page = (self.current_page - 1) % len(self.page_paths)
        self._refresh_viewer()
        self._update_page_label()

    def _next_page(self) -> None:
        if not self.page_paths:
            return
        self.current_page = (self.current_page + 1) % len(self.page_paths)
        self._refresh_viewer()
        self._update_page_label()

    def _save_pdf(self) -> None:
        if not self.render_canvas or not self.render_tmpdir:
            return
        if self.save_thread and self.save_thread.is_alive():
            return
        out_dir = filedialog.askdirectory(title="Save PDF to...")
        if not out_dir:
            return

        self.save_btn.configure(state="disabled")
        self.status_var.set("Saving PDF...")
        self._open_saving_dialog(out_dir)

        canvas_obj = self.render_canvas
        tmpdir = self.render_tmpdir
        game = self.game_var.get()

        def worker() -> None:
            try:
                canvas_obj.save_pdf(tmpdir, out_dir, game)
                self.event_queue.put(("save_done", out_dir))
            except Exception as e:
                self.event_queue.put(("save_error", f"{type(e).__name__}: {e}"))

        self.save_thread = threading.Thread(target=worker, daemon=True)
        self.save_thread.start()

    def _open_saving_dialog(self, out_dir: str) -> None:
        dialog = tk.Toplevel(self.root)
        dialog.title("Saving")
        dialog.transient(self.root)
        dialog.resizable(False, False)
        dialog.configure(background=BG)
        self._apply_icon(dialog)
        # Block closing the dialog while the save is in flight.
        dialog.protocol("WM_DELETE_WINDOW", lambda: None)

        w, h = 380, 140
        self._center_dialog_on_root(dialog, w, h)

        body = ttk.Frame(dialog, padding=20)
        body.pack(fill="both", expand=True)

        ttk.Label(body, text="Saving PDF...", style="Heading.TLabel").pack(anchor="w")
        ttk.Label(
            body,
            text=out_dir,
            style="Muted.TLabel",
            wraplength=w - 60,
            justify="left",
        ).pack(anchor="w", pady=(4, 12))

        pb = ttk.Progressbar(
            body,
            mode="indeterminate",
            style="Modern.Horizontal.TProgressbar",
            length=w - 60,
        )
        pb.pack(fill="x")
        pb.start(12)

        dialog.grab_set()
        self._save_dialog = dialog

    def _close_saving_dialog(self) -> None:
        if self._save_dialog is not None:
            try:
                self._save_dialog.grab_release()
            except tk.TclError:
                pass
            self._save_dialog.destroy()
            self._save_dialog = None

    def _center_dialog_on_root(self, dialog: tk.Toplevel, w: int, h: int) -> None:
        # Two-step geometry (size then position) survives quirky WMs better
        # than combining them, and "update_idletasks" on both windows makes
        # sure winfo_root{x,y} / winfo_{width,height} are already flushed.
        dialog.geometry(f"{w}x{h}")
        dialog.update_idletasks()
        self.root.update_idletasks()
        px = self.root.winfo_rootx()
        py = self.root.winfo_rooty()
        pw = self.root.winfo_width()
        ph = self.root.winfo_height()
        x = max(px + (pw - w) // 2, 0)
        y = max(py + (ph - h) // 2, 0)
        dialog.geometry(f"+{x}+{y}")

    def _collection_paths(self) -> tuple[str, str] | None:
        # Mirror the path plumbing the render worker uses.
        cfg = self.raw_config
        if cfg is None or cfg.card_game_alias != "fab":
            return None
        collection_input = cfg.path_to_collection_input or ""
        data_root = cfg.path_to_database or ""
        game = cfg.card_game_alias
        if not collection_input or not data_root:
            return None
        if os.path.basename(collection_input) != game:
            collection_input = os.path.join(collection_input, game)
        collection_output = os.path.join(data_root, game, "collection")
        return collection_input, collection_output

    def _start_collection_update_check(self) -> None:
        if self._collection_check_started:
            return
        if self.collection_check_thread and self.collection_check_thread.is_alive():
            return
        paths = self._collection_paths()
        if paths is None:
            return
        self._collection_check_started = True
        input_path, output_path = paths

        def worker() -> None:
            try:
                outdated, _ = is_fab_collection_outdated(input_path, output_path)
            except Exception:
                # Network/git errors: silently skip; user can retry via CLI or next launch.
                return
            if outdated:
                self.event_queue.put(("collection_update", (input_path, output_path)))

        self.collection_check_thread = threading.Thread(target=worker, daemon=True)
        self.collection_check_thread.start()

    def _prompt_collection_update(self, input_path: str, output_path: str) -> None:
        dialog = tk.Toplevel(self.root)
        dialog.title("Card database")
        dialog.transient(self.root)
        dialog.resizable(False, False)
        dialog.configure(background=BG)
        self._apply_icon(dialog)

        w, h = 460, 180
        self._center_dialog_on_root(dialog, w, h)

        body = ttk.Frame(dialog, padding=20)
        body.pack(fill="both", expand=True)
        ttk.Label(
            body,
            text="The local card database is out of sync.",
            style="Heading.TLabel",
            wraplength=w - 60,
            justify="left",
        ).pack(anchor="w")
        ttk.Label(
            body,
            text="Regenerate the local collection now?",
            style="Muted.TLabel",
        ).pack(anchor="w", pady=(6, 16))

        btn_row = ttk.Frame(body)
        btn_row.pack(anchor="e")

        def dismiss() -> None:
            try:
                dialog.grab_release()
            except tk.TclError:
                pass
            dialog.destroy()

        def on_yes() -> None:
            dismiss()
            self._start_collection_regen(input_path, output_path)

        ttk.Button(btn_row, text="Skip", command=dismiss).pack(
            side="right", padx=(8, 0)
        )
        ttk.Button(
            btn_row,
            text="Regenerate",
            command=on_yes,
            style="Accent.TButton",
        ).pack(side="right")

        dialog.protocol("WM_DELETE_WINDOW", dismiss)
        dialog.grab_set()
        dialog.lift()
        dialog.focus_force()

    def _start_collection_regen(self, input_path: str, output_path: str) -> None:
        if self.collection_regen_thread and self.collection_regen_thread.is_alive():
            return
        self._open_regen_dialog()
        self.status_var.set("Regenerating card collection...")

        def worker() -> None:
            try:
                refresh_fab_collection(input_path, output_path)
                self.event_queue.put(("collection_regen_done", None))
            except Exception as e:
                self.event_queue.put(
                    ("collection_regen_error", f"{type(e).__name__}: {e}")
                )

        self.collection_regen_thread = threading.Thread(target=worker, daemon=True)
        self.collection_regen_thread.start()

    def _open_regen_dialog(self) -> None:
        dialog = tk.Toplevel(self.root)
        dialog.title("Card database")
        dialog.transient(self.root)
        dialog.resizable(False, False)
        dialog.configure(background=BG)
        self._apply_icon(dialog)
        dialog.protocol("WM_DELETE_WINDOW", lambda: None)

        w, h = 420, 140
        self._center_dialog_on_root(dialog, w, h)

        body = ttk.Frame(dialog, padding=20)
        body.pack(fill="both", expand=True)
        ttk.Label(
            body,
            text="Regenerating card collection...",
            style="Heading.TLabel",
        ).pack(anchor="w")
        ttk.Label(
            body,
            text="Pulling latest cards from the source repository and rebuilding the local snapshot.",
            style="Muted.TLabel",
            wraplength=w - 60,
            justify="left",
        ).pack(anchor="w", pady=(4, 12))

        pb = ttk.Progressbar(
            body,
            mode="indeterminate",
            style="Modern.Horizontal.TProgressbar",
            length=w - 60,
        )
        pb.pack(fill="x")
        pb.start(12)

        dialog.grab_set()
        self._collection_regen_dialog = dialog

    def _close_regen_dialog(self) -> None:
        if self._collection_regen_dialog is not None:
            try:
                self._collection_regen_dialog.grab_release()
            except tk.TclError:
                pass
            self._collection_regen_dialog.destroy()
            self._collection_regen_dialog = None

    def _cleanup_render_tmpdir(self) -> None:
        if self.render_tmpdir and os.path.exists(self.render_tmpdir):
            shutil.rmtree(self.render_tmpdir, ignore_errors=True)
        self.render_tmpdir = None

    def _on_close(self) -> None:
        self._cleanup_render_tmpdir()
        self.root.destroy()


def main() -> None:
    parser = argparse.ArgumentParser(description="Card Proxy Printer GUI")
    parser.add_argument(
        "--config",
        type=str,
        default=None,
        help="Path to a YAML config to preload (same format as main.py).",
    )
    args = parser.parse_args()

    config_path = args.config or DEFAULT_GUI_CONFIG_PATH

    root = tk.Tk()
    CardProxyPrinterGUI(root, default_config_path=config_path)
    root.mainloop()


if __name__ == "__main__":
    main()
