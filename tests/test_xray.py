import csv
import tempfile
import unittest
from pathlib import Path

import xray


def quote(ticker: str, price: float, pe: float | None = None) -> xray.Quote:
    return xray.Quote(ticker=ticker, name=ticker, secid="", price=price, chg_pct=0.0, pe=pe, pb=None)


class LoadHoldingsTest(unittest.TestCase):
    def test_reads_rows_and_skips_zero(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "h.csv"
            path.write_text(
                "ticker,shares,cost_basis,note\nVOO,10,600,core\nnvda,0,,skip\nTSM,3,,chip\n",
                encoding="utf-8",
            )
            holdings = xray.load_holdings(path)
        self.assertEqual([h.ticker for h in holdings], ["VOO", "TSM"])
        self.assertEqual(holdings[0].shares, 10)
        self.assertEqual(holdings[0].cost_basis, 600)
        self.assertEqual(holdings[1].note, "chip")


class AssetClassTest(unittest.TestCase):
    def test_classes(self):
        self.assertEqual(xray.asset_class("VOO"), "equity")
        self.assertEqual(xray.asset_class("TLT"), "bond")
        self.assertEqual(xray.asset_class("GLD"), "commodity")
        self.assertEqual(xray.asset_class("IBIT"), "crypto")
        self.assertEqual(xray.asset_class("NVDA"), "equity")


class ReportTest(unittest.TestCase):
    def setUp(self):
        self.holdings = [
            xray.Holding("VOO", 10),
            xray.Holding("TLT", 10),
            xray.Holding("GLD", 5),
        ]
        self.quotes = {"VOO": quote("VOO", 100), "TLT": quote("TLT", 100), "GLD": quote("GLD", 100)}
        self.returns = {
            "VOO": {"date": "2026-11-06", "ytd": 8.5, "1y": 11.0},
            "TLT": {"date": "2026-11-06", "ytd": -2.2, "1y": -4.4},
            "GLD": {"date": "2026-11-06", "ytd": -6.5, "1y": 1.8},
        }

    def test_weights_and_concentration(self):
        result = xray.build_report(self.holdings, self.quotes, self.returns)
        self.assertAlmostEqual(result["total"], 2500.0)
        weights = {row["ticker"]: row["weight"] for row in result["rows"]}
        self.assertAlmostEqual(weights["VOO"], 40.0)
        self.assertAlmostEqual(sum(weights.values()), 100.0, places=6)
        self.assertAlmostEqual(result["top1"], 40.0)
        self.assertAlmostEqual(result["top5"], 100.0)
        self.assertAlmostEqual(result["class_share"]["equity"], 40.0)
        self.assertAlmostEqual(result["class_share"]["bond"], 40.0)
        self.assertAlmostEqual(result["class_share"]["commodity"], 20.0)

    def test_scenarios(self):
        result = xray.build_report(self.holdings, self.quotes, self.returns)
        self.assertAlmostEqual(result["scenarios"]["股票 -10%"], -4.0, places=6)
        # 股票 -20%：-200；债券 +100bp：TLT 久期 16 → -160；合计 -360 / 2500 = -14.4%
        self.assertAlmostEqual(result["scenarios"]["股票 -20% + 利率 +100bp"], -14.4, places=6)

    def test_warnings_and_render(self):
        result = xray.build_report(self.holdings, self.quotes, self.returns)
        self.assertTrue(any("第一大持仓" in item for item in result["warnings"]))
        markdown = xray.render_markdown(result)
        self.assertIn("# 组合体检报告", markdown)
        self.assertIn("| VOO |", markdown)
        self.assertIn("不构成投资建议", markdown)


if __name__ == "__main__":
    unittest.main()
