"""UV 映射与回写的正确性测试。

这两步是整条流水线里唯一"错了也看不出报错"的地方——贴图会静默地被写歪，
所以这里用一个只有两个部件的极简骨架，逐像素地把往返关系钉死。
"""

import numpy as np
import pytest

from spineforge.config import Config
from spineforge.raster import (OCCLUDER_ID, TEXEL_DRAWN, alpha_state,
                               edges_from_ids, render_color, render_ctrl,
                               render_uv, uv_to_mask)
from spineforge.runtime import Skeleton
from spineforge.writeback import (NOT_WRITTEN, WRITTEN, apply_frame,
                                  flood_unwritten, initial_written,
                                  reject_unreliable, rgb_to_hsv_u8)

CANVAS = 64


def make_skeleton(second_x: float = 20.0) -> Skeleton:
    """两个 16x16 的方块：back 在左、front 在右，front 后画所以压在上面。"""
    data = {
        "skeleton": {},
        "bones": [{"name": "root"}],
        "slots": [
            {"name": "back", "bone": "root", "attachment": "back"},
            {"name": "front", "bone": "root", "attachment": "front"},
        ],
        "skins": [{"name": "default", "attachments": {
            "back": {"back": {"x": 0.0, "y": 0.0, "width": 16, "height": 16}},
            "front": {"front": {"x": second_x, "y": 0.0, "width": 16, "height": 16}},
        }}],
        "animations": {},
    }
    return Skeleton(data, (CANVAS / 2, CANVAS / 2))


def solid(size: int, color: tuple[int, int, int]) -> np.ndarray:
    tex = np.zeros((size, size, 4), dtype=np.uint8)
    tex[..., 0:3] = color
    tex[..., 3] = 255
    return tex


@pytest.fixture
def setup():
    sk = make_skeleton()
    textures = {"back": solid(16, (10, 20, 200)), "front": solid(16, (200, 20, 10))}
    states = {k: alpha_state(v, 5) for k, v in textures.items()}
    ids = {"back": 1, "front": 2}
    return sk, textures, states, ids


def test_uv_encodes_slot_and_texel(setup):
    sk, _, states, ids = setup
    uv = render_uv(sk, states, ids, CANVAS, CANVAS)

    # 每个部件都占满 16x16 个像素（1:1 映射，无缩放）
    assert np.count_nonzero((uv >> 24) == 1) == 16 * 16
    assert np.count_nonzero((uv >> 24) == 2) == 16 * 16
    # 纹素下标覆盖 0..255，说明整张贴图都被映射到了
    texels = uv[(uv >> 24) == 2] & 0xFFFFFF
    assert sorted(texels.tolist()) == list(range(256))


def test_occluder_blanks_pixels_instead_of_falling_through():
    """不重绘的部件必须把它盖住的像素置空，而不是让下层部件顶上来。"""
    sk = make_skeleton(second_x=0.0)  # front 完全盖住 back
    textures = {"back": solid(16, (10, 20, 200)), "front": solid(16, (200, 20, 10))}
    states = {k: alpha_state(v, 5) for k, v in textures.items()}

    covered = render_uv(sk, states, {"back": 1, "front": OCCLUDER_ID}, CANVAS, CANVAS)
    assert np.count_nonzero(covered) == 0

    exposed = render_uv(sk, states, {"back": 1, "front": 2}, CANVAS, CANVAS)
    assert np.count_nonzero((exposed >> 24) == 2) == 256


def test_only_undrawn_hides_already_written_texels(setup):
    sk, _, states, ids = setup
    states["front"][:8, :] = TEXEL_DRAWN
    uv = render_uv(sk, states, ids, CANVAS, CANVAS, only_undrawn=True)
    assert np.count_nonzero((uv >> 24) == 2) == 8 * 16
    assert np.count_nonzero((uv >> 24) == 1) == 256  # back 不受影响


def test_writeback_lands_on_the_right_texels(setup):
    """核心往返：屏幕上画一个渐变，回写后贴图上应当出现同样的渐变。"""
    sk, textures, states, ids = setup
    uv = render_uv(sk, states, ids, CANVAS, CANVAS)

    frame = np.zeros((CANVAS, CANVAS, 3), dtype=np.uint8)
    frame[..., 1] = np.arange(CANVAS, dtype=np.uint8)[:, None]   # 纵向渐变
    frame[..., 2] = np.arange(CANVAS, dtype=np.uint8)[None, :]   # 横向渐变

    written = {k: initial_written(v, 5) for k, v in textures.items()}
    cfg = Config()
    cfg.edge_reject_radius = 0  # 关掉边缘剔除，这里要验证的是映射本身
    stats = apply_frame(uv, frame, textures, written, {1: "back", 2: "front"}, cfg)

    assert stats.written > 0
    ys, xs = np.nonzero(uv)
    for y, x in list(zip(ys, xs))[::37]:
        value = uv[y, x]
        name = {1: "back", 2: "front"}[value >> 24]
        texel = int(value & 0xFFFFFF)
        got = textures[name].reshape(-1, 4)[texel, 0:3]
        assert tuple(got) == tuple(frame[y, x])


def test_a_texel_is_written_only_once(setup):
    sk, textures, states, ids = setup
    uv = render_uv(sk, states, ids, CANVAS, CANVAS)
    written = {k: initial_written(v, 5) for k, v in textures.items()}
    cfg = Config()
    cfg.edge_reject_radius = 0

    first = np.full((CANVAS, CANVAS, 3), 111, dtype=np.uint8)
    second = np.full((CANVAS, CANVAS, 3), 222, dtype=np.uint8)
    apply_frame(uv, first, textures, written, {1: "back", 2: "front"}, cfg)
    stats = apply_frame(uv, second, textures, written, {1: "back", 2: "front"}, cfg)

    assert stats.written == 0
    assert stats.rejected_dup > 0
    assert (textures["front"][..., 0] == 111).all()


def test_edge_pixels_are_rejected(setup):
    """两个部件贴在一起时，交界处的像素不该被写回任何一边。"""
    sk = make_skeleton(second_x=16.0)  # 紧贴，无重叠
    textures = {"back": solid(16, (10, 20, 200)), "front": solid(16, (200, 20, 10))}
    states = {k: alpha_state(v, 5) for k, v in textures.items()}
    uv = render_uv(sk, states, {"back": 1, "front": 2}, CANVAS, CANVAS)

    frame = np.zeros((CANVAS, CANVAS, 3), dtype=np.uint8)
    for q in sk.quads():
        lo = q.corners.min(axis=0).astype(int)
        hi = q.corners.max(axis=0).astype(int)
        frame[lo[1]:hi[1], lo[0]:hi[0]] = (200, 20, 10) if q.slot == "front" else (10, 20, 200)

    cfg = Config()
    filtered = reject_unreliable(uv, frame, cfg)
    assert np.count_nonzero(filtered) < np.count_nonzero(uv)
    # 部件正中间的像素必须活下来，否则剔除得太狠了
    center = sk.quads()[1].corners.mean(axis=0).astype(int)
    assert filtered[center[1], center[0]] != 0


def test_flood_fills_untouched_texels():
    tex = solid(8, (255, 255, 255))
    written = np.full((8, 8), NOT_WRITTEN, dtype=np.uint8)
    written[0, 0] = WRITTEN
    tex[0, 0, 0:3] = (10, 200, 30)

    filled = flood_unwritten(tex, written)
    assert filled == 63
    assert not (tex[..., 0:3] == 255).all()
    assert (written != NOT_WRITTEN).all()


def test_cleaned_outliner_pixels_go_back_to_unwritten():
    """被刷白的孤立描边必须退回"未写入"，否则收尾的邻域扩散补不到它们。"""
    from spineforge.writeback import clean_outliner

    # 洗白后的贴图是纯白的，只剩描边有颜色
    tex = solid(9, (255, 255, 255))
    tex[4, 4, 0:3] = (20, 20, 20)      # 一个孤立的深色描边点
    written = np.full((9, 9), WRITTEN, dtype=np.uint8)

    assert clean_outliner(tex, written) == 1
    assert tuple(tex[4, 4, 0:3]) == (255, 255, 255)
    assert written[4, 4] == NOT_WRITTEN
    assert (written[written != NOT_WRITTEN] == WRITTEN).all()

    # 退回未写入之后，扩散能把它填上邻居的颜色
    tex[4, 5, 0:3] = (10, 120, 200)
    flood_unwritten(tex, written)
    assert tuple(tex[4, 4, 0:3]) != (255, 255, 255)


def test_mask_and_edges_derive_from_ids(setup):
    sk, _, states, ids = setup
    uv = render_uv(sk, states, ids, CANVAS, CANVAS)
    mask = uv_to_mask(uv)
    assert set(np.unique(mask).tolist()) == {0, 255}
    assert np.count_nonzero(mask) == np.count_nonzero(uv)

    # 两块紧贴的部件：分到同一组时中间的接缝应当消失
    adjacent = make_skeleton(second_x=16.0)
    grouped = edges_from_ids(render_ctrl(adjacent, states, {"back": 1, "front": 1},
                                         CANVAS, CANVAS))
    split = edges_from_ids(render_ctrl(adjacent, states, {"back": 1, "front": 2},
                                       CANVAS, CANVAS))
    # 分到同一组的部件之间不该出现边界线
    assert np.count_nonzero(grouped) < np.count_nonzero(split)


def test_color_render_respects_draw_order(setup):
    sk = make_skeleton(second_x=0.0)
    textures = {"back": solid(16, (10, 20, 200)), "front": solid(16, (200, 20, 10))}
    img = render_color(sk, textures, CANVAS, CANVAS)
    assert tuple(img[CANVAS // 2, CANVAS // 2, 0:3]) == (200, 20, 10)


def test_hsv_conversion_matches_colorsys():
    import colorsys

    rgb = np.array([[[255, 0, 0], [0, 255, 0], [10, 20, 30], [255, 255, 255]]], dtype=np.uint8)
    hsv = rgb_to_hsv_u8(rgb)
    for i in range(rgb.shape[1]):
        r, g, b = rgb[0, i] / 255.0
        want = np.array(colorsys.rgb_to_hsv(r, g, b)) * 255.0
        assert hsv[0, i] == pytest.approx(want, abs=1.5)
