#!/usr/bin/env python3
"""H264 VAAPI Encoder – GTK3 GUI"""

import json
import os
import threading
import gi
from urllib.parse import unquote

import i18n

gi.require_version("Gtk", "3.0")
from gi.repository import Gtk, Gdk, GLib, GObject, Pango
from gi.repository import PangoCairo
import subprocess
gi.require_version("GdkPixbuf", "2.0")
from gi.repository import GdkPixbuf
from typing import Optional

from encoder import (
    Encoder, EncodeJob,
    get_fps, get_video_dimensions, compute_output_dimensions,
    get_file_metadata, scan_folder, HIGH_FPS_THRESHOLD,
    VIDEO_EXTENSIONS,
)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

VIDEO_BITRATES = [
    ("500 kbps",   "500k"),
    ("1000 kbps",  "1000k"),
    ("2000 kbps",  "2000k"),
    ("4000 kbps",  "4000k"),
    ("6000 kbps",  "6000k"),
    ("8000 kbps",  "8000k"),
    ("12000 kbps", "12000k"),
    ("16000 kbps", "16000k"),
    ("20000 kbps", "20000k"),
]

AUDIO_BITRATES = [
    ("Original (beibehalten)", None),   # stream-copy audio
    ("64 kbps",  "64k"),
    ("96 kbps",  "96k"),
    ("128 kbps", "128k"),
    ("192 kbps", "192k"),
    ("256 kbps", "256k"),
    ("320 kbps", "320k"),
]

DEFAULT_VIDEO_IDX = 3   # 4000 kbps
DEFAULT_AUDIO_IDX = 0   # Original (beibehalten)

# (label, target_height_or_None)
RESOLUTIONS = [
    ("Original (beibehalten)", None),
    ("480p  (854 × 480)",       480),
    ("720p  (1280 × 720)",      720),
    ("1080p (1920 × 1080)",    1080),
    ("1440p (2560 × 1440)",    1440),
    ("4K    (3840 × 2160)",    2160),
]
DEFAULT_RES_IDX = 0   # Original

# TreeView columns
COL_FILENAME    = 0
COL_DIRECTORY   = 1
COL_STATUS      = 2
COL_PROGRESS    = 3
COL_FULLPATH    = 4
COL_AUDIO_LABEL = 5
COL_SUB_LABEL   = 6
COL_RESOLUTION  = 7   # e.g. "1920×1080"
COL_VID_BITRATE = 8   # e.g. "4.3 Mbps"
COL_AUD_BITRATE = 9   # e.g. "128 kbps"
COL_FPS         = 10  # e.g. "59.94"
COL_DURATION    = 11  # e.g. "1:23:45"
COL_STOP_MARKER = 12  # "⏹" when stop-after is set, "" otherwise


# ---------------------------------------------------------------------------
# Formatting helpers
# ---------------------------------------------------------------------------

def _fmt_kbps(kbps: int | None) -> str:
    if kbps is None:
        return "–"
    if kbps >= 10_000:
        return f"{kbps / 1000:.1f} Mbps"
    return f"{kbps:,} kbps".replace(",", "\u202f")   # narrow no-break space


def _fmt_resolution(w: int, h: int) -> str:
    return f"{w}×{h}" if w and h else "–"


def _fmt_fps(fps: float) -> str:
    if fps <= 0:
        return "–"
    # Show decimal only when it's not a whole number
    return f"{fps:.2f}".rstrip("0").rstrip(".") + " fps"


def _fmt_duration(secs: float) -> str:
    if secs <= 0:
        return "–"
    total = int(secs)
    h, rem = divmod(total, 3600)
    m, s = divmod(rem, 60)
    if h:
        return f"{h}:{m:02d}:{s:02d}"
    return f"{m}:{s:02d}"

# Status values – these are language-neutral sentinel keys used internally.
# The human-visible strings come from i18n.t(); see _status_str() helper.
STATUS_PENDING   = "PENDING"
STATUS_ENCODING  = "ENCODING"
STATUS_DONE      = "DONE"
STATUS_ERROR     = "ERROR"
STATUS_CANCELLED = "CANCELLED"

# Mapping from sentinel to i18n key for display strings
_STATUS_KEY = {
    STATUS_PENDING:   "status_pending",
    STATUS_ENCODING:  "status_encoding",
    STATUS_DONE:      "status_done",
    STATUS_ERROR:     "status_error",
    STATUS_CANCELLED: "status_cancelled",
}


def _status_str(sentinel: str) -> str:
    """Return the translated display string for a status sentinel."""
    key = _STATUS_KEY.get(sentinel)
    return i18n.t(key) if key else sentinel

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_output_path(
    input_path: str,
    output_dir: str,
    use_source_dir: bool,
    replace_original: bool,
    keep_name: bool,
    custom_suffix: str,
) -> str:
    """Compute the output file path from settings."""
    src_dir   = os.path.dirname(input_path)
    base, ext = os.path.splitext(input_path)
    base_name = os.path.basename(base)
    orig_name = os.path.basename(input_path)   # full original filename

    target_dir = src_dir if use_source_dir else output_dir

    if replace_original:
        # Temp file in the source directory so os.replace works atomically.
        return os.path.join(src_dir, f".{base_name}_tmp_enc.mp4")
    if keep_name:
        # Same filename, different directory — no conflict with the source.
        return os.path.join(target_dir, orig_name)
    out_name = f"{base_name}{custom_suffix}.mp4"
    return os.path.join(target_dir, out_name)


# ---------------------------------------------------------------------------
# Queue persistence
# ---------------------------------------------------------------------------

QUEUE_FILE = os.path.join(
    os.environ.get("XDG_DATA_HOME", os.path.expanduser("~/.local/share")),
    "h264-vaapi-encoder",
    "queue.txt",
)

SETTINGS_FILE = os.path.join(
    os.environ.get("XDG_CONFIG_HOME", os.path.expanduser("~/.config")),
    "h264-vaapi-encoder",
    "settings.json",
)


# ---------------------------------------------------------------------------
# Custom cell renderer: progress bar with always-black percentage text
# ---------------------------------------------------------------------------

class ProgressCellRenderer(Gtk.CellRendererProgress):
    """CellRendererProgress that draws the text label in pure black via Cairo,
    bypassing the theme colour that GTK applies internally per bar segment."""
    __gtype_name__ = "ProgressCellRenderer"

    def do_render(self, cr, widget, background_area, cell_area, flags):
        saved = self.props.text          # None when only "value" is bound
        self.props.text = ""             # suppress built-in text so bar draws clean
        Gtk.CellRendererProgress.do_render(
            self, cr, widget, background_area, cell_area, flags)
        self.props.text = saved

        # When text is None the C code auto-formats "N %"; mirror that here.
        label = saved if saved is not None else f"{self.props.value}\u202f%"
        if not label:
            return

        layout = widget.create_pango_layout(label)
        lw, lh = layout.get_pixel_size()
        tx = cell_area.x + (cell_area.width  - lw) / 2
        ty = cell_area.y + (cell_area.height - lh) / 2
        cr.set_source_rgb(0.0, 0.0, 0.0)
        cr.move_to(tx, ty)
        PangoCairo.show_layout(cr, layout)


# ---------------------------------------------------------------------------
# Main Window
# ---------------------------------------------------------------------------

class MainWindow(Gtk.Window):
    def __init__(self):
        super().__init__(title="H264 VAAPI Encoder")
        self.set_default_size(1200, 800)
        self.set_border_width(0)
        self.connect("delete-event", self._on_close)

        self._encoder = Encoder()
        self._queue: list[str] = []   # paths in order
        self._current_index: int = -1
        self._encoding_active = False
        self._file_streams: dict[str, tuple[list, list]] = {}
        self._file_metadata: dict[str, dict] = {}  # raw probe results keyed by path
        self._completed: set[str] = set()   # successfully encoded paths
        # Per-file setting overrides.  Keys: video_bitrate, audio_bitrate,
        # resolution_height, fps_limit, rotation.  Absent key = use global.
        self._file_settings: dict[str, dict] = {}
        self._preview_path: Optional[str] = None    # currently previewed path
        self._stop_after_path: Optional[str] = None # stop encoding queue after this file

        self._build_ui()
        self._load_settings()
        self._restore_queue()

    # ------------------------------------------------------------------
    # UI Construction
    # ------------------------------------------------------------------

    def _build_ui(self):
        vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        self.add(vbox)

        # ---- Toolbar ---------------------------------------------------
        toolbar = Gtk.Toolbar()
        toolbar.get_style_context().add_class(Gtk.STYLE_CLASS_PRIMARY_TOOLBAR)
        vbox.pack_start(toolbar, False, False, 0)

        self._btn_add = Gtk.ToolButton()
        self._btn_add.set_label("Dateien hinzufügen")
        self._btn_add.set_icon_name("document-open")
        self._btn_add.connect("clicked", self._on_add_files)
        toolbar.insert(self._btn_add, -1)

        self._btn_scan = Gtk.ToolButton()
        self._btn_scan.set_label("Ordner scannen")
        self._btn_scan.set_icon_name("folder-saved-search")
        self._btn_scan.connect("clicked", self._on_scan_folder)
        toolbar.insert(self._btn_scan, -1)

        self._btn_remove = Gtk.ToolButton()
        self._btn_remove.set_label("Entfernen")
        self._btn_remove.set_icon_name("list-remove")
        self._btn_remove.connect("clicked", self._on_remove_selected)
        toolbar.insert(self._btn_remove, -1)

        sep_left = Gtk.SeparatorToolItem()
        sep_left.set_expand(True)
        sep_left.set_draw(False)
        toolbar.insert(sep_left, -1)

        # Language selector – centered between the two button groups
        self._lang_btn = Gtk.MenuButton()
        self._lang_btn.set_label("🇬🇧 English")
        lang_menu = Gtk.Menu()
        item_en = Gtk.MenuItem(label="🇬🇧 English")
        item_de = Gtk.MenuItem(label="🇩🇪 Deutsch")
        item_en.connect("activate", lambda _: self._set_language("en"))
        item_de.connect("activate", lambda _: self._set_language("de"))
        lang_menu.append(item_en)
        lang_menu.append(item_de)
        lang_menu.show_all()
        self._lang_btn.set_popup(lang_menu)
        lang_tool = Gtk.ToolItem()
        lang_tool.add(self._lang_btn)
        toolbar.insert(lang_tool, -1)

        sep_right = Gtk.SeparatorToolItem()
        sep_right.set_expand(True)
        sep_right.set_draw(False)
        toolbar.insert(sep_right, -1)

        self._btn_encode = Gtk.ToolButton()
        self._btn_encode.set_label("Kodieren starten")
        self._btn_encode.set_icon_name("media-playback-start")
        self._btn_encode.connect("clicked", self._on_start_encode)
        toolbar.insert(self._btn_encode, -1)

        self._btn_cancel = Gtk.ToolButton()
        self._btn_cancel.set_label("Abbrechen")
        self._btn_cancel.set_icon_name("process-stop")
        self._btn_cancel.set_sensitive(False)
        self._btn_cancel.connect("clicked", self._on_cancel)
        toolbar.insert(self._btn_cancel, -1)

        # _tr_widgets maps i18n keys → widgets so _apply_language() can patch them.
        self._tr_widgets: dict[str, object] = {}

        # ---- Main area: paned (list | settings) ------------------------
        paned = Gtk.Paned(orientation=Gtk.Orientation.HORIZONTAL)
        paned.set_border_width(8)
        paned.set_position(520)
        vbox.pack_start(paned, True, True, 0)

        # Left: file list
        paned.pack1(self._build_file_list(), True, True)
        # Right: settings + preview (vertical split)
        settings_scroll = Gtk.ScrolledWindow()
        settings_scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        settings_scroll.add(self._build_settings())

        right_pane = Gtk.Paned(orientation=Gtk.Orientation.VERTICAL)
        right_pane.pack1(settings_scroll, True, True)
        right_pane.pack2(self._build_preview_panel(), False, False)
        right_pane.set_position(560)
        paned.pack2(right_pane, False, False)

        # ---- Status bar ------------------------------------------------
        status_box = Gtk.Box(spacing=8)
        status_box.set_border_width(4)
        vbox.pack_start(status_box, False, False, 0)

        self._status_label = Gtk.Label(label="Bereit")
        self._status_label.set_halign(Gtk.Align.START)
        status_box.pack_start(self._status_label, True, True, 0)

        self._global_progress = Gtk.ProgressBar()
        self._global_progress.set_size_request(200, -1)
        status_box.pack_end(self._global_progress, False, False, 0)

        # Apply the default language (English) to all translatable widgets.
        # _load_settings() may override this immediately after.
        self._apply_language()

    def _build_file_list(self) -> Gtk.Widget:
        self._frame_input_files = Gtk.Frame(label="Eingabedateien")
        frame = self._frame_input_files
        frame.set_shadow_type(Gtk.ShadowType.IN)

        # columns: filename, directory, status, progress, full-path,
        #          audio-label(hidden), sub-label(hidden),
        #          resolution, vid-bitrate, aud-bitrate, fps, duration
        self._store = Gtk.ListStore(str, str, str, int, str,
                                    str, str, str, str, str,
                                    str, str, str)

        tv = Gtk.TreeView(model=self._store)
        tv.get_selection().set_mode(Gtk.SelectionMode.MULTIPLE)
        tv.set_grid_lines(Gtk.TreeViewGridLines.VERTICAL)
        self._treeview = tv

        # Light 1 px vertical column separators.
        _css = b"""
            treeview {
                -GtkTreeView-grid-line-width: 1;
                border-color: alpha(white, 0.15);
            }
        """
        _prov = Gtk.CssProvider()
        _prov.load_from_data(_css)
        Gtk.StyleContext.add_provider_for_screen(
            Gdk.Screen.get_default(),
            _prov,
            Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION,
        )

        def col(title, idx):
            cell = Gtk.CellRendererText()
            cell.set_property("ellipsize", Pango.EllipsizeMode.MIDDLE)
            c = Gtk.TreeViewColumn(title, cell, text=idx)
            c.set_expand(True)
            c.set_resizable(True)
            tv.append_column(c)
            return c

        # Stop-after marker column (very narrow, no header text)
        stop_cell = Gtk.CellRendererText()
        stop_cell.set_property("foreground", "#e74c3c")
        stop_col = Gtk.TreeViewColumn("", stop_cell, text=COL_STOP_MARKER)
        stop_col.set_sizing(Gtk.TreeViewColumnSizing.AUTOSIZE)
        stop_col.set_resizable(False)
        tv.append_column(stop_col)

        self._col_filename  = col("Dateiname",   COL_FILENAME)
        self._col_directory = col("Verzeichnis", COL_DIRECTORY)

        # Status column: store raw sentinel, translate on render so language
        # switching always shows the correct string without re-patching the store.
        _status_cell = Gtk.CellRendererText()
        _status_cell.set_property("ellipsize", Pango.EllipsizeMode.MIDDLE)
        self._col_status = Gtk.TreeViewColumn("Status", _status_cell)
        self._col_status.set_expand(True)
        self._col_status.set_resizable(True)
        self._col_status.set_cell_data_func(
            _status_cell,
            lambda col, cell, model, it, _: cell.set_property(
                "text", _status_str(model.get_value(it, COL_STATUS))
            ),
        )
        tv.append_column(self._col_status)

        # Progress column
        prog_cell = ProgressCellRenderer()
        self._col_progress = Gtk.TreeViewColumn("Fortschritt", prog_cell, value=COL_PROGRESS)
        self._col_progress.set_expand(True)
        self._col_progress.set_resizable(True)
        tv.append_column(self._col_progress)

        def _auto_col(title, col_idx):
            """Metadata column: auto-sized to content, no extra expand."""
            cell = Gtk.CellRendererText()
            cell.set_property("xalign", 1.0)
            c = Gtk.TreeViewColumn(title, cell, text=col_idx)
            c.set_sizing(Gtk.TreeViewColumnSizing.AUTOSIZE)
            c.set_resizable(True)
            tv.append_column(c)
            return c

        self._col_resolution  = _auto_col("Auflösung",    COL_RESOLUTION)
        self._col_vid_bitrate = _auto_col("Video-Bitrate", COL_VID_BITRATE)
        self._col_aud_bitrate = _auto_col("Audio-Bitrate", COL_AUD_BITRATE)
        self._col_fps         = _auto_col("FPS",           COL_FPS)
        self._col_duration    = _auto_col("Länge",         COL_DURATION)

        tv.connect("button-press-event", self._on_treeview_button_press)
        tv.connect("row-activated",      self._on_row_activated)
        tv.get_selection().connect("changed", self._on_selection_changed)
        self._store.connect("rows-reordered", self._on_rows_reordered)

        sw = Gtk.ScrolledWindow()
        sw.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        sw.add(tv)

        # DnD: row reorder (internal) + file drop from file manager (external).
        #
        # We use plain drag_source_set (NOT enable_model_drag_source) so that
        # GTK never touches the model's GtkTreeDragSource interface.  That
        # interface would call drag_data_delete (removing the row) as part of
        # the MOVE protocol, causing the premature-disappearance/end-of-list
        # bug.  Instead we use a private target type, supply the data ourselves
        # in drag-data-get, and move the row only in drag-data-received (which
        # fires exclusively on actual drop / button-release).
        _ROW_TARGET = "application/x-h264enc-row"
        tv.drag_source_set(
            Gdk.ModifierType.BUTTON1_MASK,
            [Gtk.TargetEntry.new(_ROW_TARGET, Gtk.TargetFlags.SAME_WIDGET, 0)],
            Gdk.DragAction.MOVE,
        )
        # DestDefaults.DROP only: auto-calls gtk_drag_get_data on drop so
        # drag-data-received fires.  We handle MOTION ourselves to get the
        # TreeView row-level indicator line (set_drag_dest_row), which the
        # generic MOTION default never calls.
        tv.drag_dest_set(
            Gtk.DestDefaults.DROP,
            [
                Gtk.TargetEntry.new(_ROW_TARGET, Gtk.TargetFlags.SAME_WIDGET, 0),
                Gtk.TargetEntry.new("text/uri-list", 0, 1),
            ],
            Gdk.DragAction.MOVE | Gdk.DragAction.COPY,
        )
        tv.connect("drag-motion",        self._on_drag_motion)
        tv.connect("drag-leave",         self._on_drag_leave)
        tv.connect("drag-data-get",      self._on_drag_data_get)
        tv.connect("drag-data-received", self._on_drag_data)

        frame.add(sw)
        return frame

    def _build_settings(self) -> Gtk.Widget:
        outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        outer.set_border_width(4)

        # ---- Output path -----------------------------------------------
        self._frame_output_path = Gtk.Frame(label="Ausgabepfad")
        out_frame = self._frame_output_path
        out_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        out_box.set_border_width(8)
        out_frame.add(out_box)
        outer.pack_start(out_frame, False, False, 0)

        # "Use source directory" checkbox
        self._chk_src_dir = Gtk.CheckButton(
            label="Im Quellverzeichnis speichern"
        )
        self._chk_src_dir.set_active(True)
        self._chk_src_dir.connect("toggled", self._on_src_dir_toggled)
        out_box.pack_start(self._chk_src_dir, False, False, 0)

        # Custom output dir row
        dir_row = Gtk.Box(spacing=4)
        self._entry_outdir = Gtk.Entry()
        self._entry_outdir.set_placeholder_text("Ausgabeverzeichnis wählen…")
        self._entry_outdir.set_sensitive(False)
        dir_row.pack_start(self._entry_outdir, True, True, 0)
        btn_browse = Gtk.Button(label="…")
        btn_browse.connect("clicked", self._on_browse_outdir)
        dir_row.pack_start(btn_browse, False, False, 0)
        self._btn_browse_outdir = btn_browse
        self._btn_browse_outdir.set_sensitive(False)
        out_box.pack_start(dir_row, False, False, 0)

        # Work directory (optional temp encode location)
        self._chk_work_dir = Gtk.CheckButton(
            label="Arbeitsverzeichnis nutzen (erst dort kodieren, dann kopieren)"
        )
        self._chk_work_dir.connect("toggled", self._on_work_dir_toggled)
        out_box.pack_start(self._chk_work_dir, False, False, 0)

        work_row = Gtk.Box(spacing=4)
        self._entry_work_dir = Gtk.Entry()
        self._entry_work_dir.set_placeholder_text("Arbeitsverzeichnis wählen…")
        self._entry_work_dir.set_sensitive(False)
        work_row.pack_start(self._entry_work_dir, True, True, 0)
        self._btn_browse_workdir = Gtk.Button(label="…")
        self._btn_browse_workdir.connect("clicked", self._on_browse_workdir)
        self._btn_browse_workdir.set_sensitive(False)
        work_row.pack_start(self._btn_browse_workdir, False, False, 0)
        out_box.pack_start(work_row, False, False, 0)

        Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL)

        # Output naming
        self._frame_output_name = Gtk.Frame(label="Ausgabename")
        naming_frame = self._frame_output_name
        naming_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        naming_box.set_border_width(8)
        naming_frame.add(naming_box)
        outer.pack_start(naming_frame, False, False, 0)

        self._radio_new_name = Gtk.RadioButton.new_with_label(
            None, "Neuen Namen verwenden"
        )
        self._radio_same_name = Gtk.RadioButton.new_with_label_from_widget(
            self._radio_new_name, "Gleichen Dateinamen behalten"
        )
        self._radio_replace = Gtk.RadioButton.new_with_label_from_widget(
            self._radio_new_name, "Quelldatei ersetzen (Original löschen)"
        )
        # "Same name" only makes sense when output goes to a different dir;
        # "Replace" only makes sense when output stays in the source dir.
        # set_no_show_all prevents show_all() from overriding visibility;
        # we then set the correct initial state explicitly (source-dir is
        # the default → replace visible, same-name hidden).
        self._radio_same_name.set_no_show_all(True)
        self._radio_same_name.set_visible(False)
        self._radio_replace.set_no_show_all(True)
        self._radio_replace.set_visible(True)

        self._radio_new_name.connect("toggled", self._on_naming_toggled)
        self._radio_same_name.connect("toggled", self._on_naming_toggled)
        naming_box.pack_start(self._radio_new_name, False, False, 0)
        naming_box.pack_start(self._radio_same_name, False, False, 0)
        naming_box.pack_start(self._radio_replace, False, False, 0)

        suffix_row = Gtk.Box(spacing=4)
        self._lbl_suffix = Gtk.Label(label="Suffix:")
        suffix_row.pack_start(self._lbl_suffix, False, False, 0)
        self._entry_suffix = Gtk.Entry()
        self._entry_suffix.set_text("_h264")
        self._entry_suffix.set_width_chars(10)
        suffix_row.pack_start(self._entry_suffix, False, False, 0)
        naming_box.pack_start(suffix_row, False, False, 0)
        self._suffix_row = suffix_row

        # ---- Bitrate settings ------------------------------------------
        self._frame_bitrate = Gtk.Frame(label="Bitrate-Einstellungen")
        br_frame = self._frame_bitrate
        br_grid = Gtk.Grid()
        br_grid.set_column_spacing(8)
        br_grid.set_row_spacing(8)
        br_grid.set_border_width(8)
        br_frame.add(br_grid)
        outer.pack_start(br_frame, False, False, 0)

        self._lbl_vid_bitrate = Gtk.Label(label="Video-Bitrate:")
        br_grid.attach(self._lbl_vid_bitrate, 0, 0, 1, 1)
        self._combo_vbr = Gtk.ComboBoxText()
        for label, _ in VIDEO_BITRATES:
            self._combo_vbr.append_text(label)
        self._combo_vbr.set_active(DEFAULT_VIDEO_IDX)
        br_grid.attach(self._combo_vbr, 1, 0, 1, 1)

        self._lbl_aud_bitrate = Gtk.Label(label="Audio-Bitrate:")
        br_grid.attach(self._lbl_aud_bitrate, 0, 1, 1, 1)
        self._combo_abr = Gtk.ComboBoxText()
        for label, _ in AUDIO_BITRATES:
            self._combo_abr.append_text(label)
        self._combo_abr.set_active(DEFAULT_AUDIO_IDX)
        br_grid.attach(self._combo_abr, 1, 1, 1, 1)

        self._lbl_resolution = Gtk.Label(label="Auflösung:")
        self._lbl_resolution.set_halign(Gtk.Align.START)
        br_grid.attach(self._lbl_resolution, 0, 2, 1, 1)
        self._combo_res = Gtk.ComboBoxText()
        for label, _ in RESOLUTIONS:
            self._combo_res.append_text(label)
        self._combo_res.set_active(DEFAULT_RES_IDX)
        br_grid.attach(self._combo_res, 1, 2, 1, 1)

        self._lbl_res_note = Gtk.Label()
        self._lbl_res_note.set_markup(
            '<small><i>Nicht-16:9-Quellen werden automatisch\n'
            'im Originalseitenverhältnis skaliert.</i></small>'
        )
        self._lbl_res_note.set_halign(Gtk.Align.START)
        br_grid.attach(self._lbl_res_note, 0, 3, 2, 1)

        # FPS option
        self._chk_fps_limit = Gtk.CheckButton(
            label=f"HFR-Videos (>{int(HIGH_FPS_THRESHOLD)} fps) auf 30 fps begrenzen")
        br_grid.attach(self._chk_fps_limit, 0, 4, 2, 1)

        # High-FPS note
        self._lbl_fps_note = Gtk.Label()
        self._lbl_fps_note.set_markup(
            f'<small><i>Ohne Begrenzung: ≥{int(HIGH_FPS_THRESHOLD)} fps\n'
            f'→ Video-Bitrate wird verdoppelt.</i></small>'
        )
        self._lbl_fps_note.set_halign(Gtk.Align.START)
        br_grid.attach(self._lbl_fps_note, 0, 5, 2, 1)

        # ---- Post-encoding action --------------------------------------
        self._frame_post_action = Gtk.Frame(label="Aktion nach Kodierung")
        action_frame = self._frame_post_action
        action_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        action_box.set_border_width(8)
        action_frame.add(action_box)

        self._radio_action_nothing = Gtk.RadioButton.new_with_label(
            None, "Nichts tun")
        self._radio_action_quit = Gtk.RadioButton.new_with_label_from_widget(
            self._radio_action_nothing, "Programm schließen")
        self._radio_action_shutdown = Gtk.RadioButton.new_with_label_from_widget(
            self._radio_action_nothing, "Computer herunterfahren")

        action_box.pack_start(self._radio_action_nothing,  False, False, 0)
        action_box.pack_start(self._radio_action_quit,     False, False, 0)
        action_box.pack_start(self._radio_action_shutdown, False, False, 0)

        outer.pack_start(action_frame, False, False, 0)
        outer.pack_end(Gtk.Box(), True, True, 0)  # spacer

        # Auto-save global settings whenever any control changes
        for w in (self._combo_vbr, self._combo_abr, self._combo_res):
            w.connect("changed", self._save_settings)
        for w in (self._chk_fps_limit, self._chk_src_dir, self._chk_work_dir,
                  self._radio_new_name, self._radio_same_name, self._radio_replace,
                  self._radio_action_nothing, self._radio_action_quit,
                  self._radio_action_shutdown):
            w.connect("toggled", self._save_settings)
        for w in (self._entry_suffix, self._entry_outdir, self._entry_work_dir):
            w.connect("changed", self._save_settings)

        return outer

    def _build_preview_panel(self) -> Gtk.Widget:
        self._frame_preview = Gtk.Frame(label="Vorschau")
        frame = self._frame_preview
        frame.set_shadow_type(Gtk.ShadowType.IN)
        frame.set_size_request(-1, 230)

        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        box.set_valign(Gtk.Align.CENTER)
        box.set_halign(Gtk.Align.CENTER)
        box.set_vexpand(True)

        self._preview_image = Gtk.Image()
        self._preview_image.set_no_show_all(True)

        self._preview_label = Gtk.Label()
        self._preview_label.set_markup(i18n.t("lbl_no_video"))
        self._preview_label.set_sensitive(False)

        box.pack_start(self._preview_image, False, False, 0)
        box.pack_start(self._preview_label, False, False, 0)

        frame.add(box)
        return frame

    # ------------------------------------------------------------------
    # Language switching
    # ------------------------------------------------------------------

    def _set_language(self, lang: str):
        """Switch UI language, persist the choice, and refresh all labels."""
        i18n.set_lang(lang)
        self._apply_language()
        self._save_settings()

    def _apply_language(self):
        """Update every translatable widget to the current i18n language."""
        # Current language flag label for the MenuButton
        lang_labels = {"en": "🇬🇧 English", "de": "🇩🇪 Deutsch"}
        self._lang_btn.set_label(lang_labels.get(i18n._lang, "🇬🇧 English"))

        # Toolbar buttons + tooltips
        self._btn_add.set_label(i18n.t("btn_add_files"))
        self._btn_add.set_tooltip_text(i18n.t("tip_add_files"))
        self._btn_scan.set_label(i18n.t("btn_scan_folder"))
        self._btn_scan.set_tooltip_text(i18n.t("tip_scan_folder"))
        self._btn_remove.set_label(i18n.t("btn_remove"))
        self._btn_remove.set_tooltip_text(i18n.t("tip_remove"))
        self._btn_encode.set_label(i18n.t("btn_encode_start"))
        self._btn_encode.set_tooltip_text(i18n.t("tip_encode_start"))
        self._btn_cancel.set_label(i18n.t("btn_cancel"))
        self._btn_cancel.set_tooltip_text(i18n.t("tip_cancel"))
        self._lang_btn.set_tooltip_text(i18n.t("tip_lang"))

        # File list frame
        self._frame_input_files.set_label(i18n.t("frame_input_files"))

        # TreeView column headers
        self._col_filename.set_title(i18n.t("col_filename"))
        self._col_directory.set_title(i18n.t("col_directory"))
        self._col_status.set_title(i18n.t("col_status"))
        self._col_progress.set_title(i18n.t("col_progress"))
        self._col_resolution.set_title(i18n.t("col_resolution"))
        self._col_vid_bitrate.set_title(i18n.t("col_vid_bitrate"))
        self._col_aud_bitrate.set_title(i18n.t("col_aud_bitrate"))
        self._col_fps.set_title(i18n.t("col_fps"))
        self._col_duration.set_title(i18n.t("col_duration"))

        # Settings frames
        self._frame_output_path.set_label(i18n.t("frame_output_path"))
        self._chk_src_dir.set_label(i18n.t("chk_src_dir"))
        self._entry_outdir.set_placeholder_text(i18n.t("entry_outdir_ph"))
        self._chk_work_dir.set_label(i18n.t("chk_work_dir"))
        self._entry_work_dir.set_placeholder_text(i18n.t("entry_work_dir_ph"))
        self._frame_output_name.set_label(i18n.t("frame_output_name"))
        self._radio_new_name.set_label(i18n.t("radio_new_name"))
        self._radio_same_name.set_label(i18n.t("radio_same_name"))
        self._radio_replace.set_label(i18n.t("radio_replace"))
        self._lbl_suffix.set_label(i18n.t("lbl_suffix"))

        self._frame_bitrate.set_label(i18n.t("frame_bitrate"))
        self._lbl_vid_bitrate.set_label(i18n.t("lbl_vid_bitrate"))
        self._lbl_aud_bitrate.set_label(i18n.t("lbl_aud_bitrate"))
        self._lbl_resolution.set_label(i18n.t("lbl_resolution"))
        self._lbl_res_note.set_markup(i18n.t("res_note"))
        self._chk_fps_limit.set_label(
            i18n.t("chk_fps_limit").format(threshold=int(HIGH_FPS_THRESHOLD))
        )
        self._lbl_fps_note.set_markup(
            i18n.t("fps_note").format(threshold=int(HIGH_FPS_THRESHOLD))
        )

        self._frame_post_action.set_label(i18n.t("frame_post_action"))
        self._radio_action_nothing.set_label(i18n.t("radio_nothing"))
        self._radio_action_quit.set_label(i18n.t("radio_quit"))
        self._radio_action_shutdown.set_label(i18n.t("radio_shutdown"))

        # Preview panel
        self._frame_preview.set_label(i18n.t("frame_preview"))
        # Only update the preview label if no video is being shown
        if not self._preview_image.get_visible():
            self._preview_label.set_markup(i18n.t("lbl_no_video"))

        # Status bar (only reset if it still shows the "Ready" sentinel)
        # We don't overwrite an active encoding status message.
        current_status = self._status_label.get_text()
        de_ready = "Bereit"
        en_ready = "Ready"
        if current_status in (de_ready, en_ready):
            self._status_label.set_text(i18n.t("status_ready"))

        # Re-populate the audio bitrate combo box
        abr_idx = self._combo_abr.get_active()
        self._combo_abr.handler_block_by_func(self._save_settings)
        self._combo_abr.remove_all()
        abr_items = [i18n.t("audio_original")] + [lbl for lbl, _ in AUDIO_BITRATES[1:]]
        for lbl in abr_items:
            self._combo_abr.append_text(lbl)
        self._combo_abr.set_active(abr_idx if 0 <= abr_idx < len(abr_items) else DEFAULT_AUDIO_IDX)
        self._combo_abr.handler_unblock_by_func(self._save_settings)

        # Re-populate the resolution combo box
        res_idx = self._combo_res.get_active()
        self._combo_res.handler_block_by_func(self._save_settings)
        self._combo_res.remove_all()
        res_items = [i18n.t("res_original")] + [lbl for lbl, _ in RESOLUTIONS[1:]]
        for lbl in res_items:
            self._combo_res.append_text(lbl)
        self._combo_res.set_active(res_idx if 0 <= res_idx < len(res_items) else DEFAULT_RES_IDX)
        self._combo_res.handler_unblock_by_func(self._save_settings)

        # The status column uses a cell_data_func that calls _status_str() on
        # every render, so a language switch is reflected automatically.  We
        # just need to force a redraw of the TreeView.
        self._treeview.queue_draw()

    # ------------------------------------------------------------------
    # Signal Handlers
    # ------------------------------------------------------------------

    def _on_close(self, *_):
        if self._encoding_active:
            self._encoder.cancel()
        Gtk.main_quit()

    def _on_scan_folder(self, *_):
        dlg = ScanDialog(parent=self)
        dlg.connect("files-selected", self._on_scan_files_selected)
        dlg.show_all()

    def _on_scan_files_selected(self, _dlg, paths: list):
        for path in paths:
            self._add_file(path)
        n = len(paths)
        s = "" if n == 1 else "en"
        self._status_label.set_text(i18n.t("scan_added").format(n=n, s=s))

    def _on_add_files(self, *_):
        dialog = Gtk.FileChooserDialog(
            title=i18n.t("dlg_add_files_title"),
            parent=self,
            action=Gtk.FileChooserAction.OPEN,
        )
        dialog.add_buttons(
            Gtk.STOCK_CANCEL, Gtk.ResponseType.CANCEL,
            Gtk.STOCK_OPEN,   Gtk.ResponseType.OK,
        )
        dialog.set_select_multiple(True)

        filt = Gtk.FileFilter()
        filt.set_name(i18n.t("dlg_filter_videos"))
        for ext in ["*.mp4", "*.mkv", "*.avi", "*.mov", "*.wmv",
                    "*.flv", "*.webm", "*.m4v", "*.ts", "*.mts"]:
            filt.add_pattern(ext)
        dialog.add_filter(filt)

        all_filt = Gtk.FileFilter()
        all_filt.set_name(i18n.t("dlg_filter_all"))
        all_filt.add_pattern("*")
        dialog.add_filter(all_filt)

        if dialog.run() == Gtk.ResponseType.OK:
            for path in dialog.get_filenames():
                self._add_file(path)
        dialog.destroy()

    def _on_remove_selected(self, *_):
        sel = self._treeview.get_selection()
        model, paths = sel.get_selected_rows()
        # Remove in reverse order to keep iters valid
        for path in reversed(paths):
            it = model.get_iter(path)
            full = model.get_value(it, COL_FULLPATH)
            if full in self._queue:
                self._queue.remove(full)
            self._file_streams.pop(full, None)
            self._file_settings.pop(full, None)
            self._completed.discard(full)
            model.remove(it)
        self._save_queue()

    def _on_src_dir_toggled(self, btn):
        use_src = btn.get_active()
        self._entry_outdir.set_sensitive(not use_src)
        self._btn_browse_outdir.set_sensitive(not use_src)

        # Source-dir mode: "Quelldatei ersetzen" available, "Gleichen Namen"
        # hidden (would be identical to "ersetzen" in the same folder).
        # Custom-dir mode: "Gleichen Namen" available, "ersetzen" greyed out.
        self._radio_replace.set_sensitive(use_src)
        self._radio_replace.set_visible(use_src)
        self._radio_same_name.set_sensitive(not use_src)
        self._radio_same_name.set_visible(not use_src)

        # If the now-hidden option was selected, fall back to "Neuen Namen".
        if use_src and self._radio_same_name.get_active():
            self._radio_new_name.set_active(True)
        if not use_src and self._radio_replace.get_active():
            self._radio_new_name.set_active(True)

    def _on_naming_toggled(self, btn):
        # Suffix only relevant when "Neuen Namen verwenden" is active.
        self._suffix_row.set_sensitive(self._radio_new_name.get_active())

    def _on_browse_outdir(self, *_):
        dialog = Gtk.FileChooserDialog(
            title=i18n.t("dlg_browse_title"),
            parent=self,
            action=Gtk.FileChooserAction.SELECT_FOLDER,
        )
        dialog.add_buttons(
            Gtk.STOCK_CANCEL, Gtk.ResponseType.CANCEL,
            Gtk.STOCK_OPEN,   Gtk.ResponseType.OK,
        )
        if dialog.run() == Gtk.ResponseType.OK:
            self._entry_outdir.set_text(dialog.get_filename())
        dialog.destroy()

    def _on_work_dir_toggled(self, btn):
        active = btn.get_active()
        self._entry_work_dir.set_sensitive(active)
        self._btn_browse_workdir.set_sensitive(active)

    def _on_browse_workdir(self, *_):
        dialog = Gtk.FileChooserDialog(
            title=i18n.t("dlg_browse_title"),
            parent=self,
            action=Gtk.FileChooserAction.SELECT_FOLDER,
        )
        dialog.add_buttons(
            Gtk.STOCK_CANCEL, Gtk.ResponseType.CANCEL,
            Gtk.STOCK_OPEN,   Gtk.ResponseType.OK,
        )
        if dialog.run() == Gtk.ResponseType.OK:
            self._entry_work_dir.set_text(dialog.get_filename())
        dialog.destroy()

    def _on_drag_motion(self, widget, ctx, x, y, time):
        """Show the row-level drop-indicator line while dragging."""
        drop = widget.get_dest_row_at_pos(x, y)
        if drop is not None:
            path, pos = drop
            widget.set_drag_dest_row(path, pos)
        else:
            # Below all rows → indicator after the last row
            n = self._store.iter_n_children(None)
            if n > 0:
                last_it = self._store.iter_nth_child(None, n - 1)
                widget.set_drag_dest_row(
                    self._store.get_path(last_it),
                    Gtk.TreeViewDropPosition.AFTER,
                )
        # Tell GDK the drop is accepted and which action we'll perform
        src = Gtk.drag_get_source_widget(ctx)
        action = Gdk.DragAction.MOVE if src is widget else Gdk.DragAction.COPY
        Gdk.drag_status(ctx, action, time)
        return True   # we handled the motion

    def _on_drag_leave(self, widget, ctx, time):
        """Clear the drop-indicator line when the drag leaves the widget."""
        widget.set_drag_dest_row(None, Gtk.TreeViewDropPosition.BEFORE)

    def _on_drag_data_get(self, widget, ctx, data, info, time):
        """Supply the dragged row's full path as the drag payload."""
        model, paths = widget.get_selection().get_selected_rows()
        if paths:
            it = self._store.get_iter(paths[0])
            file_path = self._store.get_value(it, COL_FULLPATH)
            data.set(data.get_target(), 8, file_path.encode("utf-8"))

    def _on_drag_data(self, widget, drag_context, x, y, data, info, time):
        if info == 0:
            # ---- Internal row reorder -----------------------------------
            try:
                file_path = data.get_data().decode("utf-8")
            except Exception:
                Gtk.drag_finish(drag_context, False, False, time)
                return
            src_iter = self._find_row(file_path)
            if src_iter:
                drop = widget.get_dest_row_at_pos(x, y)
                if drop is None:
                    self._store.move_before(src_iter, None)   # to end
                else:
                    dest_path, pos = drop
                    dest_iter = self._store.get_iter(dest_path)
                    if pos in (Gtk.TreeViewDropPosition.BEFORE,
                               Gtk.TreeViewDropPosition.INTO_OR_BEFORE):
                        self._store.move_before(src_iter, dest_iter)
                    else:
                        self._store.move_after(src_iter, dest_iter)
                # Sync queue immediately — don't rely on rows-reordered signal
                # whose gint* new_order array can fail to marshal in PyGObject.
                self._sync_queue_from_store()
                self._save_queue()
                # Mirror the new order into self._jobs so _encode_next
                # uses the correct sequence during active encoding.
                # Files added after encoding started won't be in jobs_by_path,
                # so build fresh jobs for them on demand.
                if self._encoding_active and hasattr(self, "_jobs"):
                    jobs_by_path = {j.input_path: j for j in self._jobs}
                    new_jobs = [
                        jobs_by_path[p] if p in jobs_by_path else self._build_job(p)
                        for p in self._queue
                    ]
                    self._jobs[:] = new_jobs
            Gtk.drag_finish(drag_context, src_iter is not None, False, time)
            return

        # ---- External file / folder drop (text/uri-list) ----------------
        from gi.repository import GLib
        for uri in data.get_uris():
            uri = uri.strip()
            if not uri:
                continue
            try:
                path, _ = GLib.filename_from_uri(uri)
            except Exception:
                path = unquote(uri.removeprefix("file://"))
            if os.path.isfile(path):
                self._add_file(path)
            elif os.path.isdir(path):
                for root, _dirs, files in os.walk(path):
                    for f in sorted(files):
                        if os.path.splitext(f)[1].lower() in VIDEO_EXTENSIONS:
                            self._add_file(os.path.join(root, f))
        Gtk.drag_finish(drag_context, True, False, time)

    def _build_job(self, path: str) -> EncodeJob:
        """Build an EncodeJob for *path* using the current UI settings."""
        use_src_dir   = self._chk_src_dir.get_active()
        replace_orig  = self._radio_replace.get_active()
        keep_name     = self._radio_same_name.get_active()
        output_dir    = self._entry_outdir.get_text().strip()
        custom_suffix = self._entry_suffix.get_text().strip()
        work_dir = (self._entry_work_dir.get_text().strip()
                    if self._chk_work_dir.get_active() else None)
        work_dir = work_dir or None  # treat empty string as None
        global_vbr    = VIDEO_BITRATES[self._combo_vbr.get_active()][1]
        global_abr    = AUDIO_BITRATES[self._combo_abr.get_active()][1]
        global_res    = RESOLUTIONS[self._combo_res.get_active()][1]
        global_fps    = 30 if self._chk_fps_limit.get_active() else None

        out_path = make_output_path(
            input_path=path,
            output_dir=output_dir,
            use_source_dir=use_src_dir,
            replace_original=replace_orig,
            keep_name=keep_name,
            custom_suffix=custom_suffix,
        )
        fs = self._file_settings.get(path, {})
        video_bitrate     = fs.get("video_bitrate",     global_vbr)
        audio_bitrate     = fs.get("audio_bitrate",     global_abr)
        resolution_height = fs.get("resolution_height", global_res)
        fps_limit         = fs.get("fps_limit",         global_fps)
        rotation          = fs.get("rotation", 0)

        src = self._file_metadata.get(path, {})
        if resolution_height is not None:
            src_h = src.get("height", 0)
            if src_h > 0 and src_h <= resolution_height:
                resolution_height = None
        if audio_bitrate is not None:
            src_audio_kbps = src.get("audio_kbps")
            if src_audio_kbps is not None:
                if src_audio_kbps <= int(audio_bitrate.rstrip("k")):
                    audio_bitrate = None

        audio_streams, sub_streams = self._file_streams.get(path, ([], []))
        sel_audio = [s["rel_idx"] for s in audio_streams if s["enabled"]]
        sel_subs  = [s["rel_idx"] for s in sub_streams  if s["enabled"]]
        return EncodeJob(
            input_path=path,
            output_path=out_path,
            video_bitrate=video_bitrate,
            audio_bitrate=audio_bitrate,
            replace_original=replace_orig,
            resolution_height=resolution_height,
            selected_audio=sel_audio if audio_streams else None,
            selected_subtitles=sel_subs if sub_streams else None,
            rotation=rotation,
            fps_limit=fps_limit,
            work_dir=work_dir,
        )

    def _on_start_encode(self, *_):
        if not self._queue:
            self._show_error(i18n.t("err_no_files"))
            return

        use_src_dir  = self._chk_src_dir.get_active()
        output_dir   = self._entry_outdir.get_text().strip()

        if not use_src_dir and not output_dir:
            self._show_error(i18n.t("err_no_outdir"))
            return

        self._jobs: list[EncodeJob] = []
        for path in self._queue:
            self._jobs.append(self._build_job(path))

        self._encoding_active = True
        self._btn_encode.set_sensitive(False)
        self._btn_cancel.set_sensitive(True)
        self._current_index = 0
        self._encode_next()

    def _on_cancel(self, *_):
        self._encoder.cancel()
        self._btn_cancel.set_sensitive(False)
        self._status_label.set_text(i18n.t("status_cancelling"))

    # ------------------------------------------------------------------
    # Encoding Logic
    # ------------------------------------------------------------------

    def _encode_next(self):
        if self._current_index >= len(self._jobs):
            self._encoding_done()
            return

        job  = self._jobs[self._current_index]
        path = job.input_path

        # Find row in store
        row_iter = self._find_row(path)
        if row_iter:
            self._store.set_value(row_iter, COL_STATUS, STATUS_ENCODING)
            self._store.set_value(row_iter, COL_PROGRESS, 0)

        fps = get_fps(path)
        needs_fps_filter = job.fps_limit is not None and fps > job.fps_limit
        fps_note = (
            i18n.t("fps_hfr_note").format(fps=fps)
            if fps >= HIGH_FPS_THRESHOLD and not needs_fps_filter else ""
        )

        target_h = job.resolution_height
        if target_h is not None:
            src_w, src_h = get_video_dimensions(path)
            out_w, out_h = compute_output_dimensions(src_w, src_h, target_h)
            res_note = f", {out_w}×{out_h}"
        else:
            res_note = ""

        self._status_label.set_text(
            i18n.t("encoding_status").format(
                n=self._current_index + 1,
                total=len(self._jobs),
                name=os.path.basename(path),
                res=res_note,
                fps=fps_note,
            )
        )

        def on_progress(frac):
            GLib.idle_add(self._update_progress, path, frac)

        def on_done(success, msg):
            GLib.idle_add(self._job_done, path, success, msg)

        self._encoder.encode(job, on_progress, on_done)

    def _update_progress(self, path: str, frac: float):
        row_iter = self._find_row(path)
        if row_iter:
            self._store.set_value(row_iter, COL_PROGRESS, int(frac * 100))
        # Global progress
        total = len(self._jobs)
        done  = self._current_index
        global_frac = (done + frac) / total if total else 0
        self._global_progress.set_fraction(global_frac)

    def _job_done(self, path: str, success: bool, msg: str):
        row_iter = self._find_row(path)
        if row_iter:
            if success:
                self._store.set_value(row_iter, COL_STATUS,   STATUS_DONE)
                self._store.set_value(row_iter, COL_PROGRESS, 100)
                self._completed.add(path)
                self._save_queue()   # remove finished file from persistent list
            elif msg in ("Abgebrochen", "CANCELLED"):
                self._store.set_value(row_iter, COL_STATUS,   STATUS_CANCELLED)
            else:
                # Show first line in the column (space is limited) and open a
                # dialog with the full output so the user can read the details.
                first_line = msg.splitlines()[0]
                self._store.set_value(row_iter, COL_STATUS,
                                      f"{STATUS_ERROR}: {first_line}")
                self._show_error_detail(os.path.basename(path), msg)

        self._current_index += 1
        if self._encoding_active:
            if success and self._stop_after_path == path:
                self._set_stop_after(None)
                self._encoding_done()
            else:
                self._encode_next()

    def _encoding_done(self):
        self._encoding_active = False
        self._btn_encode.set_sensitive(True)
        self._btn_cancel.set_sensitive(False)
        self._global_progress.set_fraction(1.0)
        self._status_label.set_text(i18n.t("status_all_done"))
        if self._stop_after_path:
            self._set_stop_after(None)

        if self._radio_action_quit.get_active():
            Gtk.main_quit()
        elif self._radio_action_shutdown.get_active():
            subprocess.Popen(["systemctl", "poweroff"])

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _add_file(self, path: str):
        if path in self._queue:
            return
        self._queue.append(path)
        self._file_streams[path] = ([], [])
        self._save_queue()   # persist immediately so a crash loses nothing
        row_ref = Gtk.TreeRowReference.new(
            self._store,
            self._store.get_path(
                self._store.append([
                    os.path.basename(path),
                    os.path.dirname(path),
                    STATUS_PENDING,
                    0,
                    path,
                    i18n.t("loading"), i18n.t("loading"),  # audio / sub labels
                    "–", "–", "–", "–", "–",               # resolution / vid-br / aud-br / fps / duration
                    "",                                     # stop marker
                ])
            ),
        )

        # Fill streams and tech info: use cached metadata if available
        # (happens on queue restore), otherwise probe via ffprobe.
        def _probe():
            cached = self._file_metadata.get(path)
            # Re-probe if audio streams exist but bitrate wasn't detected last time.
            if cached and cached.get("audio") and cached.get("audio_kbps") is None:
                cached = None
            meta = cached or get_file_metadata(path)

            def _apply():
                self._file_streams[path]   = (meta["audio"], meta["subtitles"])
                self._file_metadata[path]  = meta
                tp = row_ref.get_path()
                if tp:
                    it = self._store.get_iter(tp)
                    self._store.set_value(it, COL_AUDIO_LABEL,
                                         self._stream_summary(meta["audio"]))
                    self._store.set_value(it, COL_SUB_LABEL,
                                         self._stream_summary(meta["subtitles"]))
                    self._store.set_value(it, COL_RESOLUTION,
                                         _fmt_resolution(meta["width"], meta["height"]))
                    self._store.set_value(it, COL_VID_BITRATE,
                                         _fmt_kbps(meta["video_kbps"]))
                    self._store.set_value(it, COL_AUD_BITRATE,
                                         _fmt_kbps(meta["audio_kbps"]))
                    self._store.set_value(it, COL_FPS,
                                         _fmt_fps(meta["fps"]))
                    self._store.set_value(it, COL_DURATION,
                                         _fmt_duration(meta["duration_secs"]))
                # If encoding is already running, append a job for this file
                # so _encode_next won't stop before reaching it.
                if self._encoding_active and hasattr(self, "_jobs"):
                    already = any(j.input_path == path for j in self._jobs)
                    if not already:
                        self._jobs.append(self._build_job(path))
                return False

            GLib.idle_add(_apply)

        threading.Thread(target=_probe, daemon=True).start()

    # ------------------------------------------------------------------
    # Queue persistence
    # ------------------------------------------------------------------

    def _save_queue(self):
        """Write pending queue + per-file settings to QUEUE_FILE as JSON."""
        try:
            os.makedirs(os.path.dirname(QUEUE_FILE), exist_ok=True)
            data = {
                "queue": [
                    {
                        "path": p,
                        "settings": self._file_settings.get(p, {}),
                        "meta":     self._file_metadata.get(p, {}),
                    }
                    for p in self._queue
                    if p not in self._completed
                ]
            }
            with open(QUEUE_FILE, "w", encoding="utf-8") as fh:
                json.dump(data, fh, indent=2, ensure_ascii=False)
        except Exception as exc:
            print(f"[queue] Fehler beim Speichern: {exc}", flush=True)

    @staticmethod
    def _load_queue() -> list[tuple[str, dict, dict]]:
        """Return (path, settings, meta) triples from QUEUE_FILE that still exist."""
        try:
            with open(QUEUE_FILE, encoding="utf-8") as fh:
                raw = fh.read()
            try:
                data = json.loads(raw)
                return [
                    (e["path"], e.get("settings", {}), e.get("meta", {}))
                    for e in data.get("queue", [])
                    if os.path.isfile(e.get("path", ""))
                ]
            except (json.JSONDecodeError, KeyError):
                # Legacy plain-text format (one path per line)
                return [
                    (line.strip(), {}, {})
                    for line in raw.splitlines()
                    if line.strip() and os.path.isfile(line.strip())
                ]
        except FileNotFoundError:
            return []
        except Exception as exc:
            print(f"[queue] Fehler beim Laden: {exc}", flush=True)
            return []

    def _restore_queue(self):
        """Add persisted pending paths back into the queue on startup."""
        entries = self._load_queue()
        if not entries:
            return
        for path, settings, meta in entries:
            self._file_settings[path] = settings
            if meta:
                # Pre-populate metadata cache so _add_file skips the ffprobe call
                self._file_metadata[path] = meta
        for path, settings, meta in entries:
            self._add_file(path)
        n = len(entries)
        self._status_label.set_text(i18n.t("scan_restored").format(n=n))

    # ------------------------------------------------------------------
    # Global settings persistence
    # ------------------------------------------------------------------

    def _save_settings(self, *_):
        try:
            os.makedirs(os.path.dirname(SETTINGS_FILE), exist_ok=True)
            if self._radio_same_name.get_active():
                naming = "same_name"
            elif self._radio_replace.get_active():
                naming = "replace"
            else:
                naming = "new_name"
            if self._radio_action_quit.get_active():
                action = "quit"
            elif self._radio_action_shutdown.get_active():
                action = "shutdown"
            else:
                action = "nothing"
            data = {
                "video_bitrate_idx": self._combo_vbr.get_active(),
                "audio_bitrate_idx": self._combo_abr.get_active(),
                "resolution_idx":    self._combo_res.get_active(),
                "fps_limit":         self._chk_fps_limit.get_active(),
                "src_dir":           self._chk_src_dir.get_active(),
                "out_dir":           self._entry_outdir.get_text(),
                "work_dir_enabled":  self._chk_work_dir.get_active(),
                "work_dir":          self._entry_work_dir.get_text(),
                "naming":            naming,
                "suffix":            self._entry_suffix.get_text(),
                "post_action":       action,
                "language":          i18n._lang,
            }
            with open(SETTINGS_FILE, "w", encoding="utf-8") as fh:
                json.dump(data, fh, indent=2, ensure_ascii=False)
        except Exception as exc:
            print(f"[settings] Fehler beim Speichern: {exc}", flush=True)

    def _load_settings(self):
        try:
            with open(SETTINGS_FILE, encoding="utf-8") as fh:
                data = json.load(fh)
        except Exception:
            return

        vbr = data.get("video_bitrate_idx", DEFAULT_VIDEO_IDX)
        if 0 <= vbr < len(VIDEO_BITRATES):
            self._combo_vbr.set_active(vbr)

        abr = data.get("audio_bitrate_idx", DEFAULT_AUDIO_IDX)
        if 0 <= abr < len(AUDIO_BITRATES):
            self._combo_abr.set_active(abr)

        res = data.get("resolution_idx", DEFAULT_RES_IDX)
        if 0 <= res < len(RESOLUTIONS):
            self._combo_res.set_active(res)

        self._chk_fps_limit.set_active(data.get("fps_limit", False))

        src_dir = data.get("src_dir", True)
        self._chk_src_dir.set_active(src_dir)
        out_dir = data.get("out_dir", "")
        if out_dir:
            self._entry_outdir.set_text(out_dir)

        naming = data.get("naming", "new_name")
        if naming == "same_name":
            self._radio_same_name.set_active(True)
        elif naming == "replace":
            self._radio_replace.set_active(True)
        else:
            self._radio_new_name.set_active(True)

        suffix = data.get("suffix", "_h264")
        self._entry_suffix.set_text(suffix)

        work_dir_enabled = data.get("work_dir_enabled", False)
        self._chk_work_dir.set_active(work_dir_enabled)
        work_dir = data.get("work_dir", "")
        if work_dir:
            self._entry_work_dir.set_text(work_dir)
        # Sync sensitivity (toggled signal not fired when set_active is called
        # before the widget tree is fully shown).
        self._entry_work_dir.set_sensitive(work_dir_enabled)
        self._btn_browse_workdir.set_sensitive(work_dir_enabled)

        action = data.get("post_action", "nothing")
        if action == "quit":
            self._radio_action_quit.set_active(True)
        elif action == "shutdown":
            self._radio_action_shutdown.set_active(True)
        else:
            self._radio_action_nothing.set_active(True)

        # Restore saved language (default: "en")
        saved_lang = data.get("language", "en")
        if saved_lang in ("en", "de"):
            i18n.set_lang(saved_lang)
            self._apply_language()

    def _sync_queue_from_store(self):
        """Rebuild self._queue to match the current ListStore row order."""
        it = self._store.get_iter_first()
        self._queue = []
        while it:
            self._queue.append(self._store.get_value(it, COL_FULLPATH))
            it = self._store.iter_next(it)

    def _on_rows_reordered(self, model, path, tree_iter, new_order):
        """Called whenever rows are reordered by D&D or programmatically."""
        self._sync_queue_from_store()
        self._save_queue()

    def _move_to_front(self, file_path: str):
        """Move file_path to the top of the queue, or right after the
        currently encoding file when encoding is active."""
        it = self._find_row(file_path)
        if not it:
            return
        if self._encoding_active and 0 <= self._current_index < len(self._jobs):
            current_path = self._jobs[self._current_index].input_path
            if current_path == file_path:
                return  # can't displace the file being encoded right now
            current_it = self._find_row(current_path)
            self._store.move_after(it, current_it)
        else:
            self._store.move_after(it, None)  # None → move to the very beginning
        self._sync_queue_from_store()
        self._save_queue()

        # Also reorder/insert into _jobs so _encode_next uses the right order.
        if self._encoding_active:
            insert_at = self._current_index + 1
            job_idx = next(
                (i for i, j in enumerate(self._jobs) if j.input_path == file_path),
                None,
            )
            if job_idx is None:
                # File was added after encoding started — build a fresh job.
                self._jobs.insert(insert_at, self._build_job(file_path))
            elif job_idx != insert_at:
                job = self._jobs.pop(job_idx)
                self._jobs.insert(insert_at, job)

    def _set_stop_after(self, path: Optional[str]):
        """Set (or clear) the stop-after marker. Pass None to clear."""
        # Clear old marker
        if self._stop_after_path:
            it = self._find_row(self._stop_after_path)
            if it:
                self._store.set_value(it, COL_STOP_MARKER, "")
        self._stop_after_path = path
        # Set new marker
        if path:
            it = self._find_row(path)
            if it:
                self._store.set_value(it, COL_STOP_MARKER, "⏹")

    def _find_row(self, path: str):
        it = self._store.get_iter_first()
        while it:
            if self._store.get_value(it, COL_FULLPATH) == path:
                return it
            it = self._store.iter_next(it)
        return None

    # ------------------------------------------------------------------
    # Stream selection helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _stream_summary(streams: list[dict]) -> str:
        if not streams:
            return "–"
        total   = len(streams)
        enabled = sum(1 for s in streams if s["enabled"])
        if enabled == 0:
            return i18n.t("stream_none").format(total=total)
        if enabled == total:
            return i18n.t("stream_all").format(total=total)
        return i18n.t("stream_active").format(enabled=enabled, total=total)

    @staticmethod
    def _stream_label(stream: dict, stype: str) -> str:
        lang  = stream.get("language", "")
        title = stream.get("title", "")
        codec = stream.get("codec", "?")
        name  = title or lang or i18n.t("stream_unknown")
        idx   = stream["rel_idx"] + 1
        if stype == "audio":
            ch = stream.get("channels", 0)
            layout = stream.get("channel_layout", "")
            ch_str = layout if layout else (f"{ch}ch" if ch else "")
            return i18n.t("stream_track_audio").format(
                idx=idx, name=name, codec=codec, ch_str=ch_str)
        else:
            return i18n.t("stream_track_sub").format(
                idx=idx, name=name, codec=codec)

    def _update_stream_summary(self, file_path: str, tree_path):
        """Recalculate and write summary strings back to the ListStore."""
        it = self._store.get_iter(tree_path)
        if not it:
            return
        audio, subs = self._file_streams.get(file_path, ([], []))
        self._store.set_value(it, COL_AUDIO_LABEL, self._stream_summary(audio))
        self._store.set_value(it, COL_SUB_LABEL,   self._stream_summary(subs))

    # ------------------------------------------------------------------
    # Preview
    # ------------------------------------------------------------------

    def _on_selection_changed(self, selection):
        model, paths = selection.get_selected_rows()
        if len(paths) == 1:
            it = model.get_iter(paths[0])
            path = model.get_value(it, COL_FULLPATH)
            self._show_preview(path)
        else:
            self._clear_preview()

    def _show_preview(self, path: str):
        if self._preview_path == path:
            return
        self._preview_path = path
        self._preview_label.show()
        self._preview_image.hide()
        self._preview_label.set_markup(i18n.t("lbl_loading_preview"))

        def _load():
            pixbuf = self._extract_thumbnail(path, max_w=580, max_h=220)
            def _apply():
                if self._preview_path != path:
                    return False   # selection changed while loading
                if pixbuf:
                    self._preview_image.set_from_pixbuf(pixbuf)
                    self._preview_image.show()
                    self._preview_label.hide()
                else:
                    self._preview_label.set_markup(i18n.t("lbl_preview_unavail"))
                return False
            GLib.idle_add(_apply)

        threading.Thread(target=_load, daemon=True).start()

    def _clear_preview(self):
        self._preview_path = None
        self._preview_image.hide()
        self._preview_label.show()
        self._preview_label.set_markup(i18n.t("lbl_no_video"))

    @staticmethod
    def _extract_thumbnail(path: str, max_w: int = 580, max_h: int = 220):
        """Return a GdkPixbuf thumbnail or None on failure."""
        try:
            result = subprocess.run(
                ["ffmpeg", "-ss", "00:00:05", "-i", path,
                 "-vframes", "1",
                 "-vf", f"scale={max_w}:{max_h}:force_original_aspect_ratio=decrease",
                 "-f", "image2pipe", "-vcodec", "png", "pipe:1"],
                capture_output=True, timeout=15,
            )
            if result.returncode == 0 and result.stdout:
                loader = GdkPixbuf.PixbufLoader.new_with_type("png")
                loader.write(result.stdout)
                loader.close()
                return loader.get_pixbuf()
        except Exception:
            pass
        return None

    # ------------------------------------------------------------------
    # Play / Context menu
    # ------------------------------------------------------------------

    def _on_row_activated(self, treeview, tree_path, column):
        """Double-click: open file with default video player."""
        it = self._store.get_iter(tree_path)
        path = self._store.get_value(it, COL_FULLPATH)
        self._play_file(path)

    @staticmethod
    def _play_file(path: str):
        try:
            subprocess.Popen(["xdg-open", path],
                             stdout=subprocess.DEVNULL,
                             stderr=subprocess.DEVNULL)
        except Exception:
            pass

    @staticmethod
    def _show_in_folder(path: str):
        """Open the parent folder in the default file manager with the file selected."""
        import urllib.parse
        uri = "file://" + urllib.parse.quote(path)
        try:
            # org.freedesktop.FileManager1 is supported by Nautilus, Dolphin,
            # Thunar, Nemo and others — selects the file in the open window.
            subprocess.Popen(
                [
                    "dbus-send", "--session",
                    "--dest=org.freedesktop.FileManager1",
                    "--type=method_call",
                    "/org/freedesktop/FileManager1",
                    "org.freedesktop.FileManager1.ShowItems",
                    f"array:string:{uri}",
                    "string:",
                ],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except Exception:
            # Fallback: just open the directory
            try:
                subprocess.Popen(["xdg-open", os.path.dirname(path)],
                                 stdout=subprocess.DEVNULL,
                                 stderr=subprocess.DEVNULL)
            except Exception:
                pass

    def _on_treeview_button_press(self, widget, event):
        """Right-click → context menu."""
        if event.button != 3:
            return False
        result = widget.get_path_at_pos(int(event.x), int(event.y))
        if result is None:
            return False
        tree_path, _col, _cx, _cy = result
        # Ensure the right-clicked row is selected
        sel = widget.get_selection()
        if not sel.path_is_selected(tree_path):
            sel.unselect_all()
            sel.select_path(tree_path)
        it = self._store.get_iter(tree_path)
        file_path = self._store.get_value(it, COL_FULLPATH)
        self._show_context_menu(widget, event, tree_path, file_path)
        return True

    def _show_context_menu(self, treeview, event, tree_path, file_path: str):
        menu = Gtk.Menu()
        menu.attach_to_widget(treeview, None)
        fs = self._file_settings.get(file_path, {})

        row_iter = self._find_row(file_path)
        status = (self._store.get_value(row_iter, COL_STATUS)
                  if row_iter else STATUS_PENDING)
        is_done = status in (STATUS_DONE, STATUS_CANCELLED) or status.startswith(STATUS_ERROR)

        # ---- Play / Show in folder --------------------------------------
        item_play = Gtk.MenuItem(label=i18n.t("ctx_play"))
        item_play.connect("activate", lambda _: self._play_file(file_path))
        menu.append(item_play)

        item_folder = Gtk.MenuItem(label=i18n.t("ctx_show_folder"))
        item_folder.connect("activate", lambda _: self._show_in_folder(file_path))
        menu.append(item_folder)

        menu.append(Gtk.SeparatorMenuItem())

        # ---- Audio tracks -----------------------------------------------
        audio, subs = self._file_streams.get(file_path, ([], []))

        audio_item = Gtk.MenuItem(label=i18n.t("ctx_audio_tracks"))
        if audio and not is_done:
            audio_sub = Gtk.Menu()
            for stream in audio:
                label = self._stream_label(stream, "audio")
                chk = Gtk.CheckMenuItem(label=label)
                chk.set_active(stream["enabled"])
                chk.connect("toggled",
                            lambda btn, s=stream, fp=file_path, tp=tree_path:
                            self._on_stream_toggle(btn, s, fp, tp))
                audio_sub.append(chk)
            audio_item.set_submenu(audio_sub)
        else:
            audio_item.set_sensitive(False)
        menu.append(audio_item)

        # ---- Subtitle tracks --------------------------------------------
        sub_item = Gtk.MenuItem(label=i18n.t("ctx_subtitles"))
        if subs and not is_done:
            sub_menu = Gtk.Menu()
            for stream in subs:
                label = self._stream_label(stream, "subtitle")
                chk = Gtk.CheckMenuItem(label=label)
                chk.set_active(stream["enabled"])
                chk.connect("toggled",
                            lambda btn, s=stream, fp=file_path, tp=tree_path:
                            self._on_stream_toggle(btn, s, fp, tp))
                sub_menu.append(chk)
            sub_item.set_submenu(sub_menu)
        else:
            sub_item.set_sensitive(False)
        menu.append(sub_item)

        menu.append(Gtk.SeparatorMenuItem())

        # ---- Rotation ---------------------------------------------------
        rot_item = self._make_radio_submenu(
            title=i18n.t("ctx_rotation"),
            options=[(i18n.t("ctx_rot_none"),  0),
                     (i18n.t("ctx_rot_cw"),   90),
                     (i18n.t("ctx_rot_ccw"), -90)],
            current=fs.get("rotation", 0),
            global_label=None,
            on_select=lambda v, fp=file_path:
                self._file_override_set(fp, "rotation", v),
        )
        rot_item.set_sensitive(not is_done)
        menu.append(rot_item)

        menu.append(Gtk.SeparatorMenuItem())

        # ---- Per-file encoding settings ---------------------------------
        for item in [
            self._make_radio_submenu(
                title=i18n.t("ctx_vid_bitrate"),
                options=VIDEO_BITRATES,
                current=fs.get("video_bitrate", "GLOBAL"),
                global_label=i18n.t("ctx_global"),
                on_select=lambda v, fp=file_path:
                    self._file_override_set(fp, "video_bitrate", v),
            ),
            self._make_radio_submenu(
                title=i18n.t("ctx_aud_bitrate"),
                options=AUDIO_BITRATES,
                current=fs.get("audio_bitrate", "GLOBAL") if "audio_bitrate" in fs else "GLOBAL",
                global_label=i18n.t("ctx_global"),
                on_select=lambda v, fp=file_path:
                    self._file_override_set(fp, "audio_bitrate", v),
            ),
            self._make_radio_submenu(
                title=i18n.t("ctx_resolution"),
                options=RESOLUTIONS,
                current=fs.get("resolution_height", "GLOBAL") if "resolution_height" in fs else "GLOBAL",
                global_label=i18n.t("ctx_global"),
                on_select=lambda v, fp=file_path:
                    self._file_override_set(fp, "resolution_height", v),
            ),
            self._make_radio_submenu(
                title=i18n.t("ctx_fps"),
                options=[(i18n.t("ctx_fps_keep"), None), (i18n.t("ctx_fps_limit30"), 30)],
                current=fs.get("fps_limit", "GLOBAL") if "fps_limit" in fs else "GLOBAL",
                global_label=i18n.t("ctx_global"),
                on_select=lambda v, fp=file_path:
                    self._file_override_set(fp, "fps_limit", v),
            ),
        ]:
            item.set_sensitive(not is_done)
            menu.append(item)

        menu.append(Gtk.SeparatorMenuItem())

        # ---- Stop after this file ---------------------------------------
        is_stop = self._stop_after_path == file_path
        stop_label = i18n.t("ctx_stop_after_set") if is_stop else i18n.t("ctx_stop_after")
        item_stop = Gtk.MenuItem(label=stop_label)
        item_stop.set_sensitive(not is_done)
        item_stop.connect(
            "activate",
            lambda _, fp=file_path: self._set_stop_after(None if self._stop_after_path == fp else fp),
        )
        menu.append(item_stop)

        menu.append(Gtk.SeparatorMenuItem())

        # ---- Move to front ----------------------------------------------
        is_encoding_this = (self._encoding_active
                            and 0 <= self._current_index < len(self._jobs)
                            and self._jobs[self._current_index].input_path == file_path)
        if self._encoding_active and not is_encoding_this:
            move_label = i18n.t("ctx_encode_next")
        else:
            move_label = i18n.t("ctx_move_front")
        item_move = Gtk.MenuItem(label=move_label)
        item_move.set_sensitive(not is_done and not is_encoding_this)
        item_move.connect("activate", lambda _, fp=file_path: self._move_to_front(fp))
        menu.append(item_move)

        menu.append(Gtk.SeparatorMenuItem())

        # ---- Remove from list -------------------------------------------
        item_remove = Gtk.MenuItem(label=i18n.t("ctx_remove"))
        item_remove.connect("activate", lambda _, fp=file_path:
                            self._remove_file(fp))
        menu.append(item_remove)

        menu.show_all()
        menu.popup_at_pointer(event)

    def _make_radio_submenu(self, title: str, options: list, current,
                            global_label: Optional[str],
                            on_select) -> Gtk.MenuItem:
        """Build a MenuItem with a radio submenu.

        options  – list of (label, value) tuples
        current  – currently selected value, or "GLOBAL" sentinel
        global_label – if not None, prepend a "Global verwenden" radio item
        on_select(value) – called with the chosen value (or "GLOBAL")
        """
        parent = Gtk.MenuItem(label=title)
        sub = Gtk.Menu()
        buttons: list[tuple[Gtk.RadioMenuItem, object]] = []

        first = None
        if global_label is not None:
            r = Gtk.RadioMenuItem(label=global_label)
            first = r
            sub.append(r)
            buttons.append((r, "GLOBAL"))

        for lbl, val in options:
            if first is None:
                r = Gtk.RadioMenuItem(label=lbl)
                first = r
            else:
                r = Gtk.RadioMenuItem.new_with_label_from_widget(first, lbl)
            sub.append(r)
            buttons.append((r, val))

        # Set active state before connecting signals to avoid spurious calls
        activated = False
        for btn, val in buttons:
            if current == "GLOBAL" and val == "GLOBAL":
                btn.set_active(True)
                activated = True
                break
            if current != "GLOBAL" and val == current:
                btn.set_active(True)
                activated = True
                break
        if not activated and buttons:
            buttons[0][0].set_active(True)

        def _connect(btn, val):
            def _on_toggle(b):
                if b.get_active():
                    on_select(val)
                    self._save_queue()
            btn.connect("toggled", _on_toggle)

        for btn, val in buttons:
            _connect(btn, val)

        parent.set_submenu(sub)
        return parent

    def _file_override_set(self, path: str, key: str, value):
        """Set or clear a per-file setting override and persist the queue."""
        if value == "GLOBAL":
            if path in self._file_settings:
                self._file_settings[path].pop(key, None)
                if not self._file_settings[path]:
                    del self._file_settings[path]
        else:
            self._file_settings.setdefault(path, {})[key] = value

    def _remove_file(self, path: str):
        """Remove a single file from the queue and the list store."""
        if self._stop_after_path == path:
            self._stop_after_path = None   # row is gone, no need to clear the cell
        it = self._find_row(path)
        if it:
            self._store.remove(it)
        if path in self._queue:
            self._queue.remove(path)
        self._file_streams.pop(path, None)
        self._file_metadata.pop(path, None)
        self._file_settings.pop(path, None)
        self._completed.discard(path)
        if self._preview_path == path:
            self._clear_preview()
        self._save_queue()

    def _on_stream_toggle(self, btn, stream: dict, file_path: str, tree_path):
        stream["enabled"] = btn.get_active()
        it = self._store.get_iter(tree_path)
        if it:
            audio, subs = self._file_streams.get(file_path, ([], []))
            self._store.set_value(it, COL_AUDIO_LABEL, self._stream_summary(audio))
            self._store.set_value(it, COL_SUB_LABEL,   self._stream_summary(subs))

    def _show_error(self, message: str):
        dlg = Gtk.MessageDialog(
            transient_for=self,
            modal=True,
            message_type=Gtk.MessageType.ERROR,
            buttons=Gtk.ButtonsType.OK,
            text=message,
        )
        dlg.run()
        dlg.destroy()

    def _show_error_detail(self, filename: str, full_msg: str):
        """Show a dialog with the complete ffmpeg error output."""
        dlg = Gtk.Dialog(
            title=i18n.t("err_dialog_title").format(filename=filename),
            transient_for=self,
            modal=True,
        )
        dlg.set_default_size(640, 380)
        dlg.add_button(i18n.t("err_dialog_close"), Gtk.ResponseType.CLOSE)

        area = dlg.get_content_area()
        area.set_border_width(12)
        area.set_spacing(8)

        lbl = Gtk.Label()
        lbl.set_markup(i18n.t("err_ffmpeg_output"))
        lbl.set_halign(Gtk.Align.START)
        area.pack_start(lbl, False, False, 0)

        tv = Gtk.TextView()
        tv.set_editable(False)
        tv.set_monospace(True)
        tv.set_wrap_mode(Gtk.WrapMode.WORD_CHAR)
        tv.get_buffer().set_text(full_msg)

        sw = Gtk.ScrolledWindow()
        sw.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        sw.add(tv)
        area.pack_start(sw, True, True, 0)

        # Scroll to the bottom so the last (most relevant) lines are visible.
        def _scroll_end(_):
            adj = sw.get_vadjustment()
            adj.set_value(adj.get_upper() - adj.get_page_size())
        dlg.connect("show", _scroll_end)

        dlg.show_all()
        dlg.run()
        dlg.destroy()


# ---------------------------------------------------------------------------
# Scan Dialog
# ---------------------------------------------------------------------------

class ScanDialog(Gtk.Window):
    """Stand-alone window that scans a folder tree and collects videos by bitrate."""

    # Custom signal to hand selected paths back to the main window.
    __gsignals__ = {
        "files-selected": (
            GObject.SignalFlags.RUN_FIRST, None, (object,)
        ),
    }

    # Result-store column indices
    _C_CHECK  = 0
    _C_NAME   = 1
    _C_DIR    = 2
    _C_KBPS   = 3
    _C_PATH   = 4

    def __init__(self, parent: Gtk.Window):
        super().__init__(title=i18n.t("scan_win_title"))
        self.set_transient_for(parent)
        self.set_destroy_with_parent(True)
        self.set_default_size(740, 560)
        self.set_border_width(0)

        self._cancel_flag = threading.Event()
        self._scanning    = False

        self._build_ui()

    # ------------------------------------------------------------------
    # UI
    # ------------------------------------------------------------------

    def _build_ui(self):
        root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        self.add(root)

        # ---- Settings bar ---------------------------------------------
        bar = Gtk.Box(spacing=8)
        bar.set_border_width(10)
        root.pack_start(bar, False, False, 0)

        bar.pack_start(Gtk.Label(label=i18n.t("scan_lbl_folder")), False, False, 0)
        self._entry_folder = Gtk.Entry()
        self._entry_folder.set_placeholder_text(i18n.t("scan_entry_ph"))
        self._entry_folder.set_hexpand(True)
        bar.pack_start(self._entry_folder, True, True, 0)

        btn_browse = Gtk.Button(label=i18n.t("scan_btn_browse"))
        btn_browse.connect("clicked", self._on_browse)
        bar.pack_start(btn_browse, False, False, 0)

        bar2 = Gtk.Box(spacing=8)
        bar2.set_border_width(10)
        bar2.set_margin_top(0)
        root.pack_start(bar2, False, False, 0)

        bar2.pack_start(Gtk.Label(label=i18n.t("scan_lbl_threshold")), False, False, 0)
        adj = Gtk.Adjustment(value=7000, lower=100, upper=200000,
                             step_increment=500, page_increment=5000)
        self._spin = Gtk.SpinButton(adjustment=adj, climb_rate=500, digits=0)
        self._spin.set_width_chars(8)
        bar2.pack_start(self._spin, False, False, 0)
        bar2.pack_start(Gtk.Label(label=i18n.t("scan_lbl_unit")), False, False, 0)
        hint = Gtk.Label(label=i18n.t("scan_lbl_hint"))
        hint.set_sensitive(False)
        bar2.pack_start(hint, False, False, 0)

        # Scan / Stop buttons
        btn_box = Gtk.Box(spacing=6)
        btn_box.set_border_width(10)
        btn_box.set_margin_top(0)
        root.pack_start(btn_box, False, False, 0)

        self._btn_scan = Gtk.Button(label=i18n.t("scan_btn_start"))
        self._btn_scan.get_style_context().add_class("suggested-action")
        self._btn_scan.connect("clicked", self._on_scan)
        btn_box.pack_start(self._btn_scan, False, False, 0)

        self._btn_stop = Gtk.Button(label=i18n.t("scan_btn_stop"))
        self._btn_stop.set_sensitive(False)
        self._btn_stop.connect("clicked", self._on_stop)
        btn_box.pack_start(self._btn_stop, False, False, 0)

        # ---- Progress -------------------------------------------------
        prog_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        prog_box.set_border_width(10)
        prog_box.set_margin_top(0)
        root.pack_start(prog_box, False, False, 0)

        self._prog_label = Gtk.Label(label=" ")
        self._prog_label.set_halign(Gtk.Align.START)
        prog_box.pack_start(self._prog_label, False, False, 0)

        self._prog_bar = Gtk.ProgressBar()
        prog_box.pack_start(self._prog_bar, False, False, 0)

        # ---- Results list ---------------------------------------------
        # store: selected(bool), filename, directory, bitrate_kbps, full_path
        self._store = Gtk.ListStore(bool, str, str, int, str)

        tv = Gtk.TreeView(model=self._store)
        tv.set_headers_clickable(True)

        # Checkbox column
        chk_cell = Gtk.CellRendererToggle()
        chk_cell.connect("toggled", self._on_row_toggled)
        chk_col = Gtk.TreeViewColumn("", chk_cell, active=self._C_CHECK)
        chk_col.set_fixed_width(32)
        tv.append_column(chk_col)

        # Filename
        name_cell = Gtk.CellRendererText()
        name_cell.set_property("ellipsize", Pango.EllipsizeMode.MIDDLE)
        name_col = Gtk.TreeViewColumn(i18n.t("scan_col_filename"), name_cell, text=self._C_NAME)
        name_col.set_expand(True)
        name_col.set_resizable(True)
        tv.append_column(name_col)

        # Directory
        dir_cell = Gtk.CellRendererText()
        dir_cell.set_property("ellipsize", Pango.EllipsizeMode.START)
        dir_col = Gtk.TreeViewColumn(i18n.t("scan_col_directory"), dir_cell, text=self._C_DIR)
        dir_col.set_min_width(140)
        dir_col.set_resizable(True)
        tv.append_column(dir_col)

        # Bitrate (rendered as formatted string)
        br_cell = Gtk.CellRendererText()
        br_cell.set_property("xalign", 1.0)
        br_col = Gtk.TreeViewColumn(i18n.t("scan_col_bitrate"), br_cell)
        br_col.set_cell_data_func(br_cell, self._render_bitrate)
        br_col.set_min_width(100)
        tv.append_column(br_col)

        sw = Gtk.ScrolledWindow()
        sw.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        sw.add(tv)
        root.pack_start(sw, True, True, 0)

        # ---- Bottom bar -----------------------------------------------
        bot = Gtk.Box(spacing=8)
        bot.set_border_width(10)
        root.pack_start(bot, False, False, 0)

        self._summary = Gtk.Label(label=i18n.t("scan_lbl_no_results"))
        self._summary.set_halign(Gtk.Align.START)
        bot.pack_start(self._summary, True, True, 0)

        btn_all = Gtk.Button(label=i18n.t("scan_btn_all"))
        btn_all.connect("clicked", lambda *_: self._set_all(True))
        bot.pack_start(btn_all, False, False, 0)

        btn_none = Gtk.Button(label=i18n.t("scan_btn_none"))
        btn_none.connect("clicked", lambda *_: self._set_all(False))
        bot.pack_start(btn_none, False, False, 0)

        sep = Gtk.Separator(orientation=Gtk.Orientation.VERTICAL)
        bot.pack_start(sep, False, False, 4)

        self._btn_add = Gtk.Button(label=i18n.t("scan_btn_add_queue"))
        self._btn_add.get_style_context().add_class("suggested-action")
        self._btn_add.set_sensitive(False)
        self._btn_add.connect("clicked", self._on_add_to_queue)
        bot.pack_start(self._btn_add, False, False, 0)

        btn_close = Gtk.Button(label=i18n.t("scan_btn_close"))
        btn_close.connect("clicked", lambda *_: self.destroy())
        bot.pack_start(btn_close, False, False, 0)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _render_bitrate(_col, cell, model, it, _):
        kbps = model.get_value(it, ScanDialog._C_KBPS)
        if kbps >= 10000:
            cell.set_property("text", f"{kbps / 1000:.1f} Mbps")
        else:
            cell.set_property("text", f"{kbps:,} kbps".replace(",", "\u202f"))

    def _set_all(self, state: bool):
        it = self._store.get_iter_first()
        while it:
            self._store.set_value(it, self._C_CHECK, state)
            it = self._store.iter_next(it)
        self._refresh_summary()

    def _refresh_summary(self):
        total    = len(self._store)
        selected = sum(1 for row in self._store if row[self._C_CHECK])
        s = "s" if total != 1 else ""
        self._summary.set_text(
            i18n.t("scan_summary").format(total=total, s=s, selected=selected)
        )
        self._btn_add.set_sensitive(selected > 0)

    # ------------------------------------------------------------------
    # Signal handlers
    # ------------------------------------------------------------------

    def _on_browse(self, *_):
        dlg = Gtk.FileChooserDialog(
            title=i18n.t("scan_entry_ph"),
            parent=self,
            action=Gtk.FileChooserAction.SELECT_FOLDER,
        )
        dlg.add_buttons(Gtk.STOCK_CANCEL, Gtk.ResponseType.CANCEL,
                        Gtk.STOCK_OPEN,   Gtk.ResponseType.OK)
        if dlg.run() == Gtk.ResponseType.OK:
            self._entry_folder.set_text(dlg.get_filename())
        dlg.destroy()

    def _on_row_toggled(self, _cell, path_str):
        it = self._store.get_iter(path_str)
        self._store.set_value(it, self._C_CHECK,
                              not self._store.get_value(it, self._C_CHECK))
        self._refresh_summary()

    def _on_stop(self, *_):
        self._cancel_flag.set()
        self._btn_stop.set_sensitive(False)

    def _on_scan(self, *_):
        folder = self._entry_folder.get_text().strip()
        if not folder:
            return
        if not os.path.isdir(folder):
            dlg = Gtk.MessageDialog(transient_for=self, modal=True,
                                    message_type=Gtk.MessageType.ERROR,
                                    buttons=Gtk.ButtonsType.OK,
                                    text=i18n.t("scan_folder_missing").format(folder=folder))
            dlg.run(); dlg.destroy()
            return

        self._store.clear()
        self._cancel_flag.clear()
        self._scanning = True
        self._btn_scan.set_sensitive(False)
        self._btn_stop.set_sensitive(True)
        self._btn_add.set_sensitive(False)
        self._prog_bar.set_fraction(0)
        self._summary.set_text(i18n.t("scan_scanning"))

        threshold = int(self._spin.get_value())

        def _on_progress(checked, total, found, current):
            GLib.idle_add(self._update_progress, checked, total, found, current)

        def _on_found(path, kbps):
            GLib.idle_add(self._add_result, path, kbps)

        def _run():
            scan_folder(
                folder=folder,
                threshold_kbps=threshold,
                on_progress=_on_progress,
                on_found=_on_found,
                is_cancelled=self._cancel_flag.is_set,
            )
            GLib.idle_add(self._scan_finished)

        threading.Thread(target=_run, daemon=True).start()

    def _on_add_to_queue(self, *_):
        paths = [row[self._C_PATH] for row in self._store if row[self._C_CHECK]]
        if paths:
            self.emit("files-selected", paths)
            n = len(paths)
            s = "en" if n != 1 else ""
            self._summary.set_text(i18n.t("scan_n_added").format(n=n, s=s))
            self._btn_add.set_sensitive(False)

    # ------------------------------------------------------------------
    # Background-thread callbacks (always called via GLib.idle_add)
    # ------------------------------------------------------------------

    def _update_progress(self, checked, total, found, current):
        if total > 0:
            self._prog_bar.set_fraction(checked / total)
            label = (
                i18n.t("scan_progress_tpl").format(
                    checked=checked, total=total, found=found
                )
                + (f"  ·  {current}" if current else "")
            )
        else:
            label = i18n.t("scan_no_videos")
        self._prog_label.set_text(label)
        return False

    def _add_result(self, path, kbps):
        self._store.append([
            True,
            os.path.basename(path),
            os.path.dirname(path),
            kbps,
            path,
        ])
        self._refresh_summary()
        return False

    def _scan_finished(self):
        self._scanning = False
        self._btn_scan.set_sensitive(True)
        self._btn_stop.set_sensitive(False)
        self._prog_bar.set_fraction(1.0)
        total = len(self._store)
        if total == 0:
            self._prog_label.set_text(i18n.t("scan_done_none"))
            self._summary.set_text(i18n.t("scan_lbl_no_results"))
        else:
            self._prog_label.set_text(i18n.t("scan_done"))
        return False


# ---------------------------------------------------------------------------
# Entry Point
# ---------------------------------------------------------------------------

def main():
    win = MainWindow()
    win.show_all()
    Gtk.main()


if __name__ == "__main__":
    main()
