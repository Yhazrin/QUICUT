#!/usr/bin/env python3
"""QUICUT CLI MVP.

A minimal command-line utility to split one long video by user-provided cut points.
Designed as an implementation starter before desktop GUI integration.
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Optional

TIME_RE = re.compile(r"^(?:(\d+):)?([0-5]?\d):([0-5]?\d(?:\.\d+)?)$")
VERSION = "0.1.0"


@dataclass(frozen=True)
class Segment:
    index: int
    start: float
    end: float

    @property
    def duration(self) -> float:
        return max(0.0, self.end - self.start)


def parse_timecode(value: str) -> float:
    """Parse `SS(.ms)` or `MM:SS(.ms)` or `HH:MM:SS(.ms)` into seconds."""
    value = value.strip()
    if value.replace(".", "", 1).isdigit():
        return float(value)

    match = TIME_RE.match(value)
    if not match:
        raise ValueError(f"invalid timecode: {value}")

    hh = int(match.group(1) or 0)
    mm = int(match.group(2))
    ss = float(match.group(3))
    return hh * 3600 + mm * 60 + ss


def read_cut_points_file(path: Path) -> List[str]:
    """Read cut points from text file.

    Supports one timecode per line. Empty lines and comments (starting with '#')
    are ignored.
    """
    raw_values: List[str] = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        value = raw.strip()
        if not value or value.startswith("#"):
            continue
        raw_values.append(value)
    return raw_values


def format_timecode(seconds: float) -> str:
    hh = int(seconds // 3600)
    mm = int((seconds % 3600) // 60)
    ss = seconds % 60
    return f"{hh:02d}:{mm:02d}:{ss:06.3f}"






def build_env_report() -> Dict[str, object]:
    report: Dict[str, object] = {
        "python": shutil.which("python3") or shutil.which("python") or "unknown",
        "ffmpeg": shutil.which("ffmpeg"),
        "ffprobe": shutil.which("ffprobe"),
        "pyinstaller": None,
    }
    pyinstaller = subprocess.run(
        ["python3", "-m", "PyInstaller", "--version"],
        capture_output=True,
        text=True,
    )
    if pyinstaller.returncode == 0:
        report["pyinstaller"] = pyinstaller.stdout.strip()
    return report


def print_env_report() -> int:
    report = build_env_report()
    print(json.dumps(report, ensure_ascii=False, indent=2))
    # ready means core split deps are present
    return 0 if report.get("ffmpeg") and report.get("ffprobe") else 2

def ensure_command_available(command: str) -> None:
    try:
        subprocess.run([command, "-version"], check=True, capture_output=True, text=True)
    except FileNotFoundError as exc:
        raise RuntimeError(f"required command not found: {command}") from exc
    except subprocess.CalledProcessError as exc:
        raise RuntimeError(f"failed to execute {command} -version") from exc


def preflight_check(args: argparse.Namespace) -> None:
    if args.duration is None:
        ensure_command_available("ffprobe")
    if not args.dry_run:
        ensure_command_available("ffmpeg")

def read_duration_seconds(input_file: Path) -> float:
    cmd = [
        "ffprobe",
        "-v",
        "error",
        "-show_entries",
        "format=duration",
        "-of",
        "json",
        str(input_file),
    ]
    result = subprocess.run(cmd, check=True, capture_output=True, text=True)
    raw = json.loads(result.stdout)
    return float(raw["format"]["duration"])


def build_segments(duration: float, cut_points: Iterable[float]) -> List[Segment]:
    points = sorted(set(float(p) for p in cut_points if 0.0 < p < duration))
    boundaries = [0.0, *points, duration]
    segments: List[Segment] = []

    for i in range(len(boundaries) - 1):
        start = boundaries[i]
        end = boundaries[i + 1]
        if end > start:
            segments.append(Segment(index=i + 1, start=start, end=end))
    return segments


def output_name(input_file: Path, index: int, ext: str = ".mp4") -> str:
    stem = input_file.stem
    return f"{stem}_{index:03d}{ext}"


def resolve_output_extension(input_file: Path, mode: str, output_ext: Optional[str]) -> str:
    if output_ext:
        ext = output_ext if output_ext.startswith('.') else f'.{output_ext}'
        return ext.lower()
    if mode == "copy":
        return input_file.suffix or ".mp4"
    return ".mp4"


def build_plan_payload(input_file: Path, segments: List[Segment]) -> dict:
    return {
        "input": str(input_file),
        "segment_count": len(segments),
        "segments": [
            {
                "index": seg.index,
                "start": format_timecode(seg.start),
                "end": format_timecode(seg.end),
                "duration_seconds": round(seg.duration, 3),
            }
            for seg in segments
        ],
    }


def write_plan_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def parse_progress_line(line: str) -> Optional[Dict[str, str]]:
    """Parse one ffmpeg `-progress` key=value line."""
    text = line.strip()
    if not text or "=" not in text:
        return None
    key, value = text.split("=", 1)
    key = key.strip()
    value = value.strip()
    if not key:
        return None
    return {key: value}


def run_ffmpeg_command(cmd: List[str], show_progress: bool) -> None:
    if not show_progress:
        subprocess.run(cmd, check=True)
        return

    process = subprocess.Popen(
        [*cmd[:-1], "-progress", "pipe:1", "-nostats", cmd[-1]],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    assert process.stdout is not None

    snapshot: Dict[str, str] = {}
    for line in process.stdout:
        entry = parse_progress_line(line)
        if entry is None:
            continue
        snapshot.update(entry)
        if "out_time_ms" in entry:
            print(f"progress out_time_ms={entry['out_time_ms']}")
        if entry.get("progress") == "end":
            speed = snapshot.get("speed", "n/a")
            print(f"progress end speed={speed}")

    rc = process.wait()
    if rc != 0:
        raise subprocess.CalledProcessError(rc, cmd)


def build_ffmpeg_command(
    input_file: Path,
    output_file: Path,
    segment: Segment,
    mode: str,
) -> List[str]:
    if mode == "copy":
        return [
            "ffmpeg",
            "-y",
            "-ss",
            format_timecode(segment.start),
            "-to",
            format_timecode(segment.end),
            "-i",
            str(input_file),
            "-map",
            "0",
            "-c",
            "copy",
            str(output_file),
        ]

    if mode == "reencode":
        return [
            "ffmpeg",
            "-y",
            "-ss",
            format_timecode(segment.start),
            "-to",
            format_timecode(segment.end),
            "-i",
            str(input_file),
            "-c:v",
            "libx264",
            "-preset",
            "slow",
            "-crf",
            "16",
            "-c:a",
            "aac",
            "-b:a",
            "192k",
            str(output_file),
        ]

    raise ValueError(f"unsupported mode: {mode}")


def run(args: argparse.Namespace) -> int:
    if not args.input:
        raise ValueError("--input is required unless --check-env is used")
    input_file = Path(args.input).expanduser().resolve()
    if not input_file.exists():
        raise FileNotFoundError(f"input does not exist: {input_file}")

    output_dir = Path(args.output_dir).expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    preflight_check(args)

    if args.min_segment < 0:
        raise ValueError("--min-segment must be >= 0")

    if args.duration is not None:
        duration = float(args.duration)
    else:
        duration = read_duration_seconds(input_file)

    raw_cuts: List[str] = list(args.cuts or [])
    if args.cuts_file:
        cuts_file = Path(args.cuts_file).expanduser().resolve()
        if not cuts_file.exists():
            raise FileNotFoundError(f"cuts file does not exist: {cuts_file}")
        raw_cuts.extend(read_cut_points_file(cuts_file))

    if not raw_cuts:
        raise ValueError("no cut points provided; use --cuts and/or --cuts-file")

    cut_points = [parse_timecode(v) for v in raw_cuts]
    segments = build_segments(duration, cut_points)

    if not segments:
        print("No valid segments were generated.")
        return 1

    if args.min_segment > 0:
        too_short = [s for s in segments if s.duration < args.min_segment]
        if too_short:
            shortest = min(s.duration for s in too_short)
            raise ValueError(
                "generated segment shorter than --min-segment: "
                f"min found {shortest:.3f}s, required {args.min_segment:.3f}s"
            )

    if args.list_segments:
        for seg in segments:
            print(
                f"[{seg.index:03d}] {format_timecode(seg.start)} -> "
                f"{format_timecode(seg.end)} ({seg.duration:.3f}s)"
            )
        if args.dry_run:
            print(f"Planned {len(segments)} segment(s).")

    if args.plan_json:
        plan_json_path = Path(args.plan_json).expanduser().resolve()
        payload = build_plan_payload(input_file, segments)
        write_plan_json(plan_json_path, payload)
        print(f"Wrote segment plan: {plan_json_path}")
        if args.dry_run:
            return 0

    output_ext = resolve_output_extension(input_file, args.mode, args.output_ext)

    for seg in segments:
        out_path = output_dir / output_name(input_file, seg.index, ext=output_ext)
        cmd = build_ffmpeg_command(input_file, out_path, seg, args.mode)
        print(" ".join(cmd))
        if not args.dry_run:
            run_ffmpeg_command(cmd, show_progress=args.show_progress)

    print(f"Done. Generated {len(segments)} segment(s).")
    return 0


def make_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Split long videos by time cut points")
    parser.add_argument("--version", action="version", version=f"quicut {VERSION}")
    parser.add_argument("--check-env", action="store_true", help="Print environment readiness and exit")
    parser.add_argument("--input", help="Path to source video")
    parser.add_argument(
        "--cuts",
        nargs="+",
        default=[],
        help="Cut points, e.g. 120 05:10 00:20:30.500",
    )
    parser.add_argument(
        "--cuts-file",
        help="Optional text file containing one cut point per line",
    )
    parser.add_argument(
        "--mode",
        choices=["copy", "reencode"],
        default="copy",
        help="Export mode",
    )
    parser.add_argument(
        "--output-dir",
        default="./outputs",
        help="Directory for generated segments",
    )
    parser.add_argument(
        "--duration",
        type=float,
        help="Optional media duration (seconds), skip ffprobe when provided",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print ffmpeg commands only, do not execute",
    )
    parser.add_argument(
        "--list-segments",
        action="store_true",
        help="Print planned segments before exporting",
    )
    parser.add_argument(
        "--min-segment",
        type=float,
        default=0.0,
        help="Fail if any generated segment is shorter than this duration (seconds)",
    )
    parser.add_argument(
        "--plan-json",
        help="Optional path to write segment planning result as JSON",
    )
    parser.add_argument(
        "--output-ext",
        help="Optional output extension (e.g. mp4/mkv); defaults to mode-aware behavior",
    )
    parser.add_argument(
        "--show-progress",
        action="store_true",
        help="Parse and print ffmpeg -progress output during export",
    )
    return parser


def main() -> int:
    parser = make_parser()
    args = parser.parse_args()
    if args.check_env:
        return print_env_report()
    return run(args)


if __name__ == "__main__":
    raise SystemExit(main())
