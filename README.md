# 红利低波指数 滚动仓位策略研究

基于 **250 日均线乖离率** 的滚动仓位策略日级回测框架，标的为 A 股红利低波指数
（H20269 全收益指数）及其跟踪 ETF（512890 华泰柏瑞红利低波 ETF）。

> ⚠️ **研究状态提示**：这是一个**研究中**的项目，不是可直接使用的投资结论。
> 已修复 8 个计算类 bug（详见 `tools/ab_compare/改前改后对比报告.md`）。
> **有证据的部分**：21 组回测中，19 组跑赢满仓指数、21 组回撤不劣于满仓指数，
> 夏普平均 +0.238（这一项无法用"降仓位"解释，见下方结论卡的 CAL 论证）。
> **没有证据的部分**：样本外、择时统计显著性、参数稳健性三项检验均未通过；
> 策略**没有任何下行出口**（无止损、无强制减仓）。
> —— 完整口径见 `docs/progress.md` 的[★ 结论卡](docs/progress.md#-结论卡双基准口径全文唯一权威处)。

---

## 目录结构

```
├── core/                  # 核心计算模块（被 scripts/ 调用，一般不直接运行）
│   ├── rolling_position_backtest.py   # 滚动仓位回测引擎（策略主体）
│   ├── performance_analysis.py        # 阶段划分与绩效/时间维度分析
│   ├── data_calculator.py             # MA250、乖离率等指标计算
│   └── analyze_ma250.py               # MA250 静态图分析（matplotlib）
│
├── scripts/               # 可执行入口（按功能分三组，见 scripts/README.md）
│   ├── data/                          # 数据获取与更新
│   │   ├── update_data.py             # ★ 每日自动拉取最新数据（中证API+东财/腾讯）
│   │   └── convert_excel_to_csv.py    # H30269perf.xlsx → CSV（旧手工流程）
│   ├── dashboard/                     # 手机看板
│   │   ├── build_dashboard.py         # ★ 生成手机看板 docs/index.html
│   │   └── dashboard_live.py          # 实时渲染模块（根目录 dashboard_app.py 调用）
│   └── backtest/                      # 策略回测与研究报告
│       ├── run_multiple_backtests.py      # 3 个主力起始日回测
│       ├── run_extended_backtests.py      # H20269 扩展 10 起始日（市场情景覆盖）
│       ├── run_512890_backtests.py        # 512890 ETF 5 起始日（真实可交易标的）
│       ├── run_orphan_backtests.py        # 3 组历史手工回测组（补齐无人负责的死角）
│       ├── build_cross_group_report.py    # ★ 21 组横向统计报告（全量指标 + 分阶段归因）
│       ├── regenerate_charts.py           # 不重跑回测，仅重画全部图表
│       └── generate_rsi_report.py         # RSI 止盈决策分析报告
│
├── tools/                 # 审计与验证工具（研究可信度的保障）
│   ├── audit_checks.py                # 16 项自动审计，逐项 PASS/FAIL
│   ├── inject_bootstrap.py            # 一次性：给脚本注入项目根引导
│   ├── fix_paths.py                   # 一次性：重构后路径批量修正
│   └── ab_compare/                    # 改前 / 改后 A/B 对比工具链
│       ├── build_legacy.py            # 反向补丁重建「改前」源码
│       ├── run_ab.py                  # 同一批回测跑两个源码版本
│       ├── make_report.py             # 由 JSON 生成对比报告
│       ├── mark_stale.py              # 给过期报告加提示横幅
│       └── 改前改后对比报告.md          # ★ 8 个 bug 的逐项影响归因
│
├── docs/                  # 文档
│   ├── progress.md                    # ★ 项目进度与全部结论（先读这个）
│   ├── ROLLING_POSITION_STRATEGY.md   # 策略规则完整定义
│   ├── STRATEGY_DESIGN.md             # 策略设计思路
│   ├── RSI_ANALYSIS_FRAMEWORK.md      # RSI 分析框架
│   ├── ANALYZE_MA250_GUIDE.md         # MA250 分析工具说明
│   ├── PROJECT_REORGANIZATION_PLAN.md # 本次重构方案（已执行）
│   ├── DASHBOARD_GUIDE.md             # ★ 每日数据更新与手机看板说明
│   ├── GitHub入门教程.md               # Git/GitHub 新手教程（推送/日常三连/数据分离问答）
│   ├── 股息率调研.md                   # H20269/H30269/512890 股息率口径与免费数据源
│   └── index.html                     # 看板页面（GitHub Pages 发布对象）
│
├── data/                  # 原始行情数据（CSV / XLSX）
└── output/                # 全部产物
    ├── backtests/
    │   ├── 横向统计报告.md               # ★ 21 组横向对比，先读这个
    │   ├── 横向统计_指标总表.csv          # 同上，机器可读
    │   ├── 横向统计_分阶段明细.csv        # 108 行阶段级明细
    │   ├── 横向统计_超额曲线对比.html     # 21 组超额（策略−满仓）曲线叠加
    │   ├── h20269/<起始日>起_<特征>/     # 16 组 H20269 回测
    │   └── etf512890/<起始日>起_<特征>/  # 5 组 ETF 回测
    ├── analysis/                       # ⚠️ 历史专题，不在主线（MA250 静态图）
    └── reports/                        # ⚠️ 历史专题，不在主线（RSI 止盈分析）
```

### 关于「历史专题，不在主线」

`output/analysis/` 与 `output/reports/` 是一次性专题产物，**不属于策略回测主线**，
也**不随主线重跑而更新**。判断结论时请以 `output/backtests/横向统计报告.md` 为准。

- **不受指标 Bug 修复影响**：两者只依赖 `data_calculator.MA250DataCalculator`
  （纯价格 / MA250 / RSI 计算），不碰 Bug A~K 所在的策略指标代码。
  RSI 报告里的"30 日内最深回撤"是**前视价格回撤**，与策略最大回撤不是同一个东西。
- **但数据口径已落后**：`analysis/` 下 3 个 HTML 生成于 2026-07-21，
  而 `data/H20269历史数据.csv` 现已到 **2026-08-04** —— 这些图**不含最新数据**。
  `analysis/515450_20260625数据/` 更是 2026-06-25 的 515450 备用标的产物，与主线无关。
- **需要时的重跑方式**：
  ```bash
  python core/analyze_ma250.py            # → output/analysis/（同名覆盖）
  python scripts/backtest/generate_rsi_report.py   # → output/reports/（按数据末日命名）
  ```
  RSI 报告文件名中的日期取自**数据最后一天**（`data_end_date`），不是写死的：
  数据更新后重跑会**新增**一个新日期的文件，不覆盖旧的 —— 旧报告会留在目录里，
  读的时候注意挑日期最新的那份。

## 快速开始

```bash
pip install -r requirements.txt

# 主力回测：3 个起始日
python scripts/backtest/run_multiple_backtests.py

# 扩展情景：H20269 10 个起始日 / 512890 ETF 5 个起始日
python scripts/backtest/run_extended_backtests.py
python scripts/backtest/run_512890_backtests.py

# 3 组历史手工回测组（别漏掉，含审计脚本的默认引用组）
python scripts/backtest/run_orphan_backtests.py

# ★ 21 组横向统计报告（累计/年化/回撤/夏普/索提诺/同仓位混合超额 + 分阶段胜负）
python scripts/backtest/build_cross_group_report.py

# 只重画图（不重跑回测，快得多）
python scripts/backtest/regenerate_charts.py

# 审计：验证 8 个已修 bug 未回归 + 查看仍未通过的检验
python tools/audit_checks.py
```

脚本可以从**任意目录**调用：每个文件顶部都有一段 `PROJECT-ROOT BOOTSTRAP`
前言，负责把项目根与 `core/` 挂到 `sys.path` 并把工作目录切到项目根。
因此代码里的 `data/...`、`output/...` 相对路径始终有效。

## 每日数据自动更新与手机看板（2026-10-23 新增）

不再需要去中证指数官网手动下载 xlsx：

```bash
python scripts/data/update_data.py      # H20269 官网API增量追加 + 512890 前复权全量刷新
python scripts/dashboard/build_dashboard.py  # 生成 docs/index.html（乖离率/RSI/均线/止盈信号灯）
```

推送 GitHub 并启用 Pages 后，`.github/workflows/update-dashboard.yml` 会在
**每交易日 19:30 / 22:00（北京时间）** 自动拉数据、重建看板并提交，
手机访问 `https://<用户名>.github.io/<仓库名>/` 即可查看。

**备选：Render.com 实时渲染**（`dashboard_app.py`，打开页面时现拉现算，ETF 盘中
可看当日价）——同一仓库连接 Render 即可，配置由 `render.yaml` 自动带入，
两种部署可共存。一次性配置步骤与信号灯的历史检验结论见 `docs/DASHBOARD_GUIDE.md`。

数据写入纪律：`H20269历史数据.csv` **只追加**（旧回测可复现）；512890 看板
用独立文件 `512890行情数据.csv`（全量刷新），回测原文件不动。

## 复现「改前 / 改后」对比

`tools/ab_compare/` 用**反向补丁**重建修 bug 之前的源码，再用同一批数据跑一遍，
从而给出可核对的差异归因（而非事后叙述）。每处反向替换都必须**命中且仅命中一次**，
否则脚本立即 `exit(1)` —— 保证重建出的 legacy 版本忠实对应改前代码。

```bash
python tools/ab_compare/build_legacy.py
python tools/ab_compare/run_ab.py --version legacy  --out tools/ab_compare/result_legacy.json
python tools/ab_compare/run_ab.py --version current --out tools/ab_compare/result_current.json
python tools/ab_compare/make_report.py
```

## 阅读顺序建议

1. `docs/progress.md` 的[⭐ 快速恢复指引](docs/progress.md#-下次对话快速恢复指引)与
   [★ 结论卡](docs/progress.md#-结论卡双基准口径全文唯一权威处) —— 当前数据与全部结论口径
   （历史章节已拆到 `docs/progress_archive.md`，**封存只读，勿引用其中数字**）
2. `output/backtests/横向统计报告.md` —— 21 组横向全景（含两个基准的口径说明）
3. `tools/ab_compare/改前改后对比报告.md` —— 8 个 bug 各自造成多大偏差
4. `docs/ROLLING_POSITION_STRATEGY.md` —— 策略规则本身
5. `python tools/audit_checks.py` —— 现在还有哪些问题没解决

## 注意

- 本项目已于 2026-10-23 初始化为 git 仓库（此前无版本控制，历史产物靠
  `_retired_2026-08-23/` 等目录手工归档；该目录体积过大**未入库**，仍在磁盘上）。
  推送 GitHub 后方可启用每日自动更新与 Pages 看板。
- `output/` 下 16 组回测已于 2026-08-23 用修复后代码全部重跑，并与
  `tools/ab_compare/result_current.json` 逐组核对一致（差异 < 0.01pp）。
  若今后再改动 `core/`，请重跑以下三个脚本 + `run_orphan_backtests.py`，
  否则报告会与代码脱节。
- ⚠️ 有 3 组回测（两个 `2015-05起_*` 与 `2026-05起_50万本金`）历史上是手工跑的，
  现由 `scripts/backtest/run_orphan_backtests.py` 负责 —— **别忘了它**，
  其中 `2015-05起_深度定投策略` 是审计脚本的默认引用组。
