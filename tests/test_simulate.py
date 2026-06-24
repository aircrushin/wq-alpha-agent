"""Tests for the simulation module."""

import pytest
from wq_alpha_agent.simulate import (
    AlphaMetrics,
    SimulationSettings,
    build_payload,
)


class TestSimulationSettings:
    def test_default_values(self):
        s = SimulationSettings()
        assert s.instrument_type == "EQUITY"
        assert s.region == "USA"
        assert s.universe == "TOP3000"
        assert s.delay == 1
        assert s.decay == 0
        assert s.neutralization == "SUBINDUSTRY"

    def test_to_dict(self):
        s = SimulationSettings(decay=4, neutralization="INDUSTRY")
        d = s.to_dict()
        assert d["decay"] == 4
        assert d["neutralization"] == "INDUSTRY"
        assert d["instrumentType"] == "EQUITY"


class TestBuildPayload:
    def test_basic_payload(self):
        payload = build_payload("rank(close)")
        assert payload["type"] == "REGULAR"
        assert payload["regular"] == "rank(close)"
        assert payload["settings"]["instrumentType"] == "EQUITY"

    def test_custom_settings(self):
        settings = SimulationSettings(decay=4, neutralization="MARKET")
        payload = build_payload("rank(close)", settings)
        assert payload["settings"]["decay"] == 4
        assert payload["settings"]["neutralization"] == "MARKET"

    def test_overrides(self):
        payload = build_payload("rank(close)", decay=12, neutralization="SECTOR")
        assert payload["settings"]["decay"] == 12
        assert payload["settings"]["neutralization"] == "SECTOR"


class TestAlphaMetrics:
    def test_from_api_response(self):
        data = {
            "status": "UNSUBMITTED",
            "grade": "GOOD",
            "is": {
                "sharpe": 1.5,
                "fitness": 1.2,
                "turnover": 0.15,
                "returns": 0.12,
                "drawdown": 0.05,
                "margin": 0.03,
                "checks": [
                    {"name": "LOW_SHARPE", "result": "PASS"},
                    {"name": "LOW_FITNESS", "result": "PASS"},
                ],
            },
        }
        metrics = AlphaMetrics.from_api_response("TEST123", data)
        assert metrics.alpha_id == "TEST123"
        assert metrics.sharpe == 1.5
        assert metrics.fitness == 1.2
        assert metrics.turnover == 0.15
        assert metrics.grade == "GOOD"
        assert len(metrics.checks) == 2

    def test_check_thresholds_pass(self):
        metrics = AlphaMetrics(
            alpha_id="X", sharpe=1.5, fitness=1.2, turnover=0.15
        )
        passed, reasons = metrics.check_thresholds()
        assert passed
        assert not reasons

    def test_check_thresholds_fail_sharpe(self):
        metrics = AlphaMetrics(
            alpha_id="X", sharpe=1.0, fitness=1.2, turnover=0.15
        )
        passed, reasons = metrics.check_thresholds()
        assert not passed
        assert any("Sharpe" in r for r in reasons)

    def test_check_thresholds_fail_turnover(self):
        metrics = AlphaMetrics(
            alpha_id="X", sharpe=1.5, fitness=1.2, turnover=0.8
        )
        passed, reasons = metrics.check_thresholds()
        assert not passed
        assert any("Turnover" in r for r in reasons)

    def test_failed_checks(self):
        metrics = AlphaMetrics(
            alpha_id="X", sharpe=1.5, fitness=1.2, turnover=0.15,
            checks=[
                {"name": "LOW_SHARPE", "result": "PASS"},
                {"name": "CONCENTRATED_WEIGHT", "result": "FAIL", "value": 0.15, "limit": 0.10},
            ],
        )
        failures = metrics.failed_checks()
        assert len(failures) == 1
        assert failures[0]["name"] == "CONCENTRATED_WEIGHT"
