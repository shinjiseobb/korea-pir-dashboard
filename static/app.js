/**
 * 전국 시·군·구 PIR 대시보드 프론트엔드 로직 (app.js)
 * 보안 및 안정성 원칙:
 * - innerHTML 사용 전면 금지 (XSS 원천 차단)
 * - 0ms 즉시 로딩을 위한 하이브리드 데이터 로더 (API 우선 -> static/pir_data.json 자동 폴백)
 * - 클라우드 서버리스 무중단 클라이언트 계산기 (오프라인/에러 자동 복구)
 * - 권역별 / 17개 시·도별 / 전체 분류 동적 필터링
 * - 다중 파일 업로드 및 자동 재분석 반영
 */

document.addEventListener("DOMContentLoaded", () => {
  // 전역 상태
  let pirDataList = [];
  let chartInstance = null;
  let currentSortAscending = false;
  let currentLevelFilter = "all"; // 'all', '시도', '권역'

  // DOM 요소 참조
  const statNationalPir = document.getElementById("statNationalPir");
  const statHighestRegion = document.getElementById("statHighestRegion");
  const statHighestValue = document.getElementById("statHighestValue");
  const statLowestRegion = document.getElementById("statLowestRegion");
  const statLowestValue = document.getElementById("statLowestValue");
  const statRegionCount = document.getElementById("statRegionCount");

  const levelButtonGroup = document.getElementById("levelButtonGroup");
  const chartTitle = document.getElementById("chartTitle");
  const chartDesc = document.getElementById("chartDesc");
  const tableTitle = document.getElementById("tableTitle");

  const btnSortPirDesc = document.getElementById("btnSortPirDesc");
  const btnSortPirAsc = document.getElementById("btnSortPirAsc");

  const calculatorForm = document.getElementById("calculatorForm");
  const inputIncome = document.getElementById("inputIncome");
  const inputMaxPir = document.getElementById("inputMaxPir");
  const calculatorResult = document.getElementById("calculatorResult");

  const regionChipsContainer = document.getElementById("regionChips");
  const btnCompareRegions = document.getElementById("btnCompareRegions");
  const compareResult = document.getElementById("compareResult");

  const tableBody = document.getElementById("tableBody");
  const tableSearchInput = document.getElementById("tableSearchInput");

  // 1. 하이브리드 초기 데이터 로드 (/api/pir -> 실패 시 /static/pir_data.json 자동 폴백)
  async function loadInitialData() {
    let json = null;

    // 1차 시도: 백엔드 API 호출
    try {
      const res = await fetch("/api/pir");
      if (res.ok) {
        json = await res.json();
      }
    } catch (err) {
      console.warn("API 엔드포인트 접속 지연 -> 정적 데이터셋으로 즉시 전환합니다.");
    }

    // 2차 시도: 정적 JSON 폴백 (Vercel 클라우드 무장애 100% 로딩 보장)
    if (!json || !json.data || !Array.isArray(json.data)) {
      try {
        const fallbackRes = await fetch("/static/pir_data.json");
        if (fallbackRes.ok) {
          json = await fallbackRes.json();
          console.log("🟢 Vercel CDN 정적 데이터셋 로드 완료:", json.count, "개 지역");
        }
      } catch (fbErr) {
        console.error("데이터 로드 완전 실패:", fbErr);
        return;
      }
    }

    if (json && Array.isArray(json.data)) {
      pirDataList = json.data;
      updateSummaryCards(pirDataList);
      refreshViews();
      initRegionChips(pirDataList);
      runBudgetCalculator();
    }
  }

  // 2. 현재 선택된 분류(시도/권역/전체)에 맞춰 데이터 필터링
  function getFilteredByLevel() {
    if (currentLevelFilter === "all") {
      return pirDataList;
    }
    return pirDataList.filter(r => r.level === currentLevelFilter || r.region_name === "전국");
  }

  // 3. 차트 & 테이블 화면 일괄 갱신
  function refreshViews() {
    const data = getFilteredByLevel();

    if (currentLevelFilter === "시도") {
      chartTitle.textContent = "📊 17개 광역 시·도별 PIR 순위 비교";
      chartDesc.textContent = "전국 17개 광역시·도(서울, 경기, 부산 등) 간 소득 대비 집값 비교";
      tableTitle.textContent = "📋 17개 시·도별 정밀 PIR 통계표";
    } else if (currentLevelFilter === "권역") {
      chartTitle.textContent = "🧭 서울 5대 권역별 PIR 순위 비교";
      chartDesc.textContent = "서울 도심권, 동남권(강남4구), 동북권, 서남권, 서북권 간 소득 대비 집값 비교";
      tableTitle.textContent = "📋 서울 5대 권역별 정밀 PIR 통계표";
    } else {
      chartTitle.textContent = "📊 전체 지역(시·도 및 서울 권역) PIR 순위 비교";
      chartDesc.textContent = "연간 소득을 한 푼도 쓰지 않고 모았을 때 집을 사는 데 걸리는 햇수(년)";
      tableTitle.textContent = "📋 전국 행정구역별 정밀 PIR 통계표";
    }

    renderChart(data);
    renderTable(data, tableSearchInput.value.trim());
  }

  // 4. 핵심 요약 카드 업데이트 (textContent 안전 바인딩)
  function updateSummaryCards(data) {
    const national = data.find(r => r.region_name === "전국");
    const nonNational = data.filter(r => r.region_name !== "전국");

    if (national) {
      statNationalPir.textContent = `${national.pir.toFixed(2)}배`;
    }

    if (nonNational.length > 0) {
      const highest = nonNational.reduce((prev, curr) => (curr.pir > prev.pir ? curr : prev));
      const lowest = nonNational.reduce((prev, curr) => (curr.pir < prev.pir ? curr : prev));

      statHighestRegion.textContent = highest.region_name;
      statHighestValue.textContent = `PIR ${highest.pir.toFixed(2)}배 (전국의 ${highest.pir_vs_national}배)`;

      statLowestRegion.textContent = lowest.region_name;
      statLowestValue.textContent = `PIR ${lowest.pir.toFixed(2)}배 (전국의 ${lowest.pir_vs_national}배)`;
    }

    statRegionCount.textContent = `${nonNational.length}개 지역`;
  }

  // 5. Chart.js 막대 차트 렌더링
  function renderChart(data) {
    const ctx = document.getElementById("pirChart").getContext("2d");
    const sorted = [...data].filter(r => r.region_name !== "전국");

    if (currentSortAscending) {
      sorted.sort((a, b) => a.pir - b.pir);
    } else {
      sorted.sort((a, b) => b.pir - a.pir);
    }

    const labels = sorted.map(r => r.region_name);
    const pirValues = sorted.map(r => r.pir);
    const backgroundColors = sorted.map(r => {
      if (r.level === "권역") return "rgba(220, 38, 38, 0.75)";
      if (r.region_name.includes("경기") || r.region_name.includes("세종")) return "rgba(37, 99, 235, 0.75)";
      return "rgba(100, 116, 139, 0.65)";
    });

    if (chartInstance) {
      chartInstance.destroy();
    }

    chartInstance = new Chart(ctx, {
      type: "bar",
      data: {
        labels: labels,
        datasets: [{
          label: "PIR (소득 대비 주택가격 배수)",
          data: pirValues,
          backgroundColor: backgroundColors,
          borderRadius: 4,
          maxBarThickness: 32
        }]
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        plugins: {
          legend: { display: false },
          tooltip: {
            callbacks: {
              label: function(context) {
                const item = sorted[context.dataIndex];
                return [
                  ` 구분: ${item.level}`,
                  ` PIR: ${item.pir}배 (전국 ${item.pir_vs_national}배)`,
                  ` 평균 주택가격: ${item.housing_price_manwon.toLocaleString()}만 원`,
                  ` 1인당 평균연소득: ${item.annual_income_manwon.toLocaleString()}만 원`
                ];
              }
            }
          }
        },
        scales: {
          y: {
            beginAtZero: true,
            title: { display: true, text: "PIR (배수)" }
          },
          x: {
            ticks: {
              maxRotation: 45,
              minRotation: 45,
              font: { size: 11 }
            }
          }
        }
      }
    });
  }

  // 6. 데이터 테이블 렌더링 (안전한 DOM 생성)
  function renderTable(data, filterKeyword = "") {
    while (tableBody.firstChild) {
      tableBody.removeChild(tableBody.firstChild);
    }

    const filtered = data.filter(r => {
      if (!filterKeyword) return true;
      return r.region_name.toLowerCase().includes(filterKeyword.toLowerCase());
    });

    filtered.forEach((row, index) => {
      const tr = document.createElement("tr");

      // 순위 td
      const tdRank = document.createElement("td");
      const spanRank = document.createElement("span");
      spanRank.className = "rank-badge";
      if (row.region_name === "전국") {
        spanRank.textContent = "-";
        spanRank.classList.add("rank-other");
      } else {
        spanRank.textContent = String(row.rank || index + 1);
        if (row.rank === 1) spanRank.classList.add("rank-1");
        else if (row.rank === 2) spanRank.classList.add("rank-2");
        else if (row.rank === 3) spanRank.classList.add("rank-3");
        else spanRank.classList.add("rank-other");
      }
      tdRank.appendChild(spanRank);
      tr.appendChild(tdRank);

      // 지역명 td
      const tdName = document.createElement("td");
      const strongName = document.createElement("strong");
      strongName.textContent = row.region_name;
      tdName.appendChild(strongName);
      tr.appendChild(tdName);

      // 구분 td
      const tdLevel = document.createElement("td");
      const badgeLevel = document.createElement("span");
      badgeLevel.className = "badge-tag";
      if (row.level === "권역") badgeLevel.classList.add("badge-hard");
      else if (row.level === "시도") badgeLevel.classList.add("badge-easy");
      else badgeLevel.classList.add("badge-medium");
      badgeLevel.textContent = row.level;
      tdLevel.appendChild(badgeLevel);
      tr.appendChild(tdLevel);

      // 주택가격 td
      const tdPrice = document.createElement("td");
      tdPrice.className = "text-right";
      tdPrice.textContent = `${row.housing_price_manwon.toLocaleString()}만 원`;
      tr.appendChild(tdPrice);

      // 연소득 td
      const tdIncome = document.createElement("td");
      tdIncome.className = "text-right";
      tdIncome.textContent = `${row.annual_income_manwon.toLocaleString()}만 원`;
      tr.appendChild(tdIncome);

      // PIR td
      const tdPir = document.createElement("td");
      tdPir.className = "text-right font-bold";
      tdPir.textContent = `${row.pir.toFixed(2)}배`;
      if (row.pir >= 15) tdPir.style.color = "var(--danger)";
      else if (row.pir <= 6) tdPir.style.color = "var(--success)";
      tr.appendChild(tdPir);

      // 전국 대비 배수 td
      const tdVsNat = document.createElement("td");
      tdVsNat.className = "text-right";
      tdVsNat.textContent = `${row.pir_vs_national.toFixed(2)}배`;
      tr.appendChild(tdVsNat);

      tableBody.appendChild(tr);
    });
  }

  // 7. 내 연소득 맞춤 계산기 (API 호출 + 로컬 자동 계산 하이브리드)
  async function runBudgetCalculator() {
    const incomeManwon = parseFloat(inputIncome.value);
    if (!incomeManwon || incomeManwon <= 0) return;

    const incomeWon = incomeManwon * 10000;
    const maxPirVal = inputMaxPir.value ? parseFloat(inputMaxPir.value) : null;

    while (calculatorResult.firstChild) {
      calculatorResult.removeChild(calculatorResult.firstChild);
    }

    let results = [];

    // 1차 시도: API 호출
    try {
      const res = await fetch("/api/filter", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ annual_income_won: incomeWon, max_pir: maxPirVal })
      });
      if (res.ok) {
        const json = await res.json();
        if (json.success && Array.isArray(json.data)) {
          results = json.data;
        }
      }
    } catch (e) {
      // API 실패 시 로컬 자바스크립트 자동 계산 전환
    }

    // 2차 시도: 로컬 데이터 기반 즉시 계산 (서버리스 무관 100% 작동)
    if (results.length === 0 && pirDataList.length > 0) {
      results = pirDataList
        .filter(r => r.region_name !== "전국")
        .map(r => {
          const userPir = Number((r.housing_price_won / incomeWon).toFixed(2));
          return {
            ...r,
            user_custom_pir: userPir,
            affordability: userPir <= 7.0 ? "진입 용이" : (userPir <= 12.0 ? "적정 수준" : "부담 큼")
          };
        })
        .filter(r => (maxPirVal === null ? true : r.user_custom_pir <= maxPirVal))
        .sort((a, b) => a.user_custom_pir - b.user_custom_pir);
    }

    if (results.length === 0) {
      const emptyMsg = document.createElement("p");
      emptyMsg.className = "stat-desc";
      emptyMsg.textContent = "조건에 부합하는 지역이 없습니다. 소득이나 목표 PIR을 조정해 보세요.";
      calculatorResult.appendChild(emptyMsg);
      return;
    }

    results.forEach(item => {
      const divItem = document.createElement("div");
      divItem.className = "result-item";

      const leftDiv = document.createElement("div");
      const nameSpan = document.createElement("strong");
      nameSpan.textContent = `${item.region_name} (${item.level})`;
      const infoSpan = document.createElement("div");
      infoSpan.className = "stat-desc";
      infoSpan.textContent = `평균 집값: ${item.housing_price_manwon.toLocaleString()}만 원`;
      leftDiv.appendChild(nameSpan);
      leftDiv.appendChild(infoSpan);

      const rightDiv = document.createElement("div");
      rightDiv.className = "text-right";
      const pirSpan = document.createElement("div");
      pirSpan.style.fontWeight = "700";
      pirSpan.textContent = `소요: ${item.user_custom_pir}년`;

      const tagSpan = document.createElement("span");
      tagSpan.className = "badge-tag";
      if (item.affordability === "진입 용이") tagSpan.classList.add("badge-easy");
      else if (item.affordability === "적정 수준") tagSpan.classList.add("badge-medium");
      else tagSpan.classList.add("badge-hard");
      tagSpan.textContent = item.affordability;

      rightDiv.appendChild(pirSpan);
      rightDiv.appendChild(tagSpan);

      divItem.appendChild(leftDiv);
      divItem.appendChild(rightDiv);
      calculatorResult.appendChild(divItem);
    });
  }

  // 8. 지역 비교용 체크박스 칩 생성
  function initRegionChips(data) {
    while (regionChipsContainer.firstChild) {
      regionChipsContainer.removeChild(regionChipsContainer.firstChild);
    }

    const defaultSelected = ["서울특별시", "경기도", "부산광역시", "서울 동남권"];
    const nonNational = data.filter(r => r.region_name !== "전국");

    nonNational.forEach(item => {
      const label = document.createElement("label");
      label.className = "chip-label";

      const chk = document.createElement("input");
      chk.type = "checkbox";
      chk.value = item.region_name;
      if (defaultSelected.includes(item.region_name)) {
        chk.checked = true;
      }

      const text = document.createTextNode(` ${item.region_name} [${item.level}]`);
      label.appendChild(chk);
      label.appendChild(text);
      regionChipsContainer.appendChild(label);
    });

    runCompareSelectedRegions();
  }

  // 9. 지역 맞비교 실행 (API + 로컬 자바스크립트 하이브리드)
  async function runCompareSelectedRegions() {
    const checkedBoxes = regionChipsContainer.querySelectorAll("input[type='checkbox']:checked");
    const selected = Array.from(checkedBoxes).map(cb => cb.value);

    while (compareResult.firstChild) {
      compareResult.removeChild(compareResult.firstChild);
    }

    if (selected.length < 1) {
      const msg = document.createElement("p");
      msg.className = "stat-desc";
      msg.textContent = "비교할 지역을 1개 이상 선택해 주세요.";
      compareResult.appendChild(msg);
      return;
    }

    let comparison = null;

    // 1차: API 호출
    try {
      const res = await fetch("/api/compare", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ regions: selected })
      });
      if (res.ok) {
        const json = await res.json();
        if (json.success && json.data) comparison = json.data;
      }
    } catch (e) {}

    // 2차: 로컬 데이터 계산 폴백
    if (!comparison && pirDataList.length > 0) {
      const matched = pirDataList.filter(r => selected.includes(r.region_name));
      if (matched.length > 0) {
        const pirs = matched.map(r => r.pir);
        comparison = {
          count: matched.length,
          highest_pir_region: matched.reduce((a, b) => (a.pir > b.pir ? a : b)).region_name,
          lowest_pir_region: matched.reduce((a, b) => (a.pir < b.pir ? a : b)).region_name,
          avg_pir: Number((pirs.reduce((a, b) => a + b, 0) / pirs.length).toFixed(2)),
          regions: matched
        };
      }
    }

    if (comparison && comparison.regions) {
      const d = comparison;
      const summaryCard = document.createElement("div");
      summaryCard.className = "result-item";
      summaryCard.style.backgroundColor = "var(--primary-light)";
      summaryCard.style.borderColor = "#bfdbfe";

      const summaryText = document.createElement("div");
      const s1 = document.createElement("div");
      s1.textContent = `📍 비교 대상 ${d.count}개 지역 분석 결과`;
      s1.style.fontWeight = "700";
      s1.style.color = "var(--primary)";

      const s2 = document.createElement("div");
      s2.className = "stat-desc";
      s2.textContent = `최고 PIR: ${d.highest_pir_region} | 최저 PIR: ${d.lowest_pir_region} | 평균 PIR: ${d.avg_pir}배`;

      summaryText.appendChild(s1);
      summaryText.appendChild(s2);
      summaryCard.appendChild(summaryText);
      compareResult.appendChild(summaryCard);

      d.regions.forEach(reg => {
        const rItem = document.createElement("div");
        rItem.className = "result-item";

        const left = document.createElement("div");
        const rTitle = document.createElement("strong");
        rTitle.textContent = `${reg.region_name} [${reg.level}]`;
        const rSub = document.createElement("div");
        rSub.className = "stat-desc";
        rSub.textContent = `집값: ${reg.housing_price_manwon.toLocaleString()}만원 / 소득: ${reg.annual_income_manwon.toLocaleString()}만원`;
        left.appendChild(rTitle);
        left.appendChild(rSub);

        const right = document.createElement("div");
        right.className = "text-right";
        const rPir = document.createElement("strong");
        rPir.textContent = `PIR ${reg.pir.toFixed(2)}배`;
        const rVs = document.createElement("div");
        rVs.className = "stat-desc";
        rVs.textContent = `전국의 ${reg.pir_vs_national}배`;
        right.appendChild(rPir);
        right.appendChild(rVs);

        rItem.appendChild(left);
        rItem.appendChild(right);
        compareResult.appendChild(rItem);
      });
    }
  }

  // 10. 분류 선택 버튼 이벤트 바인딩 (전체 / 시도 / 권역)
  levelButtonGroup.addEventListener("click", (e) => {
    const btn = e.target.closest(".btn-filter");
    if (!btn) return;

    levelButtonGroup.querySelectorAll(".btn-filter").forEach(b => b.classList.remove("active"));
    btn.classList.add("active");

    currentLevelFilter = btn.dataset.level;
    refreshViews();
  });

  // 정렬 및 폼 이벤트 바인딩
  btnSortPirDesc.addEventListener("click", () => {
    currentSortAscending = false;
    btnSortPirDesc.classList.add("active");
    btnSortPirAsc.classList.remove("active");
    refreshViews();
  });

  btnSortPirAsc.addEventListener("click", () => {
    currentSortAscending = true;
    btnSortPirAsc.classList.add("active");
    btnSortPirDesc.classList.remove("active");
    refreshViews();
  });

  calculatorForm.addEventListener("submit", (e) => {
    e.preventDefault();
    runBudgetCalculator();
  });

  btnCompareRegions.addEventListener("click", () => {
    runCompareSelectedRegions();
  });

  tableSearchInput.addEventListener("input", (e) => {
    renderTable(getFilteredByLevel(), e.target.value.trim());
  });

  // 11. 다중 파일 업로드 및 자동 재분석 트리거
  const dropZone = document.getElementById("dropZone");
  const fileInput = document.getElementById("fileInput");
  const btnBrowseFiles = document.getElementById("btnBrowseFiles");
  const selectedFilesArea = document.getElementById("selectedFilesArea");
  const selectedFilesCount = document.getElementById("selectedFilesCount");
  const fileChipsList = document.getElementById("fileChipsList");
  const btnClearFiles = document.getElementById("btnClearFiles");
  const btnUploadFiles = document.getElementById("btnUploadFiles");
  const uploadStatusMsg = document.getElementById("uploadStatusMsg");

  let queuedFiles = [];

  function updateFileListUI() {
    while (fileChipsList.firstChild) {
      fileChipsList.removeChild(fileChipsList.firstChild);
    }

    if (queuedFiles.length === 0) {
      selectedFilesArea.style.display = "none";
      return;
    }

    selectedFilesArea.style.display = "flex";
    selectedFilesCount.textContent = String(queuedFiles.length);

    queuedFiles.forEach((file, idx) => {
      const itemCard = document.createElement("div");
      itemCard.className = "file-item-card";

      const left = document.createElement("div");
      const nameText = document.createElement("strong");
      nameText.textContent = `📄 ${file.name} `;
      const sizeText = document.createElement("span");
      sizeText.className = "stat-desc";
      sizeText.textContent = `(${roundFileSize(file.size)})`;
      left.appendChild(nameText);
      left.appendChild(sizeText);

      const btnRemove = document.createElement("button");
      btnRemove.type = "button";
      btnRemove.className = "btn-remove-file";
      btnRemove.textContent = "✕";
      btnRemove.title = "목록에서 제거";
      btnRemove.addEventListener("click", () => {
        queuedFiles.splice(idx, 1);
        updateFileListUI();
      });

      itemCard.appendChild(left);
      itemCard.appendChild(btnRemove);
      fileChipsList.appendChild(itemCard);
    });
  }

  function roundFileSize(bytes) {
    if (bytes < 1024) return `${bytes} B`;
    if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
    return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
  }

  function handleAddedFiles(fileList) {
    const validExtensions = [".csv", ".xlsx", ".xls"];
    for (let i = 0; i < fileList.length; i++) {
      const f = fileList[i];
      const ext = f.name.substring(f.name.lastIndexOf(".")).toLowerCase();
      if (validExtensions.includes(ext)) {
        if (!queuedFiles.some(existing => existing.name === f.name)) {
          queuedFiles.push(f);
        }
      } else {
        alert(`'${f.name}' 은(는) 지원하지 않는 파일입니다. (CSV 및 Excel 파일만 가능)`);
      }
    }
    updateFileListUI();
  }

  btnBrowseFiles.addEventListener("click", () => fileInput.click());
  dropZone.addEventListener("click", (e) => {
    if (e.target !== btnBrowseFiles) fileInput.click();
  });

  dropZone.addEventListener("dragover", (e) => {
    e.preventDefault();
    dropZone.classList.add("dragover");
  });

  dropZone.addEventListener("dragleave", () => {
    dropZone.classList.remove("dragover");
  });

  dropZone.addEventListener("drop", (e) => {
    e.preventDefault();
    dropZone.classList.remove("dragover");
    if (e.dataTransfer && e.dataTransfer.files) {
      handleAddedFiles(e.dataTransfer.files);
    }
  });

  fileInput.addEventListener("change", (e) => {
    if (e.target.files) {
      handleAddedFiles(e.target.files);
    }
  });

  btnClearFiles.addEventListener("click", () => {
    queuedFiles = [];
    fileInput.value = "";
    updateFileListUI();
  });

  btnUploadFiles.addEventListener("click", async () => {
    if (queuedFiles.length === 0) return;

    btnUploadFiles.disabled = true;
    btnUploadFiles.textContent = "서버 업로드 및 자동 재분석 중...";
    uploadStatusMsg.style.display = "none";

    const formData = new FormData();
    queuedFiles.forEach(file => {
      formData.append("files", file);
    });

    try {
      const res = await fetch("/api/upload", {
        method: "POST",
        body: formData
      });
      const json = await res.json();

      uploadStatusMsg.style.display = "block";
      if (json.success) {
        uploadStatusMsg.className = "upload-status-msg success";
        uploadStatusMsg.textContent = `🎉 파일 ${json.uploaded_count}개가 안전하게 업로드되었으며, 새 데이터가 대시보드에 즉시 반영되었습니다!`;
        queuedFiles = [];
        fileInput.value = "";
        updateFileListUI();

        // 🔄 데이터 갱신 후 화면 즉시 자동 새로고침!
        await loadInitialData();
      } else {
        uploadStatusMsg.className = "upload-status-msg error";
        uploadStatusMsg.textContent = `❌ 업로드 실패: ${json.errors ? json.errors.join(" | ") : "오류가 발생했습니다."}`;
      }
    } catch (err) {
      uploadStatusMsg.style.display = "block";
      uploadStatusMsg.className = "upload-status-msg error";
      uploadStatusMsg.textContent = `❌ 네트워크 오류가 발생했습니다: ${err.message}`;
    } finally {
      btnUploadFiles.disabled = false;
      btnUploadFiles.textContent = "선택한 파일 서버로 업로드 전송하기";
    }
  });

  // 최초 로드 실행
  loadInitialData();

  // 12. Gemini AI 지능형 분석 에이전트 로직 (API 키는 서버 환경변수 자동 연동)
  const geminiModelSelect = document.getElementById("geminiModelSelect");
  const geminiCustomModelInput = document.getElementById("geminiCustomModelInput");
  const aiQuestionInput = document.getElementById("aiQuestionInput");
  const btnAskAi = document.getElementById("btnAskAi");
  const aiResponseContainer = document.getElementById("aiResponseContainer");
  const aiStep1Text = document.getElementById("aiStep1Text");
  const aiStep2Data = document.getElementById("aiStep2Data");
  const aiFinalReportContent = document.getElementById("aiFinalReportContent");
  const promptChips = document.querySelectorAll(".prompt-chip");

  // 모델 직접 입력 토글
  geminiModelSelect.addEventListener("change", () => {
    if (geminiModelSelect.value === "custom") {
      geminiCustomModelInput.style.display = "block";
      geminiCustomModelInput.focus();
    } else {
      geminiCustomModelInput.style.display = "none";
    }
  });

  // 추천 질문 칩 클릭
  promptChips.forEach(chip => {
    chip.addEventListener("click", () => {
      aiQuestionInput.value = chip.dataset.question;
      aiQuestionInput.focus();
    });
  });

  // AI 분석 요청 실행
  btnAskAi.addEventListener("click", async () => {
    const question = aiQuestionInput.value.trim();
    if (!question) {
      alert("질문을 입력해 주세요!");
      aiQuestionInput.focus();
      return;
    }

    // 선택된 모델 결정
    let chosenModel = geminiModelSelect.value;
    if (chosenModel === "custom") {
      chosenModel = geminiCustomModelInput.value.trim() || "gemini-1.5-flash";
    }

    // UI 상태: 로딩 시작
    btnAskAi.disabled = true;
    btnAskAi.textContent = "🤖 3단계 분석 진행 중...";
    aiResponseContainer.style.display = "flex";

    aiStep1Text.textContent = "1단계: 제미나이가 질문의 의도를 분석 중입니다...";
    aiStep2Data.textContent = "파이썬 tools.py 정밀 연산 대기 중...";
    while (aiFinalReportContent.firstChild) {
      aiFinalReportContent.removeChild(aiFinalReportContent.firstChild);
    }
    const loadingP = document.createElement("p");
    loadingP.textContent = "제미나이가 팩트 데이터를 바탕으로 전문 종합 보고서를 작성하고 있습니다. 잠시만 기다려 주세요...";
    loadingP.style.color = "#059669";
    aiFinalReportContent.appendChild(loadingP);

    try {
      const res = await fetch("/api/ai/ask", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          question: question,
          model: chosenModel
        })
      });

      const json = await res.json();

      if (json.success) {
        // [1단계 렌더링]: 파악된 의도 및 실행 도구
        aiStep1Text.textContent = `의도 파악 완료: "${json.user_intent}" (실행 도구: ${json.tool_used}, 사용 모델: ${json.model_used})`;

        // [2단계 렌더링]: 파이썬 계산 팩트 데이터
        aiStep2Data.textContent = JSON.stringify(json.raw_data, null, 2);

        // [3단계 렌더링]: 제미나이 최종 해설 보고서 (안전한 textContent)
        while (aiFinalReportContent.firstChild) {
          aiFinalReportContent.removeChild(aiFinalReportContent.firstChild);
        }
        const reportDiv = document.createElement("div");
        reportDiv.textContent = json.final_answer;
        aiFinalReportContent.appendChild(reportDiv);
      } else {
        while (aiFinalReportContent.firstChild) {
          aiFinalReportContent.removeChild(aiFinalReportContent.firstChild);
        }
        const errorP = document.createElement("p");
        errorP.style.color = "var(--danger)";
        errorP.textContent = `❌ 분석 실패: ${json.message || "오류가 발생했습니다."}`;
        aiFinalReportContent.appendChild(errorP);
      }
    } catch (err) {
      while (aiFinalReportContent.firstChild) {
        aiFinalReportContent.removeChild(aiFinalReportContent.firstChild);
      }
      const errP = document.createElement("p");
      errP.style.color = "var(--danger)";
      errP.textContent = `❌ 네트워크 오류: ${err.message}`;
      aiFinalReportContent.appendChild(errP);
    } finally {
      btnAskAi.disabled = false;
      btnAskAi.textContent = "분석 요청하기";
    }
  });
});
