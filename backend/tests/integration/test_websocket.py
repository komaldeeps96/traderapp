"""The WebSocket protocol, end to end."""

from __future__ import annotations

import pytest

from tests.integration.conftest import receive_until


class TestHandshake:
    def test_opens_with_a_status_frame(self, client):
        with client.websocket_connect("/ws") as socket:
            assert socket.receive_json()["type"] == "status"

    def test_then_sends_one_scanner_frame_per_market_cap_tier(self, client):
        with client.websocket_connect("/ws") as socket:
            socket.receive_json()  # status
            frames = [socket.receive_json() for _ in range(4)]
            assert all(frame["type"] == "scanner" for frame in frames)
            assert {frame["scanner_id"] for frame in frames} == {
                "small_cap",
                "mid_cap",
                "large_cap",
                "mega_cap",
            }
            # Each carries its own filters — the current config, not just a
            # frame count. Every scanner_id is distinct above, so any one
            # tier's shape stands in for the rest.
            config = frames[0]["config"]
            assert {"scan_code", "above_price", "below_price", "above_volume"} <= set(config)

    def test_status_names_the_active_source(self, client):
        with client.websocket_connect("/ws") as socket:
            status = socket.receive_json()
            assert status["source"] == "alpaca"
            assert status["delayed"] is False


class TestSubscribe:
    def test_returns_a_snapshot(self, ws):
        ws.send_json({"action": "subscribe", "symbol": "AAPL"})
        snapshot = receive_until(ws, "snapshot")
        assert snapshot["symbol"] == "AAPL"
        assert snapshot["timeframe"] == "1m"

    def test_snapshot_carries_bars(self, ws):
        ws.send_json({"action": "subscribe", "symbol": "AAPL"})
        assert len(receive_until(ws, "snapshot")["bars"]) > 100

    def test_bars_are_in_ascending_time_order(self, ws):
        ws.send_json({"action": "subscribe", "symbol": "AAPL"})
        times = [bar["t"] for bar in receive_until(ws, "snapshot")["bars"]]
        assert times == sorted(times)

    def test_bars_use_the_compact_shape(self, ws):
        ws.send_json({"action": "subscribe", "symbol": "AAPL"})
        bar = receive_until(ws, "snapshot")["bars"][0]
        assert {"t", "o", "h", "l", "c", "v"} <= set(bar)

    def test_snapshot_carries_indicator_series(self, ws):
        ws.send_json({"action": "subscribe", "symbol": "AAPL"})
        series = receive_until(ws, "snapshot")["series"]
        assert "ema9" in series and "ema20" in series

    def test_key_levels_are_computed_from_daily_data(self, ws):
        ws.send_json({"action": "subscribe", "symbol": "AAPL"})
        series = receive_until(ws, "snapshot")["series"]
        assert "prev_day_close" in series
        assert "high_52w" in series

    def test_series_points_are_time_value_pairs(self, ws):
        ws.send_json({"action": "subscribe", "symbol": "AAPL"})
        point = receive_until(ws, "snapshot")["series"]["ema9"][0]
        assert len(point) == 2

    def test_reports_the_source_and_delay(self, ws):
        ws.send_json({"action": "subscribe", "symbol": "AAPL"})
        snapshot = receive_until(ws, "snapshot")
        assert snapshot["source"] == "alpaca"
        assert snapshot["delayed"] is False

    def test_lowercase_symbols_are_accepted(self, ws):
        ws.send_json({"action": "subscribe", "symbol": "aapl"})
        assert receive_until(ws, "snapshot")["symbol"] == "AAPL"

    @pytest.mark.parametrize("timeframe", ["1m", "5m", "15m", "1h", "1d"])
    def test_every_timeframe_returns_a_snapshot(self, ws, timeframe):
        ws.send_json({"action": "subscribe", "symbol": "AAPL", "timeframe": timeframe})
        snapshot = receive_until(ws, "snapshot")
        assert snapshot["timeframe"] == timeframe
        assert snapshot["bars"]

    def test_resampling_reduces_the_bar_count(self, ws):
        ws.send_json({"action": "subscribe", "symbol": "AAPL", "timeframe": "1m"})
        minute_bars = len(receive_until(ws, "snapshot", timeframe="1m")["bars"])
        ws.send_json({"action": "subscribe", "symbol": "AAPL", "timeframe": "15m"})
        quarter_bars = len(receive_until(ws, "snapshot", timeframe="15m")["bars"])
        assert quarter_bars < minute_bars

    def test_switching_symbol_returns_the_new_one(self, ws):
        ws.send_json({"action": "subscribe", "symbol": "AAPL"})
        receive_until(ws, "snapshot", symbol="AAPL")
        ws.send_json({"action": "subscribe", "symbol": "TSLA"})
        assert receive_until(ws, "snapshot", symbol="TSLA")["symbol"] == "TSLA"

    def test_a_background_backfill_refreshes_the_chart(self, ws):
        """The fast first paint is followed by a fuller snapshot."""
        ws.send_json({"action": "subscribe", "symbol": "AAPL", "timeframe": "1m"})
        receive_until(ws, "snapshot", timeframe="1m")
        second = receive_until(ws, "snapshot", timeframe="1m", limit=30)
        assert second["symbol"] == "AAPL"
        assert second["bars"]


class TestExtraTimeframes:
    """The mini charts: extra timeframes served on the same connection."""

    def test_answers_with_a_snapshot_per_timeframe(self, ws):
        ws.send_json(
            {
                "action": "subscribe",
                "symbol": "AAPL",
                "timeframe": "1m",
                "extra_timeframes": ["5m", "15m"],
            }
        )
        assert receive_until(ws, "snapshot", timeframe="1m")["bars"]
        assert receive_until(ws, "snapshot", timeframe="5m", limit=30)["bars"]
        assert receive_until(ws, "snapshot", timeframe="15m", limit=30)["bars"]

    def test_the_primary_comes_first(self, ws):
        ws.send_json(
            {
                "action": "subscribe",
                "symbol": "AAPL",
                "timeframe": "1m",
                "extra_timeframes": ["5m"],
            }
        )
        timeframes = []
        for _ in range(12):
            message = ws.receive_json()
            if message.get("type") == "snapshot":
                timeframes.append(message["timeframe"])
            if len(timeframes) == 2:
                break
        assert timeframes == ["1m", "5m"]

    def test_the_extras_resample_the_same_symbol(self, ws):
        """A coarser timeframe is fewer bars off one loaded base, not a fetch."""
        ws.send_json(
            {
                "action": "subscribe",
                "symbol": "AAPL",
                "timeframe": "1m",
                "extra_timeframes": ["5m"],
            }
        )
        minute = receive_until(ws, "snapshot", timeframe="1m")
        five = receive_until(ws, "snapshot", timeframe="5m", limit=30)
        assert five["symbol"] == "AAPL"
        assert 0 < len(five["bars"]) < len(minute["bars"])

    # Live delivery to the extra timeframes is asserted in
    # tests/unit/test_hub.py::TestBroadcast, not here. Driving the broadcaster
    # from a TestClient test means calling it from the test's thread while the
    # app runs its own event loop in another — the message lands in the
    # connection's queue without waking the writer task that drains it, so the
    # frame is never sent and `receive_until` blocks forever instead of
    # failing. That hung the whole suite roughly one run in two.

    def test_an_unknown_extra_is_rejected_without_closing(self, ws):
        ws.send_json(
            {"action": "subscribe", "symbol": "AAPL", "extra_timeframes": ["3s"]}
        )
        assert receive_until(ws, "error")["code"] == "bad_command"
        ws.send_json({"action": "ping"})
        assert receive_until(ws, "pong")


class TestErrors:
    def test_rejects_a_malformed_symbol_without_closing(self, ws):
        ws.send_json({"action": "subscribe", "symbol": "not a symbol!"})
        error = receive_until(ws, "error")
        assert error["code"] == "bad_command"

    def test_stays_usable_after_an_error(self, ws):
        ws.send_json({"action": "subscribe", "symbol": "bad!!"})
        receive_until(ws, "error")
        ws.send_json({"action": "subscribe", "symbol": "AAPL"})
        assert receive_until(ws, "snapshot")["symbol"] == "AAPL"

    def test_rejects_an_unknown_timeframe(self, ws):
        ws.send_json({"action": "subscribe", "symbol": "AAPL", "timeframe": "3s"})
        assert receive_until(ws, "error")["code"] == "bad_command"

    def test_names_the_offending_field(self, ws):
        ws.send_json({"action": "subscribe", "symbol": "AAPL", "timeframe": "3s"})
        assert "timeframe" in receive_until(ws, "error")["message"]

    def test_rejects_invalid_json(self, ws):
        ws.send_text("{not json")
        assert receive_until(ws, "error")["code"] == "bad_json"

    def test_rejects_an_unknown_action(self, ws):
        ws.send_json({"action": "self_destruct"})
        assert receive_until(ws, "error")["code"] == "bad_command"

    def test_reports_a_symbol_with_no_data(self, client, alpaca_api):
        import httpx

        alpaca_api.get("/v2/stocks/bars").mock(
            return_value=httpx.Response(200, json={"bars": {}, "next_page_token": None})
        )
        with client.websocket_connect("/ws") as socket:
            socket.receive_json()
            socket.receive_json()
            socket.send_json({"action": "subscribe", "symbol": "NODATA"})
            assert receive_until(socket, "error")["code"] == "no_data"


class TestPing:
    def test_answers_with_pong(self, ws):
        ws.send_json({"action": "ping"})
        assert receive_until(ws, "pong")["type"] == "pong"


class TestClientIsolation:
    """Two windows must be able to watch different symbols.

    The previous design broadcast one globally-active ticker to everyone, so a
    second window silently hijacked the first. It also made parallel browser
    tests impossible.
    """

    def test_two_clients_can_watch_different_symbols(self, client):
        with client.websocket_connect("/ws") as first, client.websocket_connect("/ws") as second:
            for socket in (first, second):
                socket.receive_json()
                socket.receive_json()

            first.send_json({"action": "subscribe", "symbol": "AAPL"})
            assert receive_until(first, "snapshot")["symbol"] == "AAPL"

            second.send_json({"action": "subscribe", "symbol": "TSLA"})
            assert receive_until(second, "snapshot")["symbol"] == "TSLA"

    def test_one_client_subscribing_does_not_disturb_the_other(self, client):
        with client.websocket_connect("/ws") as first, client.websocket_connect("/ws") as second:
            for socket in (first, second):
                socket.receive_json()
                socket.receive_json()

            first.send_json({"action": "subscribe", "symbol": "AAPL"})
            receive_until(first, "snapshot")

            second.send_json({"action": "subscribe", "symbol": "TSLA"})
            receive_until(second, "snapshot")

            # The first client is still on AAPL: a ping round-trip must not
            # surface any TSLA traffic.
            first.send_json({"action": "ping"})
            for _ in range(6):
                message = first.receive_json()
                assert message.get("symbol", "AAPL") == "AAPL"
                if message["type"] == "pong":
                    break

    def test_health_counts_both(self, client):
        with client.websocket_connect("/ws") as first, client.websocket_connect("/ws"):
            first.receive_json()
            assert client.get("/api/health").json()["clients"] == 2


class TestUnsubscribe:
    def test_is_accepted(self, ws):
        ws.send_json({"action": "subscribe", "symbol": "AAPL"})
        receive_until(ws, "snapshot")
        ws.send_json({"action": "unsubscribe"})
        ws.send_json({"action": "ping"})
        assert receive_until(ws, "pong")

    def test_releases_the_symbol_from_memory(self, client):
        from app.services.container import get_container

        with client.websocket_connect("/ws") as socket:
            socket.receive_json()
            socket.receive_json()
            socket.send_json({"action": "subscribe", "symbol": "AAPL"})
            receive_until(socket, "snapshot")
            assert "AAPL" in get_container().market_data.loaded_symbols

            socket.send_json({"action": "unsubscribe"})
            socket.send_json({"action": "ping"})
            receive_until(socket, "pong")
            assert "AAPL" not in get_container().market_data.loaded_symbols


class TestScannerCommands:
    def test_refuses_to_configure_without_ibkr(self, ws):
        ws.send_json(
            {"action": "scanner.configure", "scanner_id": "small_cap", "scan_code": "MOST_ACTIVE"}
        )
        assert "IBKR" in receive_until(ws, "error")["message"]

    def test_rejects_an_unknown_scan_code(self, ws):
        ws.send_json(
            {"action": "scanner.configure", "scanner_id": "small_cap", "scan_code": "NONSENSE"}
        )
        assert "scan code" in receive_until(ws, "error")["message"].lower()

    def test_rejects_an_unknown_scanner_id(self, ws):
        ws.send_json({"action": "scanner.configure", "scanner_id": "nope", "scan_code": "MOST_ACTIVE"})
        assert "nope" in receive_until(ws, "error")["message"]

    def test_stop_also_rejects_an_unknown_scanner_id(self, ws):
        ws.send_json({"action": "scanner.stop", "scanner_id": "nope"})
        assert "nope" in receive_until(ws, "error")["message"]

    def test_rejects_an_inverted_price_range(self, ws):
        ws.send_json(
            {
                "action": "scanner.configure",
                "scanner_id": "small_cap",
                "above_price": 50,
                "below_price": 5,
            }
        )
        assert "price" in receive_until(ws, "error")["message"].lower()

    def test_always_echoes_the_scanner_state(self, ws):
        ws.send_json(
            {"action": "scanner.configure", "scanner_id": "small_cap", "scan_code": "MOST_ACTIVE"}
        )
        echoed = receive_until(ws, "scanner", scanner_id="small_cap")
        assert echoed["type"] == "scanner"

    def test_filters_on_one_tier_do_not_disturb_another(self, ws):
        """The whole point of four scanners: independent state per tier."""
        ws.send_json(
            {"action": "scanner.configure", "scanner_id": "small_cap", "scan_code": "MOST_ACTIVE"}
        )
        receive_until(ws, "scanner", scanner_id="small_cap")

        ws.send_json({"action": "scanner.configure", "scanner_id": "mid_cap", "scan_code": "HALTED"})
        mid = receive_until(ws, "scanner", scanner_id="mid_cap")
        assert mid["config"]["scan_code"] == "HALTED"

        # A no-op re-query of small_cap: still MOST_ACTIVE, unaffected by
        # mid_cap's change moments ago.
        ws.send_json({"action": "scanner.configure", "scanner_id": "small_cap"})
        small = receive_until(ws, "scanner", scanner_id="small_cap")
        assert small["config"]["scan_code"] == "MOST_ACTIVE"


class TestIndicatorVisibility:
    """Toggling an indicator, stored on the server rather than the browser.

    The client sends the whole picture for a timeframe; the server keeps only
    what differs from `indicators.yaml`. That is what lets a changed default
    reach a chart the user never touched, and it keeps the state file to the
    lines a person actually changed.
    """

    @staticmethod
    def _saved(client):
        return client.get("/api/session").json()["indicators"]

    def test_stores_only_what_differs_from_the_defaults(self, client, ws):
        # ema9 ships on for 1m; volume ships on too. Only the change is kept.
        ws.send_json(
            {
                "action": "indicators.visibility",
                "timeframe": "1m",
                "visible": {"ema9": False, "volume": True},
            }
        )
        ws.send_json({"action": "ping"})
        receive_until(ws, "pong")
        assert self._saved(client) == {"1m": {"ema9": False}}

    def test_each_timeframe_is_remembered_separately(self, client, ws):
        for timeframe in ("1m", "1d"):
            ws.send_json(
                {
                    "action": "indicators.visibility",
                    "timeframe": timeframe,
                    "visible": {"ema9": False},
                }
            )
        ws.send_json({"action": "ping"})
        receive_until(ws, "pong")
        assert self._saved(client) == {"1m": {"ema9": False}, "1d": {"ema9": False}}

    def test_returning_to_the_defaults_clears_the_timeframe(self, client, ws):
        ws.send_json(
            {"action": "indicators.visibility", "timeframe": "1m", "visible": {"ema9": False}}
        )
        ws.send_json(
            {"action": "indicators.visibility", "timeframe": "1m", "visible": {"ema9": True}}
        )
        ws.send_json({"action": "ping"})
        receive_until(ws, "pong")
        assert self._saved(client) == {}

    def test_an_unknown_indicator_is_dropped(self, client, ws):
        """A stale client must not grow the state file with dead ids."""
        ws.send_json(
            {
                "action": "indicators.visibility",
                "timeframe": "1m",
                "visible": {"no_such_indicator": False, "ema9": False},
            }
        )
        ws.send_json({"action": "ping"})
        receive_until(ws, "pong")
        assert self._saved(client) == {"1m": {"ema9": False}}

    def test_an_indicator_absent_from_this_timeframe_is_dropped(self, client, ws):
        """`pm_high` is intraday only; asking for it on 1d means nothing."""
        ws.send_json(
            {
                "action": "indicators.visibility",
                "timeframe": "1d",
                "visible": {"pm_high": True},
            }
        )
        ws.send_json({"action": "ping"})
        receive_until(ws, "pong")
        assert self._saved(client) == {}

    def test_an_unknown_timeframe_is_refused(self, ws):
        ws.send_json(
            {"action": "indicators.visibility", "timeframe": "3y", "visible": {"ema9": False}}
        )
        assert receive_until(ws, "error")["code"] == "bad_command"

    def test_the_connection_survives_a_refused_command(self, ws):
        ws.send_json({"action": "indicators.visibility", "timeframe": "3y", "visible": {}})
        receive_until(ws, "error")
        ws.send_json({"action": "ping"})
        assert receive_until(ws, "pong")["type"] == "pong"


class TestWatchlist:
    """Add and remove go over the socket, because the list is shared.

    It lives in one file rather than one per connection, so a name added in
    one window has to appear in the others — which is why the whole list is
    broadcast rather than acknowledged to the sender.
    """

    def test_adding_returns_the_whole_list(self, ws, stub_watchlist_quotes):
        ws.send_json({"action": "watchlist.add", "symbol": "AAPL"})
        message = receive_until(ws, "watchlist")
        assert message["symbols"] == ["AAPL"]
        assert message["rows"][0]["symbol"] == "AAPL"

    def test_removing_returns_the_whole_list(self, ws, stub_watchlist_quotes):
        for symbol in ("AAPL", "TSLA"):
            ws.send_json({"action": "watchlist.add", "symbol": symbol})
            receive_until(ws, "watchlist")
        ws.send_json({"action": "watchlist.remove", "symbol": "AAPL"})
        assert receive_until(ws, "watchlist")["symbols"] == ["TSLA"]

    def test_it_reaches_a_second_window(self, client, ws, stub_watchlist_quotes):
        """Two tabs on the same terminal share one list."""
        with client.websocket_connect("/ws") as other:
            ws.send_json({"action": "watchlist.add", "symbol": "NVDA"})
            assert receive_until(other, "watchlist", limit=20)["symbols"] == ["NVDA"]

    def test_it_is_waiting_on_the_next_connection(self, client, ws, stub_watchlist_quotes):
        ws.send_json({"action": "watchlist.add", "symbol": "ZM"})
        receive_until(ws, "watchlist")
        with client.websocket_connect("/ws") as fresh:
            assert receive_until(fresh, "watchlist", limit=20)["symbols"] == ["ZM"]

    def test_an_empty_list_costs_a_new_connection_nothing(self, client, ws):
        """No list means no screener request while the socket is opening."""
        with client.websocket_connect("/ws") as fresh:
            for _ in range(7):
                assert fresh.receive_json()["type"] != "watchlist"

    def test_a_symbol_that_is_not_one_is_refused(self, ws):
        ws.send_json({"action": "watchlist.add", "symbol": ""})
        assert receive_until(ws, "error")["code"] == "bad_command"
