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


def test_strategy_3_triggers_on_normal_market_bb_washout():
    row = IndicatorRow(
        stock_name="NVDA",
        current_price=120,
        ma200=100,
        rsi=40,
        pct_b_low=8,
    )
    result = evaluate_buy_condition(
        row,
        vix=15,
        ixic_dist=5,
        ixic_filter_active=False,
        is_recovery_market=False,
    )
    assert result["strategyType"] == "3"
    assert result["conditions"]["3"] == [True, True, True, True]


def test_strategy_3_requires_normal_regime_and_above_ma200():
    row = IndicatorRow(
        stock_name="NVDA",
        current_price=120,
        ma200=100,
        rsi=40,
        pct_b_low=8,
    )
    recovery = evaluate_buy_condition(
        row,
        vix=15,
        ixic_dist=5,
        ixic_filter_active=False,
        is_recovery_market=True,
        season_open=True,
        nasdaq_buy_block_max=18,
    )
    # Recovery + MA touch would be strategy 2 if season open; without MA touch, no S3 either.
    assert recovery["strategyType"] != "3"

    below = evaluate_buy_condition(
        IndicatorRow(stock_name="NVDA", current_price=90, ma200=100, rsi=40, pct_b_low=8),
        vix=15,
        ixic_dist=5,
        ixic_filter_active=False,
        is_recovery_market=False,
    )
    assert below["strategyType"] is None


def test_strategy_3_requires_qqq_buffer_below_seven_percent():
    row = IndicatorRow(stock_name="NVDA", current_price=120, ma200=100, rsi=40, pct_b_low=8)

    result = evaluate_buy_condition(
        row, vix=15, ixic_dist=8, ixic_filter_active=False, is_recovery_market=False
    )

    assert result["strategyType"] is None


def test_strategy_3_exit_uses_tp_sl_time_but_not_unconfirmed_sideways_peak():
    base = IndicatorRow(stock_name="NVDA", current_price=112, entry_price=100)
    tp = evaluate_exit_condition(base, strategy_type="3")
    assert tp["shouldExit"] is True
    assert "익절" in tp["reason"]

    sl = evaluate_exit_condition(
        IndicatorRow(stock_name="NVDA", current_price=74, entry_price=100),
        strategy_type="3",
    )
    assert sl["shouldExit"] is True
    assert "손절" in sl["reason"]

    extended = evaluate_exit_condition(
        IndicatorRow(stock_name="NVDA", current_price=105, entry_price=100),
        strategy_type="3",
        regime_label="횡보장 고점",
    )
    assert extended["shouldExit"] is False

    time_stop = evaluate_exit_condition(
        IndicatorRow(stock_name="NVDA", current_price=105, entry_price=100),
        strategy_type="3",
        trading_days=20,
    )
    assert time_stop["shouldExit"] is True
    assert "보유기간" in time_stop["reason"]

    # Recovery-end / peakTriggered must not force S3 out when own rules are unmet.
    hold = evaluate_exit_condition(
        IndicatorRow(stock_name="NVDA", current_price=105, entry_price=100),
        strategy_type="3",
        recovery_ended=True,
        nasdaq_peak_alert=True,
        trading_days=5,
        regime_label="정상장",
    )
    assert hold["shouldExit"] is False


def test_qqq_regime_label_uses_four_simple_market_states():
    assert qqq_regime_label(-4, False) == "하락장"
    assert qqq_regime_label(5, False) == "정상장"
    assert qqq_regime_label(12, False) == "횡보장 고점"
    assert qqq_regime_label(12, True) == "회복장"


def test_strategy_4_triggers_on_macd_golden_below_ma200_in_allowed_regimes():
    row = IndicatorRow(
        stock_name="AMD",
        current_price=90,
        ma200=100,
        macd_hist=-0.1,
        macd_hist_d1=-0.2,
    )
    # Not golden yet.
    assert evaluate_buy_condition(
        row, vix=15, ixic_dist=-4, ixic_filter_active=False, is_recovery_market=False
    )["strategyType"] is None

    golden = IndicatorRow(
        stock_name="AMD",
        current_price=90,
        ma200=100,
        macd_hist=0.2,
        macd_hist_d1=-0.1,
    )
    downtrend = evaluate_buy_condition(
        golden, vix=15, ixic_dist=-4, ixic_filter_active=False, is_recovery_market=False
    )
    assert downtrend["strategyType"] == "4"

    normal = evaluate_buy_condition(
        golden, vix=15, ixic_dist=5, ixic_filter_active=False, is_recovery_market=False
    )
    assert normal["strategyType"] == "4"

    recovery = evaluate_buy_condition(
        golden, vix=15, ixic_dist=5, ixic_filter_active=False, is_recovery_market=True
    )
    assert recovery["strategyType"] is None

    deep = evaluate_buy_condition(
        IndicatorRow(
            stock_name="AMD",
            current_price=70,
            ma200=100,
            macd_hist=0.2,
            macd_hist_d1=-0.1,
        ),
        vix=15,
        ixic_dist=-4,
        ixic_filter_active=False,
        is_recovery_market=False,
    )
    assert deep["strategyType"] is None


def test_strategy_4_yields_to_strategy_1_and_uses_s1_style_exits():
    panic = IndicatorRow(
        stock_name="AMD",
        current_price=90,
        ma200=100,
        rsi=30,
        cci=-100,
        lr_slope=1,
        lr_trendline=88,
        candle_low=92,
        macd_hist=0.2,
        macd_hist_d1=-0.1,
    )
    result = evaluate_buy_condition(panic, vix=31, ixic_dist=-4, ixic_filter_active=False)
    assert result["strategyType"] == "1"

    held = IndicatorRow(stock_name="AMD", current_price=120, entry_price=100)
    recovery_exit = evaluate_exit_condition(held, strategy_type="4", recovery_ended=True)
    assert recovery_exit["shouldExit"] is True
    assert "회복장 종료" in recovery_exit["reason"]

    peak_exit = evaluate_exit_condition(held, strategy_type="4", nasdaq_peak_alert=True)
    assert peak_exit["shouldExit"] is True
    assert "고점" in peak_exit["reason"]
