"""全局路径与调参。

所有字段都能用 ``SPINEFORGE_<大写字段名>`` 环境变量覆盖，方便在不同美术机
（本地有 SD WebUI / CI 上没有）之间切换而不用改代码。
"""

from __future__ import annotations

import os
from dataclasses import dataclass, fields
from pathlib import Path

def _find_repo_root() -> Path:
    """定位仓库根目录（同时含 ``concepts/`` 与 ``tools/palettes.json``）。

    概念库和设定集是数据而不是代码，所以不会随包被安装到 site-packages。
    正常用法是从克隆出来的仓库里 ``pip install -e .``，此时源码树就在原地；
    但如果被非 editable 地装到别处，就退回到从当前目录向上找，
    这样在仓库里任意子目录执行 ``spineforge`` 都能工作。
    """
    marker = ("concepts", "tools/palettes.json")

    def looks_like_repo(path: Path) -> bool:
        return all((path / m).exists() for m in marker)

    here = Path(__file__).resolve().parent.parent
    if looks_like_repo(here):
        return here
    for candidate in (Path.cwd(), *Path.cwd().parents):
        if looks_like_repo(candidate):
            return candidate
    return here


REPO_ROOT = _find_repo_root()


@dataclass
class Config:
    # ---- 路径 ----
    concepts_dir: str = str(REPO_ROOT / "concepts")
    build_dir: str = str(REPO_ROOT / "build")

    # ---- Stable Diffusion WebUI ----
    sd_host: str = "127.0.0.1"
    sd_port: int = 7860
    sd_model: str = ""          # 留空表示沿用 WebUI 当前模型
    sd_vae: str = ""
    sd_sampler: str = "DPM++ 2M Karras"
    sd_steps: int = 25
    sd_cfg_scale: float = 7.0
    sd_timeout: int = 600
    controlnet_canny_model: str = "control_v11p_sd15_canny [d14c016b]"

    # ---- 重绘 ----
    # 送进 SD 前把画布降采样的倍数，越大越省显存。视口尺寸会对齐到 8*downscale。
    downscale: int = 2
    denoising_strength: float = 0.75
    mask_blur: int = 6

    # ---- 关键姿势选取 ----
    # 采样动画时的步长（秒）。越小越可能找到更好的姿势，但预处理更慢。
    keypose_sample_step: float = 0.1
    keypose_max_count: int = 8
    # 一轮新增可见纹素低于 max(min_gain, 首轮增益*min_gain_ratio) 时停止迭代。
    keypose_min_gain: int = 512
    keypose_min_gain_ratio: float = 0.015

    # ---- 回写 ----
    # alpha 低于该值的纹素不算部件的一部分（抗锯齿边缘不可信）。
    low_alpha_threshold: int = 5
    # 判定"该像素处在部件边界"的邻域半径，边界像素不回写。
    edge_reject_radius: int = 2
    # HSV 梯度阈值，超过则认为像素落在色块交界上，不可信。
    edge_gradient_threshold: int = 3000
    # 前 N 帧结束后对仍为白的纹素做邻域扩散填充，避免留白洞。
    flood_fill_frames: int = 3

    def __post_init__(self) -> None:
        for f in fields(self):
            env = os.environ.get(f"SPINEFORGE_{f.name.upper()}")
            if env is None:
                continue
            if f.type in ("int", int):
                setattr(self, f.name, int(env))
            elif f.type in ("float", float):
                setattr(self, f.name, float(env))
            else:
                setattr(self, f.name, env)

    # ---- 派生路径 ----
    def character_dir(self, concept_id: str) -> Path:
        return Path(self.build_dir) / concept_id

    def images_dir(self, concept_id: str) -> Path:
        """attachment 源贴图（每次换装的起点，只读）。"""
        return self.character_dir(concept_id) / "images"

    def redraw_dir(self, concept_id: str) -> Path:
        """预处理产物：UV 映射 / mask / ctrl / sequence.txt。"""
        return self.character_dir(concept_id) / "redraw"

    def skin_dir(self, concept_id: str, outfit: str, seed: int) -> Path:
        """一次换装的输出目录。"""
        return self.character_dir(concept_id) / "skins" / f"{outfit}_{seed}"


DEFAULT = Config()
