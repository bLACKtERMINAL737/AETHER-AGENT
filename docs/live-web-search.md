# Live web search in AETHER CLAW

AETHER CLAW registers a `web.search` tool for chat requests. For current, recent, unfamiliar, or otherwise unverified questions, the model is instructed to search first, synthesize the strongest results into a direct explanation, include clickable Markdown links to the exact source URLs, and explain what each source supports. It should note uncertainty or conflicting sources rather than presenting search snippets as guaranteed truth.

## How it works

- Uses the `ddgs` Python package to query public DuckDuckGo web results.
- Returns a bounded list of titles, clickable source URLs, snippets, and a UTC search timestamp. The chat model uses these results to explain the answer and attach source links.
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

This feature currently searches and returns search-result snippets/links; it does not yet fetch and parse full web pages. Therefore, answer quality depends partly on the snippets returned, and important claims should be checked by opening the cited source links. Search availability depends on the third-party service and network connectivity.
