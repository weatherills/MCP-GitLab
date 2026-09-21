# MCP-GitLab
HTTPS Gitlab MCP server that can connect to and work with non-enterprise Gitlab Servers using PATs

## Status

Specced, not yet implemented. See [`docs/prd/`](docs/prd/) for the nine PRDs covering architecture
and each GitLab command domain, and [`CLAUDE.md`](CLAUDE.md) for the build guide, current repo
layout, and conventions for whoever implements it next.

## Development

```
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
ruff check . && mypy src && pytest
```
