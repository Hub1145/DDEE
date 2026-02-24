import pandas as pd
import ta
import numpy as np
import logging
import time
from datetime import datetime, timezone
from handlers.utils import (
    calculate_supertrend, detect_macd_divergence, check_price_action_patterns,
    score_reversal_pattern, calculate_snr_zones
)

class StrategyHandler:
    def __init__(self, bot_engine):
        self.bot = bot_engine

    def process_strategy(self, symbol, is_candle_close):
        # 1. Risk Management: Max Daily Profit/Loss
        max_loss_pct = self.bot.config.get('max_daily_loss_pct', 5)
        max_profit_pct = self.bot.config.get('max_daily_profit_pct', 10)

        if self.bot.daily_start_balance > 0:
            current_equity = self.bot.account_balance + sum(c.get('pnl', 0) for c in self.bot.contracts.values())
            daily_pnl = current_equity - self.bot.daily_start_balance
            current_pnl_pct = (daily_pnl / self.bot.daily_start_balance) * 100

            if current_pnl_pct <= -max_loss_pct:
                if self.bot.is_running:
                    self.bot.log(f"Daily Loss Limit: {current_pnl_pct:.2f}%. Trading paused.", "warning")
                    self.bot.is_running = False
                return

            if current_pnl_pct >= max_profit_pct:
                if self.bot.is_running:
                    self.bot.log(f"Daily Profit Target: {current_pnl_pct:.2f}%. Trading paused.", "info")
                    self.bot.is_running = False
                return

        sd = self.bot.symbol_data.get(symbol)
        if not sd: return

        current_price = sd.get('last_tick')
        if current_price is None: return

        strat_key = self.bot.config.get('active_strategy', 'strategy_1')

        # Strategy 5, 6, 7 rely on Screener Data
        if strat_key in ['strategy_5', 'strategy_6', 'strategy_7']:
            self._process_screener_based_strategy(symbol, strat_key)
        elif strat_key == 'strategy_1':
            self._process_strategy_1(symbol, is_candle_close)
        elif strat_key == 'strategy_2':
            self._process_strategy_2(symbol, is_candle_close)
        elif strat_key == 'strategy_3':
            self._process_strategy_3(symbol, is_candle_close)
        elif strat_key == 'strategy_4':
            self._process_strategy_4(symbol, is_candle_close)

    def _process_screener_based_strategy(self, symbol, strat_key):
        data = self.bot.screener_data.get(symbol)
        if not data: return

        # Only process if data is fresh (within last 30s)
        if time.time() - data.get('last_update', 0) > 30:
            return

        signal = data.get('signal') # 'BUY', 'SELL', or 'WAIT'
        if signal not in ['BUY', 'SELL']:
            return

        # Check if already in position for this symbol
        for cid, c in self.bot.contracts.items():
            if c['symbol'] == symbol:
                return # Already have a trade

        # Execute
        self.bot.log(f"Strategy {strat_key} triggered {signal} for {symbol} based on screener.")
        self.bot._execute_trade(symbol, 'buy' if signal == 'BUY' else 'sell')

    def _process_strategy_1(self, symbol, is_candle_close):
        sd = self.bot.symbol_data[symbol]
        htf_open = sd.get('htf_open')
        current_price = sd.get('last_tick')
        current_ltf = sd.get('current_ltf_candle')

        if htf_open is None or current_price is None or current_ltf is None: return

        # Track crosses
        self.bot._track_daily_open_crosses(symbol, current_price)
        if sd.get('daily_crosses', 0) > 3: return # Whipsaw limit

        # Check if already in position
        for cid, c in self.bot.contracts.items():
            if c['symbol'] == symbol: return

        trend_bias = None
        if len(sd.get('h4_candles', [])) >= 100:
            df_h4 = pd.DataFrame(sd['h4_candles'])
            ema100_h4 = ta.trend.EMAIndicator(df_h4['close'], window=100).ema_indicator().iloc[-1]
            trend_bias = 'buy' if current_price > ema100_h4 else 'sell'

        signal = None
        if current_ltf['open'] <= htf_open and current_price > htf_open and current_price > current_ltf['open']:
            if trend_bias is None or trend_bias == 'buy': signal = 'buy'
        elif current_ltf['open'] >= htf_open and current_price < htf_open and current_price < current_ltf['open']:
            if trend_bias is None or trend_bias == 'sell': signal = 'sell'

        if signal:
            self.bot.log(f"Strategy 1 triggered {signal} for {symbol}")
            self.bot._execute_trade(symbol, signal)

    def _process_strategy_2(self, symbol, is_candle_close):
        sd = self.bot.symbol_data[symbol]
        htf_open = sd.get('htf_open')
        current_price = sd.get('last_tick')
        current_ltf = sd.get('current_ltf_candle')

        if htf_open is None or current_price is None or current_ltf is None: return

        for cid, c in self.bot.contracts.items():
            if c['symbol'] == symbol: return

        rsi_m3 = 50
        if len(sd.get('m3_candles', [])) >= 14:
            df_m3 = pd.DataFrame(sd['m3_candles'])
            rsi_m3 = ta.momentum.RSIIndicator(df_m3['close']).rsi().iloc[-1]

        bias = None
        if len(sd.get('h4_candles', [])) >= 50:
            df_h4 = pd.DataFrame(sd['h4_candles'])
            ema21_h4 = ta.trend.EMAIndicator(df_h4['close'], window=21).ema_indicator().iloc[-1]
            ema50_h4 = ta.trend.EMAIndicator(df_h4['close'], window=50).ema_indicator().iloc[-1]
            bias = 'buy' if ema21_h4 > ema50_h4 else 'sell'

        signal = None
        if current_ltf['open'] <= htf_open and current_price > htf_open and current_price > current_ltf['open']:
            if rsi_m3 > 55 and (bias is None or bias == 'buy'): signal = 'buy'
        elif current_ltf['open'] >= htf_open and current_price < htf_open and current_price < current_ltf['open']:
            if rsi_m3 < 45 and (bias is None or bias == 'sell'): signal = 'sell'

        if signal:
            self.bot.log(f"Strategy 2 triggered {signal} for {symbol}")
            self.bot._execute_trade(symbol, signal)

    def _process_strategy_3(self, symbol, is_candle_close):
        sd = self.bot.symbol_data[symbol]
        htf_open = sd.get('htf_open')
        current_price = sd.get('last_tick')
        current_ltf = sd.get('current_ltf_candle')

        if htf_open is None or current_price is None or current_ltf is None: return

        for cid, c in self.bot.contracts.items():
            if c['symbol'] == symbol: return

        now = datetime.now(timezone.utc)
        if sd.get('last_trade_hour') != now.hour:
            sd['last_trade_hour'] = now.hour
            sd['hourly_trade_count'] = 0

        if sd.get('hourly_trade_count', 0) >= 4: return

        signal = None
        if current_ltf['open'] <= htf_open and current_price > htf_open:
            signal = 'buy'
        elif current_ltf['open'] >= htf_open and current_price < htf_open:
            signal = 'sell'

        if signal:
            self.bot.log(f"Strategy 3 triggered {signal} for {symbol}")
            self.bot._execute_trade(symbol, signal)

    def _process_strategy_4(self, symbol, is_candle_close):
        sd = self.bot.symbol_data[symbol]
        current_ltf = sd.get('current_ltf_candle')
        current_price = sd.get('last_tick')

        if current_ltf is None or current_price is None: return

        # SNR Invalidation on candle close
        zones = sd.get('snr_zones', [])
        if is_candle_close:
            remaining_zones = []
            for z in zones:
                if z['type'] in ['S', 'Flip'] and current_ltf['close'] < (z['price'] * 0.9995): continue
                if z['type'] in ['R', 'Flip'] and current_ltf['close'] > (z['price'] * 1.0005): continue
                remaining_zones.append(z)
            sd['snr_zones'] = remaining_zones
            zones = remaining_zones

        if not is_candle_close: return
        if not zones: return

        for cid, c in self.bot.contracts.items():
            if c['symbol'] == symbol: return

        pattern = check_price_action_patterns(sd['ltf_candles'])
        if not pattern or pattern == "marubozu": return

        rsi_m5 = 50
        if len(sd.get('m5_candles', [])) >= 14:
            df_m5 = pd.DataFrame(sd['m5_candles'])
            rsi_m5 = ta.momentum.RSIIndicator(df_m5['close']).rsi().iloc[-1]

        pattern_score = score_reversal_pattern(symbol, pattern, sd['ltf_candles'])
        if pattern_score < 2: return

        ema50_h1 = None
        if len(sd.get('htf_candles', [])) >= 50:
            df_h1 = pd.DataFrame(sd['htf_candles'])
            ema50_h1 = ta.trend.EMAIndicator(df_h1['close'], window=50).ema_indicator().iloc[-1]

        signal = None
        for z in zones:
            buffer = z['price'] * 0.0002
            touched = current_ltf['low'] <= (z['price'] + buffer) and current_ltf['high'] >= (z['price'] - buffer)

            if touched:
                if z['type'] in ['S', 'Flip'] and pattern in ['bullish_pin', 'bullish_engulfing', 'doji', 'tweezer_bottom', 'bullish_harami']:
                    if rsi_m5 < 80 and (ema50_h1 is None or current_price > ema50_h1):
                        signal = 'buy'
                        z['total_lifetime_touches'] = z.get('total_lifetime_touches', 0) + 1
                        break
                elif z['type'] in ['R', 'Flip'] and pattern in ['bearish_pin', 'bearish_engulfing', 'doji', 'tweezer_top', 'bearish_harami']:
                    if rsi_m5 > 20 and (ema50_h1 is None or current_price < ema50_h1):
                        signal = 'sell'
                        z['total_lifetime_touches'] = z.get('total_lifetime_touches', 0) + 1
                        break

        if signal:
            self.bot.log(f"Strategy 4 triggered {signal} for {symbol}")
            self.bot._execute_trade(symbol, signal)
