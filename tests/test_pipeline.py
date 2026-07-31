"""端到端：概念 -> 贴图/骨架 -> 关键姿势 -> mock 换装。

跑的是真实角色概念，只是把产物目录换到 tmp_path，所以这套测试同时也是
"整条流水线还能不能跑"的冒烟测试。
"""

import json

import numpy as np
import pytest
from PIL import Image

from spineforge import pipeline
from spineforge.concept import load_concept
from spineforge.config import Config


@pytest.fixture(scope="module")
def built(tmp_path_factory):
    cfg = Config()
    cfg.build_dir = str(tmp_path_factory.mktemp("build"))
    # 关键姿势扫描是整套测试里最慢的一步，采样放粗、轮次减少
    cfg.keypose_sample_step = 0.25
    cfg.keypose_max_count = 4
    concept = load_concept("sae", cfg)
    pipeline.build(concept, cfg)
    return concept, cfg


def test_build_writes_one_texture_per_part(built):
    concept, cfg = built
    images = sorted(p.stem for p in cfg.images_dir(concept.id).glob("*.png"))
    assert images == sorted(p.name for p in concept.parts)
    assert (cfg.character_dir(concept.id) / "skeleton.json").is_file()
    assert (cfg.images_dir(concept.id) / "fake.atlas").is_file()


def test_skeleton_json_is_loadable_and_complete(built):
    concept, cfg = built
    data = json.loads((cfg.character_dir(concept.id) / "skeleton.json").read_text())
    assert data["skeleton"]["spine"].startswith("3.8")
    assert len(data["slots"]) == len(concept.parts)
    assert set(data["animations"]) == set(concept.animations)
    slot_bones = {s["bone"] for s in data["slots"]}
    assert slot_bones <= {b["name"] for b in data["bones"]}


def test_every_part_is_visible_in_rest_pose(built):
    """概念里配的偏移如果写错，部件会飞出画布——这里逐个部件确认它在画面内。"""
    concept, cfg = built
    sk = pipeline.load_skeleton(concept, cfg)
    sk.pose()
    for quad in sk.quads():
        center = quad.corners.mean(axis=0)
        assert 0 <= center[0] <= concept.canvas.width, quad.slot
        assert 0 <= center[1] <= concept.canvas.height, quad.slot


def test_preprocess_selects_poses_and_reports_coverage(built):
    concept, cfg = built
    outfit = concept.outfit("combat_suit")
    manifest = pipeline.preprocess(concept, outfit, cfg)

    sequence = manifest["sequence"]
    assert sequence[0]["name"] == "restPose"
    assert len(sequence) >= 2
    # 贪心选取的收益必须递减，否则说明"已画"标记没生效
    gains = [p["new_texels"] for p in sequence]
    assert gains == sorted(gains, reverse=True)
    assert 0.0 < manifest["coverage"]["overall"] <= 1.0

    out = pipeline.redraw_dir(concept, outfit, cfg)
    for pose in sequence:
        for suffix in ("uv.npy", "@mask.png", "@ctrl.png", "@canny.png"):
            sep = "." if suffix.endswith("npy") else ""
            assert (out / f"{pose['name']}{sep}{suffix}").is_file()


def test_ids_cover_redraw_parts_and_occlude_the_rest(built):
    concept, cfg = built
    outfit = concept.outfit("combat_suit")
    manifest = pipeline.ensure_preprocess(concept, outfit, cfg)
    ids = manifest["ids"]

    redraw = {p.name for p in concept.redraw_parts(outfit)}
    assert {n for n, i in ids.items() if i != 0} == redraw
    assert len(set(ids[n] for n in redraw)) == len(redraw)  # ID 不能撞
    # 脸和头发必须是遮挡体，不然会被 SD 改掉
    assert ids["head_base"] == 0 and ids["front_hair"] == 0
    # 冴的配色纪律：全身只允许一处红（臂章），所以它也必须锁死
    assert ids["red_armband"] == 0


def test_reskin_repaints_cloth_and_leaves_the_face_alone(built):
    concept, cfg = built
    outfit = concept.outfit("combat_suit")
    before = pipeline.load_textures(cfg.images_dir(concept.id))

    result = pipeline.reskin(concept, outfit, seed=7, backend_name="mock",
                             cfg=cfg, keep_steps=False)
    after = pipeline.load_textures(result.out_dir / "images")

    assert result.written_texels > 0
    assert set(after) == set(before)
    # 保形部件必须逐像素不变
    for name in ("head_base", "front_hair", "red_armband"):
        assert np.array_equal(after[name], before[name])
    # 衣服部件必须整体换色，且不留白洞
    for name in ("coat_body", "coat_sleeve_l", "coat_skirt"):
        assert not np.array_equal(after[name], before[name])
        opaque = after[name][..., 3] > 5
        still_white = (after[name][..., 0:3] == 255).all(axis=-1) & opaque
        assert still_white.mean() < 0.02, f"{name} 还有 {still_white.mean():.1%} 的白斑"
    # alpha 通道不能被动过，否则轮廓会变
    for name in after:
        assert np.array_equal(after[name][..., 3], before[name][..., 3])


def test_reskin_is_deterministic_for_a_given_seed(built):
    concept, cfg = built
    outfit = concept.outfit("grey_turtleneck")
    a = pipeline.reskin(concept, outfit, seed=3, backend_name="mock", cfg=cfg,
                        keep_steps=False)
    tex_a = pipeline.load_textures(a.out_dir / "images")
    b = pipeline.reskin(concept, outfit, seed=3, backend_name="mock", cfg=cfg,
                        keep_steps=False)
    tex_b = pipeline.load_textures(b.out_dir / "images")
    for name in tex_a:
        assert np.array_equal(tex_a[name], tex_b[name])


def test_different_outfits_produce_different_skins(built):
    concept, cfg = built
    combat = pipeline.reskin(concept, concept.outfit("combat_suit"), seed=5,
                             backend_name="mock", cfg=cfg, keep_steps=False)
    casual = pipeline.reskin(concept, concept.outfit("grey_turtleneck"), seed=5,
                             backend_name="mock", cfg=cfg, keep_steps=False)
    a = pipeline.load_textures(combat.out_dir / "images")["coat_body"]
    b = pipeline.load_textures(casual.out_dir / "images")["coat_body"]
    assert not np.array_equal(a, b)


def test_preview_renders_a_gif(built):
    concept, cfg = built
    out = cfg.character_dir(concept.id) / "preview" / "walk.gif"
    pipeline.preview(concept, "walk", cfg.images_dir(concept.id), out, cfg, fps=6)
    with Image.open(out) as gif:
        assert gif.n_frames >= 2
        assert gif.size == (concept.canvas.width, concept.canvas.height)
