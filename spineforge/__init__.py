"""spineforge —— 由角色概念库驱动的 Spine 动画自动生成与 SD 换装工作流。

管线分四段，每段都能单独跑、单独复查产物：

1. ``build``      概念 -> attachment 贴图 + Spine 骨架 + 程序化动画
2. ``preprocess`` 骨架 -> 关键姿势序列 + UV 映射 + inpaint mask + ControlNet 控制图
3. ``reskin``     按序列逐姿势重绘，并把结果沿 UV 映射回写进 attachment 贴图
4. ``preview``    用任意一套贴图渲染动画序列帧 / GIF

第 2、3 段的算法移植自 https://github.com/Zhangyangrui916/RedrawSpine
（原实现是 OpenGL + CUDA 的 C++ analyzer，这里改写为 numpy 软件渲染，
去掉了对 Spine 编辑器、Photoshop 和 GPU 的依赖）。
"""

from spineforge.concept import Concept, load_concept, list_concepts

__all__ = ["Concept", "load_concept", "list_concepts", "__version__"]

__version__ = "0.1.0"
