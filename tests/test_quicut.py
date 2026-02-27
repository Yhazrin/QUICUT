import argparse
import json
import unittest
from unittest.mock import patch
from pathlib import Path
from tempfile import TemporaryDirectory

from src.quicut import (
    build_env_report,
    build_plan_payload,
    build_segments,
    format_timecode,
    output_name,
    parse_progress_line,
    parse_timecode,
    print_env_report,
    preflight_check,
    resolve_output_extension,
    read_cut_points_file,
    run,
)


class TestTimecode(unittest.TestCase):
    def test_parse_seconds(self):
        self.assertAlmostEqual(parse_timecode("120.5"), 120.5)

    def test_parse_hms(self):
        self.assertAlmostEqual(parse_timecode("01:02:03.500"), 3723.5)

    def test_parse_ms(self):
        self.assertAlmostEqual(parse_timecode("05:10"), 310)

    def test_format(self):
        self.assertEqual(format_timecode(3723.5), "01:02:03.500")

    def test_build_segments(self):
        result = build_segments(100.0, [10, 30, 30, -5, 120])
        self.assertEqual([(s.start, s.end) for s in result], [(0.0, 10.0), (10.0, 30.0), (30.0, 100.0)])

    def test_read_cut_points_file(self):
        with TemporaryDirectory() as td:
            p = Path(td) / "cuts.txt"
            p.write_text("\n# comment\n00:00:10\n  25.5\n", encoding="utf-8")
            self.assertEqual(read_cut_points_file(p), ["00:00:10", "25.5"])

    def test_output_name_uses_given_extension(self):
        self.assertEqual(output_name(Path("clip.mkv"), 2, ext=".mkv"), "clip_002.mkv")

    def test_build_plan_payload(self):
        segments = build_segments(60.0, [10, 30])
        payload = build_plan_payload(Path("/tmp/demo.mp4"), segments)
        self.assertEqual(payload["segment_count"], 3)
        self.assertEqual(payload["segments"][0]["start"], "00:00:00.000")
        self.assertEqual(payload["segments"][2]["end"], "00:01:00.000")


    def test_resolve_output_extension(self):
        self.assertEqual(resolve_output_extension(Path("demo.mkv"), "copy", None), ".mkv")
        self.assertEqual(resolve_output_extension(Path("demo.mkv"), "reencode", None), ".mp4")
        self.assertEqual(resolve_output_extension(Path("demo.mkv"), "copy", "mov"), ".mov")

    def test_parse_progress_line(self):
        self.assertEqual(parse_progress_line("out_time_ms=1200000\n"), {"out_time_ms": "1200000"})
        self.assertEqual(parse_progress_line("progress=end"), {"progress": "end"})
        self.assertIsNone(parse_progress_line("frame 12"))


    def test_preflight_check_dry_run_with_duration_skips_binaries(self):
        args = argparse.Namespace(duration=30.0, dry_run=True)
        preflight_check(args)

    @patch("src.quicut.subprocess.run")
    def test_preflight_requires_ffprobe_when_duration_missing(self, mock_run):
        mock_run.side_effect = FileNotFoundError("ffprobe")
        args = argparse.Namespace(duration=None, dry_run=True)
        with self.assertRaises(RuntimeError):
            preflight_check(args)

    @patch("src.quicut.subprocess.run")
    def test_preflight_requires_ffmpeg_when_not_dry_run(self, mock_run):
        def fake_run(cmd, **kwargs):
            if cmd[0] == "ffprobe":
                return None
            raise FileNotFoundError("ffmpeg")

        mock_run.side_effect = fake_run
        args = argparse.Namespace(duration=None, dry_run=False)
        with self.assertRaises(RuntimeError):
            preflight_check(args)


    @patch("src.quicut.shutil.which")
    @patch("src.quicut.subprocess.run")
    def test_build_env_report(self, mock_run, mock_which):
        mock_which.side_effect = lambda cmd: f"/usr/bin/{cmd}" if cmd in {"python3", "ffmpeg", "ffprobe"} else None
        mock_run.return_value = argparse.Namespace(returncode=0, stdout="6.1.1\n")
        report = build_env_report()
        self.assertEqual(report["ffmpeg"], "/usr/bin/ffmpeg")
        self.assertEqual(report["ffprobe"], "/usr/bin/ffprobe")
        self.assertEqual(report["pyinstaller"], "6.1.1")

    @patch("src.quicut.build_env_report")
    def test_print_env_report_returns_nonzero_when_not_ready(self, mock_report):
        mock_report.return_value = {"ffmpeg": None, "ffprobe": None}
        self.assertEqual(print_env_report(), 2)

    def test_run_writes_plan_json_in_dry_run(self):
        with TemporaryDirectory() as td:
            input_file = Path(td) / "input.mp4"
            input_file.write_text("fake", encoding="utf-8")
            plan_file = Path(td) / "plan" / "segments.json"

            args = argparse.Namespace(
                input=str(input_file),
                cuts=["10", "20"],
                cuts_file=None,
                mode="copy",
                output_dir=str(Path(td) / "outputs"),
                duration=30.0,
                dry_run=True,
                list_segments=False,
                min_segment=0.0,
                plan_json=str(plan_file),
                output_ext=None,
                show_progress=False,
            )

            self.assertEqual(run(args), 0)
            self.assertTrue(plan_file.exists())
            payload = json.loads(plan_file.read_text(encoding="utf-8"))
            self.assertEqual(payload["segment_count"], 3)


if __name__ == "__main__":
    unittest.main()
