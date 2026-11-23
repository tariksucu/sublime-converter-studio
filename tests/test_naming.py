import os
import unittest

from converterstudio import naming

from .helpers import TempDirTest


class NamingTest(TempDirTest):
    def test_first_free_name(self):
        self.assertEqual(os.path.basename(naming.claim_file(self.dir, "photo", "jpg")), "photo.jpg")
        self.assertEqual(os.path.basename(naming.claim_file(self.dir, "photo", "jpg")), "photo (2).jpg")
        self.assertEqual(os.path.basename(naming.claim_file(self.dir, "photo", "jpg")), "photo (3).jpg")

    def test_an_existing_file_is_never_touched(self):
        self.write("report.pdf", b"original")
        produced = self.write("tmp.bin", b"new")
        placed = naming.place(produced, self.dir, "report", "pdf")
        self.assertEqual(os.path.basename(placed), "report (2).pdf")
        with open(os.path.join(self.dir, "report.pdf"), "rb") as handle:
            self.assertEqual(handle.read(), b"original")

    def test_long_names_are_shortened_keeping_the_extension(self):
        name = os.path.basename(naming.claim_file(self.dir, "x" * 400, "webp"))
        self.assertLessEqual(len(name), naming.MAX_NAME)
        self.assertTrue(name.endswith(".webp"))

    def test_several_files_go_into_a_new_folder(self):
        pages = [self.write("p-%d.png" % i, b"png") for i in (2, 1)]
        os.mkdir(os.path.join(self.dir, "doc (PNG pages)"))
        folder = naming.place_many(pages, self.dir, "doc (PNG pages)")
        self.assertEqual(os.path.basename(folder), "doc (PNG pages) (2)")
        self.assertEqual(sorted(os.listdir(folder)), ["p-1.png", "p-2.png"])

    def test_a_failed_copy_leaves_no_empty_file(self):
        with self.assertRaises(OSError):
            naming.place(os.path.join(self.dir, "missing"), self.dir, "out", "txt")
        self.assertEqual(os.listdir(self.dir), [])


if __name__ == "__main__":
    unittest.main()
