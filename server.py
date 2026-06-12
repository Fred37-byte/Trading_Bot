"""
server.py — FastAPI backend for the Binance Futures Testnet Trading Bot

Endpoints:
  GET  /              → serve the frontend (frontend/index.html)
  GET  /api/health    → credential + connectivity check
  POST /api/order     → place a MARKET / LIMIT / STOP_MARKET order
  GET  /api/logs      → return the last N lines from trading_bot.log

Run with:
  python server.py
  # or
  uvicorn server:app --reload --port 8000
"""

from __future__ import annotations

import os
import traceback
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from bot.client import BinanceClient, BinanceAPIError, NetworkError
from bot import orders as order_service
from bot import validators
from bot.logging_config import get_logger

logger = get_logger(__name__)

# ── App ───────────────────────────────────────────────────────────────────────
app = FastAPI(
    title="Binance Futures Testnet Bot",
    description="REST API wrapper around the trading bot modules",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Serve frontend static files
FRONTEND_DIR = Path(__file__).parent / "frontend"
if FRONTEND_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(FRONTEND_DIR)), name="static")

LOG_FILE = Path(__file__).parent / "logs" / "trading_bot.log"


# ── Schemas ───────────────────────────────────────────────────────────────────

class OrderRequest(BaseModel):
    symbol:     str           = Field(...,  example="BTCUSDT")
    side:       str           = Field(...,  example="BUY")
    order_type: str           = Field(...,  alias="type", example="MARKET")
    quantity:   float         = Field(...,  example=0.001)
    price:      Optional[float] = Field(None, example=None)
    stop_price: Optional[float] = Field(None, alias="stopPrice", example=None)

    model_config = {"populate_by_name": True}


class OrderResponse(BaseModel):
    success:    bool
    order:      Optional[dict] = None
    error:      Optional[str]  = None
    error_code: Optional[int]  = None


# ── Routes ────────────────────────────────────────────────────────────────────

@app.get("/", include_in_schema=False)
async def serve_frontend():
    """Serve the trading dashboard frontend."""
    index = FRONTEND_DIR / "index.html"
    if index.exists():
        return FileResponse(str(index))
    return JSONResponse({"message": "Frontend not found. Place index.html in frontend/"}, status_code=404)


@app.get("/api/health")
async def health_check():
    """
    Check if API credentials are configured.
    Returns 200 with status='ok' if credentials present, 'missing' otherwise.
    Does NOT make a live API call.
    """
    api_key    = os.environ.get("BINANCE_API_KEY", "").strip()
    api_secret = os.environ.get("BINANCE_API_SECRET", "").strip()

    if api_key and api_secret:
        return {
            "status": "ok",
            "message": "Credentials loaded",
            "key_preview": f"{api_key[:6]}...{api_key[-4:]}",
            "target": "https://testnet.binancefuture.com",
        }
    return JSONResponse(
        status_code=200,
        content={
            "status": "missing",
            "message": "No API credentials. Copy .env.example → .env and fill in your keys.",
        },
    )


# Simple in-memory mock state for local testing (balances, prices)
MOCK_STATE = {
    "balances": {"USDT": 1000000.0},
    "prices": {"BTCUSDT": 60000.0, "ETHUSDT": 3500.0},
    "next_order_id": 1000000,
}


@app.get("/api/balance")
async def get_balance(asset: str = "USDT", mock: Optional[str] = None):
    """Return available futures margin balance for the given asset (default USDT).

    `mock` behaviours:
      - absent: call real BinanceClient
      - numeric string: force-return that numeric value
      - '1' or 'state': return server-side mock state (useful for interactive testing)
    Example: `/api/balance?mock=1000000` or `/api/balance?mock=1`
    """

    # If mock is provided as '1' or 'state', return the server-side mock state.
    if mock in ("1", "state"):
        bal = MOCK_STATE["balances"].get(asset, 0.0)
        return {"success": True, "asset": asset, "available": bal}

    # Otherwise, if mock is a numeric string, return that forced value.
    if mock is not None:
        try:
            val = float(mock)
            logger.info("Returning forced mocked balance for %s = %s", asset, val)
            return {"success": True, "asset": asset, "available": val}
        except ValueError:
            pass

    try:
        client = BinanceClient()
    except EnvironmentError as exc:
        logger.error("Credentials missing for balance endpoint: %s", exc)
        return JSONResponse(status_code=200, content={"success": False, "error": str(exc)})

    try:
        bal = client.get_available_balance(asset)
        return {"success": True, "asset": asset, "available": bal}
    except BinanceAPIError as exc:
        logger.error("Balance API error: %s", exc)
        return JSONResponse(
            status_code=200,
            content={"success": False, "error": str(exc.args[0]), "error_code": exc.error_code},
        )
    except NetworkError as exc:
        logger.error("Network error fetching balance: %s", exc)
        return JSONResponse(status_code=200, content={"success": False, "error": str(exc)})


@app.post("/api/order", response_model=OrderResponse)
async def place_order(req: OrderRequest, mock: Optional[str] = None):
    """
    Validate inputs and place a futures order on Binance Testnet.

    Body example:
    ```json
    {
      "symbol": "BTCUSDT",
      "side":   "BUY",
      "type":   "MARKET",
      "quantity": 0.001
    }
    ```
    """
    logger.info(
        "API /order request: %s %s %s qty=%s price=%s stop=%s mock=%s",
        req.symbol, req.side, req.order_type, req.quantity, req.price, req.stop_price, mock,
    )

    # ── 1. Validate ───────────────────────────────────────────────────────
    try:
        validators.validate_order_params(
            symbol=req.symbol,
            side=req.side,
            order_type=req.order_type,
            quantity=req.quantity,
            price=req.price,
            stop_price=req.stop_price,
        )
    except ValueError as exc:
        logger.warning("Validation error: %s", exc)
        return OrderResponse(success=False, error=str(exc))

    # ── 2. Init client / Mock handling ────────────────────────────────────
    if mock in ("1", "state"):
        import random

        symbol = req.symbol.upper()
        price = MOCK_STATE["prices"].get(symbol)
        if price is None:
            return OrderResponse(success=False, error=f"Mock price unavailable for {symbol}")

        qty = req.quantity
        side = req.side.upper()

        if req.order_type != "MARKET":
            return OrderResponse(success=False, error="Mock mode currently only supports MARKET orders.")

        required_cost = qty * price
        if side == "BUY":
            if MOCK_STATE["balances"].get("USDT", 0.0) < required_cost:
                return OrderResponse(success=False, error=f"Not enough USDT in mock balance. Required {required_cost:.2f}.")
            MOCK_STATE["balances"]["USDT"] -= required_cost
            price = price * (1 + random.uniform(0.001, 0.005))
        else:
            MOCK_STATE["balances"]["USDT"] += required_cost
            price = price * (1 - random.uniform(0.001, 0.005))

        MOCK_STATE["prices"][symbol] = price
        MOCK_STATE["next_order_id"] += 1
        order = {
            "orderId": MOCK_STATE["next_order_id"],
            "symbol": symbol,
            "status": "FILLED",
            "side": side,
            "type": "MARKET",
            "origQty": str(qty),
            "executedQty": str(qty),
            "avgPrice": f"{price:.8f}",
            "price": str(price),
            "stopPrice": None,
        }
        logger.info("Mock order executed: %s", order)
        return OrderResponse(success=True, order=order)

    try:
        client = BinanceClient()
    except EnvironmentError as exc:
        logger.error("Credentials missing: %s", exc)
        return OrderResponse(success=False, error=str(exc))

    # ── 3. Place order ────────────────────────────────────────────────────
    try:
        result = order_service.place_order(
            client=client,
            symbol=req.symbol,
            side=req.side,
            order_type=req.order_type,
            quantity=req.quantity,
            price=req.price,
            stop_price=req.stop_price,
        )
        return OrderResponse(success=True, order=result)

    except BinanceAPIError as exc:
        logger.error("BinanceAPIError: %s", exc)
        return OrderResponse(
            success=False,
            error=str(exc.args[0]),
            error_code=exc.error_code,
        )
    except NetworkError as exc:
        logger.error("NetworkError: %s", exc)
        return OrderResponse(success=False, error=str(exc))
    except Exception as exc:
        logger.exception("Unexpected error: %s", exc)
        return OrderResponse(success=False, error=f"Unexpected error: {exc}")


@app.get("/api/price")
async def get_price(symbol: str = "BTCUSDT", mock: Optional[str] = None):
    """Return current symbol price. In mock mode (`mock=1` or `mock=state`) the
    server maintains an in-memory price that performs a tiny random walk on each call.
    """
    import random

    s = symbol.upper()
    if mock in ("1", "state"):
        # apply tiny random walk
        price = MOCK_STATE["prices"].get(s, 0.0)
        price = price * (1 + random.uniform(-0.001, 0.001))
        MOCK_STATE["prices"][s] = price
        return {"success": True, "symbol": s, "price": price}

    # non-mock: attempt to call client
    try:
        client = BinanceClient()
    except EnvironmentError as exc:
        logger.error("Credentials missing for price endpoint: %s", exc)
        return JSONResponse(status_code=200, content={"success": False, "error": str(exc)})

    try:
        p = client.get_symbol_price(s)
        return {"success": True, "symbol": s, "price": p}
    except Exception as exc:
        logger.error("Failed to fetch symbol price: %s", exc)
        return JSONResponse(status_code=200, content={"success": False, "error": str(exc)})


@app.get("/api/logs")
async def get_logs(n: int = Query(default=50, ge=1, le=500)):
    """Return the last N lines from the trading bot log file."""
    if not LOG_FILE.exists():
        return {"lines": [], "message": "Log file not found yet."}

    try:
        with LOG_FILE.open("r", encoding="utf-8") as f:
            all_lines = f.readlines()
        last_lines = [l.rstrip() for l in all_lines[-n:] if l.strip()]
        return {"lines": last_lines, "total": len(all_lines)}
    except Exception as exc:
        logger.error("Failed to read log file: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc))


# ── Dev entry point ───────────────────────────────────────────────────────────

if __name__ == "__main__":
    import uvicorn
    print("\n🚀  Trading Bot Server starting at http://localhost:8000\n")
    uvicorn.run("server:app", host="0.0.0.0", port=8000, reload=True)
