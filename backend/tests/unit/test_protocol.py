"""The wire protocol.

Client commands are untrusted input — a symbol ends up inside an upstream API
request — so the validation here is a security boundary, not a formality.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.domain.bars import Bar
from app.domain.protocol import (
    DataSource,
    SubscribeCommand,
    encode_bar,
    error_message,
    parse_command,
    scanner_message,
    snapshot_message,
    status_message,
)
from app.domain.timeframes import Timeframe
from tests.conftest import make_bar, ny_epoch


class TestSubscribeCommand:
    def test_accepts_a_plain_symbol(self):
        command = parse_command({"action": "subscribe", "symbol": "AAPL"})
        assert isinstance(command, SubscribeCommand)
        assert command.symbol == "AAPL"

    def test_uppercases_and_trims(self):
        command = parse_command({"action": "subscribe", "symbol": "  aapl "})
        assert command.symbol == "AAPL"

    def test_defaults_to_one_minute(self):
        command = parse_command({"action": "subscribe", "symbol": "AAPL"})
        assert command.parsed_timeframe is Timeframe.M1

    def test_accepts_a_dotted_symbol(self):
        assert parse_command({"action": "subscribe", "symbol": "BRK.B"}).symbol == "BRK.B"

    @pytest.mark.parametrize(
        "symbol",
        [
            "",
            "TOOOOOOLONG",
            "AA PL",
            "../../etc/passwd",
            "AAPL;DROP",
            "<script>",
            "1AAPL",
            "AAPL&x=1",
            "%2e%2e",
        ],
    )
    def test_rejects_anything_unsafe(self, symbol):
        with pytest.raises(ValidationError):
            parse_command({"action": "subscribe", "symbol": symbol})

    def test_rejects_an_unknown_timeframe(self):
        with pytest.raises(ValidationError):
            parse_command({"action": "subscribe", "symbol": "AAPL", "timeframe": "3s"})

    @pytest.mark.parametrize("timeframe", ["1m", "5m", "15m", "1h", "1d", "1w"])
    def test_accepts_every_supported_timeframe(self, timeframe):
        command = parse_command(
            {"action": "subscribe", "symbol": "AAPL", "timeframe": timeframe}
        )
        assert command.timeframe == timeframe

    def test_rejects_unknown_fields(self):
        with pytest.raises(ValidationError):
            parse_command({"action": "subscribe", "symbol": "AAPL", "evil": 1})


class TestExtraTimeframes:
    """The mini charts: extra timeframes on the same symbol."""

    @staticmethod
    def parse(**overrides):
        return parse_command({"action": "subscribe", "symbol": "AAPL", **overrides})

    def test_defaults_to_none(self):
        assert self.parse().parsed_extra_timeframes == ()

    def test_parses_the_mini_pair(self):
        command = self.parse(timeframe="10s", extra_timeframes=["1m", "5m"])
        assert command.parsed_extra_timeframes == (Timeframe.M1, Timeframe.M5)

    def test_normalises_case(self):
        command = self.parse(timeframe="10s", extra_timeframes=["1M"])
        assert command.parsed_extra_timeframes == (Timeframe.M1,)

    def test_drops_the_primary(self):
        """A main chart already on 1m must not be charged for it twice."""
        command = self.parse(timeframe="1m", extra_timeframes=["1m", "5m"])
        assert command.parsed_extra_timeframes == (Timeframe.M5,)

    def test_deduplicates(self):
        command = self.parse(timeframe="10s", extra_timeframes=["5m", "5m"])
        assert command.parsed_extra_timeframes == (Timeframe.M5,)

    def test_rejects_an_unknown_timeframe(self):
        with pytest.raises(ValidationError):
            self.parse(extra_timeframes=["3s"])

    def test_rejects_more_than_the_cap(self):
        with pytest.raises(ValidationError):
            self.parse(extra_timeframes=["1m", "5m", "15m", "1h", "1d"])


class TestOtherCommands:
    def test_parses_unsubscribe(self):
        assert parse_command({"action": "unsubscribe"}).action == "unsubscribe"

    def test_parses_ping(self):
        assert parse_command({"action": "ping"}).action == "ping"

    def test_parses_scanner_configure(self):
        command = parse_command(
            {
                "action": "scanner.configure",
                "scanner_id": "small_cap",
                "scan_code": "TOP_PERC_GAIN",
                "above_price": 2.5,
            }
        )
        assert command.scanner_id == "small_cap"
        assert command.scan_code == "TOP_PERC_GAIN"
        assert command.above_price == pytest.approx(2.5)

    def test_scanner_fields_are_optional(self):
        command = parse_command({"action": "scanner.configure", "scanner_id": "small_cap"})
        assert command.scan_code is None

    def test_scanner_id_is_required(self):
        with pytest.raises(ValidationError):
            parse_command({"action": "scanner.configure", "scan_code": "TOP_PERC_GAIN"})

    def test_rejects_a_negative_price(self):
        with pytest.raises(ValidationError):
            parse_command(
                {"action": "scanner.configure", "scanner_id": "small_cap", "above_price": -1}
            )

    def test_price_bounds_accept_the_clear_sentinel(self):
        command = parse_command(
            {
                "action": "scanner.configure",
                "scanner_id": "small_cap",
                "above_price": "clear",
                "below_price": "clear",
            }
        )
        assert command.above_price == "clear"
        assert command.below_price == "clear"

    def test_parses_scanner_stop(self):
        command = parse_command({"action": "scanner.stop", "scanner_id": "mid_cap"})
        assert command.scanner_id == "mid_cap"

    def test_scanner_stop_requires_an_id(self):
        with pytest.raises(ValidationError):
            parse_command({"action": "scanner.stop"})

    @pytest.mark.parametrize("payload", [{}, {"action": "nope"}, [], "hello", 42, None])
    def test_rejects_malformed_payloads(self, payload):
        with pytest.raises(ValidationError):
            parse_command(payload)


class TestEncodeBar:
    def test_uses_short_keys(self):
        wire = encode_bar(make_bar(60, 10.0), intraday=True)
        assert set(wire) >= {"t", "o", "h", "l", "c", "v", "n"}

    def test_tags_a_premarket_bar_as_extended(self):
        bar = make_bar(ny_epoch(2024, 3, 5, 7, 0), 10.0)
        assert encode_bar(bar, intraday=True).get("x") == 1

    def test_tags_an_after_hours_bar_as_extended(self):
        bar = make_bar(ny_epoch(2024, 3, 5, 18, 0), 10.0)
        assert encode_bar(bar, intraday=True).get("x") == 1

    def test_leaves_a_regular_hours_bar_untagged(self):
        bar = make_bar(ny_epoch(2024, 3, 5, 11, 0), 10.0)
        assert "x" not in encode_bar(bar, intraday=True)

    def test_never_tags_a_daily_bar(self):
        bar = make_bar(ny_epoch(2024, 3, 5, 7, 0), 10.0)
        assert "x" not in encode_bar(bar, intraday=False)

    def test_rounds_prices_but_keeps_volume_exact(self):
        bar = Bar(time=60, open=1.123456789, high=2, low=1, close=1.5, volume=12345.0)
        wire = encode_bar(bar, intraday=False)
        assert wire["o"] == pytest.approx(1.123457)
        assert wire["v"] == pytest.approx(12345.0)


class TestOutboundMessages:
    def test_snapshot_shape(self):
        message = snapshot_message(
            symbol="AAPL",
            timeframe=Timeframe.M1,
            bars=[make_bar(60, 10.0)],
            series={"ema9": [(60, 9.5)]},
            source=DataSource.ALPACA,
            delayed=True,
            generated_at=1234,
        )
        assert message["type"] == "snapshot"
        assert message["symbol"] == "AAPL"
        assert message["timeframe"] == "1m"
        assert message["delayed"] is True
        assert message["source"] == "alpaca"
        assert len(message["bars"]) == 1

    def test_status_reports_both_providers(self):
        message = status_message(
            source=DataSource.ALPACA,
            delayed=True,
            ibkr_connected=False,
            alpaca_available=True,
            message="IBKR unavailable",
        )
        assert message["source"] == "alpaca"
        assert message["ibkr_connected"] is False
        assert message["alpaca_available"] is True

    def test_scanner_message_shape(self):
        message = scanner_message(
            scanner_id="small_cap",
            label="Small Cap",
            rows=[{"symbol": "XYZ"}],
            config={"scan_code": "X"},
            running=True,
        )
        assert message["type"] == "scanner" and message["running"] is True
        assert message["scanner_id"] == "small_cap"
        assert message["label"] == "Small Cap"

    def test_error_message_shape(self):
        message = error_message("no_data", "nothing here")
        assert message == {"type": "error", "code": "no_data", "message": "nothing here"}
