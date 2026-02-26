const socket = io();

let currentConfig = null;
const configModal = new bootstrap.Modal(document.getElementById('configModal'));
let isBotRunning = false;

document.addEventListener('DOMContentLoaded', () => {
    loadConfig();
    setupEventListeners();
    setupSocketListeners();
});

function setupEventListeners() {
    document.getElementById('startStopBtn').addEventListener('click', () => {
        if (isBotRunning) {
            socket.emit('stop_bot');
        } else {
            socket.emit('start_bot');
        }
    });

    document.getElementById('configBtn').addEventListener('click', () => {
        renderConfig();
        configModal.show();
    });

    document.getElementById('saveConfigBtn').addEventListener('click', saveConfig);

    document.getElementById('addSymbolBtn').addEventListener('click', () => {
        const symbol = prompt("Enter Binance Symbol (e.g., BTCUSDT):");
        if (symbol && currentConfig) {
            const upperSymbol = symbol.toUpperCase();
            if (!currentConfig.symbols.includes(upperSymbol)) {
                currentConfig.symbols.push(upperSymbol);
                updateSymbolList();
                saveLiveConfig();
            }
        }
    });

    document.getElementById('clearConsoleBtn').addEventListener('click', () => {
        document.getElementById('consoleOutput').innerHTML = '';
    });
}

function setupSocketListeners() {
    socket.on('bot_status', (data) => {
        isBotRunning = data.running;
        const btn = document.getElementById('startStopBtn');
        const status = document.getElementById('botStatus');
        if (isBotRunning) {
            btn.innerHTML = '<i class="bi bi-stop-fill"></i> Stop';
            btn.className = 'btn btn-sm btn-danger';
            status.textContent = 'Running';
            status.className = 'badge bg-success ms-2 status-badge';
        } else {
            btn.innerHTML = '<i class="bi bi-play-fill"></i> Start';
            btn.className = 'btn btn-sm btn-accent';
            status.textContent = 'Stopped';
            status.className = 'badge bg-secondary ms-2 status-badge';
        }
    });

    socket.on('account_update', (data) => {
        document.getElementById('balanceDisplay').textContent = `$${Number(data.total_balance || 0).toFixed(2)}`;

        const positionsTable = document.getElementById('positionsTableBody');
        if (data.positions && data.positions.length > 0) {
            positionsTable.innerHTML = data.positions.map(p => `
                <tr>
                    <td>${p.account}</td>
                    <td>${p.symbol}</td>
                    <td class="${p.amount > 0 ? 'text-success' : 'text-danger'}">${p.amount}</td>
                    <td>${Number(p.entryPrice).toFixed(4)}</td>
                    <td class="${p.unrealizedProfit >= 0 ? 'text-success' : 'text-danger'}">${Number(p.unrealizedProfit).toFixed(2)}</td>
                    <td><button class="btn btn-xs btn-outline-danger py-0 px-1" style="font-size: 0.7rem" onclick="closePosition('${p.account}', '${p.symbol}')">Close</button></td>
                </tr>
            `).join('');
        } else {
            positionsTable.innerHTML = '<tr><td colspan="6" class="text-center text-muted">No open positions</td></tr>';
        }
    });

    socket.on('console_log', (data) => {
        const consoleOutput = document.getElementById('consoleOutput');
        const line = document.createElement('div');
        line.style.marginBottom = '2px';
        line.innerHTML = `<span class="text-muted small">[${data.timestamp}]</span> <span class="${data.level === 'error' ? 'text-danger' : (data.level === 'warning' ? 'text-warning' : 'text-success')}">${data.message}</span>`;
        consoleOutput.appendChild(line);
        consoleOutput.scrollTop = consoleOutput.scrollHeight;
    });

    socket.on('success', (data) => console.log('Success:', data.message));
    socket.on('error', (data) => alert('Error: ' + data.message));
}

async function loadConfig() {
    const res = await fetch('/api/config');
    currentConfig = await res.json();
    updateUIFromConfig();
}

function updateUIFromConfig() {
    if (!currentConfig) return;
    document.getElementById('displaySymbol').textContent = `${currentConfig.strategy.direction} 0.0000000 ${currentConfig.strategy.symbol}`;
    document.getElementById('inputQuantity').value = currentConfig.strategy.total_quantity;
    document.getElementById('inputLeverage').value = currentConfig.strategy.leverage;
    document.getElementById('inputMarginType').value = currentConfig.strategy.margin_type;
    document.getElementById('inputEntryPrice').value = currentConfig.strategy.entry_price;
    document.getElementById('inputTotal').value = (currentConfig.strategy.total_quantity * currentConfig.strategy.entry_price).toFixed(2);

    document.getElementById('demoBadge').textContent = currentConfig.is_demo ? 'Demo' : 'Live';
    document.getElementById('demoBadge').className = currentConfig.is_demo ? 'badge bg-info ms-1 status-badge' : 'badge bg-danger ms-1 status-badge';

    updateSymbolList();
    updateTPGrid();
}

function closePosition(account, symbol) {
    if (confirm(`Close position for ${symbol} on account ${account}?`)) {
        socket.emit('close_trade', { account, symbol });
    }
}

function updateSymbolList() {
    const list = document.getElementById('symbolList');
    list.innerHTML = currentConfig.symbols.map(s => `
        <li class="list-group-item d-flex justify-content-between align-items-center bg-transparent border-secondary text-light py-1 small">
            ${s}
            <i class="bi bi-trash text-danger cursor-pointer" onclick="removeSymbol('${s}')" style="cursor: pointer; font-size: 0.8rem"></i>
        </li>
    `).join('');
    document.getElementById('activeAccountsDisplay').textContent = currentConfig.api_accounts.filter(a => a.enabled).length;
}

function removeSymbol(symbol) {
    currentConfig.symbols = currentConfig.symbols.filter(s => s !== symbol);
    updateSymbolList();
    saveLiveConfig();
}

function updateTPGrid() {
    const container = document.getElementById('tpGridContainer');
    const strat = currentConfig.strategy;
    const fractions = strat.total_fractions;
    const deviation = strat.price_deviation;
    const fractionPct = (100 / fractions).toFixed(2);

    let html = '';
    for (let i = 1; i <= fractions; i++) {
        const pct = (i * deviation).toFixed(2);
        html += `
            <div class="tp-grid-row">
                <span class="text-accent">${pct} %</span>
                <span>${fractionPct}%</span>
                <span class="text-muted"><i class="bi bi-x"></i></span>
            </div>
        `;
    }
    container.innerHTML = html;
}

function renderConfig() {
    const accContainer = document.getElementById('accountConfigs');
    accContainer.innerHTML = currentConfig.api_accounts.map((acc, i) => `
        <div class="mb-3 p-2 border border-secondary rounded">
            <div class="d-flex justify-content-between align-items-center mb-2">
                <span class="fw-bold">Account ${i+1}: ${acc.name}</span>
                <div class="form-check form-switch">
                    <input class="form-check-input" type="checkbox" id="acc_enabled_${i}" ${acc.enabled ? 'checked' : ''}>
                    <label class="form-check-label small">Enabled</label>
                </div>
            </div>
            <div class="row g-2">
                <div class="col-12">
                    <label class="small text-muted">API Key</label>
                    <input type="text" class="form-control form-control-sm" id="acc_key_${i}" value="${acc.api_key}">
                </div>
                <div class="col-12">
                    <label class="small text-muted">API Secret</label>
                    <input type="password" class="form-control form-control-sm" id="acc_secret_${i}" value="${acc.api_secret}">
                </div>
                <div class="col-12 text-end">
                    <button class="btn btn-xs btn-outline-info small py-0" onclick="testAccount(${i})">Test Connection</button>
                </div>
            </div>
        </div>
    `).join('');

    document.getElementById('configIsDemo').checked = currentConfig.is_demo;
    document.getElementById('configSymbol').value = currentConfig.strategy.symbol;
    document.getElementById('configDirection').value = currentConfig.strategy.direction;
    document.getElementById('configTotalQty').value = currentConfig.strategy.total_quantity;
    document.getElementById('configFractions').value = currentConfig.strategy.total_fractions;
    document.getElementById('configDeviation').value = currentConfig.strategy.price_deviation;
    document.getElementById('configEntryPrice').value = currentConfig.strategy.entry_price;
    document.getElementById('configLeverage').value = currentConfig.strategy.leverage;
    document.getElementById('configMarginType').value = currentConfig.strategy.margin_type;
}

async function testAccount(index) {
    const api_key = document.getElementById(`acc_key_${index}`).value;
    const api_secret = document.getElementById(`acc_secret_${index}`).value;

    if (!api_key || !api_secret) {
        alert("Please enter API key and secret.");
        return;
    }

    const res = await fetch('/api/test_api_key', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ api_key, api_secret })
    });
    const data = await res.json();
    alert(data.message);
}

async function saveConfig() {
    const api_accounts = currentConfig.api_accounts.map((acc, i) => ({
        name: acc.name,
        enabled: document.getElementById(`acc_enabled_${i}`).checked,
        api_key: document.getElementById(`acc_key_${i}`).value,
        api_secret: document.getElementById(`acc_secret_${i}`).value
    }));

    const config = {
        api_accounts,
        is_demo: document.getElementById('configIsDemo').checked,
        symbols: currentConfig.symbols,
        strategy: {
            symbol: document.getElementById('configSymbol').value.toUpperCase(),
            direction: document.getElementById('configDirection').value,
            total_quantity: parseFloat(document.getElementById('configTotalQty').value),
            total_fractions: parseInt(document.getElementById('configFractions').value),
            price_deviation: parseFloat(document.getElementById('configDeviation').value),
            entry_price: parseFloat(document.getElementById('configEntryPrice').value),
            leverage: parseInt(document.getElementById('configLeverage').value),
            margin_type: document.getElementById('configMarginType').value
        },
        log_level: currentConfig.log_level
    };

    const res = await fetch('/api/config', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(config)
    });

    if (res.ok) {
        currentConfig = config;
        updateUIFromConfig();
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
