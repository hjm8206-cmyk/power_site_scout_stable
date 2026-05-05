const state = {
  map: null,
  centerMarker: null,
  circles: [],
  circleLabels: [],
  mainParcelPolygon: null,
  adjacentParcelPolygons: new Map(),
  roadOverlays: [],
  accessPathOverlay: null,
  roadContactMarker: null,
  buildingMarkers: [],
  riskMarkers: [],
  mapSearchOverlay: null,
  towerMarkers: [],
  towerLine: null,
  manualRoadMarkers: [],
  manualRoadLine: null,
  markingCaptureLayer: null,
  towerMode: false,
  roadMode: false,
  manualParcelMode: false,
  cadastralOverlayEnabled: false,
  selectedParcelIds: new Set(),
  mainParcelId: null,
  showAllNearbyParcels: false,
  analysis: null
};

const colors = {
  mainParcel: "#16a34a",
  adjacentParcel: "#60a5fa",
  selectedParcel: "#f97316",
  manualParcel: "#8b5cf6",
  viaParcel: "#eab308",
  excludedParcel: "#9ca3af",
  constraintParcel: "#0891b2",
  accessParcel: "#1d4ed8",
  accessPath: "#f97316",
  roadContact: "#dc2626",
  tower: "#dc2626",
  manualRoad: "#0ea5e9",
  circle: "#16a34a"
};

const ROAD_WIDTH_OVERRIDE_IDS = ["actualRoad10m", "actualRoad6m", "actualRoad4m", "constructionAccessDifficult"];
const POLICY_REFERENCE_PRESETS = [
  {
    sido: "경기",
    sigungu: "광주",
    lagging_index: 0.277,
    lagging_rank: 45,
    population_density: 966.5,
    fiscal_independence_rate: 31.12,
    updated_year: "2026",
    source_note: "KDI PIMAC 지역낙후도지수 및 순위갱신 2025 기준, 경기 광주시 종합 지역낙후도지수 0.277, 순위 45"
  },
  {
    sido: "경기",
    sigungu: "여주",
    lagging_index: -0.174,
    lagging_rank: 85,
    population_density: "",
    fiscal_independence_rate: "",
    updated_year: "2026",
    source_note: "KDI PIMAC 지역낙후도지수 및 순위갱신 2025 기준, 경기 여주시 종합 지역낙후도지수 -0.174, 순위 85"
  }
];

const ZONING_SCORE_OPTIONS = [
  { value: "", label: "미확인", score: 0, penalty: 0 },
  { value: "계획관리지역", label: "계획관리지역", score: 20, penalty: 0 },
  { value: "자연녹지지역", label: "자연녹지지역", score: 20, penalty: 0 },
  { value: "일반공업지역", label: "일반공업지역", score: 20, penalty: 0 },
  { value: "준공업지역", label: "준공업지역", score: 20, penalty: 0 },
  { value: "전용공업지역", label: "전용공업지역", score: 20, penalty: 0 },
  { value: "중심상업지역", label: "중심상업지역", score: 20, penalty: 0 },
  { value: "일반상업지역", label: "일반상업지역", score: 20, penalty: 0 },
  { value: "근린상업지역", label: "근린상업지역", score: 20, penalty: 0 },
  { value: "유통상업지역", label: "유통상업지역", score: 20, penalty: 0 },
  { value: "준주거지역", label: "준주거지역", score: 20, penalty: 0 },
  { value: "생산관리지역", label: "생산관리지역", score: 17, penalty: 0 },
  { value: "보전관리지역", label: "보전관리지역", score: 17, penalty: 0 },
  { value: "생산녹지지역", label: "생산녹지지역", score: 17, penalty: 0 },
  { value: "제1종일반주거지역", label: "제1종일반주거지역", score: 15, penalty: 0 },
  { value: "제2종일반주거지역", label: "제2종일반주거지역", score: 15, penalty: 0 },
  { value: "제3종일반주거지역", label: "제3종일반주거지역", score: 15, penalty: 0 },
  { value: "보전녹지지역", label: "보전녹지지역", score: 10, penalty: 0 },
  { value: "농림지역", label: "농림지역", score: 4, penalty: 10 },
  { value: "개발제한구역", label: "개발제한구역", score: 0, penalty: 25 },
  { value: "자연환경보전지역", label: "자연환경보전지역", score: 0, penalty: 0 },
  { value: "상수원보호구역", label: "상수원보호구역", score: 0, penalty: 0 }
];

document.addEventListener("DOMContentLoaded", () => {
  seedPolicyReferencePresets();
  initMap();
  setupResponsiveMapPlacement();
  bindEvents();
  renderInitialNotices();
});

function setupResponsiveMapPlacement() {
  const mobileQuery = window.matchMedia("(max-width: 980px)");
  const applyPlacement = () => {
    const mapPanel = document.querySelector(".map-panel");
    const mobileSlot = document.getElementById("mobileMapSlot");
    const workspace = document.querySelector(".workspace");
    const resultPanel = document.querySelector(".result-panel");
    if (!mapPanel || !mobileSlot || !workspace || !resultPanel) return;

    if (mobileQuery.matches) {
      if (mapPanel.parentElement !== mobileSlot) {
        mobileSlot.appendChild(mapPanel);
        mobileSlot.setAttribute("aria-hidden", "false");
        relayoutMapSoon();
      }
      return;
    }

    if (mapPanel.parentElement !== workspace) {
      workspace.insertBefore(mapPanel, resultPanel);
      mobileSlot.setAttribute("aria-hidden", "true");
      relayoutMapSoon();
    }
  };

  applyPlacement();
  if (typeof mobileQuery.addEventListener === "function") {
    mobileQuery.addEventListener("change", applyPlacement);
  } else if (typeof mobileQuery.addListener === "function") {
    mobileQuery.addListener(applyPlacement);
  }
  window.addEventListener("orientationchange", () => setTimeout(applyPlacement, 180));
}

function relayoutMapSoon() {
  [80, 320].forEach((delay) => {
    setTimeout(() => {
      if (state.map) state.map.relayout();
    }, delay);
  });
}

function bindEvents() {
  document.getElementById("searchForm").addEventListener("submit", handleAnalyze);
  document.getElementById("addressInput")?.addEventListener("input", handleAddressInputChanged);
  document.querySelectorAll("[data-map-type]").forEach((button) => {
    button.addEventListener("click", () => setMapType(button.dataset.mapType));
  });
  document.getElementById("towerModeButton").addEventListener("click", toggleTowerMode);
  document.getElementById("roadModeButton").addEventListener("click", toggleRoadMode);
  document.getElementById("manualParcelModeButton").addEventListener("click", toggleManualParcelMode);
  document.getElementById("removeManualParcelButton").addEventListener("click", removeManualParcel);
  document.getElementById("undoTowerButton").addEventListener("click", undoTower);
  document.getElementById("clearRoadButton").addEventListener("click", removeManualRoadPoint);
  document.getElementById("manualRoadWidth")?.addEventListener("change", () => {
    refreshManualRoadLine();
    attachManualRoadToAnalysis();
    refreshScore();
  });
  document.getElementById("downloadMarkdown")?.addEventListener("click", () => downloadReport("markdown"));
  document.getElementById("policyReferenceForm").addEventListener("submit", handlePolicyReferenceSave);
  bindRoadWidthOverrideControls();
  document.getElementById("showMoreParcelsButton")?.addEventListener("click", () => {
    state.showAllNearbyParcels = !state.showAllNearbyParcels;
    if (state.analysis) renderNearbyParcelTable(state.analysis);
  });

  [
    "powerVoltage",
    "manualSlopeBand"
  ].forEach((id) => document.getElementById(id)?.addEventListener("change", refreshScore));
}

function bindRoadWidthOverrideControls() {
  ROAD_WIDTH_OVERRIDE_IDS.forEach((id) => {
    document.getElementById(id)?.addEventListener("change", (event) => {
      if (event.target.checked) {
        ROAD_WIDTH_OVERRIDE_IDS
          .filter((otherId) => otherId !== id)
          .forEach((otherId) => {
            const other = document.getElementById(otherId);
            if (other) other.checked = false;
          });
      }
      refreshScore();
    });
  });
}

function initMap() {
  const fallback = document.getElementById("mapFallback");
  if (!window.kakao || !kakao.maps) {
    fallback.hidden = false;
    fallback.textContent = `Kakao 지도 JS 로딩 실패. Vercel 환경변수 KAKAO_JS_KEY와 Kakao JavaScript 플랫폼 도메인(${currentServiceDomain()})을 확인하세요.`;
    return;
  }

  state.map = new kakao.maps.Map(document.getElementById("map"), {
    center: new kakao.maps.LatLng(36.5, 127.8),
    level: 11,
    mapTypeId: kakao.maps.MapTypeId.HYBRID
  });
  ensureMarkingCaptureLayer();
  kakao.maps.event.addListener(state.map, "click", (event) => {
    if (state.towerMode) {
      addTower(event.latLng);
      return;
    }
    if (state.roadMode) {
      addManualRoadPoint(event.latLng);
      return;
    }
    if (state.manualParcelMode) addManualParcel(event.latLng);
  });
  kakao.maps.event.addListener(state.map, "rightclick", handleMapRightClick);
}

function ensureMarkingCaptureLayer() {
  if (state.markingCaptureLayer) return state.markingCaptureLayer;
  const mapPanel = document.querySelector(".map-panel");
  const mapEl = document.getElementById("map");
  if (!mapPanel || !mapEl) return null;
  const layer = document.createElement("div");
  layer.id = "markingCaptureLayer";
  layer.className = "marking-capture-layer";
  layer.hidden = true;
  layer.setAttribute("aria-hidden", "true");
  layer.addEventListener("click", (event) => {
    if (!state.towerMode && !state.roadMode) return;
    event.preventDefault();
    event.stopPropagation();
    const latLng = latLngFromMapPointerEvent(event);
    if (!latLng) return;
    if (state.towerMode) {
      addTower(latLng);
      return;
    }
    if (state.roadMode) addManualRoadPoint(latLng);
  });
  mapPanel.appendChild(layer);
  state.markingCaptureLayer = layer;
  return layer;
}

function latLngFromMapPointerEvent(event) {
  if (!state.map || !window.kakao?.maps) return null;
  const mapEl = document.getElementById("map");
  if (!mapEl) return null;
  const rect = mapEl.getBoundingClientRect();
  const x = event.clientX - rect.left;
  const y = event.clientY - rect.top;
  if (x < 0 || y < 0 || x > rect.width || y > rect.height) return null;
  const projection = state.map.getProjection?.();
  if (!projection?.coordsFromContainerPoint) return null;
  return projection.coordsFromContainerPoint(new kakao.maps.Point(x, y));
}

function syncMarkingCaptureLayer() {
  const layer = ensureMarkingCaptureLayer();
  if (!layer) return;
  const active = Boolean(state.towerMode || state.roadMode);
  layer.hidden = !active;
  layer.classList.toggle("active", active);
  layer.classList.toggle("tower-mode", Boolean(state.towerMode));
  layer.classList.toggle("road-mode", Boolean(state.roadMode));
  layer.dataset.label = state.towerMode
    ? "송전탑 마킹 중: 필지 선택은 잠시 비활성화됩니다."
    : state.roadMode
      ? "가상도로 마킹 중: 필지 위를 클릭해도 도로로 입력됩니다."
      : "";
  layer.setAttribute("aria-hidden", active ? "false" : "true");
}

function handleMapRightClick(event) {
  const latLng = event.latLng;
  const position = { lat: latLng.getLat(), lng: latLng.getLng() };
  showMapSearchOverlay(latLng, {
    title: "주소 확인 중",
    address: `${position.lat.toFixed(6)}, ${position.lng.toFixed(6)}`,
    loading: true
  });
  reverseGeocodePosition(position)
    .then((address) => {
      showMapSearchOverlay(latLng, {
        title: "이 위치로 재검색",
        address: address || `${position.lat.toFixed(6)}, ${position.lng.toFixed(6)}`,
        position
      });
    })
    .catch(() => {
      showMapSearchOverlay(latLng, {
        title: "주소 확인 실패",
        address: `${position.lat.toFixed(6)}, ${position.lng.toFixed(6)}`,
        helper: "좌표 주소 변환에 실패했습니다. 지도를 조금 이동해 다시 시도하세요.",
        position,
        disabled: true
      });
    });
}

function reverseGeocodePosition(position) {
  return new Promise((resolve, reject) => {
    if (!window.kakao?.maps?.services?.Geocoder) {
      reject(new Error("Kakao geocoder unavailable"));
      return;
    }
    const geocoder = new kakao.maps.services.Geocoder();
    geocoder.coord2Address(position.lng, position.lat, (result, status) => {
      if (status !== kakao.maps.services.Status.OK || !result?.length) {
        reject(new Error("No address"));
        return;
      }
      const first = result[0] || {};
      const address = first.road_address?.address_name || first.address?.address_name;
      if (address) resolve(address);
      else reject(new Error("No address name"));
    });
  });
}

function showMapSearchOverlay(latLng, options) {
  clearMapSearchOverlay();
  const wrap = document.createElement("div");
  wrap.className = "map-search-overlay";

  const title = document.createElement("strong");
  title.textContent = options.title || "지도 위치";
  wrap.appendChild(title);

  const address = document.createElement("p");
  address.textContent = options.address || "-";
  wrap.appendChild(address);

  if (options.helper) {
    const helper = document.createElement("small");
    helper.textContent = options.helper;
    wrap.appendChild(helper);
  }

  const actions = document.createElement("div");
  actions.className = "map-search-actions";

  const searchButton = document.createElement("button");
  searchButton.type = "button";
  searchButton.textContent = options.loading ? "확인 중" : "이 주소로 재검색";
  searchButton.disabled = Boolean(options.loading || options.disabled);
  searchButton.addEventListener("click", () => {
    const nextAddress = options.address || "";
    if (!nextAddress || options.disabled) return;
    const input = document.getElementById("addressInput");
    if (input) input.value = nextAddress;
    clearMapSearchOverlay();
    document.getElementById("searchForm")?.requestSubmit();
  });
  actions.appendChild(searchButton);

  const closeButton = document.createElement("button");
  closeButton.type = "button";
  closeButton.textContent = "닫기";
  closeButton.addEventListener("click", clearMapSearchOverlay);
  actions.appendChild(closeButton);

  wrap.appendChild(actions);
  state.mapSearchOverlay = new kakao.maps.CustomOverlay({
    position: latLng,
    content: wrap,
    yAnchor: 1.08,
    zIndex: 20
  });
  state.mapSearchOverlay.setMap(state.map);
}

function clearMapSearchOverlay() {
  if (state.mapSearchOverlay) {
    state.mapSearchOverlay.setMap(null);
    state.mapSearchOverlay = null;
  }
}

function renderInitialNotices() {
  const notices = [];
  const status = window.APP_CONFIG?.keyStatus || {};
  const currentDomain = currentServiceDomain();
  if (!status.kakao_rest) notices.push("KAKAO_REST_API_KEY가 없어 주소 검색은 VWorld fallback만 시도합니다.");
  if (!status.kakao_js) notices.push(`KAKAO_JS_KEY가 없어 지도가 표시되지 않습니다. Kakao JavaScript 플랫폼 도메인에 ${currentDomain} 을 등록하세요.`);
  if (!status.vworld) notices.push("VWORLD_API_KEY가 없어 필지, 용도지역, 도로, 건물 자동조회는 수동확인으로 표시합니다.");
  notices.push(`VWorld 서비스 URL 기준: ${window.APP_CONFIG?.vworldDomain || currentDomain}`);
  renderNotices(notices);
}

function currentServiceDomain() {
  return window.APP_CONFIG?.vworldDomain || window.location?.origin || "http://localhost:8501";
}

function handleAddressInputChanged() {
  const currentAddress = document.getElementById("addressInput").value.trim();
  if (state.analysis?.address && currentAddress !== state.analysis.address) {
    resetManualControlsForNewAddress();
  }
}

async function handleAnalyze(event) {
  event.preventDefault();
  const address = document.getElementById("addressInput").value.trim();
  if (!address) return;

  setBusy(true);
  resetInteractiveState();
  resetManualControlsForNewAddress();
  clearMapAnalysis();
  state.selectedParcelIds.clear();
  state.mainParcelId = null;
  state.showAllNearbyParcels = false;
  state.analysis = null;
  try {
    const response = await fetch("/api/analyze", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        address,
        privacy: document.getElementById("privacyToggle").checked,
        manual: collectManual()
      })
    });
    const data = await parseJsonResponse(response, "분석 요청");
    state.analysis = data;
    renderNotices([...(data.warnings || []), data.buildings?.notice, data.roads?.notice, data.roads?.access_notice, data.datacenter_permit?.notice, data.policy?.notice, data.slope?.notice].filter(Boolean));
    if (!data.ok) {
      renderResults(data);
      return;
    }
    initializeParcelState(data);
    moveMapTo(data.center);
    drawAnalysis(data);
    renderResults(data);
  } catch (error) {
    renderNotices([`분석 요청 실패: ${error.message}`]);
  } finally {
    setBusy(false);
  }
}

function moveMapTo(center) {
  if (!state.map || !center) return;
  const latLng = new kakao.maps.LatLng(center.lat, center.lng);
  state.map.setCenter(latLng);
  state.map.setLevel(6);
  state.centerMarker = new kakao.maps.CustomOverlay({
    position: latLng,
    content: '<span class="anchor-pin" title="주소 기준점">★</span>',
    xAnchor: 0.5,
    yAnchor: 0.5,
    map: state.map
  });
}

function drawAnalysis(data) {
  if (!state.map || !data.center) return;
  drawRadiusCircles(data.center);
  drawParcels(data.parcel_group);
  drawRoads(data.roads);
  drawBuildings(data.buildings);
  drawResidentialRiskPlaces(data.places, data.score?.metrics);
  drawAccessPathFromAnalysis();
}

function drawRadiusCircles(center) {
  const centerPoint = new kakao.maps.LatLng(center.lat, center.lng);
  [[250, "250m"], [350, "350m"], [500, "500m"], [1000, "1km"], [3000, "3km"], [5000, "5km"]].forEach(([radius, label]) => {
    const circle = new kakao.maps.Circle({
      center: centerPoint,
      radius,
      strokeWeight: 2,
      strokeColor: colors.circle,
      strokeOpacity: 0.55,
      fillColor: "#dcfce7",
      fillOpacity: 0.06,
      map: state.map
    });
    const labelPosition = offsetLatLng(center.lat, center.lng, radius);
    const overlay = new kakao.maps.CustomOverlay({
      position: new kakao.maps.LatLng(labelPosition.lat, labelPosition.lng),
      content: `<span class="map-label">${label}</span>`,
      yAnchor: 0.5,
      map: state.map
    });
    state.circles.push(circle);
    state.circleLabels.push(overlay);
  });
}

function drawParcels(parcelGroup) {
  const main = parcelGroup?.main;
  if (main?.polygon?.length) {
    state.mainParcelPolygon = createParcelPolygon(main, colors.mainParcel, "#bbf7d0", 0.32);
    kakao.maps.event.addListener(state.mainParcelPolygon, "click", (mouseEvent) => {
      preventMapClickBubble();
      if (handleMarkingModeMapClick(mouseEvent)) return;
      renderParcelFocus(main);
    });
  }
  const adjacentForDisplay = parcelGroup?.display_adjacent?.length
    ? parcelGroup.display_adjacent
    : (parcelGroup?.displayed_parcels || parcelGroup?.adjacent || []).filter((parcel) => String(parcel?.id) !== String(main?.id));
  adjacentForDisplay.forEach((parcel) => {
    const style = parcelBaseStyle(parcel);
    const polygon = createParcelPolygon(parcel, style.strokeColor, style.fillColor, style.fillOpacity);
    if (!polygon) return;
    state.adjacentParcelPolygons.set(String(parcel.id), polygon);
    kakao.maps.event.addListener(polygon, "click", (mouseEvent) => {
      preventMapClickBubble();
      if (handleMarkingModeMapClick(mouseEvent)) return;
      toggleParcelSelection(parcel);
    });
  });
  syncParcelClickabilityForMarkingMode();
}

function isMapMarkingModeActive() {
  return Boolean(state.towerMode || state.roadMode || state.manualParcelMode);
}

function syncParcelClickabilityForMarkingMode() {
  const clickable = !(state.towerMode || state.roadMode);
  if (state.mainParcelPolygon) state.mainParcelPolygon.setOptions({ clickable });
  state.adjacentParcelPolygons.forEach((polygon) => polygon.setOptions({ clickable }));
}

function handleMarkingModeMapClick(mouseEvent) {
  if (!state.towerMode && !state.roadMode) return false;
  const latLng = mouseEvent?.latLng;
  if (!latLng) return true;
  if (state.towerMode) {
    addTower(latLng);
    return true;
  }
  if (state.roadMode) {
    addManualRoadPoint(latLng);
    return true;
  }
  return false;
}

function preventMapClickBubble() {
  if (window.kakao?.maps?.event?.preventMap) {
    kakao.maps.event.preventMap();
  }
}

function createParcelPolygon(parcel, strokeColor, fillColor, fillOpacity) {
  if (!parcel?.polygon?.length || !state.map) return null;
  return new kakao.maps.Polygon({
    path: parcel.polygon.map((p) => new kakao.maps.LatLng(p.lat, p.lng)),
    strokeWeight: parcel.role === "main" ? 3 : 2,
    strokeColor,
    strokeOpacity: 0.95,
    fillColor,
    fillOpacity,
    clickable: !(state.towerMode || state.roadMode),
    map: state.map
  });
}

function initializeParcelState(data) {
  const group = data?.parcel_group || {};
  const main = group.main || data?.parcel || {};
  state.selectedParcelIds.clear();
  state.mainParcelId = main?.id || null;
  if (main?.id) {
    main.role = "main";
    main.selection_status = "메인 필지";
    main.is_incorporation_candidate = false;
  }
  [group.adjacent || [], group.display_adjacent || [], group.displayed_parcels || [], group.nearby_parcels || []].forEach((bucket) => {
    bucket.forEach((parcel) => {
      if (!parcel?.id || String(parcel.id) === String(state.mainParcelId)) return;
      if (parcel.is_incorporation_candidate || parcel.selection_status === "편입 후보" || parcel.selection_status === "도로 연결 후보") {
        state.selectedParcelIds.add(String(parcel.id));
      }
    });
  });
}

function toggleParcelSelection(parcel) {
  const id = String(parcel.id);
  if (parcel.parcel_role === "constraint_parcel") {
    parcel.selection_status = "검토 후보";
    parcel.is_incorporation_candidate = false;
    state.selectedParcelIds.delete(id);
    syncParcelSelectionStatus(id, parcel.selection_status, parcel.road_connection_contribution, false);
    renderParcelFocus(parcel);
    updateParcelStyles();
    renderNotices(["구거·하천·제방·유지 등 제약 필지는 개발면적에 자동 합산하지 않습니다."]);
    refreshScore();
    return;
  }
  if (parcel.parcel_role === "access_candidate") {
    if (state.selectedParcelIds.has(id)) {
      state.selectedParcelIds.delete(id);
      parcel.selection_status = "검토 후보";
      parcel.road_connection_contribution = false;
    } else {
      state.selectedParcelIds.add(id);
      parcel.selection_status = "도로 연결 후보";
      parcel.road_connection_contribution = true;
    }
    parcel.is_incorporation_candidate = false;
    syncParcelSelectionStatus(id, parcel.selection_status, parcel.road_connection_contribution, false);
    renderParcelFocus(parcel);
    updateParcelStyles();
    refreshScore();
    return;
  }
  if (state.selectedParcelIds.has(id)) {
    state.selectedParcelIds.delete(id);
    parcel.selection_status = "검토 후보";
    parcel.is_incorporation_candidate = false;
  } else {
    state.selectedParcelIds.add(id);
    parcel.selection_status = "편입 후보";
    parcel.is_incorporation_candidate = true;
  }
  syncParcelSelectionStatus(id, parcel.selection_status, parcel.road_connection_contribution, parcel.is_incorporation_candidate);
  renderParcelFocus(parcel);
  updateParcelStyles();
  refreshScore();
}

function updateParcelStyles() {
  const viaIds = new Set(getViaParcels().map((item) => String(item.id)));
  const adjacent = state.analysis?.parcel_group?.adjacent || [];
  const manualIds = new Set(adjacent.filter((item) => item.role === "manual_added" || item.manual_added).map((item) => String(item.id)));
  state.adjacentParcelPolygons.forEach((polygon, id) => {
    const parcelId = String(id);
    const selected = state.selectedParcelIds.has(parcelId);
    const via = viaIds.has(parcelId);
    const manual = manualIds.has(parcelId);
    const parcel = findParcelById(id) || {};
    const base = parcelBaseStyle(parcel);
    const style = selected
      ? { strokeColor: colors.selectedParcel, fillColor: "#fed7aa", fillOpacity: 0.44, strokeWeight: 3 }
      : via
        ? { strokeColor: colors.viaParcel, fillColor: "#fef3c7", fillOpacity: 0.36, strokeWeight: 3 }
        : manual
          ? { strokeColor: colors.manualParcel, fillColor: "#ede9fe", fillOpacity: 0.34, strokeWeight: 2 }
          : parcel.selection_status === "제외"
            ? { strokeColor: colors.excludedParcel, fillColor: "#e5e7eb", fillOpacity: 0.12, strokeWeight: 1 }
          : { ...base, strokeWeight: 2 };
    polygon.setOptions(style);
  });
}

function parcelBaseStyle(parcel) {
  if (parcel.role === "manual_added") {
    return { strokeColor: colors.manualParcel, fillColor: "#ede9fe", fillOpacity: 0.34 };
  }
  if (parcel.parcel_role === "constraint_parcel") {
    return { strokeColor: colors.constraintParcel, fillColor: "#cffafe", fillOpacity: 0.36 };
  }
  if (parcel.parcel_role === "access_candidate") {
    return { strokeColor: colors.accessParcel, fillColor: "#dbeafe", fillOpacity: 0.34 };
  }
  return { strokeColor: colors.adjacentParcel, fillColor: "#dbeafe", fillOpacity: 0.24 };
}

function drawRoads(roads) {
  (roads?.candidates || []).slice(0, 16).forEach((candidate) => {
    const style = candidate.style || {};
    const overlay = drawGeometry(candidate.geometry, {
      color: style.color || "#2563eb",
      strokeStyle: style.strokeStyle || "solid",
      weight: style.weight || 3,
      opacity: style.opacity ?? 0.85
    });
    if (overlay) state.roadOverlays.push(overlay);
  });
}

function drawBuildings(buildings) {
  if (!state.map) return;
  (buildings?.candidates || []).slice(0, 220).forEach((candidate) => {
    const marker = new kakao.maps.CustomOverlay({
      position: new kakao.maps.LatLng(candidate.lat, candidate.lng),
      content: '<span class="building-square"></span>',
      yAnchor: 0.5,
      xAnchor: 0.5,
      map: state.map
    });
    state.buildingMarkers.push(marker);
  });
}

function drawResidentialRiskPlaces(places, metrics) {
  if (!state.map) return;
  const sensitive = dedupeRiskPlaces([
    ...(places?.sensitive_facilities || []),
    ...(metrics?.sensitive_facilities || [])
  ]).slice(0, 40);
  const complexes = dedupeRiskPlaces([
    ...(places?.residential_complexes || []),
    ...(metrics?.residential_complexes || [])
  ]).slice(0, 40);
  sensitive.forEach((item) => {
    if (item.lat === undefined || item.lng === undefined) return;
    const markerClass = /병원|요양|의료|노인/.test(`${item.name || ""} ${item.type || ""}`) ? "medical" : "school";
    const marker = new kakao.maps.CustomOverlay({
      position: new kakao.maps.LatLng(item.lat, item.lng),
      content: `<span class="risk-marker ${markerClass}" title="${escapeHtml(item.name || "민감시설")}">${markerClass === "medical" ? "+" : "!"}</span>`,
      yAnchor: 0.5,
      xAnchor: 0.5,
      map: state.map
    });
    state.riskMarkers.push(marker);
  });
  complexes.forEach((item) => {
    if (item.lat === undefined || item.lng === undefined) return;
    const marker = new kakao.maps.CustomOverlay({
      position: new kakao.maps.LatLng(item.lat, item.lng),
      content: `<span class="risk-marker complex" title="${escapeHtml(item.name || "주거단지")}">A</span>`,
      yAnchor: 0.5,
      xAnchor: 0.5,
      map: state.map
    });
    state.riskMarkers.push(marker);
  });
}

function dedupeRiskPlaces(items) {
  const seen = new Set();
  return (items || []).filter((item) => {
    if (item.lat === undefined || item.lng === undefined) return false;
    const key = `${item.name || item.id || ""}:${Number(item.lat).toFixed(5)}:${Number(item.lng).toFixed(5)}`;
    if (seen.has(key)) return false;
    seen.add(key);
    return true;
  });
}

function drawAccessPathFromAnalysis() {
  if (!state.map || !state.analysis) return;
  if (state.accessPathOverlay) state.accessPathOverlay.setMap(null);
  if (state.roadContactMarker) state.roadContactMarker.setMap(null);
  state.accessPathOverlay = null;
  state.roadContactMarker = null;

  const path = state.analysis.score?.metrics?.effective_access_path || state.analysis.roads?.access_path || {};
  const roadPoint = path.road_contact_point;
  if (roadPoint?.lat && roadPoint?.lng) {
    state.roadContactMarker = new kakao.maps.CustomOverlay({
      position: new kakao.maps.LatLng(roadPoint.lat, roadPoint.lng),
      content: '<span class="road-contact-dot"></span>',
      yAnchor: 0.5,
      xAnchor: 0.5,
      map: state.map
    });
  }

  const group = state.analysis.parcel_group || {};
  const points = [];
  const mainCenter = group.main?.centroid || centroid(group.main?.polygon);
  if (mainCenter) points.push(mainCenter);
  (path.via_parcels || []).forEach((parcel) => {
    const p = parcel.centroid || centroid(parcel.polygon);
    if (p) points.push(p);
  });
  if (roadPoint?.lat && roadPoint?.lng) points.push(roadPoint);
  if (points.length >= 2) {
    state.accessPathOverlay = new kakao.maps.Polyline({
      path: points.map((p) => new kakao.maps.LatLng(p.lat, p.lng)),
      strokeWeight: 5,
      strokeColor: colors.accessPath,
      strokeOpacity: 0.9,
      strokeStyle: "shortdash",
      map: state.map
    });
  }
  updateParcelStyles();
}

function drawGeometry(geometry, style) {
  if (!state.map || !geometry) return null;
  if (geometry.type === "LineString" && geometry.path?.length > 1) {
    return new kakao.maps.Polyline({
      path: geometry.path.map((p) => new kakao.maps.LatLng(p.lat, p.lng)),
      strokeWeight: style.weight,
      strokeColor: style.color,
      strokeOpacity: style.opacity,
      strokeStyle: style.strokeStyle,
      map: state.map
    });
  }
  if (geometry.type === "Polygon" && geometry.path?.length > 2) {
    return new kakao.maps.Polygon({
      path: geometry.path.map((p) => new kakao.maps.LatLng(p.lat, p.lng)),
      strokeWeight: style.weight,
      strokeColor: style.color,
      strokeOpacity: style.opacity,
      fillColor: style.color,
      fillOpacity: 0.08,
      map: state.map
    });
  }
  return null;
}

function setMapType(type) {
  document.querySelectorAll("[data-map-type]").forEach((button) => {
    button.classList.toggle("active", button.dataset.mapType === type);
  });
  if (!state.map || !window.kakao) return;
  state.map.setMapTypeId(kakao.maps.MapTypeId[type] || kakao.maps.MapTypeId.ROADMAP);
  setCadastralOverlay(type === "ROADMAP");
}

function setCadastralOverlay(enabled) {
  if (!state.map || !window.kakao || !kakao.maps.MapTypeId?.USE_DISTRICT) return;
  if (enabled && !state.cadastralOverlayEnabled) {
    state.map.addOverlayMapTypeId(kakao.maps.MapTypeId.USE_DISTRICT);
    state.cadastralOverlayEnabled = true;
  } else if (!enabled && state.cadastralOverlayEnabled) {
    state.map.removeOverlayMapTypeId(kakao.maps.MapTypeId.USE_DISTRICT);
    state.cadastralOverlayEnabled = false;
  }
}

function enableContourOverlay() {
  // Disabled: Kakao terrain/contour overlay can blank the map in this MVP.
}

function toggleTowerMode(force) {
  state.towerMode = typeof force === "boolean" ? force : !state.towerMode;
  if (state.towerMode && state.manualParcelMode) toggleManualParcelMode(false);
  if (state.towerMode && state.roadMode) toggleRoadMode(false);
  const button = document.getElementById("towerModeButton");
  button.classList.toggle("active", state.towerMode);
  button.textContent = state.towerMode ? "마킹 중" : "송전탑 마킹";
  syncParcelClickabilityForMarkingMode();
  syncMarkingCaptureLayer();
}

function toggleRoadMode(force) {
  state.roadMode = typeof force === "boolean" ? force : !state.roadMode;
  if (state.roadMode && state.towerMode) toggleTowerMode(false);
  if (state.roadMode && state.manualParcelMode) toggleManualParcelMode(false);
  const button = document.getElementById("roadModeButton");
  button.classList.toggle("active", state.roadMode);
  button.textContent = state.roadMode ? "도로 찍는 중" : "가상도로 마킹";
  syncParcelClickabilityForMarkingMode();
  syncMarkingCaptureLayer();
}

function toggleManualParcelMode(force) {
  state.manualParcelMode = typeof force === "boolean" ? force : !state.manualParcelMode;
  if (state.manualParcelMode && state.towerMode) toggleTowerMode(false);
  if (state.manualParcelMode && state.roadMode) toggleRoadMode(false);
  const button = document.getElementById("manualParcelModeButton");
  button.classList.toggle("active", state.manualParcelMode);
  button.textContent = state.manualParcelMode ? "필지 추가 중" : "필지 수동추가";
  syncParcelClickabilityForMarkingMode();
  syncMarkingCaptureLayer();
}

function addManualRoadPoint(latLng) {
  const index = state.manualRoadMarkers.length + 1;
  const marker = new kakao.maps.CustomOverlay({
    position: latLng,
    content: `<button type="button" class="road-marker" title="가상도로 후보 ${index}">${index}</button>`,
    xAnchor: 0.5,
    yAnchor: 0.5,
    map: state.map
  });
  state.manualRoadMarkers.push(marker);
  refreshManualRoadLine();
  attachManualRoadToAnalysis();
  refreshScore();
}

function clearManualRoad(silent = false) {
  state.manualRoadMarkers.forEach((marker) => marker.setMap(null));
  state.manualRoadMarkers = [];
  if (state.manualRoadLine) state.manualRoadLine.setMap(null);
  state.manualRoadLine = null;
  if (state.analysis) delete state.analysis.manual_road;
  refreshManualRoadLine();
  if (!silent) refreshScore();
}

function removeManualRoadPoint() {
  const marker = state.manualRoadMarkers.pop();
  if (!marker) {
    renderNotices(["삭제할 도로마킹 점이 없습니다."]);
    return;
  }
  marker.setMap(null);
  if (state.manualRoadMarkers.length < 2 && state.analysis) delete state.analysis.manual_road;
  refreshManualRoadLine();
  attachManualRoadToAnalysis();
  refreshScore();
}

function refreshManualRoadLine() {
  if (state.manualRoadLine) state.manualRoadLine.setMap(null);
  const points = getManualRoadPoints();
  document.getElementById("manualRoadSummary").textContent = `가상도로 후보 ${points.length}점`;
  if (!state.map || points.length < 2) return;
  state.manualRoadLine = new kakao.maps.Polyline({
    path: points.map((p) => new kakao.maps.LatLng(p.lat, p.lng)),
    strokeWeight: 5,
    strokeColor: colors.manualRoad,
    strokeOpacity: 0.95,
    strokeStyle: "shortdash",
    map: state.map
  });
}

function getManualRoadPoints() {
  return state.manualRoadMarkers.map((marker) => {
    const position = marker.getPosition();
    return { lat: position.getLat(), lng: position.getLng() };
  });
}

function attachManualRoadToAnalysis() {
  if (!state.analysis) return;
  const points = getManualRoadPoints();
  if (points.length < 2) {
    delete state.analysis.manual_road;
    return;
  }
  state.analysis.manual_road = {
    source: "카카오 스카이뷰/하이브리드 수동 판독",
    points,
    width_class: selectedRoadWidthLabel(),
    road_type: "위성사진판독도로"
  };
}

function selectedRoadWidthLabel() {
  if (document.getElementById("actualRoad10m").checked) return "10m 이상";
  if (document.getElementById("actualRoad6m").checked) return "6m 이상 10m 미만";
  if (document.getElementById("actualRoad4m").checked) return "4m 이상 6m 미만";
  return "폭원 미확인";
}

function refreshManualRoadLine() {
  if (state.manualRoadLine) state.manualRoadLine.setMap(null);
  const points = getManualRoadPoints();
  const width = selectedRoadWidthLabel();
  const summary = document.getElementById("manualRoadSummary");
  if (summary) {
    const status = points.length >= 2 ? "자동저장 · 접도 재계산됨" : "2점 이상 클릭 시 자동저장";
    summary.textContent = `수동도로 후보 ${points.length}점 / ${width} / ${status}`;
  }
  if (!state.map || points.length < 2) return;
  const style = manualRoadStyle(width);
  state.manualRoadLine = new kakao.maps.Polyline({
    path: points.map((p) => new kakao.maps.LatLng(p.lat, p.lng)),
    strokeWeight: style.weight,
    strokeColor: style.color,
    strokeOpacity: 0.95,
    strokeStyle: style.strokeStyle,
    map: state.map
  });
}

function attachManualRoadToAnalysis() {
  if (!state.analysis) return;
  const points = getManualRoadPoints();
  if (points.length < 2) {
    delete state.analysis.manual_road;
    return;
  }
  state.analysis.manual_road = {
    source: "카카오 스카이뷰/하이브리드 수동 도로마킹",
    points,
    road_polyline: points,
    width_class: selectedRoadWidthLabel(),
    road_type: "수동마킹도로",
    tolerance_m: 5
  };
}

function selectedRoadWidthLabel() {
  const manualWidth = document.getElementById("manualRoadWidth")?.value;
  if (manualWidth === "10m") return "10m 이상";
  if (manualWidth === "6m") return "6m 이상 10m 미만";
  if (manualWidth === "4m") return "4m 이상 6m 미만";
  if (document.getElementById("actualRoad10m")?.checked) return "10m 이상";
  if (document.getElementById("actualRoad6m")?.checked) return "6m 이상 10m 미만";
  if (document.getElementById("actualRoad4m")?.checked) return "4m 이상 6m 미만";
  return "폭원 미확인";
}

function manualRoadStyle(widthClass) {
  if ((widthClass || "").includes("10")) return { weight: 7, color: "#0b5fff", strokeStyle: "solid" };
  if ((widthClass || "").includes("6")) return { weight: 5, color: "#2563eb", strokeStyle: "solid" };
  if ((widthClass || "").includes("4")) return { weight: 3, color: "#2563eb", strokeStyle: "solid" };
  return { weight: 3, color: "#6b7280", strokeStyle: "shortdash" };
}

async function addManualParcel(latLng) {
  if (!state.analysis) {
    renderNotices(["주소 분석 후 주변 필지를 수동 추가할 수 있습니다."]);
    return;
  }
  try {
    const response = await fetch("/api/parcel/point", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ lat: latLng.getLat(), lng: latLng.getLng() })
    });
    const parcel = await parseJsonResponse(response, "수동 추가 필지 조회");
    if (!parcel.ok || !parcel.polygon?.length) {
      renderNotices([parcel.message || "수동 추가 필지 조회 실패, 수동확인 필요"]);
      return;
    }
    const group = state.analysis.parcel_group || {};
    group.adjacent = group.adjacent || [];
    group.display_adjacent = group.display_adjacent || [];
    group.displayed_parcels = group.displayed_parcels || [];
    group.nearby_parcels = group.nearby_parcels || [];
    group.manual_added_ids = group.manual_added_ids || [];

    const existing = findParcelById(parcel.id);
    const target = existing || parcel;
    Object.assign(target, parcel, {
      role: "manual_added",
      manual_added: true,
      selection_status: target.selection_status || "검토 후보",
      relationship_to_main: target.relationship_to_main || "수동 추가 후보"
    });
    if (String(group.main?.id) !== String(target.id)) {
      if (target.parcel_role === "development_candidate") {
        target.selection_status = "편입 후보";
        target.is_incorporation_candidate = true;
        target.road_connection_contribution = false;
        state.selectedParcelIds.add(String(target.id));
      } else if (target.parcel_role === "access_candidate") {
        target.selection_status = "도로 연결 후보";
        target.is_incorporation_candidate = false;
        target.road_connection_contribution = true;
        state.selectedParcelIds.add(String(target.id));
      } else {
        target.selection_status = "검토 후보";
        target.is_incorporation_candidate = false;
        target.road_connection_contribution = false;
        state.selectedParcelIds.delete(String(target.id));
      }
    }
    if (!group.adjacent.some((item) => String(item.id) === String(target.id)) && String(group.main?.id) !== String(target.id)) {
      group.adjacent.push(target);
    }
    if (!group.display_adjacent.some((item) => String(item.id) === String(target.id)) && String(group.main?.id) !== String(target.id)) {
      group.display_adjacent.push(target);
    }
    if (!group.displayed_parcels.some((item) => String(item.id) === String(target.id))) {
      group.displayed_parcels.push(target);
    }
    if (!group.nearby_parcels.some((item) => String(item.id) === String(target.id))) {
      group.nearby_parcels.push(target);
    }
    if (!group.manual_added_ids.map(String).includes(String(target.id))) {
      group.manual_added_ids.push(target.id);
    }
    state.analysis.parcel_group = group;
    const existingPolygon = state.adjacentParcelPolygons.get(String(target.id));
    if (existingPolygon) {
      existingPolygon.setOptions({ strokeColor: colors.manualParcel, fillColor: "#ede9fe", fillOpacity: 0.34 });
    } else {
      const polygon = createParcelPolygon(target, colors.manualParcel, "#ede9fe", 0.34);
      if (polygon) {
        state.adjacentParcelPolygons.set(String(target.id), polygon);
        kakao.maps.event.addListener(polygon, "click", (mouseEvent) => {
          preventMapClickBubble();
          if (handleMarkingModeMapClick(mouseEvent)) return;
          toggleParcelSelection(target);
        });
      }
    }
    renderParcelFocus(target);
    updateParcelStyles();
    refreshScore();
  } catch (error) {
    renderNotices([`수동 추가 필지 조회 실패: ${error.message}`]);
  }
}

function removeManualParcel() {
  if (!state.analysis?.parcel_group) {
    renderNotices(["삭제할 수동 추가 필지가 없습니다."]);
    return;
  }
  const group = state.analysis.parcel_group;
  const manualIds = [
    ...new Set([
      ...((group.manual_added_ids || []).map(String)),
      ...(group.adjacent || []).filter((item) => item.role === "manual_added" || item.manual_added).map((item) => String(item.id)),
      ...(group.display_adjacent || []).filter((item) => item.role === "manual_added" || item.manual_added).map((item) => String(item.id))
    ])
  ];
  const selectedManualIds = [...state.selectedParcelIds].map(String).filter((id) => manualIds.includes(id));
  const targetId = selectedManualIds.length ? selectedManualIds[selectedManualIds.length - 1] : manualIds[manualIds.length - 1];
  if (!targetId) {
    renderNotices(["삭제할 수동 추가 필지가 없습니다. 수동 추가 필지를 선택하거나 마지막 추가 필지를 삭제하세요."]);
    return;
  }
  group.manual_added_ids = (group.manual_added_ids || []).filter((id) => String(id) !== targetId);
  group.adjacent = (group.adjacent || []).filter((item) => String(item.id) !== targetId);
  group.display_adjacent = (group.display_adjacent || []).filter((item) => String(item.id) !== targetId);
  group.displayed_parcels = (group.displayed_parcels || []).filter((item) => String(item.id) !== targetId);
  group.nearby_parcels = (group.nearby_parcels || []).filter(
    (item) => String(item.id) !== targetId || !(item.role === "manual_added" || item.manual_added)
  );
  state.selectedParcelIds.delete(targetId);
  const polygon = state.adjacentParcelPolygons.get(targetId);
  if (polygon) polygon.setMap(null);
  state.adjacentParcelPolygons.delete(targetId);
  renderNotices([`수동 추가 필지 1개를 제거했습니다. (${targetId})`]);
  updateParcelStyles();
  refreshScore();
}

function addTower(latLng) {
  const index = state.towerMarkers.length + 1;
  const marker = new kakao.maps.CustomOverlay({
    position: latLng,
    content: `<button type="button" class="tower-marker" title="송전탑 후보 ${index}">${index}</button>`,
    xAnchor: 0.5,
    yAnchor: 0.5,
    map: state.map
  });
  state.towerMarkers.push(marker);
  refreshTowerLine();
  refreshScore();
}

function undoTower() {
  const marker = state.towerMarkers.pop();
  if (marker) marker.setMap(null);
  refreshTowerLine();
  refreshScore();
}

function clearTowers() {
  state.towerMarkers.forEach((marker) => marker.setMap(null));
  state.towerMarkers = [];
  refreshTowerLine();
  refreshScore();
}

function refreshTowerLine() {
  if (state.towerLine) state.towerLine.setMap(null);
  const points = getTowerPoints();
  document.getElementById("towerSummary").textContent = `송전탑 후보 ${points.length}개`;
  if (!state.map || points.length < 2) return;
  state.towerLine = new kakao.maps.Polyline({
    path: points.map((p) => new kakao.maps.LatLng(p.lat, p.lng)),
    strokeWeight: 3,
    strokeColor: colors.tower,
    strokeOpacity: 0.9,
    strokeStyle: "shortdash",
    map: state.map
  });
}

function getTowerPoints() {
  return state.towerMarkers.map((marker, index) => {
    const position = marker.getPosition();
    return { lat: position.getLat(), lng: position.getLng(), label: `T${index + 1}` };
  });
}

async function refreshScore() {
  if (!state.analysis) return;
  attachManualRoadToAnalysis();
  try {
    const response = await fetch("/api/score", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        analysis: state.analysis,
        manual: collectManual(),
        towers: getTowerPoints(),
        selected_parcel_ids: [...state.selectedParcelIds]
      })
    });
    const data = await parseJsonResponse(response, "점수 재계산");
    if (data.ok) {
      state.analysis.score = data.score;
      if (data.roads) state.analysis.roads = data.roads;
      state.analysis.selected_parcel_summary = data.selected_parcel_summary;
      drawAccessPathFromAnalysis();
      renderResults(state.analysis);
    }
  } catch (error) {
    renderNotices([`점수 재계산 실패: ${error.message}`]);
  }
}

function collectManual() {
  const slopeBand = document.getElementById("manualSlopeBand")?.value || "unknown";
  const roadWidthOverride = selectedRoadWidthOverride();
  return {
    power_voltage: document.getElementById("powerVoltage").value,
    actual_road_10m: roadWidthOverride === "10m",
    actual_road_6m: roadWidthOverride === "6m",
    actual_road_4m: roadWidthOverride === "4m",
    farm_or_unpaved_road: false,
    construction_access_difficult: document.getElementById("constructionAccessDifficult")?.checked || false,
    manual_slope_degree: null,
    manual_slope_band: slopeBand
  };
}

function selectedRoadWidthOverride() {
  if (document.getElementById("actualRoad10m")?.checked) return "10m";
  if (document.getElementById("actualRoad6m")?.checked) return "6m";
  if (document.getElementById("actualRoad4m")?.checked) return "4m";
  return null;
}

function resetManualControlsForNewAddress() {
  const powerVoltage = document.getElementById("powerVoltage");
  if (powerVoltage) powerVoltage.value = "unknown";

  ["actualRoad10m", "actualRoad6m", "actualRoad4m", "constructionAccessDifficult"].forEach((id) => {
    const input = document.getElementById(id);
    if (input) input.checked = false;
  });

  const manualRoadWidth = document.getElementById("manualRoadWidth");
  if (manualRoadWidth) manualRoadWidth.value = "unknown";

  const manualSlopeBand = document.getElementById("manualSlopeBand");
  if (manualSlopeBand) manualSlopeBand.value = "unknown";
}

function resetInteractiveState() {
  state.towerMarkers.forEach((marker) => marker.setMap(null));
  state.towerMarkers = [];
  if (state.towerLine) state.towerLine.setMap(null);
  state.towerLine = null;
  state.manualRoadMarkers.forEach((marker) => marker.setMap(null));
  state.manualRoadMarkers = [];
  if (state.manualRoadLine) state.manualRoadLine.setMap(null);
  state.manualRoadLine = null;
  state.selectedParcelIds.clear();
  state.mainParcelId = null;
  state.showAllNearbyParcels = false;
  if (state.towerMode) toggleTowerMode(false);
  if (state.roadMode) toggleRoadMode(false);
  if (state.manualParcelMode) toggleManualParcelMode(false);
  document.getElementById("towerSummary").textContent = "송전탑 후보 0개";
  document.getElementById("manualRoadSummary").textContent = "가상도로 후보 0점";
}

function renderResults(data) {
  document.getElementById("emptyState").hidden = true;
  document.getElementById("resultContent").hidden = false;
  const score = data.score || {};
  const areaBlocked = Boolean(score.evaluation_blocked);
  document.getElementById("totalScore").textContent = areaBlocked ? "미산정" : (score.total ?? "-");
  document.getElementById("grade").textContent = areaBlocked ? "-" : (score.grade || "-");
  updateScorePresentation(score);
  updateResultOverview(data, score);
  renderOverlayRegulations(data);
  renderFacts(data);
  renderSelectedParcelZoningBlock(data);
  renderNearbyParcelTable(data);
  renderScenarioTable(data);
  renderPolicyReferenceBlock(data);
  renderScoreTable(score.categories || [], score.adjustments || []);
  renderList("strengthList", score.strengths || []);
  renderList("weaknessList", score.weaknesses || []);
  renderList("nextCheckList", [...(score.next_checks || []), ...(data.manual_check_items || [])]);
  renderDebug(data);
}

function renderOverlayRegulations(data) {
  const block = document.getElementById("overlayRegulationBlock");
  const list = document.getElementById("overlayRegulationList");
  if (!block || !list) return;

  const regulations = data.overlay_regulations || {};
  const score = data.score || {};
  const metrics = score.metrics || {};
  const items = regulations.items || [];
  const visibleItems = items.filter((item) => {
    const status = String(item.status || "");
    return item.detected || item.suspected || status.includes("의심") || Number(item.overlay_penalty || 0) > 0;
  });
  list.innerHTML = "";
  if (!visibleItems.length) {
    block.hidden = true;
    return;
  }
  block.hidden = false;
  appendFactRow(list, "기본 입지점수", hasDisplayValue(score.base_score) ? `${fmt(score.base_score)}점` : "-");
  appendFactRow(list, "중첩규제구역 감점", metrics.overlay_regulation_penalty_total ? `-${fmt(metrics.overlay_regulation_penalty_total)}점` : "0점");
  appendFactRow(list, "최종점수", hasDisplayValue(score.final_score ?? score.total) ? `${fmt(score.final_score ?? score.total)}점` : "-");
  appendFactRow(list, "최종판정", score.decision_label || metrics.overlay_regulation_hold_decision || "-");

  visibleItems.forEach((item) => {
    const status = item.status || "미확인";
    const ratio = hasDisplayValue(item.overlap_ratio) ? ` · 중첩 ${fmt(item.overlap_ratio)}%` : "";
    const penalty = hasDisplayValue(item.overlay_penalty) && Number(item.overlay_penalty) > 0 ? ` · -${fmt(item.overlay_penalty)}점` : "";
    const decision = item.overlay_decision ? ` · ${item.overlay_decision}` : "";
    const source = item.source ? ` · ${item.source}` : "";
    appendFactRow(list, item.label || item.key || "규제구역", `${status}${ratio}${penalty}${decision}${source}`);
  });
}

function appendFactRow(list, term, description) {
  const dt = document.createElement("dt");
  const dd = document.createElement("dd");
  dt.textContent = term;
  dd.textContent = factText(description);
  list.append(dt, dd);
}

function firstNumeric(...values) {
  for (const value of values) {
    if (value === null || value === undefined || value === "") continue;
    const number = Number(value);
    if (Number.isFinite(number)) return number;
  }
  return null;
}

function pyeongFromM2(value) {
  const number = firstNumeric(value);
  return number === null ? null : number / 3.305785;
}

function areaPairText(areaM2, areaPyeong, fallback = "-") {
  const m2 = firstNumeric(areaM2);
  const pyeong = firstNumeric(areaPyeong, pyeongFromM2(m2));
  if (m2 === null && pyeong === null) return fallback;
  return `${fmt(m2 || 0)}㎡ / ${fmt(pyeong || 0)}평`;
}

function formatZoningScoreItems(items = []) {
  const added = (items || []).filter((item) => item.scope && item.scope !== "기준 필지");
  if (!added.length) return "추가필지 없음";
  return added
    .map((item) => {
      const penalty = Number(item.penalty || 0);
      const penaltyText = penalty ? ` / 감점 -${penalty}` : "";
      return `${item.scope}: ${item.zoning || "미확인"} ${item.score ?? 0}/20${penaltyText}`;
    })
    .join(" · ");
}

function buildAreaSummary(data) {
  const group = data.parcel_group || {};
  const main = group.main || data.parcel || {};
  const summary = data.selected_parcel_summary || group.summary || {};
  const mainAreaM2 = firstNumeric(main.area_m2, summary.main_area_m2);
  const mainAreaPyeong = firstNumeric(main.area_pyeong, summary.main_area_pyeong, pyeongFromM2(mainAreaM2));
  const additionalAreaM2 = firstNumeric(summary.incorporation_area_m2, 0);
  const additionalAreaPyeong = firstNumeric(summary.incorporation_area_pyeong, pyeongFromM2(additionalAreaM2), 0);
  const totalAreaM2 = mainAreaM2 === null
    ? firstNumeric(summary.total_area_m2)
    : mainAreaM2 + (additionalAreaM2 || 0);
  const totalAreaPyeong = mainAreaPyeong === null
    ? firstNumeric(summary.total_area_pyeong, pyeongFromM2(totalAreaM2))
    : mainAreaPyeong + (additionalAreaPyeong || 0);
  return {
    mainAreaM2,
    mainAreaPyeong,
    additionalAreaM2,
    additionalAreaPyeong,
    totalAreaM2,
    totalAreaPyeong
  };
}

function updateResultOverview(data, score) {
  const areaSummary = buildAreaSummary(data);
  const resultStatus = document.getElementById("resultStatus");
  const resultDecision = document.getElementById("resultDecision");
  const resultMainArea = document.getElementById("resultMainArea");
  const resultAdditionalArea = document.getElementById("resultAdditionalArea");
  const resultTotalArea = document.getElementById("resultTotalArea");
  const resultNarrative = document.getElementById("resultNarrative");
  const grade = score.grade || "-";
  const label = score.grade_label || "추가 검토";
  const decision = score.decision_label || gradeDecisionLabel(grade);
  const areaBlocked = Boolean(score.evaluation_blocked);
  const blockMessages = score.blocking_messages || score.area_requirement?.business_area_block_messages || [];
  if (resultStatus) {
    resultStatus.textContent = areaBlocked ? "면적 미달" : (grade === "-" ? "분석 전" : "분석 완료");
    resultStatus.dataset.grade = areaBlocked ? "blocked" : (String(grade).toLowerCase().replace(/[^a-z0-9-]/g, "") || "none");
  }
  if (resultDecision) resultDecision.textContent = areaBlocked ? "검토 불가" : decision;
  if (resultMainArea) resultMainArea.textContent = areaPairText(areaSummary.mainAreaM2, areaSummary.mainAreaPyeong);
  if (resultAdditionalArea) resultAdditionalArea.textContent = areaPairText(areaSummary.additionalAreaM2, areaSummary.additionalAreaPyeong, "0㎡ / 0평");
  if (resultTotalArea) resultTotalArea.textContent = areaPairText(areaSummary.totalAreaM2, areaSummary.totalAreaPyeong);
  if (resultNarrative) {
    const strengths = score.strengths || [];
    const checks = [...(score.next_checks || []), ...(data.manual_check_items || [])].filter(Boolean);
    resultNarrative.textContent = areaBlocked
      ? (blockMessages.join(" ") || "선택한 필지 총합 면적이 10,000평 미만이므로 종합점수를 산정하지 않았습니다.")
      : strengths[0] || checks[0] || label || "전력·도로·민가·정책입지 조건을 기준으로 내부 스카우트 점수를 산출했습니다.";
  }
}

function gradeDecisionLabel(grade) {
  return {
    A: "우선검토",
    B: "검토가능",
    C: "추가확인",
    D: "낮은 우선순위"
  }[String(grade || "").toUpperCase()] || "미확인";
}

function updateScorePresentation(score) {
  const gradeValue = String(score.grade || "").toLowerCase().replace(/[^a-z0-9-]/g, "");
  const resultContent = document.getElementById("resultContent");
  const scoreBand = document.querySelector(".score-band");
  const totalScore = document.getElementById("totalScore");
  const grade = document.getElementById("grade");
  if (resultContent) resultContent.dataset.grade = gradeValue || "none";
  if (scoreBand) scoreBand.classList.add("score-band-ready");
  if (totalScore) totalScore.className = "total-score-value";
  if (grade) {
    grade.className = "grade-badge";
    if (gradeValue) grade.classList.add(`grade-${gradeValue}`);
  }
}

function renderFacts(data) {
  const group = data.parcel_group || {};
  const main = group.main || data.parcel || {};
  const summary = data.selected_parcel_summary || group.summary || {};
  const areaSummary = buildAreaSummary(data);
  const zoning = data.zoning || {};
  const growth = data.growth_management || {};
  const permit = data.datacenter_permit || {};
  const roads = data.roads || {};
  const buildings = data.buildings || {};
  const policy = data.policy || {};
  const overlayRegulations = data.overlay_regulations || {};
  const scoreMetrics = data.score?.metrics || {};
  const transmission = scoreMetrics.transmission || {};
  const accessPath = scoreMetrics.effective_access_path || roads.access_path || {};
  const slope = data.slope || scoreMetrics.slope || {};
  const densityScore = findCategory(data.score, "residential_density")?.score;
  const roadScore = findCategory(data.score, "road_access")?.score;
  const powerAxisScore = findCategory(data.score, "power_axis")?.score;
  const powerDistanceScore = transmission.distance_score;
  const powerVoltageScore = transmission.voltage_score;
  const policyScore = findCategory(data.score, "policy_location")?.score;
  const permitScore = findCategory(data.score, "permitting")?.score;
  const slopeScore = findCategory(data.score, "slope")?.score;
  const powerSelfScore = findCategory(data.score, "power_self")?.score;
  const voltageLabel = { "345kv": "345kV", "154kv": "154kV", unknown: "미확인" }[transmission.voltage || document.getElementById("powerVoltage").value] || "미확인";
  const facts = [
    ["주소", document.getElementById("privacyToggle").checked ? data.masked_address : data.address],
    ["기준점 좌표", data.parcel_group?.anchor_point ? `${fmt(data.parcel_group.anchor_point.lat, 6)}, ${fmt(data.parcel_group.anchor_point.lng, 6)}` : "-"],
    ["주소점 비개발 필지 여부", group.anchor_hit_non_development ? "예, 메인 후보 직접 확인 필요" : "아니오"],
    ["기준 주소 면적", areaPairText(areaSummary.mainAreaM2, areaSummary.mainAreaPyeong, "수동입력 필요")],
    ["추가 취합 면적", areaPairText(areaSummary.additionalAreaM2, areaSummary.additionalAreaPyeong, "0㎡ / 0평")],
    ["최종 합산 면적", areaPairText(areaSummary.totalAreaM2, areaSummary.totalAreaPyeong)],
    ["최소 사업구역 기준", "10,000평 이상"],
    ["종합점수 산정 여부", data.score?.evaluation_blocked ? "미산정 / 10,000평 미만" : "산정 가능"],
    ["필지 수", summary.parcel_count ?? "-"],
    ["도로 접함 필지 수", summary.road_contact_parcel_count ?? "-"],
    ["건물 포함 필지 수", summary.building_parcel_count ?? "-"],
    ["수동 추가 후보", `${scoreMetrics.manual_added_parcel_count ?? 0}개`],
    ["지목", (summary.land_categories || []).join(", ") || main.land_category || "수동확인"],
    ["용도지역", zoning.main_zoning || (zoning.names || []).join(", ") || "수동확인 필요"],
    ["용도지역 자동 분류", scoreMetrics.zoning_group || permit.zoning_group || permit.permit_group || "주의구간 / 수동확인 필요"],
    ["성장관리계획구역", `${growth.status || "수동확인 필요"} / 신뢰도 ${growth.confidence || "낮음"}`],
    ["데이터센터 인허가 가능성", permit.grade || "수동확인 필요"],
    ["보전관리/생산관리 동일 점수", "동일 점수대로 처리"],
    ["건폐율", permit.building_coverage_ratio || "수동확인 필요"],
    ["용적률", permit.floor_area_ratio || "수동확인 필요"],
    ["행위제한 요약", permit.land_use_restriction_summary || "토지이음 수동확인 필요"],
    ["방송통신시설 가능성", permit.telecom_facility_possible || "수동확인 필요"],
    ["토지이음 확인 링크", permit.land_use_link || "https://www.eum.go.kr/"],
    ["인허가 신뢰도", permit.permit_confidence || "낮음"],
    ["인허가 설명력 점수", permitScore !== undefined ? `${permitScore} / 20` : "-"],
    ["추가필지 용도지역 평가", formatZoningScoreItems(scoreMetrics.zoning_score_items)],
    ["통합 용도지역 점수", scoreMetrics.integrated_zoning_score !== undefined && scoreMetrics.integrated_zoning_score !== null ? `${scoreMetrics.integrated_zoning_score} / 20` : (permitScore !== undefined ? `${permitScore} / 20` : "-")],
    ["농림지역 면적비율", hasDisplayValue(scoreMetrics.agricultural_area_ratio) ? `${fmt(scoreMetrics.agricultural_area_ratio)}%` : "미해당/비율 미산정"],
    ["농림지역 혼입 판정", scoreMetrics.agricultural_mixed_judgement || scoreMetrics.agricultural_dominant_judgement || "미해당"],
    ["농림지역 혼입 리스크 감점", scoreMetrics.agricultural_mixed_penalty ? `-${fmt(scoreMetrics.agricultural_mixed_penalty)}점` : "미적용"],
    ["개발제한구역 중첩", scoreMetrics.greenbelt_status || overlayRegulations.greenbelt_status || "미확인"],
    ["개발제한구역 중첩비율", hasDisplayValue(scoreMetrics.greenbelt_overlap_ratio ?? overlayRegulations.greenbelt_overlap_ratio) ? `${fmt(scoreMetrics.greenbelt_overlap_ratio ?? overlayRegulations.greenbelt_overlap_ratio)}%` : "비율 미산정"],
    ["중첩 규제구역 감지", (scoreMetrics.overlay_regulation_detected_labels || overlayRegulations.detected_labels || []).join(", ") || "미해당/미확인"],
    ["중첩 규제구역 미확인", (scoreMetrics.overlay_regulation_unknown_labels || overlayRegulations.unknown_labels || []).join(", ") || "없음"],
    ["중첩 규제구역 감점", scoreMetrics.overlay_regulation_penalty_total ? `-${fmt(scoreMetrics.overlay_regulation_penalty_total)}점` : "미적용"],
    ["중첩 규제구역 판정", scoreMetrics.overlay_regulation_hold_decision || "미적용"],
    ["개발제한구역 감점", scoreMetrics.greenbelt_penalty ? `-${scoreMetrics.greenbelt_penalty}` : "미적용"],
    ["농림지역 감점", scoreMetrics.agricultural_mixed_risk ? "혼입 리스크로 별도 반영" : (scoreMetrics.agricultural_penalty ? `-${scoreMetrics.agricultural_penalty}` : "미적용")],
    ["임야 여부", scoreMetrics.is_forest ? "예, 다드림/산지정보 확인 필요" : "아니오/수동확인"],
    ["자동판정 도로유형", roads.nearest_road_type || "접도불명확"],
    ["자동판정 도로폭", roads.width_class || "폭원 미확인"],
    ["수동보정 도로폭", scoreMetrics.manual_override_width_class || roads.manual_override_width_class || "없음"],
    ["공사차량 진입 곤란 수동체크", scoreMetrics.construction_access_difficult_manual ? "적용됨: 도로점수 0점, 맹지성 도로없음 감점 미적용" : "미적용"],
    ["최종 적용 도로폭", scoreMetrics.final_width_class || roads.final_width_class || roads.width_class || "폭원 미확인"],
    ["도로 접근등급", roads.road_access_level || "F"],
    ["직접/경유 접도", `${accessPath.method || "접도 불명확"} / 등급 ${accessPath.grade || "F"}`],
    ["추가필지 연접 도로 반영", scoreMetrics.selected_road_contact_applied ? `반영됨 / ${scoreMetrics.selected_road_width_class || "-"} / ${fmt(scoreMetrics.selected_road_distance_m)} m` : "미반영/해당 없음"],
    ["1필지 경유 가능성", accessPath.grade === "C" ? "가능" : "해당 없음/추가확인"],
    ["2필지 경유 가능성", accessPath.grade === "D" ? "가능" : "해당 없음/추가확인"],
    ["3필지 경유 가능성", accessPath.grade === "E" ? "가능 또는 취약" : "해당 없음/추가확인"],
    ["편입 후보로 도로 접도 개선", accessPath.selected_access_improvement ? "반영됨" : "미반영/해당 없음"],
    ["접도 보완 가능성 등급", accessPath.grade || "F"],
    ["경유 필지 보상·철거 리스크", accessPath.building_risk ? "건물 포함 가능성 있음" : "없음/수동확인"],
    ["경유 필지 전용·산지검토", accessPath.farmland_or_forest_check ? "농지 또는 임야 검토 필요" : "없음/수동확인"],
    ["도로 신뢰도", roads.road_confidence || "낮음"],
    ["가상도로 수동판독", scoreMetrics.manual_visual_road?.ok ? `${scoreMetrics.manual_visual_road.distance_m ?? "-"} m / ${scoreMetrics.manual_visual_road.width_class || "폭원 미확인"}` : "미사용"],
    ["수동마킹 도로", scoreMetrics.manual_road_exists ? "있음" : "없음"],
    ["수동마킹 도로폭", scoreMetrics.manual_road_width_class || "-"],
    ["수동도로 길이", scoreMetrics.manual_road_length_m !== undefined && scoreMetrics.manual_road_length_m !== null ? `${fmt(scoreMetrics.manual_road_length_m)} m` : "-"],
    ["수동도로 접도 필지", scoreMetrics.manual_road_touching_parcel_count !== undefined ? `${scoreMetrics.manual_road_touching_parcel_count}개` : "-"],
    ["접도된 필지 목록", (scoreMetrics.manual_road_touching_parcel_ids || []).join(", ") || "-"],
    ["수동도로 접도방식", scoreMetrics.road_connection_type || scoreMetrics.manual_visual_road?.road_connection_type || "-"],
    ["도로폭 기본점수", scoreMetrics.road_width_base_score !== undefined && scoreMetrics.road_width_base_score !== null ? `${scoreMetrics.road_width_base_score} / 20` : "-"],
    ["접도방식 감점", scoreMetrics.road_connection_penalty !== undefined && scoreMetrics.road_connection_penalty !== null ? `-${scoreMetrics.road_connection_penalty}` : "-"],
    ["수동도로 점수 적용", scoreMetrics.manual_road_applied_to_score ? "수동도로 우선 적용" : "미적용/자동도로 사용"],
    ["150m 건물 수", buildings.building_count_150m ?? scoreMetrics.building_counts?.["150m"] ?? "-"],
    ["250m 건물 수", buildings.building_count_250m ?? scoreMetrics.building_counts?.["250m"] ?? "-"],
    ["350m 건물 수", buildings.building_count_350m ?? scoreMetrics.building_counts?.["350m"] ?? "-"],
    ["500m 건물 수", buildings.building_count_500m ?? "-"],
    ["150m 주거노출지수", scoreMetrics.residential_exposure_150m ?? buildings.residential_exposure_150m ?? "-"],
    ["250m 주거노출지수", scoreMetrics.residential_exposure_250m ?? buildings.residential_exposure_250m ?? "-"],
    ["350m 주거노출지수", scoreMetrics.residential_exposure_350m ?? buildings.residential_exposure_350m ?? "-"],
    ["500m 주거노출지수", scoreMetrics.residential_exposure_500m ?? buildings.residential_exposure_500m ?? "-"],
    ["주거노출지수", scoreMetrics.residential_exposure_index ?? scoreMetrics.residential_exposure_500m ?? buildings.residential_exposure_500m ?? "-"],
    ["주거추정 신뢰도", scoreMetrics.residential_confidence || buildings.residential_confidence || "낮음"],
    ["1km 정보 감점 여부", scoreMetrics.residential_reference_only_1km ? "참고값만, 자동감점 없음" : "확인 필요"],
    ["대규모 주거단지 판정", scoreMetrics.residential_large_complex_detected ? "명확히 확인" : "미확인/참고"],
    ["대규모 주거단지 근거", scoreMetrics.residential_large_complex_reason || "-"],
    ["주거단지 탐지 소스", scoreMetrics.residential_large_complex_source || "-"],
    ["주거단지 신뢰도", scoreMetrics.residential_large_complex_confidence || "-"],
    ["500m 기준 민가밀집 등급", scoreMetrics.residential_density_level_500m || buildings.residential_density_level_500m || buildings.residential_density_level || "수동확인"],
    ["1km 건물 수 참고값", buildings.building_count_1km ?? "-"],
    ["3km 건물 수 참고값", buildings.building_count_3km ?? "-"],
    ["민가밀집 기본점수", scoreText(densityScore, 10)],
    ["150m 감점 후보", scoreMetrics.residential_penalty_150m !== undefined ? `-${scoreMetrics.residential_penalty_150m}` : "-"],
    ["250m 감점 후보", scoreMetrics.residential_penalty_250m !== undefined ? `-${scoreMetrics.residential_penalty_250m}` : "-"],
    ["350m 감점 후보", scoreMetrics.residential_penalty_350m !== undefined ? `-${scoreMetrics.residential_penalty_350m}` : "-"],
    ["500m 감점 후보", scoreMetrics.residential_penalty_500m !== undefined ? `-${scoreMetrics.residential_penalty_500m}` : "-"],
    ["최종 적용 근거리 민가감점", scoreMetrics.residential_proximity_penalty_applied !== undefined ? `-${scoreMetrics.residential_proximity_penalty_applied}` : "-"],
    ["민감시설 수", scoreMetrics.sensitive_facility_count ?? "-"],
    ["민감시설 자동탐지 상태", scoreMetrics.sensitive_detection_status || "-"],
    ["중대 민감시설 수", scoreMetrics.major_sensitive_facility_count ?? "-"],
    ["주민수용성 참고시설 수", scoreMetrics.reference_facility_count ?? "-"],
    ["민감시설 종류", scoreMetrics.nearest_sensitive_facility_type || "-"],
    ["가장 가까운 민감시설", scoreMetrics.nearest_sensitive_facility_name || "-"],
    ["가장 가까운 참고시설", scoreMetrics.nearest_reference_facility_name || "-"],
    ["참고시설 거리", scoreMetrics.nearest_reference_facility_distance_m !== undefined && scoreMetrics.nearest_reference_facility_distance_m !== null ? `${fmt(scoreMetrics.nearest_reference_facility_distance_m)} m` : "-"],
    ["민감시설 기준점 거리", scoreMetrics.sensitive_distance_from_anchor_m !== undefined && scoreMetrics.sensitive_distance_from_anchor_m !== null ? `${fmt(scoreMetrics.sensitive_distance_from_anchor_m)} m` : "-"],
    ["민감시설 부지경계 거리", scoreMetrics.sensitive_distance_from_site_boundary_m !== undefined && scoreMetrics.sensitive_distance_from_site_boundary_m !== null ? `${fmt(scoreMetrics.sensitive_distance_from_site_boundary_m)} m` : "-"],
    ["민감시설 감점 적용 거리", scoreMetrics.sensitive_applied_distance_m !== undefined && scoreMetrics.sensitive_applied_distance_m !== null ? `${fmt(scoreMetrics.sensitive_applied_distance_m)} m` : "-"],
    ["민감시설 거리", scoreMetrics.nearest_sensitive_facility_distance_m !== undefined && scoreMetrics.nearest_sensitive_facility_distance_m !== null ? `${fmt(scoreMetrics.nearest_sensitive_facility_distance_m)} m` : "-"],
    ["중대 민감시설 감점", scoreMetrics.major_sensitive_facility_penalty !== undefined ? `-${scoreMetrics.major_sensitive_facility_penalty}` : "-"],
    ["참고시설 약한 감점", scoreMetrics.reference_facility_penalty !== undefined ? `-${scoreMetrics.reference_facility_penalty}` : "-"],
    ["민감시설 감점", scoreMetrics.sensitive_facility_penalty !== undefined ? `-${scoreMetrics.sensitive_facility_penalty}` : "-"],
    ["민감시설 탐지 소스", scoreMetrics.sensitive_facility_source || "-"],
    ["민감시설 신뢰도", scoreMetrics.sensitive_facility_confidence || "-"],
    ["아파트·공동주택단지 수", scoreMetrics.residential_complex_count ?? "-"],
    ["주거단지 자동탐지 상태", scoreMetrics.residential_complex_detection_status || "-"],
    ["가장 가까운 주거단지", scoreMetrics.nearest_residential_complex_name || "-"],
    ["가장 가까운 주거단지 거리", scoreMetrics.nearest_residential_complex_distance_m !== undefined && scoreMetrics.nearest_residential_complex_distance_m !== null ? `${fmt(scoreMetrics.nearest_residential_complex_distance_m)} m` : "-"],
    ["아파트·주거단지 감점", scoreMetrics.residential_complex_penalty !== undefined ? `-${scoreMetrics.residential_complex_penalty}` : "-"],
    ["주거단지 탐지 소스", scoreMetrics.residential_complex_source || "-"],
    ["주거단지 신뢰도", scoreMetrics.residential_complex_confidence || "-"],
    ["최종 민가 관련 총 감점", scoreMetrics.residential_penalty_total !== undefined ? `-${scoreMetrics.residential_penalty_total}` : "-"],
    ["민가 관련 상한 적용 여부", scoreMetrics.residential_fatal_cap !== undefined && scoreMetrics.residential_fatal_cap !== null ? `${scoreMetrics.residential_fatal_cap}점 상한` : "미적용"],
    ["감점 미적용 사유", scoreMetrics.residential_penalty_not_applied_reason || "-"],
    ["민가감점 최종점수 반영", scoreMetrics.residential_penalty_applied_to_final_score ? "반영됨" : "확인 필요"],
    ["민가밀집 판정", scoreMetrics.residential_judgement || "건물 수 기반 1차 지표로 현장확인이 필요합니다."],
    ["송전탑 후보 수", transmission.tower_count ?? 0],
    ["송전선 후보축 수", transmission.line_axis_count ?? 0],
    ["전력축 관계", transmission.power_axis_relation_label || transmission.power_axis_relation || "수동마킹 없음"],
    ["부지경계 기준 최단거리", transmission.power_axis_distance_from_site_boundary_m !== undefined && transmission.power_axis_distance_from_site_boundary_m !== null ? `${fmt(transmission.power_axis_distance_from_site_boundary_m)} m` : "-"],
    ["기준점 기준 전력축 거리", transmission.power_axis_distance_from_anchor_m !== undefined && transmission.power_axis_distance_from_anchor_m !== null ? `${fmt(transmission.power_axis_distance_from_anchor_m)} m` : "-"],
    ["전력축 점수 적용 거리", transmission.power_axis_applied_distance_m !== undefined && transmission.power_axis_applied_distance_m !== null ? `${fmt(transmission.power_axis_applied_distance_m)} m` : "-"],
    ["메인 필지만 기준 송전축 거리", transmission.power_axis_main_only_distance_m !== undefined && transmission.power_axis_main_only_distance_m !== null ? `${fmt(transmission.power_axis_main_only_distance_m)} m` : "-"],
    ["편입 후보 포함 송전축 거리", transmission.power_axis_selected_site_distance_m !== undefined && transmission.power_axis_selected_site_distance_m !== null ? `${fmt(transmission.power_axis_selected_site_distance_m)} m` : "-"],
    ["추가필지 송전축 연접 반영", transmission.power_axis_improved_by_added_parcel ? `반영됨 / 선택 ${transmission.power_axis_selected_parcel_count || 0}필지` : "미반영/해당 없음"],
    ["전력축 거리 기준", transmission.power_axis_distance_basis || "-"],
    ["송전탑 후보 거리", transmission.nearest_tower_distance_from_parcel_m !== undefined && transmission.nearest_tower_distance_from_parcel_m !== null ? `${fmt(transmission.nearest_tower_distance_from_parcel_m)} m` : "수동 마킹 필요"],
    ["송전선 후보축 거리", transmission.line_distance_from_parcel_m !== undefined && transmission.line_distance_from_parcel_m !== null ? `${fmt(transmission.line_distance_from_parcel_m)} m` : "후보 2개 이상 마킹 필요"],
    ["송전축 전압", voltageLabel],
    ["전력축 위치점수", scoreText(powerDistanceScore, 20)],
    ["전력축 전압점수", scoreText(powerVoltageScore, 10)],
    ["전력축 인접성 점수", scoreText(powerAxisScore, 30)],
    ["선하지·안전거리·한전협의 필요", transmission.power_axis_needs_safety_review ? "필요" : "일반 확인"],
    ["도로·접도·공사차량 진입 점수", scoreText(roadScore, 20)],
    ["DEM/등고선 자동조회 상태", scoreMetrics.slope_auto_status || slope.slope_auto_status || "자동조회 실패"],
    ["자동 평균경사도", scoreMetrics.slope_degree_average !== undefined && scoreMetrics.slope_degree_average !== null ? `${scoreMetrics.slope_degree_average}도` : "수동확인 필요"],
    ["자동 최대경사도", scoreMetrics.slope_degree_max !== undefined && scoreMetrics.slope_degree_max !== null ? `${scoreMetrics.slope_degree_max}도` : "수동확인 필요"],
    ["수동 입력 경사도", scoreMetrics.slope_manual_value || "미적용"],
    ["최종 적용 경사도", scoreMetrics.slope_final_degree !== undefined && scoreMetrics.slope_final_degree !== null ? `${scoreMetrics.slope_final_degree}도` : "미확인"],
    ["경사도 적용 기준", scoreMetrics.slope_apply_basis || "미확인"],
    ["경사도 점수 적용 방식", scoreMetrics.slope_score_apply_method || "미확인 / 점수 미반영"],
    ["경사도 등급", scoreMetrics.slope_grade || slope.slope_grade || "수동확인"],
    ["경사도 자료", scoreMetrics.slope_source || slope.slope_source || "DEM/등고선 자료 없음"],
    ["경사도 신뢰도", scoreMetrics.slope_confidence || slope.slope_confidence || "낮음"],
    ["경사도 기본점수", slopeScore !== undefined && slopeScore !== null ? `${slopeScore} / 5` : "미반영"],
    ["경사도 감점", scoreMetrics.slope_penalty !== undefined ? `-${scoreMetrics.slope_penalty}` : "-"],
    ["경사도 상한 적용 여부", scoreMetrics.slope_fatal_cap !== undefined && scoreMetrics.slope_fatal_cap !== null ? `${scoreMetrics.slope_fatal_cap}점 상한` : "미적용"],
    ["조건부 사유", (data.score?.conditional_flags || []).join(" / ") || "없음"],
    ["기본점수 합계", scoreText(data.score?.base_total, 100)],
    ["별도 감점 합계", data.score?.penalty_score !== undefined ? `-${data.score.penalty_score}` : "-"],
    ["최종 자동 보정", data.score?.total_adjustment !== undefined ? `${data.score.total_adjustment}` : "-"],
    ["상한 적용 전 점수", data.score?.pre_cap_total ?? "-"],
    ["최종 상한", data.score?.final_score_cap !== undefined && data.score.final_score_cap !== null ? `${data.score.final_score_cap}점` : "미적용"],
    ["상한 적용 사유", (data.score?.fatal_cap_reasons || []).join(" / ") || "없음"],
    ["감점 사유 리스트", (data.score?.penalty_items || []).map((item) => item.label).join(" / ") || "없음"],
    ["행정구역", policy.admin_region || "자동매칭 실패 / 수동확인 필요"],
    ["정책자료 매칭 상태", policy.policy_reference_match_status || (policy.ok ? "정책입지 기준자료 자동매칭 성공" : "정책입지 기준자료 없음 / 정책자료 업데이트 필요")],
    ["정책자료 표", policy.policy_source_dataset || "-"],
    ["병합표 매칭지역", policy.policy_table_region_name || "-"],
    ["병합표 매칭방식", policy.policy_table_match_method || "-"],
    ["지역낙후도 배점", policy.regional_lagging_score ?? "-"],
    ["지역낙후도 원값", policy.lagging_index ?? "-"],
    ["지역낙후도 순위", policy.lagging_rank ?? "-"],
    ["인구밀도 배점", policy.population_density_score ?? "-"],
    ["인구밀도 원값", policy.population_density ?? "-"],
    ["재정자립도 배점", policy.fiscal_independence_score ?? "-"],
    ["재정자립도 원값", policy.fiscal_independence_rate ?? "-"],
    ["정책항목 합산값", policy.regional_score_sum ?? "-"],
    ["전평 공식 가·감점", policy.official_adjustment ?? "자동매칭 실패 / 수동확인 필요"],
    ["병합표 판정", policy.policy_table_judgement || "-"],
    ["정책입지 점수", scoreText(policyScore, 10)],
    ["정책입지 판정 문구", scoreMetrics.policy_judgement || policy.site_judgement || "-"],
    ["정책입지 total_score 반영", "정책입지 점수 반영됨"],
    ["정책자료 기준연도", policy.policy_data_updated_year || policy.site_updated_year || "-"],
    ["전력자립도", policy.power_self_sufficiency_rate !== undefined && policy.power_self_sufficiency_rate !== null ? `${fmt(policy.power_self_sufficiency_rate)}%` : "자동매칭 실패 / 수동확인 필요"],
    ["전력자립도 예상점수", policy.official_power_self_score !== undefined && policy.official_power_self_score !== null ? `${policy.official_power_self_score} / 10` : "-"],
    ["전력자립도 내부점수", hasDisplayValue(powerSelfScore) ? scoreText(powerSelfScore, 5) : (hasDisplayValue(policy.power_self_internal_score) ? scoreText(policy.power_self_internal_score, 5) : "미반영")],
    ["전력자립도 총점 반영", "내부 총점 5점 항목으로 반영"],
    ["정책 데이터 출처", policy.policy_source_note || policy.site_source_note || policy.source || "정책자료 업데이트 필요"],
    ["자동조회 실패 항목", (data.auto_lookup_failures || []).join(" / ") || "없음"]
  ];

  const list = document.getElementById("siteFacts");
  list.innerHTML = "";
  const growthDetected = Boolean(growth.ok || /성장관리|포함/.test(`${growth.status || ""}`));
  const visibleFacts = facts.filter(([term]) => growthDetected || !`${term}`.includes("성장관리"));
  visibleFacts.forEach(([term, description]) => {
    const dt = document.createElement("dt");
    const dd = document.createElement("dd");
    dt.textContent = term;
    dd.textContent = factText(description);
    list.append(dt, dd);
  });
}

function renderNearbyParcelTable(data) {
  const group = data.parcel_group || {};
  const rows = state.showAllNearbyParcels ? (group.nearby_parcels || []) : (group.nearby_parcel_table || group.displayed_parcels || []);
  const tbody = document.getElementById("nearbyParcelTable");
  const summary = document.getElementById("parcelDifficultySummary");
  const button = document.getElementById("showMoreParcelsButton");
  if (!tbody) return;
  summary.textContent = group.parcel_group_judgement || "주소 필지와 붙어 이어지는 필지 구조를 확인하세요.";
  if (button) {
    button.hidden = !(group.nearby_parcels || []).length || (group.nearby_parcels || []).length <= 10;
    button.textContent = state.showAllNearbyParcels ? "연결 필지만 보기" : "추가 주변 필지 보기";
  }
  tbody.innerHTML = "";
  rows.forEach((row, index) => {
    const parcel = findParcelById(row.id) || row;
    const tr = document.createElement("tr");
    tr.innerHTML = `
      <td>${row.index || index + 1}</td>
      <td>${escapeHtml(row.id || "-")}</td>
      <td>${fmt(row.anchor_distance_m)}m</td>
      <td>${escapeHtml(row.land_category || "-")}</td>
      <td>${escapeHtml(parcelRoleLabel(row.parcel_role || parcel.parcel_role))}</td>
      <td>${fmt(row.area_m2)}m²<br>${fmt(row.area_pyeong)}평</td>
      <td>${renderParcelZoningDisplay(parcel, row)}</td>
      <td>${row.has_building || parcel.has_building ? "있음" : "없음/미확인"}</td>
      <td>${row.has_road_contact ? "접함" : "미확인"}</td>
      <td>${escapeHtml(row.relationship_to_main || parcel.relationship_to_main || "-")}</td>
      <td>${escapeHtml(selectionStatus(parcel))}</td>
      <td>
        <div class="row-actions">
          <button type="button" data-parcel-action="main" data-parcel-id="${escapeHtml(row.id || "")}">메인</button>
          <button type="button" data-parcel-action="select" data-parcel-id="${escapeHtml(row.id || "")}">편입</button>
          <button type="button" data-parcel-action="access" data-parcel-id="${escapeHtml(row.id || "")}">도로</button>
          <button type="button" data-parcel-action="review" data-parcel-id="${escapeHtml(row.id || "")}">검토</button>
          <button type="button" data-parcel-action="exclude" data-parcel-id="${escapeHtml(row.id || "")}">제외</button>
        </div>
      </td>
    `;
    tbody.appendChild(tr);
  });
  tbody.querySelectorAll("button[data-parcel-action]").forEach((button) => {
    button.addEventListener("click", () => handleParcelAction(button.dataset.parcelAction, button.dataset.parcelId));
  });
}

function renderSelectedParcelZoningBlock(data) {
  const block = document.getElementById("selectedParcelZoningBlock");
  const list = document.getElementById("selectedParcelZoningList");
  if (!block || !list) return;
  const selected = [...state.selectedParcelIds]
    .map((id) => findParcelById(id))
    .filter((parcel) => parcel && (parcel.is_incorporation_candidate || parcel.selection_status === "편입 후보"));
  block.hidden = selected.length === 0;
  list.innerHTML = "";
  if (!selected.length) return;
  selected.forEach((parcel, index) => {
    const meta = zoningScoreMeta(parcel.zoning || "");
    const penaltyText = meta.penalty ? `감점 -${meta.penalty}` : "감점 없음";
    const row = document.createElement("div");
    row.className = "selected-zoning-row";
    row.innerHTML = `
      <div>
        <strong>${escapeHtml(parcel.label || parcel.pnu || parcel.id || `추가필지 ${index + 1}`)}</strong>
        <span>${areaPairText(parcel.area_m2, parcel.area_pyeong, "면적 수동확인")}</span>
      </div>
      ${renderParcelZoningDisplay(parcel, parcel)}
      <em>${meta.score} / 20 · ${penaltyText}</em>
    `;
    list.appendChild(row);
  });
}

function renderParcelZoningDisplay(parcel, row = {}) {
  const current = String(parcel?.zoning || row.zoning || "");
  const meta = zoningScoreMeta(current);
  const penaltyText = meta.penalty ? ` / 감점 -${meta.penalty}` : "";
  const status = parcel?.zoning_lookup_status === "failed" ? "자동조회 실패" : "자동조회";
  return `
    <div class="parcel-zoning-control read-only">
      <strong>${escapeHtml(current || "미확인")}</strong>
      <span>${meta.score} / 20${penaltyText}</span>
      <small>${escapeHtml(status)}</small>
    </div>
  `;
}

function renderScenarioTable(data) {
  const group = data.parcel_group || {};
  const scoreMetrics = data.score?.metrics || {};
  const scenarios = group.site_scenarios || scoreMetrics.site_scenarios || {};
  const s0 = scenarios.scenario_0 || {};
  const sa = scenarios.scenario_a || {};
  const sb = scenarios.scenario_b || {};
  const access = scoreMetrics.effective_access_path || {};
  const tbody = document.getElementById("scenarioTable");
  if (!tbody) return;
  const rows = [
    ["총면적", fmt(s0.total_area_m2), fmt(sa.total_area_m2), fmt((data.selected_parcel_summary || {}).total_area_m2 || sb.total_area_m2)],
    ["개발 후보 필지 수", s0.development_candidate_count ?? "-", sa.development_candidate_count ?? "-", (data.selected_parcel_summary || {}).selected_development_parcel_count ?? sb.development_candidate_count ?? "-"],
    ["제약 필지 수", s0.constraint_parcel_count ?? "-", sa.constraint_parcel_count ?? "-", (data.selected_parcel_summary || {}).selected_constraint_parcel_count ?? sb.constraint_parcel_count ?? "-"],
    ["도로 접도", s0.road_contact ? "예" : "미확인", sa.road_contact ? "예" : "미확인", access.grade || (sb.road_contact ? "예" : "미확인")],
    ["도로 점수", "-", "-", findCategory(data.score, "road_access")?.score ?? "-"],
    ["부지규모·집적성", `${scoreMetrics.parcel_compactness_score_cap_by_group_difficulty ?? "-"}점 상한`, `${scoreMetrics.parcel_compactness_score_cap_by_group_difficulty ?? "-"}점 상한`, `${scoreMetrics.parcel_compactness_score_cap_by_group_difficulty ?? "-"}점 상한`],
    ["필지군 난이도", s0.parcel_group_difficulty || group.parcel_group_difficulty || "-", sa.parcel_group_difficulty || group.parcel_group_difficulty || "-", sb.parcel_group_difficulty || group.parcel_group_difficulty || "-"],
    ["최종점수", "-", "-", data.score?.final_score ?? data.score?.total ?? "-"]
  ];
  tbody.innerHTML = "";
  rows.forEach(([label, a, b, c]) => {
    const tr = document.createElement("tr");
    tr.innerHTML = `<td>${escapeHtml(label)}</td><td>${escapeHtml(a)}</td><td>${escapeHtml(b)}</td><td>${escapeHtml(c)}</td>`;
    tbody.appendChild(tr);
  });
}

function findParcelById(id) {
  if (!id || !state.analysis?.parcel_group) return null;
  const group = state.analysis.parcel_group;
  const buckets = [
    group.main ? [group.main] : [],
    group.adjacent || [],
    group.displayed_parcels || [],
    group.display_adjacent || [],
    group.nearby_parcels || []
  ];
  for (const bucket of buckets) {
    const found = bucket.find((item) => String(item.id) === String(id));
    if (found) return found;
  }
  return null;
}

function parcelRoleLabel(role) {
  return {
    development_candidate: "개발 후보",
    access_candidate: "접도·진입",
    constraint_parcel: "제약·경계",
    unknown: "수동확인"
  }[role] || "수동확인";
}

function selectionStatus(parcel) {
  if (!parcel) return "-";
  if (String(state.analysis?.parcel_group?.main?.id) === String(parcel.id) || parcel.role === "main") return "메인 필지";
  if (parcel.selection_status) return parcel.selection_status;
  if (state.selectedParcelIds.has(String(parcel.id))) return "편입 후보";
  return "검토 후보";
}

function handleParcelAction(action, id) {
  const parcel = findParcelById(id);
  if (!parcel) {
    renderNotices(["선택한 필지를 찾지 못했습니다."]);
    return;
  }
  if (action === "main") {
    setMainParcel(id);
    return;
  }
  if (action === "select") {
    if (parcel.parcel_role === "constraint_parcel" || parcel.parcel_role === "access_candidate") {
      renderNotices(["구거·도로·하천·제방 등은 개발면적에 자동 합산하지 않습니다. 도로 연결 후보 또는 검토 후보로 관리하세요."]);
      parcel.selection_status = "검토 후보";
      parcel.is_incorporation_candidate = false;
      state.selectedParcelIds.delete(String(parcel.id));
    } else if (state.selectedParcelIds.has(String(parcel.id))) {
      state.selectedParcelIds.delete(String(parcel.id));
      parcel.selection_status = "검토 후보";
      parcel.is_incorporation_candidate = false;
    } else {
      state.selectedParcelIds.add(String(parcel.id));
      parcel.selection_status = "편입 후보";
      parcel.is_incorporation_candidate = true;
    }
  }
  if (action === "access") {
    state.selectedParcelIds.add(String(parcel.id));
    parcel.road_connection_contribution = true;
    parcel.is_incorporation_candidate = false;
    parcel.selection_status = "도로 연결 후보";
  }
  if (action === "review") {
    state.selectedParcelIds.delete(String(parcel.id));
    parcel.selection_status = "검토 후보";
    parcel.is_incorporation_candidate = false;
    parcel.road_connection_contribution = false;
  }
  if (action === "exclude") {
    state.selectedParcelIds.delete(String(parcel.id));
    parcel.selection_status = "제외";
    parcel.is_incorporation_candidate = false;
    parcel.road_connection_contribution = false;
  }
  syncParcelSelectionStatus(parcel.id, parcel.selection_status, parcel.road_connection_contribution, parcel.is_incorporation_candidate);
  renderParcelFocus(parcel);
  redrawParcelLayer();
  refreshScore();
}

function setMainParcel(id) {
  if (!state.analysis?.parcel_group) return;
  const group = state.analysis.parcel_group;
  const target = findParcelById(id);
  if (!target) return;
  if (target.parcel_role !== "development_candidate") {
    renderNotices(["이 필지는 개발 후보 지목이 아니라 메인 필지 자동 지정 대상에서 제외됩니다. 그래도 메인으로 보려면 지적·권리관계를 현장에서 확인하세요."]);
  }
  const oldMain = group.main;
  if (oldMain && String(oldMain.id) !== String(target.id)) {
    oldMain.role = "adjacent";
    oldMain.selection_status = "검토 후보";
    if (!(group.adjacent || []).some((item) => String(item.id) === String(oldMain.id))) {
      group.adjacent = [oldMain, ...(group.adjacent || [])];
    }
  }
  group.adjacent = (group.adjacent || []).filter((item) => String(item.id) !== String(target.id));
  group.display_adjacent = (group.display_adjacent || []).filter((item) => String(item.id) !== String(target.id));
  target.role = "main";
  target.selection_status = "메인 필지";
  target.relationship_to_main = "메인";
  group.main = target;
  state.analysis.parcel = target;
  state.mainParcelId = target.id;
  state.selectedParcelIds.delete(String(target.id));
  ensureDisplayedAfterMainChange(oldMain, target);
  redrawParcelLayer();
  renderParcelFocus(target);
  refreshScore();
}

function ensureDisplayedAfterMainChange(oldMain, target) {
  const group = state.analysis?.parcel_group;
  if (!group) return;
  const limit = group.display_limit || 10;
  group.displayed_parcels = (group.displayed_parcels || group.nearby_parcels || []).filter((item) => String(item.id) !== String(target.id));
  if (oldMain && !group.displayed_parcels.some((item) => String(item.id) === String(oldMain.id))) {
    group.displayed_parcels.push(oldMain);
  }
  group.displayed_parcels = [target, ...group.displayed_parcels.filter((item) => String(item.id) !== String(target.id))].slice(0, limit);
  group.display_adjacent = group.displayed_parcels.filter((item) => String(item.id) !== String(target.id));
  group.nearby_parcel_table = group.displayed_parcels.slice(0, limit).map((item, index) => ({
    index: index + 1,
    id: item.id,
    anchor_distance_m: item.anchor_distance_m,
    land_category: item.land_category,
    parcel_role: item.parcel_role,
    area_m2: item.area_m2,
    area_pyeong: item.area_pyeong,
    zoning: item.zoning,
    has_building: item.has_building,
    has_road_contact: item.has_road_contact,
    relationship_to_main: item.relationship_to_main,
    selection_status: item.selection_status
  }));
}

function syncParcelSelectionStatus(id, status, roadContribution, incorporationCandidate) {
  const group = state.analysis?.parcel_group;
  if (!group) return;
  [group.adjacent || [], group.display_adjacent || [], group.displayed_parcels || [], group.nearby_parcels || []].forEach((bucket) => {
    bucket.forEach((item) => {
      if (String(item.id) !== String(id)) return;
      item.selection_status = status;
      if (roadContribution !== undefined) item.road_connection_contribution = roadContribution;
      if (incorporationCandidate !== undefined) item.is_incorporation_candidate = incorporationCandidate;
    });
  });
}

function zoningScoreMeta(value) {
  const text = String(value || "");
  const direct = ZONING_SCORE_OPTIONS.find((item) => item.value === text);
  if (direct) return { score: direct.score, penalty: direct.penalty };
  return { score: zoningScoreForLabel(text), penalty: zoningPenaltyForLabel(text) };
}

function zoningScoreForLabel(value) {
  const text = String(value || "");
  if (/개발제한|자연환경보전|상수원보호/.test(text)) return 0;
  if (/농림/.test(text)) return 4;
  if (/계획관리|자연녹지|일반공업|준공업|전용공업|중심상업|일반상업|근린상업|유통상업|준주거/.test(text)) return 20;
  if (/생산관리|보전관리|생산녹지/.test(text)) return 17;
  if (/제1종일반주거|제2종일반주거|제3종일반주거/.test(text)) return 15;
  if (/보전녹지/.test(text)) return 10;
  return 0;
}

function zoningPenaltyForLabel(value) {
  const text = String(value || "");
  if (/개발제한/.test(text)) return 25;
  if (/농림/.test(text)) return 10;
  return 0;
}

function redrawParcelLayer() {
  if (state.mainParcelPolygon) state.mainParcelPolygon.setMap(null);
  state.adjacentParcelPolygons.forEach((polygon) => polygon.setMap(null));
  state.mainParcelPolygon = null;
  state.adjacentParcelPolygons = new Map();
  drawParcels(state.analysis?.parcel_group);
  updateParcelStyles();
}

function renderPolicyReferenceBlock(data) {
  const block = document.getElementById("policyReferenceBlock");
  if (!block) return;
  if (data.score?.evaluation_blocked) {
    block.hidden = true;
    return;
  }
  const policy = data.policy || {};
  const matchStatus = policy.policy_reference_match_status || policy.message || "";
  const hasPolicySourceValues = [policy.lagging_index, policy.population_density, policy.fiscal_independence_rate]
    .every((value) => value !== null && value !== undefined && value !== "");
  const missing = !hasPolicySourceValues && (
    !policy.ok || matchStatus.includes("기준자료 없음") || matchStatus.includes("업데이트 필요")
  );
  block.hidden = !missing;
  if (!missing) return;
  document.getElementById("policySido").value = policy.sido || "";
  document.getElementById("policySigungu").value = policy.sigungu || "";
  const cached = loadPolicyReferenceCache(policy.sido, policy.sigungu);
  if (cached) {
    document.getElementById("policyLaggingIndex").value = cached.lagging_index ?? "";
    document.getElementById("policyLaggingRank").value = cached.lagging_rank ?? "";
    document.getElementById("policyPopulationDensity").value = cached.population_density ?? "";
    document.getElementById("policyFiscalIndependenceRate").value = cached.fiscal_independence_rate ?? "";
    document.getElementById("policyUpdatedYear").value = cached.updated_year ?? "";
    document.getElementById("policySourceNote").value = cached.source_note ?? "";
  }
}

async function handlePolicyReferenceSave(event) {
  event.preventDefault();
  const laggingRank = document.getElementById("policyLaggingRank").value.trim();
  const payload = {
    sido: document.getElementById("policySido").value.trim(),
    sigungu: document.getElementById("policySigungu").value.trim(),
    lagging_index: Number(document.getElementById("policyLaggingIndex").value),
    lagging_rank: laggingRank ? Number(laggingRank) : null,
    population_density: Number(document.getElementById("policyPopulationDensity").value),
    fiscal_independence_rate: Number(document.getElementById("policyFiscalIndependenceRate").value),
    updated_year: document.getElementById("policyUpdatedYear").value.trim(),
    source_note: document.getElementById("policySourceNote").value.trim()
  };
  try {
    const response = await fetch("/api/policy-reference", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload)
    });
    const result = await parseJsonResponse(response, "정책자료 저장");
    if (!result.ok) {
      renderNotices([result.message || "정책자료 저장 실패"]);
      return;
    }
    savePolicyReferenceCache(payload);
    renderNotices(["정책자료를 저장했습니다. 점수표를 다시 계산합니다."]);
    document.getElementById("searchForm").requestSubmit();
  } catch (error) {
    renderNotices([`정책자료 저장 실패: ${error.message}`]);
  }
}

function policyReferenceCacheKey(sido, sigungu) {
  return `powersite.policyReference.${String(sido || "").trim()}|${String(sigungu || "").trim()}`;
}

function loadPolicyReferenceCache(sido, sigungu) {
  try {
    const raw = localStorage.getItem(policyReferenceCacheKey(sido, sigungu));
    return raw ? JSON.parse(raw) : null;
  } catch {
    return null;
  }
}

function savePolicyReferenceCache(payload) {
  try {
    localStorage.setItem(policyReferenceCacheKey(payload.sido, payload.sigungu), JSON.stringify(payload));
  } catch {
    // Local cache is a convenience only; CSV persistence remains authoritative.
  }
}

function seedPolicyReferencePresets() {
  POLICY_REFERENCE_PRESETS.forEach((preset) => {
    try {
      const key = policyReferenceCacheKey(preset.sido, preset.sigungu);
      const existing = localStorage.getItem(key);
      if (!existing) localStorage.setItem(key, JSON.stringify(preset));
    } catch {
      // Preset seeding is optional; CSV remains authoritative for scoring.
    }
  });
}

function renderParcelFocus(parcel) {
  const selected = state.selectedParcelIds.has(String(parcel.id)) ? "예" : "아니오";
  renderNotices([
    `선택 필지 ${parcel.id}: 면적 ${fmt(parcel.area_m2)} m² / ${fmt(parcel.area_pyeong)} 평`,
    `지목 ${parcel.land_category || "수동확인"}, 역할 ${parcelRoleLabel(parcel.parcel_role)}, 기준점 거리 ${fmt(parcel.anchor_distance_m)}m`,
    `용도지역 ${parcel.zoning || "수동확인"}, 건물 ${parcel.has_building ? "있음" : "없음/수동확인"}`,
    `도로 접함 ${parcel.has_road_contact ? "예" : "아니오/불명확"}, 메인 필지와의 관계 ${parcel.relationship_to_main || "-"}, 편입 후보 ${selected}`
  ]);
}

function renderScoreTable(categories, adjustments = []) {
  const table = document.getElementById("scoreTable");
  table.innerHTML = "";
  categories.forEach((item) => {
    const row = document.createElement("div");
    row.className = `score-row score-row-${item.key || "category"}`;
    const isExcluded = item.score === null || item.score === undefined;
    const percent = isExcluded ? 0 : Math.max(0, Math.min(100, (Number(item.score) / Number(item.max)) * 100));
    if (isExcluded) {
      row.classList.add("score-muted");
    } else if (percent >= 80) {
      row.classList.add("score-good");
    } else if (percent >= 55) {
      row.classList.add("score-mid");
    } else {
      row.classList.add("score-low");
    }
    const scoreText = isExcluded ? "미반영" : `${item.score} / ${item.max}`;
    row.innerHTML = `
      <div class="score-row-head">
        <strong>${escapeHtml(item.label)}</strong>
        <span>${scoreText}</span>
      </div>
      <div class="meter"><span style="width:${percent}%"></span></div>
      <p>${escapeHtml(item.reason || "")}</p>
    `;
    table.appendChild(row);
  });
  adjustments.forEach((item) => {
    const row = document.createElement("div");
    row.className = "score-row adjustment-row penalty-card";
    const scoreText = item.signed_score !== undefined ? `${item.signed_score}` : `-${Math.abs(Number(item.score) || 0)}`;
    row.innerHTML = `
      <div class="score-row-head">
        <strong>${escapeHtml(item.label)}</strong>
        <span>${scoreText}</span>
      </div>
      <p>${escapeHtml(item.reason || "")}</p>
    `;
    table.appendChild(row);
  });
}

function renderList(id, items) {
  const list = document.getElementById(id);
  list.innerHTML = "";
  [...new Set(items || [])].filter(Boolean).forEach((item) => {
    const li = document.createElement("li");
    li.textContent = item;
    list.appendChild(li);
  });
}

function renderDebug(data) {
  const block = document.getElementById("debugBlock");
  const raw = document.getElementById("debugRaw");
  if (!block || !raw) return;
  const debug = {};
  ["parcel", "zoning", "roads", "buildings"].forEach((key) => {
    if (data[key]?.raw_response) debug[key] = data[key].raw_response;
  });
  if (!Object.keys(debug).length) {
    block.hidden = true;
    raw.textContent = "";
    return;
  }
  block.hidden = false;
  raw.textContent = JSON.stringify(debug, null, 2);
}

function renderNotices(items) {
  const panel = document.getElementById("noticePanel");
  const filtered = [...new Set((items || []).filter(Boolean))];
  panel.innerHTML = "";
  if (!filtered.length) {
    panel.hidden = true;
    return;
  }
  panel.hidden = false;
  filtered.slice(0, 12).forEach((item) => {
    const p = document.createElement("p");
    p.textContent = item;
    panel.appendChild(p);
  });
}

async function downloadReport(kind) {
  if (!state.analysis) return;
  attachManualRoadToAnalysis();
  const endpoint = kind === "csv" ? "/api/report/csv" : "/api/report/markdown";
  const response = await fetch(endpoint, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      analysis: state.analysis,
      manual: collectManual(),
      towers: getTowerPoints(),
      selected_parcel_ids: [...state.selectedParcelIds],
      privacy: document.getElementById("privacyToggle").checked
    })
  });
  const blob = await response.blob();
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = kind === "csv" ? "powersite_score.csv" : "powersite_report.md";
  document.body.appendChild(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(url);
}

async function parseJsonResponse(response, label) {
  const text = await response.text();
  let data;
  try {
    data = text ? JSON.parse(text) : {};
  } catch (error) {
    const preview = text.slice(0, 180) || response.statusText || "응답 본문 없음";
    throw new Error(`${label} 실패: 서버가 JSON이 아닌 응답을 반환했습니다(${response.status}). ${preview}`);
  }
  if (!response.ok) {
    const message = data.detail || data.message || response.statusText || "서버 오류";
    throw new Error(`${label} 실패(${response.status}): ${message}`);
  }
  return data;
}

function clearMapAnalysis() {
  clearMapSearchOverlay();
  if (state.centerMarker) state.centerMarker.setMap(null);
  state.circles.forEach((item) => item.setMap(null));
  state.circleLabels.forEach((item) => item.setMap(null));
  if (state.mainParcelPolygon) state.mainParcelPolygon.setMap(null);
  state.adjacentParcelPolygons.forEach((item) => item.setMap(null));
  state.roadOverlays.forEach((item) => item.setMap(null));
  state.buildingMarkers.forEach((item) => item.setMap(null));
  state.riskMarkers.forEach((item) => item.setMap(null));
  if (state.accessPathOverlay) state.accessPathOverlay.setMap(null);
  if (state.roadContactMarker) state.roadContactMarker.setMap(null);
  if (state.manualRoadLine) state.manualRoadLine.setMap(null);
  state.manualRoadMarkers.forEach((item) => item.setMap(null));
  state.centerMarker = null;
  state.circles = [];
  state.circleLabels = [];
  state.mainParcelPolygon = null;
  state.adjacentParcelPolygons = new Map();
  state.roadOverlays = [];
  state.buildingMarkers = [];
  state.riskMarkers = [];
  state.accessPathOverlay = null;
  state.roadContactMarker = null;
  state.manualRoadLine = null;
  state.manualRoadMarkers = [];
}

function setBusy(isBusy) {
  const button = document.querySelector("#searchForm button[type='submit']");
  button.disabled = isBusy;
  button.textContent = isBusy ? "분석 중" : "분석 시작";
}

function getViaParcels() {
  return state.analysis?.score?.metrics?.effective_access_path?.via_parcels || state.analysis?.roads?.access_path?.via_parcels || [];
}

function findCategory(score, key) {
  return (score?.categories || []).find((item) => item.key === key);
}

function centroid(points) {
  if (!points?.length) return null;
  return {
    lat: points.reduce((sum, p) => sum + Number(p.lat || 0), 0) / points.length,
    lng: points.reduce((sum, p) => sum + Number(p.lng || 0), 0) / points.length
  };
}

function offsetLatLng(lat, lng, metersEast) {
  const lngDelta = metersEast / (111320 * Math.cos((lat * Math.PI) / 180));
  return { lat, lng: lng + lngDelta };
}

function fmt(value, digits = 1) {
  if (value === null || value === undefined || value === "") return "-";
  const number = Number(value);
  if (Number.isNaN(number)) return String(value);
  return number.toLocaleString("ko-KR", { maximumFractionDigits: digits });
}

function hasDisplayValue(value) {
  return value !== null && value !== undefined && value !== "";
}

function scoreText(value, max, emptyLabel = "미반영") {
  if (!hasDisplayValue(value)) return emptyLabel;
  return `${fmt(value)} / ${max}`;
}

function factText(value) {
  if (!hasDisplayValue(value)) return "-";
  const text = String(value).trim();
  if (/^-?(null|undefined)(\s*\/\s*\d+)?$/i.test(text)) return "-";
  return text;
}

function escapeHtml(value) {
  return String(value)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#039;");
}
