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
  updateThreadBadge();
  renderThreadsGrid();
  checkRotatingProxyStatus();
  checkTorStatus();
  try {
    const savedPrefix = localStorage.getItem("xai_name_prefix");
    if (savedPrefix && document.getElementById("namePrefix")) {
      document.getElementById("namePrefix").value = savedPrefix;
    }
  } catch (e) {}
  toggleNameInputs();

  const btnThreadsToggle = document.getElementById("btnOpenThreadsModal");
  if (btnThreadsToggle) {
    btnThreadsToggle.addEventListener("click", (e) => {
      e.preventDefault();
      openThreadsModal();
    });
  }

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
  if (btnText) btnText.innerText = val > 1 ? `BẮT ĐẦU (${val})` : "BẮT ĐẦU";
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
  currentThreadCount = parseInt(t) || 1;
  const btnText = document.getElementById("btnThreadsText");
  if (btnText) {
    btnText.innerText = `📊 TIẾN TRÌNH (${t} LUỒNG)`;
  }
}

function toggleNameInputs() {
  const isRandom = document.getElementById("randomNameCheckbox").checked;
  const customRow = document.getElementById("customNameRow");
  const randomRow = document.getElementById("randomNameRow");
  if (customRow) {
    customRow.style.display = isRandom ? "none" : "flex";
  }
  if (randomRow) {
    randomRow.style.display = isRandom ? "flex" : "none";
  }
  if (isRandom) updateNamePreview();
}

function shuffleString(value) {
  const src = String(value || "");
  if (src.length <= 1) return src;
  let shuffled = src;
  for (let attempt = 0; attempt < 8; attempt++) {
    const chars = src.split("");
    for (let i = chars.length - 1; i > 0; i--) {
      const j = Math.floor(Math.random() * (i + 1));
      [chars[i], chars[j]] = [chars[j], chars[i]];
    }
    shuffled = chars.join("");
    if (shuffled !== src || new Set(src).size === 1) break;
  }
  return shuffled;
}

function randomNameSuffix() {
  const digits = String(Math.floor(Math.random() * 99) + 1).padStart(2, "0");
  const letters = "ABCDEFGHIJKLMNOPQRSTUVWXYZ";
  const a = letters[Math.floor(Math.random() * 26)];
  const b = letters[Math.floor(Math.random() * 26)];
  return `${digits}${a}${b}`;
}

function updateNamePreview() {
  const prefixInput = document.getElementById("namePrefix");
  const preview = document.getElementById("namePreview");
  if (!prefixInput || !preview) return;
  const prefix = (prefixInput.value || "TAIKHOAN").trim() || "TAIKHOAN";
  preview.textContent = `${shuffleString(prefix)}${randomNameSuffix()}`;
  try {
    localStorage.setItem("xai_name_prefix", prefix);
  } catch (e) {}
}

function toggleTorSettings() {
  const useTor = document.getElementById("useTorCheckbox")?.checked;
  const torRow = document.getElementById("torConfigRow");
  if (torRow) torRow.style.display = useTor ? "block" : "none";

  if (useTor) {
    checkTorStatus();
  }
}

function toggleRotatingProxySettings() {
  const useRot = document.getElementById("useRotatingProxyCheckbox")?.checked;
  const rotRow = document.getElementById("rotatingProxyConfigRow");
  if (rotRow) rotRow.style.display = useRot ? "block" : "none";

  if (useRot) {
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

async function checkTorStatus(channel = 0) {
  if (channel === 0 || channel === 1) {
    const badge = document.getElementById("torStatusBadge");
    const ipText = document.getElementById("torIpText");
    const socksPort = document.getElementById("torSocksPort")?.value || 9050;
    const controlPort = document.getElementById("torControlPort")?.value || 9051;

    if (ipText) ipText.innerText = "Đang tải...";

    try {
      const res = await fetch(`/api/tor/status?socks_port=${socksPort}&control_port=${controlPort}`);
      const data = await res.json();
      if (data.online && data.ip) {
        if (badge) {
          badge.className = "tor-indicator";
          badge.innerHTML = `<span class="tor-dot"></span><span class="tor-conn-label">TOR 1</span>`;
        }
        if (ipText) ipText.innerText = data.ip;
      } else {
        if (badge) {
          badge.className = "tor-indicator offline";
          badge.innerHTML = `<span class="tor-dot"></span><span class="tor-conn-label">OFFLINE</span>`;
        }
        if (ipText) ipText.innerText = "Chưa kết nối Tor 1";
      }
    } catch (e) {
      if (ipText) ipText.innerText = "Lỗi kết nối";
    }
  }

  if (channel === 0 || channel === 2) {
    const badge2 = document.getElementById("tor2StatusBadge");
    const ipText2 = document.getElementById("tor2IpText");
    const socksPort2 = document.getElementById("tor2SocksPort")?.value || 9052;
    const controlPort2 = document.getElementById("tor2ControlPort")?.value || 9053;

    if (ipText2) ipText2.innerText = "Đang tải...";

    try {
      const res2 = await fetch(`/api/tor/status?socks_port=${socksPort2}&control_port=${controlPort2}`);
      const data2 = await res2.json();
      if (data2.online && data2.ip) {
        if (badge2) {
          badge2.className = "tor-indicator";
          badge2.innerHTML = `<span class="tor-dot"></span><span class="tor-conn-label">TOR 2</span>`;
        }
        if (ipText2) ipText2.innerText = data2.ip;
      } else {
        if (badge2) {
          badge2.className = "tor-indicator offline";
          badge2.innerHTML = `<span class="tor-dot"></span><span class="tor-conn-label">OFFLINE</span>`;
        }
        if (ipText2) ipText2.innerText = "Chưa kết nối Tor 2";
      }
    } catch (e) {
      if (ipText2) ipText2.innerText = "Lỗi kết nối";
    }
  }
}

async function testOrRotateTorIp(channel = 1) {
  const isCh2 = channel === 2;
  const btn = document.getElementById(isCh2 ? "btnRotateTor2Ip" : "btnRotateIp");
  const ipText = document.getElementById(isCh2 ? "tor2IpText" : "torIpText");
  const socksPort = document.getElementById(isCh2 ? "tor2SocksPort" : "torSocksPort")?.value || (isCh2 ? 9052 : 9050);
  const controlPort = document.getElementById(isCh2 ? "tor2ControlPort" : "torControlPort")?.value || (isCh2 ? 9053 : 9051);

  if (btn) btn.classList.add("rotating");
  if (ipText) ipText.innerText = "Đang đổi IP...";

  try {
    const res = await fetch(`/api/tor/renew-ip?socks_port=${socksPort}&control_port=${controlPort}`, { method: "POST" });
    const data = await res.json();
    if (data.success && data.ip) {
      showToast(`Đã đổi Tor ${channel} Exit IP: ${data.ip}`, "success");
    } else {
      showToast(`Đã đổi IP Tor ${channel}`, "info");
    }
    await checkTorStatus(channel);
  } catch (e) {
    showToast(`Lỗi kết nối Tor ${channel}`, "error");
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
  const namePrefix = (document.getElementById("namePrefix")?.value || "TAIKHOAN").trim() || "TAIKHOAN";
  const password = document.getElementById("password").value.trim() || "taikhoanAI123";

  const useTor = document.getElementById("useTorCheckbox")?.checked || false;
  const useRotating = document.getElementById("useRotatingProxyCheckbox")?.checked || false;

  let proxyMode = "direct";
  if (useRotating && useTor) proxyMode = "decoupled";
  else if (useRotating) proxyMode = "rotating";
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

  const numThreads = parseInt(document.getElementById("threadCount")?.value) || 1;
  currentThreadCount = numThreads;
  currentThreadStates = {};
  for (let i = 1; i <= numThreads; i++) {
    currentThreadStates[String(i)] = {
      id: i,
      status: "running",
      account_num: i <= count ? i : 0,
      email: "",
      step: "1. Khởi tạo trình duyệt...",
      progress: 10,
      elapsed_sec: 0
    };
  }

  const btnThreads = document.getElementById("btnOpenThreadsModal");
  if (btnThreads) {
    btnThreads.style.display = "inline-flex";
    const textEl = document.getElementById("btnThreadsText");
    if (textEl) textEl.innerText = `📊 TIẾN TRÌNH (${numThreads} LUỒNG)`;
  }

  setSystemState("running");
  startLiveTimer();

  if (progressContainer) {
    progressContainer.style.display = "block";
    updateProgress(0, count, 0);
  }

  lastKnownSuccessCount = 0;
  logMessage(`Bắt đầu chạy ${numThreads} luồng song song (tổng ${count} acc)...`, "HỆ THỐNG");

  const payload = {
    email: null,
    first_name: firstName,
    last_name: lastName,
    password: password,
    use_tempmail: true,
    proxy: null,
    headless: true,
    count: count,
    threads: numThreads,
    random_name: isRandom,
    name_prefix: namePrefix,
    proxy_mode: "decoupled",
    use_tor: true,
    tor_for_tempmail: true,
    tor_socks_port: 9050,
    tor_control_port: 9051,
    rotating_proxy_key: "HVnSXrEVXRSrUYBkwYzuId",
    rotating_proxy_nhamang: "random",
    rotating_proxy_tinhthanh: "0"
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
    stopLiveTimer();
    setSystemState("error");
  }
}

async function stopCreation() {
  if (!activeTaskId) return;
  const btnStop = document.getElementById("btnStopAccount");
  btnStop.disabled = true;
  btnStop.querySelector("span").innerText = "ĐANG DỪNG...";
  logMessage("Đang gửi yêu cầu dừng...", "CẢNH BÁO");

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
  if (statusEl) statusEl.innerText = `${current}/${total} (Xong: ${success})`;
  if (percentEl) percentEl.innerText = `${percent}%`;
  if (barEl) barEl.style.width = `${percent}%`;
}

// Live Elapsed Timer
let taskStartTime = null;
let liveTimerInterval = null;

function formatElapsed(sec) {
  const m = Math.floor(sec / 60);
  const s = sec % 60;
  return `${m < 10 ? '0' : ''}${m}:${s < 10 ? '0' : ''}${s}`;
}

function startLiveTimer(serverStartTime) {
  taskStartTime = serverStartTime ? (serverStartTime * 1000) : Date.now();
  if (liveTimerInterval) clearInterval(liveTimerInterval);
  
  const timerBadge = document.getElementById("liveTimerBadge");
  const consoleTimer = document.getElementById("consoleTimerTag");
  if (timerBadge) timerBadge.style.display = "inline-flex";
  if (consoleTimer) consoleTimer.style.display = "inline-flex";

  const update = () => {
    const elapsedSec = Math.floor((Date.now() - taskStartTime) / 1000);
    const timeStr = formatElapsed(elapsedSec);
    
    const t1 = document.getElementById("liveTimerText");
    const t2 = document.getElementById("consoleTimerText");
    const t3 = document.getElementById("modalTimerBadge");
    if (t1) t1.innerText = timeStr;
    if (t2) t2.innerText = timeStr;
    if (t3) t3.innerText = `⏱ ${timeStr}`;
  };

  update();
  liveTimerInterval = setInterval(update, 1000);
}

function stopLiveTimer() {
  if (liveTimerInterval) {
    clearInterval(liveTimerInterval);
    liveTimerInterval = null;
  }
}

// Threads Monitor Modal
let currentThreadStates = {};
let currentThreadCount = 1;

function openThreadsModal() {
  const modal = document.getElementById("threadsModal");
  if (modal) {
    modal.style.display = "flex";
    renderThreadsGrid();
  }
}

function closeThreadsModal() {
  const modal = document.getElementById("threadsModal");
  if (modal) modal.style.display = "none";
}

function handleModalBackdropClick(event) {
  if (event.target.id === "threadsModal") {
    closeThreadsModal();
  }
}

window.openThreadsModal = openThreadsModal;
window.closeThreadsModal = closeThreadsModal;
window.handleModalBackdropClick = handleModalBackdropClick;

document.addEventListener("keydown", (e) => {
  if (e.key === "Escape") closeThreadsModal();
});

function renderThreadsGrid() {
  const container = document.getElementById("threadsGridContainer");
  if (!container) return;

  const tCount = currentThreadCount || 1;
  const modalTitle = document.getElementById("threadsModalTitle");
  if (modalTitle) {
    modalTitle.innerText = `TIẾN TRÌNH SONG SONG (${tCount} LUỒNG)`;
  }

  let html = "";
  for (let i = 1; i <= tCount; i++) {
    const t = currentThreadStates[String(i)] || {
      id: i,
      status: "idle",
      account_num: 0,
      email: "",
      step: "Sẵn sàng...",
      progress: 0,
      elapsed_sec: 0
    };

    let statusClass = "idle";
    let statusLabel = "CHỜ";
    if (t.status === "running") {
      statusClass = "running";
      statusLabel = "ĐANG CHẠY";
    } else if (t.status === "success") {
      statusClass = "success";
      statusLabel = "THÀNH CÔNG";
    } else if (t.status === "error") {
      statusClass = "error";
      statusLabel = "LỖI";
    }

    const targetText = t.account_num > 0 ? `Acc #${t.account_num}` : "Chờ lệnh";
    const emailText = t.email ? `(${t.email})` : "";
    const progressPct = t.progress || 0;
    const stepText = t.step || "Đang xử lý...";
    const elapsedText = t.elapsed_sec > 0 ? `⏱ ${t.elapsed_sec}s` : "";

    html += `
      <div class="thread-card ${statusClass === 'running' ? 'active' : statusClass}">
        <div class="thread-card-top">
          <span class="thread-name-tag">LUỒNG #${i}</span>
          <span class="thread-status-pill ${statusClass}">${statusLabel}</span>
        </div>
        <div class="thread-target-info">
          <span class="thread-target-acc" title="${emailText}">${targetText} ${emailText}</span>
          <span class="thread-timer">${elapsedText}</span>
        </div>
        <div class="thread-progress-wrap">
          <div class="thread-progress-bar" style="width: ${progressPct}%;"></div>
        </div>
        <div class="thread-step-text" title="${stepText}">${stepText}</div>
      </div>
    `;
  }
  container.innerHTML = html;
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

      // Update Thread states
      if (data.thread_states) {
        currentThreadStates = data.thread_states;
      }
      if (data.threads) {
        currentThreadCount = data.threads;
      }

      const modalProgressBadge = document.getElementById("modalProgressBadge");
      if (modalProgressBadge) {
        modalProgressBadge.innerText = `${success}/${total} Acc`;
      }

      // If modal is currently open, re-render
      const modal = document.getElementById("threadsModal");
      if (modal && modal.style.display !== "none") {
        renderThreadsGrid();
      }

      if (success > lastKnownSuccessCount) {
        lastKnownSuccessCount = success;
        loadAccounts();
      }

      if (data.status === "success") {
        clearInterval(pollInterval);
        activeTaskId = null;
        stopLiveTimer();
        resetCreateButton();
        setSystemState("success");
        showToast(`Hoàn tất: Đã tạo ${success}/${total} tài khoản`, "success");
        loadAccounts();
        renderThreadsGrid();
      } else if (data.status === "stopped") {
        clearInterval(pollInterval);
        activeTaskId = null;
        stopLiveTimer();
        resetCreateButton();
        setSystemState("idle");
        showToast(`Đã dừng (${success}/${total} tài khoản)`, "info");
        loadAccounts();
        renderThreadsGrid();
      } else if (data.status === "failed") {
        clearInterval(pollInterval);
        activeTaskId = null;
        stopLiveTimer();
        resetCreateButton();
        setSystemState("error");
        showToast(data.error || "Tác vụ thất bại", "error");
        renderThreadsGrid();
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

function updateOAuthSyncStats() {
  const total = allAccounts.length;
  const oauthCount = allAccounts.filter(a => a.access_token && a.access_token.startsWith("eyJ")).length;
  const pendingCount = total - oauthCount;

  // 1. Top nav badge
  const topBadge = document.getElementById("oauthCountBadge");
  if (topBadge) {
    topBadge.innerHTML = `<span style="color: ${pendingCount === 0 ? '#34d399' : '#fbbf24'}">●</span> ${oauthCount}/${total} OAuth`;
    topBadge.title = `Đã có OAuth Token: ${oauthCount}/${total} (Chưa có: ${pendingCount})`;
  }

  // 2. Badge next to sync button
  const statusBadge = document.getElementById("oauthStatusBadge");
  const syncText = document.getElementById("oauthSyncText");
  if (statusBadge && syncText) {
    if (total === 0) {
      statusBadge.style.display = "none";
    } else {
      statusBadge.style.display = "inline-flex";
      if (pendingCount === 0) {
        statusBadge.className = "oauth-sync-badge all-synced";
        syncText.innerHTML = `✔ Đã đủ: <strong>${oauthCount}/${total}</strong> OAuth`;
      } else {
        statusBadge.className = "oauth-sync-badge";
        syncText.innerHTML = `Chưa có OAuth: <strong>${pendingCount}</strong> / ${total}`;
      }
    }
  }

  return { total, oauthCount, pendingCount };
}

async function loadAccounts() {
  try {
    const res = await fetch("/api/accounts");
    allAccounts = await res.json();
    const badge = document.getElementById("accountCountBadge");
    if (badge) {
      badge.innerText = `${allAccounts.length} TÀI KHOẢN`;
    }
    updateOAuthSyncStats();
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
    const hasOAuth = acc.access_token && acc.access_token.startsWith("eyJ");
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
    const hasOAuth = acc.access_token && acc.access_token.startsWith("eyJ");
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
      const accTok = (acc.access_token && acc.access_token.startsWith("eyJ")) 
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

async function syncAllOAuthTokens() {
  const btn = document.getElementById("btnSyncOAuth");
  if (btn) {
    btn.disabled = true;
    btn.textContent = "⏳ ĐANG ĐỒNG BỘ 10 LUỒNG...";
  }
  showToast("Đang kích hoạt đồng bộ 10 luồng song song...", "info");
  try {
    const res = await fetch("/api/sync-oauth", { method: "POST" });
    const data = await res.json();
    showToast(data.message || "Đã bắt đầu đồng bộ OAuth Token!", "success");
    
    let maxPolls = 80;
    const pollTimer = setInterval(async () => {
      await loadAccounts();
      const stats = updateOAuthSyncStats();
      if (btn && stats.pendingCount > 0) {
        btn.textContent = `⏳ ĐỒNG BỘ (Còn ${stats.pendingCount})...`;
      }
      if (stats.pendingCount === 0 || maxPolls <= 0) {
        clearInterval(pollTimer);
        if (btn) {
          btn.disabled = false;
          btn.textContent = "⚡ ĐỒNG BỘ OAUTH";
        }
        if (stats.pendingCount === 0) {
          showToast(`Hoàn tất! 100% tài khoản (${stats.total}/${stats.total}) đã có OAuth 2.0!`, "success");
        }
      }
      maxPolls--;
    }, 1500);
  } catch (err) {
    showToast("Lỗi đồng bộ: " + err.message, "error");
    if (btn) {
      btn.disabled = false;
      btn.textContent = "⚡ ĐỒNG BỘ OAUTH";
    }
  }
}

let reviveTimerInterval = null;
let reviveStartTime = null;

function openReviveModal() {
  const modal = document.getElementById("reviveModal");
  if (modal) modal.style.display = "flex";
}

function closeReviveModal() {
  const modal = document.getElementById("reviveModal");
  if (modal) modal.style.display = "none";
}

function handleReviveBackdropClick(e) {
  if (e.target.id === "reviveModal") closeReviveModal();
}

function openPingModal() {
  const modal = document.getElementById("pingModal");
  if (modal) modal.style.display = "flex";
}

function closePingModal() {
  const modal = document.getElementById("pingModal");
  if (modal) modal.style.display = "none";
}

function handlePingBackdropClick(e) {
  if (e.target.id === "pingModal") closePingModal();
}

async function stopReviveDeadAccounts() {
  try {
    const res = await fetch("/api/accounts/revive/stop", { method: "POST" });
    const data = await res.json();
    showToast(data.message || "Đã gửi yêu cầu dừng.", "warning");
    const stopBtn = document.getElementById("btnStopReviveModal");
    if (stopBtn) {
      stopBtn.disabled = true;
      stopBtn.textContent = "⏳ ĐANG DỪNG...";
    }
  } catch (e) {
    showToast("Lỗi dừng: " + e.message, "error");
  }
}

async function startReviveDeadAccounts() {
  const btn = document.getElementById("btnReviveAccounts");
  if (btn) {
    btn.disabled = true;
    btn.textContent = "⏳ ĐANG HỒI SINH...";
  }

  // Reset & open popup modal immediately
  openReviveModal();
  const stopBtn = document.getElementById("btnStopReviveModal");
  if (stopBtn) {
    stopBtn.disabled = false;
    stopBtn.textContent = "🛑 DỪNG LẠI";
  }
  document.getElementById("reviveTotalAcc").innerText = "...";
  document.getElementById("reviveLiveAcc").innerText = "0";
  document.getElementById("reviveDeadAcc").innerText = "0";
  document.getElementById("reviveCurrentEmail").innerText = "Đang kết nối...";
  document.getElementById("reviveProgressBar").style.width = "0%";
  document.getElementById("reviveProgressPercent").innerText = "0%";
  document.getElementById("reviveProgressStatus").innerText = "Đang khởi động...";
  document.getElementById("reviveLogsStream").innerHTML = '<div class="revive-log-line info">🚀 Bắt đầu tiến trình hồi sinh đa tầng (OAuth Refresh ➔ SSO Minting ➔ Password Login ➔ grok-4.6 Ping)...</div>';

  if (reviveTimerInterval) clearInterval(reviveTimerInterval);
  reviveStartTime = Date.now();
  const timerBadge = document.getElementById("reviveTimerBadge");
  reviveTimerInterval = setInterval(() => {
    if (!reviveStartTime || !timerBadge) return;
    const elapsed = Math.floor((Date.now() - reviveStartTime) / 1000);
    const m = String(Math.floor(elapsed / 60)).padStart(2, "0");
    const s = String(elapsed % 60).padStart(2, "0");
    timerBadge.innerText = `⏱ ${m}:${s}`;
  }, 1000);

  logMessage("🚀 Bắt đầu tiến trình HỒI SINH toàn bộ tài khoản chết qua SSO Cookie & OAuth Refresh...", "HỆ THỐNG");
  showToast("Đang kích hoạt tiến trình làm sống lại toàn bộ tài khoản...", "info");

  try {
    const threadCount = parseInt(document.getElementById("threadCount")?.value) || 5;
    const res = await fetch("/api/accounts/revive", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        threads: threadCount,
        proxy_mode: "rotating",
        rotating_proxy_key: "HVnSXrEVXRSrUYBkwYzuId"
      })
    });
    const data = await res.json();
    showToast(data.message || "Đã khởi chạy tiến trình hồi sinh!", "success");

    let lastLogIndex = 0;
    const logsBox = document.getElementById("reviveLogsStream");

    const pollTimer = setInterval(async () => {
      try {
        const sRes = await fetch("/api/accounts/revive/status");
        const status = await sRes.json();

        // Update modal metrics
        if (status.total > 0) {
          document.getElementById("reviveTotalAcc").innerText = status.total;
        }
        document.getElementById("reviveLiveAcc").innerText = status.revived_count;
        document.getElementById("reviveDeadAcc").innerText = status.failed_count;
        document.getElementById("reviveCurrentEmail").innerText = status.current_email || "--";
        document.getElementById("reviveProgressBadge").innerText = `${status.processed}/${status.total}`;

        const pct = status.total > 0 ? Math.min(100, Math.round((status.processed / status.total) * 100)) : 0;
        document.getElementById("reviveProgressPercent").innerText = `${pct}%`;
        document.getElementById("reviveProgressBar").style.width = `${pct}%`;
        document.getElementById("reviveProgressStatus").innerText = `Đã xử lý ${status.processed}/${status.total} tài khoản`;

        if (btn) {
          btn.textContent = `⏳ HỒI SINH (${status.processed}/${status.total} - Sống: ${status.revived_count})...`;
        }

        // Render stream logs in modal and console
        if (status.logs && status.logs.length > lastLogIndex) {
          for (let i = lastLogIndex; i < status.logs.length; i++) {
            const rawLog = status.logs[i];
            logMessage(rawLog, "HỒI SINH");

            if (logsBox) {
              const line = document.createElement("div");
              line.className = "revive-log-line " + (rawLog.includes("✔") ? "ok" : rawLog.includes("✘") ? "err" : "info");
              line.innerText = rawLog;
              logsBox.appendChild(line);
              if (logsBox.children.length > 150) {
                logsBox.removeChild(logsBox.firstElementChild);
              }
              logsBox.scrollTop = logsBox.scrollHeight;
            }
          }
          lastLogIndex = status.logs.length;
        }

        if (!status.is_running && status.processed > 0) {
          clearInterval(pollTimer);
          if (reviveTimerInterval) clearInterval(reviveTimerInterval);
          if (btn) {
            btn.disabled = false;
            btn.textContent = "⚡ HỒI SINH";
          }
          await loadAccounts();
          showToast(`Hoàn tất hồi sinh! ${status.revived_count}/${status.total} tài khoản đã SỐNG 100%!`, "success");
          logMessage(`🏁 Hoàn tất: Đã hồi sinh thành công ${status.revived_count}/${status.total} tài khoản!`, "THÀNH CÔNG");
          
          if (logsBox) {
            const endLine = document.createElement("div");
            endLine.className = "revive-log-line ok";
            endLine.innerHTML = `<strong>🏁 ĐÃ HOÀN TẤT!</strong> Thành công hồi sinh <strong>${status.revived_count}/${status.total}</strong> tài khoản sống 100%. File chuẩn Router đã sẵn sàng tải!`;
            logsBox.appendChild(endLine);
            logsBox.scrollTop = logsBox.scrollHeight;
          }
        }
      } catch (e) {}
    }, 1500);
  } catch (err) {
    showToast("Lỗi khởi chạy hồi sinh: " + err.message, "error");
    if (btn) {
      btn.disabled = false;
      btn.textContent = "⚡ HỒI SINH";
    }
  }
}

async function runHealthCheckScan() {
  const btn = document.getElementById("btnHealthCheck");
  if (btn) {
    btn.disabled = true;
    btn.textContent = "⏳ ĐANG PING...";
  }

  openPingModal();
  document.getElementById("pingTotalAcc").innerText = "...";
  document.getElementById("pingLiveAcc").innerText = "...";
  document.getElementById("pingDeadAcc").innerText = "...";
  document.getElementById("pingResultsList").innerHTML = '<div class="revive-log-line info">⏳ Đang gửi test ping grok-4.6 tới toàn bộ tài khoản (HTTP POST /v1/chat/completions)...</div>';

  showToast("Đang gửi test ping grok-4.6 tới toàn bộ tài khoản...", "info");
  logMessage("🔍 Bắt đầu kiểm tra sức khoẻ (Ping test grok-4.6)...", "HỆ THỐNG");

  try {
    const res = await fetch("/api/accounts/health-check");
    const data = await res.json();
    
    document.getElementById("pingTotalAcc").innerText = data.total;
    document.getElementById("pingLiveAcc").innerText = data.live_count;
    document.getElementById("pingDeadAcc").innerText = data.dead_count;

    const listEl = document.getElementById("pingResultsList");
    if (listEl) {
      listEl.innerHTML = "";
      (data.results || []).forEach(r => {
        const row = document.createElement("div");
        row.className = "revive-log-line " + (r.status === "healthy" ? "ok" : "err");
        row.innerHTML = `${r.status === "healthy" ? "🟢" : "🔴"} <strong>${escapeHtml(r.email)}</strong> ➔ ${r.status === "healthy" ? "SỐNG 100% (HTTP 200 OK)" : "CHẾT / 401 (" + r.message + ")"}`;
        listEl.appendChild(row);
      });
      listEl.scrollTop = 0;
    }

    logMessage(`📊 Kết quả Ping: ${data.live_count} SỐNG (HTTP 200) / ${data.dead_count} CHẾT trên tổng ${data.total} tài khoản.`, "THÔNG TIN");
    showToast(`Đã kiểm tra xong: ${data.live_count} sống / ${data.dead_count} chết`, data.live_count > 0 ? "success" : "warning");
    await loadAccounts();
  } catch (err) {
    showToast("Lỗi kiểm tra sức khoẻ: " + err.message, "error");
    document.getElementById("pingResultsList").innerHTML = `<div class="revive-log-line err">Lỗi kiểm tra: ${escapeHtml(err.message)}</div>`;
  } finally {
    if (btn) {
      btn.disabled = false;
      btn.textContent = "🩺 CHECK PING";
    }
  }
}

