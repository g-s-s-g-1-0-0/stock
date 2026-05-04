from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from calculator.rules import IndicatorRow, evaluate_buy_condition, evaluate_exit_condition


def test_strategy_a_matches_sheet_conditions():
    row = IndicatorRow(
        stock_name="NVDA",
        current_price=110,
        ma200=100,
        macd_hist_d1=-0.1,
        macd_hist=0.2,
        pct_b=85,
        rsi=72,
    )

    result = evaluate_buy_condition(row, vix=20, ixic_dist=0, ixic_filter_active=False)

    assert result["triggered"] is True
    assert result["strategyType"] == "A"


def test_strategy_b_uses_vix_and_oversold_below_ma200():
    row = IndicatorRow(
        stock_name="AAPL",
        current_price=90,
        ma200=100,
        rsi=30,
        cci=-100,
        lr_slope=1,
        lr_trendline=88,
        candle_low=92,
    )

    result = evaluate_buy_condition(row, vix=31, ixic_dist=5, ixic_filter_active=False)

    assert result["triggered"] is True
    assert result["strategyType"] == "B"


def test_exit_condition_for_non_ef_target_is_immediate():
    row = IndicatorRow(
        stock_name="AAPL",
        current_price=121,
        entry_price=100,
    )

    result = evaluate_exit_condition(row, strategy_type="A", trading_days=10)

    assert result["shouldExit"] is True
    assert "즉시" in result["reason"]


def test_exit_condition_for_ef_waits_for_macd_turn():
    row = IndicatorRow(
        stock_name="TSLA",
        current_price=121,
        entry_price=100,
        macd_hist=1.0,
        macd_hist_d1=1.3,
        macd_hist_d2=1.4,
    )

    result = evaluate_exit_condition(row, strategy_type="E", trading_days=10)

    assert result["shouldExit"] is True
    assert "MACD" in result["reason"]


if __name__ == "__main__":
    test_strategy_a_matches_sheet_conditions()
    test_strategy_b_uses_vix_and_oversold_below_ma200()
    test_exit_condition_for_non_ef_target_is_immediate()
    test_exit_condition_for_ef_waits_for_macd_turn()
    print("strategy parity smoke tests passed")
