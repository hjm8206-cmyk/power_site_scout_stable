import unittest

from app.schemas import ManualInputs
from app.scoring import score_analysis


def _base_analysis(buildings):
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
            "nearest_road_distance_m": 0,
            "nearest_road_type": "공식도로",
            "width_class": "10m 이상",
            "final_width_class": "10m 이상",
            "access_path": {"grade": "A", "method": "직접 접도"},
        },
        "zoning": {"ok": True, "main_zoning": "계획관리지역", "names": ["계획관리지역"]},
        "growth_management": {"ok": True, "status": "성장관리계획구역"},
        "datacenter_permit": {"grade": "검토 가능성 높음", "building_coverage_ratio": "40% 이하", "floor_area_ratio": "100% 이하"},
        "policy": {
            "ok": True,
            "official_adjustment": 15,
            "site_internal_score": 10,
            "power_self_internal_score": 5,
        },
        "slope": {"slope_degree": 5, "slope_grade": "매우 양호"},
        "buildings": buildings,
    }


class ResidentialRiskScoringTest(unittest.TestCase):
    def score(self, buildings, manual=None):
        manual = manual or ManualInputs(power_voltage="345kv", actual_road_10m=True)
        towers = [{"lat": 37.0002, "lng": 127.0002}]
        return score_analysis(_base_analysis(buildings), manual, towers)

    def test_sensitive_facility_within_500m_uses_boundary_distance_cap(self):
        result = self.score(
            {
                "building_count_500m": 20,
                "residential_exposure_150m": 0,
                "residential_exposure_250m": 0,
                "residential_exposure_350m": 0,
                "residential_exposure_500m": 20,
                "residential_confidence": "중간",
                "candidates": [{"lat": 37.00356, "lng": 127.0, "distance_m": 395, "name": "초등학교", "building_use": "초등학교"}],
            }
        )
        self.assertEqual(result["metrics"]["sensitive_facility_penalty"], 15)
        self.assertEqual(result["metrics"]["sensitive_facility_fatal_cap"], 75)
        self.assertLessEqual(result["final_score"], 75)
        self.assertEqual(result["metrics"]["sensitive_facility_penalty_applied"], True)

    def test_school_within_250m_applies_55_cap(self):
        result = self.score(
            {
                "building_count_500m": 10,
                "residential_exposure_150m": 0,
                "residential_exposure_250m": 0,
                "residential_exposure_350m": 0,
                "residential_exposure_500m": 10,
                "residential_confidence": "중간",
                "candidates": [{"lat": 37.00266, "lng": 127.0, "distance_m": 295, "name": "어린이집", "building_use": "어린이집"}],
            }
        )
        self.assertEqual(result["metrics"]["sensitive_facility_penalty"], 30)
        self.assertEqual(result["metrics"]["sensitive_facility_fatal_cap"], 55)
        self.assertLessEqual(result["final_score"], 55)

    def test_sensitive_facility_beyond_500m_is_reference_only(self):
        result = self.score(
            {
                "building_count_500m": 10,
                "residential_exposure_150m": 0,
                "residential_exposure_250m": 0,
                "residential_exposure_350m": 0,
                "residential_exposure_500m": 10,
                "residential_confidence": "중간",
                "candidates": [{"lat": 37.00537, "lng": 127.0, "distance_m": 600, "name": "어린이집", "building_use": "어린이집"}],
            }
        )
        self.assertEqual(result["metrics"]["sensitive_facility_penalty"], 0)
        self.assertIsNone(result["metrics"]["sensitive_facility_fatal_cap"])

    def test_clear_apartment_complex_within_500m_applies_75_cap(self):
        result = self.score(
            {
                "building_count_500m": 30,
                "residential_exposure_150m": 0,
                "residential_exposure_250m": 0,
                "residential_exposure_350m": 0,
                "residential_exposure_500m": 30,
                "residential_confidence": "중간",
                "candidates": [{"lat": 37.00428, "lng": 127.0, "distance_m": 475, "name": "테스트아파트", "building_use": "아파트"}],
            }
        )
        self.assertEqual(result["metrics"]["residential_complex_penalty"], 15)
        self.assertEqual(result["metrics"]["residential_complex_fatal_cap"], 75)
        self.assertLessEqual(result["final_score"], 75)

    def test_apartment_only_in_1km_is_reference_not_penalty(self):
        result = self.score(
            {
                "building_count_500m": 20,
                "residential_exposure_150m": 0,
                "residential_exposure_250m": 0,
                "residential_exposure_350m": 0,
                "residential_exposure_500m": 20,
                "residential_confidence": "중간",
                "candidates": [{"lat": 37.006, "lng": 127.006, "distance_m": 800, "name": "외곽아파트", "building_use": "아파트"}],
            }
        )
        self.assertEqual(result["metrics"]["residential_complex_penalty"], 0)
        self.assertIsNone(result["metrics"]["residential_complex_fatal_cap"])
        self.assertTrue(result["metrics"]["residential_reference_only_1km"])

    def test_village_hall_is_not_large_residential_complex(self):
        result = self.score(
            {
                "building_count_500m": 20,
                "residential_exposure_150m": 0,
                "residential_exposure_250m": 0,
                "residential_exposure_350m": 0,
                "residential_exposure_500m": 20,
                "residential_confidence": "중간",
                "candidates": [{"lat": 37.002, "lng": 127.002, "distance_m": 300, "name": "행복마을회관", "building_use": "마을회관"}],
            }
        )
        self.assertFalse(result["metrics"]["residential_large_complex_detected"])
        self.assertEqual(result["metrics"]["residential_complex_penalty"], 0)

    def test_low_confidence_building_count_does_not_apply_proximity_penalty(self):
        result = self.score({"building_count_500m": 301, "residential_exposure_500m": 301, "candidates": []})
        self.assertEqual(result["metrics"]["residential_penalty_500m"], 5)
        self.assertEqual(result["metrics"]["residential_proximity_penalty_applied"], 0)
        self.assertTrue(result["metrics"]["residential_penalty_not_applied_reason"])

    def test_sensitive_detection_failure_does_not_penalize_or_cap(self):
        analysis = _base_analysis(
            {
                "building_count_500m": 10,
                "residential_exposure_500m": 10,
                "residential_confidence": "중간",
                "candidates": [],
            }
        )
        analysis["places"] = {"ok": False, "message": "Kakao timeout", "sensitive_facilities": [], "residential_complexes": []}
        result = score_analysis(analysis, ManualInputs(power_voltage="345kv", actual_road_10m=True), [{"lat": 37.0002, "lng": 127.0002}])
        self.assertEqual(result["metrics"]["sensitive_facility_penalty"], 0)
        self.assertIsNone(result["metrics"]["sensitive_facility_fatal_cap"])
        self.assertIn("실패", result["metrics"]["sensitive_detection_status"])


if __name__ == "__main__":
    unittest.main()
