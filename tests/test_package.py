"""The package's own files: what Package Control's reviewers look at, and that they agree."""

import ast
import json
import os
import re
import unittest

from converterstudio import CLIENT, DESKTOP_MIN_VERSION, VERSION

from . import ROOT

PACKAGE = "Converter Studio"


def read(name):
    with open(os.path.join(ROOT, name), encoding="utf-8") as handle:
        return handle.read()


def jsonc(text):
    """Sublime Text's JSON with comments and trailing commas, as plain JSON."""
    out, i, in_string = [], 0, False
    while i < len(text):
        c = text[i]
        if in_string:
            out.append(c)
            if c == "\\":
                out.append(text[i + 1])
                i += 1
            elif c == '"':
                in_string = False
        elif c == '"':
            in_string = True
            out.append(c)
        elif text.startswith("//", i):
            i = text.find("\n", i)
            if i < 0:
                break
            continue
        elif text.startswith("/*", i):
            i = text.index("*/", i) + 2
            continue
        else:
            out.append(c)
        i += 1
    return json.loads(re.sub(r",(\s*[}\]])", r"\1", "".join(out)))


def snake(name):
    return re.sub(r"(?<!^)(?=[A-Z])", "_", name).lower()


class PackageFilesTest(unittest.TestCase):
    def test_version_matches_the_changelog(self):
        match = re.search(r"^## (\d+\.\d+\.\d+)", read("CHANGELOG.md"), re.M)
        self.assertEqual(match.group(1), VERSION)
        self.assertEqual(CLIENT, "sublime-text")
        self.assertTrue(DESKTOP_MIN_VERSION[0].isdigit())

    def test_python_host(self):
        # 3.8 selects Python 3.8 in builds 4050–4204 and Python 3.14 from 4205 on.
        self.assertEqual(read(".python-version").strip(), "3.8")

    def test_commands_in_the_palette_exist(self):
        commands = jsonc(read("Default.sublime-commands"))
        tree = ast.parse(read("converter_studio.py"))
        defined = {
            snake(node.name[: -len("Command")])
            for node in ast.walk(tree)
            if isinstance(node, ast.ClassDef) and node.name.endswith("Command")
        }
        used = {entry["command"] for entry in commands} - {"edit_settings"}
        self.assertEqual(used, defined)
        captions = [entry["caption"] for entry in commands]
        self.assertIn("Converter Studio: Convert Current File…", captions)
        self.assertIn("Converter Studio: Convert File…", captions)

    def test_settings_open_in_split_view_from_the_palette_and_the_menu(self):
        base = "${packages}/%s/%s.sublime-settings" % (PACKAGE, PACKAGE)
        palette = [e for e in jsonc(read("Default.sublime-commands")) if e["command"] == "edit_settings"]
        self.assertEqual(len(palette), 1)
        self.assertEqual(palette[0]["caption"], "Preferences: %s Settings" % PACKAGE)
        self.assertEqual(palette[0]["args"]["base_file"], base)
        menu = jsonc(read("Main.sublime-menu"))
        entry = menu[0]["children"][0]["children"][0]
        self.assertEqual(entry["caption"], PACKAGE)
        self.assertEqual(entry["children"][0]["command"], "edit_settings")
        self.assertEqual(entry["children"][0]["args"]["base_file"], base)

    def test_no_key_bindings_context_menus_or_mouse_maps(self):
        names = os.listdir(ROOT)
        for name in names:
            self.assertFalse(name.endswith((".sublime-keymap", ".sublime-mousemap")), name)
            self.assertNotIn("Context.sublime-menu", name)

    def test_default_settings_are_the_ones_the_plugin_reads(self):
        settings = jsonc(read("%s.sublime-settings" % PACKAGE))
        tree = ast.parse(read("converter_studio.py"))
        keys = None
        for node in ast.walk(tree):
            if isinstance(node, ast.Assign) and getattr(node.targets[0], "id", "") == "SETTING_KEYS":
                keys = set(ast.literal_eval(node.value))
        self.assertEqual(set(settings), keys)
        self.assertEqual(settings["api_key"], "")
        self.assertEqual(settings["api_url"], "https://converter.studio/api")
        self.assertFalse(settings["use_desktop_app"])
        self.assertIn("PLAIN TEXT", read("%s.sublime-settings" % PACKAGE))

    def test_messages(self):
        messages = json.loads(read("messages.json"))
        for path in messages.values():
            self.assertTrue(os.path.isfile(os.path.join(ROOT, path)), path)

    def test_only_one_plugin_at_the_root(self):
        plugins = [n for n in os.listdir(ROOT) if n.endswith(".py")]
        self.assertEqual(plugins, ["converter_studio.py"])
        self.assertFalse(os.path.exists(os.path.join(ROOT, "__init__.py")))

    def test_the_library_does_not_import_sublime(self):
        folder = os.path.join(ROOT, "converterstudio")
        for name in os.listdir(folder):
            if name.endswith(".py"):
                tree = ast.parse(read(os.path.join("converterstudio", name)))
                for node in ast.walk(tree):
                    if isinstance(node, (ast.Import, ast.ImportFrom)):
                        module = getattr(node, "module", None) or ""
                        names = [a.name for a in node.names]
                        self.assertFalse(module.startswith("sublime") or "sublime" in names, name)

    def test_readme_says_when_files_leave_the_computer(self):
        readme = read("README.md")
        self.assertIn("converter.studio/privacy", readme)
        self.assertIn("Nothing is uploaded", readme)
        self.assertIn("uploaded to converter.studio", readme)


if __name__ == "__main__":
    unittest.main()
