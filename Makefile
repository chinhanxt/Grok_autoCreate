# ==============================================================================
# Makefile for Grok & x.ai Account Creator
# ==============================================================================

VENV := ./venv
PYTHON := $(shell if [ -f $(VENV)/bin/python ]; then echo $(VENV)/bin/python; else echo python3; fi)
PIP := $(shell if [ -f $(VENV)/bin/pip ]; then echo $(VENV)/bin/pip; else echo pip; fi)
PYTEST := $(shell if [ -f $(VENV)/bin/pytest ]; then echo $(VENV)/bin/pytest; else echo pytest; fi)

HOST ?= 127.0.0.1
PORT ?= 7860

.PHONY: all help dev start cli test install clean

all: help

help:
	@echo "Grok & x.ai Account Creator"
	@echo "--------------------------------------------------"
	@echo "  make dev      - Run web dashboard in development mode (with auto-reload)"
	@echo "  make start    - Run web dashboard in standard mode"
	@echo "  make cli      - Run interactive CLI mode"
	@echo "  make test     - Run test suite"
	@echo "  make install  - Install requirements and Playwright browsers"
	@echo "  make clean    - Remove cache and temporary files"
	@echo "--------------------------------------------------"

dev:
	$(PYTHON) web_app.py --reload --host $(HOST) --port $(PORT)

start:
	$(PYTHON) web_app.py --host $(HOST) --port $(PORT)

cli:
	$(PYTHON) cli.py

test:
	$(PYTEST)

install:
	$(PIP) install -r requirements.txt
	$(PYTHON) -m playwright install --with-deps

clean:
	find . -type d -name "__pycache__" -exec rm -rf {} +
	find . -type d -name ".pytest_cache" -exec rm -rf {} +
	find . -type f -name "*.pyc" -delete
