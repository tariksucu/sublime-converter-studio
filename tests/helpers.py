"""Shared fakes for the unit tests."""

import os
import shutil
import sys
import tempfile
import unittest

from converterstudio.tools import Tool

# The Python that runs helper programs in tests (inside Sublime Text, sys.executable is its
# plugin host, so the harness names a real Python).
PYTHON = os.environ.get("CS_TEST_PYTHON") or sys.executable


def tool(tool_id, path=None, features=(), formats=None, version="1.0", problem=None):
    found = Tool(tool_id, path or "/usr/bin/" + tool_id, version=version, problem=problem)
    found.features = set(features)
    found.formats = dict(formats or {})
    return found


FFMPEG_ALL = (
    "libx264",
    "aac",
    "libvpx-vp9",
    "libopus",
    "gif",
    "libmp3lame",
    "pcm_s16le",
    "pcm_s16be",
    "flac",
    "libvorbis",
)
PANDOC_ALL = [
    "in:markdown",
    "in:html",
    "in:docx",
    "in:odt",
    "in:epub",
    "in:rtf",
    "out:gfm",
    "out:html5",
    "out:docx",
    "out:odt",
    "out:epub3",
    "out:rtf",
    "out:plain",
]
MAGICK_FULL = {
    "JPEG": "rw-",
    "PNG": "rw-",
    "WEBP": "rw+",
    "AVIF": "rw+",
    "HEIC": "rw+",
    "GIF": "rw+",
    "BMP": "rw-",
    "TIFF": "rw+",
    "ICO": "rw+",
    "PDF": "rw+",
}


def all_tools():
    return {
        "ffmpeg": tool("ffmpeg", features=FFMPEG_ALL),
        "soffice": tool("soffice", version=None),
        "pandoc": tool("pandoc", features=PANDOC_ALL),
        "magick": tool("magick", formats=MAGICK_FULL),
        "gs": tool("gs"),
        "tesseract": tool("tesseract", features=["eng", "deu", "osd"]),
    }


class TempDirTest(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="cs-test-")
        self.addCleanup(shutil.rmtree, self.dir, True)

    def write(self, name, data):
        path = os.path.join(self.dir, name)
        mode = "wb" if isinstance(data, bytes) else "w"
        kwargs = {} if isinstance(data, bytes) else {"encoding": "utf-8", "newline": ""}
        with open(path, mode, **kwargs) as handle:
            handle.write(data)
        return path

    def read(self, name):
        with open(os.path.join(self.dir, name), encoding="utf-8", newline="") as handle:
            return handle.read()
