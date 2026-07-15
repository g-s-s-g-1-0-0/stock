from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from calculator.rules import IndicatorRow, evaluate_buy_condition, evaluate_exit_condition
from calculator.market_regime import qqq_regime_label


def test_strategy_1_uses_vix_and_oversold_below_ma200_in_downtrend():
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
    assert result["strategyType"] == "1"


def test_strategy_1_does_not_trigger_in_normal_market():
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


def test_strategy_2_requires_season_and_recovery_ma_touch():
    row = IndicatorRow(
        stock_name="MSFT",
        current_price=101,
        ma200=100,
        ma20=100,
        ma60=99,
        ma144=98,
        candle_low=99.5,
    )

    closed = evaluate_buy_condition(
        row,
        vix=15,
        ixic_dist=5,
        ixic_filter_active=False,
        is_recovery_market=True,
        season_open=False,
        nasdaq_buy_block_max=18,
    )
    assert closed["strategyType"] is None

    opened = evaluate_buy_condition(
        row,
        vix=15,
        ixic_dist=5,
        ixic_filter_active=False,
        is_recovery_market=True,
        season_open=True,
        nasdaq_buy_block_max=18,
        warn_triggered=False,
    )
    assert opened["strategyType"] == "2"


def test_strategy_2_warn_line_no_longer_blocks_entry():
    row = IndicatorRow(
        stock_name="MSFT",
        current_price=101,
        ma200=100,
        ma20=100,
        candle_low=99.5,
    )
    result = evaluate_buy_condition(
        row,
        vix=15,
        ixic_dist=10,
        ixic_filter_active=False,
        is_recovery_market=True,
        season_open=True,
        nasdaq_buy_block_max=18,
        warn_triggered=True,
    )
    assert result["strategyType"] == "2"


def test_strategy_2_blocked_by_buy_block():
    row = IndicatorRow(
        stock_name="MSFT",
        current_price=101,
        ma200=100,
        ma20=100,
        candle_low=99.5,
    )
    result = evaluate_buy_condition(
        row,
        vix=15,
        ixic_dist=19,
        ixic_filter_active=False,
        is_recovery_market=True,
        season_open=True,
        nasdaq_buy_block_max=18,
        warn_triggered=False,
    )
    assert result["strategyType"] is None
    assert result["conditions"]["2"] == [True, True, False, True]

def test_exit_recovery_end_marks_success_when_positive():
    row = IndicatorRow(stock_name="AAPL", current_price=120, entry_price=100)
    result = evaluate_exit_condition(row, strategy_type="1", recovery_ended=True)
    assert result["shouldExit"] is True
    assert "회복장 종료" in result["reason"]
    assert "성공" in result["reason"]


def test_exit_hard_stop_still_applies():
    row = IndicatorRow(stock_name="AAPL", current_price=69, entry_price=100)
    result = evaluate_exit_condition(row, strategy_type="1")
    assert result["shouldExit"] is True
    assert "손절" in result["reason"]


def test_exit_no_profit_target_or_time():
    row = IndicatorRow(stock_name="AAPL", current_price=110, entry_price=100)
    result = evaluate_exit_condition(row, strategy_type="1", trading_days=200)
    assert result["shouldExit"] is False


def test_qqq_regime_label_uses_four_simple_market_states():
    assert qqq_regime_label(-4, False) == "하락장"
    assert qqq_regime_label(5, False) == "정상장"
    assert qqq_regime_label(12, False) == "횡보장 고점"
    assert qqq_regime_label(12, True) == "회복장"
