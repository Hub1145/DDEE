# Multi-Account Binance Futures "Grid & Scaled" Trading Bot

A professional, high-frequency trading bot for Binance Futures that executes a continuous Grid/Scaled Order strategy (Ping-Pong). It supports multiple API accounts simultaneously and features a real-time web dashboard.

## 🚀 Key Features

### 🎯 Core Strategy: Ping-Pong Grid
- **Directional Modes**: Supports both **LONG** and **SHORT** strategies.
- **Limit Orders Only**: Executes all entries and exits via Limit Orders to minimize fees and slippage.
- **Continuous Loop**: When a Take Profit (Sell/Buy) order fills, the bot immediately places a re-entry order at the previous step's price, continuously scalping volatility.
- **Fractional Exits**: Divides total quantity into uniform "steps" with configurable price deviation (e.g., 0.6% increments).

### ⚙️ Multi-Account & Risk Management
- **Simultaneous Accounts**: Manage up to 3 different API keys in parallel within a single instance.
- **Real-Time Monitoring**: Uses Binance WebSockets (User Data Stream) for instant reaction to order fills.
- **Automated Setup**: Automatically configures Leverage (e.g., 20x) and Margin Type (Cross/Isolated) on startup.
- **Precision Handling**: Fetches `tickSize` and `stepSize` from Binance to ensure all orders are formatted correctly.
- **Balance Safety**: Validates account balance before placing re-entry orders.

### 📊 Professional Dashboard
- **Grouped Configuration**: Separate menus for API settings and Strategy parameters for better usability.
- **Live Position Tracking**: Monitor open positions, entry prices, and unrealized PNL across all accounts.
- **Real-Time Console**: Integrated log viewer for system events and order updates.
- **Responsive Design**: Optimized for Desktop, Tablet, and Mobile viewports with a Binance-inspired dark theme.

---

## 🛠 Setup & Installation

1.  **Install Python 3.x**
2.  **Install Dependencies**:
    ```bash
    pip install -r requirements.txt
    ```
3.  **Run the Application**:
    ```bash
    python3 app.py
    ```
4.  **Access Dashboard**: Open `http://localhost:3000` in your browser.

### ⚠️ Troubleshooting `ImportError: cannot import name 'Client' from 'binance'`
If you encounter this error, it means you have a conflicting `binance` package installed. To fix it:
1.  **Uninstall conflicting packages**:
    ```bash
    pip uninstall binance binance-python
    ```
2.  **Install the correct package**:
    ```bash
    pip install python-binance
    ```

---

## ⚙️ Configuration Guide

### API Configuration
- Enter your **API Key** and **API Secret** for each account.
- Use the **Enabled** toggle to activate specific accounts.
- Use the **Test Connection** button to verify your API keys before starting.
- Toggle **Demo / Testnet Mode** to switch between Live and Testnet environments.

### Strategy Configuration
- **Symbol**: The trading pair (e.g., `LINKUSDC`, `BTCUSDT`).
- **Direction**: `LONG` or `SHORT`.
- **Total Qty**: The full position size to be distributed.
- **Total Fractions**: Number of grid steps (e.g., 8).
- **Deviation (%)**: Price difference between grid levels (e.g., 0.60%).
- **Entry Price**: The initial price to place the first limit order.
- **Leverage**: Applied to all active accounts.
- **Margin Type**: `Cross` or `Isolated`.

---

## 🛡 Disclaimer
This software is for educational purposes. Trading futures involves significant risk. Ensure you test your strategy on Testnet before using real funds. The authors are not responsible for any financial losses.
