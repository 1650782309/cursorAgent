# cursorAgent

## 网络状态检测与修复工具

适用于 **无畏契约（Valorant）** 等游戏启动后导致断网、需要重启才能恢复的场景。工具位于 `network-repair-tool/` 目录。

### 功能

| 命令 | 说明 |
|------|------|
| `gui` | 启动图形界面（按钮操作 + 日志面板） |
| `detect` | 全面检测网卡、网关、DNS、Ping、TCP 连通性 |
| `repair` | 按强度自动或手动修复网络 |
| `watch` | 监控无畏契约进程，断网时自动修复 |
| `monitor` | 通用持续监控 |
| `list-steps` | 列出所有修复步骤 |

### 快速开始（Windows）

```powershell
# 以管理员身份打开 PowerShell，进入工具目录
cd network-repair-tool

# 启动图形界面（推荐）
python net-repair.py gui

# 检测网络
python net-repair.py detect

# 自动修复（推荐）
python net-repair.py repair

# 游戏期间后台监控，断网自动修复
python net-repair.py watch

# 若仍无效，重度修复（需重启电脑生效）
python net-repair.py repair --level heavy -y
```

### 修复级别

- **light** — 刷新 DNS、重启 DHCP/DNS 服务
- **medium** — 在 light 基础上重置网卡、刷新路由
- **heavy** — 在 medium 基础上重置 Winsock 与 TCP/IP 栈（针对 Vanguard 破坏网络栈）

### 原理说明

无畏契约的反作弊 **Riot Vanguard** 在内核层安装网络过滤驱动，可能导致：

- Winsock 目录损坏
- DNS 缓存异常
- 网卡被禁用或路由丢失

本工具按从轻到重的顺序尝试修复，多数情况无需重启电脑。

### 要求

- Python 3.8+
- Windows 10/11（主要目标平台）
- 修复功能需 **管理员权限**
