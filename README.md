# Deriv Expert Intelligence Trading Bot (v5.3)

A high-performance, modular trading bot designed for Deriv Volatility Indices. This system combines professional-grade architecture with advanced fractal price forecasting and structural analysis to deliver precise execution and automated risk management.

## 🚀 Key Features

### 🧠 Expert Intelligence Engine (v5.3)
- **LuxAlgo Echo Forecast**: Advanced algorithmic engine that identifies historical fractal similarities and projects the most likely future price path using Pearson correlation. Validates Direction, TP, SL, and Expiry.
- **LuxAlgo Pivot SNR**: Strategy 4 implements sophisticated 15-bar pivot logic to define Support and Resistance zones from the High/Low to the midpoint of the wick.
- **Structural RR Gatekeeper**: All entries require a projected Reward/Risk ratio of ≥ 1.5 based on the forecasted structural path, filtered through an ATR-based risk floor.
- **Smart Expiry (Target Arrival)**: Dynamically calculates optimal trade duration by pinpointing the exact future candle where price is projected to reach its ATR target within the Echo window.
- **Smart & Tiered Multipliers**:
    - **Direct Tiered Mapping**: Strategy 1 (Lowest available), Strategy 2 (Middle available), Strategy 3 (Highest available). Ensuring consistent risk-to-reward profiling for each strategy tier.
    - **Volatility Scaling**: Multipliers for other strategies automatically scale based on relative volatility (ATR % of price).
    - **Liquidation Protection**: Automatically reduces multiplier values if the Stop Loss is too close to the liquidation point.

### 🏗 Modular Architecture
- **Distributed Handlers**: Optimized workload division using specialized modules:
    - `ta_handler.py`: Centralized Technical Analysis and persistent API connection.
    - `screener_handler.py`: Real-time dashboard intelligence and strategy scoring.
    - `strategy_handler.py`: High-precision entry and exit trigger logic.
    - `utils.py`: Core algorithmic engines (Echo, SuperTrend, SNR, PA).
- **Persistent Connection Manager**: Centralized WebSocket manager with a 1-minute candle cache, strictly respecting Deriv API rate limits and eliminating "Sorry, an error occurred" responses.
- **Threaded Async Execution**: concurrent monitoring of multiple symbols and positions using `ThreadPoolExecutor` and `asyncio`.

### 📊 Intelligent Dashboard
- **Real-time Metrics**: Dynamic display of Balance, PNL, Win Rate, and Avg PNL, all rounded to 1 decimal place for professional clarity.
- **Live Screener**: Advanced analytics including Four-Pillar TA Scores (Trend, Momentum, Volatility, Structure) and fractal alignment.
- **Multiplier Mode UI**: Automatically switches terminology from CALL/PUT to BUY/SELL and displays calculated TP/SL targets when Multiplier contracts are active.

---

## 📉 Trading Strategies

### 🔹 Strategy 1: Slow Breakout (Daily / 15m)
- **Concept**: Captures long-term momentum shifts.
- **Entry**: Price crosses **Daily Open** (HTF). Requires agreement from **15m TA** and **Echo Forecast**.
- **Exit**: LTF signal flip or hit targets.

### 🔹 Strategy 2: Moderate Breakout (1h / 3m)
- **Concept**: Balanced day-trading approach.
- **Entry**: Price crosses **1-Hour Open**. Requires **3m TA** alignment and **Structural RR** validation.
- **Exit**: LTF signal flip.

### 🔹 Strategy 3: Fast Breakout (15m / 1m)
- **Concept**: Scalping high-velocity moves.
- **Entry**: Price crosses **15-Minute Open**. Requires **1m TA** and **Echo Forecast** confirmation.
- **Exit**: 1m signal flip.

### 🔹 Strategy 4: LuxAlgo SNR (Rise & Fall ONLY)
- **Concept**: Pure structural reversal trading.
- **Entry**: Price enters a **5m Pivot Zone**. Requires **1m Bullish/Bearish Reversal** (TA + PA Pattern) and **Echo Forecast** confirmation.
- **Exit**: Constant **5-minute expiry** for optimal zone absorption.

### 🔹 Strategy 5: Synthetic Intelligence Screener
- **Concept**: Weighted multi-pillar decision engine. Requires **Echo Forecast** directional agreement.
- **Architecture**:
    - **Trend**: EMA 50/200, SuperTrend, ADX.
    - **Momentum**: RSI, Stoch RSI, MACD Divergence.
    - **Volatility**: ATR, Bollinger Bands.
    - **Structure**: 5m Fractals (Scalp) or 1H Order Blocks (Multiplier).
- **Thresholds**: >=72% (Rise & Fall), >=68% (Multiplier).
- **Adaptive Sensitivity**: Increases confidence thresholds (+5%) following 3+ consecutive losses on a symbol.

### 🔹 Strategy 6: Intelligence Legacy
- **Concept**: Exhaustive suite of 20+ indicators with weighted importance. Requires **Echo Forecast** directional agreement.
- **Indicator Blocks**: Trend (W3), Momentum (W2), Volatility (W1), Structure (W2).
- **Execution**: Confidence >= 60% across Core (1H), Timing (1m), and Bias (4H) alignment.

### 🔹 Strategy 7: Intelligent Multi-TF Alignment
- **Concept**: User-customizable timeframe alignment.
- **Feature**: Supports "OFF" switches for Small, Mid, or High timeframes.
- **Logic**: Enforces alignment across all active TFs with built-in signal cooling.

---

## 🛠 Risk Management

- **Daily Targets**:
    - `max_daily_loss_pct`: Automatic pause when the daily loss limit is hit.
    - `max_daily_profit_pct`: Automatic pause when the daily profit goal is reached.
- **Expert Early Exit**: Bot monitors LTF "Signal Support." If the signal flips against an open trade, it exits immediately to preserve balance.
- **Free Ride Protocol**: For Multipliers, SL is aggressively trailed at a 1.0x ATR distance once the position hits 1.5x ATR in profit.

---

## ⚙️ Setup & Deployment

1.  **Install Dependencies**: `pip install -r requirements.txt`
2.  **Run Application**: `python app.py`
3.  **Access Dashboard**: `http://localhost:3000`
4.  **Configuration**: Navigate to **Config** to set your **Deriv API Token**. Bot handles App ID 62845 by default.

---

## ⚠️ Disclaimer
Trading involves significant risk. This bot is an automation tool and does not guarantee profits. Always test strategies on a **Demo Account** before using live capital.
