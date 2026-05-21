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


def test_nasdaq_peak_exit_skips_exempt_strategies():
    row = IndicatorRow(
        stock_name="AAPL",
        current_price=110,
        entry_price=100,
    )

    result = evaluate_exit_condition(row, strategy_type="A", nasdaq_peak_alert=True, trading_days=10)

    assert result["shouldExit"] is False


def test_nasdaq_peak_exit_skips_g_recovery_pullback():
    row = IndicatorRow(
        stock_name="MSFT",
        current_price=110,
        entry_price=100,
    )

    result = evaluate_exit_condition(row, strategy_type="G", nasdaq_peak_alert=True, trading_days=10)

    assert result["shouldExit"] is False


def test_nasdaq_peak_exit_still_applies_to_b_and_d():
    row = IndicatorRow(
        stock_name="AAPL",
        current_price=110,
        entry_price=100,
    )

    result = evaluate_exit_condition(row, strategy_type="D", nasdaq_peak_alert=True, trading_days=10)

    assert result["shouldExit"] is True
    assert "나스닥 고점" in result["reason"]


def test_strategy_g_recovery_ma20_pullback_signal():
    row = IndicatorRow(
        stock_name="MSFT",
        current_price=122,
        ma200=100,
        ma20=115,
        ma20_d1=114,
        ma20_prev5=114.2,
        close_d1=116,
        candle_low=114.8,
        rsi=58,
        vol_ratio20=1.2,
    )

    result = evaluate_buy_condition(
        row,
        vix=20,
        ixic_dist=12,
        ixic_filter_active=False,
        nasdaq_buy_block_max=18,
        is_recovery_market=True,
    )

    assert result["triggered"] is True
    assert result["strategyType"] == "G"


def test_strategy_g_uses_twelve_percent_target_and_ten_percent_stop():
    target_row = IndicatorRow(stock_name="MSFT", current_price=112, entry_price=100)
    stop_row = IndicatorRow(stock_name="MSFT", current_price=90, entry_price=100)

    target = evaluate_exit_condition(target_row, strategy_type="G", trading_days=10)
    stop = evaluate_exit_condition(stop_row, strategy_type="G", trading_days=10)

    assert target["shouldExit"] is True
    assert "목표 수익" in target["reason"]
    assert stop["shouldExit"] is True
    assert "손절" in stop["reason"]


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
    test_nasdaq_peak_exit_skips_exempt_strategies()
    test_nasdaq_peak_exit_skips_g_recovery_pullback()
    test_nasdaq_peak_exit_still_applies_to_b_and_d()
    test_strategy_g_recovery_ma20_pullback_signal()
    test_strategy_g_uses_twelve_percent_target_and_ten_percent_stop()
    test_exit_condition_for_ef_waits_for_macd_turn()
    print("strategy parity smoke tests passed")
