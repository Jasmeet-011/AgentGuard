.PHONY: install lint test test-int check ingest eval app mcp

install:
	uv sync

lint:
	uv run ruff check .
	uv run ruff format --check .

test:
	uv run pytest -m "not integration"

test-int:
	uv run pytest -m integration

check: lint test

ingest:
	uv run agentguard ingest

eval:
	uv run agentguard eval --split dev

app:
	uv run streamlit run app/streamlit_app.py

mcp:
	@echo "mcp server is not implemented until M12" && exit 1
