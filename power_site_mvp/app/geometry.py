from __future__ import annotations

import math
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

try:
    from pyproj import Transformer
except Exception:  # pragma: no cover - fallback keeps the app usable.
    Transformer = None

try:
    from shapely.geometry import LineString, Point, Polygon, shape
    from shapely.ops import transform as shapely_transform
except Exception:  # pragma: no cover
    LineString = Point = Polygon = shape = shapely_transform = None


EARTH_RADIUS_M = 6_371_000
PYEONG_PER_M2 = 0.3025

_TO_KOREA_TM = (
    Transformer.from_crs("EPSG:4326", "EPSG:5179", always_xy=True)
    if Transformer
    else None
)


def haversine_distance_m(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    d_phi = math.radians(lat2 - lat1)
    d_lambda = math.radians(lng2 - lng1)
    a = (
        math.sin(d_phi / 2) ** 2
        + math.cos(phi1) * math.cos(phi2) * math.sin(d_lambda / 2) ** 2
    )
    return 2 * EARTH_RADIUS_M * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def bbox_around(lat: float, lng: float, radius_m: float) -> Tuple[float, float, float, float]:
    lat_delta = radius_m / 111_320
    lng_delta = radius_m / (111_320 * max(math.cos(math.radians(lat)), 0.2))
    return (lng - lng_delta, lat - lat_delta, lng + lng_delta, lat + lat_delta)


def to_projected(lng: float, lat: float) -> Tuple[float, float]:
    if _TO_KOREA_TM:
        return _TO_KOREA_TM.transform(lng, lat)
    return _local_xy(lng, lat, lat, lng)


def _project_geometry(geom: Any) -> Any:
    if not (_TO_KOREA_TM and shapely_transform):
        return geom
    return shapely_transform(lambda x, y, z=None: _TO_KOREA_TM.transform(x, y), geom)


def _local_xy(lng: float, lat: float, origin_lat: float, origin_lng: float) -> Tuple[float, float]:
    x = math.radians(lng - origin_lng) * EARTH_RADIUS_M * math.cos(math.radians(origin_lat))
    y = math.radians(lat - origin_lat) * EARTH_RADIUS_M
    return x, y


def polygon_area_m2(points: Sequence[Dict[str, float]]) -> float:
    if len(points) < 3:
        return 0.0
    try:
        if Polygon and _TO_KOREA_TM:
            projected = [to_projected(p["lng"], p["lat"]) for p in points]
            return abs(Polygon(projected).area)
    except Exception:
        pass

    origin = points[0]
    xy = [_local_xy(p["lng"], p["lat"], origin["lat"], origin["lng"]) for p in points]
    area = 0.0
    for idx, (x1, y1) in enumerate(xy):
        x2, y2 = xy[(idx + 1) % len(xy)]
        area += x1 * y2 - x2 * y1
    return abs(area) / 2


def area_to_pyeong(area_m2: Optional[float]) -> Optional[float]:
    if area_m2 is None:
        return None
    return area_m2 * PYEONG_PER_M2


def centroid(points: Sequence[Dict[str, float]]) -> Optional[Dict[str, float]]:
    if not points:
        return None
    try:
        if Polygon:
            poly = Polygon([(p["lng"], p["lat"]) for p in points])
            c = poly.centroid
            return {"lat": c.y, "lng": c.x}
    except Exception:
        pass
    return {
        "lat": sum(p["lat"] for p in points) / len(points),
        "lng": sum(p["lng"] for p in points) / len(points),
    }


def flatten_geojson_points(geometry: Optional[Dict[str, Any]]) -> List[Dict[str, float]]:
    if not geometry:
        return []

    points: List[Dict[str, float]] = []

    def walk(value: Any) -> None:
        if not isinstance(value, list):
            return
        if len(value) >= 2 and all(isinstance(v, (int, float)) for v in value[:2]):
            points.append({"lng": float(value[0]), "lat": float(value[1])})
            return
        for child in value:
            walk(child)

    walk(geometry.get("coordinates"))
    return points


def polygon_rings_from_geojson(geometry: Optional[Dict[str, Any]]) -> List[List[Dict[str, float]]]:
    if not geometry:
        return []
    geometry_type = geometry.get("type")
    coords = geometry.get("coordinates") or []

    def ring_to_points(ring: Iterable[Sequence[float]]) -> List[Dict[str, float]]:
        points = []
        for coord in ring:
            if isinstance(coord, Sequence) and len(coord) >= 2:
                points.append({"lng": float(coord[0]), "lat": float(coord[1])})
        if len(points) > 1 and points[0] == points[-1]:
            points = points[:-1]
        return points

    if geometry_type == "Polygon":
        return [ring_to_points(ring) for ring in coords[:1] if ring]
    if geometry_type == "MultiPolygon":
        rings = []
        for polygon in coords:
            if polygon:
                rings.append(ring_to_points(polygon[0]))
        return rings
    return []


def representative_point_from_geojson(geometry: Optional[Dict[str, Any]]) -> Optional[Dict[str, float]]:
    if not geometry:
        return None
    try:
        if shape:
            geom = shape(geometry)
            point = geom.representative_point()
            return {"lat": point.y, "lng": point.x}
    except Exception:
        pass
    points = flatten_geojson_points(geometry)
    return centroid(points) if points else None


def distance_to_geojson_m(lat: float, lng: float, geometry: Optional[Dict[str, Any]]) -> Optional[float]:
    if not geometry:
        return None
    try:
        if shape and Point:
            geom = _project_geometry(shape(geometry))
            point = Point(*to_projected(lng, lat))
            return float(point.distance(geom))
    except Exception:
        pass
    points = flatten_geojson_points(geometry)
    if not points:
        return None
    if len(points) == 1:
        return haversine_distance_m(lat, lng, points[0]["lat"], points[0]["lng"])
    return point_to_line_distance_m({"lat": lat, "lng": lng}, points)


def point_to_line_distance_m(point: Dict[str, float], line: Sequence[Dict[str, float]]) -> Optional[float]:
    if len(line) < 2:
        return None
    try:
        if LineString and Point:
            projected_line = LineString([to_projected(p["lng"], p["lat"]) for p in line])
            projected_point = Point(*to_projected(point["lng"], point["lat"]))
            return float(projected_point.distance(projected_line))
    except Exception:
        pass

    origin = point
    px, py = 0.0, 0.0
    best: Optional[float] = None
    for a, b in zip(line, line[1:]):
        ax, ay = _local_xy(a["lng"], a["lat"], origin["lat"], origin["lng"])
        bx, by = _local_xy(b["lng"], b["lat"], origin["lat"], origin["lng"])
        dist = _distance_point_to_segment(px, py, ax, ay, bx, by)
        best = dist if best is None else min(best, dist)
    return best


def distance_point_to_polygon_m(point: Dict[str, float], polygon: Sequence[Dict[str, float]]) -> Optional[float]:
    if len(polygon) < 3:
        return None
    try:
        if Polygon and Point:
            poly = Polygon([to_projected(p["lng"], p["lat"]) for p in polygon])
            projected_point = Point(*to_projected(point["lng"], point["lat"]))
            return float(projected_point.distance(poly))
    except Exception:
        pass
    closed = list(polygon) + [polygon[0]]
    return point_to_line_distance_m(point, closed)


def distance_polygon_to_line_m(
    polygon: Sequence[Dict[str, float]], line: Sequence[Dict[str, float]]
) -> Optional[float]:
    if len(polygon) < 3 or len(line) < 2:
        return None
    try:
        if Polygon and LineString:
            poly = Polygon([to_projected(p["lng"], p["lat"]) for p in polygon])
            projected_line = LineString([to_projected(p["lng"], p["lat"]) for p in line])
            return float(poly.distance(projected_line))
    except Exception:
        pass
    closed = list(polygon) + [polygon[0]]
    distances = [point_to_line_distance_m(p, line) for p in closed]
    distances = [d for d in distances if d is not None]
    return min(distances) if distances else None


def polygon_geojson_overlap_ratio(
    polygon: Sequence[Dict[str, float]],
    geojson: Optional[Dict[str, Any]],
) -> Optional[Dict[str, float]]:
    if len(polygon) < 3 or not geojson:
        return None
    try:
        if not (Polygon and shape):
            return None
        parcel_poly = Polygon([to_projected(p["lng"], p["lat"]) for p in polygon])
        other = _project_geometry(shape(geojson))
        if parcel_poly.is_empty or parcel_poly.area <= 0 or other.is_empty:
            return None
        intersection_area = float(parcel_poly.intersection(other).area)
        if intersection_area <= 0:
            return {"overlap_area_m2": 0.0, "overlap_ratio": 0.0}
        return {
            "overlap_area_m2": intersection_area,
            "overlap_ratio": min(100.0, max(0.0, (intersection_area / float(parcel_poly.area)) * 100.0)),
        }
    except Exception:
        return None


def _distance_point_to_segment(px: float, py: float, ax: float, ay: float, bx: float, by: float) -> float:
    dx = bx - ax
    dy = by - ay
    if dx == 0 and dy == 0:
        return math.hypot(px - ax, py - ay)
    t = max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / (dx * dx + dy * dy)))
    cx = ax + t * dx
    cy = ay + t * dy
    return math.hypot(px - cx, py - cy)
