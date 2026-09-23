# AgentGuard

A verified research assistant for financial advisors: it answers questions over SEC Form ADV Part 2A brochures, cites every sentence to its source chunk, and refuses when the documents don't contain the answer or when asked for personalized investment advice.

## Setup

```
uv sync
cp .env.example .env   # fill in ANTHROPIC_API_KEY
make check
```
