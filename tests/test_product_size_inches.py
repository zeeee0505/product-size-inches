import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
import zipfile
from PIL import Image, ImageDraw, ImageFont

CLI = Path(sys.argv.pop(1)).resolve()

class Workflow(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.root = self.base / "商品空 格"
        self.chart = self.root / "🎁子目录" / "白底.jpg"
        self.chart.parent.mkdir(parents=True)
        self.other = self.root / "scene.png"
        self.work = self.base / "work"
        self.backup = self.base / "original.zip"
        self.plan = self.base / "edits.json"
        image = Image.new("RGB", (420, 320), "white")
        draw = ImageDraw.Draw(image)
        font = ImageFont.load_default(size=25)
        for at, s in [((97, 28), "22mm"), ((185, 92), "1.2cm"), ((43, 236), "Length:72+5cm")]:
            draw.text(at, s, font=font, fill="black")
        draw.ellipse((126, 140, 294, 219), fill=(234, 158, 32))
        draw.line((83, 82, 209, 54), fill="black", width=2)
        image.save(self.chart, quality=96, subsampling=0)
        image.save(self.other)
        self.original = self.chart.read_bytes()
        self.scene = self.other.read_bytes()
        self.relative = self.chart.relative_to(self.root).as_posix()
        self.edits = [
            {"source":"22mm","box":[77,18,200,54],"angle":0},
            {"source":"1.2cm","box":[161,82,291,129],"angle":14,"polygon":[[162,86],[289,86],[287,126],[163,127]]},
            {"source":"72+5cm","prefix":"Length:","box":[40,229,360,278]},
        ]

    def command(self, name, *args, succeeds=True):
        run = subprocess.run([sys.executable, "-X", "utf8", str(CLI), name, *map(str,args)], capture_output=True, text=True, encoding="utf-8")
        if succeeds:
            self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
        else:
            self.assertNotEqual(run.returncode, 0, run.stdout + run.stderr)
        return run

    def stage(self):
        self.plan.write_text(json.dumps({"images":[{"path":self.relative,"edits":self.edits}]}, ensure_ascii=False),encoding="utf-8")
        return self.command("stage", self.root, self.plan, self.work)

    def test_scan_includes_unexpected_name(self):
        self.command("scan", self.root, self.work)
        files=json.loads((self.work/"inventory.json").read_text(encoding="utf-8"))
        self.assertEqual({i["path"] for i in files}, {self.relative,"scene.png"})
        self.assertTrue((self.work / "scan-001.jpg").is_file())

    def test_preview_apply_changes_only_selected_photo_and_has_exact_backup(self):
        self.stage()
        self.assertEqual(self.chart.read_bytes(), self.original)
        manifest=json.loads((self.work/"staged.json").read_text(encoding="utf-8"))
        entry=manifest["images"][0]
        self.assertEqual(entry["labels"],["2.2 cm / 0.9 in","1.2 cm / 0.5 in","Length:72+5 cm / 28.3+2.0 in"])
        with Image.open(self.chart) as original, Image.open(self.work / entry["preview"]) as preview:
            self.assertEqual(original.crop((110,135,313,225)).tobytes(),preview.crop((110,135,313,225)).tobytes())
        self.command("apply", self.root, self.work, self.backup)
        self.assertNotEqual(self.chart.read_bytes(), self.original)
        self.assertEqual(self.other.read_bytes(), self.scene)
        with Image.open(self.chart) as image:
            self.assertEqual((image.format, image.size),("JPEG",(420,320)))
        with zipfile.ZipFile(self.backup) as archive:
            self.assertEqual(archive.namelist(), [self.relative])
            self.assertEqual(archive.read(self.relative), self.original)

    def test_unknown_units_stop_staging(self):
        self.edits[0]["source"]="0.32m"
        self.plan.write_text(json.dumps({"images":[{"path":self.relative,"edits":self.edits}]}),encoding="utf-8")
        out=self.command("stage", self.root, self.plan, self.work,succeeds=False)
        self.assertIn("Unsupported measurement",out.stderr)
        self.assertFalse((self.work/"staged.json").exists())
        self.assertEqual(self.chart.read_bytes(),self.original)

    def test_apply_rejects_stale_source(self):
        self.stage()
        with self.chart.open("ab") as image:
            image.write(b"new version")
        changed=self.chart.read_bytes()
        self.command("apply",self.root,self.work,self.backup,succeeds=False)
        self.assertEqual(self.chart.read_bytes(),changed)
        self.assertFalse(self.backup.exists())

    def test_apply_rejects_modified_stage(self):
        self.stage()
        manifest=json.loads((self.work/"staged.json").read_text(encoding="utf-8"))
        (self.work/manifest["images"][0]["staged"]).write_bytes(self.scene)
        self.command("apply",self.root,self.work,self.backup,succeeds=False)
        self.assertEqual(self.chart.read_bytes(),self.original)
        self.assertFalse(self.backup.exists())

    def test_export_preserves_paths_and_leaves_uploaded_inputs_unchanged(self):
        self.stage()
        bundle = self.base / "converted.zip"
        self.command("export", self.root, self.work, bundle)
        with zipfile.ZipFile(bundle) as archive:
            self.assertEqual(archive.namelist(), [self.relative])
            self.assertNotEqual(archive.read(self.relative), self.original)
        self.assertEqual(self.chart.read_bytes(), self.original)
        self.assertEqual(self.other.read_bytes(), self.scene)

    def test_narrow_label_can_stack_two_separate_visible_rows(self):
        self.edits = [{"source":"20mm","box":[75,16,194,76],"layout":"stacked","height":15}]
        self.stage()
        entry = json.loads((self.work / "staged.json").read_text(encoding="utf-8"))["images"][0]
        self.assertEqual(entry["labels"], ["2 cm /\n0.8 in"])
        with Image.open(self.work / entry["preview"]) as image:
            region = image.convert("L").crop((78, 18, 191, 57))
            rows = [r for r in range(region.height) if region.crop((0, r, region.width, r + 1)).getextrema()[0] < 80]
            self.assertTrue(any(a + 1 < b for a, b in zip(rows, rows[1:])), rows)

if __name__ == "__main__":
    unittest.main()
