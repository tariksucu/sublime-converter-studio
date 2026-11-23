import unittest

from converterstudio import formats as fmt
from converterstudio.catalog import FORMATS


class FormatsTest(unittest.TestCase):
    def test_detects_by_extension_without_regard_to_case(self):
        self.assertEqual(fmt.detect("/a/Photo.JPEG"), "jpg")
        self.assertEqual(fmt.detect("C:\\x\\report.docx"), "docx")
        self.assertEqual(fmt.detect("notes.markdown"), "md")
        self.assertEqual(fmt.detect("clip.m4v"), "mp4")

    def test_the_longest_extension_wins(self):
        self.assertEqual(fmt.detect("backup.tar.gz"), "tgz")
        self.assertEqual(fmt.stem("backup.tar.gz", "tgz"), "backup")

    def test_unknown_or_bare_names_have_no_format(self):
        self.assertIsNone(fmt.detect("Makefile"))
        self.assertIsNone(fmt.detect("archive.xyz"))
        self.assertIsNone(fmt.detect(".pdf"))

    def test_stem_and_label_and_extension(self):
        self.assertEqual(fmt.stem("/a/b/My File.final.docx", "docx"), "My File.final")
        self.assertEqual(fmt.stem("noext"), "noext")
        self.assertEqual(fmt.label("webp"), "WebP")
        self.assertEqual(fmt.label("made-up"), "MADE-UP")
        self.assertEqual(fmt.extension("jpg"), "jpg")
        self.assertEqual(fmt.extension("tgz"), "tar.gz")

    def test_cloud_targets_keep_the_first_formats_order_and_intersect(self):
        self.assertEqual(fmt.cloud_targets(["docx"])[0], "pdf")
        both = fmt.cloud_targets(["docx", "odt"])
        self.assertIn("pdf", both)
        self.assertNotIn("odt", both)  # odt cannot become odt
        self.assertEqual(fmt.cloud_targets(["docx", "mp3"]), ())
        self.assertEqual(fmt.cloud_targets([]), ())

    def test_catalogue_is_well_formed(self):
        ids = [row[0] for row in FORMATS]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertGreater(len(ids), 50)
        for format_id, name, category, extensions, targets in FORMATS:
            self.assertTrue(name and category and extensions, format_id)
            for target in targets:
                self.assertIn(target, ids, "%s → %s" % (format_id, target))


if __name__ == "__main__":
    unittest.main()
