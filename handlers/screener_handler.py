import time
import logging
import pandas as pd
import ta
from concurrent.futures import ThreadPoolExecutor
from handlers.ta_handler import DerivTA, Interval

class ScreenerHandler:
    def __init__(self, bot_engine):
        self.bot = bot_engine
        self.stop_event = bot_engine.stop_event

    def update_screener(self, symbol, config):
        try:
            strat_key = config.get('active_strategy', 'strategy_1')
            if strat_key == 'strategy_5':
                return self.analyze_strategy_5(symbol)
            elif strat_key == 'strategy_6':
                return self.analyze_strategy_6(symbol)
            elif strat_key == 'strategy_7':
                return self.update_strat7_analysis(symbol, config)
            return None
        except Exception as e:
            logging.error(f"Screener error for {symbol}: {e}")
            return None

    def _get_smart_expiry(self, df_ltf, ltf_min, htf_min):
        """Calculate expiry based on volatility (ATR)."""
        try:
            if df_ltf is None or len(df_ltf) < 20:
                return htf_min

            atr_series = ta.volatility.AverageTrueRange(df_ltf['high'], df_ltf['low'], df_ltf['close'], window=14).average_true_range()
            atr_current = atr_series.iloc[-1]
            atr_avg = atr_series.rolling(50).mean().iloc[-1]

            if not atr_current or not atr_avg:
                return htf_min

            vol_factor = atr_avg / atr_current
            suggested = htf_min * vol_factor
            final_expiry = max(ltf_min, min(htf_min * 3, int(round(suggested))))
            return final_expiry
        except:
            return htf_min

    def analyze_strategy_5(self, symbol):
        """Strategy 5: Triple EMA Alignment (1m, 5m, 1h)"""
        try:
            h1m = DerivTA(symbol=symbol, interval=Interval.INTERVAL_1_MINUTE)
            h5m = DerivTA(symbol=symbol, interval=Interval.INTERVAL_5_MINUTES)
            h1h = DerivTA(symbol=symbol, interval=Interval.INTERVAL_1_HOUR)

            a1m = h1m.get_analysis()
            a5m = h5m.get_analysis()
            a1h = h1h.get_analysis()

            rec1m = a1m.summary['RECOMMENDATION']
            rec5m = a5m.summary['RECOMMENDATION']
            rec1h = a1h.summary['RECOMMENDATION']

            signal = "WAIT"
            direction = "NEUTRAL"
            desc = "No alignment"
            confidence = 0

            if "BUY" in rec1m and "BUY" in rec5m and "BUY" in rec1h:
                signal = "BUY"
                direction = "CALL"
                desc = "Triple EMA Alignment UP"
                confidence = 100
            elif "SELL" in rec1m and "SELL" in rec5m and "SELL" in rec1h:
                signal = "SELL"
                direction = "PUT"
                desc = "Triple EMA Alignment DOWN"
                confidence = 100

            df1m = h1m.get_dataframe()
            expiry = self._get_smart_expiry(df1m, 1, 15)
            atr_1m = ta.volatility.AverageTrueRange(df1m['high'], df1m['low'], df1m['close'], window=14).average_true_range().iloc[-1]

            data = {
                'signal': signal,
                'direction': direction,
                'desc': desc,
                'confidence': confidence,
                'expiry_min': expiry,
                'atr_1m': round(atr_1m, 4),
                'ltf': rec1m,
                'mtf': rec5m,
                'htf': rec1h,
                'last_update': time.time()
            }
            self.bot.screener_data[symbol] = data
            self.bot.emit('screener_update', {'symbol': symbol, 'data': data})
            return data
        except Exception as e:
            logging.error(f"Error in Strategy 5 analysis for {symbol}: {e}")
            return None

    def analyze_strategy_6(self, symbol):
        """Strategy 6: RSI OS/OB (1m) + 15m Trend"""
        try:
            h1m = DerivTA(symbol=symbol, interval=Interval.INTERVAL_1_MINUTE)
            h15m = DerivTA(symbol=symbol, interval=Interval.INTERVAL_15_MINUTES)

            a1m = h1m.get_analysis()
            a15m = h15m.get_analysis()

            rsi = a1m.indicators.get('RSI', 50)
            trend = a15m.summary['RECOMMENDATION']

            signal = "WAIT"
            direction = "NEUTRAL"
            desc = f"RSI: {rsi:.1f}, Trend: {trend}"
            confidence = 0

            if rsi < 30 and "BUY" in trend:
                signal = "BUY"
                direction = "CALL"
                desc = "RSI Oversold + Bullish Trend"
                confidence = 100
            elif rsi > 70 and "SELL" in trend:
                signal = "SELL"
                direction = "PUT"
                desc = "RSI Overbought + Bearish Trend"
                confidence = 100

            df1m = h1m.get_dataframe()
            expiry = self._get_smart_expiry(df1m, 1, 15)
            atr_1m = ta.volatility.AverageTrueRange(df1m['high'], df1m['low'], df1m['close'], window=14).average_true_range().iloc[-1]

            data = {
                'signal': signal,
                'direction': direction,
                'desc': desc,
                'confidence': confidence,
                'expiry_min': expiry,
                'atr_1m': round(atr_1m, 4),
                'rsi': round(rsi, 2),
                'trend': trend,
                'last_update': time.time()
            }
            self.bot.screener_data[symbol] = data
            self.bot.emit('screener_update', {'symbol': symbol, 'data': data})
            return data
        except Exception as e:
            logging.error(f"Error in Strategy 6 analysis for {symbol}: {e}")
            return None

    def update_strat7_analysis(self, symbol, config):
        tf_small_val = config.get('strat7_small_tf', '60')
        tf_mid_val = config.get('strat7_mid_tf', '300')
        tf_high_val = config.get('strat7_high_tf', '3600')

        def val_to_interval(val):
            if val == 'OFF': return None
            val = int(val)
            for item in Interval:
                if item.value == val: return item
            return Interval.INTERVAL_1_MINUTE

        try:
            tf_small = val_to_interval(tf_small_val)
            tf_mid = val_to_interval(tf_mid_val)
            tf_high = val_to_interval(tf_high_val)

            a_small = a_mid = a_high = None
            h_small = h_mid = h_high = None

            if tf_small:
                h_small = DerivTA(symbol=symbol, interval=tf_small)
                a_small = h_small.get_analysis()
            if tf_mid:
                h_mid = DerivTA(symbol=symbol, interval=tf_mid)
                a_mid = h_mid.get_analysis()
            if tf_high:
                h_high = DerivTA(symbol=symbol, interval=tf_high)
                a_high = h_high.get_analysis()

            self.bot.strat7_cache[symbol] = {
                'small': a_small,
                'mid': a_mid,
                'high': a_high,
                'timestamp': time.time()
            }

            rec_small = a_small.summary['RECOMMENDATION'] if a_small else "OFF"
            rec_mid = a_mid.summary['RECOMMENDATION'] if a_mid else "OFF"
            rec_high = a_high.summary['RECOMMENDATION'] if a_high else "OFF"

            total_buy = (a_small.summary['BUY'] if a_small else 0) + \
                        (a_mid.summary['BUY'] if a_mid else 0) + \
                        (a_high.summary['BUY'] if a_high else 0)
            total_sell = (a_small.summary['SELL'] if a_small else 0) + \
                         (a_mid.summary['SELL'] if a_mid else 0) + \
                         (a_high.summary['SELL'] if a_high else 0)

            total_signals = 0
            for a in [a_small, a_mid, a_high]:
                if a:
                    total_signals += a.summary['BUY'] + a.summary['SELL'] + a.summary['NEUTRAL']

            confidence = ((total_buy - total_sell) / total_signals) * 100 if total_signals > 0 else 0

            enabled = []
            if a_small: enabled.append(a_small)
            if a_mid: enabled.append(a_mid)
            if a_high: enabled.append(a_high)

            label = "NEUTRAL"
            direction = "NEUTRAL"
            signal = "WAIT"

            if len(enabled) == 1:
                rec = enabled[0].summary['RECOMMENDATION']
                if rec == "BUY":
                    label = "ALIGNED_BUY"
                    direction = "CALL"
                    signal = "BUY"
                elif rec == "SELL":
                    label = "ALIGNED_SELL"
                    direction = "PUT"
                    signal = "SELL"
            elif len(enabled) > 1:
                all_buy = all("BUY" in a.summary['RECOMMENDATION'] for a in enabled)
                all_sell = all("SELL" in a.summary['RECOMMENDATION'] for a in enabled)

                quick_buy = False
                quick_sell = False
                if a_high and a_small:
                    quick_buy = "STRONG_BUY" in a_high.summary['RECOMMENDATION'] and "BUY" in a_small.summary['RECOMMENDATION']
                    quick_sell = "STRONG_SELL" in a_high.summary['RECOMMENDATION'] and "SELL" in a_small.summary['RECOMMENDATION']

                if quick_buy:
                    label = "QUICK_BUY"
                    direction = "CALL"
                    signal = "BUY"
                elif quick_sell:
                    label = "QUICK_SELL"
                    direction = "PUT"
                    signal = "SELL"
                elif all_buy:
                    label = "ALIGNED_BUY"
                    direction = "CALL"
                    signal = "BUY"
                elif all_sell:
                    label = "ALIGNED_SELL"
                    direction = "PUT"
                    signal = "SELL"

            enabled_tfs = []
            if tf_small: enabled_tfs.append(tf_small.value)
            if tf_mid: enabled_tfs.append(tf_mid.value)
            if tf_high: enabled_tfs.append(tf_high.value)

            if enabled_tfs:
                min_tf_val = min(enabled_tfs) // 60
                max_tf_val = max(enabled_tfs) // 60
                ref_htf = max_tf_val
                if len(enabled_tfs) > 1:
                    ref_htf = sorted(enabled_tfs)[-1] // 60

                target_h = h_small or h_mid or h_high
                expiry = self._get_smart_expiry(target_h.get_dataframe(), min_tf_val, ref_htf)
            else:
                expiry = 5

            if "QUICK" in label:
                expiry = max(1, expiry // 2)

            data = {
                'confidence': round(confidence, 1),
                'label': label,
                'direction': direction,
                'signal': signal,
                'desc': label,
                'summary_small': rec_small,
                'summary_mid': rec_mid,
                'summary_high': rec_high,
                'expiry_min': expiry,
                'atr': 0.0,
                'last_update': time.time()
            }
            self.bot.screener_data[symbol] = data
            self.bot.emit('screener_update', {'symbol': symbol, 'data': data})
            return data
        except Exception as e:
            logging.error(f"Strategy 7 analysis error for {symbol}: {e}", exc_info=True)
            return None

    def background_loop(self):
        self.bot.log("Screener background loop started")
        with ThreadPoolExecutor(max_workers=3) as executor:
            while not self.stop_event.is_set():
                config = self.bot.config
                symbols = config.get('symbols', [])

                for symbol in symbols:
                    if self.stop_event.is_set(): break
                    executor.submit(self.update_screener, symbol, config)
                    time.sleep(1.0)

                time.sleep(10)
