"""Tests for the diversity gate module."""

import pytest
from wq_alpha_agent.diversity import (
    AlphaFingerprint,
    build_field_skeleton,
    classify_family,
    evaluate_candidate,
    extract_fields,
    extract_operators,
    filter_alpha_configs,
    jaccard,
    key_fields_for_family,
    normalize_expression,
    operator_overlap,
    fingerprint_alpha,
)


class TestNormalizeExpression:
    def test_whitespace_collapse(self):
        assert normalize_expression("  rank(   close  )  ") == "rank(close)"

    def test_number_replacement(self):
        result = normalize_expression("ts_rank(close, 126)")
        assert "#" in result
        assert "126" not in result

    def test_case_insensitive(self):
        assert normalize_expression("Rank(Close)") == normalize_expression("rank(close)")


class TestExtractFields:
    def test_basic_field_extraction(self):
        fields = extract_fields("rank(close)")
        assert "close" in fields
        assert "rank" not in fields

    def test_filter_operators(self):
        fields = extract_fields("ts_rank(operating_income / equity, 126)")
        assert "operating_income" in fields
        assert "equity" in fields
        assert "ts_rank" not in fields

    def test_filter_local_variables(self):
        expr = "my_signal = rank(close); group_neutralize(my_signal, industry)"
        fields = extract_fields(expr)
        assert "close" in fields
        assert "industry" in fields
        assert "my_signal" not in fields


class TestClassifyFamily:
    def test_eps_profit_buzz(self):
        family = classify_family({"est_eps", "operating_income", "close"})
        assert family == "eps_profit_buzz"

    def test_unknown_family(self):
        family = classify_family({"close", "volume"})
        assert family == "market_microstructure"

    def test_partial_match(self):
        family = classify_family({"operating_income", "equity"})
        assert family == "eps_profit_buzz"  # partial match on operating_income


class TestJaccard:
    def test_identical(self):
        assert jaccard({"a", "b"}, {"a", "b"}) == 1.0

    def test_disjoint(self):
        assert jaccard({"a"}, {"b"}) == 0.0

    def test_partial(self):
        assert jaccard({"a", "b"}, {"b", "c"}) == 1.0 / 3.0

    def test_both_empty(self):
        assert jaccard(set(), set()) == 1.0


class TestOperatorOverlap:
    def test_identical(self):
        assert operator_overlap(["rank", "ts_rank"], ["rank", "ts_rank"]) == 1.0

    def test_partial(self):
        result = operator_overlap(["rank", "ts_rank"], ["rank", "ts_mean"])
        assert result == 1.0 / 3.0

    def test_disjoint(self):
        assert operator_overlap(["rank"], ["ts_mean"]) == 0.0


class TestBuildFieldSkeleton:
    def test_replaces_fields(self):
        skeleton = build_field_skeleton("rank(close)")
        assert "close" not in skeleton
        assert "FIELD" in skeleton

    def test_preserves_operators(self):
        skeleton = build_field_skeleton("rank(close)")
        assert "rank" in skeleton


class TestFingerprintAlpha:
    def test_basic_fingerprint(self):
        alpha = {
            "name": "test_alpha",
            "expression": "rank(close)",
            "alpha_id": "ABC123",
        }
        fp = fingerprint_alpha(alpha)
        assert fp.name == "test_alpha"
        assert fp.alpha_id == "ABC123"
        assert "close" in fp.fields
        assert "rank" in fp.operators

    def test_missing_expression_raises(self):
        with pytest.raises(ValueError, match="has no expression"):
            fingerprint_alpha({"name": "no_expr"})


class TestEvaluateCandidate:
    def test_exact_duplicate_blocked(self):
        protected = [
            AlphaFingerprint(
                alpha_id="X1", name="existing", status="ACTIVE",
                expression="rank(close)", family="market_microstructure",
                fields=["close"], key_fields=["close"],
                operators=["rank"], skeleton="rank(close)",
                field_skeleton="rank(FIELD)",
            )
        ]
        candidate = {"name": "dup", "expression": "rank(close)"}
        allowed, reasons, _ = evaluate_candidate(candidate, protected)
        assert not allowed
        assert any(r["rule"] == "exact_normalized_expression" for r in reasons)

    def test_different_expression_allowed(self):
        protected = [
            AlphaFingerprint(
                alpha_id="X1", name="existing", status="ACTIVE",
                expression="rank(close)", family="market_microstructure",
                fields=["close"], key_fields=["close"],
                operators=["rank"], skeleton="rank(close)",
                field_skeleton="rank(FIELD)",
            )
        ]
        candidate = {"name": "new", "expression": "rank(vwap)"}
        allowed, reasons, _ = evaluate_candidate(candidate, protected)
        assert allowed


class TestFilterAlphaConfigs:
    def test_filter_with_empty_protected(self):
        configs = [
            {"name": "a1", "expression": "rank(close)"},
            {"name": "a2", "expression": "rank(vwap)"},
        ]
        accepted, rejected = filter_alpha_configs(configs, protected=[])
        assert len(accepted) == 2
        assert len(rejected) == 0
