import pandas as pd
import ta
import numpy as np
import logging
import time
from datetime import datetime, timezone

class StrategyHandler:
    def __init__(self, bot_engine):
        self.bot = bot_engine

    def process_strategy(self, symbol, is_candle_close):
        # 1. Risk Management: Max Daily Profit/Loss
        max_loss_pct = self.bot.config.get('max_daily_loss_pct', 5)
        max_profit_pct = self.bot.config.get('max_daily_profit_pct', 10)

        if self.bot.daily_start_balance > 0:
            current_equity = self.bot.account_balance + sum(c.get('pnl', 0) for c in self.bot.contracts.values())
            daily_pnl = current_equity - self.bot.daily_start_balance
            current_pnl_pct = (daily_pnl / self.bot.daily_start_balance) * 100

            if current_pnl_pct <= -max_loss_pct:
                if self.bot.is_running:
                    self.bot.log(f"Daily Loss Limit: {current_pnl_pct:.2f}%. Trading paused.", "warning")
                    self.bot.is_running = False
                return

            if current_pnl_pct >= max_profit_pct:
                if self.bot.is_running:
                    self.bot.log(f"Daily Profit Target: {current_pnl_pct:.2f}%. Trading paused.", "info")
                    self.bot.is_running = False
                return

        sd = self.bot.symbol_data.get(symbol)
        if not sd: return

        current_price = sd.get('last_tick')
        if current_price is None: return

        strat_key = self.bot.config.get('active_strategy', 'strategy_1')

        # Strategy 5, 6, 7 rely on Screener Data
        if strat_key in ['strategy_5', 'strategy_6', 'strategy_7']:
            self._process_screener_based_strategy(symbol, strat_key)
        else:
            # Fallback to legacy/default strategies if needed
            # For brevity in this refactor, we focus on the requested 5, 6, 7
            pass

    def _process_screener_based_strategy(self, symbol, strat_key):
        data = self.bot.screener_data.get(symbol)
        if not data: return

        # Only process if data is fresh (within last 30s)
        if time.time() - data.get('last_update', 0) > 30:
            return

        signal = data.get('signal') # 'BUY', 'SELL', or 'WAIT'
        if signal not in ['BUY', 'SELL']:
            return

        # Check if already in position for this symbol
        for cid, c in self.bot.contracts.items():
            if c['symbol'] == symbol:
                return # Already have a trade

        # Execute
        self.bot.log(f"Strategy {strat_key} triggered {signal} for {symbol} based on screener.")
        self.bot._execute_trade(symbol, 'buy' if signal == 'BUY' else 'sell')
