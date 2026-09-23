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
	@echo "agentguard eval is not implemented until M6" && exit 1

app:
	@echo "streamlit app is not implemented until M10" && exit 1

mcp:
	@echo "mcp server is not implemented until M12" && exit 1
