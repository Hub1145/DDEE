# Deriv Trading Bot Dashboard (Expert Intelligence v5.2)

A professional-grade, modular trading bot designed for Deriv Volatility Indices. This bot features a real-time web dashboard and a sophisticated "Expert Intelligence" engine (v5.2) that utilizes fractal price forecasting and structural analysis for high-precision execution.

## 🚀 Key Features

### 🧠 Expert Intelligence Engine (v5.2)
- **LuxAlgo Echo Forecast**: Ported algorithmic engine that identifies historical price actions (fractals) and projects the most likely future price path.
- **Structural RR Gatekeeper**: Trades are only authorized if the projected Reward/Risk ratio based on the forecasted path is ≥ 1.5. This prevents entering trades near exhaustion points.
- **Smart Expiry (Target Point Arrival)**: Dynamically calculates expiry by pinpointing the exact future candle where price is forecasted to reach its ATR target.
- **Smart Multipliers**: Automatically scales multiplier values based on relative volatility (ATR as % of price) and aligns TP/SL targets with forecasted structural peaks/troughs.

### 🏗 Modular Architecture
- **Decomposed Logic**: Workload is distributed across specialized handlers (`screener_handler`, `strategy_handler`, `ta_handler`, `utils`) for true asynchronous processing.
- **Persistent Connection Manager**: Centralized WebSocket handler with a 1-minute candle cache, ensuring rate limits are respected and preventing "Deriv API error: Sorry..." messages.
- **Threaded Execution**: Uses a `ThreadPoolExecutor` to monitor multiple symbols and manage positions concurrently without blocking.

---

## 📊 Trading Strategies

The bot features seven refactored strategies, each integrated with the Expert Intelligence gatekeepers.

### 🔹 Strategy 1: Slow Breakout (Daily / 15m)
*   **Entry Rules**:
    1.  Price must cross the **Daily Open** price.
    2.  Low-Timeframe (15m) Technical Analysis must be in agreement (BUY/SELL).
    3.  **Echo Forecast** must confirm direction (Projected close > current price for BUY).
    4.  **Structural RR** must be ≥ 1.5.
*   **Management & Exit**:
    - **Hard Exit**: Closes if price crosses back across the Daily Open.
    - **Profit Target**: Automatically closes if profit reaches +2 Daily ATRs.
    - **Expert Move**: Closes early if the 15m signal flips against the trade.
*   **Expiry**: End of Day (EOD) or dynamic based on target arrival.

### 🔹 Strategy 2: Moderate Breakout (1h / 3m)
*   **Entry Rules**:
    1.  Price must cross the **1-Hour Open** price.
    2.  Low-Timeframe (3m) Technical Analysis must be in agreement.
    3.  **Echo Forecast** and **Structural RR** validation.
*   **Management & Exit**:
    - Closes immediately on a signal flip (e.g., BUY signal becomes SELL).
    - Uses ATR-based TP/SL for Multipliers.
*   **Expiry**: Remaining time until the 1-Hour candle close.

### 🔹 Strategy 3: Fast Breakout (15m / 1m)
*   **Entry Rules**:
    1.  Price must cross the **15-Minute Open** price.
    2.  Low-Timeframe (1m) Technical Analysis must be in agreement.
    3.  **Echo Forecast** and **Structural RR** validation.
*   **Management & Exit**:
    - Closes on signal flip or hit TP/SL.
*   **Expiry**: Remaining time until the 15-Minute candle close.

### 🔹 Strategy 4: SNR Price Action
*   **Entry Rules**:
    1.  Price touches a Support, Resistance, or Flip zone (HTF 5m/1h).
    2.  **Price Action Pattern**: Requires Bullish/Bearish Pin, Engulfing, or Harami.
    3.  **RSI Filter**: M5 RSI must not be Overbought/Oversold against the move.
    4.  **Trend Filter**: Price must be on the correct side of the H1 EMA50.
    5.  **Echo Reversal**: Forecast must project a reversal away from the zone.
*   **Management & Exit**:
    - Position size is reduced by 50% if the zone has been touched ≥ 3 times.
    - Zones are invalidated and removed if a candle closes through them.
*   **Expiry**: Smart Expiry (typically 5-10m) based on forecasted reversal velocity.

### 🔹 Strategy 5: Synthetic Intelligence
*   **Entry Rules**:
    1.  **Triple EMA Alignment**: 1m, 5m, and 1h EMAs must all align in direction.
    2.  **Intelligence Score**: 4-pillar score (Trend, Momentum, Volatility, Structure) must exceed 72%.
    3.  **Late Entry Penalty**: Canceled if current candle body > 30% of average ATR.
    4.  **Echo Correlation**: High correlation (> 0.6) requirement for the projected path.
*   **Management & Exit**:
    - **Expert Exit**: Closes early if signal flips to opposite OR if signal becomes Neutral while position is in loss.
*   **Expiry**: Precision Target Arrival (Smart Expiry).

### 🔹 Strategy 6: Intelligence Legacy
*   **Entry Rules**:
    1.  **RSI OS/OB**: 1m RSI must be < 30 (BUY) or > 70 (SELL).
    2.  **HTF Trend**: 15m TA must be in agreement with the RSI reversal.
    3.  **Echo Forecast** confirmation and **Structural RR** validation.
*   **Management & Exit**:
    - Standard intelligence early-exit on signal flip.
*   **Expiry**: precision Target Arrival (Smart Expiry).

### 🔹 Strategy 7: Intelligent Multi-TF Alignment
*   **Entry Rules**:
    1.  All "ON" timeframes (Small, Mid, High) must show the same signal direction.
    2.  **OFF Mode**: User can disable specific TFs to focus on single or dual timeframe alignment.
    3.  **Quick Signal**: If High-TF is "STRONG", bot executes with reduced expiry for a momentum scalp.
*   **Management & Exit**:
    - **Cool-down**: In 1-TF mode, bot will not re-enter the same signal until it cycles through Neutral or flips.
*   **Expiry**: Dynamic based on the alignment of the enabled timeframes.

---

## 🛠 Position & Risk Management

- **Expert Monitoring**: The bot actively monitors the "Signal Support" for every open trade. If the underlying strategy signal flips, the trade is exited immediately to preserve capital.
- **Free Ride Protocol (Multipliers)**: Once a trade reaches 1.5x ATR in profit, the SL is aggressively trailed at a 1.0x ATR distance, locking in gains while allowing for exponential growth.
- **Daily Targets**:
    - `max_daily_loss_pct`: Pauses all trading if the daily loss limit is hit.
    - `max_daily_profit_pct`: Pauses all trading once the daily profit goal is achieved.
- **Force Close**: Optional hard-coded duration (e.g., 60s) to exit positions regardless of PNL.

---

## ⚙️ Setup & Deployment

1.  **Install Dependencies**:
    ```bash
    pip install -r requirements.txt
    ```
2.  **Run the Application**:
    ```bash
    python app.py
    ```
3.  **Access Dashboard**: Open `http://localhost:3000`.
4.  **Configure API**: Navigate to the **Config** tab and enter your **Deriv API Token** and **App ID**.

---

## ⚠️ Disclaimer
Trading involves significant risk. This bot is a tool for automation and does not guarantee profits. Always test strategies on a **Demo Account** before using live capital.
