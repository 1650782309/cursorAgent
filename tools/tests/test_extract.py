"""分类与提取相关测试（不依赖真实游戏资源）。"""

from __future__ import annotations

import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

from urecon.classify import (
    CATEGORY_DIRS,
    AssetHint,
    classify_asset,
    common_prefix,
    link_clips_to_models,
)
from urecon.exporters import Exporter, discover
from urecon.extract import ExtractReport, _safe, _unique_dir, extract
from urecon.source import DirSource


class ClassifyTest(unittest.TestCase):
    def test_character_by_skin_and_bones(self):
        h = AssetHint(
            name="Hero_LOD0",
            container="assets/characters/hero.bundle",
            asset_type="SkinnedMeshRenderer",
            bone_count=55,
            has_skin=True,
            is_humanoid=True,
            clip_names=["Hero_Idle", "Hero_Run", "Hero_Attack01"],
        )
        c = classify_asset(h)
        self.assertEqual(c.category, "character")
        self.assertEqual(c.label, "人物")
        self.assertIn(c.confidence, {"high", "medium"})

    def test_item_by_path_and_size(self):
        h = AssetHint(
            name="sword_01",
            container="AssetBundles/weapons/sword_01.bundle",
            asset_type="Mesh",
            vertex_count=320,
            has_skin=False,
        )
        c = classify_asset(h)
        self.assertEqual(c.category, "item")
        self.assertEqual(c.label, "物品")

    def test_scene_by_keywords(self):
        h = AssetHint(
            name="town_gate",
            container="StreamingAssets/scenes/town_gate.bundle",
            asset_type="Mesh",
            vertex_count=80_000,
            has_skin=False,
        )
        c = classify_asset(h)
        self.assertEqual(c.category, "scene")
        self.assertEqual(c.label, "场景")

    def test_ui_and_fx(self):
        ui = classify_asset(AssetHint("btn_ok", "ui_hud.bundle", "Sprite"))
        self.assertEqual(ui.category, "ui")
        fx = classify_asset(AssetHint("hit_spark", "fx/combat.bundle", "ParticleSystem"))
        self.assertEqual(fx.category, "fx")

    def test_chinese_keywords(self):
        h = AssetHint("灯莉", "资源/角色/灯莉.bundle", "SkinnedMeshRenderer", has_skin=True, bone_count=20)
        self.assertEqual(classify_asset(h).category, "character")

    def test_link_clips_by_prefix(self):
        models = [
            AssetHint("Hero", "a.bundle", "SkinnedMeshRenderer", has_skin=True),
            AssetHint("Slime", "b.bundle", "SkinnedMeshRenderer", has_skin=True),
        ]
        clips = [
            AssetHint("Hero_Idle", "a.bundle", "AnimationClip"),
            AssetHint("Hero_Run", "a.bundle", "AnimationClip"),
            AssetHint("Slime_Jump", "b.bundle", "AnimationClip"),
            AssetHint("orphan_clip", "c.bundle", "AnimationClip"),
        ]
        links = link_clips_to_models(models, clips)
        self.assertIn("Hero_Idle", links["Hero"])
        self.assertIn("Slime_Jump", links["Slime"])
        self.assertNotIn("orphan_clip", links["Hero"])

    def test_common_prefix(self):
        self.assertEqual(common_prefix(["Hero_Idle", "Hero_Run"]), "Hero")
        self.assertIsNone(common_prefix(["ab", "xy"]))


class ExtractHelpersTest(unittest.TestCase):
    def test_safe_and_unique_dir(self):
        self.assertEqual(_safe("Hero/01"), "Hero_01")
        with TemporaryDirectory() as td:
            root = Path(td)
            a = _unique_dir(root, "Hero")
            b = _unique_dir(root, "Hero")
            self.assertNotEqual(a, b)
            self.assertTrue(a.is_dir() and b.is_dir())

    def test_discover_none_without_tools(self):
        with TemporaryDirectory() as td:
            exp = discover(Path(td))
            self.assertEqual(exp.kind, "none")
            self.assertFalse(exp.available)

    def test_discover_env(self):
        with TemporaryDirectory() as td:
            fake = Path(td) / "AssetStudio.CLI.exe"
            fake.write_bytes(b"MZ")
            with mock.patch.dict("os.environ", {"URECON_ASSETSTUDIO": str(fake)}):
                exp = discover(Path(td) / "empty")
            self.assertEqual(exp.kind, "assetstudio")
            self.assertEqual(exp.path, fake)


class ExtractPipelineTest(unittest.TestCase):
    def test_classify_only_on_empty_scan(self):
        """没有可读 Unity 资源时，扫描为空，仍应写出清单结构。"""
        with TemporaryDirectory() as td:
            root = Path(td)
            game = root / "game"
            game.mkdir()
            (game / "dummy.txt").write_text("x", encoding="utf-8")
            out = root / "out"

            # 空容器扫描：UnityPy 可能未装，assetscan 会抛；用 mock 掉 scan
            fake_scan = mock.Mock()
            fake_scan.models = [
                AssetHint(
                    "Hero", "chars/hero.bundle", "SkinnedMeshRenderer",
                    bone_count=40, has_skin=True, is_humanoid=True,
                    clip_names=["Hero_Idle"],
                ),
                AssetHint(
                    "sword", "items/sword.bundle", "Mesh",
                    vertex_count=200, has_skin=False,
                ),
                AssetHint(
                    "house", "scenes/town.bundle", "Mesh",
                    vertex_count=50_000, has_skin=False,
                ),
            ]
            fake_scan.clips = []
            fake_scan.textures = []
            fake_scan.others = []
            fake_scan.errors = []
            fake_scan.clip_links = {"Hero": ["Hero_Idle"]}

            with mock.patch("urecon.extract.assetscan.scan", return_value=fake_scan), \
                 mock.patch("urecon.extract.discover", return_value=Exporter("none", None, ["no tool"])):
                report = extract(
                    DirSource(game), out,
                    format="classify-only", prefer="obj",
                )

            self.assertEqual(report.counts.get("character"), 1)
            self.assertEqual(report.counts.get("item"), 1)
            self.assertEqual(report.counts.get("scene"), 1)
            self.assertTrue((out / "models" / "人物").exists())
            self.assertTrue((out / "models" / "物品").exists())
            self.assertTrue((out / "models" / "场景").exists())
            index = json.loads((out / "models" / "_index.json").read_text(encoding="utf-8"))
            self.assertEqual(len(index["items"]), 3)
            # meta.json 应存在
            hero_dirs = list((out / "models" / "人物").iterdir())
            self.assertTrue(any((d / "meta.json").exists() for d in hero_dirs if d.is_dir()))


class CliExtractTest(unittest.TestCase):
    def test_extract_help_and_doctor(self):
        from urecon.cli import main
        self.assertEqual(main(["doctor"]), 1)  # 通常无 AssetStudio → 1


if __name__ == "__main__":
    unittest.main(verbosity=2)
