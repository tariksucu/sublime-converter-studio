import os
import unittest

from converterstudio import recipes
from converterstudio.recipes import CLOUD, COMPRESS, DESKTOP, LOCAL, OCR, PAGES, PLAIN, Choice

from .helpers import all_tools, tool


def by_key(choices):
    return {(c.target, c.variant): c for c in choices}


class LocalChoicesTest(unittest.TestCase):
    def test_office_documents_go_to_libreoffice_and_markup_to_pandoc(self):
        found = all_tools()
        docx = by_key(recipes.local_choices("docx", found))
        self.assertEqual(docx[("pdf", PLAIN)].tool, "soffice")
        self.assertEqual(docx[("md", PLAIN)].tool, "pandoc")
        self.assertEqual(docx[("odt", PLAIN)].tool, "soffice")
        md = by_key(recipes.local_choices("md", found))
        self.assertEqual(md[("docx", PLAIN)].tool, "pandoc")
        self.assertEqual(md[("pdf", PLAIN)].tool, "pandoc+soffice")
        self.assertEqual(md[("html", PLAIN)].tool, "pandoc")

    def test_one_row_per_target_in_the_catalogues_order(self):
        choices = recipes.local_choices("docx", all_tools())
        keys = [c.key for c in choices]
        self.assertEqual(len(keys), len(set(keys)))
        self.assertEqual(choices[0].target, "pdf")  # the most used first
        self.assertTrue(all(c.layer == LOCAL for c in choices))

    def test_python_needs_no_tool(self):
        choices = by_key(recipes.local_choices("csv", {}))
        self.assertEqual(choices[("json", PLAIN)].tool, "python")
        self.assertEqual(set(by_key(recipes.local_choices("srt", {}))), {("vtt", PLAIN)})

    def test_without_tools_there_is_nothing_local(self):
        self.assertEqual(recipes.local_choices("docx", {}), [])
        found = all_tools()
        found["soffice"].problem = "did not start"
        self.assertNotIn(("pdf", PLAIN), by_key(recipes.local_choices("docx", found)))

    def test_capabilities_decide(self):
        found = all_tools()
        found["ffmpeg"] = tool("ffmpeg", features=["aac", "libmp3lame"])
        mov = recipes.local_choices("mov", found, with_unavailable=True)
        ok = {c.target for c in mov if not c.reason}
        blocked = {c.target: c.reason for c in mov if c.reason}
        self.assertIn("mp3", ok)
        self.assertIn("m4a", ok)
        self.assertIn("libx264", blocked["mp4"])
        self.assertNotIn("mp4", {c.target for c in recipes.local_choices("mov", found)})

    def test_heic_needs_an_imagemagick_that_reads_it(self):
        found = all_tools()
        found["magick"] = tool("magick", formats={"HEIC": "---", "JPEG": "rw-", "PNG": "rw-"})
        heic = recipes.local_choices("heic", found, with_unavailable=True)
        self.assertTrue(heic)
        self.assertTrue(all("cannot read HEIC" in c.reason for c in heic))
        png = by_key(recipes.local_choices("png", found))
        self.assertIn(("jpg", PLAIN), png)
        self.assertNotIn(("webp", PLAIN), png)

    def test_ocr_and_pdf_variants(self):
        found = all_tools()
        png = by_key(recipes.local_choices("png", found, "deu"))
        self.assertEqual(png[("txt", OCR)].tool, "tesseract")
        self.assertEqual(png[("pdf", OCR)].tool, "tesseract")
        self.assertEqual(png[("pdf", PLAIN)].tool, "magick")
        self.assertIn("text recognition", png[("txt", OCR)].label)
        blocked = recipes.local_choices("png", found, "tur", with_unavailable=True)
        self.assertIn("tur", [c for c in blocked if c.variant == OCR][0].reason)
        pdf = by_key(recipes.local_choices("pdf", found))
        self.assertEqual(pdf[("pdf", COMPRESS)].label, "PDF, smaller (compressed)")
        self.assertEqual(pdf[("png", PAGES)].tool, "gs")

    def test_remote_choices_follow_the_catalogue(self):
        cloud = recipes.remote_choices("heic", CLOUD)
        self.assertEqual(cloud[0].target, "jpg")
        self.assertTrue(all(c.layer == CLOUD and c.tool is None for c in cloud))
        self.assertEqual(recipes.remote_choices("nope", DESKTOP), [])
        self.assertEqual(recipes.label("pdf", PLAIN, "pdf"), "PDF, smaller (compressed)")


class BuildTest(unittest.TestCase):
    def setUp(self):
        self.found = all_tools()
        self.work = os.path.join(os.sep, "tmp", "work")
        self.src = os.path.join(os.sep, "home", "ada", "My Files", "report.docx")

    def plan(self, source, target, tool_id, variant=PLAIN, src=None, **kwargs):
        choice = Choice(source, target, LOCAL, tool_id, variant)
        return recipes.build(choice, src or self.src, self.work, self.found, **kwargs)

    def test_every_step_is_an_argument_list(self):
        for source, target, tool_id, variant in (
            ("mp4", "mp3", "ffmpeg", PLAIN),
            ("docx", "pdf", "soffice", PLAIN),
            ("md", "docx", "pandoc", PLAIN),
            ("md", "pdf", "pandoc+soffice", PLAIN),
            ("png", "webp", "magick", PLAIN),
            ("pdf", "pdf", "gs", COMPRESS),
            ("png", "txt", "tesseract", OCR),
        ):
            plan = self.plan(source, target, tool_id, variant)
            self.assertTrue(plan.steps, tool_id)
            for argv in plan.steps:
                self.assertIsInstance(argv, list)
                self.assertTrue(all(isinstance(a, str) for a in argv))

    def test_ffmpeg_never_overwrites_and_writes_into_the_work_folder(self):
        argv = self.plan("mp4", "webm", "ffmpeg", src="/v/clip.mp4").steps[0]
        self.assertEqual(argv[:7], ["/usr/bin/ffmpeg", "-hide_banner", "-nostdin", "-loglevel", "error", "-n", "-i"])
        self.assertEqual(argv[7], "/v/clip.mp4")
        self.assertIn("libvpx-vp9", argv)
        self.assertEqual(argv[-1], os.path.join(self.work, "clip.webm"))

    def test_libreoffice_uses_its_own_profile_and_the_html_filter(self):
        argv = self.plan("docx", "pdf", "soffice", profile_dir="/cache/lo").steps[0]
        self.assertEqual(argv[1], "-env:UserInstallation=file:///cache/lo")
        self.assertIn("--headless", argv)
        self.assertEqual(argv[-5:], ["--convert-to", "pdf", "--outdir", self.work, self.src])
        html = self.plan("html", "docx", "soffice", src="/a/page.html").steps[0]
        self.assertIn("--infilter=HTML (StarWriter)", html)
        self.assertIn("docx:MS Word 2007 XML", html)

    def test_markdown_to_pdf_goes_through_word(self):
        steps = self.plan("md", "pdf", "pandoc+soffice", src="/a/notes.md").steps
        self.assertEqual(len(steps), 2)
        docx = os.path.join(self.work, ".step", "notes.docx")
        self.assertEqual(steps[0][:5], ["/usr/bin/pandoc", "--from", "markdown", "--to", "docx"])
        self.assertEqual(steps[0][-3:], ["--output", docx, "/a/notes.md"])
        self.assertEqual(steps[1][-1], docx)
        self.assertEqual(steps[1][-4:-1], ["pdf", "--outdir", self.work])

    def test_imagemagick_first_frame_and_format_prefix(self):
        argv = self.plan("gif", "png", "magick", src="/i/anim.gif").steps[0]
        self.assertEqual(argv[1], "/i/anim.gif[0]")
        self.assertEqual(argv[-1], "PNG:" + os.path.join(self.work, "anim.png"))
        jpg = self.plan("png", "jpg", "magick", src="/i/logo.png").steps[0]
        self.assertIn("remove", jpg)  # transparency on white
        self.assertEqual(jpg[1], "/i/logo.png")

    def test_ghostscript_page_pattern_escapes_percent(self):
        argv = self.plan("pdf", "png", "gs", PAGES, src="/d/100% done.pdf").steps[0]
        out = [a for a in argv if a.startswith("-sOutputFile=")][0]
        self.assertTrue(out.endswith("100%% done-page-%03d.png"), out)
        self.assertIn("-dSAFER", argv)
        compress = self.plan("pdf", "pdf", "gs", COMPRESS, src="/d/a.pdf").steps[0]
        self.assertIn("-dPDFSETTINGS=/ebook", compress)

    def test_tesseract_language_and_pdf(self):
        plan = self.plan("png", "pdf", "tesseract", OCR, src="/s/scan.png", language="eng+deu")
        argv = plan.steps[0]
        self.assertEqual(
            argv, ["/usr/bin/tesseract", "/s/scan.png", os.path.join(self.work, "scan"), "-l", "eng+deu", "pdf"]
        )
        self.assertEqual(plan.env, {"OMP_THREAD_LIMIT": "1"})

    def test_python_plans_write_one_file(self):
        plan = self.plan("csv", "json", "python", src="/t/table.csv")
        self.assertEqual(plan.steps, [])
        self.assertEqual(plan.output, os.path.join(self.work, "table.json"))
        self.assertTrue(callable(plan.function))


if __name__ == "__main__":
    unittest.main()
