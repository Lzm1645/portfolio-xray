# portfolio-xray

把一份持仓 CSV 变成可读的「组合体检」报告：市值、权重、区间收益、估值、集中度、资产类别、三个情景压力测试。

## 为什么做这个

散户的组合问题通常不是「买什么」，而是「不知道自己拿了什么」：单一持仓过重、股票占比过高、没有缓冲、估值和收益看不到。这个工具用公开数据把这几件事一次算清楚，输出一份可以直接发给人看的 Markdown。

## 测试

```bash
PYTHONPATH=. python3 -m unittest discover -s tests -v
```

（当前账号的 GitHub Actions 因计费问题被锁，仓库暂不带 CI 工作流。）

## 用法

```bash
python3 xray.py holdings.example.csv
python3 xray.py holdings.example.csv --out report.md
```

持仓 CSV（UTF-8）：

```csv
ticker,shares,cost_basis,note
VOO,30,600,核心宽基
NVDA,10,150,AI 优质
```

- `ticker`：美股代码；`shares`：股数；`cost_basis`、`note` 可选。
- 数据来自东方财富公开行情接口，无需 API Key；行情为最近收盘价，可能有延迟。

## 输出

Markdown 报告：总览、持仓明细表、情景压力测试、风险提示、下一步建议。

## 口径与限制

- 股票情景按整体 Beta=1 近似，不区分个股 Beta；债券按久期近似（TLT 16、IEF 7、SHY 2、AGG 6）；商品、加密按固定冲击。
- 只覆盖美股/美股 ETF；A 股、港股需要另接数据源。
- 不构成投资建议。

## 合规边界

- 本工具输出的是数据整理、情景测算与通用风控提示，**不是投资建议**，也不做收益承诺、不代客理财。
- 付费交付的形态应是「报告生成服务/模板/工具」，报告里保留免责声明；不建议把它包装成「荐股」或「投资顾问」服务（后者在国内需要相应资质）。
- 行情数据来自东方财富公开接口，商用前请自行确认数据源条款。

## 路线图

- [ ] MCP server 封装，让 Agent 直接调用
- [ ] 支持 A 股/港股持仓
- [ ] 历史回测与再平衡建议
- [ ] 订阅式周报（组合变化 + 风险提醒）

## License

MIT
