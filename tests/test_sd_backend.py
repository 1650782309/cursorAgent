"""SD 后端测试。

WebUI 那条路径平时跑不到（CI 上没有显卡也没有 WebUI），但它恰恰是最容易
悄悄写错的地方——payload 里有几个字段一旦搞错，出来的图和 mask 就对不上，
而且不会报错，只会让贴图整体错位。所以这里起一个假的 WebUI 把请求体检查一遍。
"""

import base64
import io
import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import numpy as np
import pytest
from PIL import Image

from spineforge.concept import load_concept
from spineforge.config import Config
from spineforge.sd import MockBackend, RedrawRequest, WebUIBackend, get_backend

SIZE = (32, 48)


def make_request(seed: int = 1) -> RedrawRequest:
    mask = np.zeros((SIZE[1], SIZE[0]), dtype=np.uint8)
    mask[8:40, 4:28] = 255
    return RedrawRequest(
        image=Image.new("RGB", SIZE, (240, 240, 250)),
        mask=Image.fromarray(mask, mode="L"),
        control=Image.new("L", SIZE, 0),
        prompt="new outfit",
        negative_prompt="bad",
        seed=seed,
        denoising_strength=0.7,
    )


@pytest.fixture(scope="module")
def concept():
    return load_concept("aria_mage")


# ----------------------------------------------------------------- mock 后端
def test_mock_only_touches_the_masked_region(concept):
    backend = MockBackend(concept, concept.outfit("starlight_robe"))
    req = make_request()
    out = np.asarray(backend.redraw(req))
    src = np.asarray(req.image)
    mask = np.asarray(req.mask) > 127

    assert np.array_equal(out[~mask], src[~mask])
    assert not np.array_equal(out[mask], src[mask])
    assert out.shape == src.shape


def test_mock_is_seed_deterministic(concept):
    backend = MockBackend(concept, concept.outfit("starlight_robe"))
    a = np.asarray(backend.redraw(make_request(seed=4)))
    b = np.asarray(backend.redraw(make_request(seed=4)))
    c = np.asarray(backend.redraw(make_request(seed=5)))
    assert np.array_equal(a, b)
    assert not np.array_equal(a, c)


def test_mock_handles_an_empty_mask(concept):
    backend = MockBackend(concept, concept.outfit("starlight_robe"))
    req = make_request()
    req.mask = Image.new("L", SIZE, 0)
    assert np.array_equal(np.asarray(backend.redraw(req)), np.asarray(req.image))


def test_outfit_without_palette_hint_still_works(concept):
    from spineforge.concept import Outfit

    backend = MockBackend(concept, Outfit(name="x", prompt="p"))
    out = backend.redraw(make_request())
    assert out.size == SIZE


# ---------------------------------------------------------------- webui 后端
class FakeWebUI(BaseHTTPRequestHandler):
    payloads: list[dict] = []

    def do_POST(self):  # noqa: N802
        body = self.rfile.read(int(self.headers["Content-Length"]))
        payload = json.loads(body)
        FakeWebUI.payloads.append({"path": self.path, "body": payload})

        if self.path.endswith("/options"):
            self._reply({})
            return
        buf = io.BytesIO()
        Image.new("RGB", (payload["width"], payload["height"]), (7, 8, 9)).save(buf, "PNG")
        self._reply({"images": [base64.b64encode(buf.getvalue()).decode()]})

    def _reply(self, obj: dict) -> None:
        data = json.dumps(obj).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *args):  # 别把测试输出刷满
        pass


@pytest.fixture
def fake_webui():
    FakeWebUI.payloads = []
    server = HTTPServer(("127.0.0.1", 0), FakeWebUI)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield server
    server.shutdown()


def test_webui_payload_keeps_the_settings_that_matter(fake_webui):
    cfg = Config()
    cfg.sd_host, cfg.sd_port = "127.0.0.1", fake_webui.server_address[1]
    cfg.downscale = 2
    cfg.sd_model = "some_model.safetensors"

    backend = WebUIBackend(cfg)
    out = backend.redraw(make_request())

    options = [p for p in FakeWebUI.payloads if p["path"].endswith("/options")]
    assert options and options[0]["body"]["sd_model_checkpoint"] == "some_model.safetensors"

    body = [p for p in FakeWebUI.payloads if p["path"].endswith("/img2img")][0]["body"]
    # 这两个一旦写错，返回的图和 mask 就对不齐，UV 回写会整体错位
    assert body["inpaint_full_res"] is False
    assert body["inpainting_fill"] == 1
    # 洗白后的贴图必须靠潜空间噪声重画，denoising 不能被悄悄改小
    assert body["denoising_strength"] == pytest.approx(0.7)
    assert (body["width"], body["height"]) == (SIZE[0] // 2, SIZE[1] // 2)

    unit = body["alwayson_scripts"]["controlnet"]["args"][0]
    # 控制图已经是边缘图，再跑一次预处理器会把线条糊掉
    assert unit["module"] == "none"
    assert unit["model"] == cfg.controlnet_canny_model

    # 降采样出图必须放大回画布尺寸，否则回写对不上像素
    assert out.size == SIZE


def test_webui_backend_selected_by_name(fake_webui, concept):
    cfg = Config()
    cfg.sd_host, cfg.sd_port = "127.0.0.1", fake_webui.server_address[1]
    backend = get_backend("webui", concept, concept.outfit("starlight_robe"), cfg)
    assert backend.name == "webui"
    assert get_backend("mock", concept, concept.outfit("starlight_robe"), cfg).name == "mock"
    with pytest.raises(ValueError, match="未知重绘后端"):
        get_backend("nope", concept, concept.outfit("starlight_robe"), cfg)
