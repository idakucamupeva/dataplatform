.PHONY: help install backend frontend seed reset test smoke build clean

PY  := .venv/bin/python
PIP := .venv/bin/pip

help:
	@echo "make install   create the virtualenv, install backend + frontend dependencies"
	@echo "make seed      populate the platform with the demo mesh"
	@echo "make backend   run the API on http://127.0.0.1:8000 (docs at /docs)"
	@echo "make frontend  run the UI on http://127.0.0.1:5173"
	@echo "make test      run the backend test suite"
	@echo "make smoke     render every UI route against the running backend"
	@echo "make reset     wipe the database and all data product repositories"

.venv:
	python3 -m venv .venv

install: .venv
	$(PIP) install -r backend/requirements.txt
	cd frontend && npm install

seed:
	cd backend && ../$(PY) -m app.seed

reset:
	cd backend && ../$(PY) -m app.seed --reset

backend:
	cd backend && ../$(PY) -m uvicorn app.main:app --reload --port 8000

frontend:
	cd frontend && npm run dev

test:
	cd backend && ../$(PY) -m pytest

smoke:
	cd frontend && npm run smoke

build:
	cd frontend && npm run build

clean:
	rm -rf data frontend/dist frontend/.smoke backend/**/__pycache__
