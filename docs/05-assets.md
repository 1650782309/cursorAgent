# 资源与打包管线分析

资源管线是 Unity 项目里最能体现工程水平的部分，也是最容易通过逆向学到的部分——因为它几乎全部暴露在文件结构里。

## 目录结构先看懂

```
Game_Data/
  data.unity3d / level0..N / sharedassets*.assets   # 内置资源，首场景与常驻
  resources.assets                                   # Resources 目录的产物
  StreamingAssets/                                   # 重点：bundle 通常在这
  Managed/                                           # Mono 才有
  il2cpp_data/                                       # IL2CPP 才有
```

`StreamingAssets` 的组织方式直接反映打包策略：

| 现象 | 结论 |
| --- | --- |
| `catalog.json` / `catalog_*.bin` + `*.bundle` | Addressables |
| `AssetBundles/<platform>/` + 自定义 manifest | 自研 bundle 管理 |
| 大量 hash 命名的无扩展名文件 | 做了文件名混淆，manifest 里有映射 |
| 只有几个巨大文件 | 合并打包，可能自定义容器格式 |

## 用 urecon 清点

```bash
urecon inventory targets/awesome-game -o notes/
```

输出：
- `inventory.csv` — 每个资源的类型、名字、体积、所在容器
- `bundles.csv` — bundle 列表、压缩方式、内含对象数、依赖
- 类型分布汇总（Texture2D / Mesh / AudioClip / MonoBehaviour / Shader 各占多少）

体积分布是最直观的信号：贴图占 70% 说明重点在美术管线优化；MonoBehaviour 序列化数据占比高说明配置驱动做得重。

## 要回答的问题

**分包粒度**
按场景分、按功能模块分、按资源类型分，还是混合？看 bundle 数量和平均体积。几千个小 bundle 说明粒度细（加载灵活但请求多），几十个大包说明粗（首屏快但更新浪费流量）。

**依赖管理**
共享资源是抽了公共包还是冗余打进各包？UnityPy 能读出 bundle 依赖，重复率高说明选择了空间换加载复杂度。

**压缩策略**
LZ4（`UnityFS` + chunk-based）加载快、体积大；LZMA 体积小、需整包解压。移动端多数选 LZ4 或不压缩+外层 zip。

**贴图格式**
从 Texture2D 的 `m_TextureFormat` 看：Android 是 ASTC 几 x 几、ETC2 还是混合多档；iOS 是 ASTC 还是 PVRTC。这直接反映他们的机型覆盖策略。图集怎么切（按 UI 模块？按界面？）看 SpriteAtlas。

**音频**
`m_CompressionFormat` + `m_LoadType`：BGM 通常 Streaming + Vorbis，短音效 DecompressOnLoad + ADPCM/PCM。看他们怎么分档。

**热更边界**
首包里放了什么、StreamingAssets 里放了什么、要从 CDN 下什么。这条线是产品决策的直接体现。

## 加密 bundle 的处理

判断顺序：

1. `head -c 8` 看是不是 `UnityFS`。是 → 直接 UnityPy
2. 不是，但有固定 magic/偏移 → 大概率整体异或或者头部加密，试着跳过 N 字节、或简单异或后再看是否出现 `UnityFS`
3. 结构完全乱 → 走运行时。hook `AssetBundle.LoadFromMemory`，把传进去的解密后 byte[] dump 出来

第 3 条几乎万能：不管加密多复杂，Unity 引擎自己收到的一定是标准格式。

UnityPy 支持自定义解密回调，把还原出的算法写成 Python 函数接进去，就能批量处理：

```python
import UnityPy

def decrypt(data: bytes) -> bytes:
    return bytes(b ^ 0x5A for b in data)   # 举例

env = UnityPy.load(decrypt(open("foo.bundle", "rb").read()))
for obj in env.objects:
    ...
```

## 从工程还原里看设计

AssetRipper 导出的工程用同版本 Unity 打开后，重点看这些（这些是纯粹的"工程学"知识，不涉及具体代码）：

- **ProjectSettings/**：Graphics 里的 shader stripping 与 tier 设置、Quality 的分级、Physics 的 layer 碰撞矩阵、Player 的 IL2CPP 配置
- **Prefab 组织**：嵌套 prefab 用得深不深、variant 怎么用的、UI prefab 的粒度
- **ScriptableObject**：很多团队的数值配置、技能配置、关卡配置都在这，是配置架构的直接样本
- **Animator Controller**：状态机的层级、参数设计、过渡条件的复杂度
- **Shader**：变体数量、keyword 设计、LOD 分级
