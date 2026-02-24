import time
import logging
import pandas as pd
import ta
from concurrent.futures import ThreadPoolExecutor
from handlers.ta_handler import DerivTA, Interval
from handlers.utils import (
    calculate_snr_zones, check_price_action_patterns, score_reversal_pattern
)

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

            ratio = atr_avg / atr_current

            if ltf_min == 1:
                suggested = 3 * ratio
                return max(1, min(5, int(round(suggested))))
            elif ltf_min == 5:
                suggested = 12 * ratio
                return max(5, min(20, int(round(suggested))))
            else:
                mid = (ltf_min + htf_min) / 2
                suggested = mid * ratio
                return max(ltf_min, min(htf_min * 3, int(round(suggested))))
        except:
            return htf_min

    def _calculate_scores(self, symbol, analysis, df):
        """Calculate detailed scores for the UI."""
        try:
            # 1. Trend Score
            ma = analysis.moving_averages
            t_total = ma['BUY'] + ma['SELL'] + ma['NEUTRAL']
            trend = round((ma['BUY'] - ma['SELL']) / t_total * 10, 1) if t_total > 0 else 0

            # 2. Momentum Score
            osc = analysis.oscillators
            o_total = osc['BUY'] + osc['SELL'] + osc['NEUTRAL']
            momentum = round((osc['BUY'] - osc['SELL']) / o_total * 10, 1) if o_total > 0 else 0

            # 3. Volatility Score
            atr_series = ta.volatility.AverageTrueRange(df['high'], df['low'], df['close'], window=14).average_true_range()
            atr_curr = atr_series.iloc[-1]
            atr_avg = atr_series.rolling(50).mean().iloc[-1]
            volatility = round((atr_curr / atr_avg) * 5, 1) if atr_avg else 0

            # 4. Structure Score (Price Action + SNR)
            sd = self.bot.symbol_data.get(symbol, {})
            if not sd.get('snr_zones'):
                sd['snr_zones'] = calculate_snr_zones(symbol, sd)

            zones = sd.get('snr_zones', [])
            price = df['close'].iloc[-1]

            # Base score on SNR proximity
            snr_score = 0
            closest_zone = None
            if zones:
                min_dist = 99999
                for z in zones:
                    dist = abs(price - z['price']) / price
                    if dist < min_dist:
                        min_dist = dist
                        closest_zone = z
                snr_score = max(0, (0.005 - min_dist) / 0.005 * 5) # Up to 5 points for SNR proximity

            # Price Action Pattern Detection
            candles = []
            for idx, row in df.iterrows():
                candles.append({
                    'open': row['open'], 'high': row['high'], 'low': row['low'], 'close': row['close'], 'epoch': row['epoch']
                })

            pattern = check_price_action_patterns(candles)
            pa_score = 0
            if pattern and pattern != "marubozu":
                base_pa_val = score_reversal_pattern(symbol, pattern, candles)
                # Boost if pattern matches zone type
                if closest_zone and min_dist < 0.002:
                    if pattern.startswith('bullish') and closest_zone['type'] in ['S', 'Flip']:
                        pa_score = base_pa_val * 2
                    elif pattern.startswith('bearish') and closest_zone['type'] in ['R', 'Flip']:
                        pa_score = base_pa_val * 2
                    else:
                        pa_score = base_pa_val
                else:
                    pa_score = base_pa_val

            structure = round(min(10, snr_score + pa_score), 1)

            return trend, momentum, volatility, structure
        except Exception as e:
            logging.error(f"Error calculating scores for {symbol}: {e}")
            return 0, 0, 0, 0

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

            if "BUY" in rec1m and "BUY" in rec5m and "BUY" in rec1h:
                signal = "BUY"
                direction = "CALL"
                desc = "Triple EMA Alignment UP"
            elif "SELL" in rec1m and "SELL" in rec5m and "SELL" in rec1h:
                signal = "SELL"
                direction = "PUT"
                desc = "Triple EMA Alignment DOWN"

            df1m = h1m.get_dataframe()
            expiry = self._get_smart_expiry(df1m, 1, 60)

            trend, momentum, volatility, structure = self._calculate_scores(symbol, a5m, h5m.get_dataframe())
            confidence = round(abs(a5m.summary['BUY'] - a5m.summary['SELL']) / (a5m.summary['BUY'] + a5m.summary['SELL'] + a5m.summary['NEUTRAL']) * 100, 1)

            data = {
                'signal': signal,
                'direction': direction,
                'desc': desc,
                'confidence': confidence,
                'threshold': 72,
                'expiry_min': expiry,
                'atr_1m': round(ta.volatility.AverageTrueRange(df1m['high'], df1m['low'], df1m['close']).average_true_range().iloc[-1], 4),
                'trend': trend,
                'momentum': momentum,
                'volatility': volatility,
                'structure': structure,
                'last_update': time.time()
            }
            self.bot.screener_data[symbol] = data
            logging.info(f"Strategy 5 update for {symbol}: {data['direction']} | {data['signal']} | Expiry: {data['expiry_min']}m | Trend: {data['trend']} | Mom: {data['momentum']} | Vol: {data['volatility']} | Struct: {data['structure']}")
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
            trend_rec = a15m.summary['RECOMMENDATION']

            signal = "WAIT"
            direction = "NEUTRAL"
            desc = f"RSI: {rsi:.1f}, Trend: {trend_rec}"

            if rsi < 30 and "BUY" in trend_rec:
                signal = "BUY"
                direction = "CALL"
                desc = "RSI Oversold + Bullish Trend"
            elif rsi > 70 and "SELL" in trend_rec:
                signal = "SELL"
                direction = "PUT"
                desc = "RSI Overbought + Bearish Trend"

            df1m = h1m.get_dataframe()
            expiry = self._get_smart_expiry(df1m, 1, 15)

            trend, momentum, volatility, structure = self._calculate_scores(symbol, a15m, h15m.get_dataframe())
            confidence = round(abs(a15m.summary['BUY'] - a15m.summary['SELL']) / (a15m.summary['BUY'] + a15m.summary['SELL'] + a15m.summary['NEUTRAL']) * 100, 1)

            data = {
                'signal': signal,
                'direction': direction,
                'desc': desc,
                'confidence': confidence,
                'threshold': 60,
                'expiry_min': expiry,
                'atr_1m': round(ta.volatility.AverageTrueRange(df1m['high'], df1m['low'], df1m['close']).average_true_range().iloc[-1], 4),
                'trend': trend,
                'momentum': momentum,
                'volatility': volatility,
                'structure': structure,
                'rsi': round(rsi, 2),
                'trend_rec': trend_rec,
                'last_update': time.time()
            }
            self.bot.screener_data[symbol] = data
            logging.info(f"Strategy 6 update for {symbol}: {data['direction']} | {data['signal']} | Expiry: {data['expiry_min']}m | Trend: {data['trend']} | Mom: {data['momentum']} | Vol: {data['volatility']} | Struct: {data['structure']}")
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

            def filter_strong(rec):
                if rec == "STRONG_BUY": return "BUY"
                if rec == "STRONG_SELL": return "SELL"
                return rec

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

            enabled_handlers = []
            if h_small: enabled_handlers.append(h_small)
            if h_mid: enabled_handlers.append(h_mid)
            if h_high: enabled_handlers.append(h_high)

            label = "NEUTRAL"
            direction = "NEUTRAL"
            signal = "WAIT"

            # Sort handlers by interval to identify smallest/biggest correctly
            enabled_handlers.sort(key=lambda x: x.interval.value)
            recs = [h.get_analysis().summary['RECOMMENDATION'] for h in enabled_handlers]

            if len(enabled_handlers) == 1:
                # IN ONE TIMEFRAME IGNORE STRONG BU AND STONG SELL (treat them as BUY/SELL)
                rec = recs[0]
                if "BUY" in rec:
                    label = "ALIGNED_BUY"
                    direction = "CALL"
                    signal = "BUY"
                elif "SELL" in rec:
                    label = "ALIGNED_SELL"
                    direction = "PUT"
                    signal = "SELL"

                # Update individual TF summaries to hide STRONG for 1-TF mode
                rec_small = filter_strong(rec_small)
                rec_mid = filter_strong(rec_mid)
                rec_high = filter_strong(rec_high)
            elif len(enabled_handlers) > 1:
                biggest_rec = recs[-1]
                smaller_recs = recs[:-1]

                all_buy = all("BUY" in r for r in recs)
                all_sell = all("SELL" in r for r in recs)

                if all_buy:
                    if "STRONG" in biggest_rec:
                        label = "QUICK_BUY"
                    else:
                        label = "ALIGNED_BUY"
                    direction = "CALL"
                    signal = "BUY"
                elif all_sell:
                    if "STRONG" in biggest_rec:
                        label = "QUICK_SELL"
                    else:
                        label = "ALIGNED_SELL"
                    direction = "PUT"
                    signal = "SELL"

            mid_atr_val = 0.0
            trend = momentum = volatility = structure = 0
            if enabled_handlers:
                min_tf_val = min(h.interval.value for h in enabled_handlers) // 60
                max_tf_val = max(h.interval.value for h in enabled_handlers) // 60
                ref_htf = max_tf_val

                target_h = enabled_handlers[0]
                expiry = self._get_smart_expiry(target_h.get_dataframe(), min_tf_val, ref_htf)

                h_ref = h_mid or target_h
                df_ref = h_ref.get_dataframe()
                mid_atr_val = round(ta.volatility.AverageTrueRange(df_ref['high'], df_ref['low'], df_ref['close']).average_true_range().iloc[-1], 4)

                trend, momentum, volatility, structure = self._calculate_scores(symbol, enabled_handlers[-1].get_analysis(), enabled_handlers[-1].get_dataframe())
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
                'atr': mid_atr_val,
                'trend': trend,
                'momentum': momentum,
                'volatility': volatility,
                'structure': structure,
                'last_update': time.time()
            }
            self.bot.screener_data[symbol] = data
            logging.info(f"Strategy 7 update for {symbol}: {data['direction']} | {data['signal']} | Expiry: {data['expiry_min']}m | Label: {data['label']}")
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
