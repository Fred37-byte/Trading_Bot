"""
cli.py — Binance Futures Testnet Trading Bot CLI

Entry point using Typer.  Supports:
  place-order   — place MARKET, LIMIT, or STOP_MARKET orders

Usage examples:
  python cli.py place-order --symbol BTCUSDT --side BUY --type MARKET --quantity 0.001
  python cli.py place-order --symbol ETHUSDT --side SELL --type LIMIT --quantity 0.1 --price 2000
  python cli.py place-order --symbol BTCUSDT --side SELL --type STOP_MARKET --quantity 0.001 --stop-price 29000
"""

from __future__ import annotations

from typing import Optional

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich import box

from bot.client import BinanceClient, BinanceAPIError, NetworkError
from bot import orders as order_service
from bot.logging_config import get_logger

# ── App setup ────────────────────────────────────────────────────────────────
# Using invoke_without_command + add_help_option so `python cli.py` shows help
# and `python cli.py place-order` invokes the subcommand.
app = typer.Typer(
    name="trading-bot",
    help="Binance Futures Testnet Trading Bot — place MARKET, LIMIT, and STOP_MARKET orders.",
    add_completion=False,
    no_args_is_help=True,
    invoke_without_command=True,
)

console = Console()
err_console = Console(stderr=True, style="bold red")
logger = get_logger(__name__)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _print_request_summary(
    symbol: str,
    side: str,
    order_type: str,
    quantity: float,
    price: Optional[float],
    stop_price: Optional[float],
) -> None:
    """Print a nicely formatted order request summary."""
    table = Table(box=box.ROUNDED, show_header=False, title="Order Request Summary")
    table.add_column("Field", style="cyan", no_wrap=True)
    table.add_column("Value", style="white")

    table.add_row("Symbol",     symbol.upper())
    table.add_row("Side",       side.upper())
    table.add_row("Type",       order_type.upper())
    table.add_row("Quantity",   str(quantity))
    if price is not None:
        table.add_row("Limit Price", str(price))
    if stop_price is not None:
        table.add_row("Stop Price", str(stop_price))

    console.print(table)


def _print_order_response(result: dict) -> None:
    """Print a formatted order response."""
    table = Table(box=box.ROUNDED, show_header=False, title="Order Response")
    table.add_column("Field", style="cyan", no_wrap=True)
    table.add_column("Value", style="white")

    table.add_row("Order ID",     str(result.get("orderId", "N/A")))
    table.add_row("Symbol",       str(result.get("symbol", "N/A")))
    table.add_row("Status",       str(result.get("status", "N/A")))
    table.add_row("Side",         str(result.get("side", "N/A")))
    table.add_row("Type",         str(result.get("type", "N/A")))
    table.add_row("Orig Qty",     str(result.get("origQty", "N/A")))
    table.add_row("Executed Qty", str(result.get("executedQty", "N/A")))
    table.add_row("Avg Price",    str(result.get("avgPrice", "0")))

    if result.get("price") and result.get("price") != "0":
        table.add_row("Limit Price", str(result.get("price")))
    if result.get("stopPrice") and result.get("stopPrice") != "0":
        table.add_row("Stop Price", str(result.get("stopPrice")))

    console.print(table)


# ── Subcommand: place-order ───────────────────────────────────────────────────

@app.command("place-order", help="Place a futures order (MARKET / LIMIT / STOP_MARKET) on Binance Testnet.")
def place_order(
    symbol: str = typer.Option(
        ...,
        "--symbol",
        help="Trading pair, e.g. BTCUSDT",
        show_default=False,
    ),
    side: str = typer.Option(
        ...,
        "--side",
        help="BUY or SELL",
        show_default=False,
    ),
    order_type: str = typer.Option(
        ...,
        "--type",
        help="MARKET, LIMIT, or STOP_MARKET",
        show_default=False,
    ),
    quantity: float = typer.Option(
        ...,
        "--quantity",
        help="Order quantity",
        show_default=False,
    ),
    price: Optional[float] = typer.Option(
        None,
        "--price",
        help="Limit price (required for LIMIT orders)",
    ),
    stop_price: Optional[float] = typer.Option(
        None,
        "--stop-price",
        help="Stop trigger price (required for STOP_MARKET orders)",
    ),
) -> None:
    """Place a futures order on Binance Testnet."""

    # ── Step 1: Validate inputs first (before touching the network) ───────
    try:
        from bot import validators
        validators.validate_order_params(
            symbol=symbol,
            side=side,
            order_type=order_type,
            quantity=quantity,
            price=price,
            stop_price=stop_price,
        )
    except ValueError as exc:
        err_console.print(f"\n❌  Validation Error: {exc}\n")
        logger.warning("Validation error (pre-flight): %s", exc)
        raise typer.Exit(code=1)

    # ── Step 2: Echo request summary ──────────────────────────────────────
    _print_request_summary(symbol, side, order_type, quantity, price, stop_price)

    # ── Step 3: Initialise client ─────────────────────────────────────────
    try:
        client = BinanceClient()
    except EnvironmentError as exc:
        err_console.print(f"\n❌  Setup Error: {exc}\n")
        logger.error("EnvironmentError: %s", exc)
        raise typer.Exit(code=1)

    # ── Step 4–5: Place order, print response ─────────────────────────────
    try:
        result = order_service.place_order(
            client=client,
            symbol=symbol,
            side=side,
            order_type=order_type,
            quantity=quantity,
            price=price,
            stop_price=stop_price,
        )
        _print_order_response(result)
        console.print(
            Panel(
                f"✅  Order [bold]{result.get('orderId')}[/bold] placed successfully!  "
                f"Status: [green]{result.get('status')}[/green]",
                style="green",
            )
        )

    except ValueError as exc:
        err_console.print(f"\n❌  Validation Error: {exc}\n")
        logger.warning("Validation error: %s", exc)
        raise typer.Exit(code=1)

    except BinanceAPIError as exc:
        err_console.print(f"\n❌  API Error: {exc}\n")
        logger.error("BinanceAPIError: %s", exc)
        raise typer.Exit(code=2)

    except NetworkError as exc:
        err_console.print(
            f"\n❌  Network Error: {exc}\n"
            "     → Check your internet connection and try again.\n"
        )
        logger.error("NetworkError: %s\n", exc)
        raise typer.Exit(code=3)

    except Exception as exc:  # noqa: BLE001
        err_console.print(f"\n❌  Unexpected Error: {exc}\n")
        logger.exception("Unexpected error: %s", exc)
        raise typer.Exit(code=99)


# ── Dummy second command to force multi-command mode in Typer ─────────────────
# Without a second command, Typer 0.12+ collapses the group into a single
# default command, which means `place-order` is treated as a positional argument
# and rejected.  This dummy command preserves proper subcommand routing.

@app.command("version", hidden=True)
def _version() -> None:
    """Print version info."""
    console.print("trading-bot v1.0.0 — Binance Futures Testnet")


# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    app()
