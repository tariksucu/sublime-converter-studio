import json
import os
import unittest

from converterstudio import builtin

from .helpers import TempDirTest


class CsvJsonTest(TempDirTest):
    def convert(self, source_name, data, target_name):
        source = self.write(source_name, data)
        target = os.path.join(self.dir, target_name)
        builtin.converter(*[n.rsplit(".", 1)[1] for n in (source_name, target_name)])(source, target)
        return self.read(target_name)

    def test_csv_to_json_with_header_and_bom(self):
        out = json.loads(self.convert("t.csv", "﻿name,age\r\nAda,36\r\nAlan,41\r\n", "t.json"))
        self.assertEqual(out, [{"name": "Ada", "age": "36"}, {"name": "Alan", "age": "41"}])

    def test_csv_semicolons_duplicates_and_extra_cells(self):
        out = json.loads(self.convert("t.csv", "a;a;\n1;2;3;4\n", "t.json"))
        self.assertEqual(out, [{"a": "1", "a_2": "2", "column3": "3", "_extra": ["4"]}])

    def test_csv_in_utf16(self):
        out = json.loads(self.convert("t.csv", "x,y\n1,ü\n".encode("utf-16"), "t.json"))
        self.assertEqual(out, [{"x": "1", "y": "ü"}])

    def test_empty_csv_says_so(self):
        with self.assertRaises(builtin.ConversionError):
            self.convert("t.csv", "\n\n", "t.json")

    def test_json_array_of_objects_to_csv(self):
        data = [{"name": "Ada", "tags": ["a", "b"]}, {"name": "Alan", "ok": True, "n": None}]
        out = self.convert("t.json", json.dumps(data), "t.csv")
        self.assertEqual(out, 'name,tags,ok,n\r\nAda,"[""a"",""b""]",,\r\nAlan,,true,\r\n')

    def test_json_table_inside_an_object(self):
        out = self.convert("t.json", json.dumps({"total": 1, "items": [{"id": 7}]}), "t.csv")
        self.assertEqual(out, "id\r\n7\r\n")

    def test_json_object_is_one_row(self):
        out = self.convert("t.json", json.dumps({"name": "converter", "formats": ["mp4", "mp3"]}), "t.csv")
        self.assertEqual(out, 'name,formats\r\nconverter,"[""mp4"",""mp3""]"\r\n')

    def test_invalid_json_says_so(self):
        with self.assertRaises(builtin.ConversionError) as caught:
            self.convert("t.json", "{nope", "t.csv")
        self.assertIn("not valid JSON", str(caught.exception))


SRT = "1\r\n00:00:01,000 --> 00:00:02,500\r\nHello\r\n<i>world</i>\r\n\r\n2\r\n00:01:02,5 --> 00:01:03,000\r\nBye\r\n"
VTT = "WEBVTT\n\nNOTE a note\n\nintro\n00:01.000 --> 00:02.500 align:start\n<v Ada>Hello</v>\n\n00:00:03.000 --> 00:00:04.000\nAgain\n"
ASS = """[Script Info]
ScriptType: v4.00+

[Events]
Format: Layer, Start, End, Style, Text
Dialogue: 0,0:00:05.00,0:00:06.00,Default,{\\b1}Later{\\b0}, with a comma
Dialogue: 0,0:00:01.50,0:00:02.00,Default,First\\NSecond line
"""


class SubtitleTest(TempDirTest):
    def test_srt_to_vtt(self):
        builtin.converter("srt", "vtt")(self.write("a.srt", SRT), os.path.join(self.dir, "a.vtt"))
        self.assertEqual(
            self.read("a.vtt"),
            "WEBVTT\n\n00:00:01.000 --> 00:00:02.500\nHello\n<i>world</i>\n\n00:01:02.500 --> 00:01:03.000\nBye\n",
        )

    def test_vtt_to_srt_drops_notes_and_voice_tags(self):
        builtin.converter("vtt", "srt")(self.write("a.vtt", VTT), os.path.join(self.dir, "a.srt"))
        self.assertEqual(
            self.read("a.srt"),
            "1\n00:00:01,000 --> 00:00:02,500\nHello\n\n2\n00:00:03,000 --> 00:00:04,000\nAgain\n",
        )

    def test_ass_to_srt_in_time_order_without_style_codes(self):
        builtin.converter("ass", "srt")(self.write("a.ass", ASS), os.path.join(self.dir, "a.srt"))
        self.assertEqual(
            self.read("a.srt"),
            "1\n00:00:01,500 --> 00:00:02,000\nFirst\nSecond line\n\n"
            "2\n00:00:05,000 --> 00:00:06,000\nLater, with a comma\n",
        )

    def test_a_file_without_cues_says_so(self):
        with self.assertRaises(builtin.ConversionError):
            builtin.converter("srt", "vtt")(self.write("a.srt", "just text"), os.path.join(self.dir, "a.vtt"))

    def test_targets(self):
        self.assertEqual(sorted(builtin.targets("ass")), ["srt", "vtt"])
        self.assertEqual(builtin.targets("png"), [])


if __name__ == "__main__":
    unittest.main()
