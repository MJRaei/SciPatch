"""Short narrated science videos, from AtomicShorts.

Wraps the non-LLM steps of AtomicShorts (github.com/vrindaasomjit/atomic-shorts, a
2025 LLM Hackathon project) that turn a storyboard into a video: checking a
storyboard (its JSON structure, narration time at 140 words per minute against the
target length, and the scientific terms to fact-check), rendering Manim
animation code to video, and adding a spoken narration track. AtomicShorts' GPT
storyboard, validation, and coding agents are left out: the calling agent writes
the storyboard and the Manim code, checks the facts, and fixes rendering errors.
The helpers marked "AtomicShorts" below follow the project's own functions.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Literal

Quality = Literal["low", "medium", "high", "production"]
FLAGS = {"low": "-ql", "medium": "-qm", "high": "-qh", "production": "-qp"}
#: AtomicShorts' patterns (validationagent.extract_scientific_terms), with the flags
#: they need: AtomicShorts applied IGNORECASE to all of them, which makes the
#: formula and "X principle" patterns match ordinary words.
SCIENCE_PATTERNS = [
    (
        r"\b(?:electron|proton|neutron|atom|molecule|crystal|lattice|quantum|magnetic|electric|thermal|mechanical|optical)\w*\b",
        re.IGNORECASE,
    ),
    (
        r"\b(?:flexoelectricity|piezoelectric|ferroelectric|dielectric|conductor|semiconductor|insulator)\b",
        re.IGNORECASE,
    ),
    (
        r"\b[A-Z][a-z]+(?:\s+[A-Z][a-z]+)*\s+(?:principle|effect|law|theory|equation|model|method)\b",
        0,
    ),
    (r"\b[A-Z][a-z]?\d*(?:[A-Z][a-z]?\d*)*\b", 0),
    (r"\b\d+\.?\d*\s*(?:nm|μm|mm|cm|m|km|MHz|GHz|eV|keV|MeV|GeV)\b", re.IGNORECASE),
]
FORMULA = re.compile(r"(?:[A-Z][a-z]?\d*){2,}|[A-Z][a-z]?\d+")


def _bin(name: str) -> str:
    """A program from the tool's environment (bin/ or Library/bin on Windows)."""
    for folder in (
        Path(sys.prefix) / "bin",
        Path(sys.prefix) / "Library" / "bin",
        Path(sys.prefix) / "Scripts",
    ):
        found = shutil.which(name, path=str(folder))
        if found:
            return found
    found = shutil.which(name)
    if not found:
        raise RuntimeError(f"{name} was not found in the tool's environment.")
    return found


def _probe(path: Path) -> dict:
    command = [
        _bin("ffprobe"),
        "-v",
        "error",
        "-show_entries",
        "format=duration:stream=codec_type,width,height,r_frame_rate,duration",
        "-of",
        "json",
        str(path),
    ]
    data = json.loads(subprocess.run(command, capture_output=True, text=True, check=True).stdout)
    streams = data.get("streams", [])
    video = next((s for s in streams if s.get("codec_type") == "video"), {})
    audio = next((s for s in streams if s.get("codec_type") == "audio"), None)
    rate = video.get("r_frame_rate", "0/1").split("/")
    return {
        "duration_s": round(float(data.get("format", {}).get("duration", 0.0)), 3),
        "width": video.get("width"),
        "height": video.get("height"),
        "fps": round(float(rate[0]) / float(rate[1]), 3)
        if len(rate) == 2 and float(rate[1])
        else None,
        "has_audio": audio is not None,
        "audio_duration_s": round(float(audio["duration"]), 3)
        if audio and audio.get("duration")
        else None,
    }


def _sanitize(text: str) -> str:
    """AtomicShorts codingagent._sanitize_code: strip Markdown fences from generated code."""
    match = re.search(r"```(?:[a-zA-Z0-9_-]+)?\s*([\s\S]*?)```", text, re.IGNORECASE)
    if match:
        code = match.group(1).strip()
    elif "```" in text:
        code = (
            text.replace("```python", "")
            .replace("```Python", "")
            .replace("```py", "")
            .replace("```", "")
            .strip()
        )
    else:
        code = text.strip()
    return (
        code.replace("```python", "")
        .replace("```Python", "")
        .replace("```py", "")
        .replace("```", "")
        .strip()
    )


def render_scene(
    code: str,
    scene: str = "StoryboardScene",
    quality: Quality = "low",
    output: str = "video.mp4",
) -> dict:
    """Render Manim (Community edition) animation code to an MP4 video.

    Args:
        code: Path to a Python file with the Manim scene (Markdown fences are
            stripped, as AtomicShorts does), or the code itself.
        scene: Name of the Scene class to render.
        quality: "low" (854x480, 15 fps; fast previews), "medium" (1280x720, 30
            fps), "high" (1920x1080, 60 fps), or "production" (2560x1440, 60 fps).
        output: The MP4 file to write.

    Returns:
        The video file, duration (s), resolution, frame rate, and render time; if
        Manim fails, an error with the end of Manim's message (line and cause) so
        the code can be fixed.
    """
    path = Path(code)
    text = path.read_text(encoding="utf-8") if len(code) < 4096 and path.is_file() else code
    if "class " not in text:
        raise ValueError("code must be a Python file or text defining a Manim Scene class.")
    if not re.fullmatch(r"[A-Za-z_]\w*", scene):
        raise ValueError(f"Invalid scene name {scene!r}.")
    import time

    started = time.perf_counter()
    with tempfile.TemporaryDirectory(prefix="manim-") as scratch:
        folder = Path(scratch)
        (folder / "scene.py").write_text(_sanitize(text), encoding="utf-8")
        command = [
            _bin("manim"),
            FLAGS[quality],
            "--media_dir",
            str(folder / "media"),
            "--disable_caching",
            "scene.py",
            scene,
            "-o",
            "video.mp4",
        ]
        environment = {
            **os.environ,
            "PATH": os.pathsep.join([str(Path(_bin("ffmpeg")).parent), os.environ.get("PATH", "")]),
        }
        completed = subprocess.run(
            command, cwd=folder, capture_output=True, text=True, env=environment, check=False
        )
        rendered = next(iter(folder.glob("media/videos/**/video.mp4")), None)
        if completed.returncode != 0 or rendered is None:
            message = (completed.stderr or completed.stdout).strip().splitlines()
            tail = "\n".join(
                line.strip("│ ").rstrip() for line in message[-25:] if line.strip("│ ─╭╮╰╯")
            )
            raise RuntimeError(f"Manim failed (exit {completed.returncode}):\n{tail}")
        shutil.copyfile(rendered, output)
    return {
        "video": output,
        **_probe(Path(output)),
        "quality": quality,
        "render_seconds": round(time.perf_counter() - started, 1),
    }


def _storyboard(storyboard: str) -> dict:
    path = Path(storyboard)
    text = (
        path.read_text(encoding="utf-8")
        if len(storyboard) < 4096 and path.is_file()
        else storyboard
    )
    match = re.search(
        r"===JSON START===\s*(\{.*\})\s*===JSON END===", text, re.S
    )  # AtomicShorts format
    try:
        return json.loads(match.group(1) if match else text)
    except json.JSONDecodeError as exc:
        raise ValueError(f"The storyboard is not valid JSON: {exc}") from exc


def _reading_seconds(text: str, wpm: int) -> tuple[int, float]:
    """AtomicShorts validationagent.estimate_reading_time."""
    words = len(text.split())
    return words, round(words / wpm * 60, 1)


def check_storyboard(
    storyboard: str,
    target_seconds: list[float] | None = None,
    wpm: int = 140,
    max_terms: int = 15,
) -> dict:
    """Check a video storyboard: structure, narration time, and terms to fact-check.

    The storyboard is AtomicShorts' JSON: {"prompt", "title", "age_level",
    "video_length", "scenes": [{"scene_id", "title", "narration", "visuals":
    [{"description"}]}]}.

    Args:
        storyboard: Path to the JSON file, or the JSON text (an AtomicShorts reply
            with ===JSON START=== / ===JSON END=== markers also works).
        target_seconds: Desired video length as [minimum, maximum] (default
            [30, 60], as in AtomicShorts).
        wpm: Narration speed in words per minute (AtomicShorts uses 140).
        max_terms: Maximum number of scientific terms to list.

    Returns:
        Whether the required fields are present; for each scene its narration
        words and seconds and whether it has visuals; the total narration time and
        whether it fits the target; and the scientific terms and claims to verify
        (AtomicShorts' patterns and chemistry keyword list).
    """
    data = _storyboard(storyboard)
    low, high = target_seconds or [30.0, 60.0]
    if not isinstance(data, dict):
        raise ValueError("The storyboard must be a JSON object.")
    scenes = data.get("scenes", [])
    rows = []
    for index, scene in enumerate(scenes, start=1):
        narration = scene.get("narration", "") or ""
        words, seconds = _reading_seconds(narration, wpm)
        rows.append(
            {
                "scene": scene.get("scene_id", index),
                "title": scene.get("title"),
                "narration_words": words,
                "narration_seconds": seconds,
                "has_visuals": bool(scene.get("visuals")),
            }
        )
    narration = " ".join(scene.get("narration", "") or "" for scene in scenes)
    words, seconds = _reading_seconds(narration, wpm)
    missing = [field for field in ("prompt", "title", "scenes") if field not in data]
    verdict = "too short" if seconds < low else "too long" if seconds > high else "fits"
    return {
        "title": data.get("title"),
        "required_fields_present": not missing,
        "missing_fields": missing,
        "scenes": rows,
        "scene_count": len(rows),
        "total_narration_words": words,
        "total_narration_seconds": seconds,
        "target_seconds": [low, high],
        "length": verdict,
        "terms_to_fact_check": _terms(narration + " " + _visual_text(scenes), max_terms),
        "wpm": wpm,
    }


def _visual_text(scenes: list) -> str:
    parts = []
    for scene in scenes:
        for visual in scene.get("visuals", []) or []:
            parts.append(visual.get("description", "") if isinstance(visual, dict) else str(visual))
    return " ".join(parts)


def _terms(text: str, max_terms: int) -> list[str]:
    """AtomicShorts' regex patterns plus its chemistry keyword list (no vector store)."""
    found = set()
    for index, (pattern, flags) in enumerate(SCIENCE_PATTERNS):
        matches = re.findall(pattern, text, flags)
        if index == 3:  # chemical formulas: NaCl, H2O, Fe2O3 (not ordinary capitalized words)
            matches = [m for m in matches if FORMULA.fullmatch(m)]
        found.update(matches)
    source = os.environ.get("MOTEL_SOURCE_DIR")
    keywords_file = Path(source) / "chemistry_keywords.txt" if source else None
    if keywords_file and keywords_file.is_file():
        lowered = text.lower()
        keywords = [
            k.strip().lower()
            for k in keywords_file.read_text(encoding="utf-8").splitlines()
            if k.strip()
        ]
        found.update(k for k in keywords if k in lowered)
    terms = [
        t for t in found if len(t) > 2 and t.lower() not in {"the", "and", "for", "with", "show"}
    ]
    return sorted(terms, key=lambda t: (-len(t), t))[:max_terms]


def narrate(
    video: str,
    narration: str | None = None,
    storyboard: str | None = None,
    language: str = "en",
    fit: Literal["extend_video", "trim_audio", "none"] = "extend_video",
    output: str = "narrated.mp4",
) -> dict:
    """Add a spoken narration (Google text-to-speech) to a video.

    Args:
        video: The video (e.g. from render_scene).
        narration: Text to speak. Or give storyboard instead.
        storyboard: Storyboard JSON (file or text); its scenes' narration is spoken
            in order, as AtomicShorts does.
        language: Language code for the voice (e.g. "en", "fr", "de").
        fit: When the narration is longer than the video: "extend_video" holds the
            last frame, "trim_audio" cuts the narration, "none" keeps both lengths.
        output: The narrated MP4 file.

    Returns:
        The narrated video, its duration, the narration's duration, the original
        video's duration, and whether the narration was longer.
    """
    from gtts import gTTS

    source = Path(video)
    if not source.is_file():
        raise ValueError(f"Video file {video!r} not found.")
    if (narration is None) == (storyboard is None):
        raise ValueError("Give either narration (text) or storyboard.")
    text = narration or " ".join(
        s.get("narration", "") or "" for s in _storyboard(storyboard).get("scenes", [])
    )
    if not text.strip():
        raise ValueError("There is no narration text.")
    original = _probe(source)
    with tempfile.TemporaryDirectory(prefix="narration-") as scratch:
        speech = Path(scratch) / "narration.mp3"
        try:
            gTTS(text, lang=language).save(str(speech))
        except Exception as exc:
            raise RuntimeError(f"Text-to-speech failed (it needs the internet): {exc}") from exc
        spoken = _probe(speech)["duration_s"]
        longer = spoken > original["duration_s"]
        command = [_bin("ffmpeg"), "-y", "-loglevel", "error", "-i", str(source), "-i", str(speech)]
        if longer and fit == "extend_video":
            extra = round(spoken - original["duration_s"] + 0.1, 3)
            command += [
                "-filter_complex",
                f"[0:v]tpad=stop_mode=clone:stop_duration={extra}[v]",
                "-map",
                "[v]",
                "-map",
                "1:a",
                "-c:v",
                _encoder(),
                "-pix_fmt",
                "yuv420p",
            ]
        else:
            command += ["-map", "0:v", "-map", "1:a", "-c:v", "copy"]
            if fit == "trim_audio":
                command += ["-shortest"]
        command += ["-c:a", "aac", output]
        completed = subprocess.run(command, capture_output=True, text=True, check=False)
        if completed.returncode != 0:
            raise RuntimeError(f"ffmpeg failed: {completed.stderr.strip()[-600:]}")
    result = _probe(Path(output))
    return {
        "video": output,
        "duration_s": result["duration_s"],
        "has_audio": result["has_audio"],
        "narration_seconds": spoken,
        "original_video_seconds": original["duration_s"],
        "narration_longer_than_video": longer,
        "fit": fit,
        "words": len(text.split()),
    }


def _encoder() -> str:
    listing = subprocess.run(
        [_bin("ffmpeg"), "-hide_banner", "-encoders"], capture_output=True, text=True, check=False
    ).stdout
    for name in ("libx264", "libopenh264", "mpeg4"):
        if re.search(rf"\s{name}\s", listing):
            return name
    return "mpeg4"
