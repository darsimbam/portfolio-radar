"""Read-only Interactive Brokers TWS API data access."""

from __future__ import annotations

import os
import threading
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from typing import Any

from ibapi.client import EClient
from ibapi.contract import Contract
from ibapi.wrapper import EWrapper


FUNDAMENTAL_LABELS = {
    "MKTCAP": "Market capitalization",
    "PEEXCLXOR": "P/E",
    "PRICE2BK": "Price/book",
    "TTMPR2REV": "Price/sales",
    "TTMROEPCT": "Return on equity (%)",
    "TTMGMGN": "Gross margin (%)",
    "YIELD": "Dividend yield (%)",
}
LAST_TICK_TYPES = {4: "Last", 68: "Delayed last"}
CLOSE_TICK_TYPES = {9: "Close", 75: "Delayed close"}
BID_TICK_TYPES = {1: "Bid", 66: "Delayed bid"}
ASK_TICK_TYPES = {2: "Ask", 67: "Delayed ask"}


class IBKRConnectionError(RuntimeError):
    """Actionable local IBKR connection or request failure."""


def parse_fundamental_snapshot(xml_data: str) -> dict[str, float]:
    """Extract a small, explicit set of reported snapshot ratios from IBKR XML."""
    try:
        root = ET.fromstring(xml_data)
    except ET.ParseError as error:
        raise ValueError("IBKR returned malformed fundamental data.") from error

    values: dict[str, float] = {}
    for element in root.iter():
        field_name = element.attrib.get("FieldName", "").upper()
        label = FUNDAMENTAL_LABELS.get(field_name)
        if label is None or not element.text:
            continue
        try:
            value = float(element.text.strip())
        except ValueError:
            continue
        if value == -9999 or value != value:
            continue
        values[label] = value
    return values


class _IBKRSession(EWrapper, EClient):
    def __init__(self) -> None:
        EWrapper.__init__(self)
        EClient.__init__(self, self)
        self.ready = threading.Event()
        self.positions_done = threading.Event()
        self.quotes_changed = threading.Condition()
        self.fundamentals_changed = threading.Condition()
        self.positions: list[dict[str, Any]] = []
        self.quote_requests: dict[int, dict[str, Any]] = {}
        self.fundamental_symbols: dict[int, dict[str, Any]] = {}
        self.fundamental_values: dict[int, dict[str, float]] = {}
        self.fundamental_errors: dict[int, str] = {}
        self.fundamental_done: set[int] = set()
        self.fatal_error: str | None = None

    def nextValidId(self, orderId: int) -> None:
        self.ready.set()

    def position(self, account: str, contract: Contract, position: float, avgCost: float) -> None:
        if not position:
            return
        self.positions.append(
            {
                "symbol": contract.symbol,
                "localSymbol": contract.localSymbol,
                "securityType": contract.secType,
                "exchange": contract.exchange,
                "currency": contract.currency,
                "quantity": float(position),
                "averageCost": float(avgCost),
                "contract": contract,
            }
        )

    def positionEnd(self) -> None:
        self.positions_done.set()

    def marketDataType(self, reqId: int, marketDataType: int) -> None:
        quote = self.quote_requests.get(reqId)
        if quote is not None:
            quote["marketDataType"] = marketDataType

    def tickPrice(self, reqId: int, tickType: int, price: float, attrib: Any) -> None:
        quote = self.quote_requests.get(reqId)
        if quote is None or price <= 0:
            return
        tick_name = (
            LAST_TICK_TYPES.get(tickType)
            or CLOSE_TICK_TYPES.get(tickType)
            or BID_TICK_TYPES.get(tickType)
            or ASK_TICK_TYPES.get(tickType)
        )
        if tick_name:
            quote[tick_name] = float(price)

    def tickSnapshotEnd(self, reqId: int) -> None:
        with self.quotes_changed:
            quote = self.quote_requests.get(reqId)
            if quote is not None:
                quote["complete"] = True
            self.quotes_changed.notify_all()

    def fundamentalData(self, reqId: int, data: str) -> None:
        try:
            metrics = parse_fundamental_snapshot(data)
        except ValueError as error:
            self._finish_fundamental(reqId, {}, str(error))
        else:
            self._finish_fundamental(reqId, metrics)

    def error(self, reqId: int, errorCode: int, errorString: str) -> None:
        if errorCode in {502, 504, 1100, 1300}:
            self.fatal_error = errorString
            self.ready.set()
            self.positions_done.set()
        if reqId in self.fundamental_symbols:
            self._finish_fundamental(reqId, {}, errorString)
        if reqId in self.quote_requests:
            self.quote_requests[reqId]["error"] = errorString
            with self.quotes_changed:
                self.quotes_changed.notify_all()

    def _finish_fundamental(
        self,
        req_id: int,
        metrics: dict[str, float],
        error: str | None = None,
    ) -> None:
        with self.fundamentals_changed:
            self.fundamental_values[req_id] = metrics
            if error:
                self.fundamental_errors[req_id] = error
            self.fundamental_done.add(req_id)
            self.fundamentals_changed.notify_all()


class IBKRDataProvider:
    """Fetch account positions, snapshot quotes and available stock ratios from local TWS/IB Gateway."""

    def __init__(self, timeout_seconds: float = 10) -> None:
        self.host = os.getenv("PORTFOLIO_RADAR_IBKR_HOST", "127.0.0.1").strip()
        try:
            self.port = int(os.getenv("PORTFOLIO_RADAR_IBKR_PORT", "7497"))
            self.client_id = int(os.getenv("PORTFOLIO_RADAR_IBKR_CLIENT_ID", "42"))
        except ValueError as error:
            raise IBKRConnectionError(
                "IBKR port and client ID settings must be whole numbers."
            ) from error
        if self.host not in {"127.0.0.1", "localhost", "::1"}:
            raise IBKRConnectionError(
                "For safety, Portfolio Radar only connects to an IBKR gateway on this computer."
            )
        if not 1 <= self.port <= 65535 or self.client_id < 0:
            raise IBKRConnectionError("IBKR port or client ID is outside its valid range.")
        self.timeout_seconds = timeout_seconds

    def get_positions(self) -> list[dict[str, Any]]:
        session = _IBKRSession()
        thread: threading.Thread | None = None
        positions_requested = False
        try:
            session.connect(self.host, self.port, self.client_id)
            thread = threading.Thread(target=session.run, name="portfolio-radar-ibkr", daemon=True)
            thread.start()
            if not session.ready.wait(self.timeout_seconds):
                raise IBKRConnectionError(self._connection_help())
            if session.fatal_error:
                raise IBKRConnectionError(
                    f"IBKR connection failed: {session.fatal_error} {self._connection_help()}"
                )

            session.reqPositions()
            positions_requested = True
            if not session.positions_done.wait(self.timeout_seconds):
                raise IBKRConnectionError(
                    "IBKR did not finish sending positions before timeout. Check TWS/IB Gateway API settings."
                )
            if session.fatal_error:
                raise IBKRConnectionError(
                    f"IBKR connection failed: {session.fatal_error} {self._connection_help()}"
                )

            stock_positions = [
                position for position in session.positions if position["securityType"] == "STK"
            ]
            self._request_quotes(session, stock_positions)
            self._request_fundamentals(session, stock_positions[:20])
            return self._format_positions(session)
        except OSError as error:
            raise IBKRConnectionError(self._connection_help()) from error
        finally:
            if session.isConnected():
                if positions_requested:
                    session.cancelPositions()
                session.disconnect()
            if thread and thread.is_alive():
                thread.join(timeout=1)

    def _request_quotes(self, session: _IBKRSession, positions: list[dict[str, Any]]) -> None:
        for req_id, position in enumerate(positions, start=1):
            session.quote_requests[req_id] = {"position": position, "complete": False}
            session.reqMktData(req_id, position["contract"], "", True, False, [])
        if positions:
            deadline = datetime.now().timestamp() + min(self.timeout_seconds, 5)
            with session.quotes_changed:
                while not all(
                    quote["complete"] or quote.get("error")
                    for quote in session.quote_requests.values()
                ):
                    remaining = deadline - datetime.now().timestamp()
                    if remaining <= 0:
                        break
                    session.quotes_changed.wait(remaining)

    def _request_fundamentals(self, session: _IBKRSession, positions: list[dict[str, Any]]) -> None:
        for req_id, position in enumerate(positions, start=1001):
            session.fundamental_symbols[req_id] = position
            session.reqFundamentalData(req_id, position["contract"], "ReportSnapshot", [])
        if positions:
            deadline = datetime.now().timestamp() + min(self.timeout_seconds, 5)
            with session.fundamentals_changed:
                while len(session.fundamental_done) < len(positions):
                    remaining = deadline - datetime.now().timestamp()
                    if remaining <= 0:
                        break
                    session.fundamentals_changed.wait(remaining)

    def _format_positions(self, session: _IBKRSession) -> list[dict[str, Any]]:
        retrieved_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
        fundamentals_by_position = {
            id(position): session.fundamental_values.get(req_id, {})
            for req_id, position in session.fundamental_symbols.items()
        }
        fundamental_errors_by_position = {
            id(session.fundamental_symbols[req_id]): error
            for req_id, error in session.fundamental_errors.items()
        }

        formatted = []
        for position in session.positions:
            quote = next(
                (
                    item
                    for item in session.quote_requests.values()
                    if item["position"] is position
                ),
                {},
            )
            quote_price, quote_label = self._quote_price(quote)
            is_stock = position["securityType"] == "STK"
            market_value = (
                round(position["quantity"] * quote_price, 2)
                if is_stock and quote_price is not None
                else None
            )
            unrealized_pnl = (
                round(position["quantity"] * (quote_price - position["averageCost"]), 2)
                if is_stock and quote_price is not None
                else None
            )
            data_type = quote.get("marketDataType")
            formatted.append(
                {
                    key: value
                    for key, value in {
                        "symbol": position["symbol"],
                        "localSymbol": position["localSymbol"],
                        "securityType": position["securityType"],
                        "exchange": position["exchange"],
                        "currency": position["currency"],
                        "quantity": position["quantity"],
                        "averageCost": position["averageCost"],
                        "marketPrice": quote_price if is_stock else None,
                        "marketValue": market_value,
                        "unrealizedPnl": unrealized_pnl,
                        "quoteType": quote_label if is_stock else None,
                        "marketDataType": self._market_data_label(data_type),
                        "quoteError": quote.get("error"),
                        "fundamentals": fundamentals_by_position.get(id(position), {}),
                        "fundamentalsError": fundamental_errors_by_position.get(id(position)),
                        "fundamentalsStatus": (
                            "Not requested (20-stock safety limit)"
                            if is_stock and id(position) not in fundamentals_by_position
                            else "Received" if fundamentals_by_position.get(id(position)) else "Unavailable"
                        ),
                        "retrievedAt": retrieved_at,
                    }.items()
                }
            )
        return formatted

    @staticmethod
    def _quote_price(quote: dict[str, Any]) -> tuple[float | None, str | None]:
        for tick_name in ("Last", "Delayed last", "Close", "Delayed close"):
            if tick_name in quote:
                return quote[tick_name], tick_name
        bid = quote.get("Bid") or quote.get("Delayed bid")
        ask = quote.get("Ask") or quote.get("Delayed ask")
        if bid is not None and ask is not None:
            return round((bid + ask) / 2, 4), "Bid/ask midpoint"
        return None, None

    @staticmethod
    def _market_data_label(data_type: int | None) -> str:
        return {
            1: "Real-time",
            2: "Frozen",
            3: "Delayed",
            4: "Delayed frozen",
        }.get(data_type, "Unavailable")

    @staticmethod
    def _connection_help() -> str:
        return (
            "Could not connect to IBKR on this computer. Start Trader Workstation or IB Gateway, "
            "enable socket clients for localhost, enable read-only API access, and check its API port."
        )
