"""
bot/validators.py

Pure validation functions — no I/O, no side effects.
All functions raise ValueError with human-readable messages on failure.

Supported order types:
  MARKET     — requires quantity, no price
  LIMIT      — requires quantity + price, optional timeInForce (default GTC)
  STOP_MARKET — requires quantity + stop_price (bonus feature)
"""

from __future__ import annotations

VALID_SIDES = {"BUY", "SELL"}
VALID_ORDER_TYPES = {"MARKET", "LIMIT", "STOP_MARKET"}


# ── Symbol ───────────────────────────────────────────────────────────────────

def validate_symbol(symbol: str) -> str:
    """Return normalized symbol or raise ValueError."""
    if not symbol or not isinstance(symbol, str):
        raise ValueError("Symbol must be a non-empty string (e.g. BTCUSDT).")
    normalized = symbol.strip().upper()
    if not normalized.isalnum():
        raise ValueError(
            f"Symbol '{symbol}' contains invalid characters. "
            "Use alphanumeric characters only (e.g. BTCUSDT)."
        )
    return normalized


# ── Side ─────────────────────────────────────────────────────────────────────

def validate_side(side: str) -> str:
    """Return 'BUY' or 'SELL', or raise ValueError."""
    if not side or not isinstance(side, str):
        raise ValueError("Side must be 'BUY' or 'SELL'.")
    normalized = side.strip().upper()
    if normalized not in VALID_SIDES:
        raise ValueError(
            f"Invalid side '{side}'. Must be one of: {', '.join(sorted(VALID_SIDES))}."
        )
    return normalized


# ── Order type ───────────────────────────────────────────────────────────────

def validate_order_type(order_type: str) -> str:
    """Return normalized order type or raise ValueError."""
    if not order_type or not isinstance(order_type, str):
        raise ValueError(
            f"Order type must be one of: {', '.join(sorted(VALID_ORDER_TYPES))}."
        )
    normalized = order_type.strip().upper()
    if normalized not in VALID_ORDER_TYPES:
        raise ValueError(
            f"Invalid order type '{order_type}'. "
            f"Must be one of: {', '.join(sorted(VALID_ORDER_TYPES))}."
        )
    return normalized


# ── Quantity ─────────────────────────────────────────────────────────────────

def validate_quantity(quantity: float) -> float:
    """Return validated quantity or raise ValueError."""
    try:
        qty = float(quantity)
    except (TypeError, ValueError):
        raise ValueError(f"Quantity must be a positive number, got: '{quantity}'.")
    if qty <= 0:
        raise ValueError(f"Quantity must be positive, got: {qty}.")
    # Reasonable upper bound — prevents obviously wrong inputs
    if qty > 1_000_000:
        raise ValueError(f"Quantity {qty} seems unreasonably large. Please double-check.")
    return qty


# ── Price ────────────────────────────────────────────────────────────────────

def validate_price(price: float | None, order_type: str) -> float | None:
    """
    Validate the limit price relative to order_type.

    - LIMIT:       price is required and must be positive
    - MARKET:      price must be None
    - STOP_MARKET: price must be None (stop_price is used instead)
    """
    if order_type == "LIMIT":
        if price is None:
            raise ValueError("Price is required for LIMIT orders.")
        try:
            p = float(price)
        except (TypeError, ValueError):
            raise ValueError(f"Price must be a positive number, got: '{price}'.")
        if p <= 0:
            raise ValueError(f"Price must be positive, got: {p}.")
        return p
    else:
        if price is not None:
            raise ValueError(
                f"Price must not be set for {order_type} orders "
                "(use --stop-price for STOP_MARKET)."
            )
        return None


# ── Stop price (bonus: STOP_MARKET) ─────────────────────────────────────────

def validate_stop_price(stop_price: float | None, order_type: str) -> float | None:
    """
    Validate the stop price for STOP_MARKET orders.

    - STOP_MARKET: stop_price is required and must be positive
    - Everything else: stop_price must be None
    """
    if order_type == "STOP_MARKET":
        if stop_price is None:
            raise ValueError("--stop-price is required for STOP_MARKET orders.")
        try:
            sp = float(stop_price)
        except (TypeError, ValueError):
            raise ValueError(f"Stop price must be a positive number, got: '{stop_price}'.")
        if sp <= 0:
            raise ValueError(f"Stop price must be positive, got: {sp}.")
        return sp
    else:
        if stop_price is not None:
            raise ValueError(
                f"--stop-price should only be set for STOP_MARKET orders, "
                f"not for {order_type}."
            )
        return None


# ── Composite validator ───────────────────────────────────────────────────────

def validate_order_params(
    symbol: str,
    side: str,
    order_type: str,
    quantity: float,
    price: float | None = None,
    stop_price: float | None = None,
) -> dict:
    """
    Run all validations and return a dict of normalized, validated parameters.
    Raises ValueError (with a human-readable message) on the first failure.
    """
    normalized_symbol     = validate_symbol(symbol)
    normalized_side       = validate_side(side)
    normalized_order_type = validate_order_type(order_type)
    validated_quantity    = validate_quantity(quantity)
    validated_price       = validate_price(price, normalized_order_type)
    validated_stop_price  = validate_stop_price(stop_price, normalized_order_type)

    return {
        "symbol":     normalized_symbol,
        "side":       normalized_side,
        "order_type": normalized_order_type,
        "quantity":   validated_quantity,
        "price":      validated_price,
        "stop_price": validated_stop_price,
    }


# ── Quick self-test (python -m bot.validators) ────────────────────────────────

if __name__ == "__main__":
    import sys

    tests = [
        # (args, kwargs, expect_error)
        (("btcusdt", "buy",  "market", 0.001), {},                          False),
        (("ETHUSDT", "SELL", "LIMIT",  1.0),   {"price": 2000.0},           False),
        (("BTCUSDT", "BUY",  "STOP_MARKET", 0.001), {"stop_price": 29000}, False),
        (("",       "BUY",  "MARKET", 0.001), {},                          True),   # bad symbol
        (("BTC",    "BUY",  "MARKET", -1.0),  {},                          True),   # neg qty
        (("BTC",    "BUY",  "LIMIT",  0.001), {},                          True),   # missing price
        (("BTC",    "BUY",  "MARKET", 0.001), {"price": 30000},            True),   # price on market
        (("BTC",    "BUY",  "STOP_MARKET", 0.001), {},                     True),   # missing stop price
    ]

    passed = failed = 0
    for args, kwargs, expect_error in tests:
        try:
            result = validate_order_params(*args, **kwargs)
            if expect_error:
                print(f"FAIL  — expected ValueError for {args} {kwargs}, got: {result}")
                failed += 1
            else:
                print(f"PASS  — {result}")
                passed += 1
        except ValueError as exc:
            if expect_error:
                print(f"PASS  — expected error: {exc}")
                passed += 1
            else:
                print(f"FAIL  — unexpected ValueError: {exc}")
                failed += 1

    print(f"\n{passed} passed, {failed} failed.")
    sys.exit(0 if failed == 0 else 1)
