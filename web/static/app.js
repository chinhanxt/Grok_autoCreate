/**
 * Grok & x.ai Dashboard Logic
 */

let activeTaskId = null;
let pollInterval = null;
let lastKnownSuccessCount = 0;
let totalLogCount = 0;

document.addEventListener("DOMContentLoaded", () => {
  loadAccounts();
  updateLoopBadge();
  toggleRotatingProxySettings();

  // Enter to start
  document.addEventListener("keydown", (e) => {
    if (e.key === "Enter" && !activeTaskId && (e.target.tagName === "INPUT")) {
      e.preventDefault();
      startCreation();
    }
  });
});

function setSystemState(state) {
  const indicator = document.getElementById("systemStatus");
  const label = document.getElementById("statusLabel");
  if (!indicator || !label) return;

  const stateMap = {
    idle: "CHỜ LỆNH",
    running: "ĐANG CHẠY",
    success: "HOÀN THÀNH",
    stopped: "ĐÃ DỪNG",
    error: "LỖI"
  };

  indicator.className = `status-indicator ${state}`;
  label.innerText = stateMap[state] || state.toUpperCase();
}

function logMessage(text, tag = "THÔNG TIN") {
  const consoleEl = document.getElementById("consoleLogs");
  const counterEl = document.getElementById("logCounter");
  if (!consoleEl) return;

  const row = document.createElement("div");
  let tagClass = "info";

  if (tag === "HỆ THỐNG" || tag === "SYS" || text.includes("🚀") || text.includes("System") || text.includes("Starting")) {
    tagClass = "sys";
    tag = "HỆ THỐNG";
  } else if (tag === "THÀNH CÔNG" || tag === "OK" || text.includes("✔") || text.includes("🎉") || text.includes("✨")) {
    tagClass = "ok";
    tag = "THÀNH CÔNG";
  } else if (tag === "LỖI" || tag === "ERR" || text.includes("❌") || text.includes("Lỗi") || text.includes("Error") || text.includes("Thất bại")) {
    tagClass = "err";
    tag = "LỖI";
  } else if (tag === "CẢNH BÁO" || tag === "WARN" || text.includes("⚠") || text.includes("⏳") || text.includes("📬") || text.includes("🔄") || text.includes("🧅")) {
    tagClass = "warn";
    tag = "CẢNH BÁO";
  }

  // Strip all emojis from log text for clean minimalist output
  const cleanText = text.replace(/[\u{1F300}-\u{1F9FF}\u{2600}-\u{26FF}\u{2700}-\u{27BF}🚀✔🎉✨❌⚠⏳📬🔄🧅►⚡🛡🔑👤]/gu, "").replace(/^[-:\s]+/, "").trim();

  row.className = `log-row ${tagClass}`;
  const now = new Date();
  const ts = now.toTimeString().split(" ")[0];

  row.innerHTML = `<span class="log-ts">${ts}</span><span class="log-tag">${tag}</span><span class="log-msg">${escapeHtml(cleanText || text)}</span>`;
  consoleEl.appendChild(row);
  consoleEl.scrollTop = consoleEl.scrollHeight;

  totalLogCount++;
  if (counterEl) counterEl.innerText = totalLogCount;
}

function clearLogs() {
  const consoleEl = document.getElementById("consoleLogs");
  const counterEl = document.getElementById("logCounter");
  if (consoleEl) consoleEl.innerHTML = "";
  totalLogCount = 0;
  if (counterEl) counterEl.innerText = "0";
}

function showToast(message, type = "info") {
  const container = document.getElementById("toastContainer");
  if (!container) return;

  const toast = document.createElement("div");
  toast.className = `toast ${type}`;
  toast.innerText = message;
  container.appendChild(toast);

  setTimeout(() => {
    toast.remove();
  }, 3200);
}

function updateLoopBadge() {
  const countInput = document.getElementById("loopCount");
  let val = parseInt(countInput.value) || 1;
  if (val < 1) val = 1;
  if (val > 100000) val = 100000;
  
  const btnText = document.getElementById("btnCreateText");
  if (btnText) btnText.innerText = val > 1 ? `BẮT ĐẦU TẠO (${val} ACC)` : "BẮT ĐẦU TẠO";
}

function setCount(num) {
  const countInput = document.getElementById("loopCount");
  if (countInput) {
    countInput.value = num;
    updateLoopBadge();
  }
}

function updateThreadBadge() {
  const t = document.getElementById("threadCount")?.value || "1";
  const badge = document.getElementById("threadSpeedBadge");
  if (badge) {
    if (t === "1") {
      badge.innerText = "x1 Chuẩn";
      badge.style.background = "rgba(148, 163, 184, 0.15)";
      badge.style.color = "#94a3b8";
      badge.style.borderColor = "rgba(148, 163, 184, 0.3)";
    } else {
      badge.innerText = `x${t} Tốc độ`;
      badge.style.background = "rgba(34, 197, 94, 0.15)";
      badge.style.color = "#22c55e";
      badge.style.borderColor = "rgba(34, 197, 94, 0.3)";
    }
  }
}

function toggleNameInputs() {
  const isRandom = document.getElementById("randomNameCheckbox").checked;
  const customRow = document.getElementById("customNameRow");
  if (customRow) {
    customRow.style.display = isRandom ? "none" : "flex";
  }
}

function toggleTorSettings() {
  const useTor = document.getElementById("useTorCheckbox")?.checked;
  const torRow = document.getElementById("torConfigRow");
  if (torRow) torRow.style.display = useTor ? "block" : "none";

  if (useTor) {
    // Uncheck ProxyXoay to prevent conflict
    const rotCheck = document.getElementById("useRotatingProxyCheckbox");
    if (rotCheck) {
      rotCheck.checked = false;
      const rotRow = document.getElementById("rotatingProxyConfigRow");
      if (rotRow) rotRow.style.display = "none";
    }
    checkTorStatus();
  }
}

function toggleRotatingProxySettings() {
  const useRot = document.getElementById("useRotatingProxyCheckbox")?.checked;
  const rotRow = document.getElementById("rotatingProxyConfigRow");
  if (rotRow) rotRow.style.display = useRot ? "block" : "none";

  if (useRot) {
    // Uncheck Tor to prevent conflict
    const torCheck = document.getElementById("useTorCheckbox");
    if (torCheck) {
      torCheck.checked = false;
      const torRow = document.getElementById("torConfigRow");
      if (torRow) torRow.style.display = "none";
    }
    checkRotatingProxyStatus();
  }
}

let proxyCooldownInterval = null;

function startProxyCountdown(seconds, ip, isp, vitri) {
  if (proxyCooldownInterval) clearInterval(proxyCooldownInterval);
  let remaining = seconds;

  const badge = document.getElementById("rotatingProxyBadge");
  const ipText = document.getElementById("rotatingProxyIpText");
  const locText = document.getElementById("rotatingProxyLocText");

  const updateDisplay = () => {
    if (remaining > 0) {
      if (badge) {
        badge.className = "tor-indicator waiting";
        badge.innerHTML = `<span class="tor-dot"></span><span class="tor-conn-label">CHỜ ${remaining}s</span>`;
      }
      if (ipText) {
        ipText.innerText = ip ? ip : `Đang dùng proxy (${remaining}s)`;
      }
      if (locText) {
        const loc = (isp || vitri) ? `[${isp ? isp + ' - ' : ''}${vitri}] ` : "";
        locText.innerText = `${loc}(Đổi IP mới sau ${remaining}s)`;
      }
      remaining--;
    } else {
      clearInterval(proxyCooldownInterval);
      proxyCooldownInterval = null;
      if (badge) {
        badge.className = "tor-indicator";
        badge.innerHTML = `<span class="tor-dot"></span><span class="tor-conn-label">SẴN SÀNG</span>`;
      }
      if (locText) locText.innerText = (isp || vitri) ? `[${isp ? isp + ' - ' : ''}${vitri}] (Có thể đổi IP)` : "(Có thể đổi IP)";
      checkRotatingProxyStatus();
    }
  };

  updateDisplay();
  proxyCooldownInterval = setInterval(updateDisplay, 1000);
}

async function checkRotatingProxyStatus() {
  const badge = document.getElementById("rotatingProxyBadge");
  const ipText = document.getElementById("rotatingProxyIpText");
  const locText = document.getElementById("rotatingProxyLocText");
  const key = document.getElementById("rotatingProxyKey")?.value.trim() || "";
  const nhamang = document.getElementById("rotatingProxyNhamang")?.value || "random";
  const tinhthanh = document.getElementById("rotatingProxyTinhthanh")?.value || "0";

  if (!key) {
    if (ipText) ipText.innerText = "Chưa nhập Key";
    if (locText) locText.innerText = "";
    return;
  }

  if (ipText && !proxyCooldownInterval) ipText.innerText = "Đang kiểm tra...";

  try {
    const res = await fetch(`/api/rotating-proxy/status?key=${encodeURIComponent(key)}&nhamang=${nhamang}&tinhthanh=${tinhthanh}`);
    const data = await res.json();
    const isp = (data.nhamang || "").toUpperCase();
    const vitri = data.vitri || "";
    const ip = data.ip || (data.proxy_url ? data.proxy_url.replace("http://", "") : "");

    if (data.wait_seconds && data.wait_seconds > 0) {
      startProxyCountdown(data.wait_seconds, ip, isp, vitri);
      return;
    }

    if (proxyCooldownInterval) {
      clearInterval(proxyCooldownInterval);
      proxyCooldownInterval = null;
    }

    if (data.success && (data.ip || data.proxy_url)) {
      const loc = (isp || vitri) ? `[${isp ? isp + ' - ' : ''}${vitri}]` : "";
      if (badge) {
        badge.className = "tor-indicator";
        badge.innerHTML = `<span class="tor-dot"></span><span class="tor-conn-label">DÂN CƯ</span>`;
      }
      if (ipText) ipText.innerText = ip;
      if (locText) locText.innerText = loc;
    } else {
      if (badge) {
        badge.className = "tor-indicator offline";
        badge.innerHTML = `<span class="tor-dot"></span><span class="tor-conn-label">CHỜ XOAY</span>`;
      }
      if (ipText) ipText.innerText = data.message || "Chưa lấy được IP";
      if (locText) locText.innerText = "";
    }
  } catch (e) {
    if (ipText) ipText.innerText = "Lỗi kết nối API";
  }
}

async function testOrRotateProxyXoay() {
  const btn = document.getElementById("btnRotateProxyXoay");
  const ipText = document.getElementById("rotatingProxyIpText");
  const locText = document.getElementById("rotatingProxyLocText");
  const key = document.getElementById("rotatingProxyKey")?.value.trim() || "";
  const nhamang = document.getElementById("rotatingProxyNhamang")?.value || "random";
  const tinhthanh = document.getElementById("rotatingProxyTinhthanh")?.value || "0";

  if (!key) {
    showToast("Vui lòng nhập Key ProxyXoay", "error");
    return;
  }

  if (btn) btn.classList.add("rotating");
  if (ipText) ipText.innerText = "Đang xoay IP...";
  if (locText) locText.innerText = "proxyxoay.shop";
  showToast("Đang gửi yêu cầu đổi IP dân cư mới...", "info");

  try {
    const res = await fetch(`/api/rotating-proxy/rotate?key=${encodeURIComponent(key)}&nhamang=${nhamang}&tinhthanh=${tinhthanh}`, { method: "POST" });
    const data = await res.json();
    if (data.success && (data.ip || data.proxy_url)) {
      showToast(`Đã đổi sang IP Dân Cư mới: ${data.ip}`, "success");
      await checkRotatingProxyStatus();
    } else {
      const msg = data.message || "Chưa thể xoay IP (đang chờ cooldown)";
      showToast(msg, "info");
      await checkRotatingProxyStatus();
    }
  } catch (e) {
    showToast("Lỗi kết nối ProxyXoay", "error");
  } finally {
    if (btn) btn.classList.remove("rotating");
  }
}

async function checkTorStatus() {
  const badge = document.getElementById("torStatusBadge");
  const ipText = document.getElementById("torIpText");
  const locText = document.getElementById("torLocText");
  const socksPort = document.getElementById("torSocksPort")?.value || 9050;
  const controlPort = document.getElementById("torControlPort")?.value || 9051;

  if (ipText) ipText.innerText = "Đang kiểm tra...";
  if (locText) locText.innerText = "";

  try {
    const res = await fetch(`/api/tor/status?socks_port=${socksPort}&control_port=${controlPort}`);
    const data = await res.json();
    if (data.online && data.ip) {
      const country = data.details?.country || "";
      const city = data.details?.city || "";
      const loc = (city || country) ? `[${city ? city + ', ' : ''}${country}]` : "";
      if (badge) {
        badge.className = "tor-indicator";
        badge.innerHTML = `<span class="tor-dot"></span><span class="tor-conn-label">SOCKS5</span>`;
      }
      if (ipText) ipText.innerText = data.ip;
      if (locText) locText.innerText = loc;
    } else {
      if (badge) {
        badge.className = "tor-indicator offline";
        badge.innerHTML = `<span class="tor-dot"></span><span class="tor-conn-label">OFFLINE</span>`;
      }
      if (ipText) ipText.innerText = "Chưa kết nối Tor";
      if (locText) locText.innerText = "(Kiểm tra port 9050)";
    }
  } catch (e) {
    if (ipText) ipText.innerText = "Lỗi kết nối";
  }
}

async function testOrRotateTorIp() {
  const btn = document.getElementById("btnRotateIp");
  const ipText = document.getElementById("torIpText");
  const locText = document.getElementById("torLocText");
  const socksPort = document.getElementById("torSocksPort")?.value || 9050;
  const controlPort = document.getElementById("torControlPort")?.value || 9051;

  if (btn) btn.classList.add("rotating");
  if (ipText) ipText.innerText = "Đang đổi IP...";
  if (locText) locText.innerText = "SIGNAL NEWNYM";

  try {
    const res = await fetch(`/api/tor/renew-ip?socks_port=${socksPort}&control_port=${controlPort}`, { method: "POST" });
    const data = await res.json();
    if (data.success && data.ip) {
      showToast(`Đã đổi Tor Exit IP mới: ${data.ip}`, "success");
      await checkTorStatus();
    } else {
      showToast("Không thể đổi IP (Kiểm tra Control Port 9051)", "error");
      await checkTorStatus();
    }
  } catch (e) {
    showToast("Lỗi kết nối Tor Control", "error");
  } finally {
    if (btn) btn.classList.remove("rotating");
  }
}

async function startCreation() {
  const btnCreate = document.getElementById("btnCreateAccount");
  const btnStop = document.getElementById("btnStopAccount");
  const progressContainer = document.getElementById("progressContainer");

  const count = parseInt(document.getElementById("loopCount").value) || 1;
  const isRandom = document.getElementById("randomNameCheckbox").checked;
  const firstName = isRandom ? null : (document.getElementById("firstName").value.trim() || null);
  const lastName = isRandom ? null : (document.getElementById("lastName").value.trim() || null);
  const password = document.getElementById("password").value.trim() || "taikhoanAI123";

  const useTor = document.getElementById("useTorCheckbox")?.checked || false;
  const useRotating = document.getElementById("useRotatingProxyCheckbox")?.checked || false;

  let proxyMode = "direct";
  if (useRotating) proxyMode = "rotating";
  else if (useTor) proxyMode = "tor";

  const torSocksPort = parseInt(document.getElementById("torSocksPort")?.value) || 9050;
  const torControlPort = parseInt(document.getElementById("torControlPort")?.value) || 9051;
  const rotatingKey = document.getElementById("rotatingProxyKey")?.value.trim() || "";
  const rotatingNhamang = document.getElementById("rotatingProxyNhamang")?.value || "random";
  const rotatingTinhthanh = document.getElementById("rotatingProxyTinhthanh")?.value || "0";

  btnCreate.style.display = "none";
  btnStop.style.display = "inline-flex";
  btnStop.disabled = false;
  btnStop.querySelector("span").innerText = "DỪNG";

  setSystemState("running");

  if (progressContainer) {
    progressContainer.style.display = "block";
    updateProgress(0, count, 0);
  }

  lastKnownSuccessCount = 0;
  logMessage(`Bắt đầu tiến trình tạo ${count} tài khoản...`, "HỆ THỐNG");

  const payload = {
    email: null,
    first_name: firstName,
    last_name: lastName,
    password: password,
    use_tempmail: true,
    proxy: null,
    headless: true,
    count: count,
    threads: parseInt(document.getElementById("threadCount")?.value) || 1,
    random_name: isRandom,
    proxy_mode: proxyMode,
    use_tor: useTor,
    tor_socks_port: torSocksPort,
    tor_control_port: torControlPort,
    rotating_proxy_key: rotatingKey,
    rotating_proxy_nhamang: rotatingNhamang,
    rotating_proxy_tinhthanh: rotatingTinhthanh
  };

  try {
    const res = await fetch("/api/start-signup", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload)
    });
    const data = await res.json();
    if (data.task_id) {
      activeTaskId = data.task_id;
      startTaskPolling(activeTaskId);
    } else {
      throw new Error(data.detail || "Khởi tạo tác vụ thất bại");
    }
  } catch (err) {
    logMessage(err.message, "LỖI");
    showToast(err.message, "error");
    resetCreateButton();
    setSystemState("error");
  }
}

async function stopCreation() {
  if (!activeTaskId) return;
  const btnStop = document.getElementById("btnStopAccount");
  btnStop.disabled = true;
  btnStop.querySelector("span").innerText = "ĐANG DỪNG...";
  logMessage("Đang gửi yêu cầu dừng tiến trình...", "CẢNH BÁO");

  try {
    const res = await fetch(`/api/stop-task/${activeTaskId}`, { method: "POST" });
    if (res.ok) {
      showToast("Đã gửi yêu cầu dừng", "info");
    }
  } catch (e) {
    console.error("Stop error:", e);
  }
}

function updateProgress(current, total, success) {
  const statusEl = document.getElementById("progressStatus");
  const percentEl = document.getElementById("progressPercent");
  const barEl = document.getElementById("progressBar");

  const percent = total > 0 ? Math.round((current / total) * 100) : 0;
  if (statusEl) statusEl.innerText = `Đang xử lý: ${current}/${total} (Xong: ${success})`;
  if (percentEl) percentEl.innerText = `${percent}%`;
  if (barEl) barEl.style.width = `${percent}%`;
}

function startTaskPolling(taskId) {
  if (pollInterval) clearInterval(pollInterval);

  let lastLogCount = 0;
  pollInterval = setInterval(async () => {
    try {
      const res = await fetch(`/api/task-status/${taskId}`);
      if (!res.ok) return;
      const data = await res.json();

      if (data.logs && data.logs.length > lastLogCount) {
        for (let i = lastLogCount; i < data.logs.length; i++) {
          const rawLog = data.logs[i];
          if (!rawLog || rawLog.includes("━━━━")) continue;
          logMessage(rawLog);
        }
        lastLogCount = data.logs.length;
      }

      const total = data.total_count || 1;
      const current = data.current_index || 0;
      const success = data.success_count || 0;
      updateProgress(current, total, success);

      if (success > lastKnownSuccessCount) {
        lastKnownSuccessCount = success;
        loadAccounts();
      }

      if (data.status === "success") {
        clearInterval(pollInterval);
        activeTaskId = null;
        resetCreateButton();
        setSystemState("success");
        showToast(`Hoàn tất: Đã tạo ${success}/${total} tài khoản`, "success");
        loadAccounts();
      } else if (data.status === "stopped") {
        clearInterval(pollInterval);
        activeTaskId = null;
        resetCreateButton();
        setSystemState("idle");
        showToast(`Đã dừng: Tạo được ${success}/${total} tài khoản`, "info");
        loadAccounts();
      } else if (data.status === "failed") {
        clearInterval(pollInterval);
        activeTaskId = null;
        resetCreateButton();
        setSystemState("error");
        showToast(data.error || "Tác vụ thất bại", "error");
      }
    } catch (e) {
      console.error("Polling error:", e);
    }
  }, 1000);
}

function resetCreateButton() {
  const btnCreate = document.getElementById("btnCreateAccount");
  const btnStop = document.getElementById("btnStopAccount");
  if (btnCreate) {
    btnCreate.style.display = "inline-flex";
    btnCreate.disabled = false;
  }
  if (btnStop) {
    btnStop.style.display = "none";
  }
  updateLoopBadge();
}

// State for Accounts, Selection, Filter & Pagination
let allAccounts = [];
let filteredAccountsList = [];
let selectedEmails = new Set();
let currentPage = 1;
let perPage = 10;
let currentFilterType = "all";
let searchQuery = "";

async function loadAccounts() {
  try {
    const res = await fetch("/api/accounts");
    allAccounts = await res.json();
    const badge = document.getElementById("accountCountBadge");
    if (badge) {
      badge.innerText = `${allAccounts.length} TÀI KHOẢN`;
    }
    applyFiltersAndPagination();
  } catch (err) {
    console.error("Failed to load accounts:", err);
  }
}

function onFilterChange() {
  searchQuery = (document.getElementById("searchInput")?.value || "").trim().toLowerCase();
  currentFilterType = document.getElementById("tokenFilterSelect")?.value || "all";
  currentPage = 1;
  applyFiltersAndPagination();
}

function changePerPage(val) {
  perPage = parseInt(val, 10) || 10;
  currentPage = 1;
  applyFiltersAndPagination();
}

function goToPage(page) {
  const totalPages = Math.ceil(filteredAccountsList.length / perPage) || 1;
  if (page < 1 || page > totalPages) return;
  currentPage = page;
  renderCurrentPage();
}

function applyFiltersAndPagination() {
  filteredAccountsList = allAccounts.filter(acc => {
    // 1. Search Query Filter
    const matchesSearch = !searchQuery || (
      (acc.email && acc.email.toLowerCase().includes(searchQuery)) ||
      (acc.first_name && acc.first_name.toLowerCase().includes(searchQuery)) ||
      (acc.last_name && acc.last_name.toLowerCase().includes(searchQuery)) ||
      (acc.user_id && acc.user_id.toLowerCase().includes(searchQuery))
    );
    if (!matchesSearch) return false;

    // 2. Token Type Filter
    const hasOAuth = acc.access_token && acc.access_token.startsWith("eyJ0eXAiOiJhdCtqd3Qi");
    if (currentFilterType === "oauth") {
      return hasOAuth;
    } else if (currentFilterType === "sso") {
      return !hasOAuth && !!acc.sso_cookie;
    }
    return true;
  });

  renderCurrentPage();
}

function renderCurrentPage() {
  const tbody = document.getElementById("accountsTableBody");
  if (!tbody) return;

  const total = filteredAccountsList.length;
  const totalPages = Math.ceil(total / perPage) || 1;
  if (currentPage > totalPages) currentPage = totalPages;
  if (currentPage < 1) currentPage = 1;

  const startIndex = (currentPage - 1) * perPage;
  const endIndex = Math.min(startIndex + perPage, total);
  const pageItems = filteredAccountsList.slice(startIndex, endIndex);

  // Update Pagination Info
  const infoEl = document.getElementById("paginationInfo");
  if (infoEl) {
    if (total === 0) {
      infoEl.innerText = "Hiển thị 0 - 0 / 0 tài khoản";
    } else {
      infoEl.innerText = `Hiển thị ${startIndex + 1} - ${endIndex} / ${total} tài khoản`;
    }
  }

  // Render Pagination Controls (1 2 3 4...)
  renderPaginationControls(totalPages);

  // Update Select All Checkbox state for current page
  const selectAllCb = document.getElementById("selectAllCheckbox");
  if (selectAllCb) {
    if (pageItems.length > 0 && pageItems.every(acc => selectedEmails.has(acc.email))) {
      selectAllCb.checked = true;
      selectAllCb.indeterminate = false;
    } else if (pageItems.some(acc => selectedEmails.has(acc.email))) {
      selectAllCb.checked = false;
      selectAllCb.indeterminate = true;
    } else {
      selectAllCb.checked = false;
      selectAllCb.indeterminate = false;
    }
  }

  // Render Table Rows
  if (pageItems.length === 0) {
    tbody.innerHTML = `<tr><td colspan="5" class="empty-cell">${searchQuery || currentFilterType !== 'all' ? "Không tìm thấy tài khoản phù hợp" : "Chưa có tài khoản nào"}</td></tr>`;
    return;
  }

  tbody.innerHTML = "";
  pageItems.forEach((acc) => {
    const isSelected = selectedEmails.has(acc.email);
    const hasOAuth = acc.access_token && acc.access_token.startsWith("eyJ0eXAiOiJhdCtqd3Qi");
    const fullLine = `${acc.email}:${acc.password}:${acc.sso_cookie || ''}:${acc.user_id || ''}`;
    const displayName = acc.first_name ? `${acc.first_name} ${acc.last_name || ''}`.trim() : '';

    const tr = document.createElement("tr");
    tr.innerHTML = `
      <td class="cell-checkbox">
        <input type="checkbox" class="row-checkbox" value="${escapeAttr(acc.email)}" ${isSelected ? 'checked' : ''} onchange="toggleSelectRow('${escapeAttr(acc.email)}', this)">
      </td>
      <td class="cell-email">
        <div>${escapeHtml(acc.email || '')}</div>
        ${displayName ? `<span class="cell-name">${escapeHtml(displayName)}</span>` : ''}
      </td>
      <td class="cell-pass">${escapeHtml(acc.password || '')}</td>
      <td class="cell-token">
        ${hasOAuth 
          ? `<span class="token-badge oauth" title="OAuth 2.0 CLI Access Token (at+jwt)">OAUTH 200 OK</span>` 
          : `<span class="token-badge sso" title="SSO Session Cookie">SSO COOKIE</span>`}
      </td>
      <td class="cell-actions">
        <button class="table-btn" onclick="copyToClipboard('${escapeAttr(fullLine)}', 'Đã chép thông tin tài khoản')">CHÉP</button>
        <button class="table-btn" onclick="copyToClipboard('${escapeAttr(hasOAuth ? acc.access_token : (acc.sso_cookie || ''))}', 'Đã chép ${hasOAuth ? 'OAuth Token' : 'SSO Cookie'}')">${hasOAuth ? 'OAUTH' : 'COOKIE'}</button>
        <button class="table-btn btn-del" onclick="deleteSingleAccount('${escapeAttr(acc.email)}')">XÓA</button>
      </td>
    `;
    tbody.appendChild(tr);
  });

  updateSelectionUI();
}

function renderPaginationControls(totalPages) {
  const container = document.getElementById("paginationControls");
  if (!container) return;
  container.innerHTML = "";

  if (totalPages <= 1) return;

  // Previous button
  const prevBtn = document.createElement("button");
  prevBtn.className = `page-btn ${currentPage === 1 ? 'disabled' : ''}`;
  prevBtn.innerHTML = "&laquo;";
  prevBtn.title = "Trang trước";
  prevBtn.onclick = () => goToPage(currentPage - 1);
  container.appendChild(prevBtn);

  // Determine visible page numbers (e.g. 1 2 3 4 5...)
  let pages = [];
  if (totalPages <= 7) {
    for (let i = 1; i <= totalPages; i++) pages.push(i);
  } else {
    pages.push(1);
    if (currentPage > 3) pages.push("...");
    for (let i = Math.max(2, currentPage - 1); i <= Math.min(totalPages - 1, currentPage + 1); i++) {
      pages.push(i);
    }
    if (currentPage < totalPages - 2) pages.push("...");
    pages.push(totalPages);
  }

  pages.forEach(p => {
    if (p === "...") {
      const span = document.createElement("span");
      span.className = "page-btn disabled";
      span.innerText = "...";
      container.appendChild(span);
    } else {
      const btn = document.createElement("button");
      btn.className = `page-btn ${p === currentPage ? 'active' : ''}`;
      btn.innerText = p;
      btn.onclick = () => goToPage(p);
      container.appendChild(btn);
    }
  });

  // Next button
  const nextBtn = document.createElement("button");
  nextBtn.className = `page-btn ${currentPage === totalPages ? 'disabled' : ''}`;
  nextBtn.innerHTML = "&raquo;";
  nextBtn.title = "Trang sau";
  nextBtn.onclick = () => goToPage(currentPage + 1);
  container.appendChild(nextBtn);
}

function toggleSelectRow(email, checkbox) {
  if (checkbox.checked) {
    selectedEmails.add(email);
  } else {
    selectedEmails.delete(email);
  }
  updateSelectionUI();
}

function toggleSelectAll(checkbox) {
  const startIndex = (currentPage - 1) * perPage;
  const endIndex = Math.min(startIndex + perPage, filteredAccountsList.length);
  const pageItems = filteredAccountsList.slice(startIndex, endIndex);

  if (checkbox.checked) {
    pageItems.forEach(acc => selectedEmails.add(acc.email));
  } else {
    pageItems.forEach(acc => selectedEmails.delete(acc.email));
  }
  renderCurrentPage();
}

function updateSelectionUI() {
  const wrap = document.getElementById("selectionStatusWrap");
  const countText = document.getElementById("selectedCountText");
  const size = selectedEmails.size;

  if (size > 0) {
    if (wrap) wrap.style.display = "inline-flex";
    if (countText) countText.innerText = `Đã chọn ${size} mục`;
  } else {
    if (wrap) wrap.style.display = "none";
  }
}

async function deleteSingleAccount(email) {
  const idx = allAccounts.findIndex(acc => acc.email === email);
  if (idx === -1) return;
  if (!confirm(`Bạn có chắc muốn xóa tài khoản ${email}?`)) return;

  try {
    const res = await fetch(`/api/accounts/${idx}`, { method: "DELETE" });
    if (res.ok) {
      selectedEmails.delete(email);
      showToast(`Đã xóa ${email}`, "info");
      loadAccounts();
    }
  } catch (err) {
    showToast("Xóa thất bại", "error");
  }
}

async function deleteSelectedAccounts() {
  const size = selectedEmails.size;
  if (size === 0) return;
  if (!confirm(`Bạn có chắc muốn xóa ${size} tài khoản đã chọn?`)) return;

  let deletedCount = 0;
  const toDelete = Array.from(selectedEmails);
  for (const email of toDelete) {
    const idx = allAccounts.findIndex(acc => acc.email === email);
    if (idx !== -1) {
      try {
        const res = await fetch(`/api/accounts/${idx}`, { method: "DELETE" });
        if (res.ok) {
          deletedCount++;
          allAccounts.splice(idx, 1);
        }
      } catch (e) {}
    }
  }

  selectedEmails.clear();
  showToast(`Đã xóa ${deletedCount} tài khoản`, "info");
  loadAccounts();
}

function exportData(format) {
  // If user selected specific checkboxes, export selected!
  // Otherwise export all filtered accounts (or all accounts)
  let exportList = [];
  if (selectedEmails.size > 0) {
    exportList = allAccounts.filter(acc => selectedEmails.has(acc.email));
  } else if (filteredAccountsList.length > 0) {
    exportList = filteredAccountsList;
  } else {
    exportList = allAccounts;
  }

  if (exportList.length === 0) {
    showToast("Không có tài khoản nào để xuất", "error");
    return;
  }

  const isSelective = selectedEmails.size > 0;
  const count = exportList.length;

  if (format === "oauth") {
    // Format into standard Grok Router OAuth format
    const oauthData = exportList.map(acc => {
      const accTok = (acc.access_token && acc.access_token.startsWith("eyJ0eXAiOiJhdCtqd3Qi")) 
        ? acc.access_token 
        : (acc.sso_cookie || "");
      const refTok = acc.refresh_token || acc.sso_rw_cookie || acc.sso_cookie || "";
      return {
        email: acc.email,
        access_token: accTok,
        refresh_token: refTok
      };
    });

    downloadBlob(
      JSON.stringify(oauthData, null, 2),
      isSelective ? `grok_oauth_tokens_selected_${count}.json` : "grok_oauth_tokens.json",
      "application/json"
    );
    showToast(`Đã xuất ${count} tài khoản (OAuth JSON)`, "success");

  } else if (format === "json") {
    downloadBlob(
      JSON.stringify(exportList, null, 2),
      isSelective ? `grok_accounts_selected_${count}.json` : "grok_accounts.json",
      "application/json"
    );
    showToast(`Đã xuất ${count} tài khoản (JSON)`, "success");

  } else if (format === "txt") {
    const lines = exportList.map(acc => `${acc.email}:${acc.password}:${acc.sso_cookie || ''}:${acc.user_id || ''}`);
    downloadBlob(
      lines.join("\n") + "\n",
      isSelective ? `grok_accounts_selected_${count}.txt` : "grok_accounts.txt",
      "text/plain"
    );
    showToast(`Đã xuất ${count} tài khoản (TXT)`, "success");
  }
}

function downloadBlob(content, filename, contentType) {
  const blob = new Blob([content], { type: contentType });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(url);
}

function copyToClipboard(text, successMsg) {
  if (!text) {
    showToast("Không có dữ liệu", "error");
    return;
  }
  navigator.clipboard.writeText(text).then(() => {
    showToast(successMsg || "Đã chép", "success");
  }).catch(() => {
    showToast("Sao chép thất bại", "error");
  });
}

function escapeHtml(str) {
  if (!str) return "";
  return String(str)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#039;");
}

function escapeAttr(str) {
  if (!str) return "";
  return String(str).replace(/'/g, "\\'").replace(/"/g, "&quot;");
}
