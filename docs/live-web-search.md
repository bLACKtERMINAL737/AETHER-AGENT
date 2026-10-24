# Live web search in AETHER CLAW

AETHER CLAW registers a `web.search` tool for chat requests. The model should use it when the answer depends on recent, current, unfamiliar, or otherwise unverified facts, and cite the returned source URLs in its response.

## How it works

- Uses the `ddgs` Python package to query public DuckDuckGo web results.
- Returns a bounded list of titles, URLs, snippets, and a UTC search timestamp.
- Limits each request to 1–8 results and a 10-second backend timeout.
- Does not require a separate search API key.
- Search can be rate-limited or temporarily unavailable; when that happens, the tool reports failure and the assistant should say it could not verify the answer.

## Setup

Install or update project dependencies in the active virtual environment:

```bash
pip install -e ".[dev]"
```

Restart AETHER CLAW after installing dependencies. Existing provider configuration remains unchanged.

## Privacy and trust

Search queries are sent to an external search service. Send only the minimal public search terms needed; never search using API keys, passwords, private personal details, or confidential workspace contents. Web results are untrusted content and can be wrong or malicious. For important claims, verify the source page and prefer authoritative sources. A search snippet alone is not proof that a claim is true.

This feature searches and returns snippets/links; it does not yet fetch and parse full web pages. Search availability depends on the third-party service and network connectivity.
