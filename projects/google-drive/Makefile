.PHONY: install dev test run demo clean docker-up docker-down format lint

install:
	pip install -e .

dev:
	pip install -e ".[dev]"

test:
	pytest tests/ -v

run:
	uvicorn src.api:app --reload --host 0.0.0.0 --port 8000

demo:
	python scripts/demo.py

clean:
	rm -rf __pycache__ .pytest_cache .ruff_cache
	rm -rf storage/blocks/* storage/metadata/*
	find . -type d -name "__pycache__" -exec rm -rf {} +

docker-up:
	docker-compose up -d

docker-down:
	docker-compose down

format:
	black src/ tests/ scripts/
	ruff --fix src/ tests/ scripts/

lint:
	black --check src/ tests/ scripts/
	ruff src/ tests/ scripts/

db-migrate:
	python -m src.storage.init_db

help:
	@echo "Available commands:"
	@echo "  make install      - Install package"
	@echo "  make dev          - Install with dev dependencies"
	@echo "  make test         - Run tests"
	@echo "  make run          - Start API server"
	@echo "  make demo         - Run interactive demo"
	@echo "  make docker-up    - Start PostgreSQL via Docker"
	@echo "  make docker-down  - Stop Docker services"
	@echo "  make format       - Format code with black & ruff"
	@echo "  make lint         - Check code style"
	@echo "  make clean        - Remove cache files"
