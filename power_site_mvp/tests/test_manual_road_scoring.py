import unittest

from app.schemas import ManualInputs
from app.main import _analysis_with_current_roads
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
        "roads": {"ok": False, "road_candidate_count_500m": 0, "access_path": {"grade": "F"}},
        "zoning": {"ok": True, "main_zoning": "계획관리지역", "names": ["계획관리지역"]},
        "growth_management": {"ok": False, "status": "수동확인"},
        "datacenter_permit": {"grade": "검토 가능성 높음", "building_coverage_ratio": "40% 이하", "floor_area_ratio": "100% 이하"},
        "policy": {"ok": True, "official_adjustment": 0, "site_internal_score": 5, "power_self_internal_score": 2},
        "slope": {"slope_degree": 5, "slope_grade": "매우 양호"},
        "buildings": {"building_count_500m": 0, "residential_exposure_500m": 0, "candidates": []},
    }


def _road_score(result):
    return next(item["score"] for item in result["categories"] if item["key"] == "road_access")


def _manual_road(points, width_class):
    return {
        "source": "test",
        "points": points,
        "road_polyline": points,
        "width_class": width_class,
        "tolerance_m": 5,
    }


def _selected_parcel(parcel_id, south=36.9990, north=36.9995, access=False):
    return {
        "id": parcel_id,
        "parcel_role": "access_candidate" if access else "development_candidate",
        "selection_status": "도로 연결 후보" if access else "편입 후보",
        "road_connection_contribution": access,
        "is_incorporation_candidate": not access,
        "polygon": [
            {"lat": south, "lng": 126.9995},
            {"lat": south, "lng": 127.0005},
            {"lat": north, "lng": 127.0005},
            {"lat": north, "lng": 126.9995},
        ],
    }


class ManualRoadScoringTest(unittest.TestCase):
    def test_manual_road_scores_jump_at_6m_and_ignore_farm_road(self):
        towers = [{"lat": 37.0002, "lng": 127.0002}]
        farm = score_analysis(_analysis(), ManualInputs(power_voltage="345kv", farm_or_unpaved_road=True), towers)
        four = score_analysis(_analysis(), ManualInputs(power_voltage="345kv", actual_road_4m=True), towers)
        six = score_analysis(_analysis(), ManualInputs(power_voltage="345kv", actual_road_6m=True), towers)
        ten = score_analysis(_analysis(), ManualInputs(power_voltage="345kv", actual_road_10m=True), towers)

        self.assertEqual(_road_score(farm), 0)
        self.assertEqual(_road_score(four), 5)
        self.assertEqual(_road_score(six), 15)
        self.assertEqual(_road_score(ten), 20)

    def test_difficult_construction_access_scores_zero_without_no_road_penalty(self):
        towers = [{"lat": 37.0002, "lng": 127.0002}]
        result = score_analysis(
            _analysis(),
            ManualInputs(power_voltage="345kv", construction_access_difficult=True),
            towers,
        )

        self.assertEqual(_road_score(result), 0)
        self.assertEqual(result["metrics"]["road_penalty"], 0)

    def test_unchecking_manual_road_rebuilds_from_auto_roads(self):
        analysis = _analysis()
        analysis["roads_auto"] = {
            "ok": True,
            "road_candidate_count_500m": 1,
            "nearest_road_type": "공식도로",
            "width_class": "6m 이상 10m 미만",
            "final_width_class": "6m 이상 10m 미만",
            "access_path": {"grade": "B", "method": "직접 접도"},
        }
        analysis["roads"] = {
            **analysis["roads_auto"],
            "manual_override_width_class": "10m 이상",
            "final_width_class": "10m 이상",
            "access_path": {"grade": "A", "method": "수동보정 직접 접도", "manual_override": True},
        }

        rebuilt = _analysis_with_current_roads(analysis, ManualInputs(power_voltage="345kv"))
        result = score_analysis(rebuilt, ManualInputs(power_voltage="345kv"), [{"lat": 37.0002, "lng": 127.0002}])

        self.assertIsNone(rebuilt["roads"].get("manual_override_width_class"))
        self.assertEqual(_road_score(result), 18)

    def test_manual_polyline_10m_direct_main_parcel_scores_20(self):
        analysis = _analysis()
        analysis["manual_road"] = _manual_road(
            [{"lat": 36.9995, "lng": 126.9992}, {"lat": 36.9995, "lng": 127.0008}],
            "10m 이상",
        )

        result = score_analysis(analysis, ManualInputs(power_voltage="345kv"), [{"lat": 37.0002, "lng": 127.0002}])

        self.assertEqual(_road_score(result), 20)
        self.assertTrue(result["metrics"]["manual_road_applied_to_score"])
        self.assertTrue(result["metrics"]["manual_road_touching_main_parcel"])

    def test_manual_polyline_10m_touching_selected_parcel_scores_18(self):
        analysis = _analysis()
        parcel = _selected_parcel("sel1")
        analysis["parcel_group"]["adjacent"] = [parcel]
        analysis["manual_road"] = _manual_road(
            [{"lat": 36.9990, "lng": 126.9992}, {"lat": 36.9990, "lng": 127.0008}],
            "10m 이상",
        )

        result = score_analysis(
            analysis,
            ManualInputs(power_voltage="345kv"),
            [{"lat": 37.0002, "lng": 127.0002}],
            selected_parcel_ids=["sel1"],
        )

        self.assertEqual(_road_score(result), 18)
        self.assertEqual(result["metrics"]["road_connection_type"], "편입 후보 포함 직접 접도")

    def test_manual_polyline_6m_one_access_parcel_scores_12(self):
        analysis = _analysis()
        parcel = _selected_parcel("access1", access=True)
        analysis["parcel_group"]["adjacent"] = [parcel]
        analysis["manual_road"] = _manual_road(
            [{"lat": 36.9990, "lng": 126.9992}, {"lat": 36.9990, "lng": 127.0008}],
            "6m 이상 10m 미만",
        )

        result = score_analysis(
            analysis,
            ManualInputs(power_voltage="345kv"),
            [{"lat": 37.0002, "lng": 127.0002}],
            selected_parcel_ids=["access1"],
        )

        self.assertEqual(_road_score(result), 12)
        self.assertEqual(result["metrics"]["road_connection_type"], "1필지 경유 접도")

    def test_manual_polyline_4m_direct_main_parcel_scores_5(self):
        analysis = _analysis()
        analysis["manual_road"] = _manual_road(
            [{"lat": 36.9995, "lng": 126.9992}, {"lat": 36.9995, "lng": 127.0008}],
            "4m 이상 6m 미만",
        )

        result = score_analysis(analysis, ManualInputs(power_voltage="345kv"), [{"lat": 37.0002, "lng": 127.0002}])

        self.assertEqual(_road_score(result), 5)

    def test_manual_polyline_not_touching_site_scores_zero(self):
        analysis = _analysis()
        analysis["manual_road"] = _manual_road(
            [{"lat": 37.01, "lng": 126.9992}, {"lat": 37.01, "lng": 127.0008}],
            "10m 이상",
        )

        result = score_analysis(analysis, ManualInputs(power_voltage="345kv"), [{"lat": 37.0002, "lng": 127.0002}])

        self.assertEqual(_road_score(result), 0)
        self.assertFalse(result["metrics"]["manual_road_applied_to_score"])
        self.assertEqual(result["metrics"]["road_connection_type"], "수동도로 있음 / 부지 접도 없음")

    def test_manual_polyline_overrides_auto_4m_road_when_connected(self):
        analysis = _analysis()
        analysis["roads"] = {
            "ok": True,
            "road_candidate_count_500m": 1,
            "nearest_road_type": "공식도로",
            "width_class": "4m 이상 6m 미만",
            "final_width_class": "4m 이상 6m 미만",
            "access_path": {"grade": "D", "method": "직접 접도"},
        }
        analysis["manual_road"] = _manual_road(
            [{"lat": 36.9995, "lng": 126.9992}, {"lat": 36.9995, "lng": 127.0008}],
            "10m 이상",
        )

        result = score_analysis(analysis, ManualInputs(power_voltage="345kv"), [{"lat": 37.0002, "lng": 127.0002}])

        self.assertEqual(_road_score(result), 20)
        self.assertEqual(result["metrics"]["road_score_source"], "manual_road_polyline")

    def test_selected_added_parcel_touching_auto_road_improves_road_score_and_area(self):
        analysis = _analysis()
        parcel = _selected_parcel("sel1")
        parcel["area_m2"] = 10000
        parcel["area_pyeong"] = 3025
        analysis["parcel_group"]["adjacent"] = [parcel]
        analysis["roads"] = {
            "ok": True,
            "road_candidate_count_500m": 1,
            "nearest_road_type": "공식도로",
            "width_class": "10m 이상",
            "final_width_class": "10m 이상",
            "access_path": {"grade": "F", "method": "접도 불명확"},
            "candidates": [
                {
                    "width_class": "10m 이상",
                    "road_type": "공식도로",
                    "distance_m": 60,
                    "geometry": {
                        "type": "LineString",
                        "path": [
                            {"lat": 36.9990, "lng": 126.9992},
                            {"lat": 36.9990, "lng": 127.0008},
                        ],
                    },
                }
            ],
        }

        result = score_analysis(
            analysis,
            ManualInputs(power_voltage="345kv"),
            [{"lat": 37.0002, "lng": 127.0002}],
            selected_parcel_ids=["sel1"],
        )

        self.assertEqual(_road_score(result), 19)
        self.assertTrue(result["metrics"]["selected_road_contact_applied"])
        self.assertEqual(result["metrics"]["selected_summary"]["incorporation_area_m2"], 10000)
        self.assertEqual(result["metrics"]["selected_summary"]["total_area_m2"], 30000)


if __name__ == "__main__":
    unittest.main()
