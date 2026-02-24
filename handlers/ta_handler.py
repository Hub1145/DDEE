
import asyncio
import json
import time
import threading
import numpy as np
import pandas as pd
import websockets
from dataclasses import dataclass, field
from typing import Optional, Dict

# ─────────────────────────────────────────────
#  CONSTANTS & MAPPINGS
# ─────────────────────────────────────────────

INTERVAL_MAP = {
    "1m": 60,
    "2m": 120,
    "3m": 180,
    "5m": 300,
    "10m": 600,
    "15m": 900,
    "30m": 1800,
    "1h": 3600,
    "2h": 7200,
    "4h": 14400,
    "8h": 28800,
    "1d": 86400
}

@dataclass
class Analysis:
    symbol: str
    interval: str
    summary: dict = field(default_factory=dict)
    moving_averages: dict = field(default_factory=dict)
    oscillators: dict = field(default_factory=dict)
    indicators: dict = field(default_factory=dict)

# ─────────────────────────────────────────────
#  INDICATOR COMPUTATIONS
# ─────────────────────────────────────────────

def _ema(series: pd.Series, period: int) -> pd.Series:
    return series.ewm(span=period, adjust=False).mean()

def _sma(series: pd.Series, period: int) -> pd.Series:
    return series.rolling(window=period).mean()

def _rsi(close: pd.Series, period: int = 14) -> pd.Series:
    delta = close.diff()
    gain = delta.clip(lower=0).ewm(com=period - 1, adjust=False).mean()
    loss = (-delta.clip(upper=0)).ewm(com=period - 1, adjust=False).mean()
    rs = gain / loss
    return 100 - (100 / (1 + rs))

def _stoch(high: pd.Series, low: pd.Series, close: pd.Series, k_period: int = 14, d_period: int = 3, smooth_k: int = 3):
    lowest_low = low.rolling(k_period).min()
    highest_high = high.rolling(k_period).max()
    raw_k = 100 * (close - lowest_low) / (highest_high - lowest_low + 1e-10)
    k = raw_k.rolling(smooth_k).mean()
    d = k.rolling(d_period).mean()
    return k, d

def _macd(close: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9):
    macd_line = _ema(close, fast) - _ema(close, slow)
    signal_line = _ema(macd_line, signal)
    histogram = macd_line - signal_line
    return macd_line, signal_line, histogram

# ─────────────────────────────────────────────
#  VOTING & SIGNALS
# ─────────────────────────────────────────────

def _vote(buy_cond: bool, sell_cond: bool) -> str:
    if buy_cond: return "BUY"
    elif sell_cond: return "SELL"
    return "NEUTRAL"

def _score_to_recommendation(score: float) -> str:
    if score >= 0.5: return "STRONG_BUY"
    elif score >= 0.1: return "BUY"
    elif score <= -0.5: return "STRONG_SELL"
    elif score <= -0.1: return "SELL"
    return "NEUTRAL"

def _tally(signals: list) -> dict:
    buy = signals.count("BUY")
    sell = signals.count("SELL")
    neutral = signals.count("NEUTRAL")
    numeric = [1 if s == "BUY" else -1 if s == "SELL" else 0 for s in signals]
    score = sum(numeric) / len(numeric) if numeric else 0
    return {
        "RECOMMENDATION": _score_to_recommendation(score),
        "BUY": buy,
        "SELL": sell,
        "NEUTRAL": neutral,
    }

def _compute_analysis(df: pd.DataFrame, symbol: str, interval_name: str) -> Analysis:
    close = df["close"]
    high = df["high"]
    low = df["low"]
    price = close.iloc[-1]

    # Indicators
    rsi_val = _rsi(close).iloc[-1]
    stoch_k, _ = _stoch(high, low, close)
    macd_l, macd_s, _ = _macd(close)
    ema20 = _ema(close, 20).iloc[-1]
    ema50 = _ema(close, 50).iloc[-1]
    sma200 = _sma(close, 200).iloc[-1]

    osc_signals = {
        "RSI(14)": _vote(rsi_val < 30, rsi_val > 70),
        "Stoch(14,3,3)": _vote(stoch_k.iloc[-1] < 20, stoch_k.iloc[-1] > 80),
        "MACD": _vote(macd_l.iloc[-1] > macd_s.iloc[-1], macd_l.iloc[-1] < macd_s.iloc[-1]),
    }

    ma_signals = {
        "EMA20": _vote(price > ema20, price < ema20),
        "EMA50": _vote(price > ema50, price < ema50),
        "SMA200": _vote(price > sma200, price < sma200),
    }

    all_signals = list(osc_signals.values()) + list(ma_signals.values())
    summary = _tally(all_signals)

    return Analysis(
        symbol=symbol,
        interval=interval_name,
        summary=summary,
        moving_averages=_tally(list(ma_signals.values())),
        oscillators=_tally(list(osc_signals.values())),
        indicators={"close": price, "rsi": rsi_val, "ema50": ema50}
    )

# ─────────────────────────────────────────────
#  CONNECTION MANAGER (SINGLETON)
# ─────────────────────────────────────────────

class ConnectionManager:
    _instance = None
    _lock = threading.Lock()

    def __new__(cls):
        with cls._lock:
            if cls._instance is None:
                cls._instance = super(ConnectionManager, cls).__new__(cls)
                cls._instance.ws = None
                cls._instance.loop = None
                cls._instance.thread = None
                cls._instance.requests: Dict[str, asyncio.Future] = {}
                cls._instance.stop_event = asyncio.Event()
                cls._instance.app_id = "62845"
        return cls._instance

    def set_app_id(self, app_id: str):
        if str(self.app_id) != str(app_id):
            self.app_id = app_id
            if self.ws and self.loop:
                asyncio.run_coroutine_threadsafe(self.ws.close(), self.loop)

    def start(self):
        if self.thread and self.thread.is_alive(): return
        self.thread = threading.Thread(target=self._run_loop, daemon=True)
        self.thread.start()
        time.sleep(1)

    def _run_loop(self):
        self.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.loop)
        self.loop.run_until_complete(self._maintain_connection())

    async def _maintain_connection(self):
        while not self.stop_event.is_set():
            try:
                url = f"wss://ws.binaryws.com/websockets/v3?app_id={self.app_id}"
                async with websockets.connect(url) as ws:
                    self.ws = ws
                    while not self.stop_event.is_set():
                        msg = await ws.recv()
                        data = json.loads(msg)
                        req_id = data.get('echo_req', {}).get('passthrough', {}).get('req_id')
                        if req_id and req_id in self.requests:
                            self.requests[req_id].set_result(data)
            except Exception:
                await asyncio.sleep(5)

    async def call(self, request: dict):
        req_id = str(time.time_ns())
        request['passthrough'] = {'req_id': req_id}
        future = self.loop.create_future()
        self.requests[req_id] = future
        try:
            await self.ws.send(json.dumps(request))
            return await asyncio.wait_for(future, timeout=10)
        finally:
            del self.requests[req_id]

manager = ConnectionManager()
manager.start()

# ─────────────────────────────────────────────
#  PUBLIC API
# ─────────────────────────────────────────────

_CANDLE_CACHE = {}

async def fetch_candles(symbol: str, interval: str, count: int = 300) -> pd.DataFrame:
    granularity = INTERVAL_MAP.get(interval, 60)
    cache_key = (symbol, granularity)
    now = time.time()

    if cache_key in _CANDLE_CACHE:
        ts, df = _CANDLE_CACHE[cache_key]
        if now - ts < (granularity / 2): return df

    resp = await manager.call({
        "ticks_history": symbol,
        "style": "candles",
        "granularity": granularity,
        "count": count,
        "end": "latest"
    })

    if "candles" in resp:
        df = pd.DataFrame(resp["candles"])
        df["epoch_dt"] = pd.to_datetime(df["epoch"], unit="s")
        df.set_index("epoch_dt", inplace=True)
        df = df[["open", "high", "low", "close"]].astype(float)
        _CANDLE_CACHE[cache_key] = (now, df)
        return df
    return pd.DataFrame()

def get_ta_signal(symbol: str, interval: str) -> str:
    """Returns BUY, SELL, STRONG_BUY, STRONG_SELL, or NEUTRAL."""
    try:
        df = asyncio.run_coroutine_threadsafe(fetch_candles(symbol, interval), manager.loop).result()
        if df.empty: return "NEUTRAL"
        analysis = _compute_analysis(df, symbol, interval)
        return analysis.summary.get("RECOMMENDATION", "NEUTRAL")
    except Exception:
        return "NEUTRAL"

def get_ta_indicators(symbol: str, interval: str) -> dict:
    try:
        df = asyncio.run_coroutine_threadsafe(fetch_candles(symbol, interval), manager.loop).result()
        if df.empty: return {}
        analysis = _compute_analysis(df, symbol, interval)
        return analysis.indicators
    except Exception:
        return {}
