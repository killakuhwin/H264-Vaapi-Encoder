"""Minimal i18n module for H264 VAAPI Encoder.

Usage:
    import i18n
    i18n.set_lang("en")   # or "de"
    label = i18n.t("btn_add_files")
"""

_lang: str = "en"


def set_lang(lang: str) -> None:
    global _lang
    _lang = lang


def t(key: str) -> str:
    """Return translated string for *key* in the current language."""
    return TRANSLATIONS[_lang].get(key, TRANSLATIONS["en"].get(key, key))


TRANSLATIONS: dict[str, dict[str, str]] = {
    # ------------------------------------------------------------------
    # English
    # ------------------------------------------------------------------
    "en": {
        # Toolbar buttons
        "btn_add_files":       "Add Files",
        "btn_scan_folder":     "Scan Folder",
        "btn_remove":          "Remove",
        "btn_encode_start":    "Start Encoding",
        "btn_cancel":          "Cancel",

        # Toolbar tooltips
        "tip_add_files":       "Add video files to the queue",
        "tip_scan_folder":     "Scan a folder for videos above a bitrate threshold",
        "tip_remove":          "Remove selected files from the list",
        "tip_encode_start":    "Start encoding all pending files",
        "tip_cancel":          "Cancel the current encoding",
        "tip_lang":            "Change interface language",

        # File list frame
        "frame_input_files":   "Input Files",

        # TreeView column headers
        "col_filename":        "Filename",
        "col_directory":       "Directory",
        "col_status":          "Status",
        "col_progress":        "Progress",
        "col_resolution":      "Resolution",
        "col_vid_bitrate":     "Video Bitrate",
        "col_aud_bitrate":     "Audio Bitrate",
        "col_fps":             "FPS",
        "col_duration":        "Duration",

        # Settings frames / labels
        "frame_output_path":   "Output Path",
        "chk_src_dir":         "Save in source directory",
        "entry_outdir_ph":     "Choose output directory…",
        "chk_work_dir":        "Use work directory (encode here first, then copy)",
        "entry_work_dir_ph":   "Choose work directory…",
        "frame_output_name":   "Output Name",
        "radio_new_name":      "Use new name",
        "radio_same_name":     "Keep same filename",
        "radio_replace":       "Replace source file (delete original)",
        "affix_suffix":        "Suffix",
        "affix_prefix":        "Prefix",

        "frame_bitrate":       "Bitrate Settings",
        "lbl_vid_bitrate":     "Video Bitrate:",
        "lbl_aud_bitrate":     "Audio Bitrate:",
        "lbl_resolution":      "Resolution:",

        # Resolution note (Pango markup)
        "res_note":            ("<small><i>Non-16:9 sources are automatically\n"
                                "scaled to the original aspect ratio.</i></small>"),

        # FPS checkbox
        "chk_fps_limit":       "Limit HFR videos (>{threshold} fps) to 30 fps",

        # FPS note (Pango markup – {threshold} placeholder)
        "fps_note":            ("<small><i>Without limit: ≥{threshold} fps\n"
                                "→ video bitrate is doubled.</i></small>"),

        # Post-encoding action
        "frame_post_action":   "Action after Encoding",
        "radio_nothing":       "Do nothing",
        "radio_quit":          "Close program",
        "radio_shutdown":      "Shut down computer",

        # Preview panel
        "frame_preview":       "Preview",
        "lbl_no_video":        "<i>No video selected</i>",
        "lbl_loading_preview": "<i>Loading preview…</i>",
        "lbl_preview_unavail": "<i>Preview not available</i>",

        # Status bar
        "status_ready":        "Ready",
        "status_cancelling":   "Cancelling…",
        "status_all_done":     "All tasks completed.",

        # Status column values
        "status_pending":      "Pending",
        "status_encoding":     "Encoding…",
        "status_done":         "Done",
        "status_error":        "Error",
        "status_cancelled":    "Cancelled",

        # Audio / subtitle combo special entry
        "audio_original":      "Original (keep)",
        "res_original":        "Original (keep)",

        # Context menu
        "ctx_play":            "▶  Play",
        "ctx_show_folder":     "📂  Show in Folder",
        "ctx_audio_tracks":    "Audio Tracks",
        "ctx_subtitles":       "Subtitles",
        "ctx_rotation":        "Rotation",
        "ctx_rot_none":        "No Rotation",
        "ctx_rot_cw":          "90° Clockwise",
        "ctx_rot_180":         "180°",
        "ctx_rot_ccw":         "90° Counter-clockwise",
        "ctx_vid_bitrate":     "Video Bitrate",
        "ctx_aud_bitrate":     "Audio Bitrate",
        "ctx_resolution":      "Resolution",
        "ctx_fps":             "FPS",
        "ctx_global":          "Use Global",
        "ctx_fps_keep":        "Keep Original",
        "ctx_fps_limit30":     "Limit to 30 fps",
        "ctx_stop_after":      "⏹  Stop after this file",
        "ctx_stop_after_set":  "⏹  Stop after this file ✓",
        "ctx_encode_next":     "⬆  Encode next",
        "ctx_move_front":      "⬆  Move to front of list",
        "ctx_remove":          "Remove from list",

        # Dynamic status strings (Python format strings)
        "encoding_status":     "Encoding {n}/{total}: {name}{res}{fps}",
        "fps_hfr_note":        ", HFR {fps:.1f} fps → bitrate ×2",

        # File chooser dialogs
        "dlg_add_files_title": "Select Video Files",
        "dlg_filter_videos":   "Video Files",
        "dlg_filter_all":      "All Files",
        "dlg_browse_title":    "Choose Output Directory",

        # Scan added / restored messages
        "scan_added":          "{n} file{s} from scan added to list.",
        "scan_restored":       "{n} file(s) restored from previous session.",

        # Loading placeholder
        "loading":             "Loading…",

        # Error dialogs
        "err_no_files":        "No files in the list.",
        "err_no_outdir":       "Please choose an output directory.",
        "err_dialog_close":    "Close",
        "err_ffmpeg_output":   "<b>ffmpeg output:</b>",
        "err_dialog_title":    "Error – {filename}",

        # Stream summary / track labels
        "stream_none":         "None ({total})",
        "stream_all":          "All ({total})",
        "stream_active":       "{enabled}/{total} active",
        "stream_track_audio":  "Track {idx}: {name}  [{codec}, {ch_str}]",
        "stream_track_sub":    "Track {idx}: {name}  [{codec}]",
        "stream_unknown":      "unknown",

        # Scan dialog
        "scan_win_title":      "Scan Folder for Videos",
        "scan_lbl_folder":     "Folder:",
        "scan_entry_ph":       "Choose folder…",
        "scan_btn_browse":     "Browse…",
        "scan_lbl_threshold":  "Bitrate threshold:",
        "scan_lbl_unit":       "kbps  –  Videos",
        "scan_lbl_hint":       "with higher bitrate will be found",
        "scan_btn_start":      "▶  Start Scan",
        "scan_btn_stop":       "■  Stop",
        "scan_col_filename":   "Filename",
        "scan_col_directory":  "Directory",
        "scan_col_bitrate":    "Bitrate",
        "scan_lbl_no_results": "No results.",
        "scan_btn_all":        "All",
        "scan_btn_none":       "None",
        "scan_btn_add_queue":  "Add to Queue",
        "scan_btn_close":      "Close",
        "scan_progress_tpl":   "Checked: {checked} / {total}  ·  Found: {found}",
        "scan_no_videos":      "No video files found.",
        "scan_done_none":      "Scan complete – no videos above threshold.",
        "scan_done":           "Scan complete.",
        "scan_summary":        "{total} video{s} found  ·  {selected} selected",
        "scan_n_added":        "{n} file{s} added to conversion list.",
        "scan_folder_missing": "Folder not found:\n{folder}",
        "scan_scanning":       "Scanning…",
    },

    # ------------------------------------------------------------------
    # German (original strings)
    # ------------------------------------------------------------------
    "de": {
        # Toolbar buttons
        "btn_add_files":       "Dateien hinzufügen",
        "btn_scan_folder":     "Ordner scannen",
        "btn_remove":          "Entfernen",
        "btn_encode_start":    "Kodieren starten",
        "btn_cancel":          "Abbrechen",

        # Toolbar tooltips
        "tip_add_files":       "Videodateien zur Liste hinzufügen",
        "tip_scan_folder":     "Ordner nach Videos über einem Bitrate-Schwellenwert durchsuchen",
        "tip_remove":          "Ausgewählte Dateien aus der Liste entfernen",
        "tip_encode_start":    "Alle ausstehenden Dateien kodieren",
        "tip_cancel":          "Aktuelle Kodierung abbrechen",
        "tip_lang":            "Sprache der Oberfläche ändern",

        # File list frame
        "frame_input_files":   "Eingabedateien",

        # TreeView column headers
        "col_filename":        "Dateiname",
        "col_directory":       "Verzeichnis",
        "col_status":          "Status",
        "col_progress":        "Fortschritt",
        "col_resolution":      "Auflösung",
        "col_vid_bitrate":     "Video-Bitrate",
        "col_aud_bitrate":     "Audio-Bitrate",
        "col_fps":             "FPS",
        "col_duration":        "Länge",

        # Settings frames / labels
        "frame_output_path":   "Ausgabepfad",
        "chk_src_dir":         "Im Quellverzeichnis speichern",
        "entry_outdir_ph":     "Ausgabeverzeichnis wählen…",
        "chk_work_dir":        "Arbeitsverzeichnis nutzen (erst dort kodieren, dann kopieren)",
        "entry_work_dir_ph":   "Arbeitsverzeichnis wählen…",
        "frame_output_name":   "Ausgabename",
        "radio_new_name":      "Neuen Namen verwenden",
        "radio_same_name":     "Gleichen Dateinamen behalten",
        "radio_replace":       "Quelldatei ersetzen (Original löschen)",
        "affix_suffix":        "Suffix",
        "affix_prefix":        "Präfix",

        "frame_bitrate":       "Bitrate-Einstellungen",
        "lbl_vid_bitrate":     "Video-Bitrate:",
        "lbl_aud_bitrate":     "Audio-Bitrate:",
        "lbl_resolution":      "Auflösung:",

        # Resolution note
        "res_note":            ("<small><i>Nicht-16:9-Quellen werden automatisch\n"
                                "im Originalseitenverhältnis skaliert.</i></small>"),

        # FPS checkbox
        "chk_fps_limit":       "HFR-Videos (>{threshold} fps) auf 30 fps begrenzen",

        # FPS note
        "fps_note":            ("<small><i>Ohne Begrenzung: ≥{threshold} fps\n"
                                "→ Video-Bitrate wird verdoppelt.</i></small>"),

        # Post-encoding action
        "frame_post_action":   "Aktion nach Kodierung",
        "radio_nothing":       "Nichts tun",
        "radio_quit":          "Programm schließen",
        "radio_shutdown":      "Computer herunterfahren",

        # Preview panel
        "frame_preview":       "Vorschau",
        "lbl_no_video":        "<i>Kein Video ausgewählt</i>",
        "lbl_loading_preview": "<i>Lädt Vorschau…</i>",
        "lbl_preview_unavail": "<i>Vorschau nicht verfügbar</i>",

        # Status bar
        "status_ready":        "Bereit",
        "status_cancelling":   "Wird abgebrochen…",
        "status_all_done":     "Alle Aufgaben abgeschlossen.",

        # Status column values
        "status_pending":      "Ausstehend",
        "status_encoding":     "Wird kodiert…",
        "status_done":         "Fertig",
        "status_error":        "Fehler",
        "status_cancelled":    "Abgebrochen",

        # Audio / subtitle combo special entry
        "audio_original":      "Original (beibehalten)",
        "res_original":        "Original (beibehalten)",

        # Context menu
        "ctx_play":            "▶  Abspielen",
        "ctx_show_folder":     "📂  Im Ordner ansehen",
        "ctx_audio_tracks":    "Audiospuren",
        "ctx_subtitles":       "Untertitel",
        "ctx_rotation":        "Drehung",
        "ctx_rot_none":        "Keine Drehung",
        "ctx_rot_cw":          "90° im Uhrzeigersinn",
        "ctx_rot_180":         "180°",
        "ctx_rot_ccw":         "90° gegen Uhrzeigersinn",
        "ctx_vid_bitrate":     "Video-Bitrate",
        "ctx_aud_bitrate":     "Audio-Bitrate",
        "ctx_resolution":      "Auflösung",
        "ctx_fps":             "FPS",
        "ctx_global":          "Global verwenden",
        "ctx_fps_keep":        "Original behalten",
        "ctx_fps_limit30":     "Auf 30 fps begrenzen",
        "ctx_stop_after":      "⏹  Nach dieser Datei stoppen",
        "ctx_stop_after_set":  "⏹  Nach dieser Datei stoppen ✓",
        "ctx_encode_next":     "⬆  Als nächstes kodieren",
        "ctx_move_front":      "⬆  An den Anfang der Liste",
        "ctx_remove":          "Aus Liste entfernen",

        # Dynamic status strings
        "encoding_status":     "Kodiere {n}/{total}: {name}{res}{fps}",
        "fps_hfr_note":        ", HFR {fps:.1f} fps → Bitrate x2",

        # File chooser dialogs
        "dlg_add_files_title": "Videodateien auswählen",
        "dlg_filter_videos":   "Videodateien",
        "dlg_filter_all":      "Alle Dateien",
        "dlg_browse_title":    "Ausgabeverzeichnis wählen",

        # Scan added / restored messages
        "scan_added":          "{n} Datei{s} aus Scan zur Liste hinzugefügt.",
        "scan_restored":       "{n} Datei(en) aus vorheriger Sitzung wiederhergestellt.",

        # Loading placeholder
        "loading":             "Lädt…",

        # Error dialogs
        "err_no_files":        "Keine Dateien in der Liste.",
        "err_no_outdir":       "Bitte ein Ausgabeverzeichnis auswählen.",
        "err_dialog_close":    "Schließen",
        "err_ffmpeg_output":   "<b>ffmpeg-Ausgabe:</b>",
        "err_dialog_title":    "Fehler – {filename}",

        # Stream summary / track labels
        "stream_none":         "Keine ({total})",
        "stream_all":          "Alle ({total})",
        "stream_active":       "{enabled}/{total} aktiv",
        "stream_track_audio":  "Spur {idx}: {name}  [{codec}, {ch_str}]",
        "stream_track_sub":    "Spur {idx}: {name}  [{codec}]",
        "stream_unknown":      "unbekannt",

        # Scan dialog
        "scan_win_title":      "Ordner nach Videos scannen",
        "scan_lbl_folder":     "Ordner:",
        "scan_entry_ph":       "Ordner auswählen…",
        "scan_btn_browse":     "Durchsuchen…",
        "scan_lbl_threshold":  "Bitrate-Schwelle:",
        "scan_lbl_unit":       "kbps  –  Videos",
        "scan_lbl_hint":       "mit höherer Bitrate werden gefunden",
        "scan_btn_start":      "▶  Scannen starten",
        "scan_btn_stop":       "■  Stopp",
        "scan_col_filename":   "Dateiname",
        "scan_col_directory":  "Verzeichnis",
        "scan_col_bitrate":    "Bitrate",
        "scan_lbl_no_results": "Keine Ergebnisse.",
        "scan_btn_all":        "Alle",
        "scan_btn_none":       "Keine",
        "scan_btn_add_queue":  "In Queue übernehmen",
        "scan_btn_close":      "Schließen",
        "scan_progress_tpl":   "Geprüft: {checked} / {total}  ·  Gefunden: {found}",
        "scan_no_videos":      "Keine Videodateien gefunden.",
        "scan_done_none":      "Scan abgeschlossen – keine Videos über dem Schwellenwert.",
        "scan_done":           "Scan abgeschlossen.",
        "scan_summary":        "{total} Video{s} gefunden  ·  {selected} ausgewählt",
        "scan_n_added":        "{n} Datei{s} zur Konvertierungsliste hinzugefügt.",
        "scan_folder_missing": "Ordner nicht gefunden:\n{folder}",
        "scan_scanning":       "Scanne…",
    },
}
