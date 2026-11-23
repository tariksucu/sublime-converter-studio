import os
import unittest

from converterstudio import VERSION, api

from .fakes import BASE, KEY, FakeApi, client
from .helpers import TempDirTest


class SettingsTest(unittest.TestCase):
    def test_key_from_settings_first_then_the_environment(self):
        env = {"CONVERTER_STUDIO_API_KEY": " from-env "}
        self.assertEqual(api.api_key({"api_key": " k1 "}, env), "k1")
        self.assertEqual(api.api_key({"api_key": ""}, env), "from-env")
        self.assertEqual(api.api_key({}, {}), "")

    def test_base_url_must_be_https_except_on_this_computer(self):
        self.assertEqual(api.base_url({}), "https://converter.studio/api")
        self.assertEqual(api.base_url({"api_url": "https://x.example/api/"}), "https://x.example/api")
        self.assertEqual(api.base_url({"api_url": "http://localhost:4391/api"}), "http://localhost:4391/api")
        self.assertEqual(api.base_url({"api_url": "http://127.0.0.1:9/api"}), "http://127.0.0.1:9/api")
        for bad in ("http://converter.studio/api", "ftp://x/api", "converter.studio", "https://"):
            with self.assertRaises(api.ApiError) as caught:
                api.base_url({"api_url": bad})
            self.assertEqual(caught.exception.code, api.INSECURE_URL)


class ClientTest(TempDirTest):
    def test_headers_name_the_package_and_carry_the_key_only_to_the_api(self):
        c, fake = client()
        path = self.write("photo.heic", b"0123456789")
        upload = c.create_upload("photo.heic", 10)
        c.send_file(upload, path, 10)
        first = fake.requests[0]["headers"]
        self.assertEqual(first["X-Converter-Studio-Client"], "sublime-text/" + VERSION)
        self.assertIn("ConverterStudio-Sublime/" + VERSION, first["User-Agent"])
        self.assertIn("SublimeText/4215", first["User-Agent"])
        self.assertEqual(first["Authorization"], "Bearer " + KEY)
        puts = [r for r in fake.requests if r["method"] == "PUT"]
        self.assertEqual(len(puts), 3)  # parts of 4 bytes
        self.assertTrue(all("Authorization" not in r["headers"] for r in puts))
        self.assertEqual([r["headers"]["Upload-Offset"] for r in puts], ["0", "4", "8"])
        self.assertEqual(fake.uploads["up_1"]["data"], b"0123456789")

    def test_an_upload_resumes_where_the_api_says(self):
        c, fake = client()
        path = self.write("a.bin", b"abcdefgh")
        upload = c.create_upload("a.bin", 8)
        fake.uploads["up_1"]["data"] = b"abcd"  # a part arrived but its answer was lost
        c.send_file(upload, path, 8)
        self.assertEqual(fake.uploads["up_1"]["data"], b"abcdefgh")

    def test_an_upload_address_elsewhere_is_refused(self):
        c, fake = client()
        path = self.write("a.bin", b"abc")
        with self.assertRaises(api.ApiError) as caught:
            c.send_file({"uploadUrl": "https://evil.example/u"}, path, 3)
        self.assertEqual(caught.exception.code, api.UNEXPECTED_URL)
        with self.assertRaises(api.ApiError):
            c.download("http://converter.example/api/jobs/x", os.path.join(self.dir, "o"))
        self.assertEqual(fake.requests, [])

    def test_the_apis_error_message_is_kept_and_the_key_never_shows(self):
        c, fake = client(key="cvs_live_wrong")
        with self.assertRaises(api.ApiError) as caught:
            c.account()
        self.assertEqual(caught.exception.status, 401)
        self.assertEqual(caught.exception.code, "invalidApiKey")
        self.assertEqual(caught.exception.message, "This API key does not work.")
        self.assertNotIn("cvs_live_wrong", str(caught.exception))

    def test_no_key_no_request(self):
        c, fake = client(key="")
        with self.assertRaises(api.ApiError) as caught:
            c.account()
        self.assertEqual(caught.exception.code, api.NO_KEY)
        self.assertEqual(fake.requests, [])
        self.assertEqual(c.formats(), [{"id": "jpg"}])  # the list of formats needs none
        self.assertNotIn("Authorization", fake.requests[0]["headers"])

    def test_busy_and_unreachable_are_tried_again(self):
        waits = []
        fake = FakeApi()
        fake.queue = [
            (503, {"retry-after": "3"}, {"error": {"code": "serverBusy"}}),
            (0, {}, api.ApiError(0, api.NETWORK)),
        ]
        c, _ = client(fake, sleep=waits.append)
        self.assertEqual(c.account()["plan"], "pro")
        self.assertEqual(waits, [3.0, 2.0])

    def test_lasting_errors_are_not_tried_again(self):
        fake = FakeApi()
        fake.queue = [(402, {}, {"error": {"code": "notEnoughCredits", "message": "Not enough credits."}})]
        c, _ = client(fake)
        with self.assertRaises(api.ApiError) as caught:
            c.account()
        self.assertEqual(caught.exception.code, "notEnoughCredits")
        self.assertEqual(len(fake.requests), 1)

    def test_a_proxy_page_instead_of_json(self):
        fake = FakeApi()
        fake.queue = [(502, {}, b"<html>bad gateway</html>")] * 4
        c, _ = client(fake)
        with self.assertRaises(api.ApiError) as caught:
            c.account()
        self.assertEqual(caught.exception.code, "serverBusy")

    def test_conversion_uses_an_idempotency_key(self):
        c, fake = client()
        c.convert("up_1", "jpg", 20, "key-1")
        request = fake.requests[-1]
        self.assertEqual(request["headers"]["Idempotency-Key"], "key-1")
        self.assertEqual(fake.started, {"uploadId": "up_1", "to": "jpg", "maxCredits": 20})

    def test_download_checks_its_length(self):
        fake = FakeApi()
        c, _ = client(fake)
        out = os.path.join(self.dir, "out.jpg")
        self.assertEqual(c.download(BASE + "/jobs/cv_1/download?token=d", out), 8)
        fake.queue = [(200, {"content-length": "100"}, b"short")]
        with self.assertRaises(api.ApiError):
            c.download(BASE + "/jobs/cv_1/download?token=d", out)
        self.assertFalse(os.path.exists(out))


if __name__ == "__main__":
    unittest.main()
