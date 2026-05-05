import unittest

from app.schemas import ManualInputs
from app.scoring import score_analysis


MAIN_POLYGON = [
    {"lat": 36.9995, "lng": 126.9995},
    {"lat": 36.9995, "lng": 127.0005},
    {"lat": 37.0005, "lng": 127.0005},
    {"lat": 37.0005, "lng": 126.9995},
]


def _analysis():
    return {
        "center": {"lat": 37.0, "lng": 127.0},
        "parcel_group": {
            "anchor_point": {"lat": 37.0, "lng": 127.0},
            "main": {
                "id": "main",
                "parcel_role": "development_candidate",
                "area_m2": 20000,
                "area_pyeong": 6050,
                "polygon": MAIN_POLYGON,
            },
            "adjacent": [],
            "summary": {"total_area_m2": 20000, "selected_development_parcel_count": 1},
        },
        "roads": {"ok": True, "road_candidate_count_500m": 1, "access_path": {"grade": "A", "method": "직접 접도"}},
        "zoning": {"ok": True, "main_zoning": "계획관리지역", "names": ["계획관리지역"]},
        "growth_management": {"ok": False},
        "datacenter_permit": {"grade": "검토 가능성 높음", "building_coverage_ratio": "40% 이하", "floor_area_ratio": "100% 이하"},
        "policy": {"ok": True, "official_adjustment": 0, "site_internal_score": 5, "power_self_internal_score": 2},
        "slope": {"ok": False},
        "buildings": {"building_count_500m": 0, "residential_exposure_500m": 0, "candidates": []},
    }


def _manual(voltage="345kv"):
    return ManualInputs(power_voltage=voltage, actual_road_10m=True, manual_slope_band="low")


def _category(result, key):
    return next(item for item in result["categories"] if item["key"] == key)


class PowerAxisScoringTest(unittest.TestCase):
    def test_tower_inside_site_scores_full_location_points(self):
        result = score_analysis(_analysis(), _manual("345kv"), [{"lat": 37.0, "lng": 127.0}])
        transmission = result["metrics"]["transmission"]

        self.assertEqual(transmission["power_axis_relation"], "tower_inside_site")
        self.assertEqual(transmission["power_axis_location_score_20"], 20)
        self.assertEqual(_category(result, "power_axis")["score"], 30)
        self.assertTrue(transmission["power_axis_needs_safety_review"])

    def test_boundary_distance_50_to_150m_is_not_full_score(self):
        result = score_analysis(_analysis(), _manual("unknown"), [{"lat": 37.0, "lng": 127.0016}])
        transmission = result["metrics"]["transmission"]

        self.assertEqual(transmission["power_axis_relation"], "within_150m")
        self.assertEqual(transmission["power_axis_location_score_20"], 10)
        self.assertEqual(_category(result, "power_axis")["score"], 14)

    def test_boundary_distance_150_to_500m_is_reference_level(self):
        result = score_analysis(_analysis(), _manual("154kv"), [{"lat": 37.0, "lng": 127.0040}])
        transmission = result["metrics"]["transmission"]

        self.assertEqual(transmission["power_axis_relation"], "within_500m")
        self.assertEqual(transmission["power_axis_location_score_20"], 5)
        self.assertEqual(_category(result, "power_axis")["score"], 15)

    def test_line_crossing_site_scores_full_location_points(self):
        result = score_analysis(
            _analysis(),
            _manual("154kv"),
            [{"lat": 37.0, "lng": 126.9990}, {"lat": 37.0, "lng": 127.0010}],
        )
        transmission = result["metrics"]["transmission"]

        self.assertEqual(transmission["power_axis_relation"], "line_crosses_site")
        self.assertEqual(transmission["power_axis_location_score_20"], 20)
        self.assertEqual(_category(result, "power_axis")["score"], 30)

    def test_154kv_and_345kv_use_same_voltage_score(self):
        towers = [{"lat": 37.0, "lng": 127.0016}]
        result_345 = score_analysis(_analysis(), _manual("345kv"), towers)
        result_154 = score_analysis(_analysis(), _manual("154kv"), towers)

        self.assertEqual(result_345["metrics"]["transmission"]["power_voltage_score_10"], 10)
        self.assertEqual(result_154["metrics"]["transmission"]["power_voltage_score_10"], 10)
        self.assertEqual(_category(result_345, "power_axis")["score"], _category(result_154, "power_axis")["score"])

    def test_axis_touching_site_boundary_scores_full_location_points(self):
        result = score_analysis(_analysis(), _manual("345kv"), [{"lat": 37.0, "lng": 127.00054}])
        transmission = result["metrics"]["transmission"]

        self.assertEqual(transmission["power_axis_relation"], "tower_on_boundary")
        self.assertEqual(transmission["power_axis_location_score_20"], 20)
        self.assertEqual(_category(result, "power_axis")["score"], 30)

    def test_selected_adjacent_parcel_improves_power_axis_distance_and_score(self):
        analysis = _analysis()
        selected = {
            "id": "sel-east",
            "parcel_role": "development_candidate",
            "selection_status": "편입 후보",
            "is_incorporation_candidate": True,
            "area_m2": 10000,
            "area_pyeong": 3025,
            "polygon": [
                {"lat": 36.9995, "lng": 127.0005},
                {"lat": 36.9995, "lng": 127.0020},
                {"lat": 37.0005, "lng": 127.0020},
                {"lat": 37.0005, "lng": 127.0005},
            ],
        }
        analysis["parcel_group"]["adjacent"] = [selected]

        result = score_analysis(
            analysis,
            _manual("345kv"),
            [{"lat": 37.0, "lng": 127.0012}],
            selected_parcel_ids=["sel-east"],
        )
        transmission = result["metrics"]["transmission"]

        self.assertEqual(transmission["power_axis_relation"], "tower_inside_site")
        self.assertTrue(transmission["power_axis_improved_by_added_parcel"])
        self.assertGreater(transmission["power_axis_main_only_distance_m"], transmission["power_axis_selected_site_distance_m"])
        self.assertEqual(transmission["power_axis_selected_site_distance_m"], 0)
        self.assertEqual(transmission["power_axis_selected_parcel_count"], 1)
        self.assertEqual(_category(result, "power_axis")["score"], 30)


if __name__ == "__main__":
    unittest.main()
