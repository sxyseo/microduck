/* IMU installation acceptance: structured evidence for the 解读 68 §3.4 protocol.
   Live numbers come from the bench IMU panel (Web Serial, ID 200) or any readout; this
   card only records what the operator measured. The service re-judges every value
   against the documented thresholds — the browser never decides pass/fail. */
window.ImuCheckStudio = (() => {
  const $ = id => document.getElementById(id);
  const esc = value => String(value ?? '').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  let project = null, latest = null, generation = 0;

  const request = async (url, body) => {
    const r = await StudioAPI.fetch(url, body === undefined ? {} : {method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
    const j = await r.json();
    if (!r.ok) throw Error(typeof j.detail === 'string' ? j.detail : '请求未完成');
    return j;
  };
  const status = (message, warning = false) => {
    const box = $('imucheck-status');
    box.className = `inline-note${warning ? ' warning' : ''}`;
    box.textContent = message;
    box.hidden = false;
  };
  const num = id => { const v = $(id).value.trim(); return v === '' ? null : Number(v); };
  const vec = id => { const v = $(id).value.trim(); return v === '' ? null : v.split(',').map(Number); };

  function reset() {
    generation++; project = null; latest = null;
    if ($('imucheck-result')) $('imucheck-result').replaceChildren();
    if ($('imucheck-status')) $('imucheck-status').hidden = true;
  }

  async function receiveReport(report) {
    if (report.project.id === project) return;
    generation++; project = report.project.id;
    const token = generation;
    try {
      const data = await request(`/api/projects/${project}/imu-acceptances`);
      if (token !== generation) return;
      latest = data.acceptances[0] || null;
      renderLatest();
    } catch (e) { if (token === generation) status(e.message, true); }
  }

  function collect() {
    const checks = [];
    const gyro = {gx_rad_s: num('imu-gx'), gy_rad_s: num('imu-gy'), gz_rad_s: num('imu-gz'), duration_s: num('imu-still-duration')};
    if (Object.values(gyro).some(v => v !== null)) checks.push({id: 'gyro_stationary', measured: gyro});
    const up = vec('imu-gravity-up');
    if (up) checks.push({id: 'gravity_upright', measured: {gravity: up}});
    const down = vec('imu-gravity-down');
    if (down) checks.push({id: 'gravity_inverted', measured: {gravity: down}});
    const pitchY = num('imu-pitch-gy');
    if (pitchY !== null) checks.push({id: 'pitch_sign', measured: {gyro_y_rad_s: pitchY, matches_convention: $('imu-pitch-ok').checked}});
    const q1 = vec('imu-quat-before'), q2 = vec('imu-quat-after');
    if (q1 || q2) checks.push({id: 'quat_rotation', measured: {quat_before: q1, quat_after: q2, no_jump: $('imu-quat-ok').checked}});
    const soak = {duration_s: num('imu-soak-duration'), hz: num('imu-soak-hz'), samples: num('imu-soak-samples'), max_consecutive_stale: num('imu-soak-stale')};
    if (Object.values(soak).some(v => v !== null)) checks.push({id: 'soak_50hz', measured: soak});
    return checks;
  }

  const VERDICT_TEXT = {passed: '通过', failed: '未通过', insufficient_evidence: '证据不足'};

  function renderResult(record) {
    const d = record.data || record;
    const rows = (d.checks || []).map(c => `<tr><td><code>${esc(c.id)}</code></td><td>${VERDICT_TEXT[c.verdict] || esc(c.verdict)}</td><td class="muted">${esc((c.reasons || []).join('；')) || (c.measured ? '已按门槛判定' : '未提交实测值')}</td></tr>`).join('');
    $('imucheck-result').innerHTML = `<div class="inline-note ${d.status === 'passed' ? '' : 'warning'}">
<strong>${VERDICT_TEXT[d.status] || d.status} · 规则 ${esc(d.rule_version || '')}</strong>
· 已测 ${esc(String(d.measured_steps))}/${esc(String(d.required_steps))} 步 · 安装映射 ${esc(d.mount_mapping || '')}</div>
<table class="servo-ref-table"><tbody>${rows}</tbody></table>
${(d.warnings || []).map(w => `<p class="inline-note warning">${esc(w)}</p>`).join('')}
${record.id ? `<p class="muted">记录编号 <code>${esc(record.id)}</code>${d.operator ? ` · 操作者 ${esc(d.operator)}` : ''}</p>` : ''}`;
  }

  function renderLatest() {
    if (latest) {
      renderResult(latest);
      status(`已载入最近一次验收记录（${VERDICT_TEXT[latest.data.status] || latest.data.status}）。重新实测后再次保存即可追加新记录。`);
    }
  }

  function init() {
    $('imucheck-save').onclick = guard(async () => {
      const checks = collect();
      if (!checks.length) return status('请先填写至少一步的实测数值；测量工具在「舵机实验室 → IMU 姿态」。', true);
      const operator = $('imucheck-operator').value.trim();
      if (!operator) return status('验收必须记录操作者。', true);
      const token = generation;
      const record = await request(`/api/projects/${project}/imu-acceptances`, {
        checks,
        operator,
        ...($('imucheck-imu').value.trim() ? {imu_model: $('imucheck-imu').value.trim()} : {}),
        ...($('imucheck-mount').value.trim() ? {mount_mapping: $('imucheck-mount').value.trim()} : {}),
        ...($('imucheck-note').value.trim() ? {note: $('imucheck-note').value.trim()} : {}),
      });
      if (token !== generation) return;
      latest = record;
      renderResult(record);
      status(record.data.status === 'passed' ? 'IMU 安装验收通过，已作为项目证据保存。' : `验收记录已保存，状态：${VERDICT_TEXT[record.data.status]}。`, record.data.status !== 'passed');
    });
  }

  const guard = fn => async () => { try { await fn(); } catch (e) { status(e.message, true); } };

  return {init, reset, receiveReport};
})();
