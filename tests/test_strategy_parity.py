from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from calculator.rules import IndicatorRow, enrich_profit_exit_reason, evaluate_buy_condition, evaluate_exit_condition
from calculator.market_regime import qqq_regime_label


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


def test_strategy_b_uses_vix_and_oversold_below_ma200_in_downtrend():
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

    result = evaluate_buy_condition(row, vix=31, ixic_dist=-4, ixic_filter_active=False)

    assert result["triggered"] is True
    assert result["strategyType"] == "B"


def test_strategy_b_does_not_trigger_in_normal_market():
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

    assert result["triggered"] is False
    assert result["strategyType"] is None


def test_strategy_h_exits_when_close_loses_ma20_support():
    row = IndicatorRow(
        stock_name="TE",
        current_price=94.9,
        ma20=100,
        entry_price=120,
    )

    result = evaluate_exit_condition(row, strategy_type="H", trading_days=5)

    assert result["shouldExit"] is True
    assert result["reason"] == "20일선 지지 실패 손절 -5.10% [20일선 대비 -5%]"


def test_qqq_regime_label_uses_four_simple_market_states():
    assert qqq_regime_label(-4, False) == "하락장"
    assert qqq_regime_label(5, False) == "정상장"
    assert qqq_regime_label(12, False) == "횡보장 고점"
    assert qqq_regime_label(12, True) == "회복장"


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


def test_strategy_g_blocks_late_recovery_over_fourteen_percent():
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
        ixic_dist=15,
        ixic_filter_active=False,
        nasdaq_buy_block_max=18,
        is_recovery_market=True,
    )

    assert result["triggered"] is False
    assert result["strategyType"] is None


def test_strategy_f_blocks_non_recovery_sideways_high():
    row = IndicatorRow(
        stock_name="PL",
        current_price=110,
        ma200=100,
        pct_b_low=3,
    )

    blocked = evaluate_buy_condition(
        row,
        vix=20,
        ixic_dist=12,
        ixic_filter_active=False,
        nasdaq_buy_block_max=9,
        is_recovery_market=False,
    )
    recovery = evaluate_buy_condition(
        row,
        vix=20,
        ixic_dist=12,
        ixic_filter_active=False,
        nasdaq_buy_block_max=18,
        is_recovery_market=True,
    )

    assert blocked["triggered"] is False
    assert blocked["strategyType"] is None
    assert recovery["triggered"] is True
    assert recovery["strategyType"] == "F"


def test_strategy_g_uses_twelve_percent_target_and_twelve_percent_stop():
    target_row = IndicatorRow(stock_name="MSFT", current_price=112, entry_price=100)
    stop_row = IndicatorRow(stock_name="MSFT", current_price=88, entry_price=100)

    target = evaluate_exit_condition(target_row, strategy_type="G", trading_days=10)
    stop = evaluate_exit_condition(stop_row, strategy_type="G", trading_days=10)

    assert target["shouldExit"] is True
    assert "목표 수익" in target["reason"]
    assert "급락 후 회복장 20일선 눌림 기준 +12%" in target["reason"]
    assert stop["shouldExit"] is True
    assert "손절" in stop["reason"]
    assert "급락 후 회복장 20일선 눌림 기준 -12%" in stop["reason"]


def test_strategy_d_target_exit_reason_includes_return_and_strategy_target():
    row = IndicatorRow(stock_name="PL", current_price=117.7, entry_price=100)

    result = evaluate_exit_condition(row, strategy_type="D", trading_days=10)

    assert result["shouldExit"] is True
    assert result["reason"] == (
        "목표 수익 달성 즉시 매도 +17.70% [200일선 상방 & 상승 흐름 강화 기준 +12%]"
    )


def test_all_strategies_exit_when_twenty_five_day_rebound_stalls():
    row = IndicatorRow(stock_name="MSFT", current_price=102.99, entry_price=100)

    for strategy in ("A", "B", "C", "D", "E", "F", "G"):
        result = evaluate_exit_condition(row, strategy_type=strategy, trading_days=25)

        assert result["shouldExit"] is True
        assert "25거래일 반등 미달" in result["reason"]


def test_stalled_rebound_exit_waits_until_day_twenty_five_and_below_three_percent():
    day_twenty_four_row = IndicatorRow(stock_name="MSFT", current_price=104, entry_price=100)
    three_pct_row = IndicatorRow(stock_name="MSFT", current_price=103, entry_price=100)

    day_twenty_four = evaluate_exit_condition(day_twenty_four_row, strategy_type="A", trading_days=24)
    three_pct = evaluate_exit_condition(three_pct_row, strategy_type="A", trading_days=25)

    assert day_twenty_four["shouldExit"] is False
    assert three_pct["shouldExit"] is False


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


def test_enrich_exit_reason_adds_strategy_stop_threshold_to_legacy_reason():
    result = enrich_profit_exit_reason("손절 기준 도달", "G", -11.09)

    assert result == "손절 기준 도달 -11.09% [급락 후 회복장 20일선 눌림 기준 -12%]"


if __name__ == "__main__":
    test_strategy_a_matches_sheet_conditions()
    test_strategy_b_uses_vix_and_oversold_below_ma200_in_downtrend()
    test_strategy_b_does_not_trigger_in_normal_market()
    test_strategy_h_exits_when_close_loses_ma20_support()
    test_qqq_regime_label_uses_four_simple_market_states()
    test_exit_condition_for_non_ef_target_is_immediate()
    test_nasdaq_peak_exit_skips_exempt_strategies()
    test_nasdaq_peak_exit_skips_g_recovery_pullback()
    test_nasdaq_peak_exit_still_applies_to_b_and_d()
    test_strategy_g_recovery_ma20_pullback_signal()
    test_strategy_g_blocks_late_recovery_over_fourteen_percent()
    test_strategy_f_blocks_non_recovery_sideways_high()
    test_strategy_g_uses_twelve_percent_target_and_twelve_percent_stop()
    test_all_strategies_exit_when_twenty_five_day_rebound_stalls()
    test_stalled_rebound_exit_waits_until_day_twenty_five_and_below_three_percent()
    test_exit_condition_for_ef_waits_for_macd_turn()
    test_enrich_exit_reason_adds_strategy_stop_threshold_to_legacy_reason()
    print("strategy parity smoke tests passed")
