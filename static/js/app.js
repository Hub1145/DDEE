const socket = io();

var currentConfig = null;
var activeStrategy = 'strategy_1';
const configModal = new bootstrap.Modal(document.getElementById('configModal'));
let isBotRunning = false;
let activeTrades = [];

document.addEventListener('DOMContentLoaded', () => {
    loadConfig();
    setupEventListeners();
    setupSocketListeners();
    startCountdownTimer();
});

function updateConfigLabels(strategyOverride = null) {
    // Clear screener data when configuration changes to ensure fresh readings for new mode
    window.screenerDataMap = {};
    const body = document.getElementById('screenerTableBody');
    if (body) body.innerHTML = '<tr><td colspan="12" class="text-center text-muted">Mode changed. Waiting for data...</td></tr>';

    // Entry Type Label
    const strategySelect = document.getElementById('configActiveStrategy');
    if (strategySelect || strategyOverride) {
        const strategy = strategyOverride || strategySelect.value;
        activeStrategy = strategy;
        const label = document.getElementById('configEntryTypeLabel');
        const customExpiryContainer = document.getElementById('customExpiryContainer');
        const strategy5Options = document.getElementById('strategy5Options');
        const strategy7Options = document.getElementById('strategy7Options');
        const screenerTabNavItem = document.getElementById('screenerTabNavItem');

        // Screener tab is always available for monitoring
        if (screenerTabNavItem) screenerTabNavItem.style.display = 'block';

        if (strategy === 'strategy_1') {
            label.textContent = "Wait for 15m Candle Close";
            customExpiryContainer.style.display = 'none';
            strategy5Options.style.display = 'none';
            strategy7Options.style.display = 'none';
        } else if (strategy === 'strategy_2') {
            label.textContent = "Wait for 3m Candle Close";
            customExpiryContainer.style.display = 'block';
            strategy5Options.style.display = 'none';
            strategy7Options.style.display = 'none';
        } else if (strategy === 'strategy_3') {
            label.textContent = "Wait for 1m Candle Close";
            customExpiryContainer.style.display = 'block';
            strategy5Options.style.display = 'none';
            strategy7Options.style.display = 'none';
        } else if (strategy === 'strategy_4') {
            label.textContent = "Wait for 1m Candle Close";
            customExpiryContainer.style.display = 'block';
            strategy5Options.style.display = 'none';
            strategy7Options.style.display = 'none';
        } else if (strategy === 'strategy_5' || strategy === 'strategy_6') {
            label.textContent = "Wait for 1m Candle Close";
            customExpiryContainer.style.display = 'none';
            strategy5Options.style.display = 'block';
            strategy7Options.style.display = 'none';
        } else if (strategy === 'strategy_7') {
            label.textContent = "Wait for LTF Confirm";
            customExpiryContainer.style.display = 'none';
            strategy5Options.style.display = 'block';
            strategy7Options.style.display = 'block';
        } else {
            label.textContent = "Wait for 1m Candle Close";
            customExpiryContainer.style.display = 'block';
            strategy5Options.style.display = 'none';
            strategy7Options.style.display = 'none';
        }
        // Always refresh table headers/layout when strategy changes
        updateScreenerTable(null, null);

    // Update Screener Mode Badge
    const contractType = document.getElementById('configContractType').value;
    const modeBadge = document.getElementById('screenerModeBadge');
    if (modeBadge) {
        modeBadge.textContent = contractType === 'multiplier' ? 'Multiplier' : 'Rise & Fall';
        modeBadge.className = `badge ${contractType === 'multiplier' ? 'bg-warning text-dark' : 'bg-primary'}`;
    }
    }

    // TP/SL Unit Labels
    const useFixed = document.getElementById('configUseFixedBalance').checked;
    const tpLabel = document.getElementById('configTpLabel');
    const slLabel = document.getElementById('configSlLabel');
    if (useFixed) {
        tpLabel.textContent = "Take Profit ($)";
        slLabel.textContent = "Stop Loss ($)";
    } else {
        tpLabel.textContent = "Take Profit (%)";
        slLabel.textContent = "Stop Loss (%)";
    }
}

function setupEventListeners() {
    document.getElementById('configActiveStrategy').addEventListener('change', () => updateConfigLabels());
    document.getElementById('configContractType').addEventListener('change', () => {
        updateConfigLabels();
        if (currentConfig) {
            currentConfig.contract_type = document.getElementById('configContractType').value;
            // Refresh screener table if data exists
            updateScreenerTable(null, null);
        }
    });
    document.getElementById('configUseFixedBalance').addEventListener('change', updateConfigLabels);
    document.getElementById('themeToggle').addEventListener('change', (e) => {
        document.body.setAttribute('data-theme', e.target.checked ? 'light' : 'dark');
    });

    document.getElementById('startStopBtn').addEventListener('click', () => {
        if (isBotRunning) {
            socket.emit('stop_bot');
        } else {
            socket.emit('start_bot');
        }
    });

    document.getElementById('configBtn').addEventListener('click', () => {
        if (currentConfig) {
            document.getElementById('configApiToken').value = currentConfig.deriv_api_token || '';
            document.getElementById('configAppId').value = currentConfig.deriv_app_id || '62845';
            document.getElementById('configUseFixedBalance').checked = currentConfig.use_fixed_balance !== false;
            document.getElementById('configBalanceValue').value = currentConfig.balance_value || 10;
            document.getElementById('configMaxDailyLoss').value = currentConfig.max_daily_loss_pct || 5;
            document.getElementById('configMaxDailyProfit').value = currentConfig.max_daily_profit_pct || 10;
            document.getElementById('configTpEnabled').checked = currentConfig.tp_enabled || false;
            document.getElementById('configTpValue').value = currentConfig.tp_value || 0;
            document.getElementById('configSlEnabled').checked = currentConfig.sl_enabled || false;
            document.getElementById('configSlValue').value = currentConfig.sl_value || 0;
            document.getElementById('configForceCloseEnabled').checked = currentConfig.force_close_enabled || false;
            document.getElementById('configForceCloseDuration').value = currentConfig.force_close_duration || 60;
            document.getElementById('configActiveStrategy').value = currentConfig.active_strategy || 'strategy_1';
            document.getElementById('configContractType').value = currentConfig.contract_type || 'rise_fall';
            document.getElementById('configCustomExpiry').value = currentConfig.custom_expiry || 'default';
            document.getElementById('configEntryType').value = currentConfig.entry_type || 'candle_close';
            document.getElementById('configIsDemo').checked = currentConfig.is_demo !== false;
            document.getElementById('configStrat7SmallTF').value = currentConfig.strat7_small_tf || '60';
            document.getElementById('configStrat7MidTF').value = currentConfig.strat7_mid_tf || '300';
            document.getElementById('configStrat7HighTF').value = currentConfig.strat7_high_tf || '3600';
            updateConfigLabels();
        }
        configModal.show();
    });

    document.getElementById('saveConfigBtn').addEventListener('click', saveConfig);

    document.getElementById('clearConsoleBtn').addEventListener('click', () => {
        document.getElementById('consoleOutput').innerHTML = '';
    });

    document.getElementById('downloadLogsBtn').addEventListener('click', () => {
        window.location.href = '/api/download_logs';
    });

    document.getElementById('addSymbolBtn').addEventListener('click', () => {
        const symbol = prompt("Enter symbol name (e.g., R_100, frxEURUSD):");
        if (symbol && currentConfig) {
            if (!currentConfig.symbols.includes(symbol)) {
                currentConfig.symbols.push(symbol);
                updateSymbolList();
                saveLiveConfig();
            }
        }
    });
}

function setupSocketListeners() {
    socket.on('bot_status', (data) => {
        isBotRunning = data.running;
        const btn = document.getElementById('startStopBtn');
        const status = document.getElementById('botStatus');
        if (isBotRunning) {
            btn.innerHTML = '<i class="bi bi-stop-fill"></i> <span>Stop</span>';
            btn.className = 'btn btn-danger';
            status.textContent = 'Running';
            status.className = 'badge rounded-pill status-badge bg-success mb-3';
        } else {
            btn.innerHTML = '<i class="bi bi-play-fill"></i> <span>Start</span>';
            btn.className = 'btn btn-primary';
            status.textContent = 'Stopped';
            status.className = 'badge rounded-pill status-badge bg-secondary mb-3';
        }
    });

    socket.on('account_update', (data) => {
        if (data.active_strategy && data.active_strategy !== activeStrategy) {
            activeStrategy = data.active_strategy;
            updateConfigLabels(activeStrategy);
        }
        const typeBadge = document.getElementById('accountTypeBadge');
        if (data.is_demo) {
            typeBadge.textContent = 'Demo';
            typeBadge.className = 'badge rounded-pill bg-info ms-1';
        } else {
            typeBadge.textContent = 'Live';
            typeBadge.className = 'badge rounded-pill bg-danger ms-1';
        }

        document.getElementById('balanceDisplay').textContent = `$${Number(data.total_balance || 0).toFixed(1)}`;
        document.getElementById('totalPnlDisplay').textContent = `$${Number(data.net_profit || 0).toFixed(1)}`;
        document.getElementById('totalPnlDisplay').className = `stat-value ${data.net_profit >= 0 ? 'text-success' : 'text-danger'}`;

        document.getElementById('tradesCountDisplay').textContent = data.total_trades || 0;
        document.getElementById('usedAmountDisplay').textContent = `$${Number(data.used_amount || 0).toFixed(1)}`;
        document.getElementById('realizedPnlDisplay').textContent = `$${Number(data.net_trade_profit || 0).toFixed(1)}`;
        document.getElementById('floatingPnlDisplay').textContent = `$${Number((data.net_profit || 0) - (data.net_trade_profit || 0)).toFixed(1)}`;

        if (document.getElementById('winRateDisplay')) {
            document.getElementById('winRateDisplay').textContent = `${Number(data.win_rate || 0).toFixed(1)}%`;
        }
        if (document.getElementById('avgPnlDisplay')) {
            const avg = data.avg_pnl || 0;
            const el = document.getElementById('avgPnlDisplay');
            el.textContent = `$${Number(avg).toFixed(1)}`;
            el.className = `stat-value ${avg >= 0 ? 'text-success' : 'text-danger'}`;
        }
    });

    socket.on('trades_update', (data) => {
        activeTrades = data.trades;
        updateActiveTrades(data.trades);
    });

    socket.on('screener_update', (data) => {
        updateScreenerTable(data.symbol, data.data);
    });

    socket.on('console_log', (data) => {
        const consoleOutput = document.getElementById('consoleOutput');
        const line = document.createElement('div');
        line.style.marginBottom = '2px';
        line.innerHTML = `<span class="text-muted small">[${data.timestamp}]</span> <span class="${data.level === 'error' ? 'text-danger' : (data.level === 'warning' ? 'text-warning' : 'text-success')}">${data.message}</span>`;
        consoleOutput.appendChild(line);
        consoleOutput.scrollTop = consoleOutput.scrollHeight;
    });

    socket.on('error', (data) => alert('Error: ' + data.message));
    socket.on('success', (data) => console.log('Success:', data.message));

    socket.on('multipliers_update', (data) => {
        const symbol = data.symbol;
        const multipliers = data.multipliers;
        window.symbolMultipliers = window.symbolMultipliers || {};
        window.symbolMultipliers[symbol] = multipliers;
    });
}

let screenerDataMap = {};
window.screenerDataMap = screenerDataMap;

function updateScreenerTable(symbol, data) {
    if (symbol && data) {
        screenerDataMap[symbol] = data;
    }
    const body = document.getElementById('screenerTableBody');
    if (!body) return;

    // Update Headers based on Active Strategy
    const dynamicCols = document.querySelectorAll('.screener-dynamic-col');

    const isStrat123 = ['strategy_1', 'strategy_2', 'strategy_3'].includes(activeStrategy);
    const isSmallOff = activeStrategy === 'strategy_7' && currentConfig && currentConfig.strat7_small_tf === 'OFF';
    const isMidOff = (activeStrategy === 'strategy_7' && currentConfig && currentConfig.strat7_mid_tf === 'OFF') || isStrat123;
    const isHighOff = (activeStrategy === 'strategy_7' && currentConfig && currentConfig.strat7_high_tf === 'OFF') || isStrat123;

    if (activeStrategy === 'strategy_7') {
        if (dynamicCols.length >= 4) {
            const tfMap = { "60": "1m", "120": "2m", "180": "3m", "300": "5m", "900": "15m", "1800": "30m", "3600": "1h", "7200": "2h", "14400": "4h", "86400": "1d" };
            dynamicCols[0].textContent = `Small (${tfMap[currentConfig?.strat7_small_tf] || '1m'})`;
            dynamicCols[1].textContent = `Mid (${tfMap[currentConfig?.strat7_mid_tf] || '5m'})`;
            dynamicCols[2].textContent = `High (${tfMap[currentConfig?.strat7_high_tf] || '1h'})`;
            dynamicCols[3].textContent = "Alignment";
            dynamicCols.forEach((col, idx) => {
                if (idx === 0) col.style.display = isSmallOff ? 'none' : '';
                else if (idx === 1) col.style.display = isMidOff ? 'none' : '';
                else if (idx === 2) col.style.display = isHighOff ? 'none' : '';
                else col.style.display = '';
            });
        }
    } else if (isStrat123) {
        if (dynamicCols.length >= 4) {
            dynamicCols[0].textContent = "TA Signal";
            dynamicCols[0].style.display = '';
            dynamicCols[1].style.display = 'none';
            dynamicCols[2].style.display = 'none';
            dynamicCols[3].textContent = "Crossover";
            dynamicCols[3].style.display = '';
        }
    } else {
        if (dynamicCols.length >= 4) {
            dynamicCols.forEach(col => col.style.display = '');
            dynamicCols[0].textContent = "Trend";
            dynamicCols[1].textContent = "Mom";
            dynamicCols[2].textContent = "Vol";
            dynamicCols[3].textContent = "Struct";
        }
    }

    body.innerHTML = Object.keys(screenerDataMap).sort().map(sym => {
        const d = screenerDataMap[sym];
        const threshold = d.threshold || (currentConfig?.contract_type === 'multiplier' ? 68 : 72);
        const streak = d.streak || 0;
        const isMultiplier = currentConfig?.contract_type === 'multiplier';

        const confColor = Math.abs(d.confidence) >= threshold ? 'text-success' : 'text-warning';

        // Multiplier Terminology Swap
        let directionLabel = d.direction;
        if (isMultiplier) {
            directionLabel = (d.direction === 'CALL' ? 'BUY' : 'SELL');
        }
        const dirColor = d.direction === 'CALL' ? 'text-success' : 'text-danger';

        let recValue = "";
        let col1 = d.trend || 0;
        let col2 = d.momentum || 0;
        let col3 = d.volatility || 0;
        let col4 = d.structure || 0;

        const now = Math.floor(Date.now() / 1000);
        const expiryEpoch = now + (d.expiry_countdown || 0);
        const countdownHtml = `<span class="screener-expiry-countdown text-warning" data-expiry="${expiryEpoch}">${formatCountdown(expiryEpoch)}</span>`;

        const sessionTag = d.is_dead_hours ? ' <span class="text-warning" title="Session Filter Active (22-06 UTC)">🌙</span>' : '';

        if (activeStrategy === 'strategy_7') {
            recValue = `${countdownHtml}${sessionTag} | ${d.atr || "0.00"}`;
            col1 = `<span class="badge ${d.summary_small?.includes('BUY') ? 'bg-success' : (d.summary_small?.includes('SELL') ? 'bg-danger' : 'bg-secondary')}">${d.summary_small || 'NEUTRAL'}</span>`;
            col2 = `<span class="badge ${d.summary_mid?.includes('BUY') ? 'bg-success' : (d.summary_mid?.includes('SELL') ? 'bg-danger' : 'bg-secondary')}">${d.summary_mid || 'NEUTRAL'}</span>`;
            col3 = `<span class="badge ${d.summary_high?.includes('BUY') ? 'bg-success' : (d.summary_high?.includes('SELL') ? 'bg-danger' : 'bg-secondary')}">${d.summary_high || 'NEUTRAL'}</span>`;

            const activeRecs = [d.summary_small, d.summary_mid, d.summary_high].filter(r => r && r !== 'OFF');
            const allBuy = activeRecs.length > 0 && activeRecs.every(r => r.includes('BUY'));
            const allSell = activeRecs.length > 0 && activeRecs.every(r => r.includes('SELL'));
            const aligned = allBuy || allSell;
            col4 = aligned ? '<span class="text-success fw-bold"><i class="bi bi-check-circle-fill"></i> Aligned</span>' : '<span class="text-muted">Mixed</span>';
        } else if (isStrat123) {
            recValue = `${countdownHtml}${sessionTag} | ${d.atr || "0.00"}`;
            col1 = `<span class="badge ${d.signal?.includes('BUY') ? 'bg-success' : (d.signal?.includes('SELL') ? 'bg-danger' : 'bg-secondary')}">${d.signal || 'NEUTRAL'}</span>`;
            col4 = d.direction === 'CALL' ? '<span class="text-success fw-bold">Above Open</span>' : (d.direction === 'PUT' ? '<span class="text-danger fw-bold">Below Open</span>' : '<span class="text-muted">Neutral</span>');
        } else {
            recValue = `${countdownHtml}${sessionTag} | ${d.atr || "0.00"}`;
            // Format scores for Strategies 5, 6, 4
            const getScoreClass = (v) => v >= 7 ? 'text-success' : (v <= 3 ? 'text-danger' : 'text-warning');
            col1 = `<span class="${getScoreClass(d.trend)} fw-bold">${d.trend || 0}</span>`;
            col2 = `<span class="${getScoreClass(d.momentum)} fw-bold">${d.momentum || 0}</span>`;
            col3 = `<span class="${getScoreClass(d.volatility)} fw-bold">${d.volatility || 0}</span>`;
            col4 = `<span class="${getScoreClass(d.structure)} fw-bold">${d.structure || 0}</span>`;
        }

        const displayConf = d.label ? `${d.label} (${d.confidence}%)` : `${d.confidence}%`;
        const streakBadge = streak >= 3 ? `<span class="badge bg-danger ms-1" title="Loss Streak: ${streak}">S</span>` : '';

        // Echo Forecast Column
        let echoHtml = '<span class="text-muted">N/A</span>';
        if (d.fcast_data && d.fcast_data.correlation) {
            const eDir = d.fcast_data.direction || "NEUTRAL";
            const eColor = eDir === 'CALL' ? 'text-success' : 'text-danger';
            echoHtml = `<span class="${eColor} fw-bold">${eDir}</span> <small class="text-muted">(${d.fcast_data.correlation.toFixed(2)})</small>`;
        }

        // TP Column
        let tpHtml = d.tp ? `<span class="text-primary">${Number(d.tp).toFixed(4)}</span>` : '<span class="text-muted">-</span>';
        // SL Column
        let slHtml = d.sl ? `<span class="text-danger">${Number(d.sl).toFixed(4)}</span>` : '<span class="text-muted">-</span>';
        // RR Column
        let rrHtml = d.rr ? `<span class="text-info fw-bold">${Number(d.rr).toFixed(2)}</span>` : '<span class="text-muted">-</span>';

        // Final Signal Label
        let signalLabelHtml = `<span class="badge ${d.signal === 'BUY' ? 'bg-success' : (d.signal === 'SELL' ? 'bg-danger' : 'bg-secondary')}">${d.signal}</span>`;

        return `
            <tr>
                <td><strong>${sym}</strong>${streakBadge}</td>
                <td class="${confColor} fw-bold">${displayConf} <small class="text-muted">/${threshold}%</small></td>
                <td class="${dirColor} fw-bold">${signalLabelHtml} / ${directionLabel}</td>
                <td><small>${recValue}</small></td>
                <td><small>${echoHtml}</small></td>
                <td><small>${tpHtml}</small></td>
                <td><small>${slHtml}</small></td>
                <td><small>${rrHtml}</small></td>
                <td style="${(activeStrategy === 'strategy_7' && isSmallOff) || isStrat123 ? 'display:none' : ''}">${col1}</td>
                <td style="${(activeStrategy === 'strategy_7' && isMidOff) || isStrat123 ? 'display:none' : ''}">${col2}</td>
                <td style="${(activeStrategy === 'strategy_7' && isHighOff) || isStrat123 ? 'display:none' : ''}">${col3}</td>
                <td>${col4}</td>
            </tr>
        `;
    }).join('');
}

function updateActiveTrades(trades) {
    const container = document.getElementById('activeTradesContainer');
    if (!trades || !Array.isArray(trades) || trades.length === 0) {
        container.innerHTML = '<p class="text-muted text-center py-4">No active positions</p>';
        return;
    }

    container.innerHTML = trades.map(t => {
        const pnl = typeof t.pnl === 'number' ? t.pnl : 0;
        const entry = typeof t.entry_spot_price === 'number' ? t.entry_spot_price : 0;
        const stake = typeof t.stake === 'number' ? t.stake : 0;
        const typeLabel = t.type ? t.type.toLowerCase() : 'unknown';

        const statusLabel = t.status === 'Active' ? '' : ` [${t.status}]`;
        const freerideLabel = t.is_freeride ? ' <span class="badge bg-success">FREE RIDE</span>' : '';

        return `
            <div class="trade-card ${typeLabel}">
                <div class="d-flex justify-content-between align-items-center">
                    <strong>${t.symbol || 'Unknown'} (${t.type || '???'})${statusLabel}${freerideLabel}</strong>
                    <div class="d-flex align-items-center gap-3">
                        <span class="${pnl >= 0 ? 'text-success' : 'text-danger'} fw-bold">$${pnl.toFixed(1)}</span>
                        <button class="btn btn-sm btn-outline-danger" onclick="closeTrade('${t.id}')" title="Close Trade">
                            <i class="bi bi-x-circle"></i>
                        </button>
                    </div>
                </div>
                <div class="small text-muted d-flex justify-content-between mt-1">
                    <div>ID: ${t.id} | Entry: ${entry.toFixed(4)} | Stake: $${stake.toFixed(1)}</div>
                    <div class="expiry-countdown text-warning" data-expiry="${t.expiry_time}">${formatCountdown(t.expiry_time)}</div>
                </div>
            </div>
        `;
    }).join('');
}

function closeTrade(id) {
    if (confirm(`Are you sure you want to close trade ${id}?`)) {
        socket.emit('close_trade', { contract_id: id });
    }
}

function startCountdownTimer() {
    setInterval(() => {
        document.querySelectorAll('.expiry-countdown').forEach(el => {
            const expiry = parseInt(el.getAttribute('data-expiry'));
            el.textContent = formatCountdown(expiry);
        });

        // Update Screener Countdown
        document.querySelectorAll('.screener-expiry-countdown').forEach(el => {
            const expiry = parseInt(el.getAttribute('data-expiry'));
            el.textContent = formatCountdown(expiry);
        });
    }, 1000);
}

function formatCountdown(expiryEpoch) {
    if (!expiryEpoch) return "";
    const now = Math.floor(Date.now() / 1000);
    let diff = expiryEpoch - now;
    if (diff <= 0) return "Expired";

    const h = Math.floor(diff / 3600);
    const m = Math.floor((diff % 3600) / 60);
    const s = diff % 60;

    return [h, m, s].map(v => v.toString().padStart(2, '0')).join(':');
}

async function loadConfig() {
    const res = await fetch('/api/config');
    currentConfig = await res.json();
    activeStrategy = currentConfig.active_strategy || 'strategy_1';
    updateConfigLabels(activeStrategy);
    updateSymbolList();
}

function updateSymbolList() {
    const list = document.getElementById('symbolList');
    list.innerHTML = currentConfig.symbols.map(s => `
        <li class="list-group-item d-flex justify-content-between align-items-center bg-transparent border-secondary text-light">
            ${s}
            <i class="bi bi-trash text-danger cursor-pointer" onclick="removeSymbol('${s}')" style="cursor: pointer;"></i>
        </li>
    `).join('');
}

function removeSymbol(symbol) {
    currentConfig.symbols = currentConfig.symbols.filter(s => s !== symbol);
    updateSymbolList();
    saveLiveConfig();
}

async function saveConfig() {
    const config = {
        deriv_api_token: document.getElementById('configApiToken').value,
        deriv_app_id: document.getElementById('configAppId').value,
        use_fixed_balance: document.getElementById('configUseFixedBalance').checked,
        balance_value: parseFloat(document.getElementById('configBalanceValue').value),
        max_daily_loss_pct: parseFloat(document.getElementById('configMaxDailyLoss').value),
        max_daily_profit_pct: parseFloat(document.getElementById('configMaxDailyProfit').value),
        tp_enabled: document.getElementById('configTpEnabled').checked,
        tp_value: parseFloat(document.getElementById('configTpValue').value),
        sl_enabled: document.getElementById('configSlEnabled').checked,
        sl_value: parseFloat(document.getElementById('configSlValue').value),
        force_close_enabled: document.getElementById('configForceCloseEnabled').checked,
        force_close_duration: parseInt(document.getElementById('configForceCloseDuration').value),
        active_strategy: document.getElementById('configActiveStrategy').value,
        contract_type: document.getElementById('configContractType').value,
        custom_expiry: document.getElementById('configCustomExpiry').value,
        entry_type: document.getElementById('configEntryType').value,
        is_demo: document.getElementById('configIsDemo').checked,
        strat7_small_tf: document.getElementById('configStrat7SmallTF').value,
        strat7_mid_tf: document.getElementById('configStrat7MidTF').value,
        strat7_high_tf: document.getElementById('configStrat7HighTF').value,
        symbols: currentConfig.symbols
    };

    const res = await fetch('/api/config', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(config)
    });

    if (res.ok) {
        currentConfig = config;
        activeStrategy = config.active_strategy;
        updateConfigLabels(activeStrategy);
        configModal.hide();
    }
}

async function saveLiveConfig() {
    await fetch('/api/config', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(currentConfig)
    });
}
