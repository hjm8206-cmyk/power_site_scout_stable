(function () {
  let lastParcelInitKey = null;

  function analysisKey(data) {
    const center = data?.center || {};
    const main = data?.parcel_group?.main || data?.parcel || {};
    return [data?.address || "", center.lat || "", center.lng || "", main.id || ""].join("|");
  }

  function initializeParcelSelectionState(data) {
    const group = data?.parcel_group || {};
    const main = group.main || data?.parcel || {};
    const key = analysisKey(data);
    if (key === lastParcelInitKey) return;
    lastParcelInitKey = key;

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

  const originalRenderResults = window.renderResults || renderResults;
  window.renderResults = renderResults = function patchedRenderResults(data) {
    initializeParcelSelectionState(data);
    return originalRenderResults(data);
  };

  const originalCreateParcelPolygon = window.createParcelPolygon || createParcelPolygon;
  window.createParcelPolygon = createParcelPolygon = function patchedCreateParcelPolygon(parcel, strokeColor, fillColor, fillOpacity) {
    const polygon = originalCreateParcelPolygon(parcel, strokeColor, fillColor, fillOpacity);
    if (polygon?.setOptions) polygon.setOptions({ clickable: true });
    return polygon;
  };

  window.drawParcels = drawParcels = function patchedDrawParcels(parcelGroup) {
    const main = parcelGroup?.main;
    if (main?.polygon?.length) {
      state.mainParcelPolygon = createParcelPolygon(main, colors.mainParcel, "#bbf7d0", 0.32);
      kakao.maps.event.addListener(state.mainParcelPolygon, "click", () => {
        preventMapClickBubble();
        if (state.towerMode || state.roadMode) return;
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
      kakao.maps.event.addListener(polygon, "click", () => {
        preventMapClickBubble();
        if (state.towerMode || state.roadMode) return;
        toggleParcelSelection(parcel);
      });
    });
  };

  function preventMapClickBubble() {
    if (window.kakao?.maps?.event?.preventMap) {
      kakao.maps.event.preventMap();
    }
  }

  function bindParcelClick(polygon, parcel) {
    if (!polygon || polygon.__parcelSelectionFixBound) return;
    polygon.__parcelSelectionFixBound = true;
    kakao.maps.event.addListener(polygon, "click", () => {
      if (!state.manualParcelMode) return;
      preventMapClickBubble();
      if (state.towerMode || state.roadMode) return;
      toggleParcelSelection(parcel);
    });
  }

  function manualParcelIds(group) {
    return [
      ...new Set([
        ...((group.manual_added_ids || []).map(String)),
        ...(group.adjacent || []).filter((item) => item.role === "manual_added" || item.manual_added).map((item) => String(item.id)),
        ...(group.display_adjacent || []).filter((item) => item.role === "manual_added" || item.manual_added).map((item) => String(item.id)),
        ...(group.displayed_parcels || []).filter((item) => item.role === "manual_added" || item.manual_added).map((item) => String(item.id))
      ])
    ];
  }

  function selectManualParcelByRole(parcel) {
    if (!parcel?.id || String(parcel.id) === String(state.analysis?.parcel_group?.main?.id)) return;
    if (parcel.parcel_role === "development_candidate") {
      parcel.selection_status = "편입 후보";
      parcel.is_incorporation_candidate = true;
      parcel.road_connection_contribution = false;
      state.selectedParcelIds.add(String(parcel.id));
      return;
    }
    if (parcel.parcel_role === "access_candidate") {
      parcel.selection_status = "도로 연결 후보";
      parcel.is_incorporation_candidate = false;
      parcel.road_connection_contribution = true;
      state.selectedParcelIds.add(String(parcel.id));
      return;
    }
    parcel.selection_status = "검토 후보";
    parcel.is_incorporation_candidate = false;
    parcel.road_connection_contribution = false;
    state.selectedParcelIds.delete(String(parcel.id));
  }

  const originalAddManualParcel = window.addManualParcel || addManualParcel;
  window.addManualParcel = addManualParcel = async function patchedAddManualParcel(latLng) {
    const before = new Set(manualParcelIds(state.analysis?.parcel_group || {}));
    await originalAddManualParcel(latLng);
    const group = state.analysis?.parcel_group || {};
    const after = manualParcelIds(group);
    const newId = after.find((id) => !before.has(id)) || after[after.length - 1];
    const parcel = newId ? findParcelById(newId) : null;
    if (!parcel) return;
    selectManualParcelByRole(parcel);
    syncParcelSelectionStatus(parcel.id, parcel.selection_status, parcel.road_connection_contribution, parcel.is_incorporation_candidate);
    bindParcelClick(state.adjacentParcelPolygons.get(String(parcel.id)), parcel);
    updateParcelStyles();
    refreshScore();
    renderParcelFocus(parcel);
  };
})();
