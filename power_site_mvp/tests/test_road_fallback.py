import unittest

from app import road, scoring, vworld
from app.schemas import ManualInputs


MAIN_POLYGON = [
    {"lat": 37.0, "lng": 127.0},
    {"lat": 37.0, "lng": 127.001},
    {"lat": 37.001, "lng": 127.001},
    {"lat": 37.001, "lng": 127.0},
]

TOUCHING_ROAD_POLYGON = [
    {"lat": 36.99992, "lng": 127.0},
    {"lat": 36.99992, "lng": 127.001},
    {"lat": 37.0, "lng": 127.001},
    {"lat": 37.0, "lng": 127.0},
]


class RoadFallbackTest(unittest.TestCase):
    def test_cadastral_road_parcel_counts_when_vworld_road_layer_is_empty(self):
        main = {
            "id": "main",
            "parcel_role": "development_candidate",
            "area_m2": 20000,
            "area_pyeong": 6050,
            "polygon": MAIN_POLYGON,
        }
        road_parcel = {
            "id": "road-1",
            "parcel_role": "access_candidate",
            "land_category": "도로",
            "polygon": TOUCHING_ROAD_POLYGON,
        }

        original_query = vworld.query_vworld_data_layer
        vworld.query_vworld_data_layer = lambda *args, **kwargs: {"features": [], "message": "mock empty"}
        try:
            roads = road.analyze_roads(
                37.0005,
                127.0005,
                {"main": main, "adjacent": [road_parcel], "nearby_parcels": []},
                500,
            )
        finally:
            vworld.query_vworld_data_layer = original_query

        self.assertTrue(roads["ok"])
        self.assertEqual(roads["nearest_road_distance_m"], 0.0)
        self.assertEqual(roads["access_path"]["grade"], "B")

        analysis = {
            "center": {"lat": 37.0005, "lng": 127.0005},
            "parcel_group": {
                "main": main,
                "adjacent": [road_parcel],
                "summary": {"total_area_m2": 20000, "selected_development_parcel_count": 1},
            },
            "roads": roads,
            "zoning": {"ok": True, "main_zoning": "계획관리지역", "names": ["계획관리지역"]},
            "growth_management": {"ok": False, "status": "수동확인"},
            "datacenter_permit": {
                "grade": "검토 가능성 높음",
                "building_coverage_ratio": "40% 이하",
                "floor_area_ratio": "100% 이하",
            },
            "policy": {"ok": True, "official_adjustment": 0, "site_internal_score": 5, "power_self_internal_score": 2},
            "slope": {"slope_degree": 5, "slope_grade": "매우 양호"},
            "buildings": {"building_count_500m": 0, "residential_exposure_500m": 0, "candidates": []},
        }
        score = scoring.score_analysis(
            analysis,
            ManualInputs(power_voltage="unknown"),
            [{"lat": 37.0006, "lng": 127.0006}],
        )
        self.assertGreaterEqual(score["metrics"]["road_score_20"], 18)
        self.assertEqual(score["metrics"]["road_penalty"], 0)


if __name__ == "__main__":
    unittest.main()
