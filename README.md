# 美股 Top100 历史K线报表

一个用于查看 **美股市值 Top100、标普500与纳指100** 行情和基本面的可视化报表项目。后端拉取 Yahoo Finance 数据并持久化到 SQLite，前端用 ECharts 展示 K 线、技术指标及多公司对比，且适配移动端。

数据源：Yahoo Finance（通过 `yfinance`）
技术栈：Python + FastAPI + Uvicorn · 前端原生 HTML/CSS/JS + ECharts 5

---

## 功能特性

- **三大指数切换**：市值 Top100 / 标普500 / 纳指100，成分股清单从 slickcharts 实时抓取（带 6 小时缓存），失败自动回退内置静态清单。
- **市值/权重排序**：Top100 按市值降序、指数成分股按权重排序，也支持按名称排序；实时市值/权重随数据源更新。
- **历史K线 + 多周期**：每家公司提供日/周/月三档 K 线蜡烛图，含 MA5/MA20/MA60 均线、成交量、十字光标联动、缩放（dataZoom）、悬停涨跌幅。
- **技术指标叠加**：K 线模式可切换 均线 / MACD / RSI / 布林带（MACD 与 RSI 在副图显示，布林带叠加主图）。
- **多公司对比**：对比模式勾选多家公司，同一时间轴绘制收盘价曲线直观比对；带 logo 标签可随时移除。
- **指数走势叠加**：对比图可叠加 标普500 / 纳指 / 道指 指数线（虚线），看个股相对大盘的强弱。
- **市场涨跌排行**：列表第三个 tab 切到「涨跌排行」，显示当日领涨/领跌水平柱状图（按指数实时拉取）。
- **数据落盘**：历史 K 线写入 SQLite 本地库（6 小时新鲜度），重复访问读库、离线可用、跨重启保留。
- **数据导出**：`/api/export/{ticker}` 导出 CSV / JSON，方便做进一步报表分析。
- **公司Logo**：每行展示公司 logo（Financial Modeling Prep 免费源，失败自动回退首字母占位），由后端代理规避跨域。
- **搜索**：按代码或公司名实时过滤。
- **移动端适配**：`<768px` 自动切换 App 式布局——列表/图表切换视图，带返回按钮、横向滑动时间条。
- **后端缓存**：K 线/对比 5 分钟内存缓存 + 成分股 6 小时缓存 + logo 1 天缓存，减少外部请求。

---

## 项目结构

```
/root/project/Top100/
├── server.py        # FastAPI 后端：指数/成分股清单 + 实时市值/排行 + 历史K线(落盘) + 对比 + 导出 + logo代理
├── top100.py        # 市值 Top100 公司清单 (ticker, 名称, 市值/十亿美元, 行业)
├── indices.py       # 标普500/纳指100 成分股抓取(带缓存)与内置回退清单
├── store.py         # SQLite 历史K线落盘与导出(CSV/JSON)
├── fundamentals.py  # 估值、年度财报、分红抓取与SQLite缓存
├── market.db        # SQLite长期数据文件（运行时自动创建/更新）
├── tests/           # 接口、SQLite和前端契约测试
├── start.sh         # 启动脚本（可传端口参数，默认 8000）
├── README.md        # 项目说明文档
├── shots/           # 无头浏览器渲染截图（用于视觉检查）
├── static/
│   ├── index.html   # 前端页面（Claude 风格 + 移动端响应式）
│   └── app.js       # 前端逻辑（列表/logo、K线+技术指标、多周期、对比+指数叠加、排行）
└── .venv/           # 虚拟环境（Python 3.9 + yfinance/fastapi/uvicorn/requests/bs4）
```

---

## 快速启动

```bash
cd /root/project/Top100
bash start.sh            # 默认端口 8000
# 或指定端口
bash start.sh 9000
```

启动后浏览器访问：

- 本机：`http://127.0.0.1:8000`
- 局域网/手机：`http://<服务器IP>:8000`（需开放对应端口）

### 手动启动（不依赖脚本）

```bash
cd /root/project/Top100
.venv/bin/python -m uvicorn server:app --host 0.0.0.0 --port 8000
```

---

## API 接口

### `GET /api/indices`
返回可用的指数清单。

```json
[
  {"id":"top100","name":"市值 Top100","desc":"美股市值最大的100家公司"},
  {"id":"sp500","name":"标普500","desc":"S&P 500 指数成分股"},
  {"id":"ndx100","name":"纳指100","desc":"Nasdaq-100 指数成分股"}
]
```

### `GET /api/stocks?index=sp500`
返回指定指数的成分股清单（`index` 取值 `top100` / `sp500` / `ndx100`，默认 `top100`）。

```json
[{"rank":1,"symbol":"NVDA","name":"Nvidia","weight_pct":7.58,"market_cap_b":null,"sector":null}, ...]
```

### `GET /api/quote/{ticker}`
返回某公司实时市值（十亿美元）。失败时回退为内置值。

### `GET /api/fundamentals/{ticker}`
返回公司估值、年度财报与分红历史。包括市盈率、市净率、EPS、股息率、派息率、Beta、52周高低点，以及最近年度的营收、净利润、EBITDA、自由现金流、总资产和总负债。结果写入 SQLite 并缓存24小时；传 `refresh=true` 可强制刷新。

### `GET /api/compare?symbols=AAPL,MSFT,NVDA&range=6mo`
多公司收盘价对比，`symbols` 逗号分隔（最多 15 家），`range` 同 K 线接口。返回各公司按日期（毫秒时间戳）的收盘序列。

```json
{"range":"6mo","series":{
  "AAPL":{"name":"Apple","data":[[1694505600000,190.12], ...]},
  "MSFT":{"name":"Microsoft","data":[[1694505600000,330.11], ...]}
}}
```

### `GET /api/stock/{ticker}?range=1mo&interval=1d`
返回某公司指定时间范围和周期的K线（OHLCV）。

`range` 取值：`1mo` `3mo` `6mo` `1y` `2y` `5y` `max`；`interval` 取值：`1d` `1wk` `1mo`。

```json
{
  "ticker":"AAPL","name":"Apple","range":"1mo",
  "start":"2026-08-12","end":"2026-09-11",
  "bars":[["2026-08-12",305.10,302.25,300.57,305.66,41657800], ...]
}
```

> bars 每项格式：`[日期, 开, 收, 低, 高, 量]`

### `GET /api/export/{ticker}?range=1y&fmt=csv`
将 SQLite 中的历史行情导出为 CSV 或 JSON；`fmt` 取值 `csv` / `json`。

---

## 移动端适配说明

- 断点：`max-width: 768px`。
- 交互：进入移动端后，默认显示**公司列表全屏**；点击某家公司进入**图表全屏视图**，顶部 `‹` 按钮返回列表。
- 时间条：横向滑动（`flex-wrap: nowrap` + `overflow-x:auto`）。
- 适配响应式：布局/转屏时图表自动 `resize()`。

电脑上测试：按 F12 打开开发者工具 → 切换到设备模拟，选手机尺寸即可看到移动端效果。

---

## 依赖安装（如需重建环境）

```bash
cd /root/project/Top100
python3 -m venv .venv
.venv/bin/pip install yfinance fastapi "uvicorn[standard]" requests beautifulsoup4 lxml pytest httpx
```

---

## 测试验证

```bash
cd /root/project/Top100
.venv/bin/pytest -q
node --check static/app.js
.venv/bin/python -m py_compile server.py store.py fundamentals.py indices.py top100.py
```

SQLite 文件为 `market.db`，当前包含：

- `bars`：按股票、周期和日期保存 OHLCV，主键防止重复。
- `meta`：行情数据最后更新时间。
- `fundamentals_cache`：基本面、财报和分红 JSON 缓存。

## 后续可扩展方向

- 增加季度财报与同比/环比增长率。
- 将多公司对比切换为“归一化涨跌幅”模式，避免不同股价量级影响直观比较。
- 通过 nginx 反代绑定域名，并用 systemd 守护开机自启。