from __future__ import annotations

import base64
import importlib.util
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "grok-everywhere" / "scripts" / "grok.py"
SPEC = importlib.util.spec_from_file_location("grok_everywhere_audio_tests", SCRIPT)
assert SPEC and SPEC.loader
grok = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = grok
SPEC.loader.exec_module(grok)


class AudioUpdateTests(unittest.TestCase):
    def parse(self, *args: str):
        return grok.build_parser().parse_args(list(args))

    def test_tts_payload_options_tags_and_codec_accept(self) -> None:
        text = "Hello [laugh] <whisper>Grok</whisper>"
        args = self.parse(
            "--dry-run",
            "audio",
            "tts",
            text,
            "--language",
            "en",
            "--codec",
            "ulaw",
            "--sample-rate",
            "8000",
            "--speed",
            "1.2",
            "--optimize-streaming-latency",
            "2",
            "--no-text-normalization",
            "--replace",
            "xAI=ex eye",
        )

        payload = grok.command_tts(args)["request"]

        self.assertEqual(payload["text"], text)
        self.assertEqual(payload["voice_id"], "eve")
        self.assertEqual(
            payload["output_format"], {"codec": "mulaw", "sample_rate": 8000}
        )
        self.assertEqual(payload["speed"], 1.2)
        self.assertEqual(payload["optimize_streaming_latency"], 2)
        self.assertIs(payload["text_normalization"], False)
        self.assertEqual(payload["replace"], {"xAI": "ex eye"})
        self.assertEqual(grok.audio_accept_for_payload(payload), "audio/basic")
        self.assertEqual(
            grok.audio_accept_for_payload({"output_format": {"codec": "wav"}}),
            "audio/wav",
        )
        self.assertEqual(grok.audio_accept_for_payload({}), "audio/mpeg")
        self.assertEqual(
            grok.audio_accept_for_payload({"with_timestamps": True}),
            "application/json",
        )
        custom_voice = self.parse(
            "--dry-run",
            "audio",
            "tts",
            "Hello",
            "--voice",
            "custom-voice-id",
            "--text-normalization",
        )
        custom_payload = grok.command_tts(custom_voice)["request"]
        self.assertEqual(custom_payload["voice_id"], "custom-voice-id")
        self.assertIs(custom_payload["text_normalization"], True)

    def test_tts_character_limit_and_option_validation(self) -> None:
        self.assertEqual(
            grok.audio_tts_payload(
                self.parse("--dry-run", "audio", "tts", "x" * 60_000)
            )["text"],
            "x" * 60_000,
        )
        with self.assertRaises(grok.GrokError):
            grok.audio_tts_payload(
                self.parse("--dry-run", "audio", "tts", "x" * 60_001)
            )
        with self.assertRaises(grok.GrokError):
            grok.audio_tts_payload(
                self.parse("--dry-run", "audio", "tts", "hello", "--speed", "1.6")
            )
        with self.assertRaises(grok.GrokError):
            grok.audio_tts_payload(
                self.parse(
                    "--dry-run",
                    "audio",
                    "tts",
                    "hello",
                    "--codec",
                    "wav",
                    "--bit-rate",
                    "96000",
                )
            )

    def test_tts_timestamp_envelope_decodes_and_saves_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            output = root / "speech.wav"
            envelope = {
                "audio": base64.b64encode(b"wav-audio").decode("ascii"),
                "content_type": "audio/wav",
                "duration": 1.25,
                "audio_timestamps": {
                    "graph_chars": ["H", "i"],
                    "graph_times": [[0.0, 0.4], [0.4, 0.8]],
                },
            }
            args = self.parse(
                "--cache-dir",
                str(root / "cache"),
                "audio",
                "tts",
                "Hi",
                "--language",
                "en",
                "--codec",
                "wav",
                "--with-timestamps",
                "--output",
                str(output),
            )
            credential = grok.Credential("test-only", "api_key", "mock")
            with (
                mock.patch.object(grok, "load_credential", return_value=credential),
                mock.patch.object(
                    grok,
                    "http_raw_json_post",
                    return_value=(json.dumps(envelope).encode("utf-8"), "application/json"),
                ) as post,
            ):
                result = grok.command_tts(args)

            self.assertEqual(post.call_args.args[4], "application/json")
            self.assertEqual(output.read_bytes(), b"wav-audio")
            timestamp_path = Path(result["timestamps_path"])
            metadata = json.loads(timestamp_path.read_text(encoding="utf-8"))
            self.assertEqual(metadata["duration"], 1.25)
            self.assertNotIn("audio", metadata)
            self.assertIn(str(timestamp_path), result["artifacts"])

            raw_output = root / "raw.wav"
            raw_args = self.parse(
                "--cache-dir",
                str(root / "raw-cache"),
                "audio",
                "tts",
                "raw response",
                "--language",
                "en",
                "--codec",
                "wav",
                "--output",
                str(raw_output),
            )
            with (
                mock.patch.object(grok, "load_credential", return_value=credential),
                mock.patch.object(
                    grok, "http_raw_json_post", return_value=(b"raw-wav", "audio/wav")
                ) as post,
            ):
                grok.command_tts(raw_args)
            self.assertEqual(post.call_args.args[4], "audio/wav")
            self.assertEqual(raw_output.read_bytes(), b"raw-wav")

    def test_stt_model_options_format_raw_audio_and_language_auto(self) -> None:
        args = self.parse(
            "--dry-run",
            "audio",
            "transcribe",
            "meeting.pcm",
            "--stt-model",
            "grok-voice-transcribe-1.0",
            "--language",
            "en",
            "--format",
            "--audio-format",
            "pcm",
            "--sample-rate",
            "16000",
            "--multichannel",
            "--channels",
            "2",
            "--diarize",
            "--filler-words",
            "--keyterm",
            "Acme",
            "--vad-threshold",
            "0.25",
        )

        fields = grok.command_transcribe(args)["request"]["fields"]

        self.assertEqual(fields["model"], "grok-voice-transcribe-1.0")
        self.assertEqual(fields["audio_format"], "pcm")
        self.assertEqual(fields["sample_rate"], 16000)
        self.assertEqual(fields["language"], "en")
        self.assertEqual(fields["format"], "true")
        self.assertEqual(fields["multichannel"], "true")
        self.assertEqual(fields["channels"], 2)
        self.assertEqual(fields["diarize"], "true")
        self.assertEqual(fields["filler_words"], "true")
        self.assertEqual(fields["keyterm"], ["Acme"])
        self.assertEqual(fields["vad_threshold"], 0.25)

        automatic = self.parse(
            "--dry-run", "audio", "transcribe", "meeting.mp3", "--language", "auto"
        )
        self.assertNotIn("language", grok.command_transcribe(automatic)["request"]["fields"])
        with self.assertRaises(grok.GrokError):
            grok.audio_stt_fields(
                self.parse("--dry-run", "audio", "transcribe", "meeting.mp3", "--format")
            )

    def test_transcript_without_diarization_has_no_unknown_speaker(self) -> None:
        markdown, turns = grok.render_transcript(
            {"text": "hello", "words": [{"word": "hello", "start": 0, "end": 0.5}]}
        )
        self.assertIsNone(turns[0]["speaker"])
        self.assertIn("**Transcript**", markdown)
        self.assertNotIn("Speaker unknown", markdown)

    def test_multichannel_speakers_are_counted_per_channel_and_null_is_safe(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            audio_path = root / "meeting.wav"
            audio_path.write_bytes(b"audio-fixture")
            args = self.parse(
                "--cache-dir", str(root / "cache"), "audio", "transcribe", str(audio_path)
            )
            credential = grok.Credential("test-only", "api_key", "mock")
            channel_response = {
                "channels": [
                    {"index": 0, "text": "left", "words": [{"word": "left", "speaker": 0}]},
                    {"index": 1, "text": "right", "words": [{"word": "right", "speaker": 0}]},
                ]
            }
            with (
                mock.patch.object(grok, "load_credential", return_value=credential),
                mock.patch.object(grok, "http_multipart", return_value=channel_response),
            ):
                result = grok.command_transcribe(args)
            self.assertEqual(result["speaker_count"], 2)
            self.assertEqual(result["channel_count"], 2)

            args = self.parse(
                "--cache-dir", str(root / "cache"), "audio", "transcribe", str(audio_path)
            )
            with (
                mock.patch.object(grok, "load_credential", return_value=credential),
                mock.patch.object(grok, "http_multipart", return_value={"text": "no channels", "channels": None}),
            ):
                result = grok.command_transcribe(args)
            self.assertEqual(result["speaker_count"], 0)
            self.assertEqual(result["channel_count"], 0)

    def test_minutes_uses_independent_stt_and_summary_models_and_keeps_transcript(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            audio_path = root / "meeting.wav"
            audio_path.write_bytes(b"audio-fixture")
            minutes_path = root / "minutes.md"
            args = self.parse(
                "--cache-dir",
                str(root / "cache"),
                "audio",
                "minutes",
                str(audio_path),
                "--stt-model",
                "grok-voice-transcribe-1.0",
                "--language",
                "zh",
                "--model",
                "grok-4.7",
                "--output",
                str(minutes_path),
            )
            stt_response = {
                "text": "我们下周发布。",
                "language": "zh",
                "duration": 1.2,
                "words": [
                    {"text": "我们", "start": 0.0, "end": 0.4, "speaker": 0},
                    {"text": "下周发布。", "start": 0.4, "end": 1.0, "speaker": 0},
                ],
            }
            completion = {
                "choices": [
                    {"message": {"content": "# Meeting summary\n下周发布。"}}
                ],
                "usage": {},
            }
            credential = grok.Credential("test-only", "api_key", "mock")
            with (
                mock.patch.object(grok, "load_credential", return_value=credential),
                mock.patch.object(grok, "http_multipart", return_value=stt_response) as stt,
                mock.patch.object(grok, "http_json", return_value=completion) as chat,
            ):
                result = grok.command_minutes(args)

            stt_fields = stt.call_args.args[2]
            chat_payload = chat.call_args.args[4]
            self.assertEqual(stt_fields["model"], "grok-voice-transcribe-1.0")
            self.assertEqual(stt_fields["diarize"], "true")
            self.assertEqual(chat_payload["model"], "grok-4.7")
            self.assertNotEqual(stt_fields["model"], chat_payload["model"])
            self.assertTrue(minutes_path.exists())
            run_dir = Path(result["result_path"])
            transcript_path = run_dir / "transcript.md"
            self.assertTrue(transcript_path.exists())
            self.assertIn("我们下周发布。", transcript_path.read_text(encoding="utf-8"))
            self.assertEqual(minutes_path.read_text(encoding="utf-8"), completion["choices"][0]["message"]["content"])
            request_record = json.loads((run_dir / "request.json").read_text(encoding="utf-8"))
            minutes_request = json.loads((run_dir / "minutes-request.json").read_text(encoding="utf-8"))
            self.assertEqual(request_record["stt_fields"]["model"], "grok-voice-transcribe-1.0")
            self.assertEqual(minutes_request["model"], "grok-4.7")

    def test_minutes_summary_model_defaults_to_environment_or_grok_4_6(self) -> None:
        with mock.patch.dict(os.environ, {"XAI_TEXT_MODEL": ""}):
            parser = grok.build_parser()
        args = parser.parse_args(["audio", "minutes", "meeting.wav"])
        self.assertEqual(args.model, "grok-4.6")
        self.assertEqual(args.stt_model, "grok-voice-transcribe-2.0")

    def test_audio_outputs_are_preflighted_before_paid_calls(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            input_path = root / "meeting.wav"
            input_path.write_bytes(b"audio")
            existing = root / "exists.md"
            existing.write_text("keep", encoding="utf-8")
            cache = root / "cache"
            credential = grok.Credential("test-only", "api_key", "mock")

            cases = (
                ["--cache-dir", str(cache), "audio", "tts", "Hello", "--output", str(existing)],
                ["--cache-dir", str(cache), "audio", "transcribe", str(input_path), "--output", str(existing)],
                ["--cache-dir", str(cache), "audio", "minutes", str(input_path), "--output", str(existing)],
            )
            for argv in cases:
                with self.subTest(argv=argv), mock.patch.object(
                    grok, "load_credential", return_value=credential
                ) as load, mock.patch.object(grok, "http_raw_json_post") as tts, mock.patch.object(
                    grok, "http_multipart"
                ) as stt, mock.patch.object(grok, "http_json") as chat:
                    with self.assertRaises(grok.GrokError):
                        grok.dispatch(grok.build_parser().parse_args(argv))
                    load.assert_not_called()
                    tts.assert_not_called()
                    stt.assert_not_called()
                    chat.assert_not_called()
            self.assertEqual(existing.read_text(encoding="utf-8"), "keep")


if __name__ == "__main__":
    unittest.main()
