.PHONY: help setup start stop migrate shell test demo clean

help:
	@echo "Metrics Monitoring and Alerting System - Make Commands"
	@echo ""
	@echo "Available commands:"
	@echo "  make setup     - Set up the project (install deps, start services, migrate)"
	@echo "  make start     - Start Docker services (PostgreSQL + Redis)"
	@echo "  make stop      - Stop Docker services"
	@echo "  make migrate   - Run Django migrations"
	@echo "  make shell     - Open Django shell"
	@echo "  make server    - Run Django development server"
	@echo "  make test      - Run tests"
	@echo "  make demo      - Run interactive demo"
	@echo "  make clean     - Clean up database and cache"

setup:
	@echo "Setting up Metrics Monitoring System..."
	pip install -r requirements.txt
	docker-compose up -d
	@echo "Waiting for services to be ready..."
	sleep 5
	python manage.py migrate
	@echo "Setup complete! Run 'make server' to start the dev server."

start:
	@echo "Starting Docker services..."
	docker-compose up -d
	@echo "Services started. PostgreSQL on :5432, Redis on :6379"

stop:
	@echo "Stopping Docker services..."
	docker-compose down

migrate:
	python manage.py makemigrations
	python manage.py migrate

shell:
	python manage.py shell

server:
	python manage.py runserver

test:
	pytest tests/ -v

demo:
	python scripts/demo.py

clean:
	@echo "Cleaning up..."
	docker-compose down -v
	rm -f db.sqlite3
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name "*.pyc" -delete
	@echo "Clean complete!"
