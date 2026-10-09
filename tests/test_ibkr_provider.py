import os
import unittest
from unittest.mock import patch

from ibapi.contract import Contract

import ibkr_provider
import server


class IBKRProviderTests(unittest.TestCase):
    def test_fundamental_parser_extracts_supported_ratios_and_skips_missing_values(self):
        xml = """
        <ReportSnapshot><Ratios>
          <Ratio FieldName="PEEXCLXOR">14.5</Ratio>
          <Ratio FieldName="PRICE2BK">2.1</Ratio>
          <Ratio FieldName="MKTCAP">1200</Ratio>
          <Ratio FieldName="TTMGMGN">-9999</Ratio>
          <Ratio FieldName="UNKNOWN">90</Ratio>
        </Ratios></ReportSnapshot>
        """
        self.assertEqual(
            ibkr_provider.parse_fundamental_snapshot(xml),
            {"P/E": 14.5, "Price/book": 2.1, "Market capitalization": 1200.0},
        )

    def test_fundamental_parser_rejects_malformed_xml(self):
        with self.assertRaisesRegex(ValueError, "malformed"):
            ibkr_provider.parse_fundamental_snapshot("<ReportSnapshot>")

    def test_quotes_prefer_last_then_close_then_midpoint(self):
        self.assertEqual(
            ibkr_provider.IBKRDataProvider._quote_price({"Last": 12.0, "Close": 10.0}),
            (12.0, "Last"),
        )
        self.assertEqual(
            ibkr_provider.IBKRDataProvider._quote_price({"Delayed close": 10.0}),
            (10.0, "Delayed close"),
        )
        self.assertEqual(
            ibkr_provider.IBKRDataProvider._quote_price({"Bid": 9.0, "Ask": 11.0}),
            (10.0, "Bid/ask midpoint"),
        )

    def test_format_positions_calculates_stock_value_and_labels_delayed_quote(self):
        session = ibkr_provider._IBKRSession()
        contract = Contract()
        contract.symbol = "ACME"
        contract.localSymbol = "ACME"
        contract.secType = "STK"
        contract.exchange = "SMART"
        contract.currency = "USD"
        position = {
            "symbol": "ACME",
            "localSymbol": "ACME",
            "securityType": "STK",
            "exchange": "SMART",
            "currency": "USD",
            "quantity": 2.0,
            "averageCost": 40.0,
            "contract": contract,
        }
        session.positions.append(position)
        session.quote_requests[1] = {
            "position": position,
            "Delayed last": 50.0,
            "marketDataType": 3,
        }
        session.fundamental_symbols[1001] = position
        session.fundamental_values[1001] = {"P/E": 15.0}

        [formatted] = ibkr_provider.IBKRDataProvider()._format_positions(session)

        self.assertEqual(formatted["marketValue"], 100.0)
        self.assertEqual(formatted["unrealizedPnl"], 20.0)
        self.assertEqual(formatted["quoteType"], "Delayed last")
        self.assertEqual(formatted["marketDataType"], "Delayed")
        self.assertEqual(formatted["fundamentals"], {"P/E": 15.0})
        self.assertNotIn("account", formatted)
        self.assertTrue(formatted["retrievedAt"])

    def test_provider_rejects_non_loopback_gateway_hosts(self):
        with patch.dict(os.environ, {"PORTFOLIO_RADAR_IBKR_HOST": "192.0.2.10"}, clear=True):
            with self.assertRaisesRegex(ibkr_provider.IBKRConnectionError, "this computer"):
                ibkr_provider.IBKRDataProvider()

    def test_failed_local_connection_returns_setup_guidance(self):
        with patch.dict(
            os.environ,
            {
                "PORTFOLIO_RADAR_IBKR_HOST": "127.0.0.1",
                "PORTFOLIO_RADAR_IBKR_PORT": "1",
            },
            clear=True,
        ):
            with self.assertRaisesRegex(ibkr_provider.IBKRConnectionError, "Could not connect to IBKR"):
                ibkr_provider.IBKRDataProvider(timeout_seconds=0.1).get_positions()

    def test_openai_position_analysis_sends_selected_fields_only(self):
        class FakeResponse:
            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return None

            def read(self):
                import json

                return json.dumps(
                    {
                        "output_text": json.dumps(
                            {
                                "facts": [],
                                "assumptions": [],
                                "interpretation": "Snapshot only.",
                                "risks": [],
                                "openQuestions": [],
                            }
                        )
                    }
                ).encode()

        position = {
            "symbol": "ACME",
            "securityType": "STK",
            "exchange": "SMART",
            "currency": "USD",
            "quantity": 2.0,
            "averageCost": 40.0,
            "marketPrice": 50.0,
            "marketValue": 100.0,
            "unrealizedPnl": 20.0,
            "quoteType": "Last",
            "marketDataType": "Real-time",
            "fundamentals": {},
            "retrievedAt": "2026-10-09T11:00:00+00:00",
            "account": "must-not-be-sent",
        }
        with (
            patch.dict(os.environ, {"OPENAI_API_KEY": "test-api-key"}, clear=True),
            patch("server.urlopen", return_value=FakeResponse()) as openai_request,
        ):
            server.ResearchAgent().run_position(position)

        import json

        request = openai_request.call_args.args[0]
        data = json.loads(request.data)
        supplied = json.loads(data["input"])
        self.assertEqual(request.get_header("Authorization"), "Bearer test-api-key")
        self.assertNotIn("must-not-be-sent", json.dumps(supplied))
        self.assertEqual(supplied["ticker"], "ACME")
