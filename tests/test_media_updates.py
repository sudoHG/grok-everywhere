from __future__ import annotations

import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "grok-everywhere" / "scripts" / "grok.py"
SPEC = importlib.util.spec_from_file_location("grok_everywhere_media_tests", SCRIPT)
assert SPEC and SPEC.loader
grok = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = grok
SPEC.loader.exec_module(grok)


class MediaUpdateTests(unittest.TestCase):
    def test_image_generation_accepts_api_batch_and_auto_quality(self) -> None:
        args = grok.build_parser().parse_args(
            ["--dry-run", "image", "generate", "A quiet forest", "--n", "10", "--quality", "auto"]
        )
        result = grok.command_image(args)
        self.assertEqual(result["request"]["model"], "grok-imagine-image-2.0")
        self.assertEqual(result["request"]["n"], 10)
        self.assertEqual(result["request"]["quality"], "auto")

    def test_image_edit_emits_multi_image_rest_shape_and_controls(self) -> None:
        command = [
            "--dry-run",
            "image",
            "edit",
            "https://example.test/one.png",
            "Combine the subjects",
            "--reference-image",
            "https://example.test/two.png",
            "--aspect-ratio",
            "5:2",
            "--resolution",
            "2k",
            "--quality",
            "auto",
        ]
        request = grok.command_image(grok.build_parser().parse_args(command))["request"]
        self.assertEqual(
            request["images"],
            [
                {"url": "https://example.test/one.png", "type": "image_url"},
                {"url": "https://example.test/two.png", "type": "image_url"},
            ],
        )
        self.assertEqual(request["aspect_ratio"], "5:2")
        self.assertEqual(request["resolution"], "2k")
        self.assertEqual(request["quality"], "auto")

    def test_image_edit_rejects_more_than_five_sources(self) -> None:
        command = ["--dry-run", "image", "edit", "one.png", "Combine"]
        for index in range(5):
            command.extend(["--reference-image", "{}.png".format(index)])
        args = grok.build_parser().parse_args(command)
        with self.assertRaisesRegex(grok.GrokError, "at most five"):
            grok.command_image(args)

    def test_video_15_reference_payload_matches_rest_shape(self) -> None:
        args = grok.build_parser().parse_args(
            [
                "--dry-run",
                "video",
                "generate",
                "Place the subject in a night scene",
                "--image",
                "https://example.test/first.jpg",
                "--reference-image",
                "https://example.test/wardrobe.jpg",
                "--last-frame",
                "https://example.test/last.jpg",
                "--keyframe",
                "3.0=https://example.test/middle.jpg",
                "--reference-voice",
                "eve",
            ]
        )
        endpoint, payload = grok.video_payload(args)
        self.assertEqual(endpoint, "videos/generations")
        self.assertEqual(payload["model"], "grok-imagine-video-1.5")
        self.assertEqual(payload["image"], {"url": "https://example.test/first.jpg"})
        self.assertEqual(
            payload["reference_images"],
            [{"url": "https://example.test/wardrobe.jpg"}],
        )
        self.assertEqual(payload["last_frame"], {"url": "https://example.test/last.jpg"})
        self.assertEqual(
            payload["keyframes"],
            [
                {
                    "image": {"url": "https://example.test/middle.jpg"},
                    "timestamp_s": 3.0,
                }
            ],
        )
        self.assertEqual(payload["reference_audios"], [{"voice_id": "eve"}])

    def test_classic_video_preserves_three_references_but_rejects_new_pins(self) -> None:
        parser = grok.build_parser()
        args = parser.parse_args(
            [
                "--dry-run",
                "video",
                "generate",
                "Classic reference shot",
                "--model",
                "grok-imagine-video",
                "--reference-image",
                "https://example.test/one.jpg",
                "--reference-image",
                "https://example.test/two.jpg",
                "--reference-image",
                "https://example.test/three.jpg",
            ]
        )
        _, payload = grok.video_payload(args)
        self.assertEqual(len(payload["reference_images"]), 3)
        args.last_frame = "https://example.test/last.jpg"
        with self.assertRaisesRegex(grok.GrokError, "not supported"):
            grok.video_payload(args)

        args.last_frame = None
        args.reference_image.append("https://example.test/four.jpg")
        with self.assertRaisesRegex(grok.GrokError, "At most 3"):
            grok.video_payload(args)

        classic_1080p = parser.parse_args(
            [
                "--dry-run",
                "video",
                "generate",
                "Classic shot",
                "--model",
                "grok-imagine-video",
                "--resolution",
                "1080p",
            ]
        )
        with self.assertRaisesRegex(grok.GrokError, "only for Video 1.5"):
            grok.video_payload(classic_1080p)

    def test_reference_video_rejects_1080p_and_keyframe_outside_duration(self) -> None:
        parser = grok.build_parser()
        high_res = parser.parse_args(
            [
                "--dry-run",
                "video",
                "generate",
                "Reference shot",
                "--reference-image",
                "reference.jpg",
                "--resolution",
                "1080p",
            ]
        )
        with self.assertRaisesRegex(grok.GrokError, "must use 720p"):
            grok.video_payload(high_res)

        outside = parser.parse_args(
            [
                "--dry-run",
                "video",
                "generate",
                "Reference shot",
                "--duration",
                "5",
                "--keyframe",
                "5=frame.jpg",
            ]
        )
        with self.assertRaisesRegex(grok.GrokError, "strictly inside"):
            grok.video_payload(outside)

    def test_video_can_omit_prompt_when_an_image_is_pinned(self) -> None:
        args = grok.build_parser().parse_args(
            [
                "--dry-run",
                "video",
                "generate",
                "--image",
                "https://example.test/first.png",
            ]
        )
        _, payload = grok.video_payload(args)
        self.assertNotIn("prompt", payload)
        self.assertEqual(payload["image"], {"url": "https://example.test/first.png"})

    def test_edit_and_extend_defaults_match_documented_classic_slug(self) -> None:
        parser = grok.build_parser()
        self.assertEqual(
            parser.parse_args(["video", "edit", "source.mp4", "Rainy night"]).model,
            "grok-imagine-video",
        )
        self.assertEqual(
            parser.parse_args(["video", "extend", "source.mp4", "Continue"]).model,
            "grok-imagine-video",
        )
        self.assertEqual(
            parser.parse_args(
                ["video", "edit", "source.mp4", "Rainy night", "--model", "custom-video"]
            ).model,
            "custom-video",
        )

    def test_video_get_performs_one_get_and_preserves_status(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            args = grok.build_parser().parse_args(
                [
                    "--cache-dir",
                    temporary,
                    "video",
                    "get",
                    "request-123",
                ]
            )
            credential = grok.Credential("test-token", "api_key", "test")
            with mock.patch.object(grok, "load_credential", return_value=credential), mock.patch.object(
                grok,
                "http_json",
                return_value={"status": "pending", "progress": 20, "model": "video-model"},
            ) as request:
                result = grok.command_video(args)
            request.assert_called_once_with(
                "GET", "videos/request-123", credential, args.timeout
            )
            self.assertEqual(result["status"], "pending")
            self.assertEqual(result["progress"], 20)

    def test_video_resume_polls_and_downloads_without_post(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            args = grok.build_parser().parse_args(
                ["--cache-dir", temporary, "video", "resume", "request-456"]
            )
            credential = grok.Credential("test-token", "api_key", "test")
            responses = [
                {"status": "pending", "progress": 40},
                {
                    "status": "done",
                    "model": "video-model",
                    "video": {"url": "https://example.test/result.mp4", "duration": 8},
                    "usage": {"cost_in_usd_ticks": 10_000_000_000},
                },
            ]

            def fake_download(url: str, destination: Path, timeout: int) -> Path:
                destination.write_bytes(b"mock-video")
                return destination

            with mock.patch.object(grok, "load_credential", return_value=credential), mock.patch.object(
                grok, "http_json", side_effect=responses
            ) as request, mock.patch.object(grok.time, "sleep"), mock.patch.object(
                grok, "download_url", side_effect=fake_download
            ):
                result = grok.command_video(args)
            self.assertEqual(request.call_count, 2)
            self.assertTrue(all(call.args[0] == "GET" for call in request.call_args_list))
            self.assertEqual(result["operation"], "resume")
            self.assertEqual(result["request_id"], "request-456")
            self.assertTrue(Path(result["artifacts"][0]).is_file())
            self.assertEqual(Path(result["artifacts"][0]).read_bytes(), b"mock-video")

    def test_failed_video_status_redacts_the_active_token(self) -> None:
        credential = grok.Credential("private-token-value", "api_key", "test")
        with mock.patch.object(
            grok,
            "http_json",
            return_value={"status": "failed", "error": "bad private-token-value"},
        ):
            with self.assertRaises(grok.GrokError) as raised:
                grok.poll_video(credential, "request-789", 10, 1, 0.25)
        self.assertNotIn("private-token-value", str(raised.exception))

    def test_output_directory_is_rejected_even_with_overwrite(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            with self.assertRaisesRegex(grok.GrokError, "is a directory"):
                grok.preflight_output_path(Path(temporary), overwrite=True)

            args = grok.build_parser().parse_args(
                [
                    "image",
                    "generate",
                    "Two images",
                    "--n",
                    "2",
                    "--output",
                    temporary,
                    "--overwrite",
                ]
            )
            with self.assertRaisesRegex(grok.GrokError, "is a directory"):
                grok.preflight_image_outputs(args)

    def test_existing_output_is_rejected_before_image_or_video_request(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "existing.png"
            output.write_bytes(b"keep")
            parser = grok.build_parser()
            image_args = parser.parse_args(
                [
                    "image",
                    "generate",
                    "A paper boat",
                    "--output",
                    str(output),
                ]
            )
            with mock.patch.object(grok, "load_credential") as load_auth, mock.patch.object(
                grok, "http_json"
            ) as request:
                with self.assertRaisesRegex(grok.GrokError, "Output exists"):
                    grok.command_image(image_args)
                load_auth.assert_not_called()
                request.assert_not_called()

            video_args = parser.parse_args(
                [
                    "video",
                    "generate",
                    "A paper boat",
                    "--output",
                    str(output),
                ]
            )
            with mock.patch.object(grok, "load_credential") as load_auth, mock.patch.object(
                grok, "http_json"
            ) as request:
                with self.assertRaisesRegex(grok.GrokError, "Output exists"):
                    grok.command_video(video_args)
                load_auth.assert_not_called()
                request.assert_not_called()


    def test_parent_file_is_rejected_before_paid_request(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            parent = Path(temporary) / "not-a-directory"
            parent.write_bytes(b"preserve")
            for module in ("image", "video"):
                args = grok.build_parser().parse_args([
                    module, "generate", "test", "--output", str(parent / "result.bin"),
                    "--overwrite",
                ])
                with self.subTest(module=module), mock.patch.object(grok, "load_credential") as auth, mock.patch.object(grok, "http_json") as request:
                    with self.assertRaisesRegex(grok.GrokError, "Cannot prepare output directory"):
                        getattr(grok, "command_" + module)(args)
                    auth.assert_not_called()
                    request.assert_not_called()
            self.assertEqual(parent.read_bytes(), b"preserve")


if __name__ == "__main__":
    unittest.main()
