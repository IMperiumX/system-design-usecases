.PHONY: help setup migrate shell demo test clean

help:
	@echo "Payment System - Make Commands"
	@echo "=============================="
	@echo "make setup     - Install dependencies and setup database"
	@echo "make migrate   - Run Django migrations"
	@echo "make shell     - Open Django shell"
	@echo "make demo      - Run demo script"
	@echo "make test      - Run tests"
	@echo "make clean     - Clean up containers and volumes"
	@echo "make run       - Run development server"

setup:
	docker-compose up -d
	@echo "Waiting for services to be healthy..."
	@sleep 5
	pip install -r requirements.txt -q
	python manage.py migrate
	@echo "✓ Setup complete!"

migrate:
	python manage.py makemigrations
	python manage.py migrate

shell:
	python manage.py shell_plus

demo:
	python scripts/demo.py

test:
	python manage.py test

clean:
	docker-compose down -v

run:
	python manage.py runserver
