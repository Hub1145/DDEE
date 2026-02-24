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

def predict_expiry_v5(symbol, strategy_key, ltf_min, htf_min, confidence, signals, df_ltf):
    """
    Engine to predict expiry time based on strategy, timeframe, ATR and confidence.
    Signals is a dict: {'small': 'BUY', 'mid': 'STRONG_BUY', 'high': 'BUY'} (for example)
    """
    atr = 0
    if df_ltf is not None and not df_ltf.empty:
        atr_series = ta.volatility.average_true_range(df_ltf['high'], df_ltf['low'], df_ltf['close'], window=14)
        atr = atr_series.iloc[-1]

    # Default is the Mid TF
    base_expiry = 5
    if ltf_min: base_expiry = ltf_min * 3 # e.g. 1m -> 3m

    if strategy_key == 'strategy_7':
        s = signals.get('small', 'NEUTRAL')
        m = signals.get('mid', 'NEUTRAL')
        h = signals.get('high', 'NEUTRAL')

        # 2 Timeframes active (Small & Mid)
        if m != 'OFF' and s != 'OFF' and h == 'OFF':
            if "STRONG" in m and "STRONG" not in s:
                # Shorter expiry (1m to 4m)
                base_expiry = max(1, min(4, int(4 * (confidence/100))))
            else:
                base_expiry = 5 # 5m

        # 3 Timeframes active
        elif h != 'OFF' and m != 'OFF' and s != 'OFF':
            if "STRONG" in h and "STRONG" in m:
                # Very short (< 5m)
                base_expiry = max(1, min(4, int(5 * (1 - confidence/100))))
            elif "STRONG" in h:
                # 5m to 20m
                base_expiry = max(5, min(20, int(20 * (1 - confidence/100))))
            else:
                # Match but not strong -> Less than 1h (e.g. 30m)
                base_expiry = 30

    # Fine-tune based on ATR
    # If ATR is high, price reaches targets faster -> shorter expiry
    if atr > 0 and df_ltf is not None and not df_ltf.empty:
        avg_atr = ta.volatility.average_true_range(df_ltf['high'], df_ltf['low'], df_ltf['close'], window=50).mean()
        if avg_atr > 0:
            ratio = atr / avg_atr
            if ratio > 1.5: # High volatility
                base_expiry = max(1, int(base_expiry * 0.7))
            elif ratio < 0.5: # Low volatility
                base_expiry = int(base_expiry * 1.3)

    return max(1, base_expiry)

def get_smart_targets(entry_price, side, atr, confidence):
    """
    Calculate TP/SL targets based on ATR and confidence level.
    A higher confidence level might allow for a wider TP (letting winners run).
    """
    if atr == 0:
        return None, None

    is_long = side == 'long'

    # Base risk is 1.5x ATR
    sl_dist = 1.5 * atr

    # TP is scaled by confidence (1:2 to 1:5 risk reward)
    rr = 2 + (3 * (confidence / 100))
    tp_dist = sl_dist * rr

    tp_price = (entry_price + tp_dist) if is_long else (entry_price - tp_dist)
    sl_price = (entry_price - sl_dist) if is_long else (entry_price + sl_dist)

    return tp_price, sl_price
