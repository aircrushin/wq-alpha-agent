# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with this repository.

## Repository Overview

**wq-alpha-agent** is an open-source Python framework and Claude Code skill for automated WorldQuant BRAIN alpha factor research. It provides:

- **Python package** (`wq_alpha_agent/`): Modular building blocks for auth, simulation, submission, diversity checking, field discovery, and self-evolution
- **CLI scripts** (`scripts/`): Ready-to-use command-line tools
- **Agent skill** (`SKILL.md`): A Claude Code skill playbook with templates, diagnostics, and best practices distilled from 600+ simulations
- **Examples** (`examples/`): Ready-to-run batch configurations

## Common Commands

```bash
# Install
pip install -e .

# Set credentials
export WQ_BRAIN_USERNAME="your_email"
export WQ_BRAIN_PASSWORD="your_password"

# CLI tools
wq-search-fields --search "operating_income" --category fundamental
wq-batch --config examples/example_quality.json --dry-run --limit 2
wq-evolve --apply
wq-verify <alpha_id_1> <alpha_id_2>
wq-build-blacklist --from-braindb alpha_db.json

# Run scripts directly
python scripts/run_batch.py --config my_config.json --dry-run
python scripts/search_fields.py --fetch-all --save references/my_fields.json
python scripts/evolve_skill.py --apply
```

## Architecture

### Package (`wq_alpha_agent/`)

| Module | Purpose |
|--------|---------|
| `auth.py` | BRAIN API authentication via env vars or credential file |
| `simulate.py` | Build payloads, submit simulations, poll, extract metrics |
| `submit.py` | Pre-submit check, submit, verify (201 ≠ ACTIVE) |
| `diversity.py` | Expression fingerprinting, family classification, diversity gate |
| `fields.py` | Field search (API + local cache), validation |
| `batch.py` | Full pipeline orchestration: gate → simulate → check → submit |
| `evolve.py` | Self-evolution: track alphas, compute daily-return correlations, generate lessons |
| `config.py` | Batch defaults and strategy presets |
| `utils.py` | Logging, JSONL helpers, formatting |

### Scripts (`scripts/`)

| Script | Purpose |
|--------|---------|
| `run_batch.py` | Run a batch config through the full pipeline |
| `search_fields.py` | Search/discover BRAIN data fields |
| `evolve_skill.py` | Learn from empirical BRAIN alpha data |
| `verify_status.py` | Verify submission status of alpha IDs |
| `build_blacklist.py` | Build diversity blacklist from ACTIVE alphas |

### Data Flow

```
Batch Config JSON
    │
    ▼
Diversity Gate (diversity.py)
    │
    ▼
[For each alpha]
    │
    ├── Simulate (simulate.py) ──→ BRAIN API POST /simulations
    ├── Poll until COMPLETE ──→ BRAIN API GET /simulations/{id}
    ├── Fetch details ──→ BRAIN API GET /alphas/{id}
    ├── Check thresholds (Sharpe, Fitness, Turnover...)
    ├── Pre-submit check ──→ BRAIN API GET /alphas/{id}/check
    ├── Submit ──→ BRAIN API POST /alphas/{id}/submit
    └── Verify (poll until ACTIVE or SELF_CORRELATION fail)
    │
    ▼
JSONL Evidence Log + Batch Summary
    │
    ▼
Self-Evolution (evolve.py)
```

### Batch Config Format

```json
{
  "defaults": { "decay": 4, "neutralization": "SUBINDUSTRY", ... },
  "alphas": [
    { "name": "...", "expression": "...", "decay": 4, ... }
  ]
}
```

Alpha-level fields override defaults. Only `name` and `expression` are required per alpha.

## Important Notes

- **The wqb library has a submit URL bug** (`http://` instead of `https://`). Our code uses direct REST API calls with explicit `https://` URLs, avoiding this entirely.
- **201 response ≠ ACTIVE**: After submission, always verify `status == ACTIVE`. The BRAIN platform may keep alphas as UNSUBMITTED due to SELF_CORRELATION failures.
- **Daily-return correlation is the only valid correlation metric**: Cumulative PnL correlation is severely inflated (> 0.90 for almost any pair) and is completely misleading.
- **Credentials are never committed**: Use `WQ_BRAIN_USERNAME`/`WQ_BRAIN_PASSWORD` env vars or an untracked `credential.txt`.
- **alpha_db.json is personal data**: It contains your alpha IDs, PnL series, and submission records. It is gitignored by default.
- **Rate limit**: Sleep 2-5 seconds between API calls. On 429, read `Retry-After` and use exponential backoff.
