#!/usr/bin/env python3
"""
NautilusTrader BTC Options Straddle - Visual Web Dashboard

A zero-dependency real-time web monitor and interactive presentation tool.
Serves a Bloomberg/dark-themed quantitative trading terminal at http://localhost:8000.
"""

from decimal import Decimal
import http.server
import json
import socketserver
import sys
import threading
import time
from pathlib import Path

# Add project root to sys.path
root_dir = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(root_dir))

from nautilus_trader.model.data import QuoteTick
from nautilus_trader.model.enums import AssetClass, OptionKind, OrderSide
from nautilus_trader.model.identifiers import InstrumentId, Symbol, Venue
from nautilus_trader.model.instruments import OptionContract
from nautilus_trader.model.objects import Currency, Price, Quantity

from strategy.straddle_config import BtcStraddleConfig
from strategy.straddle_strategy import BtcStraddleStrategy

PORT = 8000

# Global shared state
state = {
    "btc_price": 90450.0,
    "atm_strike": 90000.0,
    "expiry": "28MAR25",
    "call_entry": 2500.0,
    "put_entry": 2400.0,
    "combined_entry": 4900.0,
    "call_ask": 2505.0,
    "put_ask": 2405.0,
    "combined_buyback": 4910.0,
    "pct_change": 0.20,
    "sl_pct": 1.0,
    "tp_pct": 2.0,
    "sl_price": 4949.0,
    "tp_price": 4802.0,
    "pnl": -10.0,
    "status": "ACTIVE (SHORT STRADDLE)",
    "is_exiting": False,
    "logs": [
        "[SYSTEM] NautilusTrader Kernel initialized.",
        "[DATA] Subscribed to BTC options stream on Bybit venue.",
        "[STRATEGY] Underlying reference price: $90,450.00.",
        "[STRATEGY] Selected nearest ATM strike: $90,000.00 (28MAR25).",
        "[EXECUTION] Submitted simultaneous SELL market orders for Call & Put.",
        "[ORDER] Call leg filled at $2,500.00.",
        "[ORDER] Put leg filled at $2,400.00.",
        "[PORTFOLIO] Combined entry premium established: $4,900.00.",
        "[RISK] Automated Level 2 Risk Active: SL (+1.0%: $4,949.00) | TP (-2.0%: $4,802.00).",
    ],
}

HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>NautilusTrader - BTC Options Straddle Terminal</title>
    <style>
        :root {
            --bg: #0c1017;
            --panel: #161b22;
            --panel-border: #30363d;
            --text: #e6edf3;
            --text-muted: #8b949e;
            --accent: #58a6ff;
            --green: #2ea043;
            --green-glow: rgba(46, 160, 67, 0.2);
            --red: #f85149;
            --red-glow: rgba(248, 81, 73, 0.2);
            --gold: #d29922;
        }
        * { box-sizing: border-box; margin: 0; padding: 0; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, monospace; }
        body { background: var(--bg); color: var(--text); padding: 20px; font-size: 14px; }
        .header { display: flex; justify-content: space-between; align-items: center; border-bottom: 1px solid var(--panel-border); padding-bottom: 15px; margin-bottom: 20px; }
        .logo { font-size: 20px; font-weight: 700; letter-spacing: 0.5px; color: var(--accent); display: flex; align-items: center; gap: 10px; }
        .badge { background: #21262d; border: 1px solid #388bfd; color: #58a6ff; padding: 4px 10px; border-radius: 20px; font-size: 11px; font-weight: 600; text-transform: uppercase; }
        .grid-top { display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 15px; margin-bottom: 20px; }
        .card { background: var(--panel); border: 1px solid var(--panel-border); border-radius: 8px; padding: 15px; }
        .card-title { font-size: 11px; text-transform: uppercase; color: var(--text-muted); font-weight: 600; margin-bottom: 8px; }
        .card-value { font-size: 22px; font-weight: 700; }
        .card-sub { font-size: 12px; margin-top: 5px; color: var(--text-muted); }
        .grid-main { display: grid; grid-template-columns: 2fr 1fr; gap: 20px; margin-bottom: 20px; }
        @media(max-width: 900px) { .grid-main { grid-template-columns: 1fr; } }
        .risk-bar-container { background: #21262d; height: 16px; border-radius: 8px; position: relative; margin: 25px 0 15px 0; overflow: hidden; display: flex; }
        .zone-tp { background: var(--green); width: 30%; height: 100%; opacity: 0.8; }
        .zone-neutral { background: #30363d; width: 40%; height: 100%; }
        .zone-sl { background: var(--red); width: 30%; height: 100%; opacity: 0.8; }
        .marker { position: absolute; top: -6px; height: 28px; width: 4px; background: #fff; border-radius: 2px; box-shadow: 0 0 8px #fff; transition: left 0.3s ease; }
        .risk-labels { display: flex; justify-content: space-between; font-size: 11px; font-weight: 600; }
        .legs-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 15px; margin-top: 15px; }
        .leg-card { background: #0d1117; border: 1px solid var(--panel-border); border-radius: 6px; padding: 12px; }
        .btn-group { display: flex; flex-direction: column; gap: 10px; }
        button { background: #21262d; border: 1px solid var(--panel-border); color: var(--text); padding: 10px 14px; border-radius: 6px; cursor: pointer; font-weight: 600; font-size: 13px; transition: all 0.2s; text-align: left; }
        button:hover { background: #30363d; border-color: #8b949e; }
        button.tp-btn { border-left: 4px solid var(--green); }
        button.sl-btn { border-left: 4px solid var(--red); }
        button.reset-btn { border-left: 4px solid var(--accent); }
        .console { background: #010409; border: 1px solid var(--panel-border); border-radius: 8px; padding: 12px; height: 200px; overflow-y: auto; font-family: monospace; font-size: 12px; }
        .log-entry { margin-bottom: 4px; color: #7ee787; }
        .log-warn { color: #f2cc60; }
        .log-err { color: #ff7b72; }
        .status-badge { display: inline-block; padding: 3px 8px; border-radius: 4px; font-size: 12px; font-weight: 700; }
        .status-active { background: rgba(46, 160, 67, 0.2); color: #3fb950; border: 1px solid #238636; }
        .status-closed { background: rgba(248, 81, 73, 0.2); color: #f85149; border: 1px solid #da3633; }
    </style>
</head>
<body>
    <div class="header">
        <div class="logo">
            <span>⚡ NautilusTrader</span>
            <span class="badge">Bybit Options Engine</span>
        </div>
        <div>
            <span id="conn-status" style="color: #3fb950; font-weight: 600;">● Engine Online</span>
            <span style="color: var(--text-muted); margin-left: 15px;" id="clock">--:--:-- UTC</span>
        </div>
    </div>

    <div class="grid-top">
        <div class="card">
            <div class="card-title">Underlying Reference</div>
            <div class="card-value" id="btc-price">$90,450.00</div>
            <div class="card-sub">BTCUSDT Linear Index</div>
        </div>
        <div class="card">
            <div class="card-title">ATM Straddle Selection</div>
            <div class="card-value" style="color: var(--gold);" id="atm-strike">$90,000.00</div>
            <div class="card-sub" id="expiry-sub">Expiry: 28MAR25</div>
        </div>
        <div class="card">
            <div class="card-title">Combined Entry Premium</div>
            <div class="card-value" id="entry-premium">$4,900.00</div>
            <div class="card-sub">Call $2,500 + Put $2,400</div>
        </div>
        <div class="card">
            <div class="card-title">Current Buyback Ask</div>
            <div class="card-value" id="buyback-price">$4,910.00</div>
            <div class="card-sub" id="pct-change">+0.20% vs Entry</div>
        </div>
        <div class="card">
            <div class="card-title">Strategy Status</div>
            <div class="card-value" style="font-size: 15px; margin-top: 4px;">
                <span class="status-badge status-active" id="status-badge">ACTIVE</span>
            </div>
            <div class="card-sub" id="pnl-sub">PnL: -$10.00 USDC</div>
        </div>
    </div>

    <div class="grid-main">
        <div class="card">
            <div style="display: flex; justify-content: space-between; align-items: center;">
                <div class="card-title">Level 2 Risk Monitoring (Combined Ask Valuation)</div>
                <div style="font-size: 11px; color: var(--text-muted);">Real-time Ask Stream</div>
            </div>

            <!-- Risk Gauge -->
            <div class="risk-bar-container">
                <div class="zone-tp" title="Take Profit Zone (<= -2%)"></div>
                <div class="zone-neutral" title="Holding Zone (-2% to +1%)"></div>
                <div class="zone-sl" title="Stop Loss Zone (>= +1%)"></div>
                <div class="marker" id="gauge-marker" style="left: 45%;"></div>
            </div>
            <div class="risk-labels">
                <span style="color: var(--green);">🎯 Take-Profit Target: $4,802.00 (-2.0%)</span>
                <span style="color: var(--text-muted);">Neutral Range</span>
                <span style="color: var(--red);">🛑 Stop-Loss Target: $4,949.00 (+1.0%)</span>
            </div>

            <!-- Legs -->
            <div class="legs-grid">
                <div class="leg-card">
                    <div style="display: flex; justify-content: space-between; margin-bottom: 6px;">
                        <span style="font-weight: 700; color: #58a6ff;">Call Leg (SHORT)</span>
                        <span style="color: var(--text-muted);">Qty: 0.01</span>
                    </div>
                    <div style="font-size: 11px; color: var(--text-muted);" id="call-symbol">BTC-28MAR25-90000-C-OPTION</div>
                    <div style="margin-top: 10px; display: flex; justify-content: space-between;">
                        <span>Entry: <b id="call-entry">$2,500.00</b></span>
                        <span>Ask: <b id="call-ask" style="color: #f85149;">$2,505.00</b></span>
                    </div>
                </div>
                <div class="leg-card">
                    <div style="display: flex; justify-content: space-between; margin-bottom: 6px;">
                        <span style="font-weight: 700; color: #d2a8ff;">Put Leg (SHORT)</span>
                        <span style="color: var(--text-muted);">Qty: 0.01</span>
                    </div>
                    <div style="font-size: 11px; color: var(--text-muted);" id="put-symbol">BTC-28MAR25-90000-P-OPTION</div>
                    <div style="margin-top: 10px; display: flex; justify-content: space-between;">
                        <span>Entry: <b id="put-entry">$2,400.00</b></span>
                        <span>Ask: <b id="put-ask" style="color: #f85149;">$2,405.00</b></span>
                    </div>
                </div>
            </div>
        </div>

        <!-- Controls -->
        <div class="card">
            <div class="card-title">Interactive Walkthrough Controls</div>
            <div class="btn-group">
                <button class="tp-btn" onclick="triggerScenario('tp')">
                    🎯 Simulate Volatility Crush
                    <div style="font-size: 11px; color: var(--text-muted); font-weight: normal; margin-top: 2px;">
                        Ask drops to $4,760 (-2.85%) &rarr; Take-Profit
                    </div>
                </button>
                <button class="sl-btn" onclick="triggerScenario('sl')">
                    🛑 Simulate Volatility Spike
                    <div style="font-size: 11px; color: var(--text-muted); font-weight: normal; margin-top: 2px;">
                        Ask jumps to $5,000 (+2.04%) &rarr; Stop-Loss
                    </div>
                </button>
                <button class="reset-btn" onclick="triggerScenario('reset')">
                    🔄 Reset Position State
                    <div style="font-size: 11px; color: var(--text-muted); font-weight: normal; margin-top: 2px;">
                        Re-establish short straddle at $4,900
                    </div>
                </button>
            </div>
        </div>
    </div>

    <!-- Live Execution Logs -->
    <div class="card">
        <div class="card-title" style="margin-bottom: 10px;">Execution & Risk Event Log</div>
        <div class="console" id="console-logs"></div>
    </div>

    <script>
        function updateClock() {
            document.getElementById('clock').innerText = new Date().toUTCString().split(' ')[4] + ' UTC';
        }
        setInterval(updateClock, 1000);
        updateClock();

        function refreshData() {
            fetch('/api/state')
                .then(r => r.json())
                .then(d => {
                    document.getElementById('btc-price').innerText = '$' + d.btc_price.toLocaleString('en-US', {minimumFractionDigits: 2});
                    document.getElementById('atm-strike').innerText = '$' + d.atm_strike.toLocaleString('en-US', {minimumFractionDigits: 2});
                    document.getElementById('entry-premium').innerText = '$' + d.combined_entry.toLocaleString('en-US', {minimumFractionDigits: 2});
                    document.getElementById('buyback-price').innerText = '$' + d.combined_buyback.toLocaleString('en-US', {minimumFractionDigits: 2});
                    
                    const pctElem = document.getElementById('pct-change');
                    const sign = d.pct_change >= 0 ? '+' : '';
                    pctElem.innerText = sign + d.pct_change.toFixed(2) + '% vs Entry';
                    pctElem.style.color = d.pct_change >= 1.0 ? '#f85149' : (d.pct_change <= -2.0 ? '#3fb950' : '#8b949e');

                    document.getElementById('call-ask').innerText = '$' + d.call_ask.toFixed(2);
                    document.getElementById('put-ask').innerText = '$' + d.put_ask.toFixed(2);
                    document.getElementById('pnl-sub').innerText = 'PnL: ' + (d.pnl >= 0 ? '+$' : '-$') + Math.abs(d.pnl).toFixed(2) + ' USDC';

                    // Update Status Badge
                    const badge = document.getElementById('status-badge');
                    badge.innerText = d.is_exiting ? 'CLOSED (' + (d.pct_change >= 1.0 ? 'STOP-LOSS' : 'TAKE-PROFIT') + ')' : 'ACTIVE';
                    badge.className = 'status-badge ' + (d.is_exiting ? 'status-closed' : 'status-active');

                    // Marker position: -3% is 0%, +2% is 100%
                    const minPct = -3.0;
                    const maxPct = 2.0;
                    const clamped = Math.max(minPct, Math.min(maxPct, d.pct_change));
                    const markerLeft = ((clamped - minPct) / (maxPct - minPct)) * 100;
                    document.getElementById('gauge-marker').style.left = markerLeft + '%';

                    // Logs
                    const consoleElem = document.getElementById('console-logs');
                    consoleElem.innerHTML = d.logs.map(l => {
                        let cls = 'log-entry';
                        if (l.includes('STOP-LOSS') || l.includes('REJECTED')) cls = 'log-err';
                        if (l.includes('TAKE-PROFIT') || l.includes('CLOSED')) cls = 'log-warn';
                        return `<div class="${cls}">${l}</div>`;
                    }).join('');
                    consoleElem.scrollTop = consoleElem.scrollHeight;
                });
        }

        function triggerScenario(type) {
            fetch('/api/scenario?type=' + type, { method: 'POST' })
                .then(r => r.json())
                .then(() => refreshData());
        }

        setInterval(refreshData, 1000);
        refreshData();
    </script>
</body>
</html>
"""


class DashboardHandler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/" or self.path == "/index.html":
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(HTML_TEMPLATE.encode("utf-8"))
        elif self.path == "/api/state":
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps(state).encode("utf-8"))
        else:
            self.send_response(404)
            self.end_headers()

    def do_POST(self):
        if self.path.startswith("/api/scenario"):
            query = self.path.split("?")[-1]
            params = dict(qc.split("=") for qc in query.split("&") if "=" in qc)
            sc_type = params.get("type", "")

            if sc_type == "tp":
                # Take-Profit: Volatility Crush
                state["call_ask"] = 2380.0
                state["put_ask"] = 2380.0
                state["combined_buyback"] = 4760.0
                state["pct_change"] = ((4760.0 - 4900.0) / 4900.0) * 100.0  # -2.86%
                state["pnl"] = 140.0
                state["is_exiting"] = True
                state["logs"].append(
                    f"[{time.strftime('%H:%M:%S')}] 🎯 TAKE-PROFIT TRIGGERED! Buyback cost: $4,760.00 (-2.86% <= -2.0%).",
                )
                state["logs"].append(
                    f"[{time.strftime('%H:%M:%S')}] [EXECUTION] Submitting reduce-only closing BUY orders for Call & Put.",
                )
                state["logs"].append(
                    f"[{time.strftime('%H:%M:%S')}] [PORTFOLIO] Positions CLOSED. Realized PnL: +$140.00 USDC.",
                )

            elif sc_type == "sl":
                # Stop-Loss: Volatility Spike
                state["call_ask"] = 2580.0
                state["put_ask"] = 2420.0
                state["combined_buyback"] = 5000.0
                state["pct_change"] = ((5000.0 - 4900.0) / 4900.0) * 100.0  # +2.04%
                state["pnl"] = -100.0
                state["is_exiting"] = True
                state["logs"].append(
                    f"[{time.strftime('%H:%M:%S')}] 🛑 STOP-LOSS TRIGGERED! Buyback cost: $5,000.00 (+2.04% >= +1.0%).",
                )
                state["logs"].append(
                    f"[{time.strftime('%H:%M:%S')}] [EXECUTION] Submitting reduce-only closing BUY orders for Call & Put.",
                )
                state["logs"].append(
                    f"[{time.strftime('%H:%M:%S')}] [PORTFOLIO] Positions CLOSED. Realized Loss: -$100.00 USDC.",
                )

            elif sc_type == "reset":
                state["call_ask"] = 2505.0
                state["put_ask"] = 2405.0
                state["combined_buyback"] = 4910.0
                state["pct_change"] = ((4910.0 - 4900.0) / 4900.0) * 100.0
                state["pnl"] = -10.0
                state["is_exiting"] = False
                state["logs"].append(
                    f"[{time.strftime('%H:%M:%S')}] [RESET] Re-opened Short Straddle at $4,900.00 entry premium.",
                )

            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"success": True}).encode("utf-8"))
        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, format, *args):
        pass  # Quiet HTTP logs


def run_server():
    socketserver.TCPServer.allow_reuse_address = True
    with socketserver.TCPServer(("", PORT), DashboardHandler) as httpd:
        print("=" * 70)
        print("  NAUTILUS TRADER - BTC OPTIONS STRADDLE LIVE DASHBOARD")
        print("=" * 70)
        print(f"\n✓ Dashboard Server running at: http://localhost:{PORT}")
        print("  Press Ctrl+C to stop the dashboard server.\n")
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\nShutting down dashboard server...")
            httpd.server_close()


if __name__ == "__main__":
    run_server()

