import pandas as pd
import ta
import numpy as np
import logging
import time
from datetime import datetime, timezone, timedelta
from handlers.utils import (
    calculate_supertrend, detect_macd_divergence, check_price_action_patterns,
    score_reversal_pattern, calculate_snr_zones, calculate_echo_forecast,
    calculate_structural_rr
)
from handlers.ta_handler import get_ta_signal

class StrategyHandler:
    def __init__(self, bot_engine):
        self.bot = bot_engine
        self.last_prices = {} # symbol -> price

    def _get_expiry_seconds(self, interval_sec):
        now = datetime.now(timezone.utc)
        now_ts = int(now.timestamp())
        if interval_sec == 86400: # Daily
            next_close = ((now_ts // 86400) + 1) * 86400
        else:
            next_close = ((now_ts // interval_sec) + 1) * interval_sec
        return max(15, next_close - now_ts)

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

        self.last_prices[symbol] = current_price

    def _process_screener_based_strategy(self, symbol, strat_key):
        data = self.bot.screener_data.get(symbol)
        if not data: return

        # Only process if data is fresh (within last 30s)
        if time.time() - data.get('last_update', 0) > 30:
            return

        signal = data.get('signal') # 'BUY', 'SELL', or 'WAIT'

        sd = self.bot.symbol_data.get(symbol, {})

        # Strategy 7 Cooling (1-TF Mode)
        if strat_key == 'strategy_7':
            config = self.bot.config
            off_count = [config.get('strat7_small_tf'), config.get('strat7_mid_tf'), config.get('strat7_high_tf')].count('OFF')
            if off_count == 2: # 1-TF Mode
                last_sig = sd.get('last_strat7_signal')
                if signal == last_sig and signal != "WAIT":
                    return # Still same signal, wait for change
                sd['last_strat7_signal'] = signal

        if signal not in ['BUY', 'SELL']:
            return

        # v5.2 Structural Entry Validation (Gatekeeper)
        # We only enter if Reward/Risk based on Echo path is favorable (> 1.5)
        fcast_data = data.get('fcast_data')
        if fcast_data and 'forecast_prices' in fcast_data:
            rr = calculate_structural_rr(sd.get('last_tick'), fcast_data['forecast_prices'], signal)
            if rr < 1.5:
                # If RR is low, it means we are likely at the end of the move or too close to a peak.
                # We wait for a better entry (pullback).
                return

        # Check if already in position for this symbol
        for cid, c in self.bot.contracts.items():
            if c['symbol'] == symbol:
                return # Already have a trade

        # Execute with smart metadata
        self.bot.log(f"Strategy {strat_key} triggered {signal} for {symbol} based on screener.")

        # Pass full screener data as metadata to execute_trade
        self.bot._execute_trade(symbol, 'buy' if signal == 'BUY' else 'sell', metadata=data)

    def _process_strategy_1(self, symbol, is_candle_close):
        self._generic_crossover_strategy(symbol, is_candle_close, 1, "15m", 86400)

    def _process_strategy_2(self, symbol, is_candle_close):
        self._generic_crossover_strategy(symbol, is_candle_close, 2, "3m", 3600)

    def _process_strategy_3(self, symbol, is_candle_close):
        self._generic_crossover_strategy(symbol, is_candle_close, 3, "1m", 900)

    def _generic_crossover_strategy(self, symbol, is_candle_close, strat_num, ta_interval, expiry_interval_sec):
        sd = self.bot.symbol_data[symbol]
        htf_open = sd.get('htf_open')
        current_price = sd.get('last_tick')
        last_price = self.last_prices.get(symbol)

        if htf_open is None or current_price is None: return

        # Only entry if not in position
        for cid, c in self.bot.contracts.items():
            if c['symbol'] == symbol: return

        ta_signal = get_ta_signal(symbol, ta_interval)
        entry_type = self.bot.config.get('entry_type', 'candle_close')

        # Crossover detection
        is_cross_up = False
        is_cross_down = False

        if is_candle_close:
            # Check if previous candle closed across
            if len(sd.get('ltf_candles', [])) >= 1:
                last_candle = sd['ltf_candles'][-1]
                prev_candle = sd['ltf_candles'][-2] if len(sd['ltf_candles']) >= 2 else last_candle
                if prev_candle['close'] <= htf_open and last_candle['close'] > htf_open:
                    is_cross_up = True
                elif prev_candle['close'] >= htf_open and last_candle['close'] < htf_open:
                    is_cross_down = True
        else:
            # Tick mode crossover
            if last_price is not None:
                if last_price <= htf_open and current_price > htf_open:
                    is_cross_up = True
                elif last_price >= htf_open and current_price < htf_open:
                    is_cross_down = True

        # Echo Forecast Confirmation & Structural RR Gatekeeper
        echo_confirmed = False
        ltf_df = pd.DataFrame(sd.get('ltf_candles', []))
        if not ltf_df.empty:
            fcast_prices, correlation = calculate_echo_forecast(ltf_df)
            if fcast_prices and correlation > 0.5:
                fcast_final = fcast_prices[-1]

                # Check RR to ensure we aren't buying at the top or selling at the bottom
                direction = "BUY" if is_cross_up else "SELL"
                rr = calculate_structural_rr(current_price, fcast_prices, direction)

                if is_cross_up and fcast_final > current_price and rr >= 1.5:
                    echo_confirmed = True
                elif is_cross_down and fcast_final < current_price and rr >= 1.5:
                    echo_confirmed = True

        # Signal Filtering
        signal = None
        if is_cross_up and echo_confirmed:
            if ta_signal == "BUY" or (ta_signal == "STRONG_BUY" and is_candle_close):
                signal = 'buy'
        elif is_cross_down and echo_confirmed:
            if ta_signal == "SELL" or (ta_signal == "STRONG_SELL" and is_candle_close):
                signal = 'sell'

        if signal:
            self.bot.log(f"Strategy {strat_num} triggered {signal} for {symbol}. TA: {ta_signal}.")
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

        entry_type = self.bot.config.get('entry_type', 'candle_close')
        if entry_type == 'candle_close' and not is_candle_close: return
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

        # Echo Forecast Confirmation & Structural RR for SNR
        if signal:
            ltf_df = pd.DataFrame(sd.get('ltf_candles', []))
            if not ltf_df.empty:
                fcast_prices, correlation = calculate_echo_forecast(ltf_df)
                if fcast_prices and correlation > 0.5:
                    fcast_final = fcast_prices[-1]
                    rr = calculate_structural_rr(current_price, fcast_prices, signal)

                    if signal == 'buy':
                        if fcast_final <= current_price or rr < 1.5:
                            signal = None # Echo doesn't confirm reversal UP or poor RR
                    elif signal == 'sell':
                        if fcast_final >= current_price or rr < 1.5:
                            signal = None # Echo doesn't confirm reversal DOWN or poor RR

        if signal:
            self.bot.log(f"Strategy 4 triggered {signal} for {symbol}")
            self.bot._execute_trade(symbol, signal)
