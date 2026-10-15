import unittest

from calculator.opinion_reasons import (
    build_held_watch_opinion_reason,
    exit_criteria_summary,
    format_sell_opinion_reason,
    is_sparse_watch_reason,
)
from calculator.rules import IndicatorRow


class OpinionReasonTests(unittest.TestCase):
    def test_held_watch_reason_includes_strategy_release_and_exit_criteria(self) -> None:
        trade = {
            "market": "KR",
            "strategy": "6. 하락 추세 이탈 시도",
            "supportStopPrice": 347260,
        }
        reason = build_held_watch_opinion_reason(
            "6",
            buy={},
            qqq_market_state={"premiumPercent": 11.8, "buyBlockMax": 9.0},
            ind=IndicatorRow(stock_name="005380", current_price=360500),
            holding_signal_close=367500,
            trade=trade,
        )
        self.assertIn("6. 하락 추세 이탈 시도", reason)
        self.assertIn("QQQ 과열", reason)
        self.assertIn("보유 유지", reason)
        self.assertIn("익절 +12%", reason)
        self.assertIn("347,260", reason)

    def test_exit_criteria_summary_for_strategy_two(self) -> None:
        summary = exit_criteria_summary("2")
        self.assertIn("익절", summary)
        self.assertIn("손절", summary)

    def test_format_sell_opinion_reason_prefixes_strategy(self) -> None:
        reason = format_sell_opinion_reason(
            "익절 기준 도달 +12.00%",
            "6",
            12.0,
            trade={"market": "KR", "strategy": "6. 하락 추세 이탈 시도", "supportStopPrice": 347260},
        )
        self.assertIn("6. 하락 추세 이탈 시도", reason)
        self.assertIn("익절", reason)

    def test_strategy_seven_release_names_the_failed_indicator(self) -> None:
        market = build_held_watch_opinion_reason(
            "7",
            buy={"maTouches": {"20": True}},
            qqq_market_state={"premiumPercent": 10.2, "buyBlockMax": 9},
            ind=IndicatorRow(stock_name="UBER", current_price=70),
        )
        self.assertIn("QQQ 과열", market)
        self.assertIn("+10.2%", market)
        self.assertNotIn("2/2", market)

        touch = build_held_watch_opinion_reason(
            "7",
            buy={"maTouches": {"20": False, "50": False, "120": False, "200": False}},
            qqq_market_state={"premiumPercent": 6.5, "buyBlockMax": 9},
            ind=IndicatorRow(
                stock_name="UBER",
                current_price=70.37,
                candle_low=69.10,
                ma20=71.20,
                ma50=68.00,
                ma120=65.00,
                ma200=60.00,
            ),
        )
        self.assertIn("이평선 터치 이탈", touch)
        self.assertIn("69.10", touch)
        self.assertIn("20일 71.20", touch)

    def test_inverse_release_names_the_short_floor(self) -> None:
        strategy_7 = build_held_watch_opinion_reason(
            "7",
            buy={"maTouches": {"20": True}},
            qqq_market_state={"premiumPercent": 7.23, "buyBlockMax": 9, "isRecoveryMarket": False},
            ind=IndicatorRow(stock_name="SOXS", current_price=45.44),
            inverse=True,
        )
        self.assertIn("QQQ 이격 +7.2% < 차단선 +9%", strategy_7)
        self.assertNotIn("과열", strategy_7)

        strategy_3 = build_held_watch_opinion_reason(
            "3",
            qqq_market_state={"premiumPercent": 6.46, "buyBlockMax": 9, "isRecoveryMarket": False},
            ind=IndicatorRow(stock_name="SQQQ", current_price=20, ma200=10),
            inverse=True,
        )
        self.assertIn("QQQ +7% 미만", strategy_3)
        self.assertNotIn("초과", strategy_3)

    def test_sparse_watch_reason(self) -> None:
        self.assertTrue(is_sparse_watch_reason("-"))
        self.assertFalse(is_sparse_watch_reason("매수 조건 해제 — 6. 하락 추세 이탈 시도"))


if __name__ == "__main__":
    unittest.main()
