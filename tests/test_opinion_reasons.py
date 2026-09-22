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

    def test_sparse_watch_reason(self) -> None:
        self.assertTrue(is_sparse_watch_reason("-"))
        self.assertFalse(is_sparse_watch_reason("매수 조건 해제 — 6. 하락 추세 이탈 시도"))


if __name__ == "__main__":
    unittest.main()
