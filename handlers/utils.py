import pandas as pd
import ta
import numpy as np

def calculate_supertrend(df, period=10, multiplier=3):
    atr = ta.volatility.average_true_range(df['high'], df['low'], df['close'], window=period)
    hl2 = (df['high'] + df['low']) / 2
    upperband = hl2 + (multiplier * atr)
    lowerband = hl2 - (multiplier * atr)

    final_upperband = upperband.copy()
    final_lowerband = lowerband.copy()

    for i in range(1, len(df)):
        if upperband.iloc[i] < final_upperband.iloc[i-1] or df['close'].iloc[i-1] > final_upperband.iloc[i-1]:
            final_upperband.iloc[i] = upperband.iloc[i]
        else:
            final_upperband.iloc[i] = final_upperband.iloc[i-1]

        if lowerband.iloc[i] > final_lowerband.iloc[i-1] or df['close'].iloc[i-1] < final_lowerband.iloc[i-1]:
            final_lowerband.iloc[i] = lowerband.iloc[i]
        else:
            final_lowerband.iloc[i] = final_lowerband.iloc[i-1]

    supertrend = [0.0] * len(df)
    direction = [1] * len(df) # 1 for up, -1 for down

    for i in range(1, len(df)):
        if i == 1:
            supertrend[i] = final_upperband.iloc[i]
            direction[i] = -1
            continue
        if supertrend[i-1] == final_upperband.iloc[i-1]:
            if df['close'].iloc[i] > final_upperband.iloc[i]:
                supertrend[i] = final_lowerband.iloc[i]
                direction[i] = 1
            else:
                supertrend[i] = final_upperband.iloc[i]
                direction[i] = -1
        else:
            if df['close'].iloc[i] < final_lowerband.iloc[i]:
                supertrend[i] = final_upperband.iloc[i]
                direction[i] = -1
            else:
                supertrend[i] = final_lowerband.iloc[i]
                direction[i] = 1
    return pd.Series(supertrend), pd.Series(direction)

def calculate_fractals(df, window=2):
    if len(df) < 2 * window + 1: return pd.Series([False]*len(df)), pd.Series([False]*len(df))
    highs = df['high']
    lows = df['low']
    is_high = [False] * len(df)
    is_low = [False] * len(df)
    for i in range(window, len(df) - window):
        if all(highs.iloc[i] > highs.iloc[i-window:i]) and all(highs.iloc[i] > highs.iloc[i+1:i+window+1]):
            is_high[i] = True
        if all(lows.iloc[i] < lows.iloc[i-window:i]) and all(lows.iloc[i] < lows.iloc[i+1:i+window+1]):
            is_low[i] = True
    return pd.Series(is_high, index=df.index), pd.Series(is_low, index=df.index)

def calculate_order_blocks(df, lookback=100):
    if len(df) < lookback: return []
    obs = []
    for i in range(len(df) - 5, 5, -1):
        if i < 10: break
        avg_body = abs(df['close'].iloc[i-10:i] - df['open'].iloc[i-10:i]).mean()
        body = abs(df['close'].iloc[i] - df['open'].iloc[i])
        if body > 2 * avg_body:
            is_bullish_impulse = df['close'].iloc[i] > df['open'].iloc[i]
            for j in range(i-1, i-6, -1):
                if is_bullish_impulse and df['close'].iloc[j] < df['open'].iloc[j]:
                    obs.append({'price': df['low'].iloc[j], 'high': df['high'].iloc[j], 'type': 'Bullish OB', 'epoch': df['epoch'].iloc[j]})
                    break
                elif not is_bullish_impulse and df['close'].iloc[j] > df['open'].iloc[j]:
                    obs.append({'price': df['high'].iloc[j], 'low': df['low'].iloc[j], 'type': 'Bearish OB', 'epoch': df['epoch'].iloc[j]})
                    break
        if len(obs) >= 5: break
    return obs

def calculate_fvg(df, lookback=50):
    if len(df) < 3: return []
    fvgs = []
    for i in range(len(df) - 1, len(df) - lookback, -1):
        if i < 2: break
        if df['high'].iloc[i-2] < df['low'].iloc[i]:
            fvgs.append({'top': df['low'].iloc[i], 'bottom': df['high'].iloc[i-2], 'type': 'Bullish FVG', 'epoch': df['epoch'].iloc[i-1]})
        elif df['low'].iloc[i-2] > df['high'].iloc[i]:
            fvgs.append({'top': df['low'].iloc[i-2], 'bottom': df['high'].iloc[i], 'type': 'Bearish FVG', 'epoch': df['epoch'].iloc[i-1]})
        if len(fvgs) >= 10: break
    return fvgs

def detect_macd_divergence(df, window=20):
    if len(df) < window + 10: return 0
    macd_ind = ta.trend.MACD(df['close'])
    macd = macd_ind.macd()
    p_prev_low = df['close'].iloc[-2*window:-window].min()
    m_prev_low = macd.iloc[-2*window:-window].min()
    if df['close'].iloc[-1] < p_prev_low and macd.iloc[-1] > m_prev_low:
        return 1
    p_prev_high = df['close'].iloc[-2*window:-window].max()
    m_prev_high = macd.iloc[-2*window:-window].max()
    if df['close'].iloc[-1] > p_prev_high and macd.iloc[-1] < m_prev_high:
        return -1
    return 0

def check_price_action_patterns(candles):
    if len(candles) < 2: return None
    curr, prev = candles[-1], candles[-2]
    body = abs(curr['close'] - curr['open'])
    upper_wick = curr['high'] - max(curr['open'], curr['close'])
    lower_wick = min(curr['open'], curr['close']) - curr['low']
    total_range = curr['high'] - curr['low']
    if total_range == 0: return None
    if body > (total_range * 0.9): return "marubozu"
    if body < (total_range * 0.35):
        if lower_wick > (total_range * 0.6): return "bullish_pin"
        if upper_wick > (total_range * 0.6): return "bearish_pin"
    prev_body = abs(prev['close'] - prev['open'])
    if body > prev_body:
        if curr['close'] > curr['open'] and prev['close'] < prev['open']:
            if curr['close'] >= prev['open'] and curr['open'] <= prev['close']: return "bullish_engulfing"
        if curr['close'] < curr['open'] and prev['close'] > prev['open']:
            if curr['close'] <= prev['open'] and curr['open'] >= prev['close']: return "bearish_engulfing"
    if body < prev_body * 0.5:
        if max(curr['open'], curr['close']) <= max(prev['open'], prev['close']) and \
           min(curr['open'], curr['close']) >= min(prev['open'], prev['close']):
            return "bullish_harami" if curr['close'] > curr['open'] else "bearish_harami"
    if abs(curr['high'] - prev['high']) < (total_range * 0.05) and curr['high'] > max(curr['open'], curr['close']): return "tweezer_top"
    if abs(curr['low'] - prev['low']) < (total_range * 0.05) and curr['low'] < min(curr['open'], curr['close']): return "tweezer_bottom"
    if body < (total_range * 0.1): return "doji"
    return None

def calculate_adr(daily_candles, window=14):
    if len(daily_candles) < window: return 0
    ranges = [c['high'] - c['low'] for c in daily_candles[-window:]]
    return sum(ranges) / len(ranges)

def calculate_snr_zones(symbol, sd, granularity=None, active_strategy=None):
    if not sd: return []

    # v4.0 Zone Width Validation: Skip if > 1.5x ATR
    if granularity is None:
        if active_strategy == 'strategy_1': granularity = 86400
        elif active_strategy == 'strategy_2': granularity = 3600
        elif active_strategy == 'strategy_3': granularity = 900
        else: granularity = 3600

    candles = []
    if granularity == 3600: candles = sd.get('htf_candles', [])
    elif granularity == 900: candles = sd.get('m15_candles', [])
    elif granularity == 300: candles = sd.get('m5_candles', [])
    elif granularity == 86400: candles = sd.get('daily_candles', [])

    if len(candles) < 20: return sd.get('snr_zones', [])

    candles = candles[-100:]
    if len(candles) < 20: return sd.get('snr_zones', [])

    levels = []
    for i in range(1, len(candles) - 1):
        if candles[i]['high'] > candles[i-1]['high'] and candles[i]['high'] > candles[i+1]['high']:
            levels.append({'price': candles[i]['high'], 'type': 'R'})
        if candles[i]['low'] < candles[i-1]['low'] and candles[i]['low'] < candles[i+1]['low']:
            levels.append({'price': candles[i]['low'], 'type': 'S'})

    if not levels: return sd.get('snr_zones', [])
    avg_price = sum(c['close'] for c in candles) / len(candles)
    threshold = avg_price * 0.0005

    clusters = []
    for l in levels:
        found = False
        for c in clusters:
            if abs(l['price'] - c['price']) < threshold:
                c['prices'].append(l['price'])
                c['touches'] += 1
                if l['type'] != c['last_type']: c['is_flip'] = True
                c['last_type'] = l['type']
                found = True
                break
        if not found:
            clusters.append({'price': l['price'], 'touches': 1, 'is_flip': False, 'last_type': l['type'], 'prices': [l['price']]})

    active_zones = []
    for c in clusters:
        if c['touches'] >= 2:
            mean_price = sum(c['prices']) / len(c['prices'])
            active_zones.append({'price': mean_price, 'touches': c['touches'], 'is_flip': c['is_flip'], 'type': 'Flip' if c['is_flip'] else c['last_type']})

    final_zones = []
    for z in active_zones:
        old_zones = sd.get('snr_zones', [])
        for oz in old_zones:
            if abs(z['price'] - oz['price']) / oz['price'] < 0.001:
                z['total_lifetime_touches'] = oz.get('total_lifetime_touches', 0)
                break
        if 'total_lifetime_touches' not in z: z['total_lifetime_touches'] = z['touches']
        if z['total_lifetime_touches'] <= 5: final_zones.append(z)

    final_zones.sort(key=lambda x: x['touches'], reverse=True)
    return final_zones[:5]

def score_reversal_pattern(symbol, pattern, candles):
    if not candles: return 0
    c = candles[-1]
    prev = candles[-2] if len(candles) > 1 else None

    score = 0
    body = abs(c['close'] - c['open'])
    total_range = c['high'] - c['low']
    if total_range == 0: return 0

    # 1. Wick-to-body ratio (>2:1)
    upper_wick = c['high'] - max(c['open'], c['close'])
    lower_wick = min(c['open'], c['close']) - c['low']

    max_wick = max(upper_wick, lower_wick)
    if body > 0 and (max_wick / body) >= 2: score += 1
    elif body == 0: score += 1

    # 2. Close position within candle (top/bottom 25%)
    if pattern.startswith('bullish'):
        if c['close'] >= (c['low'] + total_range * 0.75): score += 1
    elif pattern.startswith('bearish'):
        if c['close'] <= (c['low'] + total_range * 0.25): score += 1
    elif pattern == 'doji': score += 1

    # 3. Prior candle strongly directional
    if prev:
        prev_body = abs(prev['close'] - prev['open'])
        prev_range = prev['high'] - prev['low']
        if prev_range > 0 and (prev_body / prev_range) > 0.6: score += 1

    return score

def get_smart_multiplier(atr_pct, base_multiplier=100):
    """
    Scale multiplier based on relative volatility (ATR as % of price).
    Low Volatility -> Higher Multiplier.
    High Volatility -> Lower Multiplier.
    """
    # Typical ATR% for indices might be 0.05% to 0.5%
    # If ATR% is 0.1%, use base.
    # If ATR% is 0.5%, use base/2.
    # If ATR% is 0.02%, use base*2.

    if atr_pct == 0: return base_multiplier

    # Target volatility index: 0.1% (0.001)
    scale = 0.001 / atr_pct
    multiplier = base_multiplier * scale

    # Constrain to sensible limits (e.g. 10x to 500x)
    return int(max(10, min(500, multiplier)))

def predict_expiry_v5(symbol, strategy_key, ltf_min, htf_min, confidence, fcast_data, df_ltf, direction='NEUTRAL'):
    """
    Expert Intelligence Expiry Engine (v5.1 Enhanced with Echo Arrival Logic).
    Predicts optimal duration based on the confidence that price will reach an ATR target
    within the forecasted structural window.
    """
    # 1. Base Intelligence from ATR Speed
    atr = 0
    curr_price = 0
    if df_ltf is not None and not df_ltf.empty:
        atr_series = ta.volatility.average_true_range(df_ltf['high'], df_ltf['low'], df_ltf['close'], window=14)
        atr = atr_series.iloc[-1]
        curr_price = df_ltf['close'].iloc[-1]

    base_expiry = 5
    if ltf_min: base_expiry = ltf_min * 3

    # 2. Echo Forecast Arrival Logic (v5.1)
    # We look for the exact candle where the forecast reaches our "Success Zone"
    if fcast_data and 'forecast_prices' in fcast_data and fcast_data.get('correlation', 0) > 0.5:
        prices = fcast_data['forecast_prices']

        # Define the target price point we are confident in reaching
        # High confidence -> reach further targets. Low confidence -> reach closer targets.
        target_dist = atr * (0.5 + (confidence / 100))

        arrival_index = -1
        if direction in ['CALL', 'BUY']:
            target_price = curr_price + target_dist
            for idx, p in enumerate(prices):
                if p >= target_price:
                    arrival_index = idx + 1
                    break
        elif direction in ['PUT', 'SELL']:
            target_price = curr_price - target_dist
            for idx, p in enumerate(prices):
                if p <= target_price:
                    arrival_index = idx + 1
                    break

        if arrival_index != -1:
            base_expiry = arrival_index
            if strategy_key in ['strategy_5', 'strategy_6']:
                base_expiry = base_expiry * (ltf_min or 1)
            return max(1, base_expiry)
        else:
            # If target not reached in forecast, find the most extreme point index
            try:
                if direction in ['CALL', 'BUY']:
                    base_expiry = prices.index(max(prices)) + 1
                elif direction in ['PUT', 'SELL']:
                    base_expiry = prices.index(min(prices)) + 1
            except:
                pass

            if strategy_key in ['strategy_5', 'strategy_6']:
                base_expiry = base_expiry * (ltf_min or 1)
            return max(1, base_expiry)

    # 3. Fallback Strategy-Specific Logic
    if strategy_key in ['strategy_5', 'strategy_6']:
        target_candles = 5 - int(4 * (confidence / 100))
        base_expiry = max(1, min(5, target_candles)) * (ltf_min or 1)

    elif strategy_key == 'strategy_7':
        signals = fcast_data.get('signals', {})
        s = signals.get('small', 'NEUTRAL')
        m = signals.get('mid', 'NEUTRAL')
        h = signals.get('high', 'NEUTRAL')

        if m != 'OFF' and s != 'OFF' and h == 'OFF':
            base_expiry = max(1, min(4, int(4 * (confidence/100)))) if "STRONG" in m else 5
        elif h != 'OFF' and m != 'OFF' and s != 'OFF':
            if "STRONG" in h and "STRONG" in m: base_expiry = max(1, min(4, int(5 * (1 - confidence/100))))
            elif "STRONG" in h: base_expiry = max(5, min(20, int(20 * (1 - confidence/100))))
            else: base_expiry = 30

    # Fine-tune Volatility
    if atr > 0 and df_ltf is not None and not df_ltf.empty:
        avg_atr = ta.volatility.average_true_range(df_ltf['high'], df_ltf['low'], df_ltf['close'], window=50).mean()
        if avg_atr > 0:
            ratio = atr / avg_atr
            if ratio > 1.5: base_expiry = max(1, int(base_expiry * 0.7))
            elif ratio < 0.5: base_expiry = int(base_expiry * 1.3)

    return max(1, base_expiry)

def calculate_structural_rr(current_price: float, forecast_prices: list, direction: str):
    """
    Calculates the Reward/Risk ratio based on the projected structural path.
    Reward = Distance to the projected extreme in signal direction.
    Risk = Distance to the projected opposite extreme (potential pullback/stop).
    """
    if not forecast_prices:
        return 1.0

    forecast_max = max(forecast_prices)
    forecast_min = min(forecast_prices)

    if direction.upper() in ["BUY", "CALL", "LONG"]:
        reward = forecast_max - current_price
        risk = current_price - forecast_min
    else:
        reward = current_price - forecast_min
        risk = forecast_max - current_price

    if risk <= 0:
        return 10.0 # High RR if no projected risk

    return reward / risk

def get_smart_targets(entry_price, side, atr, confidence, fcast_data=None):
    """
    Expert Intelligence TP/SL Engine (Enhanced with Echo Forecast).
    Uses ATR and Projected Market Structure to set optimal targets.
    """
    if atr == 0:
        return None, None

    is_long = side == 'long'

    # 1. Base ATR Risk (1.5x ATR for SL)
    sl_dist = 1.5 * atr

    # 2. Echo Structure Alignment
    # If forecast shows a clear structure peak/trough, we use it to cap or extend TP.
    fcast_tp_dist = 0
    if fcast_data and 'correlation' in fcast_data and fcast_data['correlation'] > 0.6:
        fcast_high = fcast_data.get('high')
        fcast_low = fcast_data.get('low')

        if is_long and fcast_high:
            fcast_tp_dist = fcast_high - entry_price
        elif not is_long and fcast_low:
            fcast_tp_dist = entry_price - fcast_low

    # 3. Dynamic Risk Reward (2x to 5x base risk)
    rr = 2 + (3 * (confidence / 100))
    tp_dist = sl_dist * rr

    # If Echo projects a larger move with high confidence, we let it run
    if fcast_tp_dist > tp_dist:
        tp_dist = fcast_tp_dist

    tp_price = (entry_price + tp_dist) if is_long else (entry_price - tp_dist)
    sl_price = (entry_price - sl_dist) if is_long else (entry_price + sl_dist)

    return tp_price, sl_price

def calculate_echo_forecast(df, eval_window=50, forecast_window=50):
    """
    Expert Intelligence Echo Forecast (LuxAlgo Port).
    Identifies historical fractal similarities and projects current price action.
    Returns: (forecast_prices, correlation_score)
    """
    if df is None or len(df) < (eval_window + forecast_window * 2 + 1):
        return None, 0

    src = df['close'].values
    deltas = df['close'].diff().values

    # Reference window: last 'forecast_window' bars (current action)
    ref = src[-forecast_window:]

    best_r = -1.0
    best_k = 0

    # Slide evaluation window through history to find the 'Echo'
    # Step backward from history
    for i in range(eval_window):
        # Slicing from the end
        # match_end_idx is the index just before the reference window started
        # match_start_idx is 'forecast_window' bars before that
        match_end_idx = len(src) - forecast_window - i
        match_start_idx = match_end_idx - forecast_window

        if match_start_idx < 0:
            break

        b = src[match_start_idx:match_end_idx]

        # Pearson Correlation
        std_ref = np.std(ref)
        std_b = np.std(b)

        if std_ref == 0 or std_b == 0:
            r = 0
        else:
            r = np.corrcoef(ref, b)[0, 1]

        if not np.isnan(r) and r > best_r:
            best_r = r
            best_k = i

    # Construct the Echo Forecast using price changes that followed the matched window
    # matched_window_end_at = len(src) - forecast_window - best_k
    match_end = len(src) - forecast_window - best_k

    # Use the deltas that occurred immediately after the matched historical window
    forecast_deltas = deltas[match_end : match_end + forecast_window]

    current_price = src[-1]
    forecast_prices = []
    temp_price = current_price

    for d in forecast_deltas:
        if np.isnan(d): d = 0
        temp_price += d
        forecast_prices.append(temp_price)

    return forecast_prices, best_r
