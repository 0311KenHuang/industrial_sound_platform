const $ = (id) => document.getElementById(id);
const AUTH_TOKEN_KEY = 'soundnet_token';
const nativeFetch = window.fetch.bind(window);
let authToken = localStorage.getItem(AUTH_TOKEN_KEY);
let authUser = null;
let appStarted = false;
let overview = {devices: [], alerts: [], work_orders: [], diagnoses: [], summary: {}, model: {}, faults: {}};
let trend = [], distribution = {health_status: [], fault_types: [], alert_levels: []}, editingDeviceId = null, editingMaintainerId = null;
let maintainers = [], recheckWorkOrderId = null;
const viewTitles = {overview:'工业声纹监控台', devices:'设备声纹档案', diagnosis:'智能声纹诊断', alerts:'告警中心', orders:'运维工单', maintainers:'维检人员'};
let currentView = 'overview';
let refreshTimer = null;

let toastTimer = null;
function toast(message, kind = 'info') { const el = $('toast'); if (!el) return; el.textContent = message; el.classList.remove('info','success','error','warning','show'); el.classList.add(kind, 'show'); el.setAttribute('role', kind === 'error' ? 'alert' : 'status'); el.setAttribute('aria-live', kind === 'error' ? 'assertive' : 'polite'); clearTimeout(toastTimer); toastTimer = setTimeout(() => el.classList.remove('show'), 3400); }
function clearAuth() { authToken = null; authUser = null; localStorage.removeItem(AUTH_TOKEN_KEY); }
function showAuthGate(message = '请登录后使用工业声纹监控台') { const gate = $('auth-gate'); if (!gate) return; if ($('auth-message')) $('auth-message').textContent = message; gate.classList.remove('hidden'); setTimeout(() => $('login-username')?.focus(), 0); }
function hideAuthGate() { $('auth-gate')?.classList.add('hidden'); }
async function apiFetch(url, options = {}) {
  const headers = new Headers(options.headers || {});
  if (authToken) headers.set('Authorization', `Bearer ${authToken}`);
  const response = await nativeFetch(url, {...options, headers});
  if (response.status === 401 && !String(url).startsWith('/api/auth/')) { clearAuth(); showAuthGate('登录已失效，请重新登录'); }
  return response;
}
window.fetch = apiFetch;
function esc(value) { return String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c])); }
function idArg(value) { return encodeURIComponent(value); }
function healthClass(value) { return value >= 80 ? 'health-green' : value >= 60 ? 'health-orange' : 'health-red'; }
function statusLabel(status) { return {online:'正常', warning:'关注', offline:'离线'}[status] || status; }
function pillClass(value) { return ['严重','紧急','重度'].includes(value) ? 'danger' : ['处理中','警告','中度','高'].includes(value) ? 'warning' : 'success'; }
function deviceName(id) { return overview.devices.find(x => x.id === id)?.name || id; }
function formatToday() { const parts = Object.fromEntries(new Intl.DateTimeFormat('zh-CN', {year:'numeric', month:'2-digit', day:'2-digit', weekday:'long'}).formatToParts(new Date()).map(item => [item.type, item.value])); return `${parts.year} 年 ${parts.month} 月 ${parts.day} 日 · ${parts.weekday}`; }
function formatGreeting(date = new Date()) { const hour = date.getHours(); return hour < 5 ? '晚上好' : hour < 12 ? '早上好' : hour < 14 ? '中午好' : hour < 19 ? '下午好' : '晚上好'; }
function updateToday() { if ($('today-label')) $('today-label').textContent = formatToday(); if ($('greeting-label')) $('greeting-label').textContent = formatGreeting(); }
function updateSyncStatus(partial = false) { if (!$('sync-label')) return; $('sync-label').textContent = partial ? '部分数据同步失败' : `最近同步 ${new Date().toLocaleTimeString('zh-CN', {hour:'2-digit', minute:'2-digit', second:'2-digit'})}`; }

function renderDistribution(target, items, labels = {}) {
  const total = items.reduce((sum, item) => sum + item.value, 0) || 1;
  $(target).innerHTML = items.length ? items.map(item => `<div class="distribution-row"><span class="distribution-name">${esc(labels[item.name] || item.label || item.name)}</span><span class="distribution-bar"><i style="width:${Math.max(4, item.value / total * 100)}%"></i></span><span class="distribution-value">${item.value}</span></div>`).join('') : '<span class="muted">暂无数据</span>';
}

function renderOverview() {
  const devices = overview.devices, summary = overview.summary || {}, openAlerts = overview.alerts.filter(x => x.status !== '已关闭');
  $('device-count').textContent = summary.device_total ?? devices.length; $('online-count').textContent = summary.normal_devices ?? devices.filter(x => x.status === 'online').length;
  $('diagnosis-count').textContent = summary.today_diagnoses ?? 0; $('alert-count').textContent = summary.active_alerts ?? openAlerts.length; $('open-alert-count').textContent = summary.active_alerts ?? openAlerts.length; $('alert-badge').textContent = summary.active_alerts ?? openAlerts.length; $('order-count').textContent = summary.open_work_orders ?? 0;
  $('model-detail').textContent = overview.model.ready ? `${overview.model.samples} 条本地样本已学习 · ${overview.model.backend}` : '点击右上角开始训练模型';
  $('device-list').innerHTML = devices.map(x => `<div class="device-item"><div class="device-symbol">⌁</div><div><div class="device-name">${esc(x.name)}</div><div class="device-meta">${esc(x.wind_farm || x.device_type)} · ${esc(x.city || '')}${x.county ? ' · ' + esc(x.county) : ''} · ${statusLabel(x.status)}</div></div><div class="health ${healthClass(x.health)}"><div>${x.status === 'offline' ? '—' : x.health + '%'}</div><div class="health-bar"><i style="width:${x.health}%"></i></div></div></div>`).join('');
  $('alert-list').innerHTML = overview.alerts.length ? overview.alerts.slice(0, 6).map(x => `<div class="alert-item"><i class="severity-dot"></i><div><div class="alert-title">${esc(x.title)}</div><span class="alert-meta">${esc(x.created_at)} · ${esc(x.level)} · ${esc(x.status)}</span></div><button class="pill ${x.status === '已关闭' ? 'green' : ''}" onclick="handleAlert(${x.id}, '${x.status === '未处理' ? '处理中' : '已关闭'}')">${x.status === '未处理' ? '确认告警' : x.status === '已关闭' ? '已关闭' : '关闭告警'}</button></div>`).join('') : '<div class="muted">暂无告警，设备运行平稳。</div>';
  const values = trend.length ? trend.map(x => Math.round(x.detection_rate * 100)) : [18,31,24,46,40,57,openAlerts.length * 14];
  $('trend-bars').innerHTML = values.map((v, i) => `<div class="bar-col"><div class="bar" style="height:${Math.max(4, v * 1.25)}px"></div><span>${trend[i]?.date?.slice(5) || ['周四','周五','周六','周日','周一','周二','今日'][i]}</span></div>`).join('');
  renderDistribution('health-distribution', distribution.health_status, {online:'正常', warning:'关注', offline:'离线'}); renderDistribution('fault-distribution', distribution.fault_types); renderDistribution('level-distribution', distribution.alert_levels);
}

function populateSelectors() {
  const devices = overview.devices, options = devices.map(x => `<option value="${esc(x.id)}">${esc(x.name)} · ${esc(x.id)}</option>`).join('');
  $('device-select').innerHTML = options; $('history-device-filter').innerHTML = '<option value="">全部设备</option>' + options; $('manual-order-device').innerHTML = options;
  const maintainerOptions = '<option value="">待分配</option>' + maintainers.filter(x => x.is_active).map(x => `<option value="${esc(x.id)}">${esc(x.name)}${x.team ? ' · ' + esc(x.team) : ''}</option>`).join('');
  if ($('manual-order-assignee')) $('manual-order-assignee').innerHTML = maintainerOptions;
  $('history-fault-filter').innerHTML = '<option value="">全部故障</option>' + Object.entries(overview.faults || {}).filter(([key]) => key !== 'normal').map(([key, value]) => `<option value="${esc(key)}">${esc(value)}</option>`).join('');
}

async function refreshCore(options = {}) {
  const silent = options.silent === true;
  const request = (url) => fetch(url).then(response => { if (!response.ok) throw new Error(`${url} · ${response.status}`); return response.json(); });
  const responses = await Promise.allSettled([request('/api/overview'), request('/api/dashboard/trend?days=7'), request('/api/dashboard/distribution'), request('/api/maintainers?include_inactive=false&page_size=200')]);
  const failed = [];
  if (responses[0].status === 'fulfilled') overview = responses[0].value; else failed.push('总览数据');
  if (responses[1].status === 'fulfilled') trend = responses[1].value; else failed.push('趋势数据');
  if (responses[2].status === 'fulfilled') distribution = responses[2].value; else failed.push('分布数据');
  if (responses[3].status === 'fulfilled') maintainers = responses[3].value.items || []; else failed.push('维检人员');
  populateSelectors(); renderOverview();
  updateSyncStatus(failed.length > 0);
  if (failed.length && !silent) toast(`${failed.join('、')}暂时无法加载`);
  return {failed};
}

async function goView(view, updateHash = true) {
  if (!viewTitles[view]) view = 'overview';
  const changed = currentView !== view;
  currentView = view;
  document.querySelectorAll('.view').forEach(section => section.classList.toggle('active', section.id === `view-${view}`));
  document.querySelectorAll('[data-view]').forEach(link => {
    const active = link.dataset.view === view;
    link.classList.toggle('active', active);
    if (active) link.setAttribute('aria-current', 'page'); else link.removeAttribute('aria-current');
  });
  $('page-title').textContent = viewTitles[view];
  document.title = `${viewTitles[view]} · 声网先知`;
  if (updateHash && location.hash.slice(1) !== view) history.pushState({view}, '', `#${view}`);
  if (changed) window.scrollTo({top:0, behavior:'auto'});
  const loaders = {devices: loadDevices, diagnosis: loadDiagnosisHistory, alerts: loadAlerts, orders: loadOrders, maintainers: loadMaintainers};
  if (loaders[view]) {
    try { await loaders[view](); } catch (error) { toast(`${viewTitles[view]}加载失败，请稍后重试`); console.error(error); }
  }
}

async function loadDevices() {
  const params = new URLSearchParams({page:1, page_size:100}); const q = $('device-search').value.trim(); const status = $('device-status-filter').value; if(q) params.set('q', q); if(status) params.set('status', status);
  const data = await (await fetch(`/api/devices?${params}`)).json(); $('devices-table').innerHTML = data.items.length ? data.items.map(x => `<tr><td><b>${esc(x.name)}</b><small>${esc(x.id)} · ${esc(x.device_type)}</small></td><td><b>${esc(x.wind_farm || '未填写')}</b><small>${esc(x.location)}${x.city ? ' · ' + esc(x.city) : ''}${x.county ? ' · ' + esc(x.county) : ''}</small></td><td><b>${esc(x.model)}</b><small>${x.rated_power_kw ? x.rated_power_kw + ' kW' : '额定功率待补'}</small></td><td><span class="status-dot-inline ${healthClass(x.health)}"></span>${statusLabel(x.status)} <b>${x.health || 0}%</b></td><td>${esc(x.last_seen)}</td><td><button class="table-link" onclick="showDevice('${idArg(x.id)}')">详情</button><button class="table-link" onclick="editDevice('${idArg(x.id)}')">编辑</button><button class="table-link danger-link" onclick="deleteDevice('${idArg(x.id)}')">停用</button></td></tr>`).join('') : '<tr><td colspan="6" class="empty-cell">没有符合条件的设备</td></tr>';
}
async function showDevice(encodedId) { const id = decodeURIComponent(encodedId); const x = await (await fetch(`/api/devices/${encodeURIComponent(id)}`)).json(); const panel = $('device-detail-panel'); panel.classList.remove('hidden'); panel.innerHTML = `<div class="detail-head"><div><div class="eyebrow">ASSET DETAIL · ${esc(x.id)}</div><h3>${esc(x.name)}</h3><p class="muted">${esc(x.wind_farm)} · ${esc(x.location)}</p></div><button class="ghost-button" onclick="$('device-detail-panel').classList.add('hidden')">收起</button></div><div class="detail-grid"><div><span>设备类型</span><b>${esc(x.device_type)}</b></div><div><span>设备型号</span><b>${esc(x.model)}</b></div><div><span>额定功率</span><b>${x.rated_power_kw || 0} kW</b></div><div><span>投运日期</span><b>${esc(x.install_date || '未填写')}</b></div></div><h4>历史诊断（最近 20 条）</h4><div class="mini-history">${x.diagnostics.length ? x.diagnostics.map(d => `<div><span>${esc(d.created_at)}</span><b>${esc(overview.faults[d.fault] || d.fault)}</b><em class="pill ${pillClass(d.severity)}">${esc(d.severity)}</em></div>`).join('') : '<span class="muted">暂无诊断记录</span>'}</div>`; panel.scrollIntoView({behavior:'smooth',block:'center'}); }
function modalField(form, name, value) { if(form.elements[name]) form.elements[name].value = value ?? ''; }
function openDeviceModal(device = null) { editingDeviceId = device?.id || null; const form = $('device-form'); form.reset(); form.elements.id.readOnly = Boolean(device); $('device-modal-title').textContent = device ? '编辑设备档案' : '新增设备'; if(device) Object.keys(device).forEach(key => modalField(form, key, key === 'rated_params' ? '' : device[key])); $('device-modal').classList.remove('hidden'); }
async function editDevice(encodedId) { const device = await (await fetch(`/api/devices/${decodeURIComponent(encodedId)}`)).json(); openDeviceModal(device); }
async function deleteDevice(encodedId) { const id = decodeURIComponent(encodedId); if(!confirm(`确认停用设备“${deviceName(id)}”吗？历史诊断和工单会保留。`)) return; const r = await fetch(`/api/devices/${encodeURIComponent(id)}`, {method:'DELETE'}); if(r.ok){toast('设备已停用，历史记录已保留'); await refreshCore(); await loadDevices();} else { let data={}; try{data=await r.json()}catch{} toast(data.detail || `设备停用失败（${r.status}）`); } }
async function saveDevice(event) { event.preventDefault(); const form = event.target, data = Object.fromEntries(new FormData(form).entries()); ['rated_power_kw','hub_height_m','rotor_diameter_m'].forEach(k => data[k] = Number(data[k] || 0)); data.rated_params = {}; const url = editingDeviceId ? `/api/devices/${encodeURIComponent(editingDeviceId)}` : '/api/devices'; const r = await fetch(url,{method:editingDeviceId?'PUT':'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(data)}); if(!r.ok){toast((await r.json()).detail || '保存失败');return;} $('device-modal').classList.add('hidden'); toast(editingDeviceId?'设备档案已更新':'设备档案已创建'); await refreshCore(); loadDevices(); }

async function loadMaintainers() {
  const params = new URLSearchParams({page:1, page_size:200, include_inactive:true});
  const query = $('maintainer-search')?.value.trim(); if (query) params.set('q', query);
  const response = await fetch(`/api/maintainers?${params}`);
  if (!response.ok) throw new Error((await response.json()).detail || '维检人员加载失败');
  const data = await response.json(); maintainers = data.items || []; populateSelectors();
  $('maintainers-table').innerHTML = maintainers.length ? maintainers.map(x => `<tr><td><b>${esc(x.name)}</b><small>#${esc(x.id)}</small></td><td>${esc(x.phone_masked || x.phone)}</td><td>${esc(x.team || '未分组')}</td><td><span class="pill ${x.is_active ? 'success' : 'danger'}">${x.is_active ? '在岗' : '已停用'}</span></td><td>${esc(x.created_at)}</td><td><button class="table-link" onclick="editMaintainer(${x.id})">编辑</button>${x.is_active ? `<button class="table-link danger-link" onclick="toggleMaintainer(${x.id},false)">停用</button>` : `<button class="table-link" onclick="toggleMaintainer(${x.id},true)">启用</button>`}</td></tr>`).join('') : '<tr><td colspan="6" class="empty-cell">暂无维检人员，请先新增通讯录。</td></tr>';
}
function openMaintainerModal(maintainer = null) { editingMaintainerId = maintainer?.id || null; const form = $('maintainer-form'); form.reset(); form.elements.phone.required = !maintainer; $('maintainer-modal-title').textContent = maintainer ? '编辑维检人员' : '新增维检人员'; if (maintainer) { form.elements.name.value = maintainer.name || ''; form.elements.team.value = maintainer.team || ''; form.elements.phone.placeholder = '留空保持原手机号'; } else form.elements.phone.placeholder = '13800000001'; $('maintainer-modal').classList.remove('hidden'); }
function editMaintainer(id) { const maintainer = maintainers.find(x => Number(x.id) === Number(id)); if (maintainer) openMaintainerModal(maintainer); }
async function saveMaintainer(event) { event.preventDefault(); const form = event.target; const data = {name:form.elements.name.value.trim(), team:form.elements.team.value.trim()}; const phone = form.elements.phone.value.trim(); if (phone) data.phone = phone; if (!editingMaintainerId && !phone) { toast('请输入手机号'); return; } const url = editingMaintainerId ? `/api/maintainers/${editingMaintainerId}` : '/api/maintainers'; const response = await fetch(url,{method:editingMaintainerId?'PUT':'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(data)}); if(response.ok){$('maintainer-modal').classList.add('hidden'); toast(editingMaintainerId?'维检人员已更新':'维检人员已添加'); await refreshCore(); await loadMaintainers();}else{let error={};try{error=await response.json()}catch{}toast(error.detail || `保存人员失败（${response.status}）`)} }
async function toggleMaintainer(id, active) { if(!active && !confirm('停用后不能再被新工单选择，历史工单仍会保留关联。确认停用吗？')) return; const response=await fetch(`/api/maintainers/${id}`,{method:active?'PUT':'DELETE',headers:active?{'Content-Type':'application/json'}:undefined,body:active?JSON.stringify({is_active:true}):undefined}); if(response.ok){toast(active?'维检人员已启用':'维检人员已停用'); await refreshCore(); await loadMaintainers();}else{let error={};try{error=await response.json()}catch{}toast(error.detail || '人员状态更新失败')} }

async function diagnose(body, upload = false) { const button = $('simulate-btn'); button.disabled = true; button.textContent = '分析中…'; try { const options={method:'POST'}; const query=new URLSearchParams({device_id:$('device-select').value,channel:$('channel-input').value,remark:$('remark-input').value}); if(recheckWorkOrderId) query.set('work_order_id', recheckWorkOrderId); if(upload){const form=new FormData();form.append('file',body);options.body=form;}else{options.headers={'Content-Type':'application/json'};options.body=body;} const url=upload?`/api/diagnostics/upload?${query}`:'/api/diagnostics/simulate'; const r=await fetch(url,options); if(!r.ok) throw new Error((await r.json()).detail || '诊断失败'); const data=await r.json(); showResult(data); await refreshCore(); loadDiagnosisHistory(); toast(data.recheck_result === 'passed' ? '复检通过，工单已闭环，设备已按条件恢复' : '诊断完成，报告已生成'); }catch(e){toast(e.message)}finally{button.disabled=false;button.textContent='生成合成声纹并诊断'} }
function renderSignalVisuals(visuals, channel = 1) {
  if (!visuals) return;
  const waveform = Array.isArray(visuals.waveform) ? visuals.waveform : [];
  const path = $('waveform-path');
  if (path && waveform.length > 1) {
    const points = waveform.map((value, index) => {
      const x = index / (waveform.length - 1) * 900;
      const y = 90 - Math.max(-1, Math.min(1, Number(value) || 0)) * 76;
      return `${index ? 'L' : 'M'}${x.toFixed(1)},${y.toFixed(1)}`;
    }).join(' ');
    path.setAttribute('d', points);
  }
  if ($('signal-duration')) $('signal-duration').textContent = Number(visuals.duration || 0).toFixed(2);
  if ($('signal-channel')) $('signal-channel').textContent = `CH-${channel}`;
  const bars = $('spectrum-bars');
  if (bars && Array.isArray(visuals.spectrum) && visuals.spectrum.length) bars.innerHTML = visuals.spectrum.map(item => `<i title="${Number(item.frequency_hz || 0).toFixed(0)} Hz" style="height:${Math.max(6, Math.round((Number(item.amplitude) || 0) * 100))}%"></i>`).join('');
}
function renderSmsNotice(notification) { if (!notification) return ''; const tone = notification.status === 'sent' ? 'success' : notification.status === 'failed' ? 'danger' : 'warning'; return `<div class="sms-notice ${tone}"><b>${esc(notification.display_status || notification.status)}</b>${notification.message_id ? ` · 记录 #${esc(notification.message_id)}` : ''}</div>`; }
function showResult(data) { const report=data.report || {}; const card=$('result-card'); card.classList.remove('hidden'); renderSignalVisuals(data.visuals, data.channel || 1); const action=data.alert_id ? `<button class="secondary-button" onclick="createOrder(${data.id},${data.alert_id},'${idArg(data.device_id)}','${esc(report.fault_label || data.fault)}')">由诊断创建工单</button>` : ''; const recheckText=data.recheck_result === 'passed' ? '复检通过，关联工单已关闭' : data.recheck_result === 'failed' ? '复检仍异常，工单保持待复核' : ''; card.innerHTML=`<div class="result-top"><div><div class="eyebrow">DIAGNOSIS RESULT · #${esc(data.id)}</div><h3 class="result-label">${esc(report.fault_label || overview.faults[data.fault] || data.fault)}</h3><p class="muted">${esc(report.summary || '')}</p></div><div class="confidence">${Math.round(Number(data.confidence || 0)*100)}%</div></div><div class="result-body"><div><h4>严重程度</h4><p><span class="pill ${pillClass(data.severity)}">${esc(data.severity)}</span>${recheckText ? ` <span class="muted">${esc(recheckText)}</span>` : ''}</p></div><div><h4>建议复检</h4><p>${esc(report.recommended_recheck || '按现场工况安排复核')}</p></div><div><h4>可能原因</h4><p>${esc(report.possible_causes || '暂无原因说明')}</p></div><div><h4>处理建议</h4><ul>${(report.recommendations || []).slice(0,3).map(x => `<li>${esc(x)}</li>`).join('') || '<li>请结合现场工况进一步复核。</li>'}</ul></div></div><div class="result-actions">${action}<button class="secondary-button" onclick="return openReport(${data.id})">查看完整报告</button>${(data.sms_notifications || []).map(renderSmsNotice).join('')}</div>`; if(data.recheck_result === 'passed') clearRecheckContext(); }
function reportErrorHtml(message) { return `<!doctype html><html lang="zh-CN"><meta charset="utf-8"><title>报告暂不可用 · 声网先知</title><style>body{font:15px/1.7 "Microsoft YaHei",sans-serif;background:#080807;color:#f7edda;max-width:720px;margin:80px auto;padding:0 24px}main{border:1px solid #8d6726;background:#17130d;padding:28px;box-shadow:0 12px 30px #0008}h1{color:#f4c764}p{color:#c9b485}</style><main><h1>报告暂不可用</h1><p>${esc(message)}</p><p>请返回诊断历史重试，或重新生成一条诊断记录。</p></main></html>`; }
function openReport(diagnosisId) { const popup = window.open('', '_blank'); if (!popup) { toast('报告窗口被浏览器拦截，请允许弹出窗口后重试'); return false; } popup.document.write('<!doctype html><meta charset="utf-8"><p style="font:15px sans-serif;padding:32px">正在加载诊断报告…</p>'); fetch(`/api/diagnostics/${diagnosisId}/report`).then(async response => { const body = await response.text(); if (!response.ok) { let message = `报告加载失败（${response.status}）`; try { message = JSON.parse(body).detail || message; } catch {} throw new Error(message); } return body; }).then(body => { popup.document.open(); popup.document.write(body); popup.document.close(); }).catch(error => { popup.document.open(); popup.document.write(reportErrorHtml(error.message || '报告加载失败')); popup.document.close(); toast(error.message || '报告加载失败'); }); return false; }
async function loadDiagnosisHistory() { const device=$('history-device-filter').value, fault=$('history-fault-filter').value; const p=new URLSearchParams({page:1,page_size:100});if(device)p.set('device_id',device);if(fault)p.set('fault',fault);const data=await(await fetch(`/api/diagnostics?${p}`)).json();$('diagnosis-table').innerHTML=data.items.length?data.items.map(x=>`<tr><td>${esc(x.created_at)}</td><td><b>${esc(deviceName(x.device_id))}</b><small>${esc(x.device_id)}</small></td><td><b>${esc(overview.faults[x.fault]||x.fault)}</b></td><td><strong class="confidence-small">${Math.round(x.confidence*100)}%</strong></td><td><span class="pill ${pillClass(x.severity)}">${esc(x.severity)}</span></td><td>${esc(x.model_version)}</td><td><button class="table-link" onclick="return openReport(${x.id})">查看报告</button></td></tr>`).join(''):'<tr><td colspan="7" class="empty-cell">暂无诊断记录</td></tr>'; }
function clearRecheckContext() { recheckWorkOrderId = null; const context=$('recheck-context'); if(context){context.classList.add('hidden');context.textContent='';} }
function startRecheck(orderId, deviceId) { recheckWorkOrderId = orderId; deviceId=decodeURIComponent(deviceId); if($('device-select')) $('device-select').value = deviceId; const context=$('recheck-context'); if(context){context.textContent=`当前为工单 #${orderId} 复检模式：请选择“正常”或对应异常场景后提交诊断。`;context.classList.remove('hidden');} goView('diagnosis'); }
async function createOrder(diagnosisId, alertId, deviceId, label) { deviceId=decodeURIComponent(deviceId); const r=await fetch('/api/work-orders',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({diagnosis_id:diagnosisId,alert_id:alertId||null,device_id:deviceId,title:`${label} · 建议检修`,description:`由诊断报告 ${diagnosisId} 触发，请按报告建议复核。`,priority:'高',assignee:'待分配'})});if(r.ok){const data=await r.json();await refreshCore();toast(data.order_code ? `已关联检修工单 ${data.order_code}` : '检修工单已创建');goView('orders');}else{let data={};try{data=await r.json()}catch{}toast(data.detail || `检修工单创建失败（${r.status}）`)} }

async function loadAlerts() { const p=new URLSearchParams({page:1,page_size:100});const status=$('alert-status-filter').value,level=$('alert-level-filter').value;if(status)p.set('status',status);if(level)p.set('level',level);const data=await(await fetch(`/api/alerts?${p}`)).json();$('alert-total-label').textContent=data.total;$('alerts-table').innerHTML=data.items.length?data.items.map(x=>`<tr><td><b>${esc(x.alert_code)}</b><small>诊断 #${x.diagnosis_id}</small></td><td><b>${esc(x.title)}</b><small>${esc(x.description)}</small></td><td><b>${esc(deviceName(x.device_id))}</b><small>${esc(overview.devices.find(d=>d.id===x.device_id)?.wind_farm||'')}</small></td><td><span class="pill ${pillClass(x.level)}">${esc(x.level)}</span></td><td><span class="pill ${x.status==='已关闭'?'success':'warning'}">${esc(x.status)}</span></td><td>${esc(x.created_at)}</td><td>${x.status!=='已关闭'?`<button class="table-link" onclick="handleAlert(${x.id},'${x.status==='未处理'?'处理中':'已关闭'}')">${x.status==='未处理'?'确认':'关闭'}</button><button class="table-link" onclick="convertAlert(${x.id})">转工单</button>`:'<span class="muted">已完成</span>'}</td></tr>`).join(''):'<tr><td colspan="7" class="empty-cell">暂无告警</td></tr>'; }
async function handleAlert(id,status){const r=await fetch(`/api/alerts/${id}/handle`,{method:'PUT',headers:{'Content-Type':'application/json'},body:JSON.stringify({status,remark:status==='处理中'?'运维人员已确认':'已完成现场处置'})});if(r.ok){await refreshCore();await loadAlerts();toast(`告警已更新为${status}`)}else{let data={};try{data=await r.json()}catch{}toast(data.detail || `告警状态更新失败（${r.status}）`)}}
async function convertAlert(id){const r=await fetch(`/api/alerts/${id}/convert-order`,{method:'POST'});if(r.ok){const data=await r.json();await refreshCore();toast(data.order_code ? `已关联检修工单 ${data.order_code}` : '告警已转为检修工单');goView('orders')}else{let data={};try{data=await r.json()}catch{}toast(data.detail || `告警转工单失败（${r.status}）`)}}

async function loadOrders(){const p=new URLSearchParams({page:1,page_size:100});const status=$('order-status-filter').value,priority=$('order-priority-filter').value;if(status)p.set('status',status);if(priority)p.set('priority',priority);const data=await(await fetch(`/api/work-orders?${p}`)).json();$('orders-table').innerHTML=data.items.length?data.items.map(x=>{const next={待分配:'处理中',处理中:'已完成',已完成:'已关闭'}[x.status];const recheck=x.status==='已完成' && x.recheck_required;return `<tr><td><b>${esc(x.order_code)}</b><small>#${x.id} · ${esc(x.created_at)}</small></td><td><b>${esc(x.title)}</b><small>${esc(x.description)}</small></td><td><b>${esc(deviceName(x.device_id))}</b><small>${esc(x.device_id)}</small></td><td><span class="pill ${pillClass(x.priority)}">${esc(x.priority)}</span></td><td><b>${esc(x.assignee_name || x.assignee)}</b>${x.assignee_phone_masked ? `<small>${esc(x.assignee_phone_masked)}</small>` : ''}</td><td><span class="pill ${x.status==='已关闭'?'success':recheck?'danger':'warning'}">${esc(x.status)}</span>${recheck?'<small class="danger-text">待复检</small>':''}</td><td><button class="table-link" onclick="showOrder(${x.id})">详情</button>${recheck?`<button class="table-link" onclick="startRecheck(${x.id},'${idArg(x.device_id)}')">去复检</button>`:next?`<button class="table-link" onclick="advanceOrder(${x.id},'${next}')">${next}</button>`:''}</td></tr>`}).join(''):'<tr><td colspan="7" class="empty-cell">暂无工单</td></tr>';}
async function advanceOrder(id,status){const r=await fetch(`/api/work-orders/${id}/process`,{method:'PUT',headers:{'Content-Type':'application/json'},body:JSON.stringify({status,remark:`页面操作：${status}`})});if(r.ok){const data=await r.json();await loadOrders();await refreshCore();const notice=data.sms_notifications?.find(x=>x.event_type);toast(`${notice?.status==='failed'?'工单已更新，':''}${notice?.display_status || `工单已更新为${status}`}`)}else{let data={};try{data=await r.json()}catch{}toast(data.detail || `工单状态更新失败（${r.status}）`)}}
async function retrySms(id, orderId){const response=await fetch(`/api/sms-messages/${id}/retry`,{method:'POST'});if(response.ok){toast('短信重试已完成');await showOrder(orderId);}else{let error={};try{error=await response.json()}catch{}toast(error.detail || `短信重试失败（${response.status}）`)} }
async function showOrder(id){const response=await fetch(`/api/work-orders/${id}`);if(!response.ok){toast('工单详情加载失败');return;}const x=await response.json();const panel=$('order-detail-panel');panel.classList.remove('hidden');const diagnosis=x.diagnosis?`<div class="evidence-card"><div class="panel-title"><div><h4>诊断依据</h4><p>${esc(x.diagnosis.summary || '')}</p></div><button class="table-link" onclick="return openReport(${x.diagnosis.id})">查看报告</button></div><div class="detail-grid"><div><span>结论</span><b>${esc(x.diagnosis.fault_label)}</b></div><div><span>置信度</span><b>${Math.round(Number(x.diagnosis.confidence || 0)*100)}%</b></div><div><span>严重程度</span><b>${esc(x.diagnosis.severity)}</b></div><div><span>模型</span><b>${esc(x.diagnosis.model_version)}</b></div></div></div>`:'<div class="muted">暂无关联诊断依据</div>';const recheck=x.recheck_diagnosis?`<div class="evidence-card"><div class="panel-title"><div><h4>最近复检结果</h4><p>${esc(x.recheck_diagnosis.summary || '')}</p></div><button class="table-link" onclick="return openReport(${x.recheck_diagnosis.id})">查看报告</button></div><p><span class="pill ${pillClass(x.recheck_diagnosis.severity)}">${esc(x.recheck_diagnosis.fault_label)}</span> · ${esc(x.recheck_diagnosis.created_at)}</p></div>`:'';const sms=x.sms_messages?.length?x.sms_messages.map(m=>`<div class="sms-record"><div class="sms-record-head"><b>${esc(m.event_label || m.event_type)}</b><span class="pill ${m.status==='sent'?'success':m.status==='failed'?'danger':'warning'}">${esc(m.display_status)}</span></div><p>${esc(m.maintainer_name || x.assignee_name || '未知收件人')} · ${esc(m.phone_masked || m.phone)}</p><pre class="sms-content">${esc(m.content)}</pre><small>${esc(m.created_at)} · ${esc(m.delivery_label || (m.delivery_mode==='demo'?'演示通道':'真实通道'))}${m.error_message?` · ${esc(m.error_message)}`:''}</small>${m.status==='failed'?`<button class="table-link" onclick="retrySms(${m.id},${x.id})">重试发送</button>`:''}</div>`).join(''):'<p class="muted">暂无短信记录。未关联负责人或历史自由文本负责人不会产生短信。</p>';const assigneeOptions=x.assignee_id?'<option value="">取消分配</option>'+maintainers.filter(m=>m.is_active).map(m=>`<option value="${esc(m.id)}" ${Number(m.id)===Number(x.assignee_id)?'selected':''}>${esc(m.name)}${m.team?' · '+esc(m.team):''}</option>`).join(''):'';const assigneeEditor=x.assignee_id?`<select class="detail-assignee-select" onchange="reassignOrder(${x.id},this.value)">${assigneeOptions}</select>`:`<span>${esc(x.assignee_name || x.assignee)}</span>`;panel.innerHTML=`<div class="detail-head"><div><div class="eyebrow">WORK ORDER · ${esc(x.order_code)}</div><h3>${esc(x.title)}</h3><p class="muted">${esc(x.description)}</p></div><button class="ghost-button" onclick="$('order-detail-panel').classList.add('hidden')">收起</button></div><div class="order-detail-meta"><span>负责人：${assigneeEditor}${x.assignee_phone_masked ? `（${esc(x.assignee_phone_masked)}）` : ''}</span><span>状态：<b>${esc(x.status)}</b>${x.recheck_required?' · 待复检':''}</span><span>复检状态：<b>${esc(x.recheck_status)}</b></span></div>${x.recheck_required?`<button class="primary-button" onclick="startRecheck(${x.id},'${idArg(x.device_id)}')">进入复检</button>`:''}${diagnosis}${recheck}<div class="sms-section"><div class="panel-title"><div><h4>短信记录</h4><p>展示实际保存并发送的完整正文，手机号已脱敏。</p></div></div>${sms}</div><h4>处理时间线</h4><div class="timeline">${x.logs.map(log=>`<div class="timeline-item"><i></i><div><b>${esc(log.action)} · ${esc(log.to_status)}</b><p>${esc(log.remark)}</p><small>${esc(log.created_at)}</small></div></div>`).join('')}</div>`;panel.scrollIntoView({behavior:'smooth',block:'center'});}
const renderOrderDetail = showOrder;
showOrder = async function(id) {
  await renderOrderDetail(id);
  const panel = $('order-detail-panel');
  const owner = panel?.querySelector('.order-detail-meta span');
  if (!owner || panel.querySelector('.detail-assignee-select') || !owner.textContent.includes('待分配')) return;
  const options = '<option value="">选择维检负责人</option>' + maintainers.filter(x => x.is_active).map(x => `<option value="${esc(x.id)}">${esc(x.name)}${x.team ? ' · ' + esc(x.team) : ''}</option>`).join('');
  owner.innerHTML = `负责人：<select class="detail-assignee-select" onchange="reassignOrder(${Number(id)},this.value)">${options}</select>`;
};
async function reassignOrder(orderId, assigneeId){if(!assigneeId){toast('请选择有效的维检负责人');return;}const response=await fetch(`/api/work-orders/${orderId}/process`,{method:'PUT',headers:{'Content-Type':'application/json'},body:JSON.stringify({status:'处理中',assignee_id:Number(assigneeId),remark:'工单详情页改派'})});if(response.ok){const data=await response.json();const notice=data.sms_notifications?.find(x=>x.event_type);toast(`${notice?.status==='failed'?'工单已改派，':''}${notice?.display_status || '工单已改派'}`);await refreshCore();await loadOrders();await showOrder(orderId);}else{let error={};try{error=await response.json()}catch{}toast(error.detail || `工单改派失败（${response.status}）`);await showOrder(orderId);}}
async function saveManualOrder(event){event.preventDefault();const data=Object.fromEntries(new FormData(event.target).entries());const assigneeId=data.assignee_id;data.assignee_id=assigneeId?Number(assigneeId):null;data.assignee=assigneeId?event.target.elements.assignee_id.selectedOptions[0].textContent.split(' · ')[0]:'待分配';data.description=data.description||'手动创建的设备巡检工单';const r=await fetch('/api/work-orders',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(data)});if(r.ok){const result=await r.json();$('order-modal').classList.add('hidden');event.target.reset();await refreshCore();await loadOrders();const notice=result.sms_notifications?.find(x=>x.event_type);toast(`${notice?.status==='failed'?'工单已创建，':''}${notice?.display_status || '手动工单已创建'}`)}else{let error={};try{error=await r.json()}catch{}toast(error.detail || `手动工单创建失败（${r.status}）`)}}

async function submitLogin(event) {
  event.preventDefault();
  const form = event.target, button = form.querySelector('button[type="submit"]');
  button.disabled = true; button.textContent = '登录中…';
  try {
    const response = await nativeFetch('/api/auth/login', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({username:form.elements.username.value.trim(), password:form.elements.password.value})});
    const data = await response.json();
    if (!response.ok) throw new Error(data.detail || '用户名或密码错误');
    authToken = data.token; authUser = data.user; localStorage.setItem(AUTH_TOKEN_KEY, authToken); hideAuthGate();
    await startApp();
  } catch (error) { showAuthGate(error.message || '登录失败，请稍后重试'); }
  finally { button.disabled = false; button.textContent = '登录监控台'; }
}

async function startApp() {
  if (appStarted) return;
  appStarted = true; updateToday();
  refreshTimer = setInterval(() => { updateToday(); refreshCore({silent:true}); }, 60000);
  try { await refreshCore(); await goView(routeFromLocation(), false); }
  catch (error) { appStarted = false; clearInterval(refreshTimer); refreshTimer = null; toast('无法连接本地服务，请确认后端已启动'); throw error; }
}

async function bootstrapAuth() {
  if (!authToken) { showAuthGate(); return; }
  try {
    const response = await apiFetch('/api/auth/me');
    if (!response.ok) return;
    authUser = await response.json(); await startApp();
  } catch (error) { clearAuth(); showAuthGate('无法验证登录状态，请重新登录'); }
}

function routeFromLocation() { const view = location.hash.replace(/^#/, ''); return viewTitles[view] ? view : 'overview'; }
function handleRouteEvent() { const target = routeFromLocation(); if (target !== currentView) goView(target, false); }
function setMobileNav(open) { const sidebar = $('sidebar'), scrim = $('mobile-nav-scrim'), toggle = $('mobile-nav-toggle'); if (!sidebar || !scrim || !toggle) return; sidebar.classList.toggle('mobile-open', open); scrim.classList.toggle('hidden', !open); scrim.setAttribute('aria-hidden', String(!open)); toggle.setAttribute('aria-expanded', String(open)); toggle.setAttribute('aria-label', open ? '关闭导航' : '打开导航'); document.body.classList.toggle('nav-open', open); }
document.querySelectorAll('[data-view]').forEach(link => link.addEventListener('click', event => { event.preventDefault(); goView(link.dataset.view); setMobileNav(false); }));
document.querySelectorAll('[data-go]').forEach(link => link.addEventListener('click', event => { event.preventDefault(); goView(link.dataset.go); }));
window.addEventListener('popstate', handleRouteEvent); window.addEventListener('hashchange', handleRouteEvent);
$('mobile-nav-toggle').onclick = () => setMobileNav(true); $('mobile-nav-scrim').onclick = () => setMobileNav(false);
$('simulate-btn').onclick=()=>diagnose(JSON.stringify({device_id:$('device-select').value,fault:$('fault-select').value,channel:Number($('channel-input').value),remark:$('remark-input').value,work_order_id:recheckWorkOrderId}));$('audio-file').onchange=e=>{if(e.target.files[0])diagnose(e.target.files[0],true)};$('train-btn').onclick=async()=>{$('train-btn').disabled=true;$('train-btn').textContent='训练中…';try{const r=await fetch('/api/train',{method:'POST'});const d=await r.json();await refreshCore();toast(`模型训练完成 · ${d.backend}`)}finally{$('train-btn').disabled=false;$('train-btn').textContent='重新训练模型'}};
$('device-filter-btn').onclick=loadDevices;$('device-search').onkeydown=e=>{if(e.key==='Enter')loadDevices()};$('add-device-btn').onclick=()=>openDeviceModal();$('device-form').onsubmit=saveDevice;$('history-filter-btn').onclick=loadDiagnosisHistory;$('alert-filter-btn').onclick=loadAlerts;$('order-filter-btn').onclick=loadOrders;$('maintainer-filter-btn').onclick=loadMaintainers;$('maintainer-search').onkeydown=e=>{if(e.key==='Enter')loadMaintainers()};$('add-maintainer-btn').onclick=()=>openMaintainerModal();$('maintainer-form').onsubmit=saveMaintainer;$('manual-order-btn').onclick=()=>{$('manual-order-device').innerHTML=overview.devices.map(x=>`<option value="${esc(x.id)}">${esc(x.name)}</option>`).join('');populateSelectors();$('order-modal').classList.remove('hidden')};$('order-form').onsubmit=saveManualOrder;document.querySelectorAll('[data-close-modal]').forEach(x=>x.onclick=()=>$(x.dataset.closeModal).classList.add('hidden'));
$('login-form').onsubmit = submitLogin;
bootstrapAuth();

/* Shared interaction layer: modal lifecycle, button feedback and focus management. */
function uiActiveButton() { const active = document.activeElement; return active?.closest?.('button') || null; }
function uiWithButtonLoading(button, pendingText, operation) {
  if (button?.classList.contains('is-loading')) { let nested; try { nested = operation(); } catch (error) { return Promise.reject(error); } return Promise.resolve(nested); }
  if (button?.disabled) return Promise.resolve();
  const originalText = button?.textContent;
  if (button) { button.disabled = true; button.classList.add('is-loading'); button.setAttribute('aria-busy', 'true'); button.textContent = pendingText; }
  let result;
  try { result = operation(); } catch (error) { result = Promise.reject(error); }
  return Promise.resolve(result).finally(() => { if (button) { button.disabled = false; button.classList.remove('is-loading'); button.removeAttribute('aria-busy'); button.textContent = originalText; } });
}
function uiRunAction(button, pendingText, operation, fallback = '操作失败，请稍后重试') { return uiWithButtonLoading(button, pendingText, operation).catch(error => { toast(error?.message || fallback, 'error'); }); }
function uiVisibleRowCount(targetId) { const target = $(targetId); if (!target || target.querySelector('.empty-cell')) return 0; return target.querySelectorAll('tr').length; }
function uiRunFilter(button, title, targetId, loader) { return uiWithButtonLoading(button, '筛选中…', loader).then(() => toast(`${title}：共 ${uiVisibleRowCount(targetId)} 条`, 'success')).catch(error => toast(error?.message || `${title}失败，请稍后重试`, 'error')); }

const uiModalOpeners = new Map();
function uiSyncModalScroll() { document.body.classList.toggle('modal-open', Boolean(document.querySelector('.modal:not(.hidden)'))); }
function uiShowModal(id, opener = document.activeElement) {
  const modal = $(id); if (!modal) return;
  uiModalOpeners.set(id, opener?.closest?.('button') || opener || null); modal.dataset.uiCloseHandled = 'false'; modal.dataset.dirty = 'false'; modal.classList.remove('hidden'); modal.setAttribute('aria-hidden', 'false'); uiSyncModalScroll();
  setTimeout(() => modal.querySelector('input:not([type="hidden"]),select,textarea,button[type="submit"]')?.focus(), 0);
}
function uiFinishModalClose(modal) {
  if (!modal) return;
  modal.setAttribute('aria-hidden', 'true'); uiSyncModalScroll();
  if (modal.dataset.uiCloseHandled === 'true') return;
  modal.dataset.uiCloseHandled = 'true'; const opener = uiModalOpeners.get(modal.id); if (opener && document.contains(opener)) setTimeout(() => opener.focus(), 0);
}
function uiCloseModal(id, force = false) {
  const modal = $(id); if (!modal || modal.classList.contains('hidden')) return true;
  if (!force && modal.dataset.dirty === 'true') { toast('表单有未保存内容，请点击“取消”确认关闭', 'warning'); return false; }
  modal.classList.add('hidden'); uiFinishModalClose(modal); return true;
}
function uiWrapAsync(original, pendingText, fallback) { return function(...args) { return uiWithButtonLoading(uiActiveButton(), pendingText, () => original.apply(this, args)).catch(error => toast(error?.message || fallback, 'error')); }; }

document.querySelectorAll('.modal').forEach(modal => {
  modal.setAttribute('role', 'dialog'); modal.setAttribute('aria-modal', 'true'); modal.setAttribute('aria-hidden', modal.classList.contains('hidden') ? 'true' : 'false');
  modal.querySelector('.modal-head button')?.setAttribute('aria-label', '关闭弹窗');
  modal.addEventListener('click', event => { if (event.target === modal) uiCloseModal(modal.id); });
  const form = modal.querySelector('form'); if (form) { form.addEventListener('input', () => { modal.dataset.dirty = 'true'; }); form.addEventListener('change', () => { modal.dataset.dirty = 'true'; }); form.addEventListener('reset', () => { modal.dataset.dirty = 'false'; }); }
});
document.querySelectorAll('.modal').forEach(modal => { const title = modal.querySelector('.modal-head h3'); if (title) { if (!title.id) title.id = `${modal.id}-title`; modal.setAttribute('aria-labelledby', title.id); } });
new MutationObserver(records => records.forEach(record => { if (record.attributeName === 'class' && record.target.classList.contains('modal') && record.target.classList.contains('hidden')) uiFinishModalClose(record.target); })).observe(document.body, {subtree:true, attributes:true, attributeFilter:['class']});
document.addEventListener('keydown', event => { if (event.key !== 'Escape') return; const modal = document.querySelector('.modal:not(.hidden)'); if (modal) uiCloseModal(modal.id); });
document.querySelectorAll('[data-close-modal]').forEach(control => { control.type = 'button'; control.onclick = event => { event.preventDefault(); uiCloseModal(control.dataset.closeModal, true); }; });
const uiToast = $('toast'); if (uiToast) { uiToast.setAttribute('role', 'status'); uiToast.setAttribute('aria-live', 'polite'); }

const uiOpenDeviceModal = openDeviceModal;
openDeviceModal = function(device = null, opener = null) { uiOpenDeviceModal(device); uiShowModal('device-modal', opener || uiActiveButton()); };
const uiOpenMaintainerModal = openMaintainerModal;
openMaintainerModal = function(maintainer = null, opener = null) { uiOpenMaintainerModal(maintainer); uiShowModal('maintainer-modal', opener || uiActiveButton()); };
$('add-device-btn').onclick = event => openDeviceModal(null, event.currentTarget);
$('add-maintainer-btn').onclick = event => openMaintainerModal(null, event.currentTarget);
$('manual-order-btn').onclick = event => { $('manual-order-device').innerHTML = overview.devices.map(x => `<option value="${esc(x.id)}">${esc(x.name)}</option>`).join(''); populateSelectors(); uiShowModal('order-modal', event.currentTarget); };

$('device-form').onsubmit = event => { const button = event.submitter || event.currentTarget.querySelector('button[type="submit"]'); return uiRunAction(button, '保存中…', () => saveDevice(event), '设备保存失败，请稍后重试'); };
$('maintainer-form').onsubmit = event => { const button = event.submitter || event.currentTarget.querySelector('button[type="submit"]'); return uiRunAction(button, '保存中…', () => saveMaintainer(event), '人员保存失败，请稍后重试'); };
$('order-form').onsubmit = event => { const button = event.submitter || event.currentTarget.querySelector('button[type="submit"]'); return uiRunAction(button, '创建中…', () => saveManualOrder(event), '工单创建失败，请稍后重试'); };

const uiFilterBindings = [
  ['device-filter-btn', '设备', 'devices-table', loadDevices],
  ['history-filter-btn', '诊断记录', 'diagnosis-table', loadDiagnosisHistory],
  ['alert-filter-btn', '告警', 'alerts-table', loadAlerts],
  ['order-filter-btn', '工单', 'orders-table', loadOrders],
  ['maintainer-filter-btn', '维检人员', 'maintainers-table', loadMaintainers]
];
uiFilterBindings.forEach(([id, title, target, loader]) => { const button = $(id); if (button) button.onclick = () => uiRunFilter(button, title, target, loader); });
$('device-search').onkeydown = event => { if (event.key === 'Enter') { event.preventDefault(); uiRunFilter($('device-filter-btn'), '设备', 'devices-table', loadDevices); } };
$('maintainer-search').onkeydown = event => { if (event.key === 'Enter') { event.preventDefault(); uiRunFilter($('maintainer-filter-btn'), '维检人员', 'maintainers-table', loadMaintainers); } };

const uiOriginalShowDevice = showDevice; showDevice = uiWrapAsync(uiOriginalShowDevice, '加载中…', '设备详情加载失败，请稍后重试');
const uiOriginalEditDevice = editDevice; editDevice = uiWrapAsync(uiOriginalEditDevice, '加载中…', '设备编辑页加载失败，请稍后重试');
const uiOriginalDeleteDevice = deleteDevice; deleteDevice = uiWrapAsync(uiOriginalDeleteDevice, '停用中…', '设备停用失败，请稍后重试');
const uiOriginalToggleMaintainer = toggleMaintainer; toggleMaintainer = uiWrapAsync(uiOriginalToggleMaintainer, '处理中…', '人员状态更新失败，请稍后重试');
const uiOriginalCreateOrder = createOrder; createOrder = uiWrapAsync(uiOriginalCreateOrder, '创建中…', '工单创建失败，请稍后重试');
const uiOriginalHandleAlert = handleAlert; handleAlert = uiWrapAsync(uiOriginalHandleAlert, '处理中…', '告警处理失败，请稍后重试');
const uiOriginalConvertAlert = convertAlert; convertAlert = uiWrapAsync(uiOriginalConvertAlert, '转换中…', '告警转工单失败，请稍后重试');
const uiOriginalAdvanceOrder = advanceOrder; advanceOrder = uiWrapAsync(uiOriginalAdvanceOrder, '处理中…', '工单状态更新失败，请稍后重试');
const uiOriginalRetrySms = retrySms; retrySms = uiWrapAsync(uiOriginalRetrySms, '重试中…', '短信重试失败，请稍后重试');
const uiOriginalShowOrder = showOrder; showOrder = uiWrapAsync(uiOriginalShowOrder, '加载中…', '工单详情加载失败，请稍后重试');
const uiOriginalReassignOrder = reassignOrder;
reassignOrder = async function(...args) { const select = document.activeElement?.matches?.('.detail-assignee-select') ? document.activeElement : null; if (select) { select.disabled = true; select.classList.add('is-loading'); } try { return await uiOriginalReassignOrder.apply(this, args); } finally { if (select) { select.disabled = false; select.classList.remove('is-loading'); } } };
