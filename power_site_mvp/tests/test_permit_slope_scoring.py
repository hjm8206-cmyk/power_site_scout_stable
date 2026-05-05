import unittest

from app.schemas import ManualInputs
from app.scoring import score_analysis


def _analysis():
    return {
        "center": {"lat": 37.0, "lng": 127.0},
        "parcel_group": {
            "main": {
                "id": "main",
                "parcel_role": "development_candidate",
                "area_m2": 20000,
                "area_pyeong": 6050,
                "polygon": [
                    {"lat": 36.9995, "lng": 126.9995},
                    {"lat": 36.9995, "lng": 127.0005},
                    {"lat": 37.0005, "lng": 127.0005},
                    {"lat": 37.0005, "lng": 126.9995},
                ],
            },
            "adjacent": [],
            "summary": {"total_area_m2": 20000, "selected_development_parcel_count": 1},
        },
        "roads": {
            "ok": True,
            "road_candidate_count_500m": 1,
            "width_class": "6m 이상 10m 미만",
            "final_width_class": "6m 이상 10m 미만",
            "access_path": {"grade": "B", "method": "직접 접도"},
        },
        "zoning": {"ok": True, "main_zoning": "보전관리지역", "names": ["보전관리지역"]},
        "growth_management": {"ok": False, "status": "수동확인"},
        "datacenter_permit": {"grade": "검토 가능", "building_coverage_ratio": "20% 이하", "floor_area_ratio": "80% 이하"},
        "policy": {"ok": True, "official_adjustment": 0, "site_internal_score": 5, "power_self_internal_score": 2},
        "slope": {"ok": False, "slope_auto_status": "자동조회 실패", "slope_grade": "수동확인 필요"},
        "buildings": {"building_count_500m": 0, "residential_exposure_500m": 0, "candidates": []},
    }


def _category(result, key):
    return next(item for item in result["categories"] if item["key"] == key)


class PermitSlopeScoringTest(unittest.TestCase):
    def test_conservation_management_is_not_low_score(self):
        result = score_analysis(_analysis(), ManualInputs(power_voltage="345kv"), [{"lat": 37.0002, "lng": 127.0002}])

        self.assertGreaterEqual(_category(result, "permitting")["score"], 15)

    def test_missing_dem_or_contour_is_conditional_without_penalty_or_cap(self):
        result = score_analysis(_analysis(), ManualInputs(power_voltage="345kv"), [{"lat": 37.0002, "lng": 127.0002}])

        self.assertIsNone(_category(result, "slope")["score"])
        self.assertEqual(result["metrics"]["slope_penalty"], 0)
        self.assertIsNone(result["metrics"]["slope_fatal_cap"])
        self.assertIn("경사도 확인 필요", result["conditional_flags"])
        self.assertIn("조건부", result["grade_label"])

    def test_manual_low_slope_overrides_missing_auto_slope(self):
        result = score_analysis(
            _analysis(),
            ManualInputs(power_voltage="345kv", manual_slope_band="low"),
            [{"lat": 37.0002, "lng": 127.0002}],
        )

        self.assertEqual(_category(result, "slope")["score"], 5)
        self.assertEqual(result["metrics"]["slope_penalty"], 0)
        self.assertEqual(result["metrics"]["slope_apply_basis"], "수동")

    def test_manual_high_slope_applies_penalty_and_cap(self):
        result = score_analysis(
            _analysis(),
            ManualInputs(power_voltage="345kv", manual_slope_band="high"),
            [{"lat": 37.0002, "lng": 127.0002}],
        )

        self.assertEqual(_category(result, "slope")["score"], 1)
        self.assertEqual(result["metrics"]["slope_penalty"], 12)
        self.assertEqual(result["metrics"]["slope_fatal_cap"], 70)


if __name__ == "__main__":
    unittest.main()
