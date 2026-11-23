import unittest
from urllib.parse import parse_qs, urlsplit

from converterstudio import desktop


class HandoffUrlTest(unittest.TestCase):
    def test_the_address_names_target_client_and_files(self):
        url = desktop.handoff_url("pdf", ["/home/ada/My Report.docx", "/home/ada/b.docx"])
        self.assertTrue(url.startswith("converter-studio://convert?to=pdf&from=sublime-text&file="))
        query = parse_qs(urlsplit(url).query)
        self.assertEqual(query["file"], ["/home/ada/My Report.docx", "/home/ada/b.docx"])
        self.assertEqual(query["to"], ["pdf"])
        self.assertEqual(query["from"], ["sublime-text"])

    def test_every_reserved_character_is_encoded(self):
        url = desktop.handoff_url("webp", ["/a/x+y #1 & 100%.png"])
        tail = url.split("&file=", 1)[1]
        self.assertEqual(tail, "%2Fa%2Fx%2By%20%231%20%26%20100%25.png")
        self.assertNotIn("+", tail)
        self.assertNotIn("#", url)

    def test_non_ascii_paths(self):
        url = desktop.handoff_url("jpg", ["/fotoğraf/çiçek.heic"])
        self.assertEqual(parse_qs(urlsplit(url).query)["file"], ["/fotoğraf/çiçek.heic"])
        self.assertTrue(url.isascii() if hasattr(url, "isascii") else all(ord(c) < 128 for c in url))

    def test_long_selections_are_split_under_the_limit(self):
        paths = ["/home/ada/photos/holiday-%03d-with-a-long-name.heic" % i for i in range(120)]
        urls = desktop.handoff_urls("jpg", paths)
        self.assertGreater(len(urls), 1)
        self.assertTrue(all(len(u) <= desktop.MAX_URL for u in urls))
        files = [f for u in urls for f in parse_qs(urlsplit(u).query)["file"]]
        self.assertEqual(files, paths)
        self.assertTrue(all(u.startswith("converter-studio://convert?to=jpg&from=sublime-text&file=") for u in urls))

    def test_a_single_long_path_still_goes(self):
        urls = desktop.handoff_urls("jpg", ["/" + "a" * 3000 + ".png"])
        self.assertEqual(len(urls), 1)


class LocalFileTest(unittest.TestCase):
    MOUNTS = [("/", "ext4"), ("/home", "ext4"), ("/mnt/nas", "nfs4"), ("/home/ada/remote", "fuse.sshfs")]

    def test_network_and_remote_mounts_are_not_local(self):
        mounts = sorted(self.MOUNTS, key=lambda m: len(m[0]), reverse=True)
        self.assertTrue(desktop.is_local_file("/home/ada/a.png", "linux", mounts))
        self.assertFalse(desktop.is_local_file("/mnt/nas/a.png", "linux", mounts))
        self.assertFalse(desktop.is_local_file("/home/ada/remote/a.png", "linux", mounts))
        self.assertFalse(desktop.is_local_file("/run/user/1000/gvfs/sftp:host=x/a.png", "linux", mounts))

    def test_windows_shares(self):
        self.assertFalse(desktop.is_local_file("\\\\server\\share\\a.png", "windows"))
        self.assertTrue(desktop.is_local_file("C:\\Users\\ada\\a.png", "windows"))

    def test_mount_table_parsing(self):
        text = "/dev/md1 / ext4 rw 0 0\nhost:/x /mnt/my\\040nas nfs4 rw 0 0\n"
        mounts = desktop._mount_types(lambda: text)
        self.assertEqual(mounts[0], ("/mnt/my nas", "nfs4"))


class OpenTest(unittest.TestCase):
    def test_linux_and_macos_use_argument_lists(self):
        calls = []

        def run(argv):
            calls.append(argv)
            return 0, ""

        url = desktop.handoff_url("pdf", ["/a b.docx"])
        self.assertIsNone(desktop.open_url(url, "linux", run=run))
        self.assertIsNone(desktop.open_url(url, "osx", run=run))
        self.assertEqual(calls, [["xdg-open", url], ["open", url]])

    def test_a_failure_is_explained(self):
        self.assertIn("exit code 4", desktop.open_url("x", "linux", run=lambda argv: (4, "")))
        self.assertIn("could not be started", desktop.open_url("x", "osx", run=lambda argv: (None, "nope")))

    def test_windows_uses_startfile(self):
        opened = []
        self.assertIsNone(desktop.open_url("converter-studio://x", "windows", startfile=opened.append))
        self.assertEqual(opened, ["converter-studio://x"])

        def refuse(url):
            raise OSError(2, "No application is associated")

        self.assertIn("No application", desktop.open_url("u", "windows", startfile=refuse))

    def test_is_installed_on_linux_asks_xdg_mime(self):
        self.assertTrue(desktop.is_installed("linux", run=lambda argv: (0, "converter-studio.desktop\n")))
        self.assertFalse(desktop.is_installed("linux", run=lambda argv: (0, "\n")))
        self.assertIsNone(desktop.is_installed("linux", run=lambda argv: (None, "")))

    def test_is_installed_on_macos_looks_in_applications(self):
        self.assertTrue(desktop.is_installed("osx", exists=lambda p: p == "/Applications/Converter Studio.app"))
        self.assertIsNone(desktop.is_installed("osx", exists=lambda p: False, home="/Users/ada"))


if __name__ == "__main__":
    unittest.main()
