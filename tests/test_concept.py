import pytest
import yaml

from spineforge.concept import ConceptError, list_concepts, load_concept, parse_concept


def minimal() -> dict:
    return {
        "id": "t",
        "canvas": {"width": 64, "height": 64},
        "palette": {"a": "#ff0000", "b": "#00ff00"},
        "rig": {"unit": 2.0, "hip_height": 10, "torso": 4, "chest": 4, "neck": 1,
                "head": 4, "upper_arm": 3, "lower_arm": 3, "hand": 1,
                "thigh": 5, "shin": 5, "foot": 2, "shoulder_span": 2, "hip_span": 2},
        "parts": [
            {"name": "body", "bone": "torso", "shape": "capsule",
             "size": [4, 8], "color": "a", "order": 0, "tags": ["cloth"]},
            {"name": "face", "bone": "head", "shape": "ellipse",
             "size": [4, 4], "color": "b", "order": 1, "redraw": False},
        ],
        "animations": ["idle"],
    }


def test_all_bundled_concepts_parse():
    concepts = list_concepts()
    assert {c.id for c in concepts} == {"aria_mage", "gale_ranger", "nox_knight"}
    for c in concepts:
        assert c.parts and c.animations and c.outfits


def test_pixel_size_derived_from_unit():
    c = parse_concept(minimal())
    # size 4x8 单位 * unit 2.0 + 两侧各 2px 留白
    assert c.part("body").pixel_size == (12, 20)


def test_draw_order_is_by_order_field():
    data = minimal()
    data["parts"][0]["order"] = 5
    c = parse_concept(data)
    assert [p.name for p in c.draw_order()] == ["face", "body"]


def test_duplicate_order_rejected():
    data = minimal()
    data["parts"][1]["order"] = 0
    with pytest.raises(ConceptError, match="order 必须唯一"):
        parse_concept(data)


def test_unknown_color_rejected():
    data = minimal()
    data["parts"][0]["color"] = "nope"
    with pytest.raises(ConceptError, match="不在 palette"):
        parse_concept(data)


def test_outfit_targets_filter_redraw_parts():
    data = minimal()
    data["parts"].append({"name": "boot", "bone": "foot_l", "shape": "plate",
                          "size": [3, 2], "color": "a", "order": 2, "tags": ["shoe"]})
    data["outfits"] = {"o": {"prompt": "x", "targets": ["cloth"]}}
    c = parse_concept(data)
    # face 被 redraw=false 排除，boot 因为不带 cloth 标签被 targets 排除
    assert [p.name for p in c.redraw_parts(c.outfit("o"))] == ["body"]
    assert [p.name for p in c.redraw_parts(None)] == ["body", "boot"]


def test_unknown_outfit_lists_options():
    data = minimal()
    data["outfits"] = {"real": {"prompt": "x"}}
    c = parse_concept(data)
    with pytest.raises(ConceptError, match="real"):
        c.outfit("fake")


def test_schema_doc_covers_every_top_level_field(tmp_path):
    from pathlib import Path

    doc = Path("concepts/_schema.md").read_text(encoding="utf-8")
    raw = yaml.safe_load(Path("concepts/aria_mage.yaml").read_text(encoding="utf-8"))
    for key in raw:
        assert f"`{key}`" in doc, f"_schema.md 没有描述字段 {key}"
