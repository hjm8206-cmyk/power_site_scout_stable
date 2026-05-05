from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field


PowerVoltage = Literal["345kv", "154kv", "unknown"]
SlopeManualBand = Literal["auto", "low", "medium", "high", "worst", "unknown"]


class ManualInputs(BaseModel):
    power_voltage: PowerVoltage = "unknown"
    actual_road_10m: bool = False
    actual_road_6m: bool = False
    actual_road_4m: bool = False
    farm_or_unpaved_road: bool = False
    construction_access_difficult: bool = False
    manual_slope_degree: Optional[float] = Field(default=None, ge=0, le=90)
    manual_slope_band: SlopeManualBand = "auto"


class AnalyzeRequest(BaseModel):
    address: str = Field(min_length=1, max_length=300)
    privacy: bool = False
    manual: ManualInputs = Field(default_factory=ManualInputs)


class TowerCandidate(BaseModel):
    lat: float
    lng: float
    label: Optional[str] = None


class ScoreRequest(BaseModel):
    analysis: Dict[str, Any]
    manual: ManualInputs = Field(default_factory=ManualInputs)
    towers: List[TowerCandidate] = Field(default_factory=list)
    selected_parcel_ids: List[str] = Field(default_factory=list)


class ReportRequest(BaseModel):
    analysis: Dict[str, Any]
    manual: ManualInputs = Field(default_factory=ManualInputs)
    towers: List[TowerCandidate] = Field(default_factory=list)
    selected_parcel_ids: List[str] = Field(default_factory=list)
    privacy: bool = False


class PointRequest(BaseModel):
    lat: float
    lng: float


class PolicyReferenceUpsert(BaseModel):
    sido: str = Field(min_length=1, max_length=50)
    sigungu: str = Field(min_length=1, max_length=50)
    lagging_index: float
    lagging_rank: Optional[int] = Field(default=None, ge=1)
    population_density: float = Field(ge=0)
    fiscal_independence_rate: float = Field(ge=0, le=100)
    updated_year: str = Field(min_length=4, max_length=20)
    source_note: str = Field(default="사용자 입력", max_length=300)
