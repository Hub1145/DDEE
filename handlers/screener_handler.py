import time
import logging
import pandas as pd
import ta
import numpy as np
from datetime import datetime, timezone
from concurrent.futures import ThreadPoolExecutor
from handlers.ta_handler import DerivTA, Interval
from handlers.utils import (
    calculate_supertrend, calculate_fractals, calculate_order_blocks,
    calculate_fvg, detect_macd_divergence, calculate_adr
)

class ScreenerHandler:
    def __init__(self, bot_engine):
        self.bot = bot_engine
        self.stop_event = bot_engine.stop_event

    def update_screener(self, symbol):
        strat_key = self.bot.config.get('active_strategy', 'strategy_1')
        if strat_key == 'strategy_6':
            return self._update_screener_v1(symbol)

        with self.bot.data_lock:
            sd = self.bot.symbol_data.get(symbol)
            if not sd: return

            # Create copies for thread-safe processing
            m5_candles = list(sd.get('m5_candles', []))
            m15_candles = list(sd.get('m15_candles', []))
            htf_candles = list(sd.get('htf_candles', []))
            ltf_candles = list(sd.get('ltf_candles', []))
            daily_candles = list(sd.get('daily_candles', []))
            snr_zones = list(sd.get('snr_zones', []))

        contract_type = self.bot.config.get('contract_type', 'rise_fall')
        is_multiplier = (contract_type == 'multiplier')

        # Select Base Dataframe
        df_core = None
        if is_multiplier:
            if len(htf_candles) < 100: return
            df_core = pd.DataFrame(htf_candles)
            # Calculate 1H Order Blocks & FVGs
            obs = calculate_order_blocks(df_core)
            fvgs = calculate_fvg(df_core)
            with self.bot.data_lock:
                sd['order_blocks'] = obs
                sd['fvgs'] = fvgs
        else:
            if len(m5_candles) < 100: return
            df_core = pd.DataFrame(m5_candles)
            # Calculate 5m Fractals
            f_high, f_low = calculate_fractals(df_core)
            with self.bot.data_lock:
                sd['fractal_highs'] = df_core['high'][f_high].tolist()
                sd['fractal_lows'] = df_core['low'][f_low].tolist()

        last_close = df_core['close'].iloc[-1]

        # --- 0. SESSION & INSTRUMENT CONTEXT ---
        now_utc = datetime.now(timezone.utc)
        hour = now_utc.hour
        is_dead_hours = (hour >= 22 or hour < 6)
        session_threshold_bonus = 5 if is_dead_hours else 0

        # --- 1. TREND BLOCK ---
        t_pos, t_neg = 0, 0
        ema50 = ta.trend.EMAIndicator(df_core['close'], window=50).ema_indicator().iloc[-1]
        ema200 = ta.trend.EMAIndicator(df_core['close'], window=200).ema_indicator().iloc[-1]

        if last_close > ema50: t_pos += 1
        else: t_neg += 1
        if ema50 > ema200: t_pos += 1
        else: t_neg += 1

        st, st_dir = calculate_supertrend(df_core)
        if st_dir.iloc[-1] == 1: t_pos += 2
        else: t_neg += 2

        adx_val = ta.trend.ADXIndicator(df_core['high'], df_core['low'], df_core['close']).adx().iloc[-1]
        if adx_val > 25:
            if last_close > ema50: t_pos += 1
            else: t_neg += 1

        trend_score = (t_pos - t_neg) / (t_pos + t_neg) if (t_pos + t_neg) > 0 else 0

        # --- 2. MOMENTUM BLOCK ---
        m_pos, m_neg = 0, 0
        rsi = ta.momentum.RSIIndicator(df_core['close']).rsi().iloc[-1]
        if rsi > 50: m_pos += 1
        else: m_neg += 1

        stoch_rsi_ind = ta.momentum.StochRSIIndicator(df_core['close'])
        srsi_k = stoch_rsi_ind.stochrsi_k().iloc[-1]
        srsi_d = stoch_rsi_ind.stochrsi_d().iloc[-1]
        if srsi_k > 0.5: m_pos += 1
        else: m_neg += 1
        if srsi_k > srsi_d: m_pos += 1
        else: m_neg += 1

        div = detect_macd_divergence(df_core)
        if div == 1: m_pos += 2
        elif div == -1: m_neg += 2

        mom_score = (m_pos - m_neg) / (m_pos + m_neg) if (m_pos + m_neg) > 0 else 0

        # --- 3. VOLATILITY BLOCK ---
        v_pos, v_neg = 0, 0
        bb = ta.volatility.BollingerBands(df_core['close'])
        if last_close > bb.bollinger_mavg().iloc[-1]: v_pos += 1
        else: v_neg += 1

        if last_close > bb.bollinger_hband().iloc[-1]: v_pos += 1
        elif last_close < bb.bollinger_lband().iloc[-1]: v_neg += 1

        vol_score = (v_pos - v_neg) / (v_pos + v_neg) if (v_pos + v_neg) > 0 else 0

        # --- 4. STRUCTURE BLOCK ---
        s_pos, s_neg = 0, 0
        dist = (last_close - ema50) / ema50
        if abs(dist) < 0.05: s_pos += 1
        else: s_neg += 1

        if is_multiplier:
            obs = sd.get('order_blocks', [])
            fvgs = sd.get('fvgs', [])
            ob_hit = None
            for ob in obs:
                if abs(last_close - ob['price']) / ob['price'] < 0.005:
                    ob_hit = ob
                    break
            fvg_hit = None
            for fvg in fvgs:
                if last_close >= fvg['bottom'] and last_close <= fvg['top']:
                    fvg_hit = fvg
                    break
            if ob_hit and fvg_hit:
                if ob_hit['type'].startswith('Bullish') and fvg_hit['type'].startswith('Bullish'): s_pos += 5
                elif ob_hit['type'].startswith('Bearish') and fvg_hit['type'].startswith('Bearish'): s_neg += 5
            elif ob_hit:
                if ob_hit['type'].startswith('Bullish'): s_pos += 3
                else: s_neg += 3
            elif fvg_hit:
                if fvg_hit['type'].startswith('Bullish'): s_pos += 1
                else: s_neg += 1
        else:
            f_highs = sd.get('fractal_highs', [])[-5:]
            f_lows = sd.get('fractal_lows', [])[-5:]
            for fh in f_highs:
                if abs(last_close - fh) / fh < 0.002: s_neg += 3
            for fl in f_lows:
                if abs(last_close - fl) / fl < 0.002: s_pos += 3

        for z in snr_zones:
            if abs(last_close - z['price']) / z['price'] < 0.005:
                if z['type'] in ['S', 'Flip']: s_pos += 2
                elif z['type'] in ['R', 'Flip']: s_neg += 2

        struct_score = (s_pos - s_neg) / (s_pos + s_neg) if (s_pos + s_neg) > 0 else 0

        # --- FINAL CONFIDENCE ---
        if adx_val > 25:
            regime_type = "Trending"
            confidence = (trend_score * 40) + (vol_score * 40) + (struct_score * 20)
        elif adx_val < 20:
            regime_type = "Ranging"
            confidence = (mom_score * 40) + (struct_score * 40) + (vol_score * 20)
        else:
            regime_type = "Mixed"
            if is_multiplier:
                confidence = (trend_score * 40) + (vol_score * 30) + (struct_score * 20) + (mom_score * 10)
            else:
                confidence = (struct_score * 35) + (mom_score * 35) + (vol_score * 20) + (trend_score * 10)

        atr_val = ta.volatility.AverageTrueRange(df_core['high'], df_core['low'], df_core['close']).average_true_range().iloc[-1]
        atr_1m = 0
        if ltf_candles:
            df_1m = pd.DataFrame(ltf_candles)
            if len(df_1m) >= 14:
                atr_1m = ta.volatility.AverageTrueRange(df_1m['high'], df_1m['low'], df_1m['close']).average_true_range().iloc[-1]

        suggested_multiplier = 10
        if is_multiplier:
            rel_atr = atr_val / last_close
            if rel_atr >= 0.008 and adx_val > 30: suggested_multiplier = 50
            elif rel_atr >= 0.005 and adx_val > 25: suggested_multiplier = 20
            elif rel_atr >= 0.003 and adx_val > 20: suggested_multiplier = 10
            else: suggested_multiplier = 5
            if is_dead_hours: suggested_multiplier = min(suggested_multiplier, 10)

        suggested_expiry = 5
        if abs(confidence) > 75: suggested_expiry = 15
        elif abs(confidence) > 60: suggested_expiry = 10

        streak = sd.get('consecutive_losses', 0)
        base_threshold = 72 if not is_multiplier else 68
        adaptive_threshold = base_threshold + session_threshold_bonus
        if streak >= 3: adaptive_threshold += 10

        atr_24h = 0
        if len(htf_candles) >= 24:
            df_24h = pd.DataFrame(htf_candles[-24:])
            atr_24h = ta.volatility.AverageTrueRange(df_24h['high'], df_24h['low'], df_24h['close']).average_true_range().iloc[-1]

        self.bot.screener_data[symbol] = {
            'confidence': round(confidence, 1),
            'threshold': adaptive_threshold,
            'streak': streak,
            'direction': 'CALL' if confidence > 0 else 'PUT',
            'regime': regime_type,
            'trend': round(trend_score, 1),
            'momentum': round(mom_score, 1),
            'volatility': round(vol_score, 1),
            'structure': round(struct_score, 1),
            'adx': round(adx_val, 1),
            'srsi_k': round(srsi_k, 4),
            'atr': round(atr_val, 4),
            'atr_1m': round(atr_1m, 6),
            'atr_24h': round(atr_24h, 6),
            'is_dead_hours': is_dead_hours,
            'expiry_min': suggested_expiry,
            'multiplier': suggested_multiplier,
            'st_dir': st_dir.iloc[-1],
            'last_update': time.time()
        }
        self.bot.emit('screener_update', {'symbol': symbol, 'data': self.bot.screener_data[symbol]})

    def _update_screener_v1(self, symbol):
        with self.bot.data_lock:
            sd = self.bot.symbol_data.get(symbol)
            if not sd: return
            htf_candles = list(sd.get('htf_candles', [])) # 1H Macro Bias
            m15_candles = list(sd.get('m15_candles', [])) # 15m Trend
            daily_candles = list(sd.get('daily_candles', []))
            snr_zones = list(sd.get('snr_zones', []))

        if len(m15_candles) < 200: return

        df_h = pd.DataFrame(m15_candles) # Using 15m for Core Analysis smoothing
        df_macro = pd.DataFrame(htf_candles) # 1H for Bias
        last_close = df_h['close'].iloc[-1]

        # --- v4.0 Dimensionality Reduction ---
        t_signals = []
        ema50 = ta.trend.EMAIndicator(df_h['close'], window=50).ema_indicator().iloc[-1]
        ema200 = ta.trend.EMAIndicator(df_h['close'], window=200).ema_indicator().iloc[-1]
        sma20 = ta.trend.SMAIndicator(df_h['close'], window=20).sma_indicator().iloc[-1]

        if last_close > ema50: t_signals.append(1)
        else: t_signals.append(-1)
        if ema50 > ema200: t_signals.append(1)
        else: t_signals.append(-1)
        if last_close > sma20: t_signals.append(1)
        else: t_signals.append(-1)

        adx_ind = ta.trend.ADXIndicator(df_h['high'], df_h['low'], df_h['close'])
        adx = adx_ind.adx().iloc[-1]
        if adx > 25:
            if last_close > ema50: t_signals.append(1)
            else: t_signals.append(-1)

        ichimoku = ta.trend.IchimokuIndicator(df_h['high'], df_h['low'])
        span_a = ichimoku.ichimoku_a().iloc[-1]
        span_b = ichimoku.ichimoku_b().iloc[-1]
        if last_close > span_a and last_close > span_b: t_signals.append(1)
        elif last_close < span_a and last_close < span_b: t_signals.append(-1)

        macd_ind = ta.trend.MACD(df_h['close'])
        if macd_ind.macd().iloc[-1] > macd_ind.macd_signal().iloc[-1]: t_signals.append(1)
        else: t_signals.append(-1)

        trend_sentiment = sum(t_signals) / len(t_signals) if t_signals else 0
        trend_score = trend_sentiment * 3

        # --- MOMENTUM BLOCK ---
        m_signals = []
        rsi = ta.momentum.RSIIndicator(df_h['close']).rsi().iloc[-1]
        if rsi > 50: m_signals.append(1)
        else: m_signals.append(-1)

        stoch_rsi = ta.momentum.StochRSIIndicator(df_h['close']).stochrsi_k().iloc[-1]
        if stoch_rsi > 0.5: m_signals.append(1)
        else: m_signals.append(-1)

        wr = ta.momentum.WilliamsRIndicator(df_h['high'], df_h['low'], df_h['close']).williams_r().iloc[-1]
        if wr > -50: m_signals.append(1)
        else: m_signals.append(-1)

        roc = ta.momentum.ROCIndicator(df_h['close']).roc().iloc[-1]
        if roc > 0: m_signals.append(1)
        else: m_signals.append(-1)

        cci = ta.trend.CCIIndicator(df_h['high'], df_h['low'], df_h['close']).cci().iloc[-1]
        if cci > 0: m_signals.append(1)
        else: m_signals.append(-1)

        mom_sentiment = sum(m_signals) / len(m_signals) if m_signals else 0
        mom_score = mom_sentiment * 2

        # --- VOLATILITY BLOCK ---
        v_pos, v_neg = 0, 0
        atr_ind = ta.volatility.AverageTrueRange(df_h['high'], df_h['low'], df_h['close'])
        atr = atr_ind.average_true_range().iloc[-1]
        atr_prev = atr_ind.average_true_range().iloc[-2]
        if atr > atr_prev: v_pos += 0.5

        bb = ta.volatility.BollingerBands(df_h['close'])
        bbw = (bb.bollinger_hband().iloc[-1] - bb.bollinger_lband().iloc[-1]) / bb.bollinger_mavg().iloc[-1]
        if bbw > 0: v_pos += 0.5 # Simplified

        vol_sentiment = (v_pos - v_neg) / (v_pos + v_neg) if (v_pos + v_neg) > 0 else 0
        vol_score = vol_sentiment * 1

        # --- STRUCTURE BLOCK ---
        s_pos, s_neg = 0, 0
        dist = (last_close - ema50) / ema50
        if abs(dist) < 0.05: s_pos += 1
        elif abs(dist) > 0.1: s_neg += 0.5

        struct_sentiment = (s_pos - s_neg) / (s_pos + s_neg) if (s_pos + s_neg) > 0 else 0
        struct_score = struct_sentiment * 2

        raw_sum = trend_score + mom_score + vol_score + struct_score
        confidence = (raw_sum / 8.0) * 100

        abs_conf = abs(confidence)
        suggested_expiry = 5
        if abs_conf >= 70: suggested_expiry = 15
        elif abs_conf >= 55: suggested_expiry = 10

        suggested_multiplier = 5
        if abs_conf >= 80: suggested_multiplier = 50
        elif abs_conf >= 65: suggested_multiplier = 20

        atr_1m = 0
        if not df_h.empty:
            atr_1m = ta.volatility.AverageTrueRange(df_h['high'], df_h['low'], df_h['close']).average_true_range().iloc[-1]

        self.bot.screener_data[symbol] = {
            'confidence': round(confidence, 1),
            'direction': 'CALL' if confidence > 0 else 'PUT',
            'regime': "Trending" if adx > 25 else "Ranging",
            'trend': round(trend_score, 1),
            'momentum': round(mom_score, 1),
            'volatility': round(vol_score, 1),
            'structure': round(struct_score, 1),
            'adx': round(adx, 1),
            'atr_1m': round(atr_1m, 6),
            'expiry_min': suggested_expiry,
            'multiplier': suggested_multiplier,
            'last_update': time.time()
        }
        self.bot.emit('screener_update', {'symbol': symbol, 'data': self.bot.screener_data[symbol]})

    def update_strat7_analysis(self, symbol):
        tf_small_val = self.bot.config.get('strat7_small_tf', '60')
        tf_mid_val = self.bot.config.get('strat7_mid_tf', '300')
        tf_high_val = self.bot.config.get('strat7_high_tf', '3600')

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

            # Use a shared cache or throttle to avoid rate limits
            if tf_small:
                h_small = DerivTA(symbol=symbol, interval=tf_small)
                a_small = h_small.get_analysis()
                time.sleep(0.5) # Throttle

            if tf_mid:
                h_mid = DerivTA(symbol=symbol, interval=tf_mid)
                a_mid = h_mid.get_analysis()
                time.sleep(0.5) # Throttle

            if tf_high:
                h_high = DerivTA(symbol=symbol, interval=tf_high)
                a_high = h_high.get_analysis()
                time.sleep(0.5) # Throttle

            self.bot.strat7_cache[symbol] = {
                'small': a_small,
                'mid': a_mid,
                'high': a_high,
                'timestamp': time.time()
            }

            # Handle OFF timeframes in alignment logic
            rec_small = a_small.summary['RECOMMENDATION'] if a_small else "NEUTRAL"
            rec_mid = a_mid.summary['RECOMMENDATION'] if a_mid else "NEUTRAL"
            rec_high = a_high.summary['RECOMMENDATION'] if a_high else "NEUTRAL"

            # ADR Guard
            sd = self.bot.symbol_data.get(symbol, {})
            adr = calculate_adr(sd.get('daily_candles', []))
            today_range = 0
            if sd.get('daily_candles'):
                tc = sd['daily_candles'][-1]
                today_range = tc['high'] - tc['low']

            over_adr = adr > 0 and today_range > adr

            # Confidence based on Alignment (excluding OFF)
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

            mid_atr = 0
            if a_mid:
                df_mid = h_mid.get_dataframe()
                mid_atr = ta.volatility.AverageTrueRange(df_mid['high'], df_mid['low'], df_mid['close']).average_true_range().iloc[-1]

            # Identify highest and lowest enabled timeframes
            enabled_analyses = []
            if tf_small: enabled_analyses.append(('small', a_small))
            if tf_mid: enabled_analyses.append(('mid', a_mid))
            if tf_high: enabled_analyses.append(('high', a_high))

            highest_analysis = enabled_analyses[-1][1] if enabled_analyses else None
            lowest_analysis = enabled_analyses[0][1] if enabled_analyses else None

            # All enabled Buy/Sell check
            all_buy = all("BUY" in a.summary['RECOMMENDATION'] for name, a in enabled_analyses) if enabled_analyses else False
            all_sell = all("SELL" in a.summary['RECOMMENDATION'] for name, a in enabled_analyses) if enabled_analyses else False

            # Quick entry/exit logic
            quick_buy = False
            quick_sell = False
            if highest_analysis and lowest_analysis:
                quick_buy = "STRONG_BUY" in highest_analysis.summary['RECOMMENDATION'] and "BUY" in lowest_analysis.summary['RECOMMENDATION']
                quick_sell = "STRONG_SELL" in highest_analysis.summary['RECOMMENDATION'] and "SELL" in lowest_analysis.summary['RECOMMENDATION']

            # Pullback Detection
            is_pullback_buy = ("BUY" in rec_high if tf_high else True) and \
                              ("BUY" in rec_mid if tf_mid else True) and \
                              (("SELL" in rec_small or "NEUTRAL" in rec_small) if tf_small else False)

            is_pullback_sell = ("SELL" in rec_high if tf_high else True) and \
                               ("SELL" in rec_mid if tf_mid else True) and \
                               (("BUY" in rec_small or "NEUTRAL" in rec_small) if tf_small else False)

            label = "NEUTRAL"
            suggested_expiry = 5

            if len(enabled_analyses) == 1:
                name, a = enabled_analyses[0]
                rec = a.summary['RECOMMENDATION']
                # Buy on BUY, Sell on SELL, skip STRONG
                if rec == "BUY": label = "ALIGNED_BUY"
                elif rec == "SELL": label = "ALIGNED_SELL"

                # Match expiry to the single enabled timeframe
                tf_val = int(self.bot.config.get(f'strat7_{name}_tf', 60))
                suggested_expiry = tf_val // 60
            else:
                if quick_buy: label = "QUICK_BUY"
                elif quick_sell: label = "QUICK_SELL"
                elif all_buy: label = "ALIGNED_BUY"
                elif all_sell: label = "ALIGNED_SELL"
                elif is_pullback_buy: label = "PULLBACK_BUY"
                elif is_pullback_sell: label = "PULLBACK_SELL"

                # Suggested expiry for multi-TF (based on mid TF if enabled, else highest)
                if tf_mid:
                    if tf_mid.value >= 3600: suggested_expiry = 60
                    elif tf_mid.value >= 900: suggested_expiry = 15
                    elif tf_mid.value >= 300: suggested_expiry = 5
                elif tf_high:
                    if tf_high.value >= 86400: suggested_expiry = 1440
                    elif tf_high.value >= 3600: suggested_expiry = 60

                # Reduce expiry for quick entries
                if quick_buy or quick_sell:
                    suggested_expiry = max(1, suggested_expiry // 2)

            self.bot.screener_data[symbol] = {
                'confidence': round(confidence, 1),
                'label': label,
                'direction': 'CALL' if ("BUY" in rec_high if tf_high else (confidence > 0)) else 'PUT',
                'over_adr': over_adr,
                'regime': rec_mid,
                'summary_small': rec_small if tf_small else "OFF",
                'summary_mid': rec_mid if tf_mid else "OFF",
                'summary_high': rec_high if tf_high else "OFF",
                'atr': round(mid_atr, 4),
                'expiry_min': suggested_expiry,
                'last_update': time.time()
            }
            self.bot.emit('screener_update', {'symbol': symbol, 'data': self.bot.screener_data[symbol]})

        except Exception as e:
            logging.error(f"Strategy 7 update error for {symbol}: {e}")

    def background_loop(self):
        with ThreadPoolExecutor(max_workers=5) as executor:
            while not self.stop_event.is_set():
                strat_key = self.bot.config.get('active_strategy')
                symbols = self.bot.config.get('symbols', [])

                if strat_key == 'strategy_7':
                    for symbol in symbols:
                        if self.stop_event.is_set(): break
                        executor.submit(self.update_strat7_analysis, symbol)
                        time.sleep(2.0)
                elif strat_key in ['strategy_5', 'strategy_6']:
                    for symbol in symbols:
                        if self.stop_event.is_set(): break
                        executor.submit(self.update_screener, symbol)
                        time.sleep(0.5)

                sleep_time = 30 if strat_key == 'strategy_7' else 10
                for _ in range(sleep_time):
                    if self.stop_event.is_set(): break
                    time.sleep(1)
