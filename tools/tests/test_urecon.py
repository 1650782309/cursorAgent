"""烟雾测试：用合成样本覆盖识别 / 清点 / 计划 / 报告全链路。

样本是人造的最小结构，只为验证判定逻辑，不含任何真实游戏内容。
"""

from __future__ import annotations

import json
import unittest
import zipfile
from pathlib import Path
from tempfile import TemporaryDirectory

from urecon import fingerprint as fp_mod
from urecon import inventory as inv_mod
from urecon import plan as plan_mod
from urecon import report as report_mod
from urecon import workspace as ws_mod
from urecon.cli import main
from urecon.source import open_source

IL2CPP_MAGIC = b"\xaf\x1b\xb1\xfa"


def write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)


def make_il2cpp_game(root: Path, *, encrypted_metadata: bool = False,
                     encrypted_bundles: bool = False) -> Path:
    data = root / "Awesome_Data"
    write(data / "globalgamemanagers", b"\x00" * 20 + b"2022.3.16f1\x00" + b"\x00" * 64)
    write(data / "il2cpp_data" / "Metadata" / "global-metadata.dat",
          (b"\xde\xad\xbe\xef" if encrypted_metadata else IL2CPP_MAGIC)
          + (29).to_bytes(4, "little") + b"\x00" * 128)
    write(root / "GameAssembly.dll",
          b"MZ" + b"\x00" * 512 + b"HybridCLR_Interpreter\x00"
          + b"Cysharp.Threading.Tasks\x00" + b"UnityEngine.Rendering.Universal\x00"
          + b"YooAsset.AssetsPackage\x00" + b"\x00" * 512)
    write(root / "Awesome.exe", b"MZ" + b"\x00" * 128)
    bundle_head = b"\x11\x22\x33\x44" if encrypted_bundles else b"UnityFS"
    for i in range(3):
        write(data / "StreamingAssets" / "AssetBundles" / f"ui_{i}.bundle",
              bundle_head + b"\x00" * 9000)
    write(data / "StreamingAssets" / "catalog.json", b"{}" + b"\x00" * 5000)
    return root


def make_mono_game(root: Path) -> Path:
    data = root / "Retro_Data"
    write(data / "globalgamemanagers", b"\x00" * 20 + b"2019.4.40f1\x00" + b"\x00" * 64)
    write(data / "Managed" / "Assembly-CSharp.dll", b"MZ" + b"XLua.LuaEnv\x00" + b"\x00" * 4096)
    write(data / "Managed" / "mscorlib.dll", b"MZ" + b"\x00" * 128)
    write(data / "Managed" / "DOTween.dll", b"MZ" + b"\x00" * 128)
    write(data / "resources.assets", b"\x00" * 9000)
    return root


def make_apk(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("assets/bin/Data/globalgamemanagers", b"\x00" * 20 + b"2021.3.8f1\x00" + b"\x00" * 64)
        z.writestr("assets/bin/Data/il2cpp_data/Metadata/global-metadata.dat",
                   IL2CPP_MAGIC + (27).to_bytes(4, "little") + b"\x00" * 64)
        z.writestr("lib/arm64-v8a/libil2cpp.so", b"\x7fELF" + b"XLua.LuaEnv\x00" + b"\x00" * 4096)
        z.writestr("lib/arm64-v8a/libjiagu.so", b"\x7fELF" + b"\x00" * 128)
        z.writestr("assets/bin/Data/StreamingAssets/a.bundle", b"UnityFS" + b"\x00" * 9000)
    return path


class FingerprintTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = TemporaryDirectory()
        self.tmp = Path(self._tmp.name)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def analyze(self, path: Path) -> fp_mod.Fingerprint:
        return fp_mod.analyze(open_source(path))

    def test_il2cpp_dir(self):
        fp = self.analyze(make_il2cpp_game(self.tmp / "game"))
        self.assertEqual(fp.backend, "il2cpp")
        self.assertEqual(fp.unity_version, "2022.3.16f1")
        self.assertEqual(fp.platform, "windows")
        self.assertFalse(fp.metadata_encrypted)
        self.assertEqual(fp.metadata_version, 29)
        self.assertEqual(fp.bundle_encryption, "none")
        self.assertTrue(fp.has("hybridclr"), "应通过二进制字符串识别出 HybridCLR")
        self.assertTrue(fp.has("unitask"))
        self.assertTrue(fp.has("urp"))
        self.assertTrue(fp.has("yooasset"))
        self.assertTrue(fp.has("addressables"), "catalog.json 应命中 Addressables")
        self.assertTrue(fp.data_dir and fp.data_dir.endswith("_Data"))

    def test_encrypted_variant(self):
        fp = self.analyze(make_il2cpp_game(
            self.tmp / "enc", encrypted_metadata=True, encrypted_bundles=True))
        self.assertTrue(fp.metadata_encrypted)
        self.assertEqual(fp.bundle_encryption, "all")
        self.assertTrue(any("metadata" in w for w in fp.warnings))

    def test_mono_dir(self):
        fp = self.analyze(make_mono_game(self.tmp / "retro"))
        self.assertEqual(fp.backend, "mono")
        self.assertEqual(fp.unity_version, "2019.4.40f1")
        self.assertTrue(fp.has("xlua"))
        self.assertTrue(fp.has("dotween"))
        self.assertIn("Assembly-CSharp.dll", fp.managed_assemblies)

    def test_apk(self):
        fp = self.analyze(make_apk(self.tmp / "g.apk"))
        self.assertEqual(fp.source_kind, "apk")
        self.assertEqual(fp.platform, "android")
        self.assertIn("arm64-v8a", fp.architectures)
        self.assertEqual(fp.backend, "il2cpp")
        self.assertEqual(fp.unity_version, "2021.3.8f1")
        self.assertTrue(fp.has("jiagu"), "应识别出加固壳")
        self.assertTrue(any("加固" in w for w in fp.warnings))

    def test_fast_mode_skips_string_scan(self):
        game = make_il2cpp_game(self.tmp / "fast")
        fp = fp_mod.analyze(open_source(game), deep=False)
        self.assertFalse(fp.has("hybridclr"), "fast 模式不做字符串扫描")
        self.assertTrue(fp.has("addressables"), "文件名证据仍然生效")


class PlanTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = TemporaryDirectory()
        self.tmp = Path(self._tmp.name)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_il2cpp_plan_mentions_dumper(self):
        fp = fp_mod.analyze(open_source(make_il2cpp_game(self.tmp / "g")))
        titles = [s.title for s in plan_mod.build(fp)]
        self.assertTrue(any("Il2CppDumper" in t for t in titles))
        self.assertTrue(any("热更层" in t for t in titles))

    def test_encrypted_metadata_plan_prefers_memory_dump(self):
        fp = fp_mod.analyze(open_source(
            make_il2cpp_game(self.tmp / "g", encrypted_metadata=True)))
        titles = [s.title for s in plan_mod.build(fp)]
        self.assertEqual(titles[0], "从内存 dump metadata")

    def test_mono_plan_uses_ilspy(self):
        fp = fp_mod.analyze(open_source(make_mono_game(self.tmp / "m")))
        cmds = " ".join(c for s in plan_mod.build(fp) for c in s.commands)
        self.assertIn("ilspycmd", cmds)
        self.assertNotIn("Il2CppDumper", cmds)

    def test_apk_plan_starts_with_unpack(self):
        fp = fp_mod.analyze(open_source(make_apk(self.tmp / "g.apk")))
        self.assertEqual(plan_mod.build(fp)[0].title, "解包 APK")


class InventoryTest(unittest.TestCase):
    def test_file_level_scan_always_works(self):
        with TemporaryDirectory(ignore_cleanup_errors=True) as td:
            game = make_il2cpp_game(Path(td) / "g")
            inv = inv_mod.scan(open_source(game))
            self.assertTrue(inv.containers)
            paths = [c.path for c in inv.containers]
            self.assertTrue(any(p.endswith("ui_0.bundle") for p in paths))
            files = inv_mod.write_csv(inv, Path(td) / "out")
            self.assertTrue(all(f.exists() for f in files))


class ReportTest(unittest.TestCase):
    def test_render_contains_manual_sections(self):
        with TemporaryDirectory() as td:
            fp = fp_mod.analyze(open_source(make_il2cpp_game(Path(td) / "g")))
            md = report_mod.render(fp, None, plan_mod.build(fp))
            self.assertIn("## 5. 三个「我没想到」", md)
            self.assertIn("## 6. 可迁移清单", md)
            self.assertIn("2022.3.16f1", md)
            self.assertIn("HybridCLR", md)

    def test_compare_table(self):
        rows = [{"target": "/x/A", "unity_version": "2022.3.1f1", "backend": "il2cpp",
                 "platform": "android", "total_bytes": 1 << 30,
                 "frameworks": [{"name": "HybridCLR", "category": "hotfix"}]}]
        md = report_mod.render_compare(rows)
        self.assertIn("| A |", md)
        self.assertIn("HybridCLR", md)


class CliTest(unittest.TestCase):
    def test_full_pipeline(self):
        with TemporaryDirectory() as td:
            root = Path(td)
            game = make_il2cpp_game(root / "game")
            ws_dir = root / "targets" / "awesome"

            self.assertEqual(main(["init", str(ws_dir), "--source", str(game)]), 0)
            self.assertTrue((ws_dir / "urecon.json").exists())
            self.assertTrue((ws_dir / "decompiled").is_dir())

            self.assertEqual(main(["fingerprint", str(ws_dir)]), 0)
            saved = json.loads((ws_dir / "notes" / "fingerprint.json").read_text(encoding="utf-8"))
            self.assertEqual(saved["backend"], "il2cpp")

            self.assertEqual(main(["inventory", str(ws_dir)]), 0)
            self.assertTrue((ws_dir / "notes" / "containers.csv").exists())

            self.assertEqual(main(["plan", str(ws_dir)]), 0)
            self.assertEqual(main(["report", str(ws_dir)]), 0)
            self.assertIn("逆向学习报告", (ws_dir / "notes" / "report.md").read_text(encoding="utf-8"))

            out = root / "compare.md"
            self.assertEqual(main(["compare", str(ws_dir / "urecon.json"), "-o", str(out)]), 0)
            self.assertIn("横向对比", out.read_text(encoding="utf-8"))

    def test_raw_path_without_workspace(self):
        with TemporaryDirectory() as td:
            game = make_mono_game(Path(td) / "m")
            self.assertEqual(main(["fingerprint", str(game), "--json"]), 0)

    def test_missing_target_returns_error_code(self):
        self.assertEqual(main(["fingerprint", "/definitely/not/here"]), 2)

    def test_workspace_resolve_roundtrip(self):
        with TemporaryDirectory() as td:
            root = Path(td)
            game = make_mono_game(root / "m")
            ws_mod.init(root / "ws", game)
            ws = ws_mod.resolve(root / "ws")
            self.assertEqual(ws.source, game.resolve())


if __name__ == "__main__":
    unittest.main(verbosity=2)
