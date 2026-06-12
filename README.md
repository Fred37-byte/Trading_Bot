# Binance Futures Testnet Trading Bot

A modular Python CLI application that places **Market**, **Limit**, and **Stop-Market** orders on the [Binance Futures Testnet](https://testnet.binancefuture.com) (USDT-M).

---

## Project Structure

```
trading_bot/
├── bot/
│   ├── __init__.py
│   ├── client.py           # Binance HTTP client (HMAC signing, error handling)
│   ├── orders.py           # Order orchestration layer
│   ├── validators.py       # Pure input validation (no I/O)
│   └── logging_config.py   # Rotating file + console logging
├── cli.py                  # CLI entry point (Typer + Rich)
├── logs/
│   └── trading_bot.log     # Auto-created; rotates at 5 MB × 3 backups
├── .env                    # Your credentials (gitignored — never commit)
├── .env.example            # Template
├── requirements.txt
└── implementation.md       # Architecture & design notes
```

---

## Setup

### 1. Clone and enter the project

```bash
git clone <repo-url>
cd trading-bot-internship-2026
```

### 2. Create a virtual environment and install dependencies

```bash
python -m venv venv
# Windows
venv\Scripts\activate
# macOS/Linux
source venv/bin/activate

pip install -r requirements.txt
```

### 3. Get Testnet API credentials

1. Go to [https://testnet.binancefuture.com](https://testnet.binancefuture.com)
2. Log in (GitHub auth works)
3. Navigate to **API Management** → generate an API key + secret

### 4. Configure credentials

```bash
cp .env.example .env
# Edit .env and fill in your keys:
# BINANCE_API_KEY=your_key_here
# BINANCE_API_SECRET=your_secret_here
```

---

## Usage

### Place a Market Order

```bash
python cli.py place-order \
  --symbol BTCUSDT \
  --side BUY \
  --type MARKET \
  --quantity 0.001
```

### Place a Limit Order

```bash
python cli.py place-order \
  --symbol ETHUSDT \
  --side SELL \
  --type LIMIT \
  --quantity 0.1 \
  --price 2000
```

### Place a Stop-Market Order (Bonus)

```bash
python cli.py place-order \
  --symbol BTCUSDT \
  --side SELL \
  --type STOP_MARKET \
  --quantity 0.001 \
  --stop-price 29000
```

### Get help

```bash
python cli.py --help
python cli.py place-order --help
```

---

## CLI Options

| Option | Type | Required | Description |
|---|---|---|---|
| `--symbol` | TEXT | ✅ | Trading pair (e.g. `BTCUSDT`) |
| `--side` | TEXT | ✅ | `BUY` or `SELL` |
| `--type` | TEXT | ✅ | `MARKET`, `LIMIT`, or `STOP_MARKET` |
| `--quantity` | FLOAT | ✅ | Order size |
| `--price` | FLOAT | For LIMIT | Limit price |
| `--stop-price` | FLOAT | For STOP_MARKET | Stop trigger price |

---

## Error Handling

The CLI never prints raw Python tracebacks. Error types and exit codes:

| Exit Code | Cause |
|---|---|
| `0` | Success |
| `1` | Validation or environment error |
| `2` | Binance API error (e.g. invalid symbol `-1121`) |
| `3` | Network / timeout error |
| `99` | Unexpected error |

---

## Logging

All activity is written to `logs/trading_bot.log`:

```
2025-07-01 10:23:01 | DEBUG    | bot.client | POST /fapi/v1/order | params: {symbol: BTCUSDT, side: BUY, type: MARKET, quantity: 0.001}
2025-07-01 10:23:01 | DEBUG    | bot.client | Response 200 | body: {orderId: 123456, status: FILLED, ...}
2025-07-01 10:23:01 | INFO     | bot.orders | Order placed: BTCUSDT BUY MARKET qty=0.001 → orderId=123456 status=FILLED
```

- **API key and secret are never logged**
- Log file rotates at **5 MB**, keeps **3 backups**
- Console only shows `WARNING` and above (keeps CLI output clean)

---

## Architecture

```
User (CLI args)
     │
     ▼
cli.py  ──► validators.py  (raises ValueError on bad input)
     │
     ▼
orders.py
     │
     ▼
client.py  ──► HMAC sign  ──► POST /fapi/v1/order  ──► Binance Testnet
     │                                                        │
     │◄───────────────── JSON response ──────────────────────┘
     │
     ▼
cli.py  (pretty-print result to stdout)
     │
     ▼
logs/trading_bot.log  (full request + response details)
```

---

## Running the Validator Self-Test

```bash
python -m bot.validators
```

Expected output: all tests pass.

---

## Security Notes

- `.env` is in `.gitignore` — **never commit credentials**
- `signature` and `timestamp` are stripped before any log entries
- All request signing uses HMAC-SHA256 per Binance specification
