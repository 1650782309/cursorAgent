"""重绘后端。

流水线只依赖一个方法：给一张底图、一张 inpaint mask、一张 ControlNet 控制图，
还回一张同尺寸的重绘结果。谁来画不重要，于是有两个实现：

``webui``  连本地 Stable Diffusion WebUI 的 ``/sdapi/v1/img2img``，接 ControlNet。
           这是美术组实际出图用的路径。
``mock``   纯离线的确定性配色替换。不需要显卡和模型，用来在 CI 上回归整条流水线，
           也方便在没装 SD 的机器上先把关键姿势和覆盖率调对。
"""

from __future__ import annotations

import base64
import io
from dataclasses import dataclass
from typing import Protocol

import numpy as np
from PIL import Image

from spineforge.concept import Concept, Outfit, hex_to_rgb
from spineforge.config import Config


@dataclass
class RedrawRequest:
    image: Image.Image      # RGB 底图
    mask: Image.Image       # L，白色区域要重画
    control: Image.Image    # L，ControlNet 的边缘图
    prompt: str
    negative_prompt: str
    seed: int
    denoising_strength: float


class Backend(Protocol):
    name: str

    def redraw(self, req: RedrawRequest) -> Image.Image:
        ...


# --------------------------------------------------------------------- mock
class MockBackend:
    """离线后端：把 mask 区域按亮度重新映射到换装配色上。

    它不"理解"提示词，但保留了真实后端的全部接口语义——只改 mask 内的像素、
    尺寸不变、同一个 seed 出同样的图。因此 UV 映射、回写、覆盖率这些真正
    容易出错的环节都能被它验证到。

    配色按画布上的高度铺开：上装、腰带、下装本来就分布在不同高度，
    照高度铺渐变就能得到一件"分层合理"的衣服。明暗则沿用底图的相对亮度，
    这样洗白后的纯白区域也能被正常上色——按底图颜色匹配的做法在这里会失效。
    """

    name = "mock"

    def __init__(self, concept: Concept, outfit: Outfit) -> None:
        hints = [hex_to_rgb(v) for v in outfit.palette_hint.values()]
        if not hints:
            # 没写配色提示就退回到角色自己的前几个颜色，至少保证"看得出换过装"。
            hints = [hex_to_rgb(v) for v in list(concept.palette.values())[:3]]
        if len(hints) == 1:
            hints = [hints[0], tuple(int(v * 0.5) for v in hints[0])]
        self.stops = np.array(hints, dtype=np.float32)

    def redraw(self, req: RedrawRequest) -> Image.Image:
        src = np.asarray(req.image.convert("RGB"), dtype=np.float32)
        mask = np.asarray(req.mask.convert("L")) > 127
        if not mask.any():
            return req.image.copy()

        ys, _ = np.nonzero(mask)
        top, bottom = int(ys.min()), int(ys.max())
        span = max(bottom - top, 1)
        t = (ys - top) / span

        n = len(self.stops) - 1
        pos = np.clip(t * n, 0, n - 1e-6)
        i = pos.astype(np.int32)
        frac = (pos - i)[:, None]
        out = self.stops[i] * (1.0 - frac) + self.stops[i + 1] * frac

        # 借底图的明暗关系保留褶皱和描边的层次。
        lum = (src[mask] @ np.array([0.299, 0.587, 0.114], dtype=np.float32)) / 255.0
        out = out * (0.72 + 0.36 * lum)[:, None]

        # 一点确定性噪声，模拟 SD 输出的笔触，也方便肉眼确认贴图确实被重写过。
        rng = np.random.default_rng(req.seed)
        out = np.clip(out + rng.normal(0.0, 3.0, out.shape), 0, 255)

        dst = src.copy()
        dst[mask] = out
        return Image.fromarray(dst.astype(np.uint8), mode="RGB")


# --------------------------------------------------------------------- webui
def _b64(img: Image.Image) -> str:
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return base64.b64encode(buf.getvalue()).decode()


def _unb64(data: str) -> Image.Image:
    return Image.open(io.BytesIO(base64.b64decode(data.split(",", 1)[-1]))).convert("RGB")


class WebUIBackend:
    """Stable Diffusion WebUI 的 img2img inpaint + ControlNet canny。

    参数取值沿用 RedrawSpine 的结论：
    ``inpainting_fill=1``（潜空间噪声）保证白底能被真正画上东西，
    ``inpaint_full_res=False`` 是必须的——开启后 WebUI 会先裁剪再缩放回来，
    结果和 mask 对不上，UV 回写就全乱了。
    """

    name = "webui"

    def __init__(self, cfg: Config) -> None:
        import requests

        self.cfg = cfg
        self.session = requests.Session()
        self.base = f"http://{cfg.sd_host}:{cfg.sd_port}"
        self._configure()

    def _configure(self) -> None:
        options: dict[str, str] = {}
        if self.cfg.sd_model:
            options["sd_model_checkpoint"] = self.cfg.sd_model
        if self.cfg.sd_vae:
            options["sd_vae"] = self.cfg.sd_vae
        if options:
            r = self.session.post(f"{self.base}/sdapi/v1/options", json=options,
                                  timeout=self.cfg.sd_timeout)
            r.raise_for_status()

    def redraw(self, req: RedrawRequest) -> Image.Image:
        cfg = self.cfg
        full_w, full_h = req.image.size
        ds = max(1, cfg.downscale)
        w, h = full_w // ds, full_h // ds

        payload = {
            "init_images": [_b64(req.image)],
            "mask": _b64(req.mask),
            "mask_blur": cfg.mask_blur,
            "inpainting_fill": 1,
            "inpaint_full_res": False,
            "inpainting_mask_invert": 0,
            "prompt": req.prompt,
            "negative_prompt": req.negative_prompt,
            "seed": req.seed,
            "sampler_name": cfg.sd_sampler,
            "steps": cfg.sd_steps,
            "cfg_scale": cfg.sd_cfg_scale,
            "denoising_strength": req.denoising_strength,
            "width": w,
            "height": h,
            "alwayson_scripts": {
                "controlnet": {
                    "args": [
                        {
                            "input_image": _b64(req.control.convert("RGB")),
                            "model": cfg.controlnet_canny_model,
                            "module": "none",   # 控制图已经是边缘图，不用再跑预处理器
                            "weight": 1.0,
                            "resize_mode": "Just Resize",
                            "pixel_perfect": True,
                            "control_mode": "Balanced",
                        }
                    ]
                }
            },
        }
        r = self.session.post(f"{self.base}/sdapi/v1/img2img", json=payload,
                              timeout=cfg.sd_timeout)
        r.raise_for_status()
        image = _unb64(r.json()["images"][0])

        if image.size != (full_w, full_h):
            image = self._upscale(image, (full_w, full_h))
        return image

    def _upscale(self, image: Image.Image, size: tuple[int, int]) -> Image.Image:
        """把降采样出图放大回画布尺寸。

        UV 回写要求结果和画布逐像素对齐，尺寸差一点点整张贴图就会错位。
        优先用 WebUI 的 extras 接口跑动漫超分，失败了退回 Lanczos。
        """
        try:
            r = self.session.post(
                f"{self.base}/sdapi/v1/extra-single-image",
                json={
                    "image": _b64(image),
                    "upscaling_resize_w": size[0],
                    "upscaling_resize_h": size[1],
                    "upscaling_crop": False,
                    "upscaler_1": "R-ESRGAN 4x+ Anime6B",
                    "resize_mode": 1,
                },
                timeout=self.cfg.sd_timeout,
            )
            r.raise_for_status()
            out = _unb64(r.json()["image"])
            if out.size == size:
                return out
            return out.resize(size, Image.LANCZOS)
        except Exception:
            return image.resize(size, Image.LANCZOS)


def get_backend(name: str, concept: Concept, outfit: Outfit, cfg: Config) -> Backend:
    if name == "mock":
        return MockBackend(concept, outfit)
    if name == "webui":
        return WebUIBackend(cfg)
    raise ValueError(f"未知重绘后端 {name!r}，可选：mock / webui")
