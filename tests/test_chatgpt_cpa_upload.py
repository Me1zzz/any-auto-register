import unittest
from datetime import datetime, timezone, timedelta
from unittest import mock
import sys
import types

curl_cffi_stub = types.ModuleType("curl_cffi")
curl_cffi_stub.requests = types.SimpleNamespace(post=lambda *args, **kwargs: None)


class _StubCurlMime:
    def addpart(self, **kwargs):
        pass

    def close(self):
        pass


curl_cffi_stub.CurlMime = _StubCurlMime
sys.modules.setdefault("curl_cffi", curl_cffi_stub)

from platforms.chatgpt.cpa_upload import _build_cpa_upload_filename, upload_to_cpa


class ChatGPTCpaUploadTests(unittest.TestCase):
    def test_build_cpa_upload_filename_prefixes_mmdd(self):
        now = datetime(2026, 4, 9, 10, 0, tzinfo=timezone(timedelta(hours=8)))

        filename = _build_cpa_upload_filename("demo@example.com", now=now)

        self.assertEqual(filename, "0409demo@example.com.json")

    def test_upload_to_cpa_uses_date_prefixed_filename(self):
        token_data = {"email": "demo@example.com", "access_token": "at"}

        class _FakeMime:
            def __init__(self):
                self.parts = []

            def addpart(self, **kwargs):
                self.parts.append(kwargs)

            def close(self):
                pass

        fake_mime = _FakeMime()
        fake_response = mock.Mock(status_code=200)
        fixed_now = datetime(2026, 4, 9, 10, 0, tzinfo=timezone(timedelta(hours=8)))

        with mock.patch("platforms.chatgpt.cpa_upload.CurlMime", return_value=fake_mime), mock.patch(
            "platforms.chatgpt.cpa_upload.cffi_requests.post",
            return_value=fake_response,
        ), mock.patch("platforms.chatgpt.cpa_upload.datetime") as mock_datetime:
            mock_datetime.now.return_value = fixed_now
            ok, msg = upload_to_cpa(token_data, api_url="https://cpa.example.com", api_key="secret")

        self.assertTrue(ok)
        self.assertEqual(msg, "上传成功")
        self.assertEqual(fake_mime.parts[0]["filename"], "0409demo@example.com.json")


if __name__ == "__main__":
    unittest.main()
