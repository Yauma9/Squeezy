import os
import sys
import subprocess
from pathlib import Path

TARGET_SIZE_MB = 9.7
AUDIO_BPS = 128_000
OVERHEAD_BPS = 80_000
MIN_VIDEO_BPS = 300_000

CREATE_NO_WINDOW = 0x08000000 if os.name == "nt" else 0

def get_ffmpeg_paths() -> tuple[str, str]:
    """
    Returns (ffmpeg_path, ffprobe_path) for dev and PyInstaller packaged modes.
    """
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[1]))
    ffmpeg = base / "ffmpeg_bin" / "ffmpeg.exe"
    ffprobe = base / "ffmpeg_bin" / "ffprobe.exe"
    return str(ffmpeg), str(ffprobe)


def _build_trim_args(trim_start_ms: int | None, trim_end_ms: int | None) -> list[str]:
    if trim_start_ms is None and trim_end_ms is None:
        return []
    if trim_start_ms is None or trim_end_ms is None:
        raise ValueError("Both trim_start_ms and trim_end_ms must be set")
    if trim_start_ms < 0 or trim_end_ms < 0 or trim_start_ms >= trim_end_ms:
        raise ValueError("Invalid trim range")

    start_s = trim_start_ms / 1000.0
    end_s = trim_end_ms / 1000.0
    return ["-ss", f"{start_s:.3f}", "-to", f"{end_s:.3f}"]


def compress_mp4(input_path: str, output_path: str, trim_start_ms: int | None = None, trim_end_ms: int | None = None) -> None:
    ffmpeg, _ = get_ffmpeg_paths()

    if not os.path.exists(ffmpeg):
        raise FileNotFoundError(f"FFmpeg not found at: {ffmpeg}")

    trim_args = _build_trim_args(trim_start_ms, trim_end_ms)

    cmd = [
        ffmpeg, "-y",
        "-i", input_path,
        *trim_args,
        "-c:v", "libx264",
        "-crf", "23",
        "-preset", "medium",
        "-c:a", "aac",
        "-b:a", "128k",
        "-movflags", "+faststart",
        output_path,
    ]

    # Capture output so you can show errors in the UI later
    p = subprocess.run(cmd, capture_output=True, text=True, creationflags=CREATE_NO_WINDOW)
    if p.returncode != 0:
        raise RuntimeError(p.stderr.strip() or "FFmpeg failed")


def clip_mp4(
    input_path: str,
    output_path: str,
    trim_start_ms: int,
    trim_end_ms: int,
) -> None:
    ffmpeg, _ = get_ffmpeg_paths()

    if not os.path.exists(ffmpeg):
        raise FileNotFoundError(f"FFmpeg not found at: {ffmpeg}")

    trim_args = _build_trim_args(trim_start_ms, trim_end_ms)
    cmd = [
        ffmpeg,
        "-y",
        "-i",
        input_path,
        *trim_args,
        "-c",
        "copy",
        "-movflags",
        "+faststart",
        output_path,
    ]

    p = subprocess.run(cmd, capture_output=True, text=True, creationflags=CREATE_NO_WINDOW)
    if p.returncode != 0:
        raise RuntimeError(p.stderr.strip() or "FFmpeg clip failed")


def get_duration_seconds(input_path: str) -> float:
    _, ffprobe = get_ffmpeg_paths()

    if not os.path.exists(ffprobe):
        raise FileNotFoundError(f"FFprobe not found at: {ffprobe}")

    cmd = [
        ffprobe,
        "-v",
        "error",
        "-show_entries",
        "format=duration",
        "-of",
        "default=noprint_wrappers=1:nokey=1",
        input_path,
    ]

    p = subprocess.run(cmd, capture_output=True, text=True, creationflags=CREATE_NO_WINDOW)
    if p.returncode != 0:
        raise RuntimeError(p.stderr.strip() or "FFprobe failed")

    try:
        return float(p.stdout.strip())
    except ValueError as e:
        raise RuntimeError("Could not parse duration from FFprobe output") from e


def compress_mp4_to_target_size(
    input_path: str,
    output_path: str,
    trim_start_ms: int | None = None,
    trim_end_ms: int | None = None,
    target_size_mb: float = TARGET_SIZE_MB,
) -> None:
    ffmpeg, _ = get_ffmpeg_paths()

    if not os.path.exists(ffmpeg):
        raise FileNotFoundError(f"FFmpeg not found at: {ffmpeg}")

    if trim_start_ms is not None and trim_end_ms is not None:
        if trim_start_ms < 0 or trim_end_ms < 0 or trim_start_ms >= trim_end_ms:
            raise ValueError("Invalid trim range")
        duration_seconds = (trim_end_ms - trim_start_ms) / 1000.0
    else:
        duration_seconds = get_duration_seconds(input_path)
    if duration_seconds <= 0:
        raise RuntimeError("Invalid duration reported by FFprobe")

    target_bits = target_size_mb * 1024 * 1024 * 8
    total_bps = target_bits / duration_seconds
    video_bps = max(int(total_bps - AUDIO_BPS - OVERHEAD_BPS), MIN_VIDEO_BPS)

    passlog_base = str(Path(output_path).with_suffix("")) + "_2pass"

    trim_args = _build_trim_args(trim_start_ms, trim_end_ms)

    pass1 = [
        ffmpeg,
        "-y",
        "-i",
        input_path,
        *trim_args,
        "-c:v",
        "libx264",
        "-b:v",
        str(video_bps),
        "-pass",
        "1",
        "-passlogfile",
        passlog_base,
        "-an",
        "-f",
        "mp4",
        "NUL",
    ]

    pass2 = [
        ffmpeg,
        "-y",
        "-i",
        input_path,
        *trim_args,
        "-c:v",
        "libx264",
        "-b:v",
        str(video_bps),
        "-pass",
        "2",
        "-passlogfile",
        passlog_base,
        "-c:a",
        "aac",
        "-b:a",
        "128k",
        "-movflags",
        "+faststart",
        output_path,
    ]

    try:
        p1 = subprocess.run(pass1, capture_output=True, text=True, creationflags=CREATE_NO_WINDOW)
        if p1.returncode != 0:
            raise RuntimeError(p1.stderr.strip() or "FFmpeg pass 1 failed")

        p2 = subprocess.run(pass2, capture_output=True, text=True, creationflags=CREATE_NO_WINDOW)
        if p2.returncode != 0:
            raise RuntimeError(p2.stderr.strip() or "FFmpeg pass 2 failed")
    finally:
        passlog_dir = Path(passlog_base).parent
        passlog_stem = Path(passlog_base).name
        for name in (
            f"{passlog_stem}.log",
            f"{passlog_stem}.log.mbtree",
            f"{passlog_stem}-0.log",
            f"{passlog_stem}-0.log.mbtree",
        ):
            try:
                os.remove(passlog_dir / name)
            except OSError:
                pass
