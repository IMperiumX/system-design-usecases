.PHONY: help setup start stop clean migrate test demo shell

help:
	@echo "Available commands:"
	@echo "  make setup    - Install dependencies and set up environment"
	@echo "  make start    - Start Docker services (Redis + Postgres)"
	@echo "  make stop     - Stop Docker services"
	@echo "  make migrate  - Run Django migrations"
	@echo "  make demo     - Run interactive demo"
	@echo "  make shell    - Open Django shell"
	@echo "  make test     - Run tests"
	@echo "  make clean    - Stop services and remove volumes"

setup:
	@echo "Installing Python dependencies..."
	pip install -r requirements.txt
	@echo "Copying .env.example to .env if not exists..."
	@test -f .env || cp .env.example .env
	@echo "Starting Docker services..."
	docker-compose up -d
	@echo "Waiting for services to be ready..."
	sleep 5
	@echo "Running migrations..."
	python manage.py migrate
	@echo "Setup complete!"

start:
	docker-compose up -d
	@echo "Services started. Redis: localhost:6379, Postgres: localhost:5432"

stop:
	docker-compose down

migrate:
	python manage.py makemigrations
	python manage.py migrate

demo:
	python scripts/demo.py

shell:
	python manage.py shell

test:
	pytest

clean:
	docker-compose down -v
	find . -type d -name __pycache__ -exec rm -r {} +
	find . -type f -name "*.pyc" -delete
