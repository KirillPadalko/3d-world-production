"""Load the scripts of the video-to-blueprint skill (.claude/skills/video-to-blueprint)."""

from __future__ import annotations

import importlib.util
import shutil
import subprocess
import sys
from pathlib import Path
from types import ModuleType

from tests.conftest import REPO_ROOT

SKILL = REPO_ROOT / ".claude" / "skills" / "video-to-blueprint"
SCRIPTS = SKILL / "scripts"
HAS_FFMPEG = shutil.which("ffmpeg") is not None and shutil.which("ffprobe") is not None


def load(name: str) -> ModuleType:
    """Import ``scripts/<name>.py`` once (registered so dataclasses resolve their module)."""
    module_name = f"video_skill_{name}"
    if module_name in sys.modules:
        return sys.modules[module_name]
    spec = importlib.util.spec_from_file_location(module_name, SCRIPTS / f"{name}.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def make_video(path: Path, *, seconds_per_shot: float = 2.0) -> Path:
    """Three visibly different shots (two cuts), 640x360 at 25 fps, with a creation time."""
    shot = f"duration={seconds_per_shot}"
    subprocess.run(
        [
            "ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "error", "-y",
            "-f", "lavfi", "-i", f"testsrc2=size=640x360:rate=25:{shot}",
            "-f", "lavfi", "-i", f"smptebars=size=640x360:rate=25:{shot}",
            "-f", "lavfi", "-i", f"color=c=0x2a6e2a:size=640x360:rate=25:{shot}",
            "-filter_complex", "[0][1][2]concat=n=3:v=1:a=0",
            "-c:v", "libx264", "-pix_fmt", "yuv420p",
            "-metadata", "creation_time=2026-05-01T10:00:00Z", str(path),
        ],
        check=True,
    )  # fmt: skip
    return path


def dji_srt(seconds: float, *, fps: int = 25, altitude: float = 60.0) -> str:
    """A DJI-style telemetry subtitle track (one cue per frame)."""

    def stamp(t: float) -> str:
        ms = round(t * 1000)
        return (
            f"{ms // 3_600_000:02d}:{ms // 60_000 % 60:02d}:{ms // 1000 % 60:02d},{ms % 1000:03d}"
        )

    cues = []
    for i in range(round(seconds * fps)):
        start, end = i / fps, (i + 1) / fps
        cues.append(
            f"{i + 1}\n{stamp(start)} --> {stamp(end)}\n"
            f'<font size="28">FrameCnt: {i + 1}, DiffTime: 40ms\n'
            "2026-05-01 10:00:00.000\n"
            f"[iso: 100] [shutter: 1/640.0] [fnum: 2.8] [focal_len: 24.00] "
            f"[latitude: {55.75 + i * 1e-6:.6f}] [longitude: 37.61] "
            f"[rel_alt: {altitude:.3f} abs_alt: 210.000] </font>\n"
        )
    return "\n".join(cues)
