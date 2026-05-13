from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from calculator.pipeline import preserve_existing_values
from calculator.sheet_sources import snapshot_value


def test_snapshot_value_does_not_cross_into_later_snapshot_cells():
    html = (
        '<td><div class="snapshot-td-label">Market Cap</div></td>'
        '<td><div class="snapshot-td-content"><svg></svg></div></td>'
        '<td><div class="snapshot-td-label">Inverse/Leveraged</div></td>'
        '<td><div class="snapshot-td-content"><b>106.49%</b></div></td>'
    )

    assert snapshot_value(html, "Market Cap") == "-"
    assert snapshot_value(html, "Inverse/Leveraged") == "106.49%"


def test_preserve_existing_values_drops_invalid_cached_market_cap():
    row = preserve_existing_values(
        {"marketCap": "-", "sales": "-"},
        {"marketCap": "106.49%", "sales": "$1.00B"},
    )

    assert row["marketCap"] == "-"
    assert row["sales"] == "$1.00B"
