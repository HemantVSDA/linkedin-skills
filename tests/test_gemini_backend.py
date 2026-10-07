"""Offline tests for the Google image backend.

Covers the Gemini client's request/response contract, backend selection, the
local-file publish path through Publora's upload flow, the brand layer and the
OCR text check's matching rules.

No credentials and no real network calls are used.
"""

from __future__ import annotations

import base64
import io
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from lib import backend_selector as bs
from lib.gemini_client import GeminiError, GeminiImageClient, _extract_image


def png_bytes(w: int = 40, h: int = 50) -> bytes:
    from PIL import Image

    buf = io.BytesIO()
    Image.new("RGB", (w, h), (40, 50, 100)).save(buf, "PNG")
    return buf.getvalue()


def gemini_response(raw: bytes, mime: str = "image/png") -> dict:
    return {
        "candidates": [{"content": {"parts": [
            {"inlineData": {"mimeType": mime, "data": base64.b64encode(raw).decode()}}]},
            "finishReason": "STOP"}],
        "modelVersion": "gemini-nano-banana-2.1",
    }


class ClientContract(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        with patch.dict(os.environ, {"GEMINI_API_KEY": "test"}):
            self.client = GeminiImageClient(output_dir=Path(self.tmp.name))

    def tearDown(self):
        self.tmp.cleanup()

    def test_missing_key_fails_with_setup_hint(self):
        with patch.dict(os.environ, {"GEMINI_API_KEY": ""}), patch("lib.gemini_client.load_env"):
            with self.assertRaisesRegex(GeminiError, "billing"):
                GeminiImageClient()

    @patch.object(GeminiImageClient, "_post")
    def test_generate_sends_image_config_and_saves_file(self, post):
        post.return_value = gemini_response(png_bytes())
        out = self.client.generate("a ledger", aspect_ratio="4:5", image_size="1K")

        path, body = post.call_args[0]
        self.assertEqual(path, "/models/gemini-nano-banana-2.1:generateContent")
        self.assertEqual(body["generationConfig"]["responseModalities"], ["IMAGE"])
        self.assertEqual(body["generationConfig"]["imageConfig"], {"aspectRatio": "4:5", "imageSize": "1K"})
        self.assertTrue(out["id"].startswith("gimg_"))
        self.assertTrue(Path(out["path"]).is_file())
        self.assertAlmostEqual(out["cost"], 0.0336)

    @patch.object(GeminiImageClient, "_post")
    def test_identical_generation_uses_cache(self, post):
        post.return_value = gemini_response(png_bytes())
        self.client.generate("same prompt")
        self.client.generate("same prompt")
        post.assert_called_once()

    @patch.object(GeminiImageClient, "_post")
    def test_bad_aspect_ratio_is_rejected_before_calling(self, post):
        with self.assertRaises(GeminiError):
            self.client.generate("x", aspect_ratio="1200:628")
        post.assert_not_called()

    @patch.object(GeminiImageClient, "_post")
    def test_edit_resends_the_source_image(self, post):
        post.return_value = gemini_response(png_bytes(40, 50))
        first = self.client.generate("scene")
        post.return_value = gemini_response(png_bytes(41, 50))
        src = Path(first["path"])
        with patch("lib.gemini_client.image_path_for", return_value=src):
            self.client.edit(first["id"], "make it darker")
        parts = post.call_args[0][1]["contents"][0]["parts"]
        self.assertIn("inlineData", parts[0])
        self.assertEqual(parts[1]["text"], "make it darker")
        # aspect ratio defaults to the source's own shape (40x50 -> 4:5)
        self.assertEqual(post.call_args[0][1]["generationConfig"]["imageConfig"]["aspectRatio"], "4:5")

    def test_text_only_answer_is_an_error_not_a_crash(self):
        resp = {"candidates": [{"content": {"parts": [{"text": "I can't draw that"}]}, "finishReason": "STOP"}]}
        with self.assertRaisesRegex(GeminiError, "no image returned"):
            _extract_image(resp)

    def test_blocked_prompt_names_the_reason(self):
        with self.assertRaisesRegex(GeminiError, "SAFETY"):
            _extract_image({"promptFeedback": {"blockReason": "SAFETY"}})


class BackendSelection(unittest.TestCase):
    def test_google_wins_over_pixfaro(self):
        with patch.dict(os.environ, {"GEMINI_API_KEY": "g", "PIXFARO_TOKEN": "pf_live_x"}):
            self.assertEqual(bs.image_backend(), "google")

    def test_pixfaro_still_works_without_google(self):
        with patch.dict(os.environ, {"GEMINI_API_KEY": "", "PIXFARO_TOKEN": "pf_live_x"}):
            self.assertEqual(bs.image_backend(), "pixfaro")

    def test_nothing_set_is_manual(self):
        with patch.dict(os.environ, {"GEMINI_API_KEY": "", "PIXFARO_TOKEN": "", "PIXFARO_API_KEY": ""}):
            self.assertEqual(bs.image_backend(), "manual")

    def test_split_media_separates_urls_from_files(self):
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
            f.write(png_bytes())
        try:
            remote, local = bs._split_media(["https://x/y.png", f.name])
            self.assertEqual(remote, ["https://x/y.png"])
            self.assertEqual(local, [f.name])
            with self.assertRaises(ValueError):
                bs._split_media(["not-a-file.png"])
        finally:
            os.unlink(f.name)


class PublishLocalImages(unittest.TestCase):
    """A local image goes through draft -> upload -> schedule, never as a URL."""

    def setUp(self):
        fd, self.img = tempfile.mkstemp(suffix=".png")
        os.write(fd, png_bytes())
        os.close(fd)

    def tearDown(self):
        os.unlink(self.img)

    def _publish(self, scheduled_time):
        client = MagicMock()
        client.create_post.return_value = {"success": True, "postGroupId": "pg1"}
        client.upload_file.return_value = {"fileUrl": "https://s3/x.png", "mediaId": "m1"}
        client.update_post.return_value = {"success": True}
        env = {"PUBLORA_API_KEY": "sk_x", "LINKEDIN_PLATFORM_ID": "linkedin-1"}
        with patch.dict(os.environ, env), patch("lib.publora_client.PubloraClient", return_value=client):
            out = bs.publish("post", "text", "https://www.linkedin.com/post/new/",
                             media_urls=[self.img], scheduled_time=scheduled_time)
        return client, out

    def test_local_file_is_uploaded_into_a_draft_then_scheduled(self):
        client, out = self._publish("2026-10-08T13:30:00Z")
        _, kwargs = client.create_post.call_args
        self.assertNotIn("scheduled_time", kwargs)          # created as a draft
        self.assertIsNone(kwargs["media_urls"])             # no local path sent as a URL
        client.upload_file.assert_called_once_with(path=self.img, post_group_id="pg1")
        client.update_post.assert_called_once_with(
            post_group_id="pg1", status="scheduled", scheduledTime="2026-10-08T13:30:00Z")
        self.assertEqual(len(out["uploaded"]), 1)

    def test_without_a_time_it_stays_a_draft(self):
        client, _ = self._publish(None)
        client.update_post.assert_not_called()

    def test_manual_tier_lists_files_to_attach(self):
        with patch.dict(os.environ, {"PUBLORA_API_KEY": "", "LINKEDIN_PLATFORM_ID": "",
                                     "LINKEDIN_SKILLS_CUSTOM_POSTER": ""}):
            out = bs.publish("post", "text", "https://www.linkedin.com/post/new/", media_urls=[self.img])
        self.assertIn(self.img, out["message"])


class BrandLayer(unittest.TestCase):
    def test_cards_are_portrait_by_default_and_reject_overflow(self):
        from PIL import Image
        from lib import brand_compose as bc

        with patch.dict(os.environ, {"BRAND_LOGO_PATH": ""}):
            q = bc.quote_card("Profit does not always equal cash.")
            with Image.open(q) as im:
                self.assertEqual(im.size, (1080, 1350))
            with self.assertRaises(ValueError):
                bc.text_card("h", [f"item {i}" for i in range(8)])
            with self.assertRaises(ValueError):
                bc.quote_card("x" * 281)


class TextCheckRules(unittest.TestCase):
    """Matching rules, with the OCR engine stubbed out."""

    def check(self, ocr, expected):
        from lib import text_check

        with patch.object(text_check, "ocr_lines", return_value=ocr):
            return text_check.verify("unused.png", expected)

    def test_exact_text_passes_even_when_ocr_drops_spaces(self):
        r = self.check(["5 records CRA asks for", "inanSR&EDreview"], ["5 records CRA asks for in an SR&ED review"])
        self.assertTrue(r["ok"])

    def test_one_wrong_digit_fails(self):
        r = self.check(["6 records CRA asks for in an SR&ED review"], ["5 records CRA asks for in an SR&ED review"])
        self.assertFalse(r["ok"])

    def test_plain_words_tolerate_a_single_ocr_slip(self):
        r = self.check(["Proof of the technical uncertalnty"], ["Proof of the technical uncertainty"])
        self.assertTrue(r["ok"])

    def test_a_stray_number_nobody_planned_fails(self):
        r = self.check(["Dated project notes", "Due 2026"], ["Dated project notes"])
        self.assertFalse(r["ok"])
        self.assertEqual(r["stray_numbers"], ["Due 2026"])

    def test_fix_instruction_names_only_the_failures(self):
        from lib.text_check import fix_instruction

        r = self.check(["Dated projct notes", "Timesheets"], ["Dated project notes", "Timesheets"])
        msg = fix_instruction(r)
        self.assertIn('"Dated project notes"', msg)
        self.assertNotIn('"Timesheets"', msg)


if __name__ == "__main__":
    unittest.main()
