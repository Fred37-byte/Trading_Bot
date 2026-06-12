"""
bot/orders.py

Thin orchestration layer between the CLI and the API client.

Responsibilities:
  1. Validate all inputs via validators.py
  2. Delegate to BinanceClient.place_order(...)
  3. Extract a clean, normalised result dict from the raw API response
  4. Log order summary and result at INFO level
"""

from __future__ import annotations

from typing import Optional

from bot.client import BinanceClient
from bot.logging_config import get_logger
from bot import validators
from bot.client import NetworkError

logger = get_logger(__name__)


def place_order(
    client: BinanceClient,
    symbol: str,
    side: str,
    order_type: str,
    quantity: float,
    price: Optional[float] = None,
    stop_price: Optional[float] = None,
) -> dict:
    """
    Validate inputs, place the order, and return a clean result dict.

    Args:
        client:     Initialised BinanceClient instance.
        symbol:     Trading pair (e.g. 'BTCUSDT').
        side:       'BUY' or 'SELL'.
        order_type: 'MARKET', 'LIMIT', or 'STOP_MARKET'.
        quantity:   Order size.
        price:      Limit price — required for LIMIT, None otherwise.
        stop_price: Stop trigger price — required for STOP_MARKET, None otherwise.

    Returns:
        dict with keys: orderId, symbol, status, side, type,
                        origQty, executedQty, avgPrice, price.

    Raises:
        ValueError:       On invalid inputs.
        BinanceAPIError:  On API-level errors (propagated from client).
        NetworkError:     On network failures (propagated from client).
    """
    # ── 1. Validate ────────────────────────────────────────────────────────
    validated = validators.validate_order_params(
        symbol=symbol,
        side=side,
        order_type=order_type,
        quantity=quantity,
        price=price,
        stop_price=stop_price,
    )

    logger.info(
        "Placing order: %s %s %s qty=%s price=%s stop_price=%s",
        validated["symbol"],
        validated["side"],
        validated["order_type"],
        validated["quantity"],
        validated["price"],
        validated["stop_price"],
    )

    # ── 2. Safety check: available margin first ────────────────────────────
    try:
        available_balance = client.get_available_balance("USDT")
        logger.debug("Available USDT balance: %s", available_balance)
    except BinanceAPIError as exc:
        logger.warning("Could not retrieve balance for pre-order check: %s", exc)
        available_balance = None

    if available_balance is not None and validated["order_type"] == "MARKET":
        try:
            latest_price = client.get_symbol_price(validated["symbol"])
            required_cost = validated["quantity"] * latest_price
            if required_cost > available_balance:
                raise ValueError(
                    f"Not enough USDT balance for this MARKET order. "
                    f"Estimated required: {required_cost:.2f} USDT, "
                    f"available: {available_balance:.2f} USDT."
                )
        except NetworkError as exc:
            logger.warning("Could not fetch symbol price for pre-order check: %s", exc)

    # ── 2. Delegate to client ──────────────────────────────────────────────
    raw_response = client.place_order(
        symbol=validated["symbol"],
        side=validated["side"],
        order_type=validated["order_type"],
        quantity=validated["quantity"],
        price=validated["price"],
        stop_price=validated["stop_price"],
    )

    # ── 3. Extract clean result ────────────────────────────────────────────
    result = {
        "orderId":     raw_response.get("orderId"),
        "symbol":      raw_response.get("symbol"),
        "status":      raw_response.get("status"),
        "side":        raw_response.get("side"),
        "type":        raw_response.get("type"),
        "origQty":     raw_response.get("origQty"),
        "executedQty": raw_response.get("executedQty"),
        "avgPrice":    raw_response.get("avgPrice", "0"),
        "price":       raw_response.get("price"),
        "stopPrice":   raw_response.get("stopPrice"),
    }

    # ── 4. Log result ─────────────────────────────────────────────────────
    logger.info(
        "Order placed: %s %s %s qty=%s → orderId=%s status=%s executedQty=%s avgPrice=%s",
        result["symbol"],
        result["side"],
        result["type"],
        result["origQty"],
        result["orderId"],
        result["status"],
        result["executedQty"],
        result["avgPrice"],
    )

    return result
