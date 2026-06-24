---
name: wq-alpha-agent
description: "WorldQuant BRAIN alpha factor research agent — design WQ Alpha expressions, select fields/operators, diagnose simulation and IS check failures, tune Sharpe/Fitness/Turnover, submit alphas, and build low-correlation alpha portfolios. Triggers on: WorldQuant, BRAIN, WQ Alpha, factor expression, backtest, submission, turnover, Fitness, Sharpe, alpha mining."
---

# WQ Alpha Agent — Research Playbook

Structured playbook for LLM-driven alpha factor research on WorldQuant BRAIN:
**Fields → Expression → Simulate → Check → Submit → Portfolio**.

Built from USA TOP3000 delay=1 empirical experience across 600+ simulations,
168+ batch research sessions, and distilled failure patterns.

---

## 1. Quick Decision Tree

```
START
  ├── Pull ALL alpha list → focus on ACTIVE; compute **daily-return** correlation, >0.7 = modify or abandon
  ├── Design new factor
  │    ├── Field validated? ──NO──→ Check Section 2 (local field search / simulate rank(field))
  │    └── YES
  │         ├── Fundamental ──→ group_rank + ts_rank, SUBINDUSTRY, decay=0
  │         ├── Analyst ────→ group_rank + ts_rank, INDUSTRY/SUBINDUSTRY, decay=0–4
  │         ├── Technical ────→ high decay(10–30) or blend with fundamental to reduce turnover
  │         └── Sentiment ────→ nanHandling=ON, small windows, careful
  └── After submit ──→ verify status == ACTIVE, else check SELF_CORRELATION
```

---

## 2. Operators Reference

| Type | Operator | Purpose |
|------|----------|---------|
| Cross-section | `rank(x)`, `zscore(x)`, `normalize(x)`, `scale(x)`, `winsorize(x, std=4)` | Daily standardization across stocks |
| Time-series | `ts_mean`, `ts_std_dev`, `ts_delta`, `ts_rank`, `ts_corr`, `ts_decay_linear`, `ts_backfill`, `ts_zscore` | Per-stock historical window computations |
| Group | `group_rank(x, group)`, `group_neutralize(x, group)`, `group_zscore(x, group)`, `group_backfill(x, group, N)` | Within-group neutralization |
| Conditional | `if_else(cond, a, b)`, `trade_when(x, cond, delay)` | Conditional exposure |
| Vector | `vec_avg(a, b, c)`, `vec_sum(a, b, c)` | Element-wise multi-field averaging/summing |

**Golden combination**: `group_rank(ts_rank(signal, N), subindustry)`

---

## 3. Factor Template Library

### 3.1 High-Pass-Rate Templates

```fastexpr
-- Template A: ROE Trend (highest pass rate)
group_rank(ts_rank(operating_income / equity, 126), subindustry)

-- Template B: EPS Yield Revision
group_rank(ts_rank(est_eps / close, 126), industry)

-- Template C: FCF Yield
group_rank(ts_rank(free_cash_flow_reported_value / equity, 126), industry)

-- Template D: Multi-factor Blend (high Fitness)
0.5 * group_rank(ts_rank(operating_income / equity, 126), subindustry)
+ 0.5 * group_rank(ts_rank(est_eps / close, 126), industry)

-- Template E: Low-Correlation Tech+Fund Hybrid
0.5 * rank(-(close / open - 1)) + 0.5 * rank(ts_rank(operating_income / equity, 126))

-- Template F: Asset Turnover × Profit Margin
rank(ts_rank(operating_income / sales * sales / assets, 126))
```

### 3.2 Recommended Default Settings

| Factor Type | Decay | Neutralization | Truncation | nanHandling | Expected TO |
|-------------|-------|----------------|------------|-------------|-------------|
| Fundamental Quality | 0 | SUBINDUSTRY | 0.08 | ON | 2–8% |
| Analyst Expectation | 0–4 | INDUSTRY/SUBINDUSTRY | 0.08 | ON | 9–16% |
| Technical Reversal | 10–30 | INDUSTRY | 0.08 | OFF | 15–35% |
| Hybrid Blend | 4–20 | INDUSTRY/SUBINDUSTRY | 0.08 | ON | 10–20% |
| Sentiment | 4–10 | INDUSTRY | 0.05–0.08 | ON | 8–30% |

---

## 4. Metrics & IS Checks

### 4.1 Core Metrics

| Metric | Formula/Meaning | Target |
|--------|----------------|--------|
| Sharpe | Daily IR × √252 | ≥ 1.5 (minimum 1.25) |
| Fitness | Sharpe × √(|Returns| / max(TO, 0.125)) | ≥ 1.1 (minimum 1.0) |
| Returns | Annualized return / $10M | ≥ 7% |
| Turnover | Daily traded / Book Size | 1%–20% |
| Drawdown | Peak-to-trough max drawdown | < 15% |
| Margin | PnL / Total traded | Higher is better |

### 4.2 IS Check Diagnostics

| Check | Threshold | Failure Cause | Fix |
|-------|-----------|---------------|-----|
| LOW_SHARPE | ≥ 1.25 | Weak signal | Change field/window, add group_rank |
| LOW_FITNESS | ≥ 1.0 | Turnover too high | Increase decay, blend with stable signal |
| LOW_TURNOVER | ≥ 1% | Signal too stable | Shorten window, use more active fields |
| HIGH_TURNOVER | ≤ 70% | Turnover explosion | Increase decay, trade_when, blend |
| CONCENTRATED_WEIGHT | Single stock < 10% & diversified | Weight concentration | Use rank(), lower truncation, ts_backfill |
| LOW_SUB_UNIVERSE_SHARPE | Works in TOP1000 too | Small-cap dependence | Use fundamentals, SUBINDUSTRY, avoid cap bias |
| SELF_CORRELATION | **Daily return** corr < 0.7 | Too similar to existing | Change signal family, add filters, change universe |
| MATCHES_COMPETITION | Informational | — | No impact |

### 4.3 Failure Statistics (from 625 simulations)

| Failure | Rate | Takeaway |
|---------|------|----------|
| LOW_SHARPE | 90.7% | Signal quality is the #1 bottleneck |
| LOW_FITNESS | 66.2% | Usually the soft version of HIGH_TURNOVER |
| LOW_SUB_UNIVERSE_SHARPE | 51.0% | Avoid small-cap/liquidity bias |

**Pass rate by data type**: Fundamental 40% > Hybrid 12.7% > Pure Technical 5.3% > Other 0%

---

## 5. Problem Diagnosis

| Symptom | Likely Cause | Fix |
|---------|-------------|-----|
| Fitness < 1.0 | Turnover > 30% | Increase decay, blend with fundamentals, ts_decay_linear |
| Sharpe < 1.25 | Weak signal | Lengthen window, group_rank, change field |
| TO > 50% | Signal changing too fast | decay 10–30, trade_when, blend |
| DD > 15% | High volatility/leverage | Increase decay, lower truncation, blend with low-vol signals |
| CONCENTRATED_WEIGHT FAIL | Sparse/extreme values | rank(), truncation 0.05, ts_backfill |
| Sub-Universe FAIL | Small-cap dependence | Avoid `rank(-assets)`, use group_rank, add liquidity filter |
| simulation_error | Field doesn't exist / operator param error | Validate with `rank(field)` first, check operator arg count |
| trade_when zero trades | Condition too strict | Relax condition or use if_else |

---

## 6. BRAIN API Automation

### 6.1 Authentication

```python
from wq_alpha_agent.auth import create_session, logout

# Uses WQ_BRAIN_USERNAME / WQ_BRAIN_PASSWORD env vars
# or a local untracked credential.txt file
session = create_session()
# ... do work ...
logout(session)
```

### 6.2 Simulate and Poll

```python
from wq_alpha_agent.simulate import simulate_and_wait, SimulationSettings

settings = SimulationSettings(
    decay=0, neutralization="SUBINDUSTRY", universe="TOP3000"
)
metrics = simulate_and_wait(
    session,
    "group_rank(ts_rank(operating_income / equity, 126), subindustry)",
    settings=settings,
    label="ROE_Test",
)
print(f"Sharpe={metrics.sharpe:.2f}, Fitness={metrics.fitness:.2f}, TO={metrics.turnover:.3f}")
```

### 6.3 Full Submit Pipeline

```python
from wq_alpha_agent.submit import submit_with_full_verification

result = submit_with_full_verification(session, alpha_id, label="MyAlpha")
if result["submitted"]:
    print("Alpha is ACTIVE!")
else:
    print(f"Failed: {result.get('error')}")
```

### 6.4 Rate Limiting

- Sleep 2–5 seconds between simulations/submissions
- On 429, read `Retry-After` header, exponential backoff
- Batch: single-threaded or ≤ 2 concurrent

### 6.5 Post-Submit Verification (201 ≠ ACTIVE)

`POST /alphas/{id}/submit` returning 201 only means the request was accepted,
**not** that the alpha became ACTIVE. Common outcomes:

- Alpha stays `UNSUBMITTED` (SELF_CORRELATION not passed or under review)
- Same signal with different parameters gets rejected as duplicate

**Always verify**:

```python
from wq_alpha_agent.submit import verify_submission

result = verify_submission(session, alpha_id)
if result.get("verified"):
    print("ACTIVE!")
elif result.get("self_correlation_failed"):
    print("Rejected: SELF_CORRELATION")
```

---

## 7. Portfolio Construction

### 7.1 Diversified Cluster Examples

| Cluster | Representative Expression |
|---------|--------------------------|
| Profitability | `group_rank(ts_rank(operating_income/equity, 126), subindustry)` |
| Analyst | `group_rank(ts_rank(est_eps/close, 252), subindustry)` |
| FCF | `group_rank(ts_rank(free_cash_flow_reported_value/equity, 126), industry)` |
| Low-Correlation Hybrid | `0.5*rank(-(close/open-1)) + 0.5*rank(ts_rank(operating_income/equity, 126))` |
| Quality Composite | `0.5*group_rank(ts_rank(oi/equity,126),subindustry) + 0.5*group_rank(ts_rank(est_eps/close,126),industry)` |

### 7.2 Submission Priority

1. High Fitness (≥ 1.5) with low TO (< 15%)
2. From different signal clusters
3. If SELF_CORRELATION conflict, keep the higher-Fitness version

### 7.3 The Truth About Correlation

From daily-return correlation analysis of ACTIVE alphas:

- **Within same cluster correlations are extremely high**:
  - Two open-close reversal + OI/Equity blends (different weights) daily corr **0.84**
  - Two analyst EPS variants daily corr **0.74**
  - Two leverage/quality factors (-equity/assets vs liabilities/assets) daily corr **0.84**
- **Cross-cluster doesn't guarantee diversification**: sentiment-based alpha vs analyst alpha corr still **0.59–0.67**
- **Cumulative PnL correlation is severely inflated**: cumulative curves routinely show > 0.90 pairwise correlation, making all factors appear identical

**Conclusions**:

- Changing windows, weights, or neutralization **cannot create truly low correlation**
- True low correlation comes from **completely different data sources or economic logic** (macro events, option flow, cross-border, alternative data)
- In standard USA TOP3000 fundamental/price-volume/analyst pools, "low correlation" is typically **0.3–0.6 daily-return correlation** — don't chase 0

---

## 8. Pre-Submit Checklist

- [ ] Pulled **ALL** alpha list (ACTIVE + UNSUBMITTED), not just this session
- [ ] New factor daily-return correlation with existing ACTIVE < 0.7 (or new Sharpe ≥ old Sharpe × 1.1)
- [ ] Correlation computed on **daily returns**, not cumulative PnL
- [ ] Field validated
- [ ] Simulation without errors
- [ ] Sharpe ≥ 1.3 (ideal ≥ 1.5)
- [ ] Fitness ≥ 1.1
- [ ] Turnover 1%–20% (up to 35% acceptable)
- [ ] Drawdown < 15%
- [ ] All IS checks PASS
- [ ] Long/short counts reasonable
- [ ] After submit, **confirmed status == ACTIVE** — 201 does not mean live

---

## 9. Core Lessons (One-Liners)

1. **Pull all ACTIVE alphas' PnL before designing new factors** — avoid high-correlation duplicates
2. **Correlation must be on daily returns** — cumulative PnL correlation makes everything look the same
3. **201 response ≠ submission success** — always confirm `status == ACTIVE`
4. **Fundamentals > Hybrid > Technical**: `operating_income/equity`, `est_eps/close`, `free_cash_flow_reported_value/equity` are the most stable starting points
5. **group_rank + ts_rank is the golden combo**
6. **SUBINDUSTRY neutralization has the highest pass rate**
7. **Decay is the main lever for turnover control**: fundamental 0, technical 10–30
8. **50/50 orthogonal blends reduce turnover but not necessarily correlation** — correlation depends on signal source, not weights
9. **Validate fields first** — invalid fields fail in seconds
10. **True low correlation is hard in USA TOP3000** — "different" expressions from the same data pool are often highly correlated

---

## 10. Self-Evolution Mechanism

After each BRAIN interaction (submission, query, analysis), run the evolution script
to incorporate new findings:

```bash
# Preview lessons without modifying anything
python scripts/evolve_skill.py

# Apply lessons to local alpha_db.json
python scripts/evolve_skill.py --apply

# Output Markdown snippet to a file
python scripts/evolve_skill.py --output lessons.md
```

The script:
1. Fetches `/users/self/alphas` (paginated) for all alphas
2. Compares with local `alpha_db.json` to find new or changed alphas
3. For new alphas, fetches `recordsets/pnl` and computes daily-return correlations against ACTIVE
4. Auto-generates lesson entries (metric assessment + correlation assessment + expression summary)
5. First run = bulk snapshot; subsequent runs = incremental entries

**AI should manually curate** which lessons to permanently incorporate into
Sections 3, 4, 5, 7, and 9 above. Keep successful patterns; merge repeated same-cluster
entries into single rules; update thresholds when the data shifts.

---

## 11. Using This Skill with Claude Code

This SKILL.md file is a Claude Code skill. Place it in your project's
`.claude/skills/wq-alpha-agent/` directory alongside the Python package.

When Claude Code loads this skill, it will follow the playbook above for:
- Designing alpha expressions from templates
- Selecting appropriate settings per factor type
- Diagnosing simulation failures
- Running and interpreting the diversity gate
- Deciding when to submit
- Evolving the skill from new empirical results

### Quick Start

```bash
# 1. Install the package
pip install -e .

# 2. Set credentials
export WQ_BRAIN_USERNAME="your_email"
export WQ_BRAIN_PASSWORD="your_password"

# 3. Search available fields
wq-search-fields --search "operating_income"

# 4. Run a batch (dry-run first!)
wq-batch --config examples/example_quality.json --dry-run --limit 2

# 5. When ready, run without --dry-run
wq-batch --config my_research_batch.json

# 6. Evolve from results
wq-evolve --apply

# 7. Verify submission status
wq-verify MPpxAmgL KPbLeq3p
```
