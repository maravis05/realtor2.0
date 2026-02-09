"""Tests for the property scoring engine."""

from src.parser import Property
from src.scorer import (
    ScoreBreakdown,
    score_property,
    _normalize_threshold,
    _normalize_peak,
)

SAMPLE_CONFIG = {
    "criteria": {
        "lot_size_acres": {
            "weight": 40,
            "min": 0.5,
            "max": 5.0,
            "direction": "higher_is_better",
        },
        "commute": {
            "weight": 25,
            "scoring": "threshold",
            "full_points_under": 20,
            "zero_points_over": 46,
        },
        "bedrooms": {
            "weight": 20,
            "scoring": "peak",
            "ideal": 3,
            "min": 1,
            "max": 5,
        },
        "bathrooms": {
            "weight": 15,
            "min": 0,
            "max": 2,
            "direction": "higher_is_better",
        },
    },
    "bonuses": {
        "has_garage": {"points": 15},
        "has_basement": {"points": 5},
        "has_fireplace": {"points": 3},
    },
    "minimum_score_threshold": 30,
}


def _make_property(**overrides) -> Property:
    defaults = dict(
        zpid="111",
        address="123 Test St",
        price=300000,
        bedrooms=3,
        bathrooms=2.0,
        sqft=1800,
        lot_size_acres=3.0,
        year_built=2000,
        hoa_monthly=0,
        has_garage=None,
        has_basement=None,
        has_fireplace=None,
        property_type="SINGLE_FAMILY",
        commute_minutes={"Work": 15, "School": 20},
    )
    defaults.update(overrides)
    return Property(**defaults)


class TestScoring:
    def test_returns_score_breakdown(self):
        prop = _make_property()
        result = score_property(prop, config=SAMPLE_CONFIG)
        assert isinstance(result, ScoreBreakdown)
        assert 0 <= result.final_score <= 100

    def test_more_land_is_better(self):
        big_lot = _make_property(lot_size_acres=5.0)
        small_lot = _make_property(lot_size_acres=1.0)
        s_big = score_property(big_lot, config=SAMPLE_CONFIG)
        s_small = score_property(small_lot, config=SAMPLE_CONFIG)
        assert s_big.final_score > s_small.final_score

    def test_bonus_features_add_points(self):
        # Use a low-scoring property so bonuses don't hit the 100 cap
        no_bonus = _make_property(lot_size_acres=0.6, commute_minutes={"Work": 40})
        all_bonus = _make_property(
            lot_size_acres=0.6, commute_minutes={"Work": 40},
            has_garage=True, has_basement=True, has_fireplace=True,
        )
        s_none = score_property(no_bonus, config=SAMPLE_CONFIG)
        s_all = score_property(all_bonus, config=SAMPLE_CONFIG)
        assert s_all.final_score - s_none.final_score == 23.0

    def test_garage_bonus_is_15(self):
        no_garage = _make_property()
        with_garage = _make_property(has_garage=True)
        s_no = score_property(no_garage, config=SAMPLE_CONFIG)
        s_yes = score_property(with_garage, config=SAMPLE_CONFIG)
        assert s_yes.final_score - s_no.final_score == 15.0

    def test_score_capped_at_100(self):
        perfect = _make_property(
            price=100000,
            lot_size_acres=5.0,
            bedrooms=3,
            bathrooms=2.0,
            commute_minutes={"Work": 10, "School": 15},
            has_garage=True,
            has_basement=True,
            has_fireplace=True,
        )
        result = score_property(perfect, config=SAMPLE_CONFIG)
        assert result.final_score == 100.0

    def test_score_not_negative(self):
        worst = _make_property(
            price=500000,
            lot_size_acres=0.5,
            bedrooms=5,
            bathrooms=0,
            commute_minutes={"Work": 60},
        )
        result = score_property(worst, config=SAMPLE_CONFIG)
        assert result.final_score >= 0

    def test_missing_data_not_penalized(self):
        full = _make_property()
        partial = _make_property(bathrooms=0)
        s_full = score_property(full, config=SAMPLE_CONFIG)
        s_partial = score_property(partial, config=SAMPLE_CONFIG)
        assert s_partial.final_score > 0

    def test_summary_string(self):
        prop = _make_property(has_garage=True)
        result = score_property(prop, config=SAMPLE_CONFIG)
        summary = result.summary()
        assert "lot_size_acres" in summary
        assert "+has_garage" in summary

    def test_sqft_and_year_not_scored(self):
        """sqft and year_built should not appear in criterion scores."""
        prop = _make_property()
        result = score_property(prop, config=SAMPLE_CONFIG)
        assert "sqft" not in result.criterion_scores
        assert "year_built" not in result.criterion_scores

    def test_none_bonus_awards_zero(self):
        """None (unknown) bonus features should award 0 points, same as False."""
        no_bonus = _make_property(has_garage=False, has_basement=False, has_fireplace=False)
        unknown = _make_property(has_garage=None, has_basement=None, has_fireplace=None)
        s_no = score_property(no_bonus, config=SAMPLE_CONFIG)
        s_unknown = score_property(unknown, config=SAMPLE_CONFIG)
        assert s_no.final_score == s_unknown.final_score
        assert s_unknown.bonus_total == 0.0


class TestBedroomPeakScoring:
    def test_3_beds_scores_highest(self):
        two = _make_property(bedrooms=2)
        three = _make_property(bedrooms=3)
        four = _make_property(bedrooms=4)
        s2 = score_property(two, config=SAMPLE_CONFIG)
        s3 = score_property(three, config=SAMPLE_CONFIG)
        s4 = score_property(four, config=SAMPLE_CONFIG)
        assert s3.final_score > s2.final_score
        assert s3.final_score > s4.final_score

    def test_3_beds_gets_100_normalized(self):
        prop = _make_property(bedrooms=3)
        result = score_property(prop, config=SAMPLE_CONFIG)
        assert result.criterion_scores["bedrooms"] == 100.0

    def test_2_beds_gets_50_normalized(self):
        prop = _make_property(bedrooms=2)
        result = score_property(prop, config=SAMPLE_CONFIG)
        assert result.criterion_scores["bedrooms"] == 50.0

    def test_4_beds_gets_50_normalized(self):
        prop = _make_property(bedrooms=4)
        result = score_property(prop, config=SAMPLE_CONFIG)
        assert result.criterion_scores["bedrooms"] == 50.0

    def test_5_beds_gets_zero(self):
        prop = _make_property(bedrooms=5)
        result = score_property(prop, config=SAMPLE_CONFIG)
        assert result.criterion_scores["bedrooms"] == 0.0


class TestCommuteScoring:
    def test_shorter_commute_scores_higher(self):
        close = _make_property(commute_minutes={"Work": 10, "School": 15})
        far = _make_property(commute_minutes={"Work": 35, "School": 40})
        s_close = score_property(close, config=SAMPLE_CONFIG)
        s_far = score_property(far, config=SAMPLE_CONFIG)
        assert s_close.final_score > s_far.final_score

    def test_threshold_full_points_under_20(self):
        prop = _make_property(commute_minutes={"Work": 15})
        result = score_property(prop, config=SAMPLE_CONFIG)
        assert result.criterion_scores["commute"] == 100.0

    def test_threshold_zero_points_at_46(self):
        prop = _make_property(commute_minutes={"Work": 46})
        result = score_property(prop, config=SAMPLE_CONFIG)
        assert result.criterion_scores["commute"] == 0.0

    def test_threshold_partial_zone(self):
        prop = _make_property(commute_minutes={"Work": 33})
        result = score_property(prop, config=SAMPLE_CONFIG)
        # (46 - 33) / (46 - 20) * 100 = 50.0
        assert result.criterion_scores["commute"] == 50.0

    def test_45_min_gets_minimal_points(self):
        prop = _make_property(commute_minutes={"Work": 45})
        result = score_property(prop, config=SAMPLE_CONFIG)
        # (46 - 45) / (46 - 20) * 100 = 3.8
        assert 3 <= result.criterion_scores["commute"] <= 5

    def test_worst_destination_used(self):
        prop = _make_property(commute_minutes={"Work": 10, "School": 40})
        result = score_property(prop, config=SAMPLE_CONFIG)
        # Worst is 40: (46-40)/(46-20)*100 = 23.1
        assert 20 <= result.criterion_scores["commute"] <= 25

    def test_missing_commute_not_penalized(self):
        prop = _make_property(commute_minutes={})
        result = score_property(prop, config=SAMPLE_CONFIG)
        assert "commute" not in result.criterion_scores
        assert result.final_score > 0


class TestValueRatio:
    def test_value_ratio_computed(self):
        prop = _make_property(price=200000)
        result = score_property(prop, config=SAMPLE_CONFIG)
        # Ratio is computed from unrounded final_score internally, so check approx
        expected = result.final_score / 2.0
        assert abs(result.value_ratio - expected) < 0.15

    def test_cheaper_house_higher_ratio(self):
        cheap = _make_property(price=150000)
        expensive = _make_property(price=450000)
        s_cheap = score_property(cheap, config=SAMPLE_CONFIG)
        s_expensive = score_property(expensive, config=SAMPLE_CONFIG)
        assert s_cheap.value_ratio > s_expensive.value_ratio

    def test_zero_price_gives_zero_ratio(self):
        prop = _make_property(price=0)
        result = score_property(prop, config=SAMPLE_CONFIG)
        assert result.value_ratio == 0.0

    def test_ratio_is_score_per_100k(self):
        prop = _make_property(price=300000)
        result = score_property(prop, config=SAMPLE_CONFIG)
        expected = result.final_score / 3.0
        assert abs(result.value_ratio - expected) < 0.15


class TestNormalizeThreshold:
    def test_under_full_points(self):
        cfg = {"full_points_under": 20, "zero_points_over": 46}
        assert _normalize_threshold(10, cfg) == 100.0
        assert _normalize_threshold(20, cfg) == 100.0

    def test_over_zero_points(self):
        cfg = {"full_points_under": 20, "zero_points_over": 46}
        assert _normalize_threshold(46, cfg) == 0.0
        assert _normalize_threshold(60, cfg) == 0.0

    def test_partial_zone_midpoint(self):
        cfg = {"full_points_under": 20, "zero_points_over": 46}
        assert _normalize_threshold(33, cfg) == 50.0


class TestNormalizePeak:
    def test_at_ideal(self):
        cfg = {"ideal": 3, "min": 1, "max": 5}
        assert _normalize_peak(3, cfg) == 100.0

    def test_at_min(self):
        cfg = {"ideal": 3, "min": 1, "max": 5}
        assert _normalize_peak(1, cfg) == 0.0

    def test_at_max(self):
        cfg = {"ideal": 3, "min": 1, "max": 5}
        assert _normalize_peak(5, cfg) == 0.0

    def test_below_min(self):
        cfg = {"ideal": 3, "min": 1, "max": 5}
        assert _normalize_peak(0, cfg) == 0.0

    def test_above_max(self):
        cfg = {"ideal": 3, "min": 1, "max": 5}
        assert _normalize_peak(6, cfg) == 0.0

    def test_left_side_midpoint(self):
        cfg = {"ideal": 3, "min": 1, "max": 5}
        # 2 is halfway between min=1 and ideal=3
        assert _normalize_peak(2, cfg) == 50.0

    def test_right_side_midpoint(self):
        cfg = {"ideal": 3, "min": 1, "max": 5}
        # 4 is halfway between ideal=3 and max=5
        assert _normalize_peak(4, cfg) == 50.0


class TestHandCalculatedScore:
    def test_specific_score_calculation(self):
        """Verify a hand-calculated score with the new config."""
        # Lot 3.0 acres: (3.0 - 0.5) / (5.0 - 0.5) * 100 = 55.6   (weight 40)
        # Commute worst=20 (full zone): 100.0                        (weight 25)
        # Bedrooms 3 (peak ideal): 100.0                             (weight 20)
        # Bathrooms 2: (2 - 0) / (2 - 0) * 100 = 100.0              (weight 15)
        #
        # Weighted avg = (55.6*40 + 100*25 + 100*20 + 100*15) / 100
        #              = (2224 + 2500 + 2000 + 1500) / 100
        #              = 8224 / 100 = 82.2

        prop = _make_property()
        result = score_property(prop, config=SAMPLE_CONFIG)
        assert 81 <= result.weighted_average <= 84
