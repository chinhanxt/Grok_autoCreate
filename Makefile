# ==============================================================================
# Makefile for Grok & x.ai Account Creator
# ==============================================================================

VENV := ./venv
PYTHON := $(shell if [ -f $(VENV)/bin/python ]; then echo $(VENV)/bin/python; else echo python3; fi)
PIP := $(shell if [ -f $(VENV)/bin/pip ]; then echo $(VENV)/bin/pip; else echo pip; fi)
PYTEST := $(shell if [ -f $(VENV)/bin/pytest ]; then echo $(VENV)/bin/pytest; else echo pytest; fi)

HOST ?= 127.0.0.1
PORT ?= 7860

.PHONY: all help dev start stop cli sync-oauth batch test install clean tor

all: help

help:
	@echo "=================================================="
	@echo "  ⚡ Grok & x.ai Account Creator Management ⚡"
	@echo "=================================================="
	@echo "  make dev          - Run Web UI in Development Mode (auto-reload)"
	@echo "                      Default: http://127.0.0.1:7860"
	@echo "                      Custom port: make dev PORT=8000 HOST=0.0.0.0"
	@echo "  make start        - Run Web UI in Production Mode"
	@echo "  make stop         - Stop Web UI on PORT (default 7860) and Tor 1/2"
	@echo "  make cli          - Run interactive CLI mode"
	@echo "  make sync-oauth   - Sync OAuth 2.0 CLI Tokens for accounts"
	@echo "  make batch        - Run 100 accounts batch creator script"
	@echo "  make test         - Run test suite with pytest"
	@echo "  make install      - Install Python dependencies & Playwright browsers"
	@echo "  make tor          - Cài (user-space) và khởi động Tor 1 (9050) + Tor 2 (9052)"
	@echo "  make clean        - Clean cache and temporary files"
	@echo "=================================================="

tor:
	@echo "🧅 Đảm bảo Tor 1 (9050/9051) và Tor 2 (9052/9053) đang chạy..."
	$(PYTHON) -c "from core.tor_launcher import ensure_local_tors; ensure_local_tors()"

dev: tor
	@echo "🚀 Khởi động Web Dashboard ở chế độ Dev (Auto-reload)..."
	@echo "👉 Truy cập: http://$(HOST):$(PORT)"
	$(PYTHON) web_app.py --reload --host $(HOST) --port $(PORT)

start: tor
	@echo "🚀 Khởi động Web Dashboard..."
	@echo "👉 Truy cập: http://$(HOST):$(PORT)"
	$(PYTHON) web_app.py --host $(HOST) --port $(PORT)

stop:
	@echo "🛑 Dừng Web UI (port $(PORT)) và Tor 1/2..."
	@pids=$$(ss -lntp 2>/dev/null | awk '/:$(PORT)/ { while (match($$0, /pid=[0-9]+/)) { print substr($$0, RSTART+4, RLENGTH-4); $$0=substr($$0, RSTART+RLENGTH) } }' | sort -u); \
	if [ -n "$$pids" ]; then echo "$$pids" | xargs -r kill; echo "✔ Đã dừng Web UI (pid: $$pids)"; else echo "• Web UI không chạy trên port $(PORT)"; fi
	@for pidfile in .run/tor1/tor.pid .run/tor2/tor.pid; do \
		if [ -f $$pidfile ]; then \
			pid=$$(cat $$pidfile); \
			if kill -0 $$pid 2>/dev/null; then kill $$pid && echo "✔ Đã dừng $$(basename $$(dirname $$pidfile)) (pid: $$pid)"; else echo "• $$(basename $$(dirname $$pidfile)) không chạy"; fi; \
		fi; \
	done
	@pkill -f 'web_app.py' 2>/dev/null || true

cli:
	$(PYTHON) cli.py

sync-oauth:
	$(PYTHON) sync_all_oauth.py

batch:
	$(PYTHON) batch_create_100_oauth.py

test:
	$(PYTEST)

install:
	$(PIP) install -r requirements.txt
	$(PYTHON) -m playwright install --with-deps
	$(PYTHON) -c "from core.tor_launcher import ensure_vendor_tor; ensure_vendor_tor()"

clean:
	find . -type d -name "__pycache__" -exec rm -rf {} +
	find . -type d -name ".pytest_cache" -exec rm -rf {} +
	find . -type f -name "*.pyc" -delete
