# 模型与动画提取（可播放 FBX + 自动分类）

## 目标

从 Unity 包体里抽出**能在 Blender / Maya / Unity 里直接播放**的 FBX，并自动归到：

| 目录 | 含义 |
| --- | --- |
| `人物/` | 角色、NPC、怪物等蒙皮模型 |
| `物品/` | 道具、武器、可互动物 |
| `场景/` | 建筑、地形、场景静态物 |
| `特效/` | 粒子、拖尾等 |
| `UI/` | 图标、图集等 |
| `其他/` | 信号不足，待人工复核 |

## 用法

```bash
pip install -e "tools/[assets]"          # 需要 UnityPy
bash scripts/fetch_tools.sh              # 下载 AssetStudio 等到 vendor/

# 检查导出器
urecon doctor

# 识别后提取
urecon init targets/foo --source /games/Foo
urecon fingerprint targets/foo
urecon extract targets/foo --format fbx
```

产出：

```
extracted/models/
  人物/<角色名>/
    *.fbx                 # 可播放（AssetStudio 成功时）
    textures/
    animations/           # 降级时的 JSON 摘要
    meta.json             # 分类证据、骨骼数、关联 clip
  物品/...
  场景/...
  _index.json             # 机器可读总清单
  _summary.md
  _raw/                   # 外部工具原始输出
```

## 可播放 FBX 怎么来的

UnityPy **不能**导出带动画的 FBX。真正可播放的 FBX 依赖外部工具：

1. **AssetStudio / AssetStudioMod CLI（首选）**  
   直接导出 Mesh + Animator + AnimationClip → FBX。  
   设置：`URECON_ASSETSTUDIO=C:\path\AssetStudio.CLI.exe`

2. **AssetRipper（备选）**  
   导出可打开的 Unity 工程；FBX 需在 Unity 里用 FBX Exporter 二次导出。  
   设置：`URECON_ASSETRIPPER=...`

3. **降级（无外部工具时）**  
   UnityPy 导出 OBJ + 贴图 PNG + 动画曲线 JSON，并按分类放好目录。  
   装上 AssetStudio 后重新 `urecon extract --format fbx` 即可补齐 FBX。

```bash
urecon extract targets/foo --format fbx --exporter assetstudio
urecon extract targets/foo --format obj          # 强制只要网格
urecon extract targets/foo --classify-only       # 只分类，不导出
```

## 分类怎么做的

对每个 Mesh / SkinnedMeshRenderer 打分，信号来自：

- **路径与名字关键词**：`character/`、`weapon_`、`scene_`、中文「角色」「道具」等
- **结构特征**：蒙皮、骨骼数、Humanoid Avatar、Animator
- **动画关联**：同容器或同名前缀的 clip；含 idle/walk/run/attack 等位移类动画 → 倾向人物
- **规模**：高模无蒙皮 → 场景；低模无蒙皮 → 物品

每项都写入 `meta.json` 的 `evidence` 与 `confidence`（high/medium/low）。  
置信度低的优先人工过一遍 `_summary.md`。

动画会尽量挂到同名/同容器模型上；挂不上的进各类别下的 `_orphan_clips/`。

## 加密与失败

- bundle 不是 `UnityFS` → 先走 `scripts/trace_bundle.js` 落盘明文，再 extract
- AssetStudio 对某容器失败 → 该项降级 OBJ，不中断整次任务
- 自定义动画系统（Spine / Live2D / 自研曲线）→ 不是标准 AnimationClip，不会进 FBX，需另走对应工具

## 合规

导出的模型与动画是他人资产，**只可用于学习研究，禁止二次分发或商用**。见 [07-legal.md](07-legal.md)。
