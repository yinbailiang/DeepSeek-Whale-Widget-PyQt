# DeepSeek 小鲸鱼余额挂件（PyQt 桌面版）

**DeepSeek Balance Whale Widget** 的 PyQt6 桌面移植版：常驻桌面的透明小鲸鱼挂件，
实时显示 DeepSeek API 余额、今日已用、峰谷时段，带自由拖拽、随机台词、音效与按压 Q 弹效果。

> 原版是 DSH Web 插件（浏览器右下角挂件），本仓库用 Python + PyQt6 把同一套视觉与逻辑搬到了桌面，
> 不依赖 DSH，任何桌面环境都能用。

![示意](assets/DSH2.png)

## 特性

- 🐋 **透明置顶常驻**：无边框、置顶、点击穿透（透明区域不挡桌面），默认停在屏幕右下角
- 💰 **余额**：60 秒自动刷新 + 点击鲸鱼手动刷新；余额变化时数字**滚动动画**；
  瞬时网络抖动自动沿用最近余额不报错
- 📊 **今日已用**：两种模式任选
  - **小鲸鱼记账（推荐，免令牌）**：用余额差值自动记账（`~/.dsh/.dshw-usage.json`，跨天自动归零归档）
  - **实时·令牌**：填入平台会话令牌后直接调用平台用量接口，按**峰谷定价**实时换算今日已用
- ⚡ **峰谷定价**：工作日高峰 9:00–12:00 与 14:00–18:00（北京时间），2026-08-23 起周末全天谷价；
  内置 `deepseek-v4-flash / v4-pro / chat / reasoner` 定价表（v4-pro 3 倍价），DeepSeek 调价可在
  `src/deepseek_whale_widget/pricing.py` 修改
- 💬 **随机台词**：点击气泡切换加权随机台词（含峰谷提示/今日已用/rua 动图/卖萌吐槽），再点一次关闭；
  气泡总显示 5 秒自动收起
- 🖱️ **自由拖拽**：拖到哪里停哪里，位置自动记忆（不做吸附、不翻转）
- 🧸 **按压 Q 弹**玩偶效果（按压时底部坐标不变）
- 🎚️ **汉堡菜单**（悬停鲸鱼右上角出现）：大小滑块（0.6–2.5 倍）、音效切换（小黄鸭 / 音效1）、音量、
  用量模式、峰谷提示文案（默认 / 梁文峰谷 / !?强强?!）、气泡开关、每轮消耗提示与自动关闭时间、API 设置、退出
- 🔊 **音效**：按压/松手音效（`assets/*.mp3`，缺失时静默降级）
- 💬 **每轮对话消耗**：可选的本地 JSON 轮询（配合 DSH 或其他工具写入），出现新 seq 时弹出本轮消耗金额泡泡

## 安装与运行

需要 [uv](https://docs.astral.sh/uv/)（已测试 uv 0.11+）与 Python 3.10+。

```bash
cd DeepSeek-Whale-Widget-PyQt
uv sync                 # 安装 PyQt6 等依赖（自动创建 .venv）
uv run dsh-whale-widget # 或 uv run python -m deepseek_whale_widget
```

桌面发行版一般自带 Qt 运行库；若缺少 `libGL`/`libxkbcommon` 等，请安装系统对应包。

## 凭据配置（按优先级）

1. **环境变量**：`DEEPSEEK_API_KEY`（拉余额，必需）、`DEEPSEEK_PLATFORM_TOKEN`（实时·令牌模式，可选）
2. **DSH 凭据文件**：`~/.dsh/.credentials.yaml`（若你也在用 DSH，可直接复用）
3. **菜单 → API 设置**：在挂件里填写并保存到 `~/.dsh/.dshw-pyqt-credentials.json`

> 未配置 API Key 时挂件显示「未配置 DEEPSEEK_API_KEY」，其余功能不受影响。

## 用量模式

- **小鲸鱼记账（默认）**：零配置。鲸鱼每次观测余额后用余额差值自动记账，账本与 DSH 原版共用
  `~/.dsh/.dshw-usage.json`，两边数据互通。
- **实时·令牌**：在菜单 → 用量 选择。需要 DeepSeek 平台网页会话令牌（F12 → Network →
  `usage/by_api_key/amount` 请求的 `Authorization: Bearer eyJ…`），可填在 API 设置里。
  接口不返回金额，挂件按内置峰谷定价表换算。

## 每轮对话消耗（可选）

桌面版没有 DSH 会话事件，因此改为**轮询本地 JSON**。让任意工具/脚本把最近一轮消耗写到一个 JSON 文件，
格式如下，挂件每秒检查一次，`seq` 递增时弹出消耗泡泡：

```json
{ "ok": true, "seq": 3, "turn": 1, "amount": 0.0123, "tokens": 321 }
```

文件路径按顺序尝试：环境变量 `DSHW_LAST_TURN_FILE` → `~/.dsh/.dshw-last-turn.json` → `~/.dshw-last-turn.json`。
若不需要此功能，在菜单关掉「每轮消耗提示」即可。

## 操作

| 操作 | 效果 |
| --- | --- |
| 单击鲸鱼 | 展开气泡 + 手动刷新余额 |
| 拖拽鲸鱼 | 自由移动，松手即停在原地并记住位置 |
| 单击气泡 | 切换随机台词；再点一次关闭 |
| 悬停鲸鱼右上角 | 出现汉堡菜单按钮 |

## 目录结构

```text
DeepSeek-Whale-Widget-PyQt/
├── pyproject.toml            # uv 项目元数据 + 入口
├── README.md
├── assets/                   # 鲸鱼 PNG / rua.gif / 音效 mp3（自原版仓库复制）
└── src/deepseek_whale_widget/
    ├── __init__.py
    ├── __main__.py           # python -m 入口
    ├── app.py                # QApplication 入口
    ├── pricing.py            # 峰谷定价 + 今日已用换算
    ├── storage.py            # 配置/账本/凭据持久化（与 DSH 原版文件兼容）
    ├── api.py                # 余额拉取、平台用量、凭据解析
    └── widget.py             # 主挂件（绘制/拖拽/气泡/菜单/音效）
```

## 与 DSH 原版的关系

- 配置文件：复用 `~/.dsh/.dshw-size.json`（大小/音量/模式等），Web 插件版与桌面版可共享
- 账本文件：复用 `~/.dsh/.dshw-usage.json`，两种模式记账数据互通
- 视觉参数（气泡 SVG、文字位置/字号、鲸鱼占比 59.45%、随机台词权重）均与原版一致
- 差异：桌面版无「滚动条避让」和「四边吸附/镜像翻转」（改为自由拖拽）；「每轮对话消耗」由 DSH 事件改为本地 JSON 轮询

## 许可证

MIT，详见原仓库 LICENSE。
