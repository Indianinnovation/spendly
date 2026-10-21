"""Tests for planner.py (pure functions, no DB, no Flask)."""

from datetime import date

import pytest

import planner

START = date(2026, 1, 1)


def debt(id, balance, apr=0.0, min_payment=100.0, priority=None, name=None):
    return {
        "id": id,
        "name": name or f"Debt{id}",
        "balance": balance,
        "apr": apr,
        "min_payment": min_payment,
        "priority": priority,
    }


def payoff_month(result, debt_id):
    for entry in result["payoff_order"]:
        if entry["debt_id"] == debt_id:
            return entry["month"]
    return None


class TestSimulateSingleDebt:
    def test_zero_apr_pays_off_in_ten_months_with_no_interest(self):
        r = planner.simulate([debt(1, 1000, 0, 100)], 0, "avalanche", start=START)
        assert r["months"] == 10
        assert r["total_interest"] == 0
        assert r["paid_off"] is True
        assert r["debt_free_date"] == "Nov 2026"

    def test_twelve_percent_apr_matches_hand_computation(self):
        r = planner.simulate([debt(1, 1000, 12, 510)], 0, "avalanche", start=START)
        assert r["months"] == 2
        assert r["total_interest"] == pytest.approx(15.0)

    def test_extra_payment_shortens_payoff(self):
        base = planner.simulate([debt(1, 1000, 0, 100)], 0, "avalanche", start=START)
        more = planner.simulate([debt(1, 1000, 0, 100)], 100, "avalanche", start=START)
        assert more["months"] < base["months"]
        assert more["months"] == 5

    def test_empty_debt_list_gives_zero_months(self):
        r = planner.simulate([], 0, "avalanche", start=START)
        assert r["months"] == 0

    def test_series_starts_with_initial_balance_and_ends_at_zero(self):
        r = planner.simulate([debt(1, 300, 0, 100)], 0, "snowball", start=START)
        assert r["series"][1][0] == 300
        assert r["series"][1][-1] == 0
        assert len(r["series"][1]) == r["months"] + 1


class TestCap:
    def test_unpayable_debt_hits_600_month_cap(self):
        d = [debt(1, 10000, 24, 100, name="Card")]
        r = planner.simulate(d, 0, "avalanche", start=START)
        assert r["paid_off"] is False
        assert r["months"] == 600
        assert r["debt_free_date"] is None

    def test_interest_warnings_flags_debt_whose_minimum_misses_interest(self):
        d = [debt(1, 10000, 24, 100, name="Card"), debt(2, 1000, 0, 100, name="Fine")]
        warnings = planner.interest_warnings(d)
        assert "Card" in warnings
        assert "Fine" not in warnings

    def test_interest_warnings_empty_when_all_covered(self):
        assert not planner.interest_warnings([debt(1, 1000, 12, 200)])


class TestOrdering:
    def test_avalanche_orders_highest_apr_first(self):
        ds = [debt(1, 500, 5), debt(2, 500, 20), debt(3, 500, 10)]
        assert [d["id"] for d in planner.order_debts(ds, "avalanche")] == [2, 3, 1]

    def test_snowball_orders_smallest_balance_first(self):
        ds = [debt(1, 900), debt(2, 100), debt(3, 500)]
        assert [d["id"] for d in planner.order_debts(ds, "snowball")] == [2, 3, 1]

    def test_custom_orders_by_priority(self):
        ds = [
            debt(1, 100, priority=3),
            debt(2, 100, priority=1),
            debt(3, 100, priority=2),
        ]
        assert [d["id"] for d in planner.order_debts(ds, "custom")] == [2, 3, 1]

    def test_custom_puts_unprioritised_debts_last(self):
        ds = [debt(1, 100, priority=None), debt(2, 100, priority=5)]
        assert [d["id"] for d in planner.order_debts(ds, "custom")] == [2, 1]

    def test_avalanche_pays_highest_apr_off_first_with_extra(self):
        ds = [debt(1, 1000, 5, 50), debt(2, 1000, 25, 50)]
        r = planner.simulate(ds, 200, "avalanche", start=START)
        assert payoff_month(r, 2) < payoff_month(r, 1)

    def test_snowball_pays_smallest_balance_off_first_with_extra(self):
        ds = [debt(1, 2000, 25, 50), debt(2, 500, 5, 50)]
        r = planner.simulate(ds, 200, "snowball", start=START)
        assert payoff_month(r, 2) < payoff_month(r, 1)

    def test_avalanche_interest_not_more_than_snowball(self):
        ds = [debt(1, 500, 5, 30), debt(2, 3000, 24, 60), debt(3, 1500, 12, 40)]
        av = planner.simulate(ds, 150, "avalanche", start=START)
        sn = planner.simulate(ds, 150, "snowball", start=START)
        assert av["total_interest"] <= sn["total_interest"]


class TestRollover:
    def test_freed_minimum_rolls_to_next_debt(self):
        ds = [debt(1, 100, 0, 50), debt(2, 1000, 0, 50)]
        r = planner.simulate(ds, 0, "snowball", start=START)
        assert payoff_month(r, 1) == 2
        assert payoff_month(r, 2) == 11

    def test_minimums_baseline_has_no_rollover(self):
        ds = [debt(1, 100, 0, 50), debt(2, 1000, 0, 50)]
        r = planner.simulate(ds, 0, "minimums", start=START)
        assert r["months"] == 20

    def test_leftover_in_final_month_spills_into_next_debt_same_month(self):
        ds = [debt(1, 30, 0, 50), debt(2, 1000, 0, 50)]
        r = planner.simulate(ds, 0, "snowball", start=START)
        assert r["series"][2][:3] == [1000, 930, 830]


class TestCompare:
    def test_includes_each_strategy_and_minimums_last(self):
        ds = [debt(1, 500, 5, 50, priority=1), debt(2, 800, 15, 50)]
        names = [r["strategy"] for r in planner.compare(ds, 100, start=START)]
        assert names[-1] == "minimums"
        assert "snowball" in names and "avalanche" in names

    def test_custom_included_only_when_a_priority_is_set(self):
        no_prio = planner.compare([debt(1, 500, 5, 50)], 0, start=START)
        with_prio = planner.compare([debt(1, 500, 5, 50, priority=1)], 0, start=START)
        assert "custom" not in [r["strategy"] for r in no_prio]
        assert "custom" in [r["strategy"] for r in with_prio]

    def test_interest_and_months_saved_never_negative(self):
        ds = [debt(1, 1500, 18, 60), debt(2, 400, 8, 30)]
        for r in planner.compare(ds, 100, start=START):
            assert r["interest_saved"] >= 0
            assert r["months_saved"] >= 0

    def test_minimums_baseline_saves_nothing(self):
        ds = [debt(1, 1500, 18, 60)]
        base = planner.compare(ds, 100, start=START)[-1]
        assert base["interest_saved"] == 0
        assert base["months_saved"] == 0

    def test_extra_payment_produces_positive_savings(self):
        ds = [debt(1, 1500, 18, 60)]
        results = planner.compare(ds, 200, start=START)
        assert results[0]["interest_saved"] > 0
        assert results[0]["months_saved"] > 0


class TestBuildChart:
    def _chart(self, n_debts=2, months=400):
        series = {
            i: [float(months - m) for m in range(months + 1)]
            for i in range(1, n_debts + 1)
        }
        names = {i: f"Debt{i}" for i in series}
        labels = [f"L{m}" for m in range(months + 1)]
        return planner.build_chart(series, names, labels), labels

    def test_downsamples_to_at_most_120_points(self):
        chart, _ = self._chart()
        for layer in chart["layers"]:
            upper_and_lower = layer["points"].split()
            assert (
                len(upper_and_lower) <= 240
            ), "upper + lower edge should be <= 2*120 points"

    def test_one_polygon_per_debt(self):
        chart, _ = self._chart(n_debts=3)
        assert len(chart["layers"]) == 3

    def test_final_month_label_is_kept(self):
        chart, labels = self._chart()
        assert chart["x_labels"][-1]["label"] == labels[-1]
        assert chart["x_labels"][0]["label"] == labels[0]

    def test_y_ticks_are_formatted_in_rupees(self):
        chart, _ = self._chart()
        assert all(t["label"].startswith("₹") for t in chart["y_ticks"])

    def test_coordinates_rounded_to_one_decimal(self):
        chart, _ = self._chart()
        for pair in chart["layers"][0]["points"].split():
            for value in pair.split(","):
                decimals = value.split(".")[1] if "." in value else ""
                assert len(decimals) <= 1, f"coordinate {value} has more than 1 decimal"
