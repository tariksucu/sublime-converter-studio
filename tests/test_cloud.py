import os
import unittest

from converterstudio import api, cloud

from .fakes import KEY, FakeApi, client
from .helpers import TempDirTest


class CloudTest(TempDirTest):
    def run_cloud(self, fake=None, confirm=None, cancelled=None, name="photo.heic"):
        c, fake = client(fake)
        path = self.write(name, b"heic bytes")
        steps = []
        written = cloud.run(
            c,
            path,
            "jpg",
            20,
            progress=lambda step, done, total: steps.append(step),
            cancelled=cancelled,
            confirm=confirm,
            poll_wait=0,
        )
        return written, fake, steps

    def test_upload_convert_wait_download(self):
        fake = FakeApi()
        fake.statuses = ["processing", "done"]
        written, fake, steps = self.run_cloud(fake)
        self.assertEqual(os.path.basename(written), "photo.jpg")
        with open(written, "rb") as handle:
            self.assertEqual(handle.read(), b"JPEGDATA")
        self.assertEqual(sorted(set(steps)), [cloud.CONVERT, cloud.DOWNLOAD, cloud.UPLOAD])
        self.assertEqual(fake.uploads["up_1"]["data"], b"heic bytes")

    def test_never_overwrites(self):
        self.write("photo.jpg", b"mine")
        written, _, _ = self.run_cloud()
        self.assertEqual(os.path.basename(written), "photo (2).jpg")

    def test_the_apis_output_name_is_kept(self):
        fake = FakeApi()
        fake.output_name = "photo-pages.zip"
        written, _, _ = self.run_cloud(fake)
        self.assertEqual(os.path.basename(written), "photo-pages.zip")

    def test_a_price_above_the_limit_asks_and_no_means_nothing_is_charged(self):
        fake = FakeApi()
        fake.quoted = True
        fake.price = 30
        asked = []
        with self.assertRaises(api.Canceled):
            self.run_cloud(fake, confirm=lambda credits: asked.append(credits) or False)
        self.assertEqual(asked, [30])
        self.assertFalse(fake.confirmed)
        self.assertEqual(sorted(os.listdir(self.dir)), ["photo.heic"])

    def test_yes_goes_ahead(self):
        fake = FakeApi()
        fake.quoted = True
        written, fake, _ = self.run_cloud(fake, confirm=lambda credits: True)
        self.assertTrue(fake.confirmed)
        self.assertTrue(os.path.exists(written))

    def test_a_failed_conversion_gives_the_apis_message(self):
        fake = FakeApi()
        fake.statuses = ["failed"]
        with self.assertRaises(api.ApiError) as caught:
            self.run_cloud(fake)
        self.assertEqual(cloud.message(caught.exception), "This file could not be converted.")

    def test_a_refused_conversion(self):
        fake = FakeApi()
        fake.fail_with = (422, {"error": {"code": "unsupportedConversion", "message": "We can't convert heic to mp3."}})
        with self.assertRaises(api.ApiError) as caught:
            self.run_cloud(fake)
        self.assertEqual(caught.exception.status, 422)
        self.assertIn("can't convert", cloud.message(caught.exception))

    def test_cancel_between_steps(self):
        calls = []

        def cancelled():
            calls.append(1)
            return len(calls) > 2

        with self.assertRaises(api.Canceled):
            self.run_cloud(cancelled=cancelled)
        self.assertEqual(sorted(os.listdir(self.dir)), ["photo.heic"])

    def test_an_empty_file_is_not_uploaded(self):
        c, fake = client()
        path = self.write("empty.png", b"")
        with self.assertRaises(api.ApiError):
            cloud.run(c, path, "jpg", 20)
        self.assertEqual(fake.requests, [])

    def test_messages_for_our_own_codes_never_hold_the_key(self):
        for code in (
            api.NO_KEY,
            api.INSECURE_URL,
            api.NETWORK,
            api.TLS,
            api.UNEXPECTED_URL,
            "invalidApiKey",
            "notEnoughCredits",
            "fileExpired",
            "somethingNew",
        ):
            text = cloud.message(api.ApiError(0, code))
            self.assertTrue(text.endswith("."), code)
            self.assertNotIn(KEY, text)
        self.assertIn("CONVERTER_STUDIO_API_KEY", cloud.message(api.ApiError(0, api.NO_KEY)))


if __name__ == "__main__":
    unittest.main()
