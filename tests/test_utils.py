import pytest

from wq_alpha_agent.utils import format_metrics_table


class TestFormatMetricsTable:
    def test_empty_list_returns_no_metrics_message(self):
        assert format_metrics_table([]) == "No metrics to display."

    def test_formats_missing_values_and_exact_name_boundary(self):
        name = "a" * 30
        table = format_metrics_table([{"name": name}])
        lines = table.splitlines()

        assert len(lines) == 3
        assert lines[1] == "-" * len(lines[0])
        assert lines[2] == f"{name:<30} {0:>8.2f} {0:>8.2f} {0:>9.4f} {'?':>8}"

    def test_truncates_names_longer_than_thirty_characters(self):
        table = format_metrics_table([{"name": "a" * 30 + "b"}])

        assert table.splitlines()[2].startswith("a" * 30 + " ")
        assert "b" not in table

    def test_rejects_non_string_name(self):
        with pytest.raises(TypeError):
            format_metrics_table([{"name": 123}])
