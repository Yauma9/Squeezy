# Squeezy

Squeezy is a small Windows desktop application for compressing MP4 videos to
Discord-friendly sizes. It provides an in-app video preview, lets you select a
portion of a video, and runs FFmpeg processing in the background so the
interface remains responsive.

## Features

- Open an MP4 file by selecting it or dragging it onto the drop zone.
- Preview the video with play/pause controls and a seek bar.
- Set and clear Start and End trim points from the current playback position.
- Preview only the selected section before exporting it.
- Compress a video to approximately:
  - **50 MB** (`49.5 MB` target)
  - **20 MB** (`19.4 MB` target)
- Export a selected section without re-encoding with **Clip Only**.
- Automatically avoid overwriting existing files by adding `(2)`, `(3)`, and
  so on to the output name.
- Display success and error messages when processing finishes.

## How it works

1. Start Squeezy.
2. Select an MP4 file or drag one into the application.
3. Use the preview controls to find the desired section.
4. Optionally choose **Set Start** and **Set End** to define a trim range.
   Both compression actions can use the selected range.
5. Choose an export action:
   - **Compress to 50MB** re-encodes the video with two-pass H.264 encoding and
     AAC audio.
   - **Compress to 20MB** uses the same process with a smaller target.
   - **Clip Only** copies the selected section without re-encoding, which is
     faster but may only cut accurately at compatible keyframes.
6. Wait for the completion dialog and find the output beside the source file.

When a trim range is selected, the preview can be toggled with
**Preview Selection**. Start must be before End and both points must fall
within the video duration.

## Output files

Exports are written to the same directory as the source MP4:

| Action | Default output name |
| --- | --- |
| Compress to 50MB | `video - 50MB.mp4` |
| Compress to 20MB | `video - 20MB.mp4` |
| Clip Only | `video - clip.mp4` |

If a file with the default name already exists, Squeezy creates a new name such
as `video - 50MB (2).mp4` instead of replacing the existing file.

## Requirements

- Windows
- Python 3.10 or newer
- FFmpeg and FFprobe executables
- Python dependency listed in [`requirements.txt`](./requirements.txt)

The application expects FFmpeg files in `ffmpeg_bin`:

```text
ffmpeg_bin/
├── ffmpeg.exe
└── ffprobe.exe
```

The other FFmpeg DLLs should remain alongside `ffmpeg.exe` so FFmpeg can load
its codecs and libraries. The packaged build includes these files when they
are present.

## Run from source

From the project directory, create and activate a virtual environment, install
the dependency, and start the application:

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python .\app\main.py
```

If PowerShell prevents script activation, run the executable directly instead:

```powershell
.\.venv\Scripts\python.exe .\app\main.py
```

## Build a Windows executable

The repository includes a PyInstaller specification that bundles the
application and the FFmpeg executables:

```powershell
.\.venv\Scripts\python.exe -m PyInstaller .\main.spec
```

The generated executable is placed in the `dist` directory. Keep the bundled
`ffmpeg_bin` files with the executable if you distribute the unpackaged output.

## Project structure

```text
app/
├── main.py          # PySide6 user interface and application workflow
└── ffmpeg_util.py   # FFmpeg command construction and video processing
ffmpeg_bin/          # FFmpeg/FFprobe binaries and supporting DLLs
main.spec            # PyInstaller packaging configuration
requirements.txt     # Python dependencies
```

## Technical notes

- Compression calculates a video bitrate from the selected duration and target
  size, reserving space for AAC audio and container overhead.
- Compression uses H.264 video, AAC audio, and `+faststart` for web-friendly
  MP4 output.
- Video processing runs on a worker thread to keep the UI responsive.
- Temporary two-pass FFmpeg log files are removed after processing.