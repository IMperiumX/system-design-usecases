.PHONY: install run test demo clean redis-up redis-down

install:
	pip install -r requirements.txt

redis-up:
	docker-compose up -d
	@echo "Waiting for Redis to be ready..."
	@sleep 2

redis-down:
	docker-compose down

run: redis-up
	uvicorn src.api:app --reload --port 8000

test:
	pytest tests/ -v

demo: redis-up
	python scripts/demo.py

clean:
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name .pytest_cache -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name "*.pyc" -delete
