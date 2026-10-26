# scripts/ 目录导航

按功能分三组。所有脚本顶部都有 `PROJECT-ROOT BOOTSTRAP` 前言，
**可从任意目录调用**（自动定位项目根、挂载 `core/`、切换工作目录）。

## data/ —— 数据获取与更新

| 脚本 | 作用 |
|---|---|
| `update_data.py` | ★ 每日数据更新：H20269 走中证官网 API（增量只追加），512890 走东财→腾讯前复权（全量刷新）。`--check` 只看不写 |
| `convert_excel_to_csv.py` | 旧手工流程：H30269perf.xlsx → CSV（现已少用） |

## dashboard/ —— 手机看板

| 脚本 | 作用 |
|---|---|
| `build_dashboard.py` | ★ 读 `data/` 两个 CSV → 生成 `docs/index.html`（静态快照，供 GitHub Pages 发布） |
| `dashboard_live.py` | 实时渲染模块：现场拉数现算、不落盘、10 分钟缓存；被根目录 `dashboard_app.py` 调用（Render 部署） |

## backtest/ —— 策略回测与研究报告

| 脚本 | 作用 |
|---|---|
| `run_multiple_backtests.py` | 3 个主力起始日回测 |
| `run_extended_backtests.py` | H20269 扩展 10 起始日（覆盖牛顶/熊底等情景） |
| `run_512890_backtests.py` | 512890 ETF 5 起始日（真实可交易标的） |
| `run_orphan_backtests.py` | 3 组历史手工回测组（无 `__main__` 保护，导入即运行） |
| `build_cross_group_report.py` | ★ 21 组横向统计报告（含 vintage 一致性断言） |
| `regenerate_charts.py` | 不重跑回测，仅重画全部图表（快） |
| `generate_rsi_report.py` | RSI 止盈决策分析报告 → `output/reports/` |

完整说明见根目录 `README.md` 与 `docs/DASHBOARD_GUIDE.md`。
