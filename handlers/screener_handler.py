import time
import logging
import pandas as pd
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

    def analyze_strategy_5(self, symbol):
        """Strategy 5: Triple EMA Alignment (1m, 5m, 1h)"""
        try:
            # We use 1m, 5m, 1h
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
            desc = "No alignment"

            # Use exact match for signal to allow skipping 'STRONG' if desired,
            # but for Strat 5 alignment usually allows Strong.
            # User didn't specify skipping strong for Strat 5.
            if "BUY" in rec1m and "BUY" in rec5m and "BUY" in rec1h:
                signal = "BUY"
                desc = "Triple EMA Alignment UP"
            elif "SELL" in rec1m and "SELL" in rec5m and "SELL" in rec1h:
                signal = "SELL"
                desc = "Triple EMA Alignment DOWN"

            data = {
                'signal': signal,
                'desc': desc,
                'expiry_min': 5,
                'ltf': rec1m,
                'mtf': rec5m,
                'htf': rec1h,
                'last_update': time.time()
            }
            self.bot.screener_data[symbol] = data
            logging.info(f"Strategy 5 update for {symbol}: {signal} ({rec1m}, {rec5m}, {rec1h})")
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
            desc = f"RSI: {rsi:.1f}, Trend: {trend}"

            if rsi < 30 and "BUY" in trend:
                signal = "BUY"
                desc = "RSI Oversold + Bullish Trend"
            elif rsi > 70 and "SELL" in trend:
                signal = "SELL"
                desc = "RSI Overbought + Bearish Trend"

            data = {
                'signal': signal,
                'desc': desc,
                'expiry_min': 2,
                'rsi': round(rsi, 2),
                'trend': trend,
                'last_update': time.time()
            }
            self.bot.screener_data[symbol] = data
            logging.info(f"Strategy 6 update for {symbol}: {signal} (RSI: {rsi:.1f}, Trend: {trend})")
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

            if tf_small:
                a_small = DerivTA(symbol=symbol, interval=tf_small).get_analysis()
            if tf_mid:
                a_mid = DerivTA(symbol=symbol, interval=tf_mid).get_analysis()
            if tf_high:
                a_high = DerivTA(symbol=symbol, interval=tf_high).get_analysis()

            self.bot.strat7_cache[symbol] = {
                'small': a_small,
                'mid': a_mid,
                'high': a_high,
                'timestamp': time.time()
            }

            rec_small = a_small.summary['RECOMMENDATION'] if a_small else "OFF"
            rec_mid = a_mid.summary['RECOMMENDATION'] if a_mid else "OFF"
            rec_high = a_high.summary['RECOMMENDATION'] if a_high else "OFF"

            # Confidence
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

            # Alignment Logic
            enabled = []
            if a_small: enabled.append(a_small)
            if a_mid: enabled.append(a_mid)
            if a_high: enabled.append(a_high)

            label = "NEUTRAL"
            if len(enabled) == 1:
                # Requirement: Skip STRONG signals if only one timeframe is used
                rec = enabled[0].summary['RECOMMENDATION']
                if rec == "BUY": label = "ALIGNED_BUY"
                elif rec == "SELL": label = "ALIGNED_SELL"
            elif len(enabled) > 1:
                all_buy = all("BUY" in a.summary['RECOMMENDATION'] for a in enabled)
                all_sell = all("SELL" in a.summary['RECOMMENDATION'] for a in enabled)

                # Quick entry (Highest Strong, Lowest normal)
                quick_buy = False
                quick_sell = False
                if a_high and a_small:
                    quick_buy = "STRONG_BUY" in a_high.summary['RECOMMENDATION'] and "BUY" in a_small.summary['RECOMMENDATION']
                    quick_sell = "STRONG_SELL" in a_high.summary['RECOMMENDATION'] and "SELL" in a_small.summary['RECOMMENDATION']

                if quick_buy: label = "QUICK_BUY"
                elif quick_sell: label = "QUICK_SELL"
                elif all_buy: label = "ALIGNED_BUY"
                elif all_sell: label = "ALIGNED_SELL"

            # Dynamic Expiry matching the highest active timeframe
            enabled_tfs = []
            if tf_small: enabled_tfs.append(tf_small.value)
            if tf_mid: enabled_tfs.append(tf_mid.value)
            if tf_high: enabled_tfs.append(tf_high.value)

            if enabled_tfs:
                max_tf = max(enabled_tfs)
                if max_tf >= 86400: suggested_expiry = 1440
                elif max_tf >= 14400: suggested_expiry = 240
                elif max_tf >= 3600: suggested_expiry = 60
                elif max_tf >= 1800: suggested_expiry = 30
                elif max_tf >= 900: suggested_expiry = 15
                elif max_tf >= 300: suggested_expiry = 5
                else: suggested_expiry = 1
            else:
                suggested_expiry = 5

            if "QUICK" in label:
                suggested_expiry = max(1, suggested_expiry // 2)

            data = {
                'confidence': round(confidence, 1),
                'label': label,
                'signal': 'BUY' if 'BUY' in label else ('SELL' if 'SELL' in label else 'WAIT'),
                'desc': label,
                'summary_small': rec_small,
                'summary_mid': rec_mid,
                'summary_high': rec_high,
                'expiry_min': suggested_expiry,
                'atr': 0.0, # Placeholder or calculate if needed
                'last_update': time.time()
            }
            self.bot.screener_data[symbol] = data
            logging.info(f"Strategy 7 update for {symbol}: {label} (Expiry: {suggested_expiry}m)")
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
                    time.sleep(1.0) # Throttle symbol processing

                time.sleep(10)
