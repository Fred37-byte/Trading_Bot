"""
bot/client.py

BinanceClient — HTTP wrapper for the Binance Futures Testnet API.

Features:
  - HMAC-SHA256 request signing using Binance server time (avoids clock skew)
  - Structured logging (DEBUG for requests/responses, never logs secrets)
  - Custom exception hierarchy: BinanceAPIError, NetworkError
  - Supports MARKET, LIMIT, and STOP_MARKET order types
"""

from __future__ import annotations

import hashlib
import hmac
import os
import time
from typing import Optional
from urllib.parse import urlencode

import requests
from dotenv import load_dotenv

from bot.logging_config import get_logger

logger = get_logger(__name__)

# Load .env from the project root (two levels up from this file)
_ENV_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), ".env")
load_dotenv(_ENV_PATH)

BASE_URL = "https://testnet.binancefuture.com"
ORDER_ENDPOINT = "/fapi/v1/order"
BALANCE_ENDPOINT = "/fapi/v2/balance"
TICKER_PRICE_ENDPOINT = "/fapi/v1/ticker/price"
SERVER_TIME_ENDPOINT = "/fapi/v1/time"
REQUEST_TIMEOUT = 10  # seconds

# Binance rejects requests where timestamp is outside this window (ms)
RECV_WINDOW = 5000


# ── Exceptions ───────────────────────────────────────────────────────────────

class BinanceAPIError(Exception):
    """Raised when the Binance API returns a non-2xx status or error payload."""

    def __init__(self, message: str, status_code: int, error_code: Optional[int] = None):
        super().__init__(message)
        self.status_code = status_code
        self.error_code = error_code

    def __str__(self) -> str:
        code_info = f" (code: {self.error_code})" if self.error_code is not None else ""
        return f"BinanceAPIError {self.status_code}{code_info}: {self.args[0]}"


class NetworkError(Exception):
    """Raised on connection failures, timeouts, etc."""


# ── Client ───────────────────────────────────────────────────────────────────

class BinanceClient:
    """
    Thin wrapper around the Binance Futures Testnet REST API.

    Reads credentials from environment variables:
      BINANCE_API_KEY
      BINANCE_API_SECRET
    """

    def __init__(self) -> None:
        api_key = os.environ.get("BINANCE_API_KEY", "").strip()
        api_secret = os.environ.get("BINANCE_API_SECRET", "").strip()

        if not api_key or not api_secret:
            raise EnvironmentError(
                "API credentials are missing.\n"
                "  1. Copy .env.example to .env\n"
                "  2. Fill in BINANCE_API_KEY and BINANCE_API_SECRET\n"
                "  Testnet credentials: https://testnet.binancefuture.com"
            )

        self._api_key = api_key
        self._api_secret = api_secret

        self._session = requests.Session()
        self._session.headers.update({"X-MBX-APIKEY": self._api_key})

        # Compute and cache the clock offset between local time and Binance
        # server time. This is the fix for "Signature for this request is not
        # valid" — if the local clock is even a few seconds off from the
        # Binance server clock, the timestamp in the signed payload falls
        # outside the 5000ms recvWindow and Binance rejects it.
        self._time_offset_ms = self._sync_server_time()
        logger.debug(
            "BinanceClient initialised | testnet: %s | time offset: %+dms",
            BASE_URL,
            self._time_offset_ms,
        )

    # ── Private helpers ───────────────────────────────────────────────────

    def _sync_server_time(self) -> int:
        """
        Fetch Binance server time and return offset (server_ms - local_ms).
        Falls back to 0 (use local time) if the request fails.
        """
        try:
            resp = self._session.get(
                BASE_URL + SERVER_TIME_ENDPOINT,
                timeout=REQUEST_TIMEOUT,
            )
            server_ms = resp.json()["serverTime"]
            local_ms = int(time.time() * 1000)
            offset = server_ms - local_ms
            logger.debug("Server time sync: offset=%+dms", offset)
            return offset
        except Exception as exc:
            logger.warning("Could not sync server time (%s) — using local clock", exc)
            return 0

    def _get_timestamp(self) -> int:
        """Return current timestamp adjusted for server clock skew."""
        return int(time.time() * 1000) + self._time_offset_ms

    def _sign(self, params: dict) -> str:
        """
        Build a signed query string from params.

        Returns the complete query string (including timestamp and signature)
        as a string — NOT a dict — so the exact bytes that are signed are
        also the exact bytes sent to Binance. Passing a dict to requests would
        let requests re-encode it independently, risking a mismatch.
        """
        params["timestamp"] = self._get_timestamp()
        params["recvWindow"] = RECV_WINDOW
        query_string = urlencode(params)
        signature = hmac.new(
            self._api_secret.encode("utf-8"),
            query_string.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()
        return f"{query_string}&signature={signature}"

    def _send_signed_request(self, method: str, endpoint: str, params: dict | None = None) -> dict:
        """Send a signed request to a Binance private endpoint."""
        if params is None:
            params = {}
        signed_query_string = self._sign(params)
        url = BASE_URL + endpoint
        try:
            if method.upper() == "GET":
                response = self._session.get(
                    f"{url}?{signed_query_string}",
                    timeout=REQUEST_TIMEOUT,
                )
            else:
                response = self._session.request(
                    method.upper(),
                    url,
                    data=signed_query_string,
                    headers={"Content-Type": "application/x-www-form-urlencoded"},
                    timeout=REQUEST_TIMEOUT,
                )
        except requests.exceptions.Timeout:
            raise NetworkError(
                f"Request timed out after {REQUEST_TIMEOUT}s. "
                "Check your network or try again later."
            )
        except requests.exceptions.ConnectionError as exc:
            raise NetworkError(
                f"Connection failed: {exc}. "
                "Ensure you have internet access and the testnet is reachable."
            )

        return self._handle_response(response)

    def _sanitise_for_log(self, params: dict) -> dict:
        """Return a copy of params with sensitive fields removed."""
        return {
            k: v
            for k, v in params.items()
            if k not in ("signature", "timestamp", "recvWindow")
        }

    def _handle_response(self, response: requests.Response) -> dict:
        """
        Parse the API response.
        Raises BinanceAPIError on non-2xx or Binance error payload.
        """
        logger.debug(
            "Response %d | body: %s",
            response.status_code,
            response.text[:1000],
        )

        if not response.ok:
            try:
                error_body = response.json()
                error_code = error_body.get("code")
                error_msg = error_body.get("msg", response.text)
            except ValueError:
                error_code = None
                error_msg = response.text

            logger.error(
                "API Error %s: %s | status=%d",
                error_code,
                error_msg,
                response.status_code,
            )
            raise BinanceAPIError(error_msg, response.status_code, error_code)

        return response.json()

    def get_available_balance(self, asset: str = "USDT") -> float:
        """Return the available futures margin balance for the requested asset."""
        balances = self._send_signed_request("GET", BALANCE_ENDPOINT)
        for item in balances:
            if item.get("asset") == asset:
                return float(item.get("availableBalance", 0.0))
        raise BinanceAPIError(
            f"Balance information for asset '{asset}' not found.",
            status_code=500,
        )

    def get_symbol_price(self, symbol: str) -> float:
        """Return the latest market price for the symbol."""
        try:
            response = self._session.get(
                BASE_URL + TICKER_PRICE_ENDPOINT,
                params={"symbol": symbol},
                timeout=REQUEST_TIMEOUT,
            )
            data = self._handle_response(response)
            return float(data.get("price", 0.0))
        except (TypeError, ValueError) as exc:
            raise NetworkError(
                f"Failed to parse ticker price for {symbol}: {exc}"
            )

    # ── Public API ────────────────────────────────────────────────────────

    def place_order(
        self,
        symbol: str,
        side: str,
        order_type: str,
        quantity: float,
        price: Optional[float] = None,
        stop_price: Optional[float] = None,
    ) -> dict:
        """
        Place an order on Binance Futures Testnet.

        Args:
            symbol:     Trading pair, e.g. 'BTCUSDT'
            side:       'BUY' or 'SELL'
            order_type: 'MARKET', 'LIMIT', or 'STOP_MARKET'
            quantity:   Order size
            price:      Limit price (LIMIT orders only)
            stop_price: Stop trigger price (STOP_MARKET orders only)

        Returns:
            Raw API response dict.

        Raises:
            BinanceAPIError: On API-level errors.
            NetworkError:    On connection/timeout failures.
        """
        params: dict = {
            "symbol":   symbol,
            "side":     side,
            "type":     order_type,
            "quantity": quantity,
        }

        if order_type == "LIMIT":
            params["price"] = price
            params["timeInForce"] = "GTC"

        if order_type == "STOP_MARKET":
            params["stopPrice"] = stop_price

        logger.debug(
            "POST %s | params: %s",
            ORDER_ENDPOINT,
            self._sanitise_for_log(params),
        )

        # _sign returns a pre-built query string, not a dict.
        # We post it as the raw request body with the correct Content-Type
        # so the exact signed bytes are what Binance receives.
        signed_query_string = self._sign(params)
        url = BASE_URL + ORDER_ENDPOINT

        try:
            response = self._session.post(
                url,
                data=signed_query_string,
                headers={"Content-Type": "application/x-www-form-urlencoded"},
                timeout=REQUEST_TIMEOUT,
            )
        except requests.exceptions.Timeout:
            raise NetworkError(
                f"Request timed out after {REQUEST_TIMEOUT}s. "
                "Check your network or try again later."
            )
        except requests.exceptions.ConnectionError as exc:
            raise NetworkError(
                f"Connection failed: {exc}. "
                "Ensure you have internet access and the testnet is reachable."
            )

        return self._handle_response(response)
