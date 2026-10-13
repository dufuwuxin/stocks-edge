# stocks-edge — 长跑采集 Codespace + 高频增量数据

## 用途

1. **Codespaces 长跑采集**（突破 GitHub Actions 单次 6 小时限制）
2. **高频增量数据**（交易时段分钟级快照，Actions cron 最快只能 5 分钟）

## 启动 Codespace

GitHub 网页 → 本仓 → Code → Codespaces → Create codespace on main

镜像构建期已装好全部依赖（`requests`/`duckdb`/`numpy`/`pandas`），
冷启动即可运行，**零构建**。

## 用法

```bash
# 1. 补全 K 线覆盖率 (当前 48% → 目标 90%+)
#    断点续传，限流自适应退避，Ctrl+C 安全退出
python3 scripts/longrun_collect.py kline --max-hours 4

# 2. 分钟级实时采集 (交易时段每 60s)
python3 scripts/longrun_collect.py realtime --interval 60
```

## 与 GitHub Actions 的分工

| | Actions | Codespace |
|---|---|---|
| 单次时长 | < 5 min | 数小时 |
| 频率 | cron 最快 5 min | 1 min 或更低 |
| 适用 | 轻量定时任务 | 全量补录、长跑采集 |
| 额度 | 2000 min/月 | Codespaces 额度 |

## 数据源

全部零鉴权公开接口，实测可达清单见 `qwerzxcva/stocks-ai-view/data/sources_registry.json`。

> 仅供研究，不构成投资建议。
