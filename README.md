# Deriv Trading Bot Dashboard (Expert Intelligence v5.2)

A professional-grade, modular trading bot designed for Deriv Volatility Indices. This bot features a real-time web dashboard and a sophisticated "Expert Intelligence" engine (v5.2) that utilizes fractal price forecasting and structural analysis for high-precision execution.

## 🚀 Key Features

### 🧠 Expert Intelligence Engine (v5.2)
- **LuxAlgo Echo Forecast**: Ported algorithmic engine that identifies historical price actions (fractals) and projects the most likely future price path.
- **Structural RR Gatekeeper**: Trades are only authorized if the projected Reward/Risk ratio based on the forecasted path is ≥ 1.5. This prevents entering trades near exhaustion points.
- **Smart Expiry (Target Point Arrival)**: Dynamically calculates expiry by pinpointing the exact future candle where price is forecasted to reach its ATR target.
- **Smart Multipliers**: Automatically scales multiplier values based on relative volatility (ATR as % of price) and aligns TP/SL targets with forecasted structural peaks/troughs. Includes liquidation protection scaling based on SL distance.

### 🏗 Modular Architecture
- **Decomposed Logic**: Workload is distributed across specialized handlers (`screener_handler`, `strategy_handler`, `ta_handler`, `utils`) for true asynchronous processing.
- **Persistent Connection Manager**: Centralized WebSocket handler with a 1-minute candle cache, ensuring rate limits are respected and preventing connection errors.
- **Threaded Execution**: Uses a `ThreadPoolExecutor` to monitor multiple symbols and manage positions concurrently without blocking.

---

## 📊 Trading Strategies

The bot features seven refactored strategies, each integrated with the Expert Intelligence gatekeepers.

### 🔹 Strategy 1: Slow Breakout (Daily / 15m)
*   **Entry Rules**:
    1.  Price must cross the **Daily Open** price.
    2.  Low-Timeframe (15m) Technical Analysis must be in agreement (BUY/SELL).
    3.  **Echo Forecast** and **Structural RR** validation.
*   **Multiplier Support**: Supports Multipliers with **Low (50x)** base scaling.
*   **Management & Exit**:
    - **Rise & Fall**: Closes immediately if the 15m LTF TA signal flips.
    - **Multiplier**: Advanced management including Daily Open cross-back exit and +2 Daily ATR profit targets, plus LTF signal flip monitoring.

### 🔹 Strategy 2: Moderate Breakout (1h / 3m)
*   **Entry Rules**:
    1.  Price must cross the **1-Hour Open** price.
    2.  Low-Timeframe (3m) Technical Analysis must be in agreement.
    3.  **Echo Forecast** and **Structural RR** validation.
*   **Multiplier Support**: Supports Multipliers with **Medium (100x)** base scaling.
*   **Management & Exit**:
    - Closes immediately on a 3m LTF signal flip (e.g., BUY signal becomes SELL).

### 🔹 Strategy 3: Fast Breakout (15m / 1m)
*   **Entry Rules**:
    1.  Price must cross the **15-Minute Open** price.
    2.  Low-Timeframe (1m) Technical Analysis must be in agreement.
    3.  **Echo Forecast** and **Structural RR** validation.
*   **Multiplier Support**: Supports Multipliers with **High (200x)** base scaling for quick scalps.
*   **Management & Exit**:
    - Closes on 1m LTF signal flip.

### 🔹 Strategy 4: SNR Price Action (Rise & Fall ONLY)
*   **Entry Rules**:
    1.  **5m SNR Zones**: Price enters a zone defined from the High/Low to the midpoint of the wick of 5m candles.
    2.  **1m Reversal**: Requires agreement from the 1m Technical Analysis (BUY for Support, SELL for Resistance).
    3.  **Price Action Pattern**: Requires 1m Bullish/Bearish Pin, Engulfing, or Reversal patterns.
*   **Management & Exit**:
    - Relies on constant **1-minute expiry**.
    - Respects configuration-based TP/SL for PNL capture.
*   **Constraint**: This strategy does not support Multipliers.

### 🔹 Strategy 5: Synthetic Intelligence
*   **Architecture**: Uses a four-pillar scoring system (Trend, Momentum, Volatility, Market Structure).
*   **Execution**: Multi-TF alignment (1m, 5m, 1h) using persistent technical analysis streams.
*   **Smart Expiry**: Dynamically calculates expiry based on target point arrival logic.
*   **Exit**: Closes early if signal flips or if confidence drops to Neutral while in loss.

### 🔹 Strategy 6: Intelligence Legacy
*   **Logic**: Grouped indicator suite refactored for dimensionality and smoothing.
*   **Filter**: Uses 1m Entry combined with 15m Trend for high-conviction scalps.

### 🔹 Strategy 7: Intelligent Multi-TF Alignment
*   **Timeframe Control**: Users can switch "OFF" specific timeframes (Small, Mid, High) to focus on specific market horizons.
*   **Management**: Features a signal cool-down mechanism in 1-TF mode to prevent entry spamming.

---

## 🛠 Position & Risk Management

- **Expert Monitoring**: The bot actively monitors the "Signal Support" for every open trade. If the underlying LTF TA signal flips, the trade is exited immediately.
- **Dynamic TP/SL**:
    - All positions (Rise & Fall and Multipliers) respect the TP/SL values set in the config.
    - Captures small gains or limits losses by monitoring real-time PNL fluctuations.
- **Smart Multiplier Scaling**: Automatically adjusts multiplier values based on SL distance to ensure the liquidation point is strictly beyond the Stop Loss level.
- **Free Ride Protocol**: Once a trade reaches 1.5x ATR in profit, the SL is aggressively trailed at a 1.0x ATR distance.
- **Daily Targets**:
    - `max_daily_loss_pct`: Pauses all trading if the daily loss limit is hit.
    - `max_daily_profit_pct`: Pauses all trading once the daily profit goal is achieved.

---

## ⚙️ Setup & Deployment

1.  **Install Dependencies**: `pip install -r requirements.txt`
2.  **Run the Application**: `python app.py`
3.  **Access Dashboard**: Open `http://localhost:3000`.
4.  **Configure API**: Navigate to the **Config** tab and enter your **Deriv API Token** and **App ID**.

---

## ⚠️ Disclaimer
Trading involves significant risk. This bot is a tool for automation and does not guarantee profits. Always test strategies on a **Demo Account** before using live capital.
