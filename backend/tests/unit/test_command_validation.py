"""What a client cannot smuggle in through a command's fields."""

from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from app.domain.protocol import parse_command


@pytest.mark.parametrize("value", ["NaN", "Infinity", "-Infinity"])
def test_a_non_finite_scanner_filter_is_rejected(value: str) -> None:
    """NaN fails every comparison, so as a filter it switches the filter off —
    and it was saved to state.yaml and broadcast back as invalid JSON."""
    payload = json.loads(
        f'{{"action": "scanner.configure", "scanner_id": "small_cap", '
        f'"change_perc_above": {value}}}'
    )
    with pytest.raises(ValidationError):
        parse_command(payload)


def test_a_non_finite_market_cap_is_rejected() -> None:
    with pytest.raises(ValidationError):
        parse_command(
            {"action": "scanner.configure", "scanner_id": "small_cap", "market_cap_below": float("nan")}
        )


@pytest.mark.parametrize("symbol", ["a/b?c=d", "../x", "", "WAYTOOLONGSYMBOL", "A B", "1ABC"])
def test_a_watchlist_symbol_is_held_to_the_ticker_pattern(symbol: str) -> None:
    """It is saved, broadcast to every window and sent to TradingView."""
    with pytest.raises(ValidationError):
        parse_command({"action": "watchlist.add", "symbol": symbol})


def test_a_blank_trade_rate_clears_like_every_other_filter() -> None:
    """The panel sends "clear" for a blank field. A trade rate that could not
    be cleared rejected the whole command, and none of the filters applied."""
    command = parse_command(
        {"action": "scanner.configure", "scanner_id": "small_cap", "above_trade_rate": "clear"}
    )
    assert command.above_trade_rate == "clear"


def test_a_fractional_trade_rate_is_rejected() -> None:
    with pytest.raises(ValidationError):
        parse_command(
            {"action": "scanner.configure", "scanner_id": "small_cap", "above_trade_rate": 1.5}
        )


def test_a_watchlist_symbol_is_normalised_as_a_charts_is() -> None:
    assert parse_command({"action": "watchlist.add", "symbol": " brk.b "}).symbol == "BRK.B"
    assert parse_command({"action": "watchlist.remove", "symbol": "zm"}).symbol == "ZM"
