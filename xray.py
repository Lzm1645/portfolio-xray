#!/usr/bin/env python3
"""portfolio-xray：把一份持仓 CSV 变成可读的「组合体检」报告。

数据源：东方财富公开行情接口（无需 API Key）。输出 Markdown，便于直接发给人或存档。
用法：
    python3 xray.py holdings.csv
    python3 xray.py holdings.csv --out report.md --currency USD

持仓 CSV 列：ticker, shares, cost_basis(可选), note(可选)
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import json
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path

UA = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)"}
MARKETS = ("105", "106", "107")  # 纳斯达克 / 纽交所 / 美交所(Arca)

# 资产类别（用于风险汇总和情景测算）；未列出的按股票处理。
BOND_DURATION = {
    "TLT": 16.0,
    "IEF": 7.0,
    "SHY": 2.0,
    "BIL": 0.1,
    "AGG": 6.0,
    "BND": 6.0,
    "LQD": 8.0,
    "HYG": 3.5,
    "TIP": 6.5,
    "VGIT": 5.0,
    "VCSH": 2.0,
}
COMMODITY = {"GLD", "IAU", "SLV", "USO", "DBC", "GDX"}
CRYPTO = {"IBIT", "GBTC", "FBTC", "ETHA", "BITO"}
CASH = {"BIL", "SHV", "SGOV"}


@dataclass
class Holding:
    ticker: str
    shares: float
    cost_basis: float | None = None
    note: str = ""


@dataclass
class Quote:
    ticker: str
    name: str
    secid: str
    price: float
    chg_pct: float
    pe: float | None
    pb: float | None


def _get(url: str, timeout: int = 15) -> dict:
    request = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310 - fixed https endpoints
        return json.load(response)


def find_secid(ticker: str) -> str | None:
    """在三个美股市场里定位代码（105 纳指 / 106 纽交所 / 107 Arca）。"""
    for market in MARKETS:
        query = urllib.parse.urlencode(
            {"fltt": 2, "secids": f"{market}.{ticker}", "fields": "f12,f14"}
        )
        try:
            data = _get(f"https://push2.eastmoney.com/api/qt/ulist.np/get?{query}")
        except Exception:  # noqa: BLE001 - 某个市场不可用就换下一个
            continue
        rows = (data.get("data") or {}).get("diff") or []
        if rows and (rows[0].get("f12") or "").upper() == ticker.upper():
            return f"{market}.{ticker}"
    return None


def batch_quotes(tickers: list[str]) -> dict[str, Quote]:
    """一次性拿所有代码的价格：对每个代码试三个市场，收集命中的。"""
    by_ticker: dict[str, Quote] = {}
    for start in range(0, len(tickers), 10):
        chunk = tickers[start : start + 10]
        secids = [f"{market}.{t}" for t in chunk for market in MARKETS]
        query = urllib.parse.urlencode(
            {"fltt": 2, "secids": ",".join(secids), "fields": "f2,f3,f9,f12,f14,f20,f23"}
        )
        data = _get(f"https://push2.eastmoney.com/api/qt/ulist.np/get?{query}")
        for row in (data.get("data") or {}).get("diff") or []:
            ticker = (row.get("f12") or "").upper()
            if ticker in by_ticker or not row.get("f14"):
                continue
            by_ticker[ticker] = Quote(
                ticker=ticker,
                name=row.get("f14") or ticker,
                secid="",
                price=float(row.get("f2") or 0),
                chg_pct=float(row.get("f3") or 0),
                pe=float(row.get("f9") or 0) or None,
                pb=float(row.get("f23") or 0) or None,
            )
    return by_ticker


def kline_returns(secid: str) -> dict[str, float]:
    """取日 K，算 YTD / 近 1 年收益。失败返回空 dict。"""
    if not secid:
        return {}
    query = urllib.parse.urlencode(
        {
            "secid": secid,
            "klt": 101,
            "fqt": 1,
            "beg": 20240101,
            "end": 20500101,
            "fields1": "f1,f2,f3,f4,f5,f6",
            "fields2": "f51,f52,f53",
        }
    )
    try:
        data = _get(f"https://push2his.eastmoney.com/api/qt/stock/kline/get?{query}")
    except Exception:  # noqa: BLE001 - 单只失败不影响报告
        return {}
    rows = (data.get("data") or {}).get("klines") or []
    series = []
    for row in rows:
        parts = row.split(",")
        if len(parts) > 2:
            series.append((parts[0], float(parts[2])))
    if not series:
        return {}
    last_date, last = series[-1]
    result = {"date": last_date}
    year = [p for d, p in series if d >= "2026-01-01"]
    if year:
        result["ytd"] = round((last / year[0] - 1) * 100, 1)
    target = (dt.date.fromisoformat(last_date) - dt.timedelta(days=365)).isoformat()
    older = [p for d, p in series if d <= target]
    if older:
        result["1y"] = round((last / older[-1] - 1) * 100, 1)
    return result


def load_holdings(path: Path) -> list[Holding]:
    holdings = []
    with path.open(newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            ticker = (row.get("ticker") or "").strip().upper()
            if not ticker:
                continue
            shares = float(row.get("shares") or 0)
            if shares == 0:
                continue
            cost = row.get("cost_basis")
            holdings.append(
                Holding(
                    ticker=ticker,
                    shares=shares,
                    cost_basis=float(cost) if cost not in (None, "") else None,
                    note=(row.get("note") or "").strip(),
                )
            )
    return holdings


ASSET_LABEL = {"equity": "股票", "bond": "债券", "commodity": "商品", "crypto": "加密", "cash": "现金"}


def asset_class(ticker: str) -> str:
    if ticker in BOND_DURATION:
        return "bond"
    if ticker in COMMODITY:
        return "commodity"
    if ticker in CRYPTO:
        return "crypto"
    if ticker in CASH:
        return "cash"
    return "equity"


def build_report(holdings: list[Holding], quotes: dict[str, Quote], returns: dict[str, dict]) -> dict:
    rows = []
    for holding in holdings:
        quote = quotes.get(holding.ticker)
        price = quote.price if quote else 0.0
        value = price * holding.shares
        info = returns.get(holding.ticker) or {}
        rows.append(
            {
                "ticker": holding.ticker,
                "name": quote.name if quote else "（未找到行情）",
                "shares": holding.shares,
                "price": price,
                "value": value,
                "pe": quote.pe if quote else None,
                "ytd": info.get("ytd"),
                "1y": info.get("1y"),
                "asset": asset_class(holding.ticker),
                "cost": holding.cost_basis,
                "note": holding.note,
            }
        )
    total = sum(row["value"] for row in rows)
    for row in rows:
        row["weight"] = (row["value"] / total * 100) if total else 0.0
    rows.sort(key=lambda row: row["value"], reverse=True)

    class_values: dict[str, float] = {}
    for row in rows:
        class_values[row["asset"]] = class_values.get(row["asset"], 0.0) + row["value"]

    def share(asset: str) -> float:
        return class_values.get(asset, 0.0) / total * 100 if total else 0.0

    equity = share("equity")
    bond = share("bond")
    top5 = sum(row["weight"] for row in rows[:5])
    top1 = rows[0]["weight"] if rows else 0.0

    # 情景：只做一阶近似，用资产类别而非单票 beta。
    bond_shock = 0.0
    for row in rows:
        duration = BOND_DURATION.get(row["ticker"], 0.0)
        bond_shock += row["value"] * (-duration * 0.01)  # 利率 +100bp
    scenarios = {
        "股票 -10%": total and (equity / 100 * total * -0.10) / total * 100,
        "股票 -20% + 利率 +100bp": total and ((equity / 100 * total * -0.20) + bond_shock) / total * 100,
        "风险偏好回升（股 +10%、利率 +50bp、金 -5%）": total
        and (
            equity / 100 * total * 0.10
            + sum(row["value"] * (-BOND_DURATION.get(row["ticker"], 0.0) * 0.005) for row in rows)
            + class_values.get("commodity", 0.0) * -0.05
        )
        / total
        * 100,
    }

    warnings = []
    if top1 > 25:
        warnings.append(f"第一大持仓占 {top1:.1f}%，集中度偏高（建议单一持仓 ≤ 20%）。")
    if top5 > 70:
        warnings.append(f"前五大持仓占 {top5:.1f}%，组合分散度不足。")
    if equity > 90:
        warnings.append(f"股票类占 {equity:.1f}%，几乎没有债券/现金缓冲，回撤会直接打在净值上。")
    if bond > 60:
        warnings.append(f"债券类占 {bond:.1f}%，利率上行时久期风险集中。")

    return {
        "rows": rows,
        "total": total,
        "top1": top1,
        "top5": top5,
        "class_share": {"equity": equity, "bond": bond, "commodity": share("commodity"), "crypto": share("crypto"), "cash": share("cash")},
        "scenarios": scenarios,
        "warnings": warnings,
        "data_date": next((info.get("date") for info in returns.values() if info.get("date")), "未知"),
        "generated_at": dt.datetime.now().astimezone().isoformat(timespec="seconds"),
    }


def _fmt_pct(value: float | None) -> str:
    return "—" if value is None else f"{value:+.1f}%"


def render_markdown(result: dict) -> str:
    lines = [
        "# 组合体检报告",
        "",
        f"> 生成时间：{result['generated_at']}　行情日期：{result['data_date']}（收盘价）",
        "> 数据来自东方财富公开行情，可能存在延迟；本报告是数据分析，不构成投资建议。",
        "",
        "## 一、总览",
        "",
        f"- 组合市值：**${result['total']:,.2f}**",
        f"- 第一大持仓：{result['top1']:.1f}%；前五大合计：{result['top5']:.1f}%",
        "- 资产类别："
        + " / ".join(
            f"{name} {value:.1f}%"
            for name, value in (
                ("股票", result["class_share"]["equity"]),
                ("债券", result["class_share"]["bond"]),
                ("商品", result["class_share"]["commodity"]),
                ("加密", result["class_share"]["crypto"]),
                ("现金", result["class_share"]["cash"]),
            )
            if value > 0
        ),
        "",
        "## 二、持仓明细",
        "",
        "| 代码 | 名称 | 股数 | 价格 | 市值 | 权重 | YTD | 近 1 年 | PE | 资产类别 |",
        "|---|---|---:|---:|---:|---:|---:|---:|---:|---|",
    ]
    for row in result["rows"]:
        pe = "—" if not row["pe"] else f"{row['pe']:.1f}"
        lines.append(
            f"| {row['ticker']} | {row['name']} | {row['shares']:g} | {row['price']:.2f} | "
            f"{row['value']:,.2f} | {row['weight']:.1f}% | {_fmt_pct(row['ytd'])} | "
            f"{_fmt_pct(row['1y'])} | {pe} | {ASSET_LABEL.get(row['asset'], row['asset'])} |"
        )
    lines += ["", "## 三、情景压力测试", "", "| 情景 | 组合影响 |", "|---|---:|"]
    for name, value in result["scenarios"].items():
        if value is not None:
            lines.append(f"| {name} | {value:+.1f}% |")
    lines += [
        "",
        "口径：股票按整体 Beta=1 近似；债券按久期近似（TLT 16、IEF 7、SHY 2、AGG 6）；商品、加密按固定冲击。真实组合的个股 Beta 不同，结果只用于量级判断。",
        "",
        "## 四、风险提示",
        "",
    ]
    lines += [f"- {item}" for item in result["warnings"]] or ["- 未发现明显的集中度或资产类别失衡。"]
    lines += [
        "",
        "## 五、下一步建议",
        "",
        "1. 单一持仓超过 20% 的，分批降到 20% 以内；",
        "2. 股票占比过高时，用短债/货币基金补 10%–20% 的缓冲；",
        "3. 每季度复核一次权重，偏离目标 ±5 个百分点再动手；",
        "4. 以上为通用框架，具体交易请结合自己的期限、税与资金安排。",
        "",
        "---",
        "本报告由 portfolio-xray 生成，仅供研究与学习使用，不构成投资建议。",
    ]
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("holdings", type=Path, help="持仓 CSV 路径")
    parser.add_argument("--out", type=Path, help="Markdown 输出路径；缺省打印到 stdout")
    args = parser.parse_args()

    holdings = load_holdings(args.holdings)
    if not holdings:
        raise SystemExit("持仓为空：检查 CSV 的 ticker / shares 列")
    quotes = batch_quotes([holding.ticker for holding in holdings])
    returns = {}
    for holding in holdings:
        if holding.ticker not in quotes:
            continue
        secid = find_secid(holding.ticker)
        if secid:
            returns[holding.ticker] = kline_returns(secid)
    result = build_report(holdings, quotes, returns)
    if result["total"] <= 0:
        raise SystemExit("没有取到任何行情：检查代码是否正确、网络是否可达（东财接口）")
    markdown = render_markdown(result)
    if args.out:
        args.out.write_text(markdown, encoding="utf-8")
        print(f"wrote {args.out}")
    else:
        print(markdown)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
