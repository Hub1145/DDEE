# Deriv Expert Intelligence Trading Bot (v5.3)

A high-performance, modular trading bot designed for Deriv Volatility Indices. This system combines professional-grade architecture with advanced fractal price forecasting and structural analysis to deliver precise execution and automated risk management.

## 🚀 Key Features

### 🧠 Expert Intelligence Engine (v5.3)
- **LuxAlgo Echo Forecast**: Ported algorithmic engine that identifies historical price actions (fractals) and projects the most likely future price path using Pearson correlation.
- **LuxAlgo Pivot SNR**: Support and Resistance zones identified via LuxAlgo-style 15-bar pivots, with zones precisely defined from High/Low to the midpoint of the wick.
- **Structural RR Gatekeeper**: All entries require a projected Reward/Risk ratio of ≥ 1.5 based on the forecasted path, preventing entries near exhaustion points.
- **Smart Expiry (Target Point Arrival)**: Dynamically calculates optimal trade duration by pinpointing the exact future candle where price is projected to reach its ATR target.
- **Smart & Tiered Multipliers**:
    - **Tiered Base Levels**: Strategy 1 (50x), Strategy 2 (100x), Strategy 3 (200x).
    - **Volatility Scaling**: Multipliers automatically adjust based on relative volatility (ATR as % of price).
    - **Liquidation Protection**: Automatically scales multiplier amounts down if the Stop Loss distance is too close to the liquidation point.
    - **Symbol-Specific Matching**: Bot fetches and utilizes only the supported multiplier ranges for each specific Deriv symbol.

### 🏗 Modular Architecture
- **Distributed Workload**: Specialized handlers for Technical Analysis (`ta_handler`), Dashboard Screener (`screener_handler`), and Strategy Trigger Logic (`strategy_handler`).
- **Persistent Connection Manager**: Centralized WebSocket manager with a 1-minute candle cache, eliminating API rate limit errors and "Deriv API error: Sorry..." responses.
- **Threaded Async Execution**: Concurrent monitoring of multiple symbols and positions using `ThreadPoolExecutor` and `asyncio`.

### 📊 Intelligent Dashboard
- **Real-time Metrics**: Dynamic display of Balance, PNL, Win Rate, and Avg PNL, all rounded to a precise 1 decimal place.
- **Live Position Monitoring**: Real-time tracking of active contracts with PNL, entry spot, and expiry countdowns.
- **Dynamic Screener**: Strategy-specific technical analysis including Four-Pillar TA Scores (Trend, Momentum, Volatility, Structure) and Echo correlation.

---

## 📉 Trading Strategies

### 🔹 Strategy 1: Slow Breakout (Daily / 15m)
- **Entry**: Price crosses the **Daily Open** (HTF). Requires agreement from **15m TA** (BUY/SELL) and **Echo Forecast** confirmation.
- **Exit**: LTF signal flip, Daily Open cross-back (Multi), or +2 Daily ATR target (Multi).
- **Multiplier**: Low (50x base).

### 🔹 Strategy 2: Moderate Breakout (1h / 3m)
- **Entry**: Price crosses the **1-Hour Open**. Requires agreement from **3m TA** and **Structural RR** validation.
- **Exit**: 3m LTF signal flip or hit TP/SL.
- **Multiplier**: Medium (100x base).

### 🔹 Strategy 3: Fast Breakout (15m / 1m)
- **Entry**: Price crosses the **15-Minute Open**. Requires agreement from **1m TA** and **Echo Forecast**.
- **Exit**: 1m LTF signal flip or hit TP/SL.
- **Multiplier**: High (200x base).

### 🔹 Strategy 4: LuxAlgo SNR (Rise & Fall ONLY)
- **Entry**: Price enters a **5m Pivot Zone** (High/Low to Mid-wick). Requires **1m TA Reversal** (BUY at Support, SELL at Resistance) and **PA Pattern** validation.
- **Exit**: Constant **1-minute expiry**.
- **Management**: Removed complex exit logic to focus on pure zone-to-zone reversal execution.

### 🔹 Strategy 5: Synthetic Intelligence
- **Entry**: Triple EMA alignment (1m, 5m, 1h) + Four-Pillar TA Score > 72%.
- **Exit**: Expert early-close on signal flip or Neutral transition while in loss.
- **Expiry**: Precision Target Arrival (Smart Expiry).

### 🔹 Strategy 6: Intelligence Legacy
- **Entry**: RSI Oversold/Overbought on 1m + 15m Trend Alignment.
- **Exit**: Intelligent early-exit on signal flip.

### 🔹 Strategy 7: Intelligent Multi-TF Alignment
- **Feature**: Supports switching "OFF" specific timeframes (Small, Mid, High) to focus on custom alignment (e.g., 1-TF or 2-TF).
- **Cool-down**: Signal cooling in 1-TF mode prevents entry spamming.

---

## 🛠 Risk & Position Management

- **Expert Monitoring**: The bot actively monitors "Signal Support." If the underlying LTF TA signal flips against the trade, it is exited immediately to preserve capital.
- **Free Ride Protocol (Multipliers)**: SL is aggressively trailed at a 1.0x ATR distance once a trade reaches 1.5x ATR in profit.
- **Configurable Targets**:
    - `max_daily_loss_pct`: Pauses trading if the daily loss limit is hit.
    - `max_daily_profit_pct`: Pauses trading once the daily profit goal is achieved.
- **TP/SL Enforcement**: All positions (Rise & Fall and Multipliers) strictly respect the TP/SL values set in the dashboard config.

---

## ⚙️ Setup & Deployment

1.  **Install Dependencies**: `pip install -r requirements.txt`
2.  **Run Application**: `python app.py`
3.  **Access Dashboard**: Open `http://localhost:3000`.
4.  **Configuration**: Navigate to the **Config** tab to set your **Deriv API Token** and **App ID**.

---

## ⚠️ Disclaimer
Trading involves significant risk. This bot is an automation tool and does not guarantee profits. Always test strategies on a **Demo Account** before using live capital.
