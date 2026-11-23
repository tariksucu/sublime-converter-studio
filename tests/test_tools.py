import os
import unittest

from converterstudio import tools

FFMPEG_ENCODERS = """Encoders:
 V..... = Video
 ------
 V....D libx264              libx264 H.264 / AVC / MPEG-4 AVC (codec h264)
 V....D libvpx-vp9           libvpx VP9 (codec vp9)
 A....D aac                  AAC (Advanced Audio Coding)
 A....D libmp3lame           libmp3lame MP3 (MPEG audio layer 3) (codec mp3)
"""

MAGICK_FORMATS = """   Format  Module    Mode  Description
-------------------------------------------------------------------------------
      3FR  DNG       r--   Hasselblad CFV/H3D39II Raw Format (0.21.2)
     AVIF  HEIC      rw+   AV1 Image File Format (1.17.6)
     HEIC  HEIC      r--   High Efficiency Image Format (1.17.6)
     JPEG* JPEG      rw-   Joint Photographic Experts Group JFIF format (80)
      PNG* PNG       rw-   Portable Network Graphics (libpng 1.6.43)
     WEBP* WEBP      rw+   WebP Image Format (libwebp 1.3.2 [020F])
"""


def fake_run(answers):
    """A run_probe stand-in: {(basename, first argument): (code, output)}."""
    calls = []

    def run(argv):
        calls.append(argv)
        key = (os.path.basename(argv[0]), argv[1] if len(argv) > 1 else "")
        return answers.get(key, (1, "unknown"))

    run.calls = calls
    return run


class ExpandTest(unittest.TestCase):
    def test_windows_variables_any_case(self):
        env = {"PROGRAMFILES": "C:\\Program Files"}
        self.assertEqual(tools.expand("%ProgramFiles%\\Pandoc", env), ["C:\\Program Files\\Pandoc"])

    def test_a_missing_variable_drops_the_folder(self):
        self.assertEqual(tools.expand("%ProgramFiles(x86)%\\gs", {}), [])

    def test_home(self):
        self.assertEqual(tools.expand("~/.local/bin", {"HOME": "/home/ada"}), ["/home/ada/.local/bin"])

    def test_patterns_newest_first(self):
        import tempfile

        root = tempfile.mkdtemp()
        try:
            for name in ("ImageMagick-7.1.1-9", "ImageMagick-7.1.10-1", "ImageMagick-7.1.2-0"):
                os.mkdir(os.path.join(root, name))
            found = tools.expand(os.path.join(root, "ImageMagick-*"), {})
            self.assertEqual(
                [os.path.basename(p) for p in found],
                ["ImageMagick-7.1.10-1", "ImageMagick-7.1.2-0", "ImageMagick-7.1.1-9"],
            )
        finally:
            import shutil

            shutil.rmtree(root)


class CandidatesTest(unittest.TestCase):
    def test_path_first_then_usual_folders(self):
        spec = tools.SPEC_BY_ID["ffmpeg"]
        found = tools.candidates(spec, "osx", {"PATH": "/x"}, which=lambda name, path=None: "/x/" + name)
        self.assertEqual(found[0], "/x/ffmpeg")
        self.assertIn("/opt/homebrew/bin/ffmpeg", found)
        self.assertEqual(len(found), len(set(found)))

    def test_windows_names(self):
        spec = tools.SPEC_BY_ID["gs"]
        env = {"ProgramFiles": "C:\\PF", "LOCALAPPDATA": "C:\\L", "ProgramData": "C:\\PD", "USERPROFILE": "C:\\U"}
        found = tools.candidates(spec, "windows", env, which=lambda name, path=None: None)
        self.assertTrue(all(os.path.basename(p.replace("\\", "/")) in ("gswin64c.exe", "gswin32c.exe") for p in found))

    def test_imagemagick_6_convert_is_never_used_on_windows(self):
        spec = tools.SPEC_BY_ID["magick"]
        found = tools.candidates(spec, "windows", {}, which=lambda name, path=None: "C:\\Windows\\" + name)
        self.assertFalse(any("convert" in p.lower() for p in found))
        found = tools.candidates(spec, "linux", {}, which=lambda name, path=None: "/usr/bin/" + name)
        self.assertEqual(found[:2], ["/usr/bin/magick", "/usr/bin/convert"])


class ProbeTest(unittest.TestCase):
    def test_ffmpeg_encoders_and_version(self):
        run = fake_run(
            {
                ("ffmpeg", "-hide_banner"): (0, FFMPEG_ENCODERS),
                ("ffmpeg", "-version"): (0, "ffmpeg version 7.1.1 Copyright (c) 2000-2025"),
            }
        )
        found = tools.probe("ffmpeg", "/usr/bin/ffmpeg", run)
        self.assertTrue(found.usable)
        self.assertEqual(found.version, "7.1.1")
        self.assertEqual(found.features, {"libx264", "libvpx-vp9", "aac", "libmp3lame"})

    def test_imagemagick_formats_and_flavor(self):
        run = fake_run(
            {
                ("magick", "-version"): (0, "Version: ImageMagick 7.1.1-43 Q16-HDRI x86_64"),
                ("magick", "-list"): (0, MAGICK_FORMATS),
            }
        )
        found = tools.probe("magick", "/usr/bin/magick", run)
        self.assertEqual(found.flavor, "magick")
        self.assertEqual(found.version, "7.1.1-43")
        self.assertEqual(found.magick_mode("HEIC"), "r--")
        self.assertEqual(found.magick_mode("JPEG"), "rw-")
        self.assertEqual(found.magick_mode("JXL"), "---")

    def test_a_convert_that_is_not_imagemagick_is_not_used(self):
        run = fake_run({("convert", "-version"): (1, "convert: unknown option")})
        found = tools.probe("magick", "/usr/bin/convert", run)
        self.assertFalse(found.usable)
        self.assertIn("not ImageMagick", found.problem)

    def test_pandoc_formats(self):
        run = fake_run(
            {
                ("pandoc", "--version"): (0, "pandoc 3.6.4\nFeatures: +server +lua"),
                ("pandoc", "--list-input-formats"): (0, "markdown\ndocx\n"),
                ("pandoc", "--list-output-formats"): (0, "gfm\nplain\n"),
            }
        )
        found = tools.probe("pandoc", "/usr/bin/pandoc", run)
        self.assertEqual(found.version, "3.6.4")
        self.assertEqual(found.features, {"in:markdown", "in:docx", "out:gfm", "out:plain"})

    def test_tesseract_languages(self):
        run = fake_run(
            {
                ("tesseract", "--version"): (0, "tesseract 5.5.0\n leptonica-1.85.0"),
                ("tesseract", "--list-langs"): (
                    0,
                    'List of available languages in "/usr/share/tessdata/" (3):\neng\nosd\ntur\n',
                ),
            }
        )
        found = tools.probe("tesseract", "/usr/bin/tesseract", run)
        self.assertEqual(found.version, "5.5.0")
        self.assertEqual(found.features, {"eng", "osd", "tur"})

    def test_ghostscript_version_and_libreoffice_trusted(self):
        found = tools.probe("gs", "/usr/bin/gs", fake_run({("gs", "--version"): (0, "10.05.1\n")}))
        self.assertEqual(found.version, "10.05.1")
        run = fake_run({})
        office = tools.probe("soffice", "/usr/bin/soffice", run)
        self.assertTrue(office.usable)
        self.assertEqual(run.calls, [])  # LibreOffice is not started just to look at it

    def test_a_tool_that_hangs_is_reported(self):
        found = tools.probe("gs", "/usr/bin/gs", lambda argv: (None, "did not answer in 15 seconds"))
        self.assertFalse(found.usable)
        self.assertIn("15 seconds", found.problem)


class DiscoverTest(unittest.TestCase):
    def test_finds_and_skips_a_broken_copy(self):
        present = {"/usr/bin/convert", "/usr/local/bin/convert", "/usr/bin/gs"}

        def which(name, path=None):
            return "/usr/bin/" + name if "/usr/bin/" + name in present else None

        run = fake_run(
            {
                ("gs", "--version"): (0, "10.0"),
                ("convert", "-version"): (0, "Version: ImageMagick 6.9.12-98 Q16"),
                ("convert", "-list"): (0, MAGICK_FORMATS),
            }
        )
        broken = {"/usr/bin/convert"}

        def run_with_broken(argv):
            if argv[0] in broken:
                return 0, "Usage: convert something-else"
            return run(argv)

        found = tools.discover(
            "linux", {"HOME": "/home/ada"}, run=run_with_broken, which=which, is_program=lambda p: p in present
        )
        self.assertEqual(found["gs"].path, "/usr/bin/gs")
        self.assertEqual(found["magick"].path, "/usr/local/bin/convert")
        self.assertEqual(found["magick"].flavor, "convert")
        self.assertIsNone(found["ffmpeg"].path)
        self.assertIsNone(found["ffmpeg"].problem)

    def test_a_configured_path_is_the_only_one_used(self):
        found = tools.discover(
            "linux",
            {"HOME": "/home/ada"},
            configured={"ffmpeg": "~/bin/ffmpeg"},
            run=fake_run({}),
            which=lambda name, path=None: "/usr/bin/" + name,
            is_program=lambda p: p == "/usr/bin/ffmpeg",
        )
        self.assertIsNone(found["ffmpeg"].path)
        self.assertIn("~/bin/ffmpeg", found["ffmpeg"].problem)


if __name__ == "__main__":
    unittest.main()
