"""把重绘结果沿 UV 映射写回 attachment 贴图。

这是整条流水线里最需要小心的一步。屏幕上一个像素能直接查到它属于哪张贴图的
哪个纹素，但不是每个像素都值得写回去：

* 落在部件轮廓上的像素混了旁边部件甚至背景的颜色，写回去会在贴图边缘糊出脏边；
* 同一个纹素可能在多个姿势里都可见，只认第一次写入，否则后面的姿势会把
  前面画好的细节反复覆盖，多轮之后颜色会漂。

所以这里做三件事：标记已写纹素、剔除不可信的边缘像素、把剩下的写回去。
最后对始终没被任何姿势覆盖到的纹素做邻域扩散，避免贴图上留白洞。
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from spineforge.config import Config

# 纹素写入状态
NOT_WRITTEN = 255
WRITTEN = 128
FLOODED = 200
TRANSPARENT = 0


@dataclass
class WriteStats:
    written: int
    rejected_edge: int
    rejected_dup: int


def rgb_to_hsv_u8(rgb: np.ndarray) -> np.ndarray:
    """HxWx3 uint8 RGB -> HxWx3 uint8 HSV。色相在 0~255 上环绕。"""
    arr = rgb.astype(np.float32) / 255.0
    r, g, b = arr[..., 0], arr[..., 1], arr[..., 2]
    mx = arr.max(axis=-1)
    mn = arr.min(axis=-1)
    diff = mx - mn

    hue = np.zeros_like(mx)
    safe = diff > 1e-6
    idx = safe & (mx == r)
    hue[idx] = ((g - b)[idx] / diff[idx]) % 6.0
    idx = safe & (mx == g)
    hue[idx] = ((b - r)[idx] / diff[idx]) + 2.0
    idx = safe & (mx == b)
    hue[idx] = ((r - g)[idx] / diff[idx]) + 4.0
    hue = hue / 6.0

    sat = np.zeros_like(mx)
    nz = mx > 1e-6
    sat[nz] = diff[nz] / mx[nz]

    out = np.stack([hue, sat, mx], axis=-1) * 255.0
    return np.clip(out, 0, 255).astype(np.uint8)


def _gather(img: np.ndarray, ys: np.ndarray, xs: np.ndarray,
            dy: int, dx: int, fill: int = 0) -> tuple[np.ndarray, np.ndarray]:
    """取偏移邻居，越界的位置用 fill 补，并返回有效性掩码。"""
    h, w = img.shape[:2]
    ny, nx = ys + dy, xs + dx
    ok = (ny >= 0) & (ny < h) & (nx >= 0) & (nx < w)
    ny = np.clip(ny, 0, h - 1)
    nx = np.clip(nx, 0, w - 1)
    vals = img[ny, nx]
    if vals.ndim == 1:
        vals = np.where(ok, vals, fill)
    else:
        vals = np.where(ok[:, None], vals, fill)
    return vals, ok


def reject_unreliable(uv: np.ndarray, frame_rgb: np.ndarray, cfg: Config) -> np.ndarray:
    """返回剔除后的 UV 图：不可信的像素被置 0。

    只有"处在部件边界附近"的像素才需要接受检验；部件内部的像素直接放行。
    检验在 HSV 空间做，因为 SD 输出的同一块布料常有明度渐变但色相稳定，
    用 RGB 判据会把正常的受光面误判成边界。
    """
    r = cfg.edge_reject_radius
    ids = (uv >> np.uint32(24)).astype(np.int16)
    valid = uv != 0
    if r <= 0 or not valid.any():
        return uv.copy()

    at_edge = np.zeros_like(valid)
    for dy in range(-r, r + 1):
        for dx in range(-r, r + 1):
            if dy == 0 and dx == 0:
                continue
            shifted = np.roll(ids, (dy, dx), axis=(0, 1))
            at_edge |= shifted != ids
    # roll 会环绕，画布四边一律当作边界处理（保守剔除）。
    at_edge[:r, :] = at_edge[-r:, :] = True
    at_edge[:, :r] = at_edge[:, -r:] = True

    candidates = valid & at_edge
    ys, xs = np.nonzero(candidates)
    if ys.size == 0:
        return uv.copy()

    hsv = rgb_to_hsv_u8(frame_rgb).astype(np.int32)
    hue = hsv[..., 0]
    sat = hsv[..., 1]
    val = hsv[..., 2]

    reject = np.zeros(ys.size, dtype=bool)

    # 1) 极暗像素基本是描边，写回去会在贴图里留下黑边。
    reject |= val[ys, xs] < 32

    # 2) 明度/色相梯度过大 -> 处在色块交界上。
    def central_diff(channel: np.ndarray, dy: int, dx: int, wrap: bool) -> np.ndarray:
        a, _ = _gather(channel, ys, xs, -dy, -dx)
        b, _ = _gather(channel, ys, xs, dy, dx)
        d = a - b
        if wrap:
            d = np.abs(d)
            d = np.where(d > 128, 256 - d, d)
        return d

    gv = central_diff(val, 0, 1, False) ** 2 + central_diff(val, 1, 0, False) ** 2
    gh = central_diff(hue, 0, 1, True) ** 2 + central_diff(hue, 1, 0, True) ** 2
    reject |= (gv > cfg.edge_gradient_threshold) | (gh > cfg.edge_gradient_threshold)

    # 3) 颜色相近的邻居里，属于别的部件的居多 -> 这块颜色其实是邻居部件的。
    win = 5
    same = np.zeros(ys.size, dtype=np.int32)
    other = np.zeros(ys.size, dtype=np.int32)
    self_hue = hue[ys, xs]
    self_sat = sat[ys, xs]
    self_id = ids[ys, xs]
    for dy in range(-win, win + 1):
        for dx in range(-win, win + 1):
            if dy == 0 and dx == 0:
                continue
            nh, ok = _gather(hue, ys, xs, dy, dx)
            ns, _ = _gather(sat, ys, xs, dy, dx)
            nid, _ = _gather(ids, ys, xs, dy, dx, fill=-1)
            close = ok & (((nh - self_hue) ** 2 + (ns - self_sat) ** 2) < 200)
            same += (close & (nid == self_id)).astype(np.int32)
            other += (close & (nid != self_id)).astype(np.int32)
    reject |= (other != 0) & (other + 3 > same)

    out = uv.copy()
    out[ys[reject], xs[reject]] = 0
    return out


def apply_frame(uv: np.ndarray, frame_rgb: np.ndarray,
                textures: dict[str, np.ndarray], written: dict[str, np.ndarray],
                id_to_name: dict[int, str], cfg: Config) -> WriteStats:
    """把一帧重绘结果写回 attachment 贴图（原地修改 textures / written）。"""
    before_valid = int(np.count_nonzero(uv))
    filtered = reject_unreliable(uv, frame_rgb, cfg)
    rejected_edge = before_valid - int(np.count_nonzero(filtered))

    ys, xs = np.nonzero(filtered)
    if ys.size == 0:
        return WriteStats(0, rejected_edge, 0)

    values = filtered[ys, xs]
    slot_ids = (values >> np.uint32(24)).astype(np.int64)
    texels = (values & np.uint32(0xFFFFFF)).astype(np.int64)
    colors = frame_rgb[ys, xs]

    total_written = 0
    rejected_dup = 0
    for sid in np.unique(slot_ids):
        name = id_to_name.get(int(sid))
        if name is None:
            continue
        sel = slot_ids == sid
        idx = texels[sel]
        col = colors[sel]

        mask = written[name].reshape(-1)
        fresh = mask[idx] != WRITTEN
        rejected_dup += int(np.count_nonzero(~fresh))
        idx = idx[fresh]
        col = col[fresh]
        if idx.size == 0:
            continue

        # 同一纹素在这一帧里可能被多个屏幕像素命中，np.unique 保证只取一个。
        idx, first = np.unique(idx, return_index=True)
        col = col[first]

        tex = textures[name]
        flat = tex.reshape(-1, 4)
        flat[idx, 0:3] = col
        mask[idx] = WRITTEN
        total_written += idx.size

    return WriteStats(total_written, rejected_edge, rejected_dup)


def flood_unwritten(texture: np.ndarray, written: np.ndarray,
                    max_iterations: int = 64) -> int:
    """用已写纹素的颜色向外扩散，填掉还没被任何姿势覆盖到的纹素。

    没有这一步，那些永远背对镜头的纹素会保持洗白后的纯白；一旦动画把它们转出来，
    就是一块刺眼的白斑。扩散出来的颜色不准，但至少和周围连得上。
    """
    flat_tex = texture.reshape(-1, 4)
    h, w = written.shape
    filled_total = 0

    for _ in range(max_iterations):
        target = (written == NOT_WRITTEN)
        if not target.any():
            break
        source = (written == WRITTEN) | (written == FLOODED)

        acc = np.zeros((h, w, 3), dtype=np.int32)
        cnt = np.zeros((h, w), dtype=np.int32)
        rgb = texture[..., :3].astype(np.int32)
        for dy in (-1, 0, 1):
            for dx in (-1, 0, 1):
                if dy == 0 and dx == 0:
                    continue
                s = np.roll(source, (dy, dx), axis=(0, 1))
                c = np.roll(rgb, (dy, dx), axis=(0, 1))
                acc += np.where(s[..., None], c, 0)
                cnt += s.astype(np.int32)

        fillable = target & (cnt > 0)
        if not fillable.any():
            break
        avg = (acc[fillable] // cnt[fillable][:, None]).astype(np.uint8)
        idx = np.nonzero(fillable.reshape(-1))[0]
        flat_tex[idx, 0:3] = avg
        written[fillable] = FLOODED
        filled_total += int(idx.size)

    return filled_total


def clean_outliner(texture: np.ndarray) -> None:
    """清掉孤立的描边像素。

    洗白之后贴图上只剩描边是有颜色的，这些孤立深色点会污染后面的邻域扩散，
    把整块布料染灰。原实现在第一帧回写后同样先做这一步。
    """
    rgb = texture[..., :3]
    alpha = texture[..., 3]
    not_white = (rgb != 255).any(axis=-1) & (alpha > 0)
    neighbors = np.zeros(not_white.shape, dtype=np.int32)
    for dy in range(-2, 3):
        for dx in range(-2, 3):
            if dy == 0 and dx == 0:
                continue
            neighbors += np.roll(not_white, (dy, dx), axis=(0, 1)).astype(np.int32)
    isolated = not_white & (neighbors < 8)
    texture[isolated, 0:3] = 255


def initial_written(texture: np.ndarray, low_alpha_threshold: int) -> np.ndarray:
    return np.where(texture[..., 3] > low_alpha_threshold,
                    np.uint8(NOT_WRITTEN), np.uint8(TRANSPARENT))
