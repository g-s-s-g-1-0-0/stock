from scripts import sync_watchlist_type_maps as sync


def test_personal_type_map_preserves_existing_investment_types():
    row = {
        "scope": "personal",
        "tickers": [],
        "tickers_by_type": {
            "long_term": [],
            "swing": ["NVDA", "MSFT"],
        },
    }

    assert sync.desired_type_map(row) == {
        "long_term": [],
        "swing": ["NVDA", "MSFT"],
    }


def test_personal_type_map_backfills_missing_type_only():
    row = {
        "scope": "personal",
        "tickers": ["AAPL"],
        "tickers_by_type": {
            "swing": ["NVDA"],
        },
    }

    assert sync.desired_type_map(row) == {
        "long_term": ["AAPL"],
        "swing": ["NVDA"],
    }


def test_operator_type_map_preserves_existing_investment_types():
    row = {
        "scope": "operator",
        "tickers": ["AAPL"],
        "tickers_by_type": {
            "long_term": ["MSFT"],
            "swing": ["NVDA"],
        },
    }

    assert sync.desired_type_map(row) == {
        "long_term": ["MSFT"],
        "swing": ["NVDA"],
    }
