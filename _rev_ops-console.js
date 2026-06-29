const OPS_API = window.OPS_API_PREFIX || "/api/workbench/ops";
const panels = [
  ["users", "用户"],
  ["payments", "订单"],
  ["jobs", "任务"],
  ["traffic", "流量检测"],
  ["security", "安全监控"],
  ["plans", "套餐"],
  ["licenses", "授权码"],
  ["audit", "审计"],
];
const opsState = { plans: [] };

const $ = (id) => document.getElementById(id);
const esc = (value) => String(value ?? "").replaceAll("&", "&amp;").replaceAll("<", "&lt;").replaceAll(">", "&gt;").replaceAll('"', "&quot;").replaceAll("'", "&#039;");
const cookie = (name) => document.cookie.split(";").map((v) => v.trim()).find((v) => v.startsWith(`${name}=`))?.slice(name.length + 1) || "";
const message = (text, bad = false) => {
  $("ops-message").textContent = text || "";
  $("ops-message").style.color = bad ? "#fecdd3" : "#8ff7e8";
};

async function api(path, options = {}) {
  const headers = { "content-type": "application/json", ...(options.headers || {}) };
  const csrf = cookie("csrf_token");
  if (csrf) headers["x-csrf-token"] = csrf;
  const res = await fetch(`${OPS_API}${path}`, { ...options, headers });
  const text = await res.text();
  const data = text ? JSON.parse(text) : {};
  if (!res.ok) throw new Error(data.error || `HTTP ${res.status}`);
  return data;
}

async function licenseApi(path, options = {}) {
  const token = sessionStorage.getItem("social_ai_admin_token") || $("license-admin-token")?.value.trim() || "";
  if (!token) throw new Error("请先填写 AI 管理 Token，再刷新授权码数据");
  const headers = { "content-type": "application/json", authorization: `Bearer ${token}`, ...(options.headers || {}) };
  const res = await fetch(`/social-ai-credit-api${path}`, { ...options, headers });
  const text = await res.text();
  const data = text ? JSON.parse(text) : {};
  if (!res.ok) {
    const detail = data.detail || data.error || `HTTP ${res.status}`;
    throw new Error(detail === "invalid admin token" ? "AI 管理 Token 无效，请清除后重新填写" : detail);
  }
  return data;
}

function renderNav() {
  $("ops-nav").innerHTML = panels.map(([id, label]) => `<button data-panel-target="${id}" class="${id === "overview" ? "active" : ""}">${label}</button>`).join("");
  $("ops-nav").addEventListener("click", (event) => {
    const btn = event.target.closest("[data-panel-target]");
    if (!btn) return;
    document.querySelectorAll("[data-panel-target]").forEach((item) => item.classList.toggle("active", item === btn));
    document.querySelectorAll(".ops-panel").forEach((panel) => panel.classList.toggle("active", panel.dataset.panel === btn.dataset.panelTarget));
    loadPanel(btn.dataset.panelTarget).catch((err) => message(err.message, true));
  });
}

function table(headers, rows) {
  return `<table class="ops-table"><thead><tr>${headers.map((h) => `<th>${esc(h)}</th>`).join("")}</tr></thead><tbody>${rows.join("") || `<tr><td colspan="${headers.length}" class="ops-muted">暂无数据</td></tr>`}</tbody></table>`;
}

async function loadUsers() {
  const q = encodeURIComponent($("users-q").value.trim());
  const data = await api(`/users?q=${q}&page_size=50`);
  $("users-table").innerHTML = table(["ID", "用户", "余额", "状态", "任务/订单", "操作"], data.users.map((u) => `
    <tr>
      <td>${u.id}</td><td>${esc(u.name)}<br><span class="ops-muted">${esc(u.email)}</span></td>
      <td>${u.credits}</td><td>${u.is_disabled ? '<span class="ops-badge bad">停用</span>' : '<span class="ops-badge">正常</span>'}${u.is_admin ? ' <span class="ops-badge">operator</span>' : ''}</td>
      <td>${u.total_jobs} / ${u.total_payments}<br><span class="ops-muted">实付 ${Number(u.paid_amount || 0).toFixed(2)}</span></td>
      <td><div class="ops-actions">
        <button class="ops-btn secondary" data-credit="${u.id}">加扣点</button>
        <button class="ops-btn ${u.is_disabled ? "secondary" : "danger"}" data-status="${u.id}" data-disabled="${u.is_disabled ? "0" : "1"}">${u.is_disabled ? "解封" : "封禁"}</button>
        <button class="ops-btn warn" data-reset="${u.id}">重置密码</button>
      </div></td>
    </tr>`));
}

async function loadPayments() {
  const q = encodeURIComponent($("payments-q").value.trim());
  const status = encodeURIComponent($("payments-status").value);
  const data = await api(`/payments?q=${q}&status=${status}&page_size=50`);
  $("payments-table").innerHTML = table(["订单", "用户", "金额", "状态", "时间", "操作"], data.payments.map((p) => `
    <tr>
      <td>${esc(p.out_trade_no)}<br><span class="ops-muted">${esc(p.trade_no || p.plan_id)}</span></td>
      <td>${esc(p.user_name)}<br><span class="ops-muted">${esc(p.user_email)}</span></td>
      <td>${esc(p.money)} 元<br><span class="ops-muted">${p.credits} 点</span></td>
      <td><span class="ops-badge ${p.status === "paid" ? "" : "bad"}">${esc(p.status)}</span><br><span class="ops-muted">${esc(p.admin_note || "")}</span></td>
      <td>${esc(p.created_at)}<br><span class="ops-muted">${esc(p.paid_at || "")}</span></td>
      <td><div class="ops-actions"><button class="ops-btn secondary" data-note-payment="${p.id}">备注</button>${p.status !== "paid" ? `<button class="ops-btn danger" data-close-payment="${p.id}">关闭</button>` : ""}</div></td>
    </tr>`));
}

async function loadJobs() {
  const q = encodeURIComponent($("jobs-q").value.trim());
  const status = encodeURIComponent($("jobs-status").value);
  const data = await api(`/jobs?q=${q}&status=${status}&page_size=50`);
  $("jobs-table").innerHTML = table(["任务", "用户", "状态", "模板", "错误/输出", "操作"], data.jobs.map((j) => `
    <tr>
      <td>#${j.id}<br><span class="ops-muted">${esc(j.created_at)}</span></td>
      <td>${esc(j.user_name)}<br><span class="ops-muted">${esc(j.user_email)}</span></td>
      <td><span class="ops-badge ${j.status === "failed" ? "bad" : ""}">${esc(j.status)}</span><br><span class="ops-muted">${esc(j.comfy_prompt_id || "")}</span></td>
      <td>${esc(j.workflow_id)}<br><span class="ops-muted">${esc(j.ckpt_name || "")}</span></td>
      <td>${esc(j.error || "")}<br><span class="ops-muted">输出 ${j.outputs?.length || 0}</span>${renderJobDiagnostics(j)}</td>
      <td><div class="ops-actions">${["queued","submitting","running"].includes(j.status) ? `<button class="ops-btn danger" data-job-action="cancel" data-job="${j.id}">取消</button>` : ""}<button class="ops-btn secondary" data-job-action="refund" data-job="${j.id}">退点</button>${j.status === "failed" ? `<button class="ops-btn warn" data-job-action="retry" data-job="${j.id}">重试</button>` : ""}</div></td>
    </tr>`));
}

function renderJobDiagnostics(job) {
  const diag = job.talking_diagnostics || {};
  const node207 = (job.runninghub_node_info || []).find((item) => String(item.nodeId) === "207");
  const outputUrl = job.outputs?.[0]?.url || "";
  if (!diag.runninghub_task_id && !node207 && !outputUrl) return "";
  const image = diag.input_image || {};
  const imageSize = image.image_width && image.image_height ? `${image.image_width}x${image.image_height}` : "";
  return `
    <div class="ops-muted">
      taskId: ${esc(job.external_task_id || diag.runninghub_task_id || "")}<br>
      207.image: ${esc(node207?.fieldValue || diag.image_media?.fileName || "")}<br>
      原图: ${esc(image.filename || "")} ${esc(imageSize)} ${esc(image.size_bytes || "")} bytes<br>
      输出: ${esc(outputUrl)}
    </div>`;
}

const severityText = { critical: "严重", high: "高危", medium: "中危", low: "低危", info: "信息" };
const categoryText = {
  scanner: "扫描器",
  mapping: "资产测绘",
  cms_probe: "CMS探测",
  backoffice_probe: "后台探测",
  sensitive_probe: "敏感文件",
  exploit_probe: "漏洞探测",
  auth_attack: "认证攻击",
  unknown_probe: "未知探测",
  business: "业务访问",
  static: "静态资源",
};

function trafficHours() {
  return $("traffic-hours")?.value || "24";
}

function riskBadge(level) {
  return `<span class="ops-badge ${["critical", "high", "medium"].includes(level) ? "bad" : ""}">${esc(severityText[level] || level)}</span>`;
}

async function loadTraffic() {
  const hours = trafficHours();
  const overview = await api(`/traffic/overview?hours=${encodeURIComponent(hours)}`);
  $("traffic-summary").innerHTML = [
    ["总请求", overview.total_requests],
    ["可疑 IP", overview.suspicious_ips],
    ["高危事件", overview.high_risk_events],
    ["扫描命中", overview.scanner_hits],
  ].map(([label, value]) => `<div class="ops-card ops-stat"><span class="ops-muted">${label}</span><strong>${esc(value)}</strong></div>`).join("");
  $("traffic-risk-ips").innerHTML = `
    <h3>风险 IP</h3>
    ${table(["IP", "等级", "归属判断", "目的", "请求", "规则", "最后出现", "操作"], (overview.risk_ips || []).map((item) => `
      <tr>
        <td>${esc(item.ip)}</td>
        <td>${riskBadge(item.severity)}</td>
        <td>${esc(item.actor)}</td>
        <td>${esc(item.intent)}</td>
        <td>${esc(item.requests)}</td>
        <td>${esc((item.rules || []).slice(0, 4).join(", "))}</td>
        <td>${esc(item.last_seen)}</td>
        <td><button class="ops-btn secondary" data-traffic-ip="${esc(item.ip)}">画像</button></td>
      </tr>`))}`;
  await loadTrafficEvents();
}

async function loadTrafficEvents() {
  const params = new URLSearchParams({
    hours: trafficHours(),
    page_size: "80",
    ip: $("traffic-ip")?.value.trim() || "",
    severity: $("traffic-severity")?.value || "",
    category: $("traffic-category")?.value || "",
  });
  const data = await api(`/traffic/events?${params.toString()}`);
  $("traffic-events").innerHTML = `
    <h3>可疑事件</h3>
    ${table(["时间", "IP", "请求", "状态", "类型", "研判", "证据"], (data.events || []).map((event) => `
      <tr>
        <td>${esc(event.time)}</td>
        <td><button class="ops-btn secondary" data-traffic-ip="${esc(event.ip)}">${esc(event.ip)}</button></td>
        <td>${esc(event.method)} ${esc(event.path)}</td>
        <td>${esc(event.status)}</td>
        <td>${riskBadge(event.severity)} ${esc(categoryText[event.category] || event.category)}</td>
        <td>${esc(event.actor)}<br><span class="ops-muted">${esc(event.intent)}</span></td>
        <td><span class="ops-muted">${esc(event.evidence)}</span></td>
      </tr>`))}`;
}

async function loadTrafficIp(ip) {
  const data = await api(`/traffic/ip/${encodeURIComponent(ip)}?hours=${encodeURIComponent(trafficHours())}`);
  const p = data.profile;
  $("traffic-ip-profile").innerHTML = `
    <div class="ops-grid">
      <div class="ops-card ops-stat"><span class="ops-muted">IP</span><strong>${esc(p.ip)}</strong></div>
      <div class="ops-card ops-stat"><span class="ops-muted">等级</span><strong>${esc(severityText[p.severity] || p.severity)}</strong></div>
      <div class="ops-card ops-stat"><span class="ops-muted">请求数</span><strong>${esc(p.requests)}</strong></div>
      <div class="ops-card ops-stat"><span class="ops-muted">最后出现</span><strong style="font-size:18px">${esc(p.last_seen)}</strong></div>
    </div>
    <p><strong>归属判断：</strong>${esc(p.actor)}</p>
    <p><strong>目的判断：</strong>${esc(p.intent)}</p>
    <p><strong>行为摘要：</strong>${esc(p.behavior_summary)}</p>
    <p><strong>命中规则：</strong>${esc((p.rules || []).join(", "))}</p>
    <p><strong>封禁建议文本：</strong><code>${esc(p.block_suggestion)}</code></p>
    <h3>Top 路径</h3>
    ${table(["路径", "次数"], (p.top_paths || []).map((row) => `<tr><td>${esc(row.path)}</td><td>${esc(row.count)}</td></tr>`))}
    <h3>最近请求</h3>
    ${table(["时间", "方法", "路径", "状态", "规则"], (p.recent_requests || []).map((row) => `<tr><td>${esc(row.time)}</td><td>${esc(row.method)}</td><td>${esc(row.path)}</td><td>${esc(row.status)}</td><td>${esc((row.rules || []).join(", "))}</td></tr>`))}`;
}

async function loadSecurity() {
  const overview = await api("/security/overview");
  $("security-summary").innerHTML = [
    ["最近 1 分钟请求", overview.requests_1m],
    ["最近 5 分钟请求", overview.requests_5m],
    ["今日请求样本", overview.requests_today],
    ["今日异常请求", overview.suspicious_today],
    ["今日 4xx", overview.errors_4xx],
    ["今日 5xx", overview.errors_5xx],
    ["登录失败", overview.login_failures],
    ["限流次数", overview.rate_limited],
    ["待处理事件", overview.open_events],
  ].map(([label, value]) => `<div class="ops-card ops-stat"><span class="ops-muted">${label}</span><strong>${esc(value)}</strong></div>`).join("");
  $("security-top").innerHTML = `
    <p class="ops-muted">异步日志队列 ${esc(overview.queue_size)}，丢弃统计 ${esc(JSON.stringify(overview.queue_dropped || {}))}</p>
    <div class="ops-form-grid">
      <div><h3>Top IP</h3>${table(["IP", "请求"], (overview.top_ips || []).map((row) => `<tr><td>${esc(row.ip)}</td><td>${esc(row.total)}</td></tr>`))}</div>
      <div><h3>Top 路径</h3>${table(["路径", "请求"], (overview.top_paths || []).map((row) => `<tr><td>${esc(row.path)}</td><td>${esc(row.total)}</td></tr>`))}</div>
      <div><h3>异常路径</h3>${table(["路径", "请求"], (overview.suspicious_paths || []).map((row) => `<tr><td>${esc(row.path)}</td><td>${esc(row.total)}</td></tr>`))}</div>
    </div>`;
  await Promise.all([loadSecurityEvents(), loadSecurityLogs(), loadSecurityIpRules()]);
}

async function loadSecurityEvents() {
  const params = new URLSearchParams({ hours: $("security-event-hours")?.value || "168", event_type: $("security-event-type")?.value.trim() || "", severity: $("security-event-severity")?.value || "", status: $("security-event-status")?.value || "", ip: $("security-event-ip")?.value.trim() || "", page_size: "80" });
  const data = await api(`/security/events?${params}`);
  $("security-events").innerHTML = table(["时间", "等级", "类型", "IP", "请求", "状态", "操作"], (data.events || []).map((event) => `<tr>
    <td>${esc(event.created_at)}</td><td>${riskBadge(event.severity)}</td><td>${esc(event.event_type)}</td><td>${esc(event.ip || "")}</td>
    <td>${esc(event.method || "")} ${esc(event.path || "")}<br><span class="ops-muted">${esc(event.message || "")}</span></td><td>${esc(event.status)}</td>
    <td><div class="ops-actions"><button class="ops-btn secondary" data-security-event="${event.id}" data-security-status="resolved">解决</button><button class="ops-btn secondary" data-security-event="${event.id}" data-security-status="ignored">忽略</button></div></td>
  </tr>`));
}

async function loadSecurityLogs() {
  const params = new URLSearchParams({ hours: $("security-log-hours")?.value || "24", ip: $("security-log-ip")?.value.trim() || "", path: $("security-log-path")?.value.trim() || "", status_code: $("security-log-status")?.value.trim() || "", is_suspicious: $("security-log-suspicious")?.value || "", page_size: "80" });
  const data = await api(`/security/request-logs?${params}`);
  $("security-logs").innerHTML = table(["时间", "IP", "请求", "状态", "耗时", "异常原因"], (data.logs || []).map((row) => `<tr>
    <td>${esc(row.created_at)}</td><td>${esc(row.ip || "")}</td><td>${esc(row.method)} ${esc(row.path)}<br><span class="ops-muted">${esc(row.query || "")}</span></td>
    <td>${esc(row.status_code)}</td><td>${esc(row.response_time_ms)}ms</td><td>${esc(row.suspicious_reason || "")}</td>
  </tr>`));
}

async function loadSecurityIpRules() {
  const data = await api("/security/ip-rules");
  $("security-ip-rules").innerHTML = table(["IP", "类型", "备注", "过期", "更新时间"], (data.rules || []).map((row) => `<tr><td>${esc(row.ip)}</td><td>${esc(row.rule_type)}</td><td>${esc(row.reason || "")}</td><td>${esc(row.expires_at || "长期")}</td><td>${esc(row.updated_at)}</td></tr>`));
}

async function loadPlans() {
  const data = await api("/payment-config");
  opsState.plans = data.plans || [];
  $("plans-editor").innerHTML = `
    <div class="ops-form-grid">${opsState.plans.map((p, index) => `
      <div class="ops-plan" data-plan-index="${index}">
        <input class="ops-input" data-field="id" value="${esc(p.id)}" placeholder="id">
        <input class="ops-input" data-field="name" value="${esc(p.name)}" placeholder="名称">
        <input class="ops-input" data-field="money" value="${esc(p.money)}" placeholder="金额">
        <input class="ops-input" data-field="credits" value="${esc(p.credits)}" placeholder="点数">
      </div>`).join("")}</div>
    <label class="ops-muted"><input type="checkbox" id="disable-alipay" ${(data.disabled_types || []).includes("alipay") ? "checked" : ""}> 暂停支付宝入口</label>
    <p class="ops-muted">支付宝配置状态：${data.alipay_enabled ? "已配置" : "未配置"}</p>`;
}

function setLicenseTokenStatus(text, bad = false) {
  const el = $("license-token-status");
  if (!el) return;
  el.textContent = text;
  el.classList.toggle("empty", bad);
  el.style.color = bad ? "#fecdd3" : "#8ff7e8";
}

function renderLicenseDashboard(licenses = [], usage = [], activations = []) {
  const totalBalance = licenses.reduce((sum, item) => sum + Number(item.balance_credits || 0), 0);
  const totalTokens = licenses.reduce((sum, item) => sum + Number(item.total_tokens || 0), 0);
  const spentCredits = licenses.reduce((sum, item) => sum + Number(item.total_spent_credits || 0), 0);
  const lowBalance = licenses.filter((item) => Number(item.balance_credits || 0) < 10).length;
  const failed = usage.filter((item) => !item.success).length;
  $("license-summary").innerHTML = [
    ["授权客户", licenses.length],
    ["总剩余积分", totalBalance.toFixed(3)],
    ["累计 Token", totalTokens],
    ["累计消耗积分", spentCredits.toFixed(3)],
    ["低余额客户", lowBalance],
    ["已激活机器", activations.length],
    ["近期失败调用", failed],
  ].map(([label, value]) => `<div class="ops-config-status-card"><span>${esc(label)}</span><strong>${esc(value)}</strong></div>`).join("");
}

function licenseStatusBadge(item) {
  const low = Number(item.balance_credits || 0) < 10;
  if (item.status !== "active") return `<span class="ops-badge bad">${esc(item.status)}</span>`;
  if (low) return '<span class="ops-badge bad">余额偏低</span>';
  return '<span class="ops-badge">正常</span>';
}

function renderLicenseSummary(license, usage = []) {
  if (!license) {
    $("license-detail").innerHTML = '<p class="ops-muted">输入完整授权码，或点击列表中的“详情”，可查看客户余额、Token 消耗、最近设备调用与失败原因。</p>';
    return;
  }
  const successCount = usage.filter((row) => row.success).length;
  const failedCount = usage.length - successCount;
  const devices = [...new Set(usage.map((row) => row.device_id).filter(Boolean))];
  const features = [...new Set(usage.map((row) => row.feature).filter(Boolean))];
  $("license-detail").innerHTML = `
    <div class="ops-grid">
      <div class="ops-card ops-stat"><span class="ops-muted">客户</span><strong style="font-size:20px">${esc(license.customer_name || "-")}</strong></div>
      <div class="ops-card ops-stat"><span class="ops-muted">剩余积分</span><strong>${Number(license.balance_credits || 0).toFixed(3)}</strong></div>
      <div class="ops-card ops-stat"><span class="ops-muted">累计 Token</span><strong>${esc(license.total_tokens || 0)}</strong></div>
      <div class="ops-card ops-stat"><span class="ops-muted">最近调用</span><strong>${esc(usage.length)}</strong></div>
    </div>
    <div class="ops-config-group">
      <p><strong>授权码：</strong><code>${esc(license.license_key)}</code></p>
      <p><strong>状态：</strong>${licenseStatusBadge(license)} <span class="ops-muted">创建 ${esc(license.created_at || "")}，更新 ${esc(license.updated_at || "")}</span></p>
      <p><strong>累计消耗：</strong>${Number(license.total_spent_credits || 0).toFixed(3)} 积分，输入 ${esc(license.total_input_tokens || 0)} Token，输出 ${esc(license.total_output_tokens || 0)} Token</p>
      <p><strong>最近设备：</strong>${esc(devices.slice(0, 6).join(", ") || "暂无")} <span class="ops-muted">成功 ${successCount} 次，失败 ${failedCount} 次</span></p>
      <p><strong>最近功能：</strong>${esc(features.slice(0, 8).join(", ") || "暂无")}</p>
    </div>
    <div class="ops-toolbar">
      <input class="ops-input" id="recharge-license-amount" placeholder="充值积分">
      <button class="ops-btn" data-recharge-license="${esc(license.license_key)}">充值</button>
    </div>
    <h3>该授权码最近调用</h3>
    ${renderUsageTable(usage || [])}`;
}

function renderMachineTable(activations = []) {
  return table(["机器 / 客户", "授权码 / 机器余额", "消耗倍率", "在线 / 次数", "状态", "操作"], (activations || []).map((row) => {
    const disabled = Number(row.disabled || 0);
    const mult = Number(row.rate_multiplier || 1);
    return `
    <tr>
      <td><code>${esc(row.machine_id || "")}</code><br><span class="ops-muted">${esc(row.customer_name || "-")} · ${esc(row.os_name || "")} ${esc(row.app_version || "")}<br>host ${esc(row.hostname_hash || "")}</span></td>
      <td><code>${esc(row.license_key || "")}</code><br><strong>${Number(row.balance_credits || 0).toFixed(3)}</strong> 积分</td>
      <td><input class="ops-input" data-multiplier-input data-license="${esc(row.license_key || "")}" data-machine="${esc(row.machine_id || "")}" value="${mult.toFixed(2)}" style="width:72px" type="number" step="0.1" min="0.1" max="10">
          <button class="ops-btn secondary" data-set-multiplier="1" data-license="${esc(row.license_key || "")}" data-machine="${esc(row.machine_id || "")}">保存倍率</button></td>
      <td>${esc(row.last_seen || "")}<br><span class="ops-muted">${esc(row.verify_count || 0)} 次 · ${esc(row.last_ip || "")}</span><br><span class="ops-muted">首次 ${esc(row.first_seen || "")}</span></td>
      <td>${disabled ? '<span class="ops-badge bad">已停用</span>' : '<span class="ops-badge">正常</span>'}</td>
      <td><div class="ops-actions">
        <button class="ops-btn secondary" data-adjust-credits="1" data-license="${esc(row.license_key || "")}" data-machine="${esc(row.machine_id || "")}" data-customer="${esc(row.customer_name || "")}">调整积分</button>
        <button class="ops-btn secondary" data-toggle-machine="1" data-license="${esc(row.license_key || "")}" data-machine="${esc(row.machine_id || "")}" data-disabled="${disabled}">${disabled ? "启用" : "停用"}</button>
      </div></td>
    </tr>`;
  }));
}

function renderUsageTable(usage) {
  return table(["时间", "授权码", "设备", "平台/功能", "Token", "积分", "结果"], (usage || []).map((row) => `
    <tr>
      <td>${esc(row.created_at)}</td>
      <td><code>${esc(row.license_key)}</code></td>
      <td>${esc(row.device_id || "")}</td>
      <td>${esc(row.platform || "")}<br><span class="ops-muted">${esc(row.feature || "")}</span></td>
      <td>${esc(row.total_tokens || 0)}<br><span class="ops-muted">in ${esc(row.input_tokens || 0)} / out ${esc(row.output_tokens || 0)}</span></td>
      <td>${Number(row.spent_credits || 0).toFixed(3)}</td>
      <td>${row.success ? '<span class="ops-badge">成功</span>' : `<span class="ops-badge bad">失败</span><br><span class="ops-muted">${esc(row.error || "")}</span>`}</td>
    </tr>`));
}

async function loadLicenses() {
  const saved = sessionStorage.getItem("social_ai_admin_token") || "";
  if ($("license-admin-token") && saved) $("license-admin-token").value = saved;
  if (!saved && !$("license-admin-token")?.value.trim()) {
    setLicenseTokenStatus("未验证 AI 管理 Token。请先填写 Token 后刷新授权码。", true);
    $("license-summary").innerHTML = "";
    $("licenses-table").innerHTML = "";
    $("license-usage-table").innerHTML = "";
    if ($("license-machines-table")) $("license-machines-table").innerHTML = "";
    renderLicenseSummary(null);
    return;
  }
  let data;
  let usage;
  let activations;
  try {
    data = await licenseApi("/admin/licenses");
    usage = await licenseApi("/admin/usage?limit=100");
    activations = await licenseApi("/admin/activations?limit=500");
    setLicenseTokenStatus("AI 管理 Token 已验证，授权码数据已同步。");
  } catch (err) {
    setLicenseTokenStatus(err.message, true);
    $("license-summary").innerHTML = "";
    throw err;
  }
  const q = ($("license-search")?.value || "").trim().toLowerCase();
  const allLicenses = data.licenses || [];
  const allUsage = usage.usage || [];
  const allActivations = activations.activations || [];
  renderLicenseDashboard(allLicenses, allUsage, allActivations);
  const licenses = allLicenses.filter((item) => !q || String(item.license_key || "").toLowerCase().includes(q) || String(item.customer_name || "").toLowerCase().includes(q));
  $("licenses-table").innerHTML = table(["客户", "授权码", "余额", "Token/消耗", "时间", "状态", "操作"], licenses.map((item) => `
    <tr>
      <td>${esc(item.customer_name || "-")}<br><span class="ops-muted">${esc(item.created_at || "")}</span></td>
      <td><code>${esc(item.license_key)}</code></td>
      <td>${Number(item.balance_credits || 0).toFixed(3)}</td>
      <td>${esc(item.total_tokens || 0)}<br><span class="ops-muted">${Number(item.total_spent_credits || 0).toFixed(3)} 积分</span></td>
      <td><span class="ops-muted">更新 ${esc(item.updated_at || "")}</span></td>
      <td>${licenseStatusBadge(item)}</td>
      <td><div class="ops-actions"><button class="ops-btn secondary" data-license-detail="${esc(item.license_key)}">详情</button></div></td>
    </tr>`));
  $("license-usage-table").innerHTML = renderUsageTable(allUsage);
  if ($("license-machines-table")) $("license-machines-table").innerHTML = renderMachineTable(allActivations);
  if (!$("license-detail").innerHTML.trim()) renderLicenseSummary(null);
}

async function loadLicenseDetail(licenseKey) {
  const data = await licenseApi(`/admin/licenses/${encodeURIComponent(licenseKey)}`);
  renderLicenseSummary(data.license, data.usage || []);
  if ($("license-machines-table")) $("license-machines-table").innerHTML = renderMachineTable(data.activations || []);
}

async function createLicense() {
  const customer_name = $("new-license-customer").value.trim();
  const credits = Number($("new-license-credits").value || "0");
  const license_key = $("new-license-key").value.trim() || undefined;
  if (!customer_name) throw new Error("请填写客户名称");
  if (!Number.isFinite(credits) || credits < 0) throw new Error("初始积分不正确");
  const data = await licenseApi("/admin/licenses", { method: "POST", body: JSON.stringify({ customer_name, credits, license_key }) });
  $("license-search").value = data.license_key;
  await loadLicenseDetail(data.license_key);
  await loadLicenses();
}

async function rechargeLicense(licenseKey) {
  const amount = Number($("recharge-license-amount")?.value || "0");
  if (!Number.isFinite(amount) || amount <= 0) throw new Error("请填写大于 0 的充值积分");
  await licenseApi(`/admin/licenses/${encodeURIComponent(licenseKey)}/recharge`, { method: "POST", body: JSON.stringify({ credits: amount }) });
  await loadLicenseDetail(licenseKey);
  await loadLicenses();
}

async function loadAudit() {
  const q = encodeURIComponent($("audit-q").value.trim());
  const data = await api(`/audit-logs?q=${q}&page_size=80`);
  $("audit-table").innerHTML = table(["时间", "操作", "对象", "人员", "摘要"], data.logs.map((l) => `
    <tr><td>${esc(l.created_at)}</td><td>${esc(l.action)}</td><td>${esc(l.target_type)} #${esc(l.target_id)}</td><td>${esc(l.admin_name || l.admin_user_id)}<br><span class="ops-muted">${esc(l.ip || "")}</span></td><td><span class="ops-muted">${esc(l.summary_json || "")}</span></td></tr>`));
}

async function loadPanel(panel) {
  if (panel === "users") return loadUsers();
  if (panel === "payments") return loadPayments();
  if (panel === "jobs") return loadJobs();
  if (panel === "traffic") return loadTraffic();
  if (panel === "security") return loadSecurity();
  if (panel === "plans") return loadPlans();
  if (panel === "licenses") return loadLicenses();
  if (panel === "audit") return loadAudit();
}

function bindActions() {
  document.addEventListener("click", async (event) => {
    const target = event.target.closest("button");
    if (!target) return;
    try {
      if (target.dataset.load) await loadPanel(target.dataset.load);
      if (target.id === "refresh-all") await loadPanel(document.querySelector(".ops-panel.active")?.dataset.panel || "users");
      if (target.dataset.credit) {
        const amount = Number(prompt("输入加扣点数量，扣点请填负数"));
        if (!Number.isFinite(amount) || amount === 0) return;
        const reason = prompt("请输入原因") || "operator adjustment";
        await api(`/users/${target.dataset.credit}/credits`, { method: "POST", body: JSON.stringify({ amount, reason }) });
        await loadUsers();
      }
      if (target.dataset.status) {
        await api(`/users/${target.dataset.status}/status`, { method: "POST", body: JSON.stringify({ disabled: target.dataset.disabled === "1" }) });
        await loadUsers();
      }
      if (target.dataset.reset) {
        if (!confirm("确认重置该用户密码？")) return;
        const data = await api(`/users/${target.dataset.reset}/reset-password`, { method: "POST", body: "{}" });
        alert(`临时密码：${data.temporary_password}`);
      }
      if (target.dataset.notePayment) {
        const note = prompt("订单备注") || "";
        await api(`/payments/${target.dataset.notePayment}/note`, { method: "POST", body: JSON.stringify({ note }) });
        await loadPayments();
      }
      if (target.dataset.closePayment) {
        const note = prompt("关闭原因") || "operator closed";
        await api(`/payments/${target.dataset.closePayment}/close`, { method: "POST", body: JSON.stringify({ note }) });
        await loadPayments();
      }
      if (target.dataset.jobAction) {
        if (!confirm(`确认执行 ${target.dataset.jobAction}？`)) return;
        await api(`/jobs/${target.dataset.job}/${target.dataset.jobAction}`, { method: "POST", body: "{}" });
        await loadJobs();
      }
      if (target.id === "refresh-traffic") await loadTraffic();
      if (target.dataset.trafficIp) await loadTrafficIp(target.dataset.trafficIp);
      if (target.id === "refresh-security") await loadSecurity();
      if (target.id === "search-security-events") await loadSecurityEvents();
      if (target.id === "search-security-logs") await loadSecurityLogs();
      if (target.dataset.securityEvent) {
        await api(`/security/events/${target.dataset.securityEvent}`, { method: "POST", body: JSON.stringify({ status: target.dataset.securityStatus }) });
        await loadSecurityEvents();
      }
      if (target.id === "save-security-rule") {
        await api("/security/ip-rules", { method: "POST", body: JSON.stringify({ ip: $("security-rule-ip").value.trim(), rule_type: $("security-rule-type").value, reason: $("security-rule-reason").value.trim(), expires_at: $("security-rule-expires").value.trim() }) });
        await loadSecurityIpRules();
      }
      if (target.id === "save-plans") await savePlans();
      if (target.id === "save-license-token") {
        sessionStorage.setItem("social_ai_admin_token", $("license-admin-token").value.trim());
        await loadLicenses();
        message("AI 管理 Token 已保存并验证");
      }
      if (target.id === "clear-license-token") {
        sessionStorage.removeItem("social_ai_admin_token");
        if ($("license-admin-token")) $("license-admin-token").value = "";
        setLicenseTokenStatus("AI 管理 Token 已清除。请重新填写后刷新授权码。", true);
        $("license-summary").innerHTML = "";
        $("licenses-table").innerHTML = "";
        $("license-usage-table").innerHTML = "";
        if ($("license-machines-table")) $("license-machines-table").innerHTML = "";
        renderLicenseSummary(null);
      }
      if (target.id === "refresh-licenses") await loadLicenses();
      if (target.id === "search-license") {
        const q = $("license-search").value.trim();
        if (q.startsWith("saa_")) await loadLicenseDetail(q);
        else await loadLicenses();
      }
      if (target.id === "create-license") await createLicense();
      if (target.dataset.licenseDetail) await loadLicenseDetail(target.dataset.licenseDetail);
      if (target.dataset.rechargeLicense) await rechargeLicense(target.dataset.rechargeLicense);
      // ===== 已激活机器：保存消耗倍率 =====
      if (target.dataset.setMultiplier) {
        const { license, machine } = target.dataset;
        const wrap = target.closest("td");
        const input = wrap && wrap.querySelector("[data-multiplier-input]");
        const val = Number(input ? input.value : "");
        if (!Number.isFinite(val) || val <= 0) throw new Error("倍率必须为大于 0 的数字");
        await licenseApi(`/admin/activations/${encodeURIComponent(license)}/${encodeURIComponent(machine)}`, { method: "PATCH", body: JSON.stringify({ rate_multiplier: val }) });
        await loadLicenses();
        message(`倍率已设为 ${val}`);
        return;
      }
      // ===== 已激活机器：调整积分(可正可负) =====
      if (target.dataset.adjustCredits) {
        const { license, machine, customer } = target.dataset;
        const raw = prompt(`调整 ${customer || ""} 的积分\n请输入金额，正数=增加，负数=扣减（如 10 或 -5）`);
        if (raw === null) return;
        const amount = Number(raw);
        if (!Number.isFinite(amount) || amount === 0) throw new Error("金额需为非 0 数字");
        const reason = (prompt("请输入调整原因（必填）") || "").trim();
        if (!reason) throw new Error("原因必填");
        const data = await licenseApi(`/admin/licenses/${encodeURIComponent(license)}/adjust`, { method: "POST", body: JSON.stringify({ amount, reason, machine_id: machine }) });
        await loadLicenses();
        message(`积分已调整：${data.balance_before} → ${data.balance_after}`);
        return;
      }
      // ===== 已激活机器：停用 / 启用 =====
      if (target.dataset.toggleMachine) {
        const { license, machine } = target.dataset;
        const willDisable = target.dataset.disabled !== "1";
        if (willDisable && !confirm("确认停用该机器？停用后该机器的 AI 调用将被拒绝。")) return;
        await licenseApi(`/admin/activations/${encodeURIComponent(license)}/${encodeURIComponent(machine)}`, { method: "PATCH", body: JSON.stringify({ disabled: willDisable ? 1 : 0 }) });
        await loadLicenses();
        message(willDisable ? "机器已停用" : "机器已启用");
        return;
      }
      message("操作完成");
    } catch (err) {
      message(err.message, true);
    }
  });
}

async function savePlans() {
  const plans = [...document.querySelectorAll("[data-plan-index]")].map((card) => {
    const item = {};
    card.querySelectorAll("[data-field]").forEach((field) => item[field.dataset.field] = field.value);
    return item;
  });
  const disabled_types = $("disable-alipay")?.checked ? ["alipay", "wxpay", "qqpay"] : ["wxpay", "qqpay"];
  await api("/payment-config", { method: "POST", body: JSON.stringify({ plans, disabled_types }) });
}

async function bootstrap() {
  renderNav();
  bindActions();
  const status = await fetch("/api/status");
  const data = await status.json();
  if (!data.authenticated || !data.user?.is_admin) {
    document.body.innerHTML = "";
    return;
  }
  $("ops-session").textContent = `${data.user.name} · secure session`;
  await loadUsers();
}

bootstrap().catch((err) => {
  document.body.innerHTML = "";
  console.error(err);
});
