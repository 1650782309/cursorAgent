"""角色设定集读取测试。

设定集的 README 写明色号与头身比只在 ``tools/palettes.json`` 中维护，
所以这里重点确认两件事：配色确实是从那份 JSON 现取的（没被复制到别处），
以及头身比真的会改变骨架。
"""

import json
from pathlib import Path

import pytest

from spineforge.bible import BibleError, derive_rig, get_character, load_bible
from spineforge.concept import ConceptError, load_concept, parse_concept

BIBLE_JSON = Path("tools/palettes.json")


def test_every_bible_character_is_loadable():
    bible = load_bible()
    assert set(bible) == {
        "kirimicho/akari", "kirimicho/sumi", "kirimicho/sae",
        "kirimicho/shinobu", "icarus/icarus",
    }


def test_palette_keys_come_from_the_english_group_labels():
    akari = get_character("kirimicho/akari")
    # "头发 Hair" 的三个色板 -> hair / hair_2 / hair_3
    assert akari.palette["hair"] == "#E8703A"
    assert akari.palette["hair_2"] == "#B84E27"
    assert akari.palette["hair_3"] == "#FFA168"
    # "服装 Costume" 按设定集里的顺序：制服 / 制服影 / 半纏 / 半纏影 / 家纹
    assert akari.palette["costume"] == "#2C3E63"
    assert akari.palette["costume_3"] == "#35547E"
    assert akari.uses["costume_3"] == "半纏"


def test_metrics_are_parsed_from_the_subtitle():
    akari = get_character("kirimicho/akari")
    assert (akari.height_cm, akari.heads) == (156.0, 6.8)
    assert akari.silhouette == "半纏 + 呆毛"
    # 伊卡洛斯的企划没写 proportions 表，身高头身比仍应从 subtitle 读出来
    icarus = get_character("icarus/icarus")
    assert (icarus.height_cm, icarus.heads) == (168.0, 8.0)


def test_colors_are_read_from_json_not_copied(tmp_path):
    """改了数据源，概念的配色必须跟着变——否则说明色号在某处被复制了。"""
    data = json.loads(BIBLE_JSON.read_text(encoding="utf-8"))
    groups = data["works"]["kirimicho"]["characters"]["akari"]["groups"]
    groups[0]["swatches"][0]["hex"] = "#00FF00"
    patched = tmp_path / "palettes.json"
    patched.write_text(json.dumps(data), encoding="utf-8")

    raw = {"id": "t", "bible": "kirimicho/akari",
           "canvas": {"width": 64, "height": 64},
           "parts": [{"name": "p", "bone": "torso", "shape": "capsule",
                      "size": [0.5, 1.0], "color": "hair", "order": 0}],
           "animations": ["idle"]}
    concept = parse_concept(raw, bible_path=patched)
    assert concept.palette["hair"] == "#00FF00"


def test_unknown_bible_reference_lists_what_exists():
    with pytest.raises(BibleError, match="kirimicho/akari"):
        get_character("kirimicho/nobody")


def test_alias_error_lists_the_available_swatches():
    raw = {"id": "t", "bible": "kirimicho/akari",
           "canvas": {"width": 64, "height": 64},
           "aliases": {"hanten": "costume_99"},
           "parts": [{"name": "p", "bone": "torso", "shape": "capsule",
                      "size": [0.5, 1.0], "color": "hair", "order": 0}],
           "animations": ["idle"]}
    with pytest.raises(ConceptError) as exc:
        parse_concept(raw)
    # 报错要能直接照着改：列出键和设定集里写的用途
    assert "costume_3(半纏)" in str(exc.value)


def test_head_count_drives_leg_length():
    """头身比越大腿越长，这是头身比的定义，也是骨架必须体现出来的。"""
    short = derive_rig(heads=5.5, height_cm=142, px_per_cm=2.4)
    tall = derive_rig(heads=8.0, height_cm=168, px_per_cm=2.4)
    assert short["hip_height"] == pytest.approx(2.4)
    assert tall["hip_height"] == pytest.approx(4.9)
    # 躯干链恒定占 3.1 个头长，所以全身正好是 heads 个头长
    for rig, heads in ((short, 5.5), (tall, 8.0)):
        total = rig["hip_height"] + rig["torso"] + rig["chest"] + rig["neck"] + rig["head"]
        assert total == pytest.approx(heads)


def test_unit_reflects_real_world_height():
    """身高不同的角色画在同一块画布上，像素高度必须按真实身高比例。"""
    sumi = load_concept("sumi")
    shinobu = load_concept("shinobu")
    sumi_px = sumi.rig["unit"] * sumi.bible.heads
    shinobu_px = shinobu.rig["unit"] * shinobu.bible.heads
    assert sumi_px / shinobu_px == pytest.approx(178 / 142, abs=1e-6)


def test_impossible_head_count_is_rejected():
    with pytest.raises(BibleError, match="躯干链"):
        derive_rig(heads=3.0, height_cm=100, px_per_cm=2.4)
