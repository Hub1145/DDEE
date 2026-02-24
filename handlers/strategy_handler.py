import pandas as pd
import ta
import numpy as np
import logging
import time
from datetime import datetime, timezone, timedelta
from handlers.utils import (
    check_price_action_patterns, score_reversal_pattern,
    calculate_supertrend
)

class StrategyHandler:
    def __init__(self, bot_engine):
        self.bot = bot_engine

    def process_strategy(self, symbol, is_candle_close):
        # Check Max Daily Loss/Profit relative to starting balance of the day
        max_loss_pct = self.bot.config.get('max_daily_loss_pct', 5)
        max_profit_pct = self.bot.config.get('max_daily_profit_pct', 10)

        if self.bot.daily_start_balance > 0:
            current_equity = self.bot.account_balance + sum(c.get('pnl', 0) for c in self.bot.contracts.values())
            daily_pnl = current_equity - self.bot.daily_start_balance
            current_pnl_pct = (daily_pnl / self.bot.daily_start_balance) * 100

            if current_pnl_pct <= -max_loss_pct:
                if self.bot.is_running:
                    self.bot.log(f"Max daily loss reached ({current_pnl_pct:.2f}% of starting balance). Trading paused.", "warning")
                    self.bot.is_running = False
                return

            if current_pnl_pct >= max_profit_pct:
                if self.bot.is_running:
                    self.bot.log(f"Max daily profit reached ({current_pnl_pct:.2f}% of starting balance). Trading paused.", "warning")
                    self.bot.is_running = False
                return

        sd = self.bot.symbol_data[symbol]
        htf_open = sd['htf_open']
        current_ltf = sd['current_ltf_candle']
        current_price = sd['last_tick']

        if htf_open is None or current_ltf is None or current_price is None:
            return

        time_key = current_ltf['epoch']
        if sd.get('last_processed_ltf') == time_key and is_candle_close:
            return

        signal = None
        strat_key = self.bot.config.get('active_strategy', 'strategy_1')

        if strat_key == 'strategy_1':
            self.bot._track_daily_open_crosses(symbol, current_price)

        if strat_key == 'strategy_4':
            signal = self._process_strategy_4(symbol, sd, current_ltf, current_price, is_candle_close)
        elif strat_key == 'strategy_7':
            signal = self._process_strategy_7(symbol, sd, is_candle_close)
        elif strat_key in ['strategy_5', 'strategy_6']:
            signal = self._process_intelligence_strategy(symbol, sd, strat_key)
        else:
            signal = self._process_default_strategies(symbol, sd, strat_key, htf_open, current_ltf, current_price, is_candle_close)

        if signal:
            if sd.get('last_trade_ltf') == time_key:
                return

            sd['last_trade_ltf'] = time_key
            if is_candle_close:
                sd['last_processed_ltf'] = time_key

            self.bot._execute_trade(symbol, signal)

    def _process_strategy_4(self, symbol, sd, current_ltf, current_price, is_candle_close):
        zones = sd.get('snr_zones', [])
        if is_candle_close:
            remaining_zones = []
            for z in zones:
                if z['type'] in ['S', 'Flip'] and current_ltf['close'] < (z['price'] * 0.9995):
                    self.bot.log(f"Strategy 4: Zone {z['price']:.2f} broken (Bearish close through).")
                    continue
                if z['type'] in ['R', 'Flip'] and current_ltf['close'] > (z['price'] * 1.0005):
                    self.bot.log(f"Strategy 4: Zone {z['price']:.2f} broken (Bullish close through).")
                    continue
                remaining_zones.append(z)
            sd['snr_zones'] = remaining_zones
            zones = remaining_zones

        if not is_candle_close: return None
        if not zones: return None

        pattern = check_price_action_patterns(sd['ltf_candles'])
        if not pattern or pattern == "marubozu": return None

        if len(sd.get('m5_candles', [])) >= 14:
            df_m5 = pd.DataFrame(sd['m5_candles'])
            rsi_m5 = ta.momentum.RSIIndicator(df_m5['close']).rsi().iloc[-1]
        else: rsi_m5 = 50

        pattern_score = score_reversal_pattern(symbol, pattern, sd['ltf_candles'])
        if pattern_score < 2: return None

        ema50_h1 = None
        if len(sd.get('htf_candles', [])) >= 50:
            df_h1 = pd.DataFrame(sd['htf_candles'])
            ema50_h1 = ta.trend.EMAIndicator(df_h1['close'], window=50).ema_indicator().iloc[-1]

        for z in zones:
            buffer = z['price'] * 0.0002
            touched = current_ltf['low'] <= (z['price'] + buffer) and current_ltf['high'] >= (z['price'] - buffer)

            if touched:
                if z['type'] in ['S', 'Flip'] and pattern in ['bullish_pin', 'bullish_engulfing', 'doji', 'tweezer_bottom', 'bullish_harami']:
                    if rsi_m5 < 80:
                        if ema50_h1 is None or current_price > ema50_h1:
                            z['total_lifetime_touches'] = z.get('total_lifetime_touches', 0) + 1
                            self.bot.log(f"Strategy 4 BUY Signal: {pattern} at {z['type']} zone {z['price']:.2f}")
                            return 'buy'
                elif z['type'] in ['R', 'Flip'] and pattern in ['bearish_pin', 'bearish_engulfing', 'doji', 'tweezer_top', 'bearish_harami']:
                    if rsi_m5 > 20:
                        if ema50_h1 is None or current_price < ema50_h1:
                            z['total_lifetime_touches'] = z.get('total_lifetime_touches', 0) + 1
                            self.bot.log(f"Strategy 4 SELL Signal: {pattern} at {z['type']} zone {z['price']:.2f}")
                            return 'sell'
        return None

    def _process_strategy_7(self, symbol, sd, is_candle_close):
        cache = self.bot.strat7_cache.get(symbol)
        if not cache: return None

        metrics = self.bot.screener_data.get(symbol, {})
        if metrics.get('over_adr'): return None
        if time.time() - cache['timestamp'] > 65: return None

        rec_small = cache['small'].summary['RECOMMENDATION'] if cache['small'] else "NEUTRAL"
        rec_mid = cache['mid'].summary['RECOMMENDATION'] if cache['mid'] else "NEUTRAL"
        rec_high = cache['high'].summary['RECOMMENDATION'] if cache['high'] else "NEUTRAL"

        prev_small = sd.get('last_strat7_small_rec')
        sd['last_strat7_small_rec'] = rec_small

        # Only proceed if small TF is not OFF
        if self.bot.config.get('strat7_small_tf') == 'OFF':
            # If small is OFF, we might use Mid/High alignment
             if "BUY" in rec_high and "BUY" in rec_mid: return 'buy'
             if "SELL" in rec_high and "SELL" in rec_mid: return 'sell'
             return None

        if "BUY" in rec_high and "BUY" in rec_mid:
            if "BUY" in rec_small and (prev_small is None or "BUY" not in prev_small):
                self.bot.log(f"Strategy 7: Pullback entry BUY on {symbol}")
                return 'buy'
        elif "SELL" in rec_high and "SELL" in rec_mid:
            if "SELL" in rec_small and (prev_small is None or "SELL" not in prev_small):
                self.bot.log(f"Strategy 7: Pullback entry SELL on {symbol}")
                return 'sell'
        return None

    def _process_intelligence_strategy(self, symbol, sd, strat_key):
        metrics = self.bot.screener_data.get(symbol)
        if not metrics: return None

        contract_type = self.bot.config.get('contract_type', 'rise_fall')
        is_multiplier = (contract_type == 'multiplier')

        threshold = metrics.get('threshold', 72 if not is_multiplier else 68)
        if strat_key == 'strategy_6': threshold = 60

        if abs(metrics['confidence']) < threshold: return None

        direction = metrics['direction']

        if is_multiplier:
            if strat_key == 'strategy_6': return 'buy' if direction == 'CALL' else 'sell'

            df_m15 = pd.DataFrame(sd.get('m15_candles', []))
            if df_m15.empty: return None

            ema50_15 = ta.trend.EMAIndicator(df_m15['close'], window=50).ema_indicator().iloc[-1]
            st_15, st_dir_15 = calculate_supertrend(df_m15)
            price_15 = df_m15['close'].iloc[-1]
            near_zone = (abs(price_15 - ema50_15) / ema50_15 < 0.005) or \
                        (abs(price_15 - st_15.iloc[-1]) / st_15.iloc[-1] < 0.005)

            if near_zone:
                df_m5 = pd.DataFrame(sd.get('m5_candles', []))
                if not df_m5.empty:
                    last_m5 = df_m5.iloc[-1]
                    m5_resumed = (direction == 'CALL' and last_m5['close'] > last_m5['open']) or \
                                 (direction == 'PUT' and last_m5['close'] < last_m5['open'])
                    if m5_resumed and sd['ltf_candles']:
                        last_ltf = sd['ltf_candles'][-1]
                        ltf_confirmed = (direction == 'CALL' and last_ltf['close'] > last_ltf['open']) or \
                                        (direction == 'PUT' and last_ltf['close'] < last_ltf['open'])
                        if ltf_confirmed: return 'buy' if direction == 'CALL' else 'sell'
        else:
            if strat_key == 'strategy_6': return 'buy' if direction == 'CALL' else 'sell'

            price_5m = sd['current_ltf_candle']['close'] if sd.get('current_ltf_candle') else sd['last_tick']
            f_highs = sd.get('fractal_highs', [])[-3:]
            f_lows = sd.get('fractal_lows', [])[-3:]

            fractal_touch = False
            if direction == 'PUT': fractal_touch = any(abs(price_5m - fh) / fh < 0.002 for fh in f_highs)
            else: fractal_touch = any(abs(price_5m - fl) / fl < 0.002 for fl in f_lows)

            at_structure = fractal_touch
            if not at_structure:
                df_m15 = pd.DataFrame(sd.get('m15_candles', []))
                if not df_m15.empty:
                    bb_15 = ta.volatility.BollingerBands(df_m15['close'])
                    price_15 = df_m15['close'].iloc[-1]
                    at_bb = (direction == 'PUT' and price_15 >= bb_15.bollinger_hband().iloc[-1]) or \
                            (direction == 'CALL' and price_15 <= bb_15.bollinger_lband().iloc[-1])
                    zones = sd.get('snr_zones', [])
                    at_snr = any(abs(price_15 - z['price']) / z['price'] < 0.002 for z in zones)
                    at_structure = at_bb or at_snr

            if at_structure:
                srsi_k = metrics.get('srsi_k', 0.5)
                stoch_extreme = (direction == 'CALL' and srsi_k <= 0.2) or (direction == 'PUT' and srsi_k >= 0.8)
                if fractal_touch and not stoch_extreme: return None

                if sd['ltf_candles']:
                    pattern = check_price_action_patterns(sd['ltf_candles'])
                    if direction == 'CALL' and pattern in ['bullish_pin', 'bullish_engulfing', 'tweezer_bottom']: return 'buy'
                    elif direction == 'PUT' and pattern in ['bearish_pin', 'bearish_engulfing', 'tweezer_top']: return 'sell'
        return None

    def _process_default_strategies(self, symbol, sd, strat_key, htf_open, current_ltf, current_price, is_candle_close):
        if strat_key == 'strategy_1' and not is_candle_close: return None
        check_price = current_ltf['close'] if is_candle_close else current_price

        if strat_key == 'strategy_1':
            if sd.get('daily_crosses', 0) > 3: return None
            trend_bias = None
            if len(sd.get('h4_candles', [])) >= 100:
                df_h4 = pd.DataFrame(sd['h4_candles'])
                ema100_h4 = ta.trend.EMAIndicator(df_h4['close'], window=100).ema_indicator().iloc[-1]
                trend_bias = 'buy' if current_price > ema100_h4 else 'sell'

            if current_ltf['open'] <= htf_open and check_price > htf_open and check_price > current_ltf['open']:
                if trend_bias is None or trend_bias == 'buy': return 'buy'
            elif current_ltf['open'] >= htf_open and check_price < htf_open and check_price < current_ltf['open']:
                if trend_bias is None or trend_bias == 'sell': return 'sell'

        elif strat_key == 'strategy_2':
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

            if current_ltf['open'] <= htf_open and check_price > htf_open and check_price > current_ltf['open']:
                if rsi_m3 > 55 and (bias is None or bias == 'buy'): return 'buy'
            elif current_ltf['open'] >= htf_open and check_price < htf_open and check_price < current_ltf['open']:
                if rsi_m3 < 45 and (bias is None or bias == 'sell'): return 'sell'

        elif strat_key == 'strategy_3':
            now = datetime.now(timezone.utc)
            if sd.get('last_trade_hour') != now.hour:
                sd['last_trade_hour'] = now.hour
                sd['hourly_trade_count'] = 0
            if sd.get('hourly_trade_count', 0) >= 4: return None

            atr_1m = 0
            if len(sd['ltf_candles']) >= 14:
                df_1m = pd.DataFrame(sd['ltf_candles'])
                atr_1m = ta.volatility.AverageTrueRange(df_1m['high'], df_1m['low'], df_1m['close']).average_true_range().iloc[-1]
                sd['atr_1m_history'].append(atr_1m)
            if len(sd['atr_1m_history']) >= 20:
                if atr_1m < np.percentile(list(sd['atr_1m_history']), 20): return None

            if len(sd['ltf_candles']) >= 2:
                c1, c2 = sd['ltf_candles'][-1], sd['ltf_candles'][-2]
                if c1['close'] > htf_open and c2['close'] > htf_open and c1['close'] > c1['open']:
                    sd['hourly_trade_count'] += 1
                    return 'buy'
                elif c1['close'] < htf_open and c2['close'] < htf_open and c1['close'] < c1['open']:
                    sd['hourly_trade_count'] += 1
                    return 'sell'
        else:
            if current_ltf['open'] <= htf_open and check_price > htf_open and check_price > current_ltf['open']: return 'buy'
            elif current_ltf['open'] >= htf_open and check_price < htf_open and check_price < current_ltf['open']: return 'sell'
        return None
