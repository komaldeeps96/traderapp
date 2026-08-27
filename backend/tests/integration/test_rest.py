"""REST endpoints against a running application."""

from __future__ import annotations


class TestHealth:
    def test_reports_ok(self, client):
        assert client.get("/api/health").json()["status"] == "ok"

    def test_reports_alpaca_as_the_active_source(self, client):
        body = client.get("/api/health").json()
        assert body["source"] == "alpaca"
        assert body["alpaca_available"] is True

    def test_reports_ibkr_as_absent(self, client):
        body = client.get("/api/health").json()
        assert body["ibkr_connected"] is False

    def test_explains_the_fallback(self, client):
        """A user with no TWS should be told why, not left guessing."""
        assert "IBKR" in (client.get("/api/health").json()["message"] or "")

    def test_counts_connected_clients(self, client):
        assert client.get("/api/health").json()["clients"] == 0


class TestIndicators:
    def test_returns_the_configured_set(self, client):
        assert len(client.get("/api/indicators").json()) >= 25

    def test_each_entry_has_what_the_chart_needs(self, client):
        first = client.get("/api/indicators").json()[0]
        assert {"id", "type", "label", "color", "color_dark", "pane", "timeframes"} <= set(first)

    def test_exposes_key_levels(self, client):
        ids = {entry["id"] for entry in client.get("/api/indicators").json()}
        assert {"pm_high", "pm_low", "prev_day_close", "high_52w"} <= ids

    def test_panes_are_declared(self, client):
        panes = {entry["pane"] for entry in client.get("/api/indicators").json()}
        # No macd: the shipped config dropped it, though the engine still
        # knows how to build one if the YAML ever brings it back.
        assert panes == {"price", "volume"}


class TestTimeframes:
    def test_lists_every_timeframe(self, client):
        values = [entry["value"] for entry in client.get("/api/timeframes").json()]
        assert values == ["10s", "1m", "5m", "15m", "30m", "1h", "4h", "1d", "1w"]

    def test_marks_which_are_intraday(self, client):
        entries = {e["value"]: e["intraday"] for e in client.get("/api/timeframes").json()}
        assert entries["10s"] is True and entries["1m"] is True and entries["1d"] is False


class TestSession:
    def test_returns_defaults_before_anything_is_viewed(self, client):
        body = client.get("/api/session").json()
        assert body["symbol"] == "AAPL"
        assert body["timeframe"] == "10s"

    def test_remembers_the_last_chart(self, client):
        with client.websocket_connect("/ws") as socket:
            socket.receive_json()
            socket.receive_json()
            socket.send_json({"action": "subscribe", "symbol": "TSLA", "timeframe": "5m"})
            for _ in range(6):
                if socket.receive_json().get("type") == "snapshot":
                    break

        body = client.get("/api/session").json()
        assert body["symbol"] == "TSLA"
        assert body["timeframe"] == "5m"


class TestScannerTiers:
    def test_lists_the_scan_codes(self, client):
        codes = {entry["code"] for entry in client.get("/api/scanner/tiers").json()["scan_codes"]}
        assert "TOP_PERC_GAIN" in codes

    def test_lists_the_four_market_cap_tiers(self, client):
        tiers = client.get("/api/scanner/tiers").json()["tiers"]
        assert {t["id"] for t in tiers} == {"small_cap", "mid_cap", "large_cap", "mega_cap"}
        assert all("label" in t for t in tiers)

    def test_the_note_explains_ibkr_is_required(self, client):
        body = client.get("/api/scanner/tiers").json()
        assert "IBKR" in body["note"]


class TestCors:
    def test_allows_the_dev_frontend(self, client):
        response = client.get("/api/health", headers={"Origin": "http://localhost:3000"})
        assert response.headers.get("access-control-allow-origin") == "http://localhost:3000"
