"""安装自检的测试。

doctor 是本地部署时用户看到的第一个东西，它自己出错会把人带偏，
所以每条判定都要有测试兜着——尤其是"该报错的时候必须报错"。
"""

import json

import pytest

from spineforge import doctor
from spineforge.config import Config
from spineforge.doctor import FAIL, OK, WARN, Check


@pytest.fixture
def cfg(tmp_path):
    c = Config()
    c.build_dir = str(tmp_path / "build")
    return c


def status_of(checks, keyword):
    for c in checks:
        if keyword in c.title:
            return c
    raise AssertionError(f"没有名字含 {keyword!r} 的检查项：{[c.title for c in checks]}")


def test_clean_environment_passes(cfg):
    checks = doctor.run(cfg, probe_sd=False)
    assert all(c.status != FAIL for c in checks), [c for c in checks if c.status == FAIL]
    assert status_of(checks, "角色设定集").status == OK
    # 概念库要真的被解析过，不能只是看目录存在
    assert "5 个角色" in status_of(checks, "概念库").detail


def test_offline_run_does_not_touch_the_network(cfg, monkeypatch):
    """不加 --sd 时一个网络请求都不能发，否则离线机器上会卡住。"""
    import requests

    def explode(*a, **kw):
        raise AssertionError("doctor 在没有 --sd 时不应该访问网络")

    monkeypatch.setattr(requests, "get", explode)
    monkeypatch.setattr(requests, "post", explode)
    doctor.run(cfg, probe_sd=False)


def test_canvas_misalignment_is_reported(cfg):
    """画布不是 8*downscale 的倍数时必须警告——这会让回写整体错位。"""
    cfg.downscale = 7  # 448 和 576 都不是 56 的倍数
    check = status_of(doctor.run(cfg, probe_sd=False), "画布对齐")
    assert check.status == WARN
    assert "akari" in check.detail


def test_unwritable_build_dir_fails(cfg, tmp_path):
    blocker = tmp_path / "blocked"
    blocker.write_text("我是文件不是目录", encoding="utf-8")
    cfg.build_dir = str(blocker / "build")
    assert doctor.check_writable(cfg).status == FAIL


def test_broken_concept_is_surfaced(cfg, tmp_path):
    concepts = tmp_path / "concepts"
    concepts.mkdir()
    (concepts / "broken.yaml").write_text("id: broken\n", encoding="utf-8")
    cfg.concepts_dir = str(concepts)
    check = status_of(doctor.check_data(cfg), "概念库")
    assert check.status == FAIL
    assert "解析失败" in check.detail


class FakeResponse:
    def __init__(self, payload, status=200):
        self._payload = payload
        self.status = status

    def raise_for_status(self):
        if self.status >= 400:
            raise RuntimeError(self.status)

    def json(self):
        return self._payload


def fake_sd(monkeypatch, routes):
    """按 URL 后缀路由的假 WebUI；没配的路由一律抛错。"""
    import requests

    def get(url, timeout=None):
        for suffix, payload in routes.items():
            if url.endswith(suffix):
                return FakeResponse(payload)
        raise ConnectionError(url)

    monkeypatch.setattr(requests, "get", get)


def test_sd_probe_reports_a_healthy_setup(cfg, monkeypatch):
    cfg.sd_model = "meinapastel_v6Pastel.safetensors"
    fake_sd(monkeypatch, {
        "/sdapi/v1/sd-models": [{"title": "meinapastel_v6Pastel.safetensors [4679331655]"}],
        "/controlnet/model_list": {"model_list": [cfg.controlnet_canny_model]},
        "/sdapi/v1/upscalers": [{"name": "R-ESRGAN 4x+ Anime6B"}],
    })
    checks = doctor.check_stable_diffusion(cfg)
    assert [c.status for c in checks] == [OK, OK, OK, OK, OK]


def test_sd_probe_explains_a_missing_api(cfg, monkeypatch):
    fake_sd(monkeypatch, {})
    checks = doctor.check_stable_diffusion(cfg)
    assert checks[0].status == FAIL
    assert "--api" in checks[0].hint
    # API 都不通就别再往下查了，免得刷一屏无意义的错误
    assert len(checks) == 1


def test_sd_probe_detects_a_missing_controlnet_extension(cfg, monkeypatch):
    fake_sd(monkeypatch, {"/sdapi/v1/sd-models": [{"title": "any.safetensors"}]})
    check = status_of(doctor.check_stable_diffusion(cfg), "ControlNet 扩展")
    assert check.status == FAIL
    assert "sd-webui-controlnet" in check.hint


def test_sd_probe_lists_alternatives_when_the_canny_model_is_absent(cfg, monkeypatch):
    fake_sd(monkeypatch, {
        "/sdapi/v1/sd-models": [{"title": "any.safetensors"}],
        "/controlnet/model_list": {"model_list": ["control_v11p_sd15_openpose [abc]"]},
    })
    check = status_of(doctor.check_stable_diffusion(cfg), "canny 模型")
    assert check.status == FAIL
    # 报错要能直接照着改，所以得把现有的模型名列出来
    assert "control_v11p_sd15_openpose [abc]" in check.hint


def test_unpinned_model_is_a_warning_not_a_failure(cfg, monkeypatch):
    cfg.sd_model = ""
    fake_sd(monkeypatch, {
        "/sdapi/v1/sd-models": [{"title": "any.safetensors"}],
        "/controlnet/model_list": {"model_list": [cfg.controlnet_canny_model]},
        "/sdapi/v1/upscalers": [{"name": "R-ESRGAN 4x+ Anime6B"}],
    })
    check = status_of(doctor.check_stable_diffusion(cfg), "SD 模型")
    assert check.status == WARN
    assert "不可复现" in check.hint


def test_exit_code_follows_the_failures():
    passing = [Check(OK, "a"), Check(WARN, "b", hint="小心")]
    text, code = doctor.report(passing, probe_sd=False)
    assert code == 0 and "spineforge run" in text

    failing = [Check(OK, "a"), Check(FAIL, "b", "坏了", hint="这样修")]
    text, code = doctor.report(failing, probe_sd=True)
    assert code == 1
    assert "这样修" in text          # 修复建议必须出现在输出里
    assert "doctor --sd" not in text  # 已经查过 SD 了就别再提示


def test_cjk_titles_are_aligned():
    """中文标题占两列，用 len() 对齐会歪，输出看起来会很乱。"""
    text, _ = doctor.report([Check(OK, "角色设定集", "detail-a"), Check(OK, "ab", "detail-b")],
                            probe_sd=False)
    rows = [line for line in text.splitlines() if line.startswith("  [")]
    # 两行的 detail 必须落在同一列上
    starts = {doctor.display_width(row[:row.index("detail-")]) for row in rows}
    assert len(starts) == 1, text
