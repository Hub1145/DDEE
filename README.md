# Deriv Trading Bot Dashboard (Modular Architecture v5.0)

A high-performance, modular trading bot designed for Deriv Volatility Indices. This bot features a real-time web dashboard for monitoring statistics, logs, and active positions with a focus on precision execution and algorithmic market context.

## 🚀 Key Features

### 🏗 Modular Architecture
- **Refactored Engine**: Workload is distributed across specialized handlers (`screener_handler`, `strategy_handler`, `ta_handler`) ensuring efficient async processing.
- **Persistent Connection Manager**: Uses a centralized WebSocket manager for technical analysis with smart candle caching to respect API rate limits.
- **Asynchronous Execution**: Leverages Python's threading and `asyncio` to monitor multiple symbols and positions simultaneously.

### 🎯 Intelligent Dashboard
- **Amount Tab**: Comprehensive real-time statistics including Balance, PNL, Total Trades, Win Rate, and Average Trade PNL.
- **Position Tab**: Live monitoring of all open contracts with real-time PNL tracking, entry spot prices, and automated expiry countdowns.
- **Log Tab**: Real-time console output streaming system events, signal generation, and trade executions.
- **Dynamic Screener**: Real-time technical analysis for all strategies with adaptive columns based on the active strategy. Now displays recommended expiry times and TA ratings.

### ⚙️ Professional Bot Controls
- **Start/Stop**: One-click control for bot execution. The bot continues to monitor and close existing positions even when trading is paused.
- **Risk Management**: Toggle between fixed USD or percentage-based balance usage. Configure Max Daily Loss %, Max Daily Profit %, Take Profit, Stop Loss, and Force Close durations.

---

## 📊 Trading Strategies

The bot supports seven distinct trading strategies, refactored for the new modular engine.

### 🔹 Strategy 1: Slow Breakout (Daily / 15m)
*   **Timeframes**: Daily (HTF) / 15-Minute (LTF).
*   **Filter**: Strictly uses a 15-minute Technical Analysis filter.
*   **Logic**: Triggers on a crossover across the Daily Open (HTF). Entry requires agreement from the 15m TA rating (BUY/SELL).
*   **Expiry**: Defaults to the close of the Daily candle (End of Day).

### 🔹 Strategy 2: Moderate (1h / 3m)
*   **Timeframes**: 1-Hour (HTF) / 3-Minute (LTF).
*   **Filter**: Strictly uses a 3-minute Technical Analysis filter.
*   **Logic**: Triggers on a crossover across the 1-Hour Open (HTF). Entry requires agreement from the 3m TA rating.
*   **Expiry**: Defaults to the close of the current 1-Hour candle.

### 🔹 Strategy 3: Fast (15m / 1m)
*   **Timeframes**: 15-Minute (HTF) / 1-Minute (LTF).
*   **Filter**: Strictly uses a 1-minute Technical Analysis filter.
*   **Logic**: Triggers on a crossover across the 15-Minute Open (HTF). Entry requires agreement from the 1m TA rating.
*   **Expiry**: Defaults to the close of the current 15-Minute candle.

### 🔹 Strategy 4: SNR Price Action
*   **Logic**: Pure Price Action strategy based on Support, Resistance, and Flip zones.
*   **Zone Freshness**: Tracks touch counts; reduces position size after 3 touches and retires zones after 5.
*   **Hard Invalidation**: Marks zones as broken based on candle closes while allowing for tick-based execution.

### 🔹 Strategy 5: Synthetic Intelligence
*   **Architecture**: Uses a four-pillar scoring system (Trend, Momentum, Volatility, Market Structure).
*   **Execution**: Multi-TF alignment (1m, 5m, 1h) using persistent technical analysis streams.
*   **Smart Expiry**: Dynamically calculates expiry based on current market volatility (ATR-based).

### 🔹 Strategy 6: Intelligence Legacy
*   **Logic**: Grouped indicator suite refactored for dimensionality and smoothing.
*   **Filter**: Uses 1m Entry combined with 15m Trend for high-conviction scalps.

### 🔹 Strategy 7: Intelligent Multi-TF Alignment
*   **Timeframe Control**: Users can switch "OFF" specific timeframes (Small, Mid, High) to focus on specific market horizons.
*   **Logic**: Triggers when all active timeframes align.
*   **Quick Execution**: Automatically triggers "QUICK_BUY/SELL" with reduced expiry if the highest enabled timeframe shows "STRONG" conviction.

---

## 🛠 Advanced Position Management

- **One Trade Per Symbol**: The bot ensures only one active position exists per symbol.
- **Opposite Cancellation**: Receiving a new signal in the opposite direction automatically closes the existing trade before entering the new one.
- **Contract Type Support**: Integrated support for both "Multiplier" and "Rise and Fall" contracts.
- **Free Ride Protocol (Multipliers)**: Moves SL to a structural safety zone (Fractal/ATR) once profit reaches 1.5 ATR.
- **Ghost Cleanup**: Automatically purges expired contracts from internal state if API updates are missed.

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
3.  **Access Dashboard**: Open `http://localhost:3000` (or your configured PORT).
4.  **Configure API**: Click "Config" and enter your **Deriv API Token** and **App ID**.

---

## ⚠️ Important Notes

- **Demo First**: Always test strategies with a Deriv Demo account before going live.
- **Rate Limits**: The centralized `ta_handler` uses caching and throttles to respect Deriv API limits.

---

## 🛡 License & Disclaimer

This software is for educational purposes. Trading financial instruments involves significant risk of loss. The authors are not responsible for any financial losses incurred.
