# H264 VAAPI Encoder

A Linux desktop GUI for batch H.264 video encoding using Intel/AMD hardware acceleration (VAAPI). Built with Python and GTK3.

![Platform](https://img.shields.io/badge/platform-Linux-blue) ![Python](https://img.shields.io/badge/python-3.10%2B-blue) ![License](https://img.shields.io/badge/license-MIT-green)

---

## What it does

H264 VAAPI Encoder is specialised for **normalising large video archives to a consistent quality level**. Its folder scanner finds every video file that exceeds a configurable bitrate threshold — regardless of codec, container, or origin — and adds them to an encoding queue. This lets you process an entire archive in one run, touching only the files that actually need re-encoding, without manually inspecting every file.

Hardware encoding via VAAPI keeps CPU usage low and encoding speed high, making it practical to work through hundreds of files without dedicated hardware or long wait times.

---

## Features

### Folder scanner
- Recursively scans any folder for video files whose bitrate exceeds a user-defined threshold (kbps)
- Files at or below the threshold are skipped automatically — only oversized files enter the queue
- High frame rate videos (>40 fps) are compared against double the threshold, since they will be encoded at double bitrate
- Designed to bring a mixed-bitrate archive down to a single consistent quality level in one batch

### Hardware-accelerated encoding
- Encodes to H.264 using VAAPI (`h264_vaapi`) — offloads work to the GPU
- Automatically detects the DRI render node (`/dev/dri/renderD*`)
- SW-decode pipeline with CPU-side filters (scale, rotate, fps) + `hwupload` for cases where frame manipulation is needed
- Full HW-decode pipeline when no filters are required (faster)
- HFR videos (≥40 fps) are automatically encoded at double the configured bitrate to maintain quality

### Encoding queue
- Add individual files or entire folders via drag-and-drop or the file/folder dialog
- Files added while encoding is already running are picked up automatically
- Queue is saved to disk on every change — resumable after a crash or restart
- Metadata (resolution, bitrate, fps, duration, streams) is cached per file and restored on next launch

### Per-file settings
Each file in the queue can override the global defaults individually:
- **Video bitrate** — from 500 kbps to 20 000 kbps
- **Audio bitrate** — or stream-copy when the source is already at or below the target
- **Output resolution** — downscale to 480p / 720p / 1080p / 2160p; source resolution is never upscaled
- **FPS limit** — optionally cap HFR content at 30 fps
- **Rotation** — 90° clockwise / counter-clockwise
- **Audio track selection** — include or exclude individual audio streams
- **Subtitle track selection** — pass through specific subtitle streams

### Output options
- Write output files to a custom directory, or next to the source file
- Keep the original filename or add a custom suffix
- Replace the original file in-place after successful encoding

### Queue management
- Drag and drop to reorder files within the queue at any time, including during encoding
- Right-click → *Encode next* to prioritise any file immediately
- Right-click → *Stop after this file* to finish the current file and then pause
- All queue changes (reorder, new files, prioritisation) take effect on the fly without interrupting the current encode

### Post-encoding actions
- Do nothing
- Quit the application
- Shut down the computer

---

## Requirements

- Linux with a VAAPI-capable GPU (Intel Gen 6+, AMD GCN+)
- `ffmpeg` with `h264_vaapi` support
- Python 3.10+
- GTK3 / PyGObject (`python3-gi`, `gir1.2-gtk-3.0`)

Install dependencies on Debian/Ubuntu:

```bash
sudo apt install ffmpeg python3-gi python3-gi-cairo gir1.2-gtk-3.0
```

---

## Usage

```bash
python3 main.py
```

1. Set your global encoding settings in the right-hand panel (bitrate, resolution, output directory).
2. Use **Scan folder** to find files above a bitrate threshold, or drag files/folders directly onto the list.
3. Optionally adjust per-file settings via right-click.
4. Click **Start Encoding** to begin encoding.
