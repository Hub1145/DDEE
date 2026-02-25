import json
import time
import logging
import threading
import asyncio
from datetime import datetime
from collections import deque
from binance import Client, ThreadedWebsocketManager
from binance.exceptions import BinanceAPIException

class BinanceTradingBotEngine:
    def __init__(self, config_path, emit_callback):
        self.config_path = config_path
        self.emit = emit_callback
        self.console_logs = deque(maxlen=500)
        self.config = self._load_config()

        self.is_running = False
        self.stop_event = threading.Event()

        self.accounts = {} # account_index -> { 'client': Client, 'twm': ThreadedWebsocketManager, 'info': account_config }
        self.exchange_info = {} # symbol -> info

        # Grid state: account_index -> symbol -> { 'initial_entry_filled': bool, 'grid_orders': { order_id: { 'level': int, 'type': 'TP'|'RE_ENTRY' } } }
        self.grid_state = {}

        # Dashboard metrics
        self.account_balances = {} # account_index -> balance
        self.open_positions = {} # account_index -> [positions]
        self.total_equity = 0.0

        self.data_lock = threading.Lock()

        self._setup_logging()

    def _setup_logging(self):
        numeric_level = getattr(logging, self.config.get('log_level', 'INFO').upper(), logging.INFO)
        root_logger = logging.getLogger()
        root_logger.setLevel(numeric_level)
        for handler in root_logger.handlers[:]:
            root_logger.removeHandler(handler)
        ch = logging.StreamHandler()
        ch.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(message)s'))
        root_logger.addHandler(ch)
        fh = logging.FileHandler('binance_bot.log', encoding='utf-8')
        fh.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(message)s'))
        root_logger.addHandler(fh)

    def _load_config(self):
        try:
            with open(self.config_path, 'r') as f:
                return json.load(f)
        except Exception as e:
            logging.error(f"Error loading config: {e}")
            return {}

    def log(self, message, level='info', account_name=None):
        timestamp = datetime.now().strftime('%H:%M:%S')
        prefix = f"[{account_name}] " if account_name else ""
        log_entry = {'timestamp': timestamp, 'message': f"{prefix}{message}", 'level': level}
        self.console_logs.append(log_entry)
        self.emit('console_log', log_entry)
        if level == 'error': logging.error(f"{prefix}{message}")
        elif level == 'warning': logging.warning(f"{prefix}{message}")
        else: logging.info(f"{prefix}{message}")

    def _get_client(self, api_key, api_secret):
        testnet = self.config.get('is_demo', True)
        return Client(api_key, api_secret, testnet=testnet)

    def test_account(self, api_key, api_secret):
        try:
            client = self._get_client(api_key, api_secret)
            client.futures_account_balance()
            return True, "Connection successful"
        except Exception as e:
            return False, str(e)

    def start(self):
        if self.is_running: return
        self.is_running = True
        self.stop_event.clear()

        self.log("Starting Binance Bot Engine...")

        # Initialize accounts
        api_accounts = self.config.get('api_accounts', [])
        for i, acc in enumerate(api_accounts):
            if acc.get('api_key') and acc.get('api_secret') and acc.get('enabled', True):
                try:
                    client = self._get_client(acc['api_key'], acc['api_secret'])
                    twm = ThreadedWebsocketManager(api_key=acc['api_key'], api_secret=acc['api_secret'], testnet=self.config.get('is_demo', True))
                    twm.start()

                    self.accounts[i] = {
                        'client': client,
                        'twm': twm,
                        'info': acc,
                        'last_update': 0
                    }

                    # Start user data stream
                    twm.start_futures_user_data_stream(callback=lambda msg, idx=i: self._handle_user_data(idx, msg))

                    self.log(f"Account {acc.get('name', i)} initialized.", account_name=acc.get('name'))

                    # Initial setup for strategy
                    self._setup_strategy_for_account(i)

                except Exception as e:
                    self.log(f"Failed to initialize account {acc.get('name', i)}: {e}", 'error')

    def stop(self):
        self.is_running = False
        self.stop_event.set()
        for i, acc in self.accounts.items():
            acc['twm'].stop()
        self.accounts = {}
        self.log("Binance Bot Engine stopped.")

    def _setup_strategy_for_account(self, idx):
        acc = self.accounts[idx]
        client = acc['client']
        strategy = self.config.get('strategy', {})
        symbol = strategy.get('symbol')
        if not symbol: return

        try:
            # Get exchange info for precision
            if symbol not in self.exchange_info:
                info = client.futures_exchange_info()
                for s in info['symbols']:
                    if s['symbol'] == symbol:
                        self.exchange_info[symbol] = s
                        break

            # Set leverage and margin type
            leverage = strategy.get('leverage', 20)
            margin_type = strategy.get('margin_type', 'CROSSED')

            try:
                client.futures_change_margin_type(symbol=symbol, marginType=margin_type)
            except BinanceAPIException as e:
                if "No need to change margin type" not in e.message:
                    self.log(f"Margin type change error: {e.message}", 'warning', acc['info'].get('name'))

            client.futures_change_leverage(symbol=symbol, leverage=leverage)

            self.log(f"Leverage set to {leverage}x, Margin: {margin_type}", account_name=acc['info'].get('name'))

            # Force metrics update to get balance
            self._update_account_metrics(idx, force=True)

            # Initial entry if needed
            self._check_and_place_initial_entry(idx, symbol)

        except Exception as e:
            self.log(f"Strategy setup error: {e}", 'error', acc['info'].get('name'))

    def _check_and_place_initial_entry(self, idx, symbol):
        acc = self.accounts[idx]
        client = acc['client']
        strategy = self.config.get('strategy', {})
        direction = strategy.get('direction', 'LONG')
        quantity = float(strategy.get('total_quantity', 0))
        entry_price = float(strategy.get('entry_price', 0))

        if quantity <= 0 or entry_price <= 0: return

        # Check if we already have a position or open orders
        orders = client.futures_get_open_orders(symbol=symbol)
        pos = client.futures_position_information(symbol=symbol)
        has_pos = any(float(p['positionAmt']) != 0 for p in pos if p['symbol'] == symbol)

        if not has_pos and not orders:
            self.log(f"Placing initial {direction} entry at {entry_price}", account_name=acc['info'].get('name'))
            side = Client.SIDE_BUY if direction == 'LONG' else Client.SIDE_SELL

            try:
                order_id = self._place_limit_order(idx, symbol, side, quantity, entry_price)

                if order_id:
                    with self.data_lock:
                        if idx not in self.grid_state: self.grid_state[idx] = {}
                        self.grid_state[idx][symbol] = {
                            'initial_order_id': order_id,
                            'initial_filled': False,
                            'levels': {} # level -> { 'tp_order_id': id, 'buy_back_order_id': id }
                        }

            except Exception as e:
                self.log(f"Initial entry placement failed: {e}", 'error', acc['info'].get('name'))

    def _format_quantity(self, symbol, quantity):
        info = self.exchange_info.get(symbol)
        if not info: return quantity
        step_size = 0.00000001
        for f in info['filters']:
            if f['filterType'] == 'LOT_SIZE':
                step_size = float(f['stepSize'])
                break
        precision = 0
        if step_size < 1:
            precision = len(str(step_size).split('.')[-1].rstrip('0'))
        return round(quantity, precision)

    def _format_price(self, symbol, price):
        info = self.exchange_info.get(symbol)
        if not info: return price
        tick_size = 0.00000001
        for f in info['filters']:
            if f['filterType'] == 'PRICE_FILTER':
                tick_size = float(f['tickSize'])
                break
        precision = 0
        if tick_size < 1:
            precision = len(str(tick_size).split('.')[-1].rstrip('0'))
        return round(price, precision)

    def _handle_user_data(self, idx, msg):
        event_type = msg.get('e')
        acc_name = self.accounts[idx]['info'].get('name')

        if event_type == 'ORDER_TRADE_UPDATE':
            order_data = msg.get('o', {})
            symbol = order_data.get('s')
            status = order_data.get('X')
            side = order_data.get('S')
            order_id = order_data.get('i')
            avg_price = float(order_data.get('ap', 0))
            filled_qty = float(order_data.get('z', 0))

            if status == 'FILLED':
                self.log(f"Order {order_id} FILLED: {side} {filled_qty} {symbol} at {avg_price}", account_name=acc_name)
                self._process_filled_order(idx, symbol, order_data)

        elif event_type == 'ACCOUNT_UPDATE':
            # Update balances and positions
            update_data = msg.get('a', {})
            balances = update_data.get('B', [])
            for b in balances:
                asset = b.get('a')
                if asset in ['USDT', 'USDC']:
                    # Update local balance storage
                    pass
            self._update_account_metrics(idx)

    def _process_filled_order(self, idx, symbol, order_data):
        order_id = order_data.get('i')
        strategy = self.config.get('strategy', {})
        if symbol != strategy.get('symbol'): return

        direction = strategy.get('direction', 'LONG')
        total_fractions = int(strategy.get('total_fractions', 8))
        price_deviation = float(strategy.get('price_deviation', 0.6)) / 100.0
        total_qty = float(strategy.get('total_quantity', 0))
        fraction_qty = total_qty / total_fractions

        with self.data_lock:
            state = self.grid_state.get(idx, {}).get(symbol)
            if not state: return

            # 1. Initial Entry Filled
            if not state.get('initial_filled') and order_id == state.get('initial_order_id'):
                state['initial_filled'] = True
                entry_price = float(order_data.get('ap'))
                self.log(f"Initial entry filled at {entry_price}. Placing {total_fractions} fractional TP orders.", account_name=self.accounts[idx]['info'].get('name'))
                self._place_tp_grid(idx, symbol, entry_price, total_fractions, fraction_qty, price_deviation, direction)
                return

            # 2. Check if a TP order was filled
            for level, orders in state['levels'].items():
                if order_id == orders.get('tp_order_id'):
                    self.log(f"TP Level {level} filled. Placing re-entry order.", account_name=self.accounts[idx]['info'].get('name'))
                    # Place re-entry order at previous level's price
                    entry_price = float(strategy.get('entry_price', 0))
                    if direction == 'LONG':
                        re_entry_price = entry_price + (level - 1) * entry_price * price_deviation
                    else:
                        re_entry_price = entry_price - (level - 1) * entry_price * price_deviation

                    re_entry_id = self._place_limit_order(idx, symbol, 'BUY' if direction == 'LONG' else 'SELL', fraction_qty, re_entry_price)
                    orders['re_entry_order_id'] = re_entry_id
                    orders['tp_order_id'] = None # Clear TP order id
                    return

                # 3. Check if a re-entry order was filled
                if order_id == orders.get('re_entry_order_id'):
                    self.log(f"Re-entry Level {level} filled. Placing TP order again.", account_name=self.accounts[idx]['info'].get('name'))
                    # Place TP order again at its level's price
                    entry_price = float(strategy.get('entry_price', 0))
                    if direction == 'LONG':
                        tp_price = entry_price + level * entry_price * price_deviation
                    else:
                        tp_price = entry_price - level * entry_price * price_deviation

                    tp_id = self._place_limit_order(idx, symbol, 'SELL' if direction == 'LONG' else 'BUY', fraction_qty, tp_price)
                    orders['tp_order_id'] = tp_id
                    orders['re_entry_order_id'] = None # Clear re-entry id
                    return

    def _place_tp_grid(self, idx, symbol, entry_price, fractions, qty, deviation, direction):
        state = self.grid_state[idx][symbol]
        for i in range(1, fractions + 1):
            if direction == 'LONG':
                tp_price = entry_price + (i * entry_price * deviation)
                side = Client.SIDE_SELL
            else:
                tp_price = entry_price - (i * entry_price * deviation)
                side = Client.SIDE_BUY

            order_id = self._place_limit_order(idx, symbol, side, qty, tp_price)
            state['levels'][i] = {
                'tp_order_id': order_id,
                're_entry_order_id': None,
                'price': tp_price
            }

    def _check_balance_for_order(self, idx, qty, price):
        # Basic check: balance > qty * price
        # In futures, it's more complex (margin), but this is a reasonable safety check
        balance = self.account_balances.get(idx, 0)
        notional = qty * price
        return balance > notional

    def _place_limit_order(self, idx, symbol, side, qty, price):
        client = self.accounts[idx]['client']

        # Validate balance before placing re-buy/re-sell orders
        if not self._check_balance_for_order(idx, qty, price):
            self.log(f"Insufficient balance to place order for {qty} at {price}", 'warning', self.accounts[idx]['info'].get('name'))
            return None

        try:
            formatted_qty = self._format_quantity(symbol, qty)
            formatted_price = self._format_price(symbol, price)
            order = client.futures_create_order(
                symbol=symbol,
                side=side,
                type=Client.FUTURE_ORDER_TYPE_LIMIT,
                timeInForce=Client.TIME_IN_FORCE_GTC,
                quantity=formatted_qty,
                price=formatted_price
            )
            return order['orderId']
        except Exception as e:
            self.log(f"Limit order placement failed: {e}", 'error', self.accounts[idx]['info'].get('name'))
            return None

    def _update_account_metrics(self, idx, force=False):
        acc = self.accounts[idx]
        client = acc['client']
        try:
            # Throttle updates
            if not force and time.time() - acc['last_update'] < 5: return
            acc['last_update'] = time.time()

            account_info = client.futures_account()
            total_balance = float(account_info['totalWalletBalance'])
            total_unrealized_pnl = float(account_info['totalUnrealizedProfit'])

            self.account_balances[idx] = total_balance

            positions = []
            for p in account_info['positions']:
                if float(p['positionAmt']) != 0:
                    positions.append({
                        'symbol': p['symbol'],
                        'amount': p['positionAmt'],
                        'entryPrice': p['entryPrice'],
                        'unrealizedProfit': p['unrealizedProfit'],
                        'leverage': p['leverage']
                    })
            self.open_positions[idx] = positions

            self._emit_account_update()

        except Exception as e:
            logging.error(f"Error updating metrics for account {idx}: {e}")

    def _emit_account_update(self):
        total_balance = sum(self.account_balances.values())

        # Flatten positions for UI
        all_positions = []
        for idx, pos_list in self.open_positions.items():
            acc_name = self.accounts[idx]['info'].get('name')
            for p in pos_list:
                p['account'] = acc_name
                all_positions.append(p)

        payload = {
            'total_balance': total_balance,
            'positions': all_positions,
            'running': self.is_running
        }
        self.emit('account_update', payload)

    def apply_live_config_update(self, new_config):
        old_symbols = set(self.config.get('symbols', []))
        new_symbols = set(new_config.get('symbols', []))
        self.config = new_config

        if self.is_running:
            # If symbols changed, we might need to setup new ones
            for sym in new_symbols - old_symbols:
                for idx in self.accounts:
                    self._setup_strategy_for_account(idx) # This will check symbols
        return {"success": True}

    def close_position(self, account_name, symbol):
        # Find the account
        for idx, acc in self.accounts.items():
            if acc['info'].get('name') == account_name:
                client = acc['client']
                try:
                    # Cancel all orders
                    client.futures_cancel_all_open_orders(symbol=symbol)
                    # Close position by market order
                    pos = client.futures_position_information(symbol=symbol)
                    for p in pos:
                        if p['symbol'] == symbol:
                            amt = float(p['positionAmt'])
                            if amt != 0:
                                side = Client.SIDE_SELL if amt > 0 else Client.SIDE_BUY
                                client.futures_create_order(
                                    symbol=symbol,
                                    side=side,
                                    type=Client.FUTURE_ORDER_TYPE_MARKET,
                                    quantity=abs(amt)
                                )
                    self.log(f"Position for {symbol} closed manually.", account_name=account_name)
                except Exception as e:
                    self.log(f"Error closing position: {e}", 'error', account_name)
                break

    def get_status(self):
        return {
            'running': self.is_running,
            'accounts_count': len(self.accounts),
            'total_balance': sum(self.account_balances.values())
        }
