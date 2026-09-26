from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "grok-everywhere" / "scripts" / "grok.py"
SPEC = importlib.util.spec_from_file_location("grok_everywhere_cli", SCRIPT)
assert SPEC and SPEC.loader
grok = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = grok
SPEC.loader.exec_module(grok)


class GrokCliTests(unittest.TestCase):
    def test_media_workflows_use_new_models_and_image_quality(self) -> None:
        parser = grok.build_parser()
        image_args = parser.parse_args(
            [
                "--dry-run",
                "image",
                "generate",
                "Detailed portrait",
                "--quality",
                "medium",
                "--resolution",
                "2k",
            ]
        )
        image_request = grok.command_image(image_args)["request"]
        self.assertEqual(image_args.model, "grok-imagine-image-2.0")
        self.assertEqual(image_request["quality"], "medium")
        self.assertEqual(image_request["resolution"], "2k")

        commands = (
            (["image", "edit", "input.jpg", "Adjust lighting"], "grok-imagine-image-2.0"),
            (["video", "generate", "A paper boat"], "grok-imagine-video-1.5"),
            (["video", "edit", "input.mp4", "Make it rainy"], "grok-imagine-video"),
            (["video", "extend", "input.mp4", "Continue"], "grok-imagine-video"),
        )
        for command, model in commands:
            with self.subTest(command=command):
                self.assertEqual(parser.parse_args(command).model, model)

    def test_text_workflows_default_to_grok_4_6(self) -> None:
        with mock.patch.dict(os.environ, {}, clear=True):
            parser = grok.build_parser()
        commands = (
            ["text", "Explain this"],
            ["search", "x", "AI news"],
            ["search", "web", "xAI pricing"],
            ["audio", "minutes", "meeting.mp3"],
        )
        for command in commands:
            with self.subTest(command=command):
                self.assertEqual(parser.parse_args(command).model, "grok-4.6")

    def test_text_payload_offers_web_search_unless_disabled(self) -> None:
        parser = grok.build_parser()
        default_args = parser.parse_args(["--dry-run", "text", "Explain this"])
        default_payload = grok.build_text_payload(default_args)
        self.assertEqual(default_payload["tools"], [{"type": "web_search"}])
        self.assertEqual(default_payload["tool_choice"], "auto")
        self.assertEqual(default_payload["max_turns"], 1)

        offline_args = parser.parse_args(
            ["--dry-run", "text", "Explain this", "--no-search"]
        )
        offline_payload = grok.build_text_payload(offline_args)
        self.assertNotIn("tools", offline_payload)
        self.assertNotIn("tool_choice", offline_payload)

    def test_search_quick_payload_is_bounded(self) -> None:
        args = grok.build_parser().parse_args(
            [
                "--dry-run",
                "search",
                "x",
                "24 hour AI news",
                "--depth",
                "quick",
                "--allow",
                "@xai",
                "--media",
                "both",
            ]
        )
        tool = grok.build_search_tool(args)
        payload = grok.build_search_payload(args, tool)
        self.assertEqual(payload["max_turns"], 1)
        self.assertTrue(payload["stream"])
        self.assertTrue(payload["parallel_tool_calls"])
        self.assertEqual(tool["allowed_x_handles"], ["xai"])
        self.assertTrue(tool["enable_image_understanding"])
        self.assertTrue(tool["enable_video_understanding"])

    def test_web_search_tool_uses_session_compatible_payload(self) -> None:
        args = grok.build_parser().parse_args(
            ["--dry-run", "search", "web", "official xAI pricing"]
        )
        self.assertEqual(grok.build_search_tool(args), {"type": "web_search"})

    def test_sanitize_removes_secrets_and_media(self) -> None:
        value = {
            "Authorization": "Bearer secret",
            "nested": {
                "token": "secret",
                "image": "data:image/png;base64,abc123",
            },
        }
        clean = grok.sanitize(value)
        self.assertEqual(clean["Authorization"], "[REDACTED]")
        self.assertEqual(clean["nested"]["token"], "[REDACTED]")
        self.assertNotIn("abc123", clean["nested"]["image"])

    def test_diarized_words_become_speaker_turns(self) -> None:
        response = {
            "words": [
                {"word": "你好", "start": 0, "end": 0.3, "speaker": 0},
                {"word": "。", "start": 0.3, "end": 0.4, "speaker": 0},
                {"word": "收到", "start": 0.5, "end": 0.8, "speaker": 1},
            ]
        }
        turns = grok.transcript_turns(response)
        self.assertEqual([turn["speaker"] for turn in turns], [0, 1])
        self.assertEqual(turns[0]["text"], "你好。")

    def test_auth_status_never_contains_token(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            auth_file = Path(temp) / "auth.json"
            auth_file.write_text(
                json.dumps({"xai::api_key": {"key": "dummy-test-token"}}),
                encoding="utf-8",
            )
            old = os.environ.pop("XAI_API_KEY", None)
            try:
                status = grok.auth_status("api-key", auth_file)
            finally:
                if old is not None:
                    os.environ["XAI_API_KEY"] = old
            self.assertTrue(status["available"])
            self.assertNotIn("dummy-test-token", json.dumps(status))

    def test_multipart_repeats_keyterm_field(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            audio = Path(temp) / "sample.mp3"
            audio.write_bytes(b"audio")
            body, _ = grok.multipart_body(
                {"format": "true", "keyterm": ["Grok", "产品名"]},
                "file",
                audio,
            )
            self.assertEqual(body.count(b'name="keyterm"'), 2)
            self.assertIn("产品名".encode("utf-8"), body)

    def test_minutes_output_is_not_used_for_intermediate_transcript(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            audio = root / "meeting.mp3"
            audio.write_bytes(b"audio")
            requested = root / "minutes.md"
            args = SimpleNamespace(
                file=audio,
                language="zh",
                diarize=True,
                keyterm=None,
                timeout=10,
                output=requested,
                overwrite=False,
                audio_operation="minutes",
            )
            response = {
                "text": "测试会议",
                "words": [
                    {"text": "测试", "start": 0, "end": 0.2, "speaker": 0},
                    {"text": "会议", "start": 0.2, "end": 0.5, "speaker": 0},
                ],
            }
            with mock.patch.object(grok, "http_multipart", return_value=response):
                grok.transcribe(
                    args,
                    grok.Credential("secret", "api_key", "test"),
                    grok.RunContext("test", root / "run"),
                )
            self.assertFalse(requested.exists())
            self.assertTrue((root / "run" / "transcript.md").exists())

    def test_cli_dry_run_works_without_credentials(self) -> None:
        completed = subprocess.run(
            [
                sys.executable,
                str(SCRIPT),
                "--dry-run",
                "image",
                "generate",
                "a paper boat",
            ],
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        output = json.loads(completed.stdout)
        self.assertTrue(output["dry_run"])
        self.assertEqual(output["module"], "image")
if __name__ == "__main__":
    unittest.main()
