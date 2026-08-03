# WQ Alpha Agent

> 🤖 Automated WorldQuant BRAIN alpha factor research agent — generate, simulate, diversity-check, submit, and evolve alpha expressions with LLM-driven automation.

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)

**wq-alpha-agent** is an open-source Python framework and Claude Code agent skill for automated alpha factor research on the [WorldQuant BRAIN](https://www.worldquantbrain.com/) platform. It packages hundreds of simulations worth of empirical knowledge into reusable building blocks, playbook templates, and self-evolving workflows.

## Why This Exists

WQ Alpha mining is not just about writing more expressions. The bottleneck is the **research loop**:

- Finding usable fields fast enough
- Avoiding repeated low-Sharpe templates
- Controlling turnover before submission
- Checking SELF_CORRELATION against existing ACTIVE alphas
- Preserving lessons from failed simulations instead of rediscovering them

This framework packages that loop into agent-readable modules plus a self-evolution mechanism that turns each BRAIN interaction into reusable research rules.

## What It Does

| Capability | Module | Status |
|-----------|--------|--------|
| 🔐 BRAIN API authentication | `auth.py` | ✅ |
| 🧪 Simulation with retry & polling | `simulate.py` | ✅ |
| 📤 Pre-check → Submit → Verify pipeline | `submit.py` | ✅ |
| 🔍 Field search (API + local cache) | `fields.py` | ✅ |
| 🛡️ Diversity/novelty gate (fingerprint-based) | `diversity.py` | ✅ |
| 📦 Batch orchestration (full pipeline) | `batch.py` | ✅ |
| 🧬 Self-evolution (correlate, track, learn) | `evolve.py` | ✅ |
| 🎯 Strategy presets (fundamental, hybrid, etc.) | `config.py` | ✅ |
| 🤖 Claude Code agent skill playbook | `SKILL.md` | ✅ |

## Quick Start

### 1. Install

```bash
git clone https://github.com/UltraV/wq-alpha-agent.git
cd wq-alpha-agent
pip install -e .
```

### 2. Set Credentials

```bash
export WQ_BRAIN_USERNAME="your_email@example.com"
export WQ_BRAIN_PASSWORD="your_password"
```

Or create an untracked `credential.txt`:
```json
["your_email@example.com", "your_password"]
```

### 3. Search Available Fields

```bash
# Search locally cached fields (USA TOP3000 delay=1)
wq-search-fields --search "operating_income" --category fundamental

# Fetch fresh field data from BRAIN API
wq-search-fields --fetch-all --save references/my_fields.json
```

### 4. Run a Research Batch

```bash
# Always dry-run first!
wq-batch --config examples/example_quality.json --dry-run --limit 2

# When you're ready (and have set auto_submit: true in config)
wq-batch --config my_research_batch.json
```

### 5. Learn From Results

```bash
# Preview lessons from your alpha history
wq-evolve

# Apply lessons to local database
wq-evolve --apply
```

### 6. Verify Submissions

```bash
wq-verify <alpha_id_1> <alpha_id_2>
wq-verify --input alpha_ids.txt --output verification_results.json
```

## Using with Claude Code

Place this repository's `SKILL.md` in your project's `.claude/skills/wq-alpha-agent/` directory
alongside the Python package. Claude Code will automatically follow the playbook for:

- Designing alpha expressions from proven templates
- Selecting appropriate settings per factor type  
- Diagnosing simulation failures
- Running and interpreting the diversity gate
- Deciding when to submit
- Evolving the skill from new empirical results

## Core Research Loop

```
Batch Config JSON
    │
    ▼
Diversity Gate ── blocks near-duplicates of ACTIVE alphas
    │
    ▼
[For each accepted alpha]
    ├── POST /simulations      → sim_id
    ├── POLL until COMPLETE    → alpha_id
    ├── GET /alphas/{id}       → metrics (Sharpe, Fitness, Turnover...)
    ├── Threshold check        → pass/fail
    ├── GET /alphas/{id}/check → pre-submit validation
    ├── POST /alphas/{id}/submit → submission
    └── POLL verify            → must confirm status == ACTIVE
    │
    ▼
JSONL Evidence + Batch Summary
    │
    ▼
Self-Evolution ── daily-return correlations, lessons
```

## Key Design Decisions

### Fingerprint-Based Diversity, Not Just Blacklists

The diversity gate normalizes expressions, extracts field/operator skeletons, and classifies
alphas into families. It blocks candidates that are:
1. Exact normalized matches of protected alphas
2. Same field skeleton with only parameter/weight changes
3. Same family with high key-field and operator overlap

This catches near-duplicates that simple string matching would miss.

### Daily-Return Correlation, Not Cumulative PnL

The framework **always** computes correlation on daily PnL changes, never on cumulative PnL
curves. Cumulative PnL correlation is severely inflated (> 0.90 for almost any pair) and
completely misleading for diversification decisions.

### 201 ≠ ACTIVE

A 201 response from the submit endpoint only means the request was accepted. The framework
always follows up by polling until the alpha status resolves to ACTIVE or a SELF_CORRELATION
failure is detected.

## Empirical Foundation

Built from:
- **600+** BRAIN simulations
- **168+** batch research sessions
- **4,367** USA TOP3000 delay=1 data fields catalogued
- Failure pattern analysis: LOW_SHARPE (90.7%), LOW_FITNESS (66.2%), LOW_SUB_UNIVERSE_SHARPE (51.0%)
- Pass rate by type: Fundamental (40%) > Hybrid (12.7%) > Pure Technical (5.3%)

## Project Structure

```
wq-alpha-agent/
├── wq_alpha_agent/          # Python package
│   ├── auth.py              # Authentication
│   ├── simulate.py          # Simulation engine
│   ├── submit.py            # Submission pipeline
│   ├── diversity.py         # Diversity gate
│   ├── fields.py            # Field discovery
│   ├── batch.py             # Batch orchestration
│   ├── evolve.py            # Self-evolution
│   ├── config.py            # Strategy presets
│   └── utils.py             # Utilities
├── scripts/                 # CLI tools
│   ├── run_batch.py
│   ├── search_fields.py
│   ├── evolve_skill.py
│   ├── verify_status.py
│   └── build_blacklist.py
├── examples/                # Example batch configs
│   ├── batch_config_template.json
│   ├── example_quality.json
│   ├── example_reversal.json
│   └── example_market_neutral.json
├── references/              # Field cache directory
├── tests/                   # Test suite
├── SKILL.md                 # Claude Code agent playbook
├── CLAUDE.md                # Claude Code project instructions
└── README.md                # This file
```

## Safety Notes

These files are intentionally gitignored and should never be committed:

- `credential.txt` — BRAIN credentials
- `alpha_db.json` — Personal alpha records with PnL series
- `batch_submit_results.json` — Submission results
- `.env` — Environment variables
- Python caches and virtual environments

If you want to share research lessons, summarize them into general rules and add them to
`SKILL.md`. Never publish raw alpha IDs, PnL series, or account-linked submission data.

## License

MIT — see [LICENSE](LICENSE).
