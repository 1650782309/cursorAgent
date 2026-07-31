import math

import numpy as np
import pytest

from spineforge.animation import animation_duration, build_animations
from spineforge.concept import load_concept
from spineforge.runtime import Skeleton
from spineforge.skeleton import build_bones, build_skeleton


@pytest.fixture(scope="module")
def concept():
    return load_concept("akari")


@pytest.fixture(scope="module")
def skeleton(concept):
    data = build_skeleton(concept)
    return Skeleton(data, (concept.canvas.origin_x, concept.canvas.origin_y))


def test_bone_hierarchy_is_parent_before_child(concept):
    seen = set()
    for b in build_bones(concept):
        assert b.parent is None or b.parent in seen
        seen.add(b.name)


def test_head_is_above_hip_in_canvas(skeleton):
    # 画布 y 轴向下，所以头的 y 应该更小
    head = skeleton.bones["head"]
    hip = skeleton.bones["hip"]
    assert head.wy > hip.wy  # Spine 世界坐标 y 向上


def test_limb_bones_point_downward(skeleton):
    """大腿骨的局部 +x 在世界里应该朝下，否则 attachment 会整条挂反。"""
    thigh = skeleton.bones["thigh_l"]
    assert thigh.c < -0.9  # 局部 x 轴的世界 y 分量接近 -1


def test_left_and_right_are_mirrored(skeleton):
    assert skeleton.bones["thigh_l"].wx < skeleton.bones["thigh_r"].wx


def test_attachment_quad_follows_its_bone(concept, skeleton):
    skeleton.pose()
    rest = {q.slot: q.corners.mean(axis=0) for q in skeleton.quads()}
    skeleton.pose("wave", 0.9)
    waving = {q.slot: q.corners.mean(axis=0) for q in skeleton.quads()}
    # 挥手时右臂抬起，右袖子必须跟着往上走（画布 y 减小）
    assert waving["hanten_sleeve_r"][1] < rest["hanten_sleeve_r"][1] - 5
    # 左腿没有参与，位置基本不动
    assert abs(waving["L_sock"][1] - rest["L_sock"][1]) < 1.0
    skeleton.pose()


def test_animation_keys_close_the_loop(concept):
    """循环动画的首尾关键帧必须一致，否则播放时会在接缝处抖一下。"""
    anims = build_animations(concept)
    for name in ("idle", "walk", "run"):
        for tracks in anims[name]["bones"].values():
            for channel, frames in tracks.items():
                first = {k: v for k, v in frames[0].items() if k != "time"}
                last = {k: v for k, v in frames[-1].items() if k != "time"}
                assert first == pytest.approx(last, abs=1e-3), (name, channel)


def test_pose_is_reset_between_calls(skeleton):
    skeleton.pose("run", 0.3)
    moved = skeleton.bones["thigh_l"].rotation
    skeleton.pose()
    rest = skeleton.bones["thigh_l"].rotation
    skeleton.pose("run", 0.3)
    assert skeleton.bones["thigh_l"].rotation == pytest.approx(moved)
    assert rest != pytest.approx(moved)
    skeleton.pose()


def test_timeline_interpolates_between_keys(skeleton):
    a = skeleton.duration("walk")
    assert a == pytest.approx(1.0)
    skeleton.pose("walk", 0.0)
    r0 = skeleton.bones["thigh_l"].rotation
    skeleton.pose("walk", 0.25)
    r1 = skeleton.bones["thigh_l"].rotation
    assert abs(r1 - r0) > 5
    skeleton.pose()


def test_duration_matches_generated_keys(concept):
    anims = build_animations(concept)
    assert animation_duration(anims["walk"]) == pytest.approx(1.0)
    assert animation_duration(anims["run"]) == pytest.approx(0.7)


def test_bounds_cover_every_animation(concept, skeleton):
    lo_x, lo_y, hi_x, hi_y = skeleton.bounds()
    assert 0 <= lo_x and 0 <= lo_y
    assert hi_x <= concept.canvas.width and hi_y <= concept.canvas.height
