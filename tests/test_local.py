import json
import os
import threading
import unittest

from converterstudio import local, recipes
from converterstudio.recipes import LOCAL, PAGES, PLAIN, Choice

from .helpers import PYTHON, TempDirTest, tool

FAKE_TOOL = """
import os, sys, time
args = sys.argv[1:]
mode = os.environ.get("FAKE_MODE", "one")
out = args[-1]
for arg in args:
    if arg.startswith("-sOutputFile="):
        out = arg.split("=", 1)[1]
if mode == "fail":
    sys.stderr.write("Invalid data found when processing input\\n")
    sys.exit(1)
if mode == "nothing":
    sys.exit(0)
if mode == "slow":
    time.sleep(60)
if mode == "pages":
    folder = os.path.dirname(out)
    for n in (1, 2, 3):
        open(os.path.join(folder, "doc-page-%03d.png" % n), "wb").write(b"\\x89PNG")
    sys.exit(0)
open(out, "wb").write(b"converted")
"""


class LocalTest(TempDirTest):
    def setUp(self):
        super().setUp()
        script = self.write("fake_tool.py", FAKE_TOOL)
        # A stand-in for a tool: a small Python program run through a wrapper script.
        if os.name == "nt":
            self.exe = self.write("fake.bat", '@"%s" "%s" %%*\r\n' % (PYTHON, script))
        else:
            self.exe = self.write("fake.sh", '#!/bin/sh\nexec "%s" "%s" "$@"\n' % (PYTHON, script))
            os.chmod(self.exe, 0o700)
        self.src_dir = os.path.join(self.dir, "src")
        os.mkdir(self.src_dir)

    def source(self, name, data=b"input"):
        path = os.path.join(self.src_dir, name)
        with open(path, "wb") as handle:
            handle.write(data)
        return path

    def found(self, tool_id):
        return {tool_id: tool(tool_id, path=self.exe, features=["libmp3lame"])}

    def convert(self, choice, path, mode="one", **settings):
        os.environ["FAKE_MODE"] = mode
        self.addCleanup(os.environ.pop, "FAKE_MODE", None)
        settings.setdefault("timeout_seconds", 30)
        return local.convert(choice, path, self.found(choice.tool), settings)

    def test_the_result_lands_next_to_the_source_without_overwriting(self):
        path = self.source("clip.mp4")
        self.source("clip.mp3", b"keep me")
        written = self.convert(Choice("mp4", "mp3", LOCAL, "ffmpeg"), path)
        self.assertEqual([os.path.basename(p) for p in written], ["clip (2).mp3"])
        with open(os.path.join(self.src_dir, "clip.mp3"), "rb") as handle:
            self.assertEqual(handle.read(), b"keep me")

    def test_a_failing_tool_gives_its_last_lines(self):
        with self.assertRaises(local.LocalFailure) as caught:
            self.convert(Choice("mp4", "mp3", LOCAL, "ffmpeg"), self.source("clip.mp4"), mode="fail")
        self.assertIn("FFmpeg could not convert the file (exit code 1)", caught.exception.message)
        self.assertIn("Invalid data", caught.exception.details)
        self.assertEqual(sorted(os.listdir(self.src_dir)), ["clip.mp4"])

    def test_a_tool_that_writes_nothing_is_a_failure(self):
        with self.assertRaises(local.LocalFailure) as caught:
            self.convert(Choice("mp4", "mp3", LOCAL, "ffmpeg"), self.source("clip.mp4"), mode="nothing")
        self.assertIn("without writing a MP3 file", caught.exception.message)

    def test_timeout(self):
        with self.assertRaises(local.LocalFailure) as caught:
            self.convert(Choice("mp4", "mp3", LOCAL, "ffmpeg"), self.source("clip.mp4"), mode="slow", timeout_seconds=1)
        self.assertIn("did not finish in 1 seconds", caught.exception.message)

    def test_cancel_saves_nothing(self):
        flag = threading.Event()
        threading.Timer(0.8, flag.set).start()
        os.environ["FAKE_MODE"] = "slow"
        self.addCleanup(os.environ.pop, "FAKE_MODE", None)
        with self.assertRaises(local.Canceled):
            local.convert(
                Choice("mp4", "mp3", LOCAL, "ffmpeg"),
                self.source("clip.mp4"),
                self.found("ffmpeg"),
                {"timeout_seconds": 30},
                cancelled=flag.is_set,
            )
        self.assertEqual(os.listdir(self.src_dir), ["clip.mp4"])

    def test_several_pages_go_into_one_folder(self):
        written = self.convert(Choice("pdf", "png", LOCAL, "gs", PAGES), self.source("doc.pdf"), mode="pages")
        self.assertEqual(len(written), 1)
        self.assertEqual(os.path.basename(written[0]), "doc (PNG pages)")
        self.assertEqual(len(os.listdir(written[0])), 3)

    def test_python_conversion_needs_no_tool(self):
        path = self.source("t.csv", b"a,b\n1,2\n")
        written = local.convert(Choice("csv", "json", LOCAL, "python"), path, {}, {})
        with open(written[0], encoding="utf-8") as handle:
            self.assertEqual(json.load(handle), [{"a": "1", "b": "2"}])

    def test_python_conversion_error_is_a_failure(self):
        with self.assertRaises(local.LocalFailure) as caught:
            local.convert(Choice("json", "csv", LOCAL, "python"), self.source("x.json", b"{"), {}, {})
        self.assertIn("not valid JSON", caught.exception.message)

    def test_a_missing_tool_is_named(self):
        with self.assertRaises(local.LocalFailure) as caught:
            local.convert(Choice("md", "pdf", LOCAL, "pandoc+soffice"), self.source("n.md"), {}, {})
        self.assertIn("Pandoc is not available", caught.exception.message)

    def test_work_folders_are_removed(self):
        import tempfile

        before = set(os.listdir(tempfile.gettempdir()))
        self.convert(Choice("mp4", "mp3", LOCAL, "ffmpeg"), self.source("clip.mp4"))
        after = set(os.listdir(tempfile.gettempdir()))
        self.assertFalse([n for n in after - before if n.startswith("converter-studio-")])

    def test_labels(self):
        self.assertEqual(recipes.TOOL_NAMES["pandoc+soffice"], "Pandoc and LibreOffice")
        self.assertEqual(Choice("png", "jpg", LOCAL, "magick", PLAIN).label, "JPG")


if __name__ == "__main__":
    unittest.main()
