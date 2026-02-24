import json
import time
import logging
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from collections import deque
import websocket
import pandas as pd
import numpy as np
import ta
from handlers.ta_handler import manager
from handlers.screener_handler import ScreenerHandler
from handlers.strategy_handler import StrategyHandler
from handlers.utils import (
    calculate_supertrend, calculate_fractals, calculate_order_blocks,
    calculate_fvg, detect_macd_divergence, calculate_adr,
    calculate_snr_zones, check_price_action_patterns, score_reversal_pattern
)

class TradingBotEngine:
    STRATEGY_MAP = {
        'strategy_1': {
            'name': 'Slow (Daily / 15m)',
            'htf_granularity': 86400, # Daily
            'ltf_granularity': 900,   # 15m
            'expiry_type': 'eod'      # End of Day
        },
        'strategy_2': {
            'name': 'Moderate (1h / 3m)',
            'htf_granularity': 3600,  # 1h
            'ltf_granularity': 180,   # 3m
            'expiry_type': 'fixed',
            'duration': 3600          # 1 hour
        },
        'strategy_3': {
            'name': 'Fast (15m / 1m)',
            'htf_granularity': 900,   # 15m
            'ltf_granularity': 60,    # 1m
            'expiry_type': 'fixed',
            'duration': 900           # 15 minutes
        },
        'strategy_4': {
            'name': 'SNR Price Action',
            'htf_granularity': 300,   # 5m for SNR
            'ltf_granularity': 60,    # 1m for Entry
            'expiry_type': 'fixed',
            'duration': 300           # 5m expiry
        },
        'strategy_5': {
            'name': 'Intelligence Screener v2.0',
            'htf_granularity': 3600,  # 1h
            'ltf_granularity': 60,    # 1m
            'bias_granularity': 900,   # 15m
            'm5_granularity': 300,
            'daily_granularity': 86400,
            'expiry_type': 'dynamic'
        },
        'strategy_6': {
            'name': 'Intelligence Legacy v1.0',
            'htf_granularity': 3600,  # 1h for Intelligence Core
            'ltf_granularity': 60,    # 1m for Timing
            'bias_granularity': 14400, # 4h for bias
            'expiry_type': 'dynamic'
        },
        'strategy_7': {
            'name': 'Intelligent Multi-TF Alignment',
            'expiry_type': 'dynamic',
            'ltf_granularity': 60, # Default trigger on 1m
            'htf_granularity': 3600 # Placeholder to prevent KeyErrors
        }
    }

    def __init__(self, config_path, emit_callback):
        self.config_path = config_path
        self.emit = emit_callback
        self.console_logs = deque(maxlen=500)
        self.screener_data = {} # Symbol -> Screener metrics
        self.config = self._load_config()

        self.is_running = False
        self.is_connected = False
        self.ws = None
        self.ws_thread = None
        self.stop_event = threading.Event()

        self.screener_handler = ScreenerHandler(self)
        self.strategy_handler = StrategyHandler(self)
        self.screener_thread = None
        self.tick_executor = ThreadPoolExecutor(max_workers=10)
        self.history_queue = deque()
        self.history_lock = threading.Lock()
        self.last_fetches = {} # (symbol, granularity) -> last_fetch_epoch
        self.strat7_cache = {} # Symbol -> { 'small': Analysis, 'mid': Analysis, 'high': Analysis, 'timestamp': float }

        # Account metrics
        self.account_balance = 0.0
        self.available_balance = 0.0
        self.total_equity = 0.0
        self.net_profit = 0.0
        self.total_trades_count = 0
        self.trade_fees = 0.0
        self.used_fees = 0.0
        self.size_fees = 0.0
        self.cached_pos_notional = 0.0
        self.used_amount_notional = 0.0
        self.remaining_amount_notional = 0.0
        self.max_allowed_display = 0.0
        self.max_amount_display = 0.0
        self.total_capital_2nd = 0.0
        self.net_trade_profit = 0.0
        self.total_trade_profit = 0.0
        self.total_trade_loss = 0.0
        self.wins_count = 0
        self.losses_count = 0
        self.symbol_streaks = {} # Symbol -> current consecutive losses
        self.daily_start_balance = 0.0
        self.last_balance_reset_date = None

        # Positions and data
        self.open_trades = []
        self.contracts = {} # contract_id -> contract_info
        self.symbol_data = {} # Symbol -> { 'ltf_candles': [], 'htf_open': price, 'last_tick': price, ... }

        # UI Compatibility (aggregated or first symbol)
        self.in_position = {'long': False, 'short': False}
        self.position_entry_price = {'long': 0.0, 'short': 0.0}
        self.position_qty = {'long': 0.0, 'short': 0.0}
        self.current_take_profit = {'long': 0.0, 'short': 0.0}
        self.current_stop_loss = {'long': 0.0, 'short': 0.0}

        self.data_lock = threading.Lock()

        # Configure logging
        numeric_level = getattr(logging, self.config.get('log_level', 'INFO').upper(), logging.INFO)
        root_logger = logging.getLogger()
        root_logger.setLevel(numeric_level)

        # Clear handlers
        for handler in root_logger.handlers[:]:
            root_logger.removeHandler(handler)

        # Console handler
        ch = logging.StreamHandler()
        ch.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(message)s'))
        root_logger.addHandler(ch)

        # File handler
        fh = logging.FileHandler('debug.log', encoding='utf-8')
        fh.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(message)s'))
        root_logger.addHandler(fh)

    def _load_config(self):
        try:
            with open(self.config_path, 'r') as f:
                config = json.load(f)
                if 'deriv_app_id' in config:
                    manager.set_app_id(config['deriv_app_id'])
                return config
        except Exception as e:
            # We can't use self.log yet because it might emit before engine is ready
            logging.error(f"Error loading config: {e}")
            return {}

    def log(self, message, level='info'):
        timestamp = datetime.now().strftime('%H:%M:%S')
        log_entry = {'timestamp': timestamp, 'message': message, 'level': level}
        self.console_logs.append(log_entry)
        self.emit('console_log', log_entry)

        # Also write to standard logging for the debug.log file
        if level == 'error':
            logging.error(message)
        elif level == 'warning':
            logging.warning(message)
        else:
            logging.info(message)

    def _get_ws_url(self):
        app_id = self.config.get('deriv_app_id', '62845')
        return f"wss://ws.binaryws.com/websockets/v3?app_id={app_id}"

    def on_open(self, ws):
        self.log("Deriv WebSocket connected.")
        self.is_connected = True
        self._emit_updates() # Send initial state
        auth_request = {"authorize": self.config.get('deriv_api_token')}
        ws.send(json.dumps(auth_request))

    def on_message(self, ws, message):
        try:
            data = json.loads(message)
        except Exception as e:
            self.log(f"Error parsing message: {e}", 'error')
            return

        msg_type = data.get('msg_type')

        if 'error' in data:
            self.log(f"Deriv Error: {data['error']['message']}", 'error')
            if data['error'].get('code') == 'AuthorizationRequired':
                self.is_running = False
            return

        if msg_type == 'authorize':
            self.log("Authorization successful.")
            auth_data = data.get('authorize', {})
            self.account_balance = auth_data.get('balance', 0.0)
            self.available_balance = self.account_balance
            self.total_equity = self.account_balance

            # Initial daily start balance capture
            if self.daily_start_balance == 0.0:
                self.daily_start_balance = self.account_balance
                self.last_balance_reset_date = datetime.now(timezone.utc).date()
                self.log(f"Daily starting balance set: {self.daily_start_balance}")

            self._emit_updates()

            ws.send(json.dumps({"balance": 1, "subscribe": 1}))

            ws.send(json.dumps({"proposal_open_contract": 1, "subscribe": 1}))

            if self.is_running:
                strat_key = self.config.get('active_strategy', 'strategy_1')
                strat = self.STRATEGY_MAP.get(strat_key, self.STRATEGY_MAP['strategy_1'])

                for symbol in self.config.get('symbols', []):
                    self._init_symbol_data(symbol)
                    ws.send(json.dumps({"ticks": symbol, "subscribe": 1}))
                    time.sleep(0.5)

                    if strat_key == 'strategy_7': continue

                    self._fetch_history(ws, symbol, strat['ltf_granularity'], 100)
                    time.sleep(0.5)
                    h_count = 200 if strat_key in ['strategy_4', 'strategy_5', 'strategy_6'] else 2
                    self._fetch_history(ws, symbol, strat['htf_granularity'], h_count)
                    time.sleep(0.5)

                    # Enhanced History for Strategies 1 & 2 (Bias filters)
                    if strat_key in ['strategy_1', 'strategy_2']:
                        self._fetch_history(ws, symbol, 14400, 100) # 4H
                        time.sleep(0.5)

                    if strat_key == 'strategy_5':
                        for g, c in [(60, 100), (300, 100), (900, 200), (3600, 200), (86400, 50)]:
                            self._fetch_history(ws, symbol, g, c)
                            time.sleep(0.5)
                        ws.send(json.dumps({"contracts_for": symbol}))
                    elif strat_key == 'strategy_6':
                        for g, c in [(60, 100), (900, 200), (3600, 200), (86400, 50)]:
                            self._fetch_history(ws, symbol, g, c)
                            time.sleep(0.5)
                        ws.send(json.dumps({"contracts_for": symbol}))
                    time.sleep(0.5)

        elif msg_type == 'balance':
            self.account_balance = data['balance']['balance']
            self.available_balance = self.account_balance
            self.total_equity = self.account_balance
            self._emit_updates()

        elif msg_type == 'candles':
            echo = data.get('echo_req', {})
            symbol = echo.get('ticks_history')
            granularity = echo.get('granularity')
            candles = data.get('candles', [])
            self.log(f"Received {len(candles)} candles for {symbol} (G:{granularity})")
            self._handle_candles(symbol, granularity, candles)

        elif msg_type == 'tick':
            sub_id = data.get('subscription', {}).get('id')
            self._handle_tick(data['tick'], sub_id)

        elif msg_type == 'proposal_open_contract':
            poc = data.get('proposal_open_contract')
            if poc and 'contract_id' in poc:
                self._handle_contract_update(poc)

        elif msg_type == 'contracts_for':
            echo = data.get('echo_req', {})
            symbol = echo.get('contracts_for')
            contracts = data.get('contracts_for', {}).get('available', [])
            multipliers = []
            for c in contracts:
                if c.get('contract_type') == 'MULTUP':
                    multipliers = c.get('multiplier_range', [])
                    break
            if multipliers:
                self.log(f"Available multipliers for {symbol}: {multipliers}")
                self.emit('multipliers_update', {'symbol': symbol, 'multipliers': multipliers})

        elif msg_type == 'buy':
            buy_data = data.get('buy')
            if buy_data:
                cid = buy_data.get('contract_id')
                self.log(f"Trade opened: {cid} for {buy_data.get('buy_price')} USD")

                # Initialize contract entry to start monitoring immediately
                params = data.get('echo_req', {}).get('parameters', {})
                symbol = params.get('symbol')
                ctype = params.get('contract_type')
                side = 'long' if ctype in ['CALL', 'MULTUP'] else 'short'

                with self.data_lock:
                    sd = self.symbol_data.get(symbol, {})
                    self.contracts[cid] = {
                        'id': cid, 'symbol': symbol, 'side': side,
                        'contract_type': ctype,
                        'stake': buy_data.get('buy_price', 0),
                        'pnl': 0, 'is_closing': False,
                        'status': 'Opened',
                        'multiplier': params.get('multiplier'),
                        'tp_price': None, 'sl_price': None,
                        'entry_price': None,
                        'entry_snapshot': sd.get('last_trade_snapshot', {})
                    }
                    # Use last known tick as preliminary entry price for immediate TP/SL tracking
                    if symbol in self.symbol_data and self.symbol_data[symbol].get('last_tick'):
                        self.contracts[cid]['entry_price'] = self.symbol_data[symbol]['last_tick']
                        self._calculate_target_prices(cid)

        elif msg_type == 'sell':
            sell_data = data.get('sell')
            if sell_data:
                self.log(f"Trade closed: {sell_data.get('contract_id')}")

    def _init_symbol_data(self, symbol):
        if symbol not in self.symbol_data:
            self.symbol_data[symbol] = {
                'ltf_candles': [],
                'htf_candles': [],
                'bias_candles': [], # 15m or 4h for Strategy 5
                'daily_candles': [], # Daily for Strategy 5 Multiplier
                'm5_candles': [],
                'm15_candles': [],
                'htf_open': None,
                'htf_epoch': None,
                'last_tick': None,
                'last_processed_ltf': None,
                'last_trade_ltf': None,
                'current_ltf_candle': None,
                'current_htf_candle': None, # for tracking HTF closes
                'current_bias_candle': None,
                'snr_zones': [], # List of { 'price': level, 'type': 'S'|'R'|'Flip', 'touches': n }
                'consecutive_wins': 0,
                'consecutive_losses': 0,
                'daily_crosses': 0,
                'last_cross_side': None, # 'above' or 'below'
                'hourly_trade_count': 0,
                'last_trade_hour': None,
                'h4_candles': [],
                'm3_candles': [],
                'atr_1m_history': deque(maxlen=50)
            }

    def _fetch_history(self, ws, symbol, granularity, count):
        with self.history_lock:
            # Avoid redundant requests in same minute (or for small granularities, same period)
            now_epoch = int(time.time() // max(60, granularity))
            cache_key = (symbol, granularity)
            if self.last_fetches.get(cache_key) == now_epoch:
                return

            request = {
                "ticks_history": symbol,
                "adjust_start_time": 1,
                "count": count,
                "end": "latest",
                "granularity": granularity,
                "style": "candles"
            }
            self.history_queue.append(request)
            self.last_fetches[cache_key] = now_epoch

    def _history_worker(self):
        self.log("History worker started")
        while not self.stop_event.is_set():
            is_conn = False
            if self.ws:
                try:
                    # WebSocketApp keeps its own state
                    is_conn = self.ws.sock and self.ws.sock.connected
                except:
                    is_conn = False

            if is_conn and self.history_queue:
                try:
                    req = self.history_queue.popleft()
                    self.log(f"History worker sending: {req.get('ticks_history')} G:{req.get('granularity')}")
                    self.ws.send(json.dumps(req))
                    time.sleep(1.0) # More conservative throttle
                except Exception as e:
                    self.log(f"History worker error: {e}", "error")
            else:
                if not is_conn and self.history_queue:
                     # Log occasionally that we are waiting for connection
                     if int(time.time()) % 30 == 0:
                         self.log("History worker waiting for connection...")
                time.sleep(0.5)

    def _handle_candles(self, symbol, granularity, candles):
        strat_key = self.config.get('active_strategy', 'strategy_1')
        strat = self.STRATEGY_MAP.get(strat_key, self.STRATEGY_MAP['strategy_1'])
        htf_gran = strat.get('htf_granularity')
        ltf_gran = strat.get('ltf_granularity')

        with self.data_lock:
            if symbol not in self.symbol_data: return
            sd = self.symbol_data[symbol]

            if granularity == 60:
                if len(candles) > 1: sd['ltf_candles'] = candles
                else:
                    sd['ltf_candles'].append(candles[0])
                    if len(sd['ltf_candles']) > 100: sd['ltf_candles'].pop(0)
            if granularity == 180: # 3m
                if len(candles) > 1: sd['m3_candles'] = candles
                else:
                    sd['m3_candles'].append(candles[0])
                    if len(sd['m3_candles']) > 100: sd['m3_candles'].pop(0)
            if granularity == 300:
                if len(candles) > 1: sd['m5_candles'] = candles
                else:
                    sd['m5_candles'].append(candles[0])
                    if len(sd['m5_candles']) > 100: sd['m5_candles'].pop(0)
            if granularity == 900:
                if len(candles) > 1: sd['m15_candles'] = candles
                else:
                    sd['m15_candles'].append(candles[0])
                    if len(sd['m15_candles']) > 200: sd['m15_candles'].pop(0)
                if strat_key == 'strategy_5':
                    sd['snr_zones'] = calculate_snr_zones(symbol, sd, 900, strat_key) # 15m SNR
            if granularity == 3600:
                if len(candles) > 1: sd['htf_candles'] = candles
                else:
                    sd['htf_candles'].append(candles[0])
                    if len(sd['htf_candles']) > 200: sd['htf_candles'].pop(0)
            if granularity == 14400:
                if len(candles) > 1:
                    sd['bias_candles'] = candles
                    sd['h4_candles'] = candles
                else:
                    sd['bias_candles'].append(candles[0])
                    sd['h4_candles'].append(candles[0])
                    if len(sd['bias_candles']) > 100: sd['bias_candles'].pop(0)
                    if len(sd['h4_candles']) > 100: sd['h4_candles'].pop(0)

            if granularity == strat.get('bias_granularity'):
                if candles:
                    sd['current_bias_candle'] = candles[-1]

            if granularity == 86400:
                sd['daily_candles'] = candles

            if htf_gran and granularity == htf_gran:
                if candles:
                    now_utc = datetime.now(timezone.utc)
                    # For Daily (86400), start is 00:00 UTC
                    # For Hourly (3600), start is top of the hour
                    # For 15m (900), start is every 15m
                    htf_start_epoch = int(now_utc.replace(second=0, microsecond=0).timestamp())
                    if granularity == 86400:
                        htf_start_epoch = int(now_utc.replace(hour=0, minute=0, second=0, microsecond=0).timestamp())
                    elif granularity == 3600:
                        htf_start_epoch = int(now_utc.replace(minute=0, second=0, microsecond=0).timestamp())
                    elif granularity == 900:
                        htf_start_epoch = int(now_utc.replace(minute=(now_utc.minute // 15) * 15, second=0, microsecond=0).timestamp())

                    target_candle = candles[-1]

                    if target_candle['epoch'] < htf_start_epoch:
                        sd['htf_open'] = target_candle['close']
                        sd['htf_epoch'] = htf_start_epoch
                        self.log(f"HTF Open for {symbol} set from previous close: {sd['htf_open']} (Target candle not in history yet)")
                    else:
                        sd['htf_open'] = target_candle['open']
                        sd['htf_epoch'] = target_candle['epoch']
                        self.log(f"HTF Open for {symbol}: {sd['htf_open']} (Epoch: {sd['htf_epoch']})")

                if strat_key == 'strategy_4':
                    sd['htf_candles'] = candles
                    sd['snr_zones'] = calculate_snr_zones(symbol, sd, active_strategy=strat_key)

                if strat_key == 'strategy_5':
                    sd['htf_candles'] = candles
                    sd['snr_zones'] = calculate_snr_zones(symbol, sd, 3600, strat_key) # 1H SNR
                elif strat_key == 'strategy_6':
                    sd['htf_candles'] = candles
                    sd['snr_zones'] = calculate_snr_zones(symbol, sd, 3600, strat_key) # 1H SNR

            elif ltf_gran and granularity == ltf_gran:
                sd['ltf_candles'] = candles
                if candles:
                    sd['current_ltf_candle'] = candles[-1]

    def _handle_tick(self, tick, sub_id=None):
        self.tick_executor.submit(self._process_tick_async, tick, sub_id)

    def _process_tick_async(self, tick, sub_id=None):
        symbol = tick['symbol']
        price = tick['quote']
        tick_time = datetime.fromtimestamp(tick['epoch'], tz=timezone.utc)
        tick_date = tick_time.date()

        strat_key = self.config.get('active_strategy', 'strategy_1')
        strat = self.STRATEGY_MAP.get(strat_key, self.STRATEGY_MAP['strategy_1'])
        ltf_min = strat['ltf_granularity'] // 60
        htf_sec = strat['htf_granularity']

        with self.data_lock:
            # Check for new day to reset daily starting balance
            if self.last_balance_reset_date is None or tick_date > self.last_balance_reset_date:
                self.daily_start_balance = self.account_balance
                self.last_balance_reset_date = tick_date
                self.log(f"New day detected ({tick_date}). Daily starting balance reset to: {self.daily_start_balance}")

                # Refresh daily open if strategy 1 is active (Strategy 1 uses Daily)
                if strat_key == 'strategy_1':
                    for sym in self.config.get('symbols', []):
                        self._fetch_history(self.ws, sym, 86400, 2)

            if symbol not in self.symbol_data: return
            sd = self.symbol_data[symbol]
            sd['last_tick'] = price
            if sub_id and not sd.get('subscription_id'):
                sd['subscription_id'] = sub_id

            # Background Position Monitoring (Force Close, TP/SL)
            # This runs even if is_running is False, as long as WS is connected
            self._monitor_open_contracts(symbol, price)

            if self.is_running:
                # Periodic fetches removed - Handlers now use DerivTA with centralized caching and persistent WS

                # HTF Candle Management (Internal tracking for closure triggers)
                if sd['current_htf_candle']:
                    htf_sec = strat['htf_granularity']
                    htf_start = datetime.fromtimestamp(sd['current_htf_candle']['epoch'], tz=timezone.utc)
                    if tick_time >= htf_start + timedelta(seconds=htf_sec):
                        # Store closed HTF candle
                        sd['htf_candles'].append(sd['current_htf_candle'])
                        if len(sd['htf_candles']) > 200: sd['htf_candles'].pop(0)

                        # New HTF candle
                        new_htf_start = int((tick_time.timestamp() // htf_sec) * htf_sec)
                        sd['current_htf_candle'] = {
                            'epoch': new_htf_start, 'open': price, 'high': price, 'low': price, 'close': price
                        }

                    else:
                        sd['current_htf_candle']['close'] = price
                        sd['current_htf_candle']['high'] = max(sd['current_htf_candle']['high'], price)
                        sd['current_htf_candle']['low'] = min(sd['current_htf_candle']['low'], price)
                else:
                    htf_sec = strat['htf_granularity']
                    new_htf_start = int((tick_time.timestamp() // htf_sec) * htf_sec)
                    sd['current_htf_candle'] = {
                        'epoch': new_htf_start, 'open': price, 'high': price, 'low': price, 'close': price
                    }

                # LTF Candle Management
                if sd['current_ltf_candle']:
                    candle_start = datetime.fromtimestamp(sd['current_ltf_candle']['epoch'], tz=timezone.utc)
                    if tick_time >= candle_start + timedelta(seconds=strat['ltf_granularity']):
                        # LTF Candle transition
                        self.log(f"LTF ({ltf_min}m) Candle closed for {symbol} at {sd['current_ltf_candle']['close']}")

                        # Store closed candle for pattern recognition
                        sd['ltf_candles'].append(sd['current_ltf_candle'])
                        if len(sd['ltf_candles']) > 100: sd['ltf_candles'].pop(0)

                        if self.config.get('entry_type') == 'candle_close':
                            self.strategy_handler.process_strategy(symbol, True)

                        # New LTF candle start time
                        new_start_minute = (tick_time.minute // ltf_min) * ltf_min
                        sd['current_ltf_candle'] = {
                            'epoch': int(tick_time.replace(minute=new_start_minute, second=0, microsecond=0).timestamp()),
                            'open': price, 'high': price, 'low': price, 'close': price
                        }
                    else:
                        sd['current_ltf_candle']['close'] = price
                        sd['current_ltf_candle']['high'] = max(sd['current_ltf_candle']['high'], price)
                        sd['current_ltf_candle']['low'] = min(sd['current_ltf_candle']['low'], price)

                if self.config.get('entry_type') == 'tick':
                    self.strategy_handler.process_strategy(symbol, False)

    def _background_screener_loop(self):
        self.screener_handler.background_loop()

    def _track_daily_open_crosses(self, symbol, current_price):
        sd = self.symbol_data[symbol]
        htf_open = sd['htf_open']
        if htf_open is None: return

        current_side = 'above' if current_price > htf_open else 'below'
        if sd['last_cross_side'] is not None and sd['last_cross_side'] != current_side:
            sd['daily_crosses'] += 1
            self.log(f"Daily Open Cross detected for {symbol}. Total crosses: {sd['daily_crosses']}")
        sd['last_cross_side'] = current_side

    def _monitor_open_contracts(self, symbol=None, current_price=None):
        now_epoch = int(time.time())
        force_close_enabled = self.config.get('force_close_enabled', False)
        force_close_duration = self.config.get('force_close_duration', 60)
        tp_enabled = self.config.get('tp_enabled', False)
        sl_enabled = self.config.get('sl_enabled', False)

        for cid in list(self.contracts.keys()):
            c = self.contracts[cid]
            if symbol != c['symbol']: continue

            side = c.get('side')
            is_long = side == 'long'

            # --- DECISION MAKING POSITION ENGINE v4.0 ---
            strat_key = self.config.get('active_strategy')

            if strat_key == 'strategy_1' and current_price:
                sd = self.symbol_data.get(symbol, {})
                htf_open = sd.get('htf_open')
                if htf_open:
                    # Exit if closed back across Daily Open
                    if (side == 'long' and current_price < htf_open) or (side == 'short' and current_price > htf_open):
                        self.log(f"Strategy 1 EXIT for {symbol}: Price crossed back Daily Open.")
                        self._close_contract(cid)
                        continue

                    # Exit at +2 Daily ATRs
                    if len(sd.get('daily_candles', [])) >= 14:
                        df_d = pd.DataFrame(sd['daily_candles'])
                        daily_atr = ta.volatility.AverageTrueRange(df_d['high'], df_d['low'], df_d['close']).average_true_range().iloc[-1]
                        entry_p = c.get('entry_price')
                        if entry_p:
                            profit_dist = (current_price - entry_p) if is_long else (entry_p - current_price)
                            if profit_dist > (2 * daily_atr):
                                self.log(f"Strategy 1 EXIT for {symbol}: +2 Daily ATR target reached.")
                                self._close_contract(cid)
                                continue

            if (strat_key == 'strategy_5' or strat_key == 'strategy_7') and current_price:
                sd = self.symbol_data.get(symbol, {})
                df_h = pd.DataFrame(sd.get('htf_candles', []))
                df_m15 = pd.DataFrame(sd.get('m15_candles', []))

                if not df_h.empty and len(df_h) >= 20 and not df_m15.empty and len(df_m15) >= 20:
                    exit_reason = None

                    # 1. Divergence Hard Exit (1H)
                    div = detect_macd_divergence(df_h)
                    if (is_long and div == -1) or (not is_long and div == 1):
                        exit_reason = "MACD Divergence detected"

                    # 2. Multiplier Management
                    is_multiplier = c.get('contract_type') in ['MULTUP', 'MULTDOWN']
                    if is_multiplier and not exit_reason:
                        entry_price = c.get('entry_price')
                        atr_1h = ta.volatility.AverageTrueRange(df_h['high'], df_h['low'], df_h['close']).average_true_range().iloc[-1]

                        if entry_price:
                            profit_pips = (current_price - entry_price) if is_long else (entry_price - current_price)

                            # v4.0 "Free Ride" Protocol: Trailing Zone via Fractals/ATR
                            if profit_pips >= 1.5 * atr_1h and not c.get('is_freeride'):
                                self.log(f"Multiplier FREE RIDE for {symbol}: 1.5 ATR profit reached. Moving SL to structural safety zone.")

                                # Find recent 1m Fractal for structural safety
                                trailing_sl = entry_price
                                if sd.get('fractal_lows') and is_long:
                                    trailing_sl = sd['fractal_lows'][-1]
                                elif sd.get('fractal_highs') and not is_long:
                                    trailing_sl = sd['fractal_highs'][-1]
                                else:
                                    # Fallback to Entry + ATR buffer if no fractal
                                    buffer = atr_1h * 0.2
                                    trailing_sl = (entry_price + buffer) if is_long else (entry_price - buffer)

                                c['sl_price'] = trailing_sl
                                c['is_freeride'] = True

                            # SuperTrend Trailing (15m)
                            if c.get('is_freeride'):
                                _, st_dir = calculate_supertrend(df_m15)
                                if (is_long and st_dir.iloc[-1] == -1) or (not is_long and st_dir.iloc[-1] == 1):
                                    exit_reason = "15m SuperTrend reversal (Trailing)"

                    if exit_reason:
                        self.log(f"Strategy {strat_key[-1]} Engine EXIT for {symbol} ({cid}): {exit_reason}.")
                        self._close_contract(cid)
                        continue

            # Price-based TP/SL trigger (Fail-safe tracking for both types)
            if current_price and symbol == c['symbol'] and (tp_enabled or sl_enabled):
                    tp_price = c.get('tp_price')
                    sl_price = c.get('sl_price')

                    if is_long:
                        if tp_enabled and tp_price and current_price >= tp_price:
                            self.log(f"TP reached for {c['symbol']} ({cid}): {current_price} >= {tp_price}. Closing...")
                            self._close_contract(cid)
                            continue
                        if sl_enabled and sl_price and current_price <= sl_price:
                            self.log(f"SL reached for {c['symbol']} ({cid}): {current_price} <= {sl_price}. Closing...")
                            self._close_contract(cid)
                            continue
                    else:
                        if tp_enabled and tp_price and current_price <= tp_price:
                            self.log(f"TP reached for {c['symbol']} ({cid}): {current_price} <= {tp_price}. Closing...")
                            self._close_contract(cid)
                            continue
                        if sl_enabled and sl_price and current_price >= sl_price:
                            self.log(f"SL reached for {c['symbol']} ({cid}): {current_price} >= {sl_price}. Closing...")
                            self._close_contract(cid)
                            continue

            # Ghost cleanup: if expired more than 60s ago and still here
            if c.get('expiry_time') and now_epoch > c['expiry_time'] + 60:
                self.log(f"Cleaning up ghost contract {cid} for {c['symbol']} (expired 60s ago).")
                del self.contracts[cid]
                continue

            if c.get('is_closing'):
                # Retry closing if it's been in is_closing state for more than 30s
                if c.get('last_close_attempt') and now_epoch - c['last_close_attempt'] > 30:
                    self.log(f"Retrying close for contract {cid} ({c['symbol']})...")
                    self._close_contract(cid)
                continue

            # Force Close Check
            purchase_time = c.get('purchase_time')
            if force_close_enabled and purchase_time:
                elapsed = now_epoch - purchase_time
                if elapsed >= force_close_duration:
                    self.log(f"Force close duration reached for {c['symbol']} ({cid}): {elapsed}s elapsed. Closing...")
                    self.contracts[cid]['is_closing'] = True
                    self._close_contract(cid)
                    continue

            # TP/SL check (Redundant but safe if proposal updates are slow)
            profit = c.get('pnl', 0)
            stake = c.get('stake', 0)
            use_fixed = self.config.get('use_fixed_balance', True)

            tp_val = self.config.get('tp_value', 0)
            sl_val = self.config.get('sl_value', 0)

            if use_fixed:
                tp_threshold = tp_val
                sl_threshold = -sl_val # SL is input as positive, we check for profit <= negative
            else:
                tp_threshold = stake * (tp_val / 100.0)
                sl_threshold = -stake * (sl_val / 100.0)

            if tp_enabled and tp_val > 0 and profit >= tp_threshold:
                self.log(f"TP reached (monitor) for {c['symbol']} ({cid}): {profit:.2f} USD (Target: >= {tp_threshold:.2f}). Closing...")
                self.contracts[cid]['is_closing'] = True
                self._close_contract(cid)
            elif sl_enabled and sl_val > 0 and profit <= sl_threshold:
                self.log(f"SL reached (monitor) for {c['symbol']} ({cid}): {profit:.2f} USD (Target: <= {sl_threshold:.2f}). Closing...")
                self.contracts[cid]['is_closing'] = True
                self._close_contract(cid)

    def _execute_trade(self, symbol, side):
        # side is 'buy' or 'sell' from strategy
        internal_side = 'long' if side == 'buy' else 'short'

        sd = self.symbol_data.get(symbol)
        if not sd: return

        strat_key = self.config.get('active_strategy', 'strategy_1')
        strat = self.STRATEGY_MAP.get(strat_key, self.STRATEGY_MAP['strategy_1'])

        duration_seconds = 0
        now = datetime.now(timezone.utc)
        expiry_label = ""

        custom_expiry = self.config.get('custom_expiry', 'default')

        if strat_key == 'strategy_1':
            # v4.0 Dynamic Expiry: Check if price moved > 2 Daily ATRs
            daily_atr = 0
            if len(sd.get('daily_candles', [])) >= 14:
                df_d = pd.DataFrame(sd['daily_candles'])
                daily_atr = ta.volatility.AverageTrueRange(df_d['high'], df_d['low'], df_d['close']).average_true_range().iloc[-1]

            # For now, Strategy 1 remains EOD as base, but we will add ATR TP in monitor
            end_of_day = (now + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
            duration_seconds = int((end_of_day - now).total_seconds())
            expiry_label = f"Expiry: {end_of_day.strftime('%H:%M:%S')} UTC"

        elif strat_key == 'strategy_2':
            # Remaining time for 1h candle
            htf_gran = 3600
            next_close_epoch = ((int(now.timestamp()) // htf_gran) + 1) * htf_gran
            duration_seconds = max(15, next_close_epoch - int(now.timestamp()))
            expiry_label = f"Expiry: {duration_seconds // 60}m {duration_seconds % 60}s"

        elif strat_key == 'strategy_3':
            # Remaining time for 15m candle
            htf_gran = 900
            next_close_epoch = ((int(now.timestamp()) // htf_gran) + 1) * htf_gran
            duration_seconds = max(15, next_close_epoch - int(now.timestamp()))
            expiry_label = f"Expiry: {duration_seconds // 60}m {duration_seconds % 60}s"

        elif strat_key in ['strategy_5', 'strategy_6', 'strategy_7']:
            metrics = self.screener_data.get(symbol, {})
            contract_type = self.config.get('contract_type', 'rise_fall')
            is_multiplier = (contract_type == 'multiplier')

            if not is_multiplier:
                # Rise & Fall Constraints for Strategy 5
                if strat_key == 'strategy_5':
                    # 1. Late Entry Penalty
                    if sd['ltf_candles']:
                        last_c = sd['ltf_candles'][-1]
                        body = abs(last_c['close'] - last_c['open'])
                        df_ltf = pd.DataFrame(sd['ltf_candles'])
                        avg_atr = ta.volatility.AverageTrueRange(df_ltf['high'], df_ltf['low'], df_ltf['close']).average_true_range().mean()
                        if body > (avg_atr * 0.3):
                            self.log(f"Strategy 5 Scalp CANCELLED: Late entry (body {body:.4f} > 30% avg ATR {avg_atr*0.3:.4f})")
                            return

                    # 2. Volatility Freeze (v4.0 Instrument Specific)
                    atr_1m = metrics.get('atr_1m', 0)
                    atr_24h = metrics.get('atr_24h', 0)
                    if atr_24h > 0 and atr_1m < (atr_24h * 0.1):
                        self.log(f"Strategy 5 Scalp PAUSED: Volatility too low (1m ATR {atr_1m} < 10% of 24h ATR {atr_24h})")
                        return
                    elif atr_1m < 0.00001: # Fail-safe absolute baseline
                        self.log(f"Strategy 5 Scalp PAUSED: Volatility too low (1m ATR: {atr_1m})")
                        return

                # Dynamic expiry based on trigger timeframe
                duration_minutes = metrics.get('expiry_min', 5)
                duration_seconds = duration_minutes * 60
                expiry_label = f"Dynamic Expiry: {duration_minutes}m"
            else:
                expiry_label = "Multiplier Position"
        elif strat['expiry_type'] == 'eod':
            # End of day calculation (UTC)
            end_of_day = (now + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
            duration_seconds = int((end_of_day - now).total_seconds())
            expiry_label = f"Expiry: {end_of_day.strftime('%H:%M:%S')} UTC"
        elif strat['expiry_type'] == 'fixed':
            if custom_expiry != 'default':
                try:
                    duration_seconds = int(custom_expiry)
                except:
                    duration_seconds = strat['duration']
            else:
                # Calculate duration till NEXT HTF candle close for Strategy 2 and 3
                # if the user wants "Time till candle close" behavior
                if strat_key in ['strategy_2', 'strategy_3']:
                    htf_gran = strat['htf_granularity']
                    next_close_epoch = ((int(now.timestamp()) // htf_gran) + 1) * htf_gran
                    duration_seconds = next_close_epoch - int(now.timestamp())
                else:
                    duration_seconds = strat['duration']

            if duration_seconds >= 60:
                expiry_label = f"Expiry: {duration_seconds // 60}m {duration_seconds % 60}s"
            else:
                expiry_label = f"Expiry: {duration_seconds} seconds"

        if duration_seconds <= 0:
            return

        # Position management: One trade per symbol, cancel opposite
        existing_cid = None
        for cid, c in self.contracts.items():
            if c['symbol'] == symbol:
                if c['side'] == internal_side:
                    self.log(f"Trade already exists for {symbol} in {side} direction.")
                    return
                else:
                    existing_cid = cid
                    break

        if existing_cid:
            self.log(f"Closing opposite {self.contracts[existing_cid]['side']} trade for {symbol}.")
            self._close_contract(existing_cid)

        # Place trade
        amount = self.config.get('balance_value', 10)

        # v4.0 Strategy 4 Position Sizing: Reduce after 3 touches
        if strat_key == 'strategy_4':
            sd = self.symbol_data.get(symbol, {})
            # Find the zone we are trading
            current_price = sd['last_tick']
            for z in sd.get('snr_zones', []):
                if abs(current_price - z['price']) / z['price'] < 0.005:
                    if z.get('total_lifetime_touches', 0) >= 3:
                        amount *= 0.5
                        self.log(f"Strategy 4: Zone heavily tested ({z.get('total_lifetime_touches')} touches). Reducing position size by 50%.")
                    break
        if not self.config.get('use_fixed_balance'):
            amount = (amount / 100.0) * self.account_balance

        amount = max(0.35, round(amount, 2))

        contract_type = self.config.get('contract_type', 'rise_fall')
        is_multiplier = (strat_key in ['strategy_5', 'strategy_6', 'strategy_7'] and contract_type == 'multiplier')

        if is_multiplier:
            # Use 5% of balance for multipliers
            if not self.config.get('use_fixed_balance'):
                amount = max(0.35, round(self.account_balance * 0.05, 2))

            # Multiplier tied to Volatility (ATR)
            metrics = self.screener_data.get(symbol, {})
            mult_val = metrics.get('multiplier', int(self.config.get('multiplier_value', 100)))

            # TP/SL based on 1H ATR (Mode B: 1.5x ATR SL, 3.0x ATR TP)
            atr_1h = metrics.get('atr', 1.0)
            # We need to convert ATR-based price targets to USD profit/loss for multipliers
            # Profit = (Price_Change / Entry_Price) * Multiplier * Stake
            # So, Target_USD = (ATR_Multiple / Entry_Price) * Multiplier * Stake
            entry_price = sd['last_tick']
            sl_usd = ( (1.5 * atr_1h) / entry_price ) * mult_val * amount
            tp_usd = ( (3.0 * atr_1h) / entry_price ) * mult_val * amount

            self.log(f"Opening MULTIPLIER {side.upper()} on {symbol} | Stake: {amount} | Mult: {mult_val}x | ATR: {atr_1h}")

            buy_request = {
                "buy": 1,
                "price": amount,
                "parameters": {
                    "amount": amount,
                    "basis": "stake",
                    "contract_type": "MULTUP" if side == 'buy' else "MULTDOWN",
                    "currency": "USD",
                    "multiplier": mult_val,
                    "symbol": symbol
                }
            }

            limit_order = {
                'take_profit': round(tp_usd, 2),
                'stop_loss': round(sl_usd, 2)
            }
            buy_request['parameters']['limit_order'] = limit_order
        else:
            self.log(f"Opening {side.upper()} on {symbol} | Stake: {amount} | {expiry_label}")

            buy_request = {
                "buy": 1,
                "price": amount,
                "parameters": {
                    "amount": amount,
                    "basis": "stake",
                    "contract_type": "CALL" if side == 'buy' else "PUT",
                    "currency": "USD",
                    "duration": duration_seconds,
                    "duration_unit": "s",
                    "symbol": symbol
                }
            }
        if self.ws and self.ws.sock and self.ws.sock.connected:
            # Capture entry snapshot
            if is_multiplier:
                metrics = self.screener_data.get(symbol, {})
                sd['last_trade_snapshot'] = {
                    'confidence': metrics.get('confidence', 0),
                    'atr': metrics.get('atr', 0),
                    'entry_time': time.time()
                }

            self.ws.send(json.dumps(buy_request))

    def _close_contract(self, contract_id):
        if self.ws and self.ws.sock and self.ws.sock.connected:
            if contract_id in self.contracts:
                self.contracts[contract_id]['last_close_attempt'] = int(time.time())
            self.ws.send(json.dumps({"sell": contract_id, "price": 0}))

    def _handle_contract_update(self, contract):
        try:
            cid = contract['contract_id']
            symbol = contract['underlying']
            is_sold = contract['is_sold']
            # Map Deriv types to our long/short internal state
            ctype = contract['contract_type']
            side = 'long' if ctype in ['CALL', 'MULTUP'] else 'short'

            if is_sold:
                if cid in self.contracts:
                    self.contracts[cid]['status'] = 'Sold'
                    profit = contract.get('profit', 0)
                    self.log(f"Trade {cid} ({symbol}) closed. PnL: {profit}")
                    self.net_trade_profit += profit

                    sd = self.symbol_data.get(symbol)

                    if profit > 0:
                        self.total_trade_profit += profit
                        self.wins_count += 1
                        # v4.0 Streak Reset: 2 consecutive wins OR 1 win + ADX > 20
                        if sd:
                            sd['consecutive_wins'] = sd.get('consecutive_wins', 0) + 1
                            sd['consecutive_losses'] = 0

                            metrics = self.screener_data.get(symbol, {})
                            adx_val = metrics.get('adx', 0)

                            if sd['consecutive_wins'] >= 2 or adx_val > 20:
                                if sd.get('consecutive_losses', 0) >= 3:
                                    self.log(f"Adaptive Sensitivity RESET for {symbol} (Wins: {sd['consecutive_wins']}, ADX: {adx_val})")
                                sd['consecutive_losses'] = 0
                    else:
                        self.total_trade_loss += abs(profit)
                        self.losses_count += 1
                        # v4.0 Streak Tracking: Increment streak on loss
                        if sd:
                            sd['consecutive_losses'] += 1
                            sd['consecutive_wins'] = 0
                            if sd['consecutive_losses'] >= 3:
                                self.log(f"Adaptive Sensitivity: {symbol} on {sd['consecutive_losses']} loss streak. Threshold increased.", "warning")

                    self.total_trades_count += 1
                    del self.contracts[cid]
            else:
                profit = contract.get('profit', 0)
                is_closing = self.contracts.get(cid, {}).get('is_closing', False)
                entry_tick = contract.get('entry_tick')

                # Retrieve or initialize contract data
                c_data = self.contracts.get(cid, {})

                self.contracts[cid] = {
                    'id': cid, 'symbol': symbol, 'side': side,
                    'contract_type': ctype,
                    'entry_price': entry_tick,
                    'pnl': profit,
                    'stake': contract.get('buy_price', 0),
                    'purchase_time': contract.get('purchase_time'),
                    'expiry_time': contract.get('date_expiry'),
                    'is_closing': is_closing,
                    'status': c_data.get('status', 'Active'),
                    'multiplier': contract.get('multiplier'),
                    'tp_price': c_data.get('tp_price'),
                    'sl_price': c_data.get('sl_price')
                }

                # Calculate TP/SL prices if not yet set and we have an entry price
                if entry_tick and not self.contracts[cid]['tp_price']:
                    self._calculate_target_prices(cid)

                # TP/SL check
                if not is_closing:
                    # Force Close Duration Check
                    force_close_enabled = self.config.get('force_close_enabled', False)
                    force_close_duration = self.config.get('force_close_duration', 60)
                    purchase_time = contract.get('purchase_time')

                    if force_close_enabled and purchase_time:
                        now_epoch = int(time.time())
                        if now_epoch - purchase_time >= force_close_duration:
                            self.log(f"Force close duration reached for {symbol} ({cid}). Closing...")
                            self.contracts[cid]['is_closing'] = True
                            self._close_contract(cid)
                            return # Skip further checks if closing

                    tp_enabled = self.config.get('tp_enabled', False)
                    sl_enabled = self.config.get('sl_enabled', False)

                    use_fixed = self.config.get('use_fixed_balance', True)
                    stake = contract.get('buy_price', 0)

                    tp_val = self.config.get('tp_value', 0)
                    sl_val = self.config.get('sl_value', 0)

                    if use_fixed:
                        tp_threshold = tp_val
                        sl_threshold = -sl_val
                    else:
                        tp_threshold = stake * (tp_val / 100.0)
                        sl_threshold = -stake * (sl_val / 100.0)

                    if tp_enabled and tp_val > 0 and profit >= tp_threshold:
                        self.log(f"TP reached for {symbol} ({cid}): {profit:.2f} USD (Target: >= {tp_threshold:.2f}). Closing...")
                        self.contracts[cid]['is_closing'] = True
                        self._close_contract(cid)
                    elif sl_enabled and sl_val > 0 and profit <= sl_threshold:
                        self.log(f"SL reached for {symbol} ({cid}): {profit:.2f} USD (Target: <= {sl_threshold:.2f}). Closing...")
                        self.contracts[cid]['is_closing'] = True
                        self._close_contract(cid)

            self._update_aggregated_positions()
            self._emit_updates()
        except Exception as e:
            self.log(f"Error handling contract update: {e}", 'error')

    def _calculate_target_prices(self, cid):
        c = self.contracts[cid]
        entry = c['entry_price']
        if not entry: return

        tp_val = self.config.get('tp_value', 0)
        sl_val = self.config.get('sl_value', 0)
        use_fixed = self.config.get('use_fixed_balance', True)
        stake = c['stake']
        multiplier = c.get('multiplier')
        side = c['side'] # 'long' or 'short'

        if not (tp_val > 0 or sl_val > 0): return

        # Calculate threshold in USD
        tp_usd = tp_val if use_fixed else (stake * tp_val / 100.0)
        sl_usd = sl_val if use_fixed else (stake * sl_val / 100.0)

        if multiplier:
            # Check if Strategy 5 generated specific levels
            metrics = self.screener_data.get(c['symbol'])
            strat_key = self.config.get('active_strategy')

            if strat_key == 'strategy_5' and metrics:
                tp_pips = metrics.get('tp_pips', 0)
                sl_pips = metrics.get('sl_pips', 0)
                if side == 'long':
                    self.contracts[cid]['tp_price'] = entry + tp_pips
                    self.contracts[cid]['sl_price'] = entry - sl_pips
                else:
                    self.contracts[cid]['tp_price'] = entry - tp_pips
                    self.contracts[cid]['sl_price'] = entry + sl_pips
            else:
                # Fallback to fixed USD/percentage TP/SL
                # Profit = (Price - Entry) / Entry * Multiplier * Stake
                # Price = Entry * (1 + Profit / (Multiplier * Stake))
                denom = multiplier * stake
                if denom == 0: return

                if side == 'long':
                    if tp_val > 0: self.contracts[cid]['tp_price'] = entry * (1 + tp_usd / denom)
                    if sl_val > 0: self.contracts[cid]['sl_price'] = entry * (1 - sl_usd / denom)
                else:
                    if tp_val > 0: self.contracts[cid]['tp_price'] = entry * (1 - tp_usd / denom)
                    if sl_val > 0: self.contracts[cid]['sl_price'] = entry * (1 + sl_usd / denom)
        else:
            # For Rise & Fall, price-based TP/SL is an approximation
            # We'll use a 0.5% move as a default "unit" if no other info, but that's arbitrary.
            # Better: if it's Rise & Fall, we mostly rely on the 'profit' field monitoring
            # which we already do. But let's set a wide price trigger as a safety.
            # Assume 1% move corresponds to a significant win/loss for binary.
            if side == 'long':
                if tp_val > 0: self.contracts[cid]['tp_price'] = entry * 1.01
                if sl_val > 0: self.contracts[cid]['sl_price'] = entry * 0.99
            else:
                if tp_val > 0: self.contracts[cid]['tp_price'] = entry * 0.99
                if sl_val > 0: self.contracts[cid]['sl_price'] = entry * 1.01

    def _update_aggregated_positions(self):
        # Update UI compatibility fields
        self.in_position = {'long': False, 'short': False}
        self.position_entry_price = {'long': 0.0, 'short': 0.0}
        self.position_qty = {'long': 0.0, 'short': 0.0}

        for c in self.contracts.values():
            side = c['side'] # 'long' or 'short'
            if side in self.in_position:
                self.in_position[side] = True
                # For simplicity, if multiple symbols, we show the first one's price/qty or avg
                if self.position_entry_price[side] == 0:
                    self.position_entry_price[side] = c['entry_price'] or 0.0
                    self.position_qty[side] = c['stake'] or 0.0

    def _emit_updates(self):
        self.open_trades = []
        floating_pnl = 0.0
        used_notional = 0.0
        for cid, c in self.contracts.items():
            self.open_trades.append({
                'id': cid, 'type': c['side'].capitalize(), 'symbol': c['symbol'],
                'entry_spot_price': c['entry_price'], 'stake': c['stake'], 'pnl': c['pnl'],
                'expiry_time': c['expiry_time'],
                'status': c.get('status', 'Holding'),
                'is_freeride': c.get('is_freeride', False)
            })
            floating_pnl += c['pnl']
            used_notional += c['stake']

        self.net_profit = floating_pnl + self.net_trade_profit
        self.used_amount_notional = used_notional
        self.cached_pos_notional = used_notional

        win_rate = 0.0
        if self.total_trades_count > 0:
            win_rate = (self.wins_count / self.total_trades_count) * 100

        avg_pnl = 0.0
        if self.total_trades_count > 0:
            avg_pnl = self.net_trade_profit / self.total_trades_count

        payload = {
            'running': self.is_running,
            'is_demo': self.config.get('is_demo', True),
            'active_strategy': self.config.get('active_strategy'),
            'total_balance': self.account_balance,
            'available_balance': self.available_balance,
            'open_trades': self.open_trades,
            'net_profit': self.net_profit,
            'total_trades': self.total_trades_count + len(self.open_trades),
            'win_rate': round(win_rate, 1),
            'avg_pnl': round(avg_pnl, 2),
            'total_capital': self.total_equity,
            'total_capital_2nd': self.total_capital_2nd,
            'used_amount': self.used_amount_notional,
            'remaining_amount': self.remaining_amount_notional,
            'max_allowed_used_display': self.max_allowed_display,
            'max_amount_display': self.max_amount_display,
            'used_fees': self.used_fees,
            'size_fees': self.size_fees,
            'net_trade_profit': self.net_trade_profit,
            'total_trade_profit': self.total_trade_profit,
            'total_trade_loss': self.total_trade_loss,
            'in_position': self.in_position,
            'position_entry_price': self.position_entry_price
        }
        self.emit('account_update', payload)
        self.emit('trades_update', {'trades': self.open_trades})

    def start(self, passive_monitoring=False):
        self.is_running = not passive_monitoring
        self.log(f"Bot started | Trading: {'ON' if self.is_running else 'OFF'}")

        if not self.screener_thread or not self.screener_thread.is_alive():
            self.screener_thread = threading.Thread(target=self._background_screener_loop, daemon=True)
            self.screener_thread.start()

        if not self.ws_thread or not self.ws_thread.is_alive():
            self.stop_event.clear()
            self.ws_thread = threading.Thread(target=self._run_ws, daemon=True)
            self.ws_thread.start()
            threading.Thread(target=self._history_worker, daemon=True).start()
        elif self.is_running and self.ws and self.ws.sock and self.ws.sock.connected:
            # Already connected but just started trading, trigger subscriptions
            self.log("Already connected, triggering trading subscriptions...")
            strat_key = self.config.get('active_strategy', 'strategy_1')
            strat = self.STRATEGY_MAP.get(strat_key, self.STRATEGY_MAP['strategy_1'])
            h_count = 200 if strat_key in ['strategy_4', 'strategy_5', 'strategy_6'] else 2

            for symbol in self.config.get('symbols', []):
                self._init_symbol_data(symbol)
                self.ws.send(json.dumps({"ticks": symbol, "subscribe": 1}))
                time.sleep(0.5)

                if strat_key == 'strategy_7': continue

                self._fetch_history(self.ws, symbol, strat['ltf_granularity'], 100)
                time.sleep(0.5)
                self._fetch_history(self.ws, symbol, strat['htf_granularity'], h_count)
                time.sleep(0.5)

    def _run_ws(self):
        while not self.stop_event.is_set():
            # Connect if we have a token, to allow balance monitoring
            if not self.config.get('deriv_api_token'):
                time.sleep(2)
                continue

            try:
                self.ws = websocket.WebSocketApp(
                    self._get_ws_url(),
                    on_open=self.on_open,
                    on_message=self.on_message,
                    on_error=lambda ws, err: self.log(f"WS Error: {err}", 'error'),
                    on_close=lambda ws, code, msg: self.log("WS Connection Closed")
                )
                # Use ping_interval to keep connection alive
                self.ws.run_forever(ping_interval=30, ping_timeout=10)
            except Exception as e:
                self.log(f"WS Exception: {e}", 'error')
            if not self.stop_event.is_set():
                time.sleep(5)

    def stop(self):
        self.is_running = False
        self.log("Bot trading paused")

        # Unsubscribe from ticks to save resources
        self.log("Unsubscribing from ticks to save resources (Passive Monitoring active).")
        if self.ws and self.ws.sock and self.ws.sock.connected:
            with self.data_lock:
                for sym, sd in self.symbol_data.items():
                    if sd.get('subscription_id'):
                        self.ws.send(json.dumps({"forget": sd['subscription_id']}))
                        sd['subscription_id'] = None

    def stop_bot(self):
        self.stop_event.set()
        if self.ws:
            self.ws.close()
        self.log("Bot engine shut down")

    def check_credentials(self):
        if not self.config.get('deriv_api_token'):
            return False, "API Token missing"
        return True, "API Token present"

    def test_api_credentials(self):
        token = self.config.get('deriv_api_token')
        if not token: return False
        try:
            ws = websocket.create_connection(self._get_ws_url(), timeout=10)
            ws.send(json.dumps({"authorize": token}))
            res = json.loads(ws.recv())
            ws.close()
            return 'authorize' in res and 'error' not in res
        except: return False

    def apply_live_config_update(self, new_config):
        if 'deriv_app_id' in new_config:
            manager.set_app_id(new_config['deriv_app_id'])

        old_symbols = set(self.config.get('symbols', []))
        new_symbols = set(new_config.get('symbols', []))

        old_token = self.config.get('deriv_api_token')
        new_token = new_config.get('deriv_api_token')

        old_strat = self.config.get('active_strategy', 'strategy_1')
        new_strat = new_config.get('active_strategy', 'strategy_1')

        self.config = new_config
        self.log("Config applied live")

        # If token changed, we need a full reconnect
        if old_token != new_token:
            self._apply_api_credentials()
            return {"success": True}

        # If strategy changed, reset all symbol data to re-fetch with new granularities
        if old_strat != new_strat:
            self.log(f"Strategy changed to {new_strat}. Resetting data...")
            with self.data_lock:
                # Keep subscription ids but clear candles/opens
                for sym in self.symbol_data:
                    sub_id = self.symbol_data[sym].get('subscription_id')
                    self._init_symbol_data(sym)
                    self.symbol_data[sym]['subscription_id'] = sub_id

            if self.ws and self.ws.sock and self.ws.sock.connected:
                strat = self.STRATEGY_MAP.get(new_strat, self.STRATEGY_MAP['strategy_1'])
                h_count = 200 if new_strat in ['strategy_4', 'strategy_5', 'strategy_6'] else 2

                for sym in new_symbols:
                    if new_strat == 'strategy_7':
                        self.ws.send(json.dumps({"ticks": sym, "subscribe": 1}))
                        time.sleep(0.5)
                        continue

                    self._fetch_history(self.ws, sym, strat['ltf_granularity'], 100)
                    time.sleep(0.5)
                    self._fetch_history(self.ws, sym, strat['htf_granularity'], h_count)
                    time.sleep(0.5)

                    if new_strat == 'strategy_5':
                        for g, c in [(60, 100), (300, 100), (900, 200), (3600, 200), (86400, 50)]:
                            self._fetch_history(self.ws, sym, g, c)
                            time.sleep(0.4)
                        self.ws.send(json.dumps({"contracts_for": sym}))
                    elif new_strat == 'strategy_6':
                        for g, c in [(60, 100), (900, 200), (3600, 200), (86400, 50)]:
                            self._fetch_history(self.ws, sym, g, c)
                            time.sleep(0.4)
                        self.ws.send(json.dumps({"contracts_for": sym}))
                    time.sleep(0.5)
            return {"success": True}

        # If only symbols changed and we are connected
        if self.ws and self.ws.sock and self.ws.sock.connected:
            strat = self.STRATEGY_MAP.get(new_strat, self.STRATEGY_MAP['strategy_1'])
            h_count = 200 if new_strat in ['strategy_4', 'strategy_5', 'strategy_6'] else 2
            added_symbols = new_symbols - old_symbols
            for symbol in added_symbols:
                self.log(f"Subscribing to new symbol: {symbol}")
                self._init_symbol_data(symbol)
                self.ws.send(json.dumps({"ticks": symbol, "subscribe": 1}))
                time.sleep(0.5)

                if new_strat == 'strategy_7': continue

                self._fetch_history(self.ws, symbol, strat['ltf_granularity'], 100)
                time.sleep(0.5)
                self._fetch_history(self.ws, symbol, strat['htf_granularity'], h_count)
                time.sleep(0.5)

                if new_strat == 'strategy_5':
                    for g, c in [(60, 100), (300, 100), (900, 200), (3600, 200), (86400, 50)]:
                        self._fetch_history(self.ws, symbol, g, c)
                        time.sleep(0.4)
                    self.ws.send(json.dumps({"contracts_for": symbol}))
                elif new_strat == 'strategy_6':
                    for g, c in [(60, 100), (900, 200), (3600, 200), (86400, 50)]:
                        self._fetch_history(self.ws, symbol, g, c)
                        time.sleep(0.4)
                    self.ws.send(json.dumps({"contracts_for": symbol}))
                time.sleep(0.5)

            removed_symbols = old_symbols - new_symbols
            for symbol in removed_symbols:
                sd = self.symbol_data.get(symbol)
                if sd and sd.get('subscription_id'):
                    self.log(f"Unsubscribing from symbol: {symbol}")
                    self.ws.send(json.dumps({"forget": sd['subscription_id']}))
                with self.data_lock:
                    if symbol in self.symbol_data:
                        del self.symbol_data[symbol]

        return {"success": True}

    def _apply_api_credentials(self):
        self.log("Applying new API credentials, reconnecting...")
        if self.ws:
            self.ws.close()
            # The run_forever loop in _run_ws will handle reconnection

    def fetch_account_data_sync(self):
        self._emit_updates()

    def batch_modify_tpsl(self): pass

    def batch_cancel_orders(self):
        self.log("Cancelling all open trades...")
        with self.data_lock:
            for cid in list(self.contracts.keys()):
                self._close_contract(cid)

    def emergency_sl(self):
        self.batch_cancel_orders()
