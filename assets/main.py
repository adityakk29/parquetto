#!/usr/bin/env python3
"""
Parquetto
=========
A small, dependency-light, standalone GUI for browsing Parquet files,
with a SQL box for filtering and aggregating the loaded data, and a
dark theme.

Run it with:
    python main.py
    python main.py path/to/file.parquet

Requirements: pandas, pyarrow (see requirements.txt). The UI itself is
built entirely in Python with Tkinter, which ships with the Python
standard library. SQL support uses Python's built-in sqlite3 module
together with pandas.DataFrame.to_sql / pandas.read_sql_query: the
loaded file is written into an in-memory SQLite table named "data",
and each query you type is run against that table with pandas doing
the read/write.
"""

import os
import sys
import sqlite3
import threading
import traceback
import tkinter as tk
import tkinter.font as tkfont
from tkinter import ttk, filedialog, messagebox

import pandas as pd
import pyarrow.parquet as pq

APP_TITLE = "Parquetto"
PAGE_SIZES = [100, 500, 1000, 5000]
DEFAULT_PAGE_SIZE = 500
MAX_CELL_CHARS = 200  # truncate very long cell values for display
SQL_TABLE_NAME = "data"

# ---------------------------------------------------------------------------
# Dark theme palette
# ---------------------------------------------------------------------------
BG = "#1e1f22"            # window background
PANEL_BG = "#26272b"      # toolbar / panel background
FIELD_BG = "#2b2d31"      # entries, text boxes, table
FIELD_BG_ALT = "#232428"  # zebra-stripe row color
BORDER = "#3a3b3f"
FG = "#e6e6e6"            # primary text
FG_MUTED = "#9aa0a6"      # secondary text / hints
ACCENT = "#5b9dfa"        # accent blue
ACCENT_ACTIVE = "#4a86e0"
SELECT_BG = "#2f4f7a"     # selected row / text selection
DISABLED_FG = "#6b6f76"


def resource_path(relative_path):
    """Resolve a path to a bundled resource, whether running from source
    or from a PyInstaller-frozen executable (which unpacks data files
    into a temporary folder referenced by sys._MEIPASS)."""
    base_path = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base_path, relative_path)


class ParquetViewer(tk.Tk):
    def __init__(self, initial_path=None):
        super().__init__()
        self.title(APP_TITLE)
        self.geometry("1180x780")
        self.minsize(800, 500)
        self.configure(bg=BG)
        self._set_window_icon()

        # Data state
        self.file_path = None
        self.raw_df = None          # the originally loaded dataframe (immutable per file)
        self.base_df = None         # currently active dataframe (raw_df, or last SQL result)
        self.view_df = None         # base_df after quick-search + sort applied (what's paginated)
        self.columns = []
        self.sql_conn = None        # in-memory sqlite connection backing the "data" table
        self.sql_enabled = False

        # View state
        self.page = 0
        self.page_size = DEFAULT_PAGE_SIZE
        self.sort_col = None
        self.sort_desc = False
        self.search_term = ""

        self._pick_fonts()
        self._init_style()
        self._build_menu()
        self._build_toolbar()
        self._build_sql_panel()
        self._build_body()
        self._build_statusbar()

        self.bind("<Control-o>", lambda e: self.open_file_dialog())

        if initial_path:
            self.after(100, lambda: self.load_file(initial_path))

    def _set_window_icon(self):
        # .png works with iconphoto on Windows/Linux/macOS. If it's missing
        # for some reason, fail quietly rather than crash the app.
        try:
            icon_img = tk.PhotoImage(file=resource_path(os.path.join("assets", "icon_128.png")))
            self.iconphoto(True, icon_img)
            self._icon_img_ref = icon_img  # keep a reference so it isn't garbage-collected
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Fonts & theme
    # ------------------------------------------------------------------
    def _pick_fonts(self):
        available = set(tkfont.families())

        def pick(candidates, fallback):
            for name in candidates:
                if name in available:
                    return name
            return fallback

        ui_family = pick(["Segoe UI", "Helvetica Neue", "Helvetica", "Arial", "DejaVu Sans"], "TkDefaultFont")
        mono_family = pick(["Cascadia Mono", "Consolas", "Menlo", "DejaVu Sans Mono", "Courier New"], "Courier")

        self.font_ui = (ui_family, 10)
        self.font_ui_bold = (ui_family, 10, "bold")
        self.font_heading = (ui_family, 13, "bold")
        self.font_muted = (ui_family, 9)
        self.font_mono = (mono_family, 10)

        self.option_add("*Font", self.font_ui)

    def _init_style(self):
        style = ttk.Style(self)
        # 'clam' is the most themeable built-in ttk theme across platforms.
        style.theme_use("clam")

        style.configure(".", background=BG, foreground=FG, font=self.font_ui,
                         fieldbackground=FIELD_BG, bordercolor=BORDER, lightcolor=BORDER, darkcolor=BORDER)

        style.configure("TFrame", background=BG)
        style.configure("Panel.TFrame", background=PANEL_BG)

        style.configure("TLabel", background=BG, foreground=FG)
        style.configure("Panel.TLabel", background=PANEL_BG, foreground=FG)
        style.configure("Muted.TLabel", background=PANEL_BG, foreground=FG_MUTED, font=self.font_muted)
        style.configure("Heading.TLabel", background=BG, foreground=FG, font=self.font_heading)

        style.configure("TLabelframe", background=PANEL_BG, foreground=FG, bordercolor=BORDER)
        style.configure("TLabelframe.Label", background=PANEL_BG, foreground=FG_MUTED, font=self.font_muted)

        style.configure("TButton", background=FIELD_BG, foreground=FG, bordercolor=BORDER,
                         focusthickness=0, padding=(10, 6))
        style.map("TButton",
                   background=[("active", ACCENT_ACTIVE), ("pressed", ACCENT_ACTIVE)],
                   foreground=[("active", "#ffffff"), ("pressed", "#ffffff")])

        style.configure("Accent.TButton", background=ACCENT, foreground="#ffffff", padding=(10, 6))
        style.map("Accent.TButton",
                   background=[("active", ACCENT_ACTIVE), ("pressed", ACCENT_ACTIVE)])

        style.configure("TEntry", fieldbackground=FIELD_BG, foreground=FG,
                         insertcolor=FG, bordercolor=BORDER, padding=6)
        style.map("TEntry", bordercolor=[("focus", ACCENT)])

        style.configure("TCombobox", fieldbackground=FIELD_BG, background=FIELD_BG, foreground=FG,
                         arrowcolor=FG, bordercolor=BORDER, padding=5)
        style.map("TCombobox",
                   fieldbackground=[("readonly", FIELD_BG)],
                   foreground=[("readonly", FG)],
                   bordercolor=[("focus", ACCENT)])
        self.option_add("*TCombobox*Listbox.background", FIELD_BG)
        self.option_add("*TCombobox*Listbox.foreground", FG)
        self.option_add("*TCombobox*Listbox.selectBackground", SELECT_BG)
        self.option_add("*TCombobox*Listbox.selectForeground", "#ffffff")

        style.configure("Treeview", background=FIELD_BG, fieldbackground=FIELD_BG, foreground=FG,
                         bordercolor=BORDER, rowheight=26, borderwidth=0)
        style.map("Treeview",
                   background=[("selected", SELECT_BG)],
                   foreground=[("selected", "#ffffff")])
        style.configure("Treeview.Heading", background=PANEL_BG, foreground=FG,
                         font=self.font_ui_bold, relief="flat", padding=(8, 6))
        style.map("Treeview.Heading", background=[("active", FIELD_BG)])

        style.configure("Vertical.TScrollbar", background=PANEL_BG, troughcolor=BG,
                         bordercolor=BG, arrowcolor=FG_MUTED)
        style.map("Vertical.TScrollbar", background=[("active", FIELD_BG)])
        style.configure("Horizontal.TScrollbar", background=PANEL_BG, troughcolor=BG,
                         bordercolor=BG, arrowcolor=FG_MUTED)
        style.map("Horizontal.TScrollbar", background=[("active", FIELD_BG)])

        style.configure("Status.TLabel", background=PANEL_BG, foreground=FG_MUTED,
                         font=self.font_muted, padding=(8, 5))

        # Native tk menus can't fully adopt ttk styling on every platform, but
        # setting colors helps on Linux and does no harm elsewhere.
        self.option_add("*Menu.background", PANEL_BG)
        self.option_add("*Menu.foreground", FG)
        self.option_add("*Menu.activeBackground", ACCENT)
        self.option_add("*Menu.activeForeground", "#ffffff")
        self.option_add("*Menu.disabledForeground", DISABLED_FG)

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------
    def _build_menu(self):
        menubar = tk.Menu(self, bg=PANEL_BG, fg=FG, activebackground=ACCENT, activeforeground="#ffffff")

        file_menu = tk.Menu(menubar, tearoff=0, bg=PANEL_BG, fg=FG,
                             activebackground=ACCENT, activeforeground="#ffffff")
        file_menu.add_command(label="Open...", command=self.open_file_dialog, accelerator="Ctrl+O")
        file_menu.add_command(label="Export current view to CSV...", command=self.export_csv)
        file_menu.add_separator()
        file_menu.add_command(label="Quit", command=self.destroy)
        menubar.add_cascade(label="File", menu=file_menu)

        view_menu = tk.Menu(menubar, tearoff=0, bg=PANEL_BG, fg=FG,
                             activebackground=ACCENT, activeforeground="#ffffff")
        view_menu.add_command(label="Show schema / metadata", command=self.show_schema_dialog)
        menubar.add_cascade(label="View", menu=view_menu)

        help_menu = tk.Menu(menubar, tearoff=0, bg=PANEL_BG, fg=FG,
                             activebackground=ACCENT, activeforeground="#ffffff")
        help_menu.add_command(label="About", command=self.show_about_dialog)
        menubar.add_cascade(label="Help", menu=help_menu)

        self.config(menu=menubar)

    def _build_toolbar(self):
        outer = tk.Frame(self, bg=PANEL_BG, highlightthickness=1, highlightbackground=BORDER)
        outer.pack(side=tk.TOP, fill=tk.X)

        bar = ttk.Frame(outer, style="Panel.TFrame", padding=10)
        bar.pack(fill=tk.X)

        ttk.Label(bar, text=f"📊  {APP_TITLE}", style="Panel.TLabel", font=self.font_heading).pack(
            side=tk.LEFT, padx=(0, 18)
        )

        ttk.Button(bar, text="Open File", style="Accent.TButton", command=self.open_file_dialog).pack(side=tk.LEFT)

        ttk.Label(bar, text="Quick search:", style="Panel.TLabel").pack(side=tk.LEFT, padx=(18, 6))
        self.search_var = tk.StringVar()
        entry = ttk.Entry(bar, textvariable=self.search_var, width=22)
        entry.pack(side=tk.LEFT)
        entry.bind("<Return>", lambda e: self.apply_search())
        ttk.Button(bar, text="Go", command=self.apply_search).pack(side=tk.LEFT, padx=(6, 0))
        ttk.Button(bar, text="Clear", command=self.clear_search).pack(side=tk.LEFT, padx=(6, 0))

        ttk.Label(bar, text="Rows/page:", style="Panel.TLabel").pack(side=tk.LEFT, padx=(18, 6))
        self.page_size_var = tk.StringVar(value=str(DEFAULT_PAGE_SIZE))
        page_combo = ttk.Combobox(
            bar, textvariable=self.page_size_var, values=[str(p) for p in PAGE_SIZES],
            width=6, state="readonly"
        )
        page_combo.pack(side=tk.LEFT)
        page_combo.bind("<<ComboboxSelected>>", self._on_page_size_change)

        nav = ttk.Frame(bar, style="Panel.TFrame")
        nav.pack(side=tk.RIGHT)
        ttk.Button(nav, text="◀ Prev", command=self.prev_page).pack(side=tk.LEFT)
        self.page_label = ttk.Label(nav, text="Page 0 / 0", style="Panel.TLabel", width=14, anchor="center")
        self.page_label.pack(side=tk.LEFT, padx=8)
        ttk.Button(nav, text="Next ▶", command=self.next_page).pack(side=tk.LEFT)

    def _build_sql_panel(self):
        outer = tk.Frame(self, bg=PANEL_BG, highlightthickness=1, highlightbackground=BORDER)
        outer.pack(side=tk.TOP, fill=tk.X, padx=0, pady=(1, 0))

        panel = ttk.Frame(outer, style="Panel.TFrame", padding=10)
        panel.pack(fill=tk.X)

        header = ttk.Frame(panel, style="Panel.TFrame")
        header.pack(fill=tk.X, pady=(0, 6))
        ttk.Label(header, text="SQL QUERY", style="Muted.TLabel", font=self.font_ui_bold).pack(side=tk.LEFT)
        ttk.Label(header, text=f"  ·  table name: {SQL_TABLE_NAME}", style="Muted.TLabel").pack(side=tk.LEFT)

        row = ttk.Frame(panel, style="Panel.TFrame")
        row.pack(fill=tk.X)

        self.sql_text = tk.Text(
            row, height=3, wrap="none", font=self.font_mono,
            bg=FIELD_BG, fg=FG, insertbackground=FG,
            selectbackground=SELECT_BG, selectforeground="#ffffff",
            relief="flat", highlightthickness=1, highlightbackground=BORDER, highlightcolor=ACCENT,
            padx=8, pady=6,
        )
        self.sql_text.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 10))
        self.sql_text.bind("<Control-Return>", lambda e: (self.run_sql_query(), "break"))

        btns = ttk.Frame(panel, style="Panel.TFrame")
        btns.pack(side=tk.LEFT)
        ttk.Button(btns, text="Run Query  (Ctrl+Enter)", style="Accent.TButton",
                   command=self.run_sql_query).pack(fill=tk.X, pady=(0, 6))
        ttk.Button(btns, text="Reset to full data", command=self.reset_view).pack(fill=tk.X)

        hint = (
            "e.g.  SELECT * FROM data WHERE amount > 100 ORDER BY amount DESC     "
            "SELECT category, COUNT(*) AS n, AVG(amount) AS avg_amount FROM data GROUP BY category"
        )
        ttk.Label(panel, text=hint, style="Muted.TLabel").pack(fill=tk.X, anchor="w", pady=(8, 0))

    def _build_body(self):
        container = ttk.Frame(self)
        container.pack(fill=tk.BOTH, expand=True)

        # Sidebar: schema
        sidebar_outer = tk.Frame(container, bg=PANEL_BG, width=230,
                                  highlightthickness=1, highlightbackground=BORDER)
        sidebar_outer.pack(side=tk.LEFT, fill=tk.Y)
        sidebar_outer.pack_propagate(False)

        ttk.Label(sidebar_outer, text="COLUMNS", style="Panel.TLabel", font=self.font_ui_bold).pack(
            anchor="w", padx=10, pady=(10, 4)
        )
        self.schema_box = tk.Listbox(
            sidebar_outer, activestyle="none",
            bg=FIELD_BG, fg=FG, selectbackground=SELECT_BG, selectforeground="#ffffff",
            relief="flat", highlightthickness=0, borderwidth=0, font=self.font_ui,
        )
        self.schema_box.pack(fill=tk.BOTH, expand=True, padx=10, pady=(0, 10))

        # Table
        table_frame = ttk.Frame(container, padding=(1, 0, 0, 0))
        table_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        self.tree = ttk.Treeview(table_frame, show="headings")
        vsb = ttk.Scrollbar(table_frame, orient="vertical", command=self.tree.yview)
        hsb = ttk.Scrollbar(table_frame, orient="horizontal", command=self.tree.xview)
        self.tree.configure(yscrollcommand=vsb.set, xscrollcommand=hsb.set)
        self.tree.tag_configure("oddrow", background=FIELD_BG)
        self.tree.tag_configure("evenrow", background=FIELD_BG_ALT)

        self.tree.grid(row=0, column=0, sticky="nsew")
        vsb.grid(row=0, column=1, sticky="ns")
        hsb.grid(row=1, column=0, sticky="ew")
        table_frame.grid_rowconfigure(0, weight=1)
        table_frame.grid_columnconfigure(0, weight=1)

        # Placeholder message
        self.placeholder = tk.Label(
            table_frame, text="Open a .parquet file to get started\n(File > Open, or Ctrl+O)",
            bg=FIELD_BG, fg=FG_MUTED, justify="center", font=self.font_heading,
        )
        self.placeholder.grid(row=0, column=0, sticky="nsew")

    def _build_statusbar(self):
        outer = tk.Frame(self, bg=PANEL_BG, highlightthickness=1, highlightbackground=BORDER)
        outer.pack(side=tk.BOTTOM, fill=tk.X)
        self.status_var = tk.StringVar(value="No file loaded")
        ttk.Label(outer, textvariable=self.status_var, style="Status.TLabel", anchor="w").pack(fill=tk.X)

    # ------------------------------------------------------------------
    # File loading
    # ------------------------------------------------------------------
    def open_file_dialog(self):
        path = filedialog.askopenfilename(
            title="Open Parquet File",
            filetypes=[("Parquet files", "*.parquet *.pq"), ("All files", "*.*")],
        )
        if path:
            self.load_file(path)

    def load_file(self, path):
        """Load a parquet file in a background thread so the UI stays responsive."""
        if not os.path.isfile(path):
            messagebox.showerror(APP_TITLE, f"File not found:\n{path}")
            return

        self.status_var.set(f"Loading {os.path.basename(path)} ...")
        self.config(cursor="watch")
        self.update_idletasks()

        def worker():
            try:
                table = pq.read_table(path)
                df = table.to_pandas()
                self.after(0, lambda: self._on_load_success(path, df))
            except Exception as exc:  # noqa: BLE001
                err_text = f"{exc}\n\n{traceback.format_exc(limit=2)}"
                self.after(0, lambda: self._on_load_error(err_text))

        threading.Thread(target=worker, daemon=True).start()

    def _on_load_success(self, path, df):
        self.config(cursor="")
        self.file_path = path
        self.raw_df = df

        self.sql_text.delete("1.0", tk.END)
        self._setup_sql_table(df)

        self.placeholder.grid_remove()
        self._set_base_df(df)
        self.title(f"{APP_TITLE} - {os.path.basename(path)}")

    def _on_load_error(self, message):
        self.config(cursor="")
        self.status_var.set("Failed to load file")
        messagebox.showerror(APP_TITLE, f"Could not read parquet file:\n\n{message}")

    # ------------------------------------------------------------------
    # SQL support
    # ------------------------------------------------------------------
    @staticmethod
    def _sql_safe_copy(df):
        """Stringify columns SQLite can't natively store (lists, dicts, nested arrays)
        so to_sql doesn't choke on parquet's richer nested types."""
        safe = df.copy()
        for col in safe.columns:
            if safe[col].dtype == object:
                non_null = safe[col].dropna()
                sample = non_null.iloc[0] if not non_null.empty else None
                if isinstance(sample, (list, dict, tuple, set)) or hasattr(sample, "tolist"):
                    safe[col] = safe[col].apply(lambda v: None if v is None else str(v))
        return safe

    def _setup_sql_table(self, df):
        if self.sql_conn is not None:
            try:
                self.sql_conn.close()
            except Exception:
                pass
            self.sql_conn = None
        self.sql_enabled = False

        try:
            conn = sqlite3.connect(":memory:")
            safe_df = self._sql_safe_copy(df)
            safe_df.to_sql(SQL_TABLE_NAME, conn, index=False, if_exists="replace")
            self.sql_conn = conn
            self.sql_enabled = True
        except Exception as exc:  # noqa: BLE001
            self.sql_enabled = False
            messagebox.showwarning(
                APP_TITLE,
                "SQL querying is unavailable for this file because it couldn't be loaded "
                f"into SQLite:\n\n{exc}\n\nYou can still browse, search, sort and export it normally."
            )

    def run_sql_query(self):
        if self.raw_df is None:
            messagebox.showinfo(APP_TITLE, "Open a parquet file first.")
            return
        if not self.sql_enabled:
            messagebox.showinfo(APP_TITLE, "SQL querying isn't available for this file (see earlier warning).")
            return

        query = self.sql_text.get("1.0", tk.END).strip()
        if not query:
            messagebox.showinfo(APP_TITLE, "Type a SQL query first, e.g. SELECT * FROM data LIMIT 100")
            return

        try:
            result = pd.read_sql_query(query, self.sql_conn)
        except Exception as exc:  # noqa: BLE001
            messagebox.showerror("SQL Error", str(exc))
            return

        self.search_var.set("")
        self.search_term = ""
        self._set_base_df(result, is_query_result=True)

    def reset_view(self):
        if self.raw_df is None:
            return
        self.sql_text.delete("1.0", tk.END)
        self.search_var.set("")
        self.search_term = ""
        self._set_base_df(self.raw_df)

    # ------------------------------------------------------------------
    # Schema panel
    # ------------------------------------------------------------------
    def _populate_schema(self, df):
        self.schema_box.delete(0, tk.END)
        for name, dtype in df.dtypes.items():
            self.schema_box.insert(tk.END, f"  {name}   ({dtype})")

    def show_schema_dialog(self):
        if self.base_df is None:
            messagebox.showinfo(APP_TITLE, "No file loaded yet.")
            return
        win = tk.Toplevel(self, bg=BG)
        win.title("Schema / Metadata")
        win.geometry("540x500")

        text = tk.Text(
            win, wrap="word", bg=FIELD_BG, fg=FG, insertbackground=FG,
            selectbackground=SELECT_BG, selectforeground="#ffffff",
            relief="flat", padx=12, pady=12, font=self.font_mono,
        )
        text.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)

        lines = [
            f"File: {self.file_path}",
            f"Rows currently shown: {len(self.base_df):,} (of {len(self.raw_df):,} in file)",
            f"Columns: {len(self.base_df.columns)}",
            "",
        ]
        try:
            pf = pq.ParquetFile(self.file_path)
            meta = pf.metadata
            lines.append(f"Row groups: {meta.num_row_groups}")
            lines.append(f"Created by: {meta.created_by}")
            lines.append("")
        except Exception:
            pass

        lines.append("Columns:")
        for name, dtype in self.base_df.dtypes.items():
            lines.append(f"  - {name}: {dtype}")

        text.insert("1.0", "\n".join(lines))
        text.config(state="disabled")

    # ------------------------------------------------------------------
    # Table rendering
    # ------------------------------------------------------------------
    def _set_base_df(self, df, is_query_result=False):
        """Make `df` the dataframe currently being displayed / browsed."""
        self.base_df = df
        self.columns = list(df.columns)
        self.sort_col = None
        self.sort_desc = False
        self.page = 0

        self._configure_tree_columns()
        self._populate_schema(df)
        self._recompute_view()

        if is_query_result:
            self.status_var.set(f"Query returned {len(df):,} rows, {len(df.columns)} columns")

    def _configure_tree_columns(self):
        self.tree.delete(*self.tree.get_children())
        self.tree["columns"] = self.columns
        for col in self.columns:
            self.tree.heading(col, text=col, command=lambda c=col: self._on_sort(c))
            self.tree.column(col, width=140, minwidth=60, stretch=True, anchor="w")

    def _on_sort(self, col):
        if self.sort_col == col:
            self.sort_desc = not self.sort_desc
        else:
            self.sort_col = col
            self.sort_desc = False
        self._recompute_view()

    def _recompute_view(self):
        df = self.base_df
        if df is None:
            return

        if self.search_term:
            term = self.search_term.lower()
            mask = df.apply(
                lambda row: row.astype(str).str.lower().str.contains(term, na=False).any(), axis=1
            )
            df = df[mask]

        if self.sort_col:
            try:
                df = df.sort_values(self.sort_col, ascending=not self.sort_desc, kind="mergesort")
            except TypeError:
                df = df.sort_values(
                    self.sort_col, ascending=not self.sort_desc, kind="mergesort",
                    key=lambda s: s.astype(str)
                )

        self.view_df = df
        self.page = 0
        self._render_page()

    def _render_page(self):
        self.tree.delete(*self.tree.get_children())
        if self.view_df is None:
            return

        total = len(self.view_df)
        start = self.page * self.page_size
        end = min(start + self.page_size, total)
        page_df = self.view_df.iloc[start:end]

        for i, (_, row) in enumerate(page_df.iterrows()):
            values = [self._format_cell(v) for v in row.tolist()]
            tag = "evenrow" if i % 2 == 0 else "oddrow"
            self.tree.insert("", tk.END, values=values, tags=(tag,))

        max_page = max(0, (total - 1) // self.page_size) if total else 0
        self.page_label.config(text=f"Page {self.page + 1} / {max_page + 1}")

        sort_info = f"  |  sorted by {self.sort_col} ({'desc' if self.sort_desc else 'asc'})" if self.sort_col else ""
        search_info = f"  |  filter: '{self.search_term}'" if self.search_term else ""
        size_str = self._file_size_str()
        self.status_var.set(
            f"{os.path.basename(self.file_path)}  |  "
            f"{total:,} rows shown / {len(self.raw_df):,} in file  |  "
            f"{len(self.columns)} columns  |  {size_str}{sort_info}{search_info}"
        )

    @staticmethod
    def _format_cell(value):
        if value is None:
            return ""
        try:
            if pd.isna(value):
                return ""
        except (TypeError, ValueError):
            pass
        s = str(value)
        if len(s) > MAX_CELL_CHARS:
            return s[:MAX_CELL_CHARS] + "..."
        return s

    def _file_size_str(self):
        try:
            size = os.path.getsize(self.file_path)
        except OSError:
            return ""
        for unit in ["B", "KB", "MB", "GB"]:
            if size < 1024:
                return f"{size:.1f} {unit}"
            size /= 1024
        return f"{size:.1f} TB"

    # ------------------------------------------------------------------
    # Toolbar actions
    # ------------------------------------------------------------------
    def apply_search(self):
        if self.base_df is None:
            return
        self.search_term = self.search_var.get().strip()
        self._recompute_view()

    def clear_search(self):
        self.search_var.set("")
        self.search_term = ""
        if self.base_df is not None:
            self._recompute_view()

    def _on_page_size_change(self, event=None):
        try:
            self.page_size = int(self.page_size_var.get())
        except ValueError:
            self.page_size = DEFAULT_PAGE_SIZE
        self.page = 0
        self._render_page()

    def prev_page(self):
        if self.page > 0:
            self.page -= 1
            self._render_page()

    def next_page(self):
        if self.view_df is None:
            return
        max_page = max(0, (len(self.view_df) - 1) // self.page_size)
        if self.page < max_page:
            self.page += 1
            self._render_page()

    def export_csv(self):
        if self.view_df is None:
            messagebox.showinfo(APP_TITLE, "No file loaded yet.")
            return
        path = filedialog.asksaveasfilename(
            title="Export to CSV", defaultextension=".csv",
            filetypes=[("CSV files", "*.csv")]
        )
        if not path:
            return
        try:
            self.view_df.to_csv(path, index=False)
            messagebox.showinfo(APP_TITLE, f"Exported {len(self.view_df):,} rows to:\n{path}")
        except Exception as exc:  # noqa: BLE001
            messagebox.showerror(APP_TITLE, f"Export failed:\n{exc}")

    def show_about_dialog(self):
        messagebox.showinfo(
            APP_TITLE,
            f"{APP_TITLE}\n\n"
            "A simple, standalone Parquet file viewer built with Tkinter,\n"
            "pandas, and pyarrow.\n\n"
            "Open a file, search across all columns, sort by clicking a\n"
            "column header, run SQL against it (table name: data), and\n"
            "export the current view to CSV.",
        )


def main():
    initial_path = sys.argv[1] if len(sys.argv) > 1 else None
    app = ParquetViewer(initial_path=initial_path)
    app.mainloop()


if __name__ == "__main__":
    main()
