import time
import logging
import asyncio
import threading
import pandas as pd
import ta
from concurrent.futures import ThreadPoolExecutor
from handlers.ta_handler import get_ta_signal, get_ta_indicators, fetch_candles, manager
from handlers.utils import (
    calculate_snr_zones, check_price_action_patterns, score_reversal_pattern,
    predict_expiry_v5, calculate_echo_forecast, calculate_structural_rr, get_smart_targets,
    calculate_supertrend, calculate_fractals, calculate_order_blocks, detect_macd_divergence
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
            elif strat_key == 'strategy_1':
                return self.analyze_crossover_strategy(symbol, 1, "15m", 86400)
            elif strat_key == 'strategy_2':
                return self.analyze_crossover_strategy(symbol, 2, "3m", 3600)
            elif strat_key == 'strategy_3':
                return self.analyze_crossover_strategy(symbol, 3, "1m", 900)
            elif strat_key == 'strategy_4':
                return self.analyze_strategy_4(symbol)
            return None
        except Exception as e:
            logging.error(f"Screener error for {symbol}: {e}")
            return None

    def _get_smart_expiry(self, df_ltf, ltf_min, htf_min):
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

    def _calculate_scores(self, symbol, indicators, df):
        try:
            if df is None or df.empty:
                return 5.0, 5.0, 5.0, 5.0

            # 1. Trend Score (EMA alignment)
            ema20 = indicators.get('ema20', df['close'].ewm(span=20).mean().iloc[-1])
            ema50 = indicators.get('ema50', df['close'].ewm(span=50).mean().iloc[-1])
            price = df['close'].iloc[-1]
            trend = 5.0
            if price > ema20 > ema50: trend = 8.5
            elif price < ema20 < ema50: trend = 1.5

            # 2. Momentum Score (RSI)
            rsi = indicators.get('rsi', 50)
            momentum = round(rsi / 10, 1)

            # 3. Volatility Score (ATR vs MA)
            atr_series = ta.volatility.AverageTrueRange(df['high'], df['low'], df['close'], window=14).average_true_range()
            atr_curr = atr_series.iloc[-1]
            atr_avg = atr_series.rolling(50).mean().iloc[-1]
            volatility = round((atr_curr / atr_avg) * 5, 1) if atr_avg else 5.0

            # 4. Structure Score (Price Action)
            candles = []
            for _, row in df.tail(10).iterrows():
                candles.append({'open': row['open'], 'high': row['high'], 'low': row['low'], 'close': row['close']})
            pattern = check_price_action_patterns(candles)
            structure = 5.0
            if pattern:
                if "bullish" in pattern: structure = 7.5
                elif "bearish" in pattern: structure = 2.5

            return trend, momentum, volatility, structure
        except Exception as e:
            logging.error(f"Error calculating scores for {symbol}: {e}")
            return 0, 0, 0, 0

    def analyze_strategy_5(self, symbol):
        """Strategy 5: Synthetic Intelligence Screener (v5.3)"""
        try:
            # 1. Gather Data across multiple timeframes
            df1m = asyncio.run_coroutine_threadsafe(fetch_candles(symbol, "1m"), manager.loop).result()
            df5m = asyncio.run_coroutine_threadsafe(fetch_candles(symbol, "5m"), manager.loop).result()
            df1h = asyncio.run_coroutine_threadsafe(fetch_candles(symbol, "1h"), manager.loop).result()

            if df1m.empty or df5m.empty or df1h.empty: return None

            # Trend Block: EMA 50/200, SuperTrend, ADX
            ind1h = get_ta_indicators(symbol, "1h")
            ema50_1h = ind1h.get('ema50', 0)
            ema200_1h = ind1h.get('ema200', 0)
            adx_1h = ind1h.get('adx', 0)
            price_1h = ind1h.get('close', 0)

            st_val, st_dir = calculate_supertrend(df1h)
            st_curr = st_dir.iloc[-1] # 1 for UP, -1 for DOWN

            trend_score = 0
            if ema50_1h and ema200_1h:
                if price_1h > ema50_1h > ema200_1h: trend_score += 30
                elif price_1h < ema50_1h < ema200_1h: trend_score -= 30

            if st_curr == 1: trend_score += 10
            else: trend_score -= 10

            if adx_1h > 25: trend_score *= 1.2 # Strength boost

            # Momentum Block: RSI, Stoch RSI, MACD Divergence
            ind5m = get_ta_indicators(symbol, "5m")
            rsi_5m = ind5m.get('rsi', 50)
            stoch_k_5m = ind5m.get('stoch_k', 50)
            macd_div = detect_macd_divergence(df5m)

            mom_score = 0
            if rsi_5m > 50: mom_score += 10
            else: mom_score -= 10

            if stoch_k_5m > 50: mom_score += 10
            else: mom_score -= 10

            if macd_div == 1: mom_score += 15
            elif macd_div == -1: mom_score -= 15

            # Volatility Block: ATR, Bollinger Bands
            bb_h = ind5m.get('bb_h', 0)
            bb_l = ind5m.get('bb_l', 0)
            vol_score = 0
            if price_1h > bb_h: vol_score += 5
            elif price_1h < bb_l: vol_score -= 5

            # Structure Block: 5m Fractals (Scalp) or 1H Order Blocks (Multiplier)
            is_multiplier = self.bot.config.get('contract_type') == 'multiplier'
            struct_score = 0
            if is_multiplier:
                obs = calculate_order_blocks(df1h)
                for ob in obs:
                    if ob['type'] == 'Bullish OB' and abs(price_1h - ob['price'])/ob['price'] < 0.005:
                        struct_score += 20
                    elif ob['type'] == 'Bearish OB' and abs(price_1h - ob['price'])/ob['price'] < 0.005:
                        struct_score -= 20
            else:
                f_high, f_low = calculate_fractals(df5m)
                if f_low.iloc[-1]: struct_score += 15
                elif f_high.iloc[-1]: struct_score -= 15

            # Total Confidence Calculation
            total_raw = trend_score + mom_score + vol_score + struct_score
            confidence = min(100, abs(total_raw))
            direction = "CALL" if total_raw > 0 else "PUT"
            signal = "WAIT"

            # Adaptive Sensitivity
            sd = self.bot.symbol_data.get(symbol, {})
            loss_streak = sd.get('consecutive_losses', 0)

            threshold = 68 if is_multiplier else 72
            if loss_streak >= 3:
                threshold += (loss_streak - 2) * 5
                self.bot.log(f"Adaptive Sensitivity: Boosting Strategy 5 threshold to {threshold}% for {symbol} due to {loss_streak} losses.")

            if confidence >= threshold:
                signal = "BUY" if total_raw > 0 else "SELL"

            # 5. Echo Forecast (5m) validation
            fcast_prices, correlation = calculate_echo_forecast(df5m)
            fcast_data = {}
            if fcast_prices:
                fcast_final = fcast_prices[-1]
                if signal == "BUY" and fcast_final <= df5m['close'].iloc[-1]:
                    signal = "WAIT"
                elif signal == "SELL" and fcast_final >= df5m['close'].iloc[-1]:
                    signal = "WAIT"

                fcast_data = {
                    'final': fcast_final, 'correlation': correlation,
                    'forecast_prices': fcast_prices,
                    'high': max(fcast_prices), 'low': min(fcast_prices)
                }

            atr_val = ta.volatility.AverageTrueRange(df5m['high'], df5m['low'], df5m['close']).average_true_range().iloc[-1]
            expiry = predict_expiry_v5(symbol, 'strategy_5', 1, 60, confidence, fcast_data, df1m, direction=direction)

            tp_price, sl_price, rr = None, None, 0
            if signal != "WAIT":
                tp_price, sl_price = get_smart_targets(df1m['close'].iloc[-1], 'long' if signal == "BUY" else 'short', atr_val, confidence, fcast_data)
                rr = calculate_structural_rr(df1m['close'].iloc[-1], fcast_prices, signal, atr_val)

            data = {
                'tp': round(tp_price, 4) if tp_price else None,
                'sl': round(sl_price, 4) if sl_price else None,
                'rr': round(float(rr), 1),
                'signal': signal,
                'direction': direction,
                'confidence': round(float(confidence), 1),
                'threshold': threshold,
                'expiry_min': expiry,
                'atr': round(atr_val, 4),
                'trend': trend_score, 'momentum': mom_score, 'volatility': vol_score, 'structure': struct_score,
                'fcast_data': fcast_data,
                'last_update': time.time()
            }
            self.bot.screener_data[symbol] = data
            self.bot.emit('screener_update', {'symbol': symbol, 'data': data})
            return data
        except Exception as e:
            logging.error(f"Error in Strategy 5 analysis for {symbol}: {e}")
            return None

    def analyze_strategy_6(self, symbol):
        """Strategy 6: Intelligence Legacy (v5.3)"""
        try:
            # 1. Gather Data (1m, 1h, 4h)
            df1m = asyncio.run_coroutine_threadsafe(fetch_candles(symbol, "1m"), manager.loop).result()
            df1h = asyncio.run_coroutine_threadsafe(fetch_candles(symbol, "1h"), manager.loop).result()
            df4h = asyncio.run_coroutine_threadsafe(fetch_candles(symbol, "4h"), manager.loop).result()

            if df1m.empty or df1h.empty or df4h.empty: return None

            # Indicator Blocks with Weights: Trend (3), Momentum (2), Volatility (1), Structure (2)
            ind1h = get_ta_indicators(symbol, "1h")
            ind1m = get_ta_indicators(symbol, "1m")
            ind4h = get_ta_indicators(symbol, "4h")

            # Trend Score (Weight 3)
            trend_score = 0
            if ind1h.get('close') > ind1h.get('ema50'): trend_score += 1
            else: trend_score -= 1
            if ind4h.get('close') > ind4h.get('ema50'): trend_score += 1
            else: trend_score -= 1
            if ind1m.get('close') > ind1m.get('ema50'): trend_score += 1
            else: trend_score -= 1
            trend_final = trend_score * 3

            # Momentum Score (Weight 2)
            mom_score = 0
            if ind1h.get('rsi') > 50: mom_score += 1
            else: mom_score -= 1
            if ind1m.get('rsi') > 50: mom_score += 1
            else: mom_score -= 1
            mom_final = mom_score * 2

            # Volatility Score (Weight 1)
            vol_score = 0
            if ind1m.get('close') > ind1m.get('bb_h'): vol_score += 1
            elif ind1m.get('close') < ind1m.get('bb_l'): vol_score -= 1
            vol_final = vol_score * 1

            # Structure Score (Weight 2)
            struct_score = 0
            macd_div = detect_macd_divergence(df1h)
            if macd_div == 1: struct_score += 1
            elif macd_div == -1: struct_score -= 1
            struct_final = struct_score * 2

            # Normalize confidence (max possible absolute score is 3*3 + 2*2 + 1*1 + 1*2 = 9 + 4 + 1 + 2 = 16)
            total_score = trend_final + mom_final + vol_final + struct_final
            confidence = min(100, abs(total_score) / 16 * 100)

            direction = "CALL" if total_score > 0 else "PUT"
            signal = "WAIT"
            if confidence >= 60:
                signal = "BUY" if total_score > 0 else "SELL"

            # Echo Forecast validation
            fcast_prices, correlation = calculate_echo_forecast(df1h)
            fcast_data = {}
            if fcast_prices:
                fcast_final = fcast_prices[-1]
                if signal == "BUY" and fcast_final <= df1h['close'].iloc[-1]:
                    signal = "WAIT"
                elif signal == "SELL" and fcast_final >= df1h['close'].iloc[-1]:
                    signal = "WAIT"
                fcast_data = {'final': fcast_final, 'correlation': correlation, 'forecast_prices': fcast_prices}

            atr_val = ta.volatility.AverageTrueRange(df1h['high'], df1h['low'], df1h['close']).average_true_range().iloc[-1]
            expiry = predict_expiry_v5(symbol, 'strategy_6', 1, 15, confidence, fcast_data, df1m, direction=direction)

            tp_price, sl_price, rr = None, None, 0
            if signal != "WAIT":
                tp_price, sl_price = get_smart_targets(df1m['close'].iloc[-1], 'long' if signal == "BUY" else 'short', atr_val, confidence, fcast_data)
                rr = calculate_structural_rr(df1m['close'].iloc[-1], fcast_prices, signal, atr_val)

            data = {
                'tp': round(tp_price, 4) if tp_price else None,
                'sl': round(sl_price, 4) if sl_price else None,
                'rr': round(float(rr), 1),
                'signal': signal,
                'direction': direction,
                'confidence': round(float(confidence), 1),
                'threshold': 60,
                'expiry_min': expiry,
                'atr': round(atr_val, 4),
                'trend': trend_final, 'momentum': mom_final, 'volatility': vol_final, 'structure': struct_final,
                'fcast_data': fcast_data,
                'last_update': time.time()
            }
            self.bot.screener_data[symbol] = data
            self.bot.emit('screener_update', {'symbol': symbol, 'data': data})
            return data
        except Exception as e:
            logging.error(f"Error in Strategy 6 analysis for {symbol}: {e}")
            return None

    def update_strat7_analysis(self, symbol, config):
        tf_small_str = config.get('strat7_small_tf', '60')
        tf_mid_str = config.get('strat7_mid_tf', '300')
        tf_high_str = config.get('strat7_high_tf', '3600')

        def val_to_str(val):
            if val == 'OFF': return None
            val = int(val)
            if val == 60: return "1m"
            if val == 120: return "2m"
            if val == 180: return "3m"
            if val == 300: return "5m"
            if val == 600: return "10m"
            if val == 900: return "15m"
            if val == 1800: return "30m"
            if val == 3600: return "1h"
            if val == 86400: return "1d"
            return "1m"

        try:
            s_tf = val_to_str(tf_small_str)
            m_tf = val_to_str(tf_mid_str)
            h_tf = val_to_str(tf_high_str)

            rec_small = get_ta_signal(symbol, s_tf) if s_tf else "OFF"
            rec_mid = get_ta_signal(symbol, m_tf) if m_tf else "OFF"
            rec_high = get_ta_signal(symbol, h_tf) if h_tf else "OFF"

            active_recs = [r for r in [rec_small, rec_mid, rec_high] if r != "OFF"]

            label = "NEUTRAL"
            direction = "NEUTRAL"
            signal = "WAIT"

            if len(active_recs) == 1:
                rec = active_recs[0]
                if "BUY" in rec:
                    label = "ALIGNED_BUY"
                    direction = "CALL"
                    signal = "BUY"
                elif "SELL" in rec:
                    label = "ALIGNED_SELL"
                    direction = "PUT"
                    signal = "SELL"
            elif len(active_recs) > 1:
                all_buy = all("BUY" in r for r in active_recs)
                all_sell = all("SELL" in r for r in active_recs)

                # High TF check for QUICK signals
                high_rec = active_recs[-1]

                if all_buy:
                    label = "QUICK_BUY" if "STRONG" in high_rec else "ALIGNED_BUY"
                    direction = "CALL"
                    signal = "BUY"
                elif all_sell:
                    label = "QUICK_SELL" if "STRONG" in high_rec else "ALIGNED_SELL"
                    direction = "PUT"
                    signal = "SELL"

            df_ref = pd.DataFrame()
            ref_tf = "1h"
            if h_tf: ref_tf = h_tf
            elif m_tf: ref_tf = m_tf
            elif s_tf: ref_tf = s_tf

            df_ref = asyncio.run_coroutine_threadsafe(fetch_candles(symbol, ref_tf), manager.loop).result()
            indicators = get_ta_indicators(symbol, ref_tf)
            trend, momentum, volatility, structure = self._calculate_scores(symbol, indicators, df_ref)

            confidence = 80 if signal != "WAIT" else 0
            if signal != "WAIT" and "STRONG" in str(active_recs): confidence = 90

            # Echo Forecast Intelligence (Use Mid TF for Echo)
            df_echo = asyncio.run_coroutine_threadsafe(fetch_candles(symbol, m_tf or "5m"), manager.loop).result()
            fcast_prices, correlation = calculate_echo_forecast(df_echo)
            fcast_data = {'signals': {'small': rec_small, 'mid': rec_mid, 'high': rec_high}}
            if fcast_prices:
                fcast_final = fcast_prices[-1]
                if signal == 'BUY' and fcast_final > df_echo['close'].iloc[-1]:
                    confidence = min(100, confidence + (correlation * 10))
                elif signal == 'SELL' and fcast_final < df_echo['close'].iloc[-1]:
                    confidence = min(100, confidence + (correlation * 10))

                fcast_data.update({
                    'high': max(fcast_prices), 'low': min(fcast_prices),
                    'final': fcast_final, 'correlation': correlation,
                    'forecast_prices': fcast_prices
                })

            df_ltf = asyncio.run_coroutine_threadsafe(fetch_candles(symbol, s_tf or "1m"), manager.loop).result()
            expiry = predict_expiry_v5(symbol, 'strategy_7', 1, 60, confidence, fcast_data, df_ltf, direction=direction)

            atr_val = 0
            tp_price, sl_price, rr = None, None, 0
            if not df_ref.empty:
                atr_val = ta.volatility.AverageTrueRange(df_ref['high'], df_ref['low'], df_ref['close']).average_true_range().iloc[-1]
                price = df_ref['close'].iloc[-1]
                if signal != "WAIT":
                    tp_price, sl_price = get_smart_targets(price, 'long' if signal == 'BUY' else 'short', atr_val, confidence, fcast_data)
                    rr = calculate_structural_rr(price, fcast_data.get('forecast_prices', []), signal, atr_val)

            data = {
                'tp': round(tp_price, 4) if tp_price else None,
                'sl': round(sl_price, 4) if sl_price else None,
                'rr': round(float(rr), 1),
                'confidence': round(float(confidence), 1),
                'label': label,
                'direction': direction,
                'signal': signal,
                'desc': label,
                'summary_small': rec_small,
                'summary_mid': rec_mid,
                'summary_high': rec_high,
                'expiry_min': expiry,
                'atr': round(atr_val, 4),
                'trend': trend, 'momentum': momentum, 'volatility': volatility, 'structure': structure,
                'fcast_data': fcast_data,
                'last_update': time.time()
            }
            self.bot.screener_data[symbol] = data
            self.bot.emit('screener_update', {'symbol': symbol, 'data': data})
            return data
        except Exception as e:
            logging.error(f"Strategy 7 analysis error for {symbol}: {e}")
            return None

    def analyze_strategy_4(self, symbol):
        """Strategy 4: SNR Reversal + Echo Confirmation"""
        try:
            sd = self.bot.symbol_data.get(symbol, {})
            df1m = asyncio.run_coroutine_threadsafe(fetch_candles(symbol, "1m"), manager.loop).result()

            fcast_prices, correlation = calculate_echo_forecast(df1m)

            # Simple Echo Direction
            echo_dir = "NEUTRAL"
            if fcast_prices:
                echo_dir = "CALL" if fcast_prices[-1] > df1m['close'].iloc[-1] else "PUT"

            confidence = int(correlation * 100)
            fcast_data = {
                'forecast_prices': fcast_prices,
                'correlation': correlation
            }
            expiry = predict_expiry_v5(symbol, 'strategy_4', 1, 5, confidence, fcast_data, df1m, direction=echo_dir)

            data = {
                'signal': "WAIT",
                'direction': echo_dir,
                'desc': f"Echo Corr: {correlation:.2f} | PA Pattern: {check_price_action_patterns(sd.get('ltf_candles', []))}",
                'confidence': round(float(confidence), 1),
                'threshold': 50,
                'expiry_min': expiry,
                'trend_rec': echo_dir,
                'fcast_data': fcast_data,
                'last_update': time.time()
            }
            self.bot.screener_data[symbol] = data
            self.bot.emit('screener_update', {'symbol': symbol, 'data': data})
            return data
        except Exception as e:
            logging.error(f"Strategy 4 screener error: {e}")
            return None

    def analyze_crossover_strategy(self, symbol, strat_num, ta_interval, htf_sec):
        ta_signal = get_ta_signal(symbol, ta_interval)
        indicators = get_ta_indicators(symbol, ta_interval)

        sd = self.bot.symbol_data.get(symbol, {})
        htf_open = sd.get('htf_open')
        price = sd.get('last_tick', indicators.get('close', 0))

        direction = "NEUTRAL"
        if htf_open:
            direction = "CALL" if price > htf_open else "PUT"

        # Echo Confirmation
        df_ltf = asyncio.run_coroutine_threadsafe(fetch_candles(symbol, ta_interval), manager.loop).result()
        fcast_prices, correlation = calculate_echo_forecast(df_ltf)

        echo_conf = "WAIT"
        if fcast_prices:
            fcast_final = fcast_prices[-1]
            if direction == "CALL" and fcast_final > price: echo_conf = "Confirmed UP"
            elif direction == "PUT" and fcast_final < price: echo_conf = "Confirmed DOWN"
            else: echo_conf = "Not Confirmed"

        data = {
            'signal': ta_signal,
            'direction': direction,
            'desc': f"HTF Open: {htf_open} | Echo: {echo_conf} ({correlation:.2f})",
            'confidence': round(float(correlation * 100), 1),
            'threshold': 0,
            'expiry_min': htf_sec // 60,
            'trend_rec': ta_signal,
            'fcast_data': {
                'forecast_prices': fcast_prices,
                'correlation': correlation
            },
            'last_update': time.time()
        }
        self.bot.screener_data[symbol] = data
        self.bot.emit('screener_update', {'symbol': symbol, 'data': data})
        return data

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
