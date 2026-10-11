/* Regional robot weighing against the official MJCF template, plus the servo ID map.
   The template is parsed read-only by the service; measured masses stay project evidence
   and the official MJCF is never modified (copies are written under explicit confirm).
   The ID map records what the operator wrote into the servos — bus probing verifies it. */
window.WeighingStudio = (() => {
  const $ = id => document.getElementById(id);
  const esc = value => String(value ?? '').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  let project = null, template = null, latestWeighing = null, latestIdMap = null, generation = 0;

  const METHOD_LABELS = {scale: '整称', derived: '倒推', mirror: '镜像'};
  // Mirrors HL2915_ID_CONVENTION in microduck_studio/weighing.py; placeholders only.
  const DEFAULT_ID_CONVENTION = {1:'left_hip_yaw',2:'left_hip_roll',3:'left_hip_pitch',4:'left_knee',5:'left_ankle',
    6:'neck_pitch',7:'head_pitch',8:'head_yaw',9:'head_roll',10:'mouth',
    11:'right_hip_yaw',12:'right_hip_roll',13:'right_hip_pitch',14:'right_knee',15:'right_ankle'};

  const request = async (url, body) => {
    const r = await StudioAPI.fetch(url, body === undefined ? {} : {method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
    const j = await r.json();
    if (!r.ok) throw Error(typeof j.detail === 'string' ? j.detail : '请求未完成');
    return j;
  };
  const status = (message, warning = false) => {
    const box = $('weighing-status');
    box.className = `inline-note${warning ? ' warning' : ''}`;
    box.textContent = message;
    box.hidden = false;
  };
  const projectPath = path => `/api/projects/${project}/${path}`;

  function reset() {
    generation++;
    project = null; template = null; latestWeighing = null; latestIdMap = null;
    if ($('weighing-template')) {
      $('weighing-template').replaceChildren(new Option('选择项目后载入官方模板',''));
      $('weighing-template-info').textContent = '';
      $('weighing-rows').replaceChildren();
      $('weighing-result').replaceChildren();
      $('idmap-result').replaceChildren();
      $('weighing-status').hidden = true;
      $('weighing-copy').disabled = true;
    }
  }

  async function receiveReport(report) {
    if (report.project.id === project) return;
    generation++;
    project = report.project.id;
    const token = generation;
    try {
      await loadTemplate();
      if (token !== generation) return;
      await loadLatest();
    } catch (e) { if (token === generation) status(e.message, true); }
  }

  async function loadTemplate(path) {
    const data = await request(projectPath(`weighing-template${path ? `?path=${encodeURIComponent(path)}` : ''}`));
    template = data.template;
    const select = $('weighing-template');
    select.replaceChildren(...data.candidates.map(c => new Option(
      `${c.path} · ${c.body_count} 区域 · 官方 ${c.official_total_g} g${c.upstream ? ' · upstream' : ''}`, c.path)));
    if (data.candidates.some(c => c.path === template.relative_path)) select.value = template.relative_path;
    $('weighing-template-info').textContent = `模板 SHA-256 ${template.sha256.slice(0, 16)}… · 官方整机 ${template.official_total_g} g · 分区域称完可整机对账`;
    renderRows();
    syncCopyButton();
  }

  function savedEntry(body) {
    if (latestWeighing && latestWeighing.data?.template?.sha256 === template.sha256) {
      return latestWeighing.data.entries.find(entry => entry.body === body);
    }
    return null;
  }

  function renderRows() {
    $('weighing-rows').innerHTML = `<table><thead><tr><th>body（称重区域）</th><th>官方 g</th><th>实测 g</th><th>方式</th><th>备注</th></tr></thead><tbody>${
      template.bodies.map(b => {
        const saved = savedEntry(b.body);
        return `<tr data-body="${esc(b.body)}"><td><code>${esc(b.body)}</code></td><td class="num">${b.official_mass_g}</td>
<td><input class="w-measured" type="number" step="0.01" min="0" inputmode="decimal" placeholder="待称" value="${saved ? saved.measured_g : ''}"></td>
<td><select class="w-method">${['scale','derived','mirror'].map(m => `<option value="${m}"${saved?.method === m ? ' selected' : ''}>${METHOD_LABELS[m]}</option>`).join('')}</select></td>
<td><input class="w-note" placeholder="倒推/镜像的依据" value="${saved?.note ? esc(saved.note) : ''}"></td></tr>`;
      }).join('')}</tbody></table>`;
  }

  function collectEntries() {
    return [...document.querySelectorAll('#weighing-rows tr[data-body]')]
      .map(row => ({row, raw: row.querySelector('.w-measured').value.trim()}))
      .filter(({raw}) => raw !== '')
      .map(({row, raw}) => ({
        body: row.dataset.body,
        measured_g: Number(raw),
        method: row.querySelector('.w-method').value,
        ...(row.querySelector('.w-note').value.trim() ? {note: row.querySelector('.w-note').value.trim()} : {}),
      }));
  }

  function renderWeighingResult(record) {
    const d = record.data || record;
    const missing = d.missing_regions || [];
    $('weighing-result').innerHTML = `<div class="inline-note ${d.status === 'complete' ? '' : 'warning'}">
<strong>${d.status === 'complete' ? '称重记录完整' : '证据不足'} · 规则 ${esc(d.rule_version || '')}</strong>
已称 ${d.entries.length} 区域 · 实测合计 ${d.measured_total_g} g · 官方 ${d.official_total_g} g · 差值 ${d.delta_g} g（${d.delta_pct}%）</div>
${missing.length ? `<p class="muted">缺失区域：${missing.map(esc).join('、')}。缺失时总数不能与官方整机质量对账。</p>` : ''}
${(d.warnings || []).map(w => `<p class="inline-note warning">${esc(w)}</p>`).join('')}
${record.id ? `<p class="muted">记录编号 <code>${esc(record.id)}</code></p>` : ''}`;
  }

  function syncCopyButton() {
    $('weighing-copy').disabled = !(latestWeighing && latestWeighing.data?.status === 'complete');
  }

  async function loadLatest() {
    const token = generation;
    const [w, m] = await Promise.all([request(projectPath('weighings')), request(projectPath('servo-id-maps'))]);
    if (token !== generation) return;
    latestWeighing = w.weighings[0] || null;
    latestIdMap = m.id_maps[0] || null;
    if (latestWeighing && latestWeighing.data?.template?.sha256 === template?.sha256) {
      renderRows();
      renderWeighingResult(latestWeighing);
    }
    renderIdMapRows();
    syncCopyButton();
  }

  function renderIdMapRows() {
    const saved = {};
    if (latestIdMap) for (const entry of latestIdMap.data.entries) saved[entry.servo_id] = entry.joint;
    $('idmap-rows').innerHTML = `<table><thead><tr><th>总线 ID</th><th>关节（实际写入位置）</th></tr></thead><tbody>${
      Object.entries(DEFAULT_ID_CONVENTION).map(([id, joint]) =>
        `<tr><td><input class="m-id" type="number" min="1" max="253" step="1" value="${id}"></td>
<td><input class="m-joint" value="${esc(saved[id] ?? joint)}" placeholder="例如 ${joint}"></td></tr>`).join('')}</tbody></table>`;
    renderIdMapResult();
  }

  function renderIdMapResult() {
    if (!latestIdMap) { $('idmap-result').replaceChildren(); return; }
    const d = latestIdMap.data;
    $('idmap-result').innerHTML = `<div class="inline-note ${d.matches_default_convention ? '' : 'warning'}">
<strong>${d.matches_default_convention ? '与 hl2915 默认约定一致' : '与 hl2915 默认约定不同'}</strong>
· ${d.entries.length} 颗舵机 · 记录编号 <code>${esc(latestIdMap.id)}</code></div>
${d.matches_default_convention ? '' : '<p class="muted">后续 robotd.toml、标定与 BAM 都按此表的实际映射执行；确认表格与实物一致后可忽略本提示。</p>'}`;
  }

  const guard = fn => async () => { try { await fn(); } catch (e) { status(e.message, true); } };

  function init() {
    $('weighing-template').onchange = guard(async () => { await loadTemplate($('weighing-template').value || undefined); });
    $('weighing-save').onclick = guard(async () => {
      const entries = collectEntries();
      if (!entries.length) return status('请先填写至少一个区域的实测克重。', true);
      const token = generation;
      const record = await request(projectPath('weighings'), {
        template_path: template.relative_path,
        entries,
        scale: {model: $('weighing-scale').value.trim() || null, precision_g: $('weighing-precision').value ? Number($('weighing-precision').value) : null},
        ...( $('weighing-operator').value.trim() ? {operator: $('weighing-operator').value.trim()} : {}),
      });
      if (token !== generation) return;
      latestWeighing = record;
      renderWeighingResult(record);
      syncCopyButton();
      status(record.data.status === 'complete' ? `称重记录已保存；整机差值 ${record.data.delta_g} g。` : '称重记录已保存；还有区域未称，状态为证据不足。');
    });
    $('weighing-copy').onclick = guard(async () => {
      if (!latestWeighing) return status('先保存一份完整的称重记录。', true);
      if (!window.confirm('将在项目目录内生成质量修正 MJCF 副本（不覆盖官方模板与已有文件）。继续？')) return;
      const token = generation;
      const result = await request(projectPath(`weighings/${latestWeighing.id}/model-copy`), {output_path: $('weighing-copy-path').value.trim(), confirm: true});
      if (token !== generation) return;
      $('weighing-result').insertAdjacentHTML('beforeend', `<div class="inline-note"><strong>模型副本已生成</strong><br><code>${esc(result.output_path)}</code><br>替换 ${result.replaced_bodies} 个 body 的质量，惯量按比例缩放 · SHA-256 <code>${esc(result.sha256.slice(0, 16))}…</code>${result.artifact ? ' · 已登记为产物' : ''}</div>`);
      status('模型副本已生成；进入仿真验证前请在仿真中核对总质量。');
    });
    $('idmap-save').onclick = guard(async () => {
      const entries = [...document.querySelectorAll('#idmap-rows tr')]
        .map(row => ({servo_id: Number(row.querySelector('.m-id').value), joint: row.querySelector('.m-joint').value.trim()}))
        .filter(entry => entry.joint);
      if (!entries.length) return status('请先填写至少一行 ID 与关节位置。', true);
      const token = generation;
      const record = await request(projectPath('servo-id-maps'), {
        entries,
        ...( $('idmap-operator').value.trim() ? {operator: $('idmap-operator').value.trim()} : {}),
      });
      if (token !== generation) return;
      latestIdMap = record;
      renderIdMapResult();
      status(record.data.matches_default_convention ? 'ID 映射已保存，与 hl2915 默认约定一致。' : 'ID 映射已保存；与默认约定不同，后续配置会按此表执行。');
    });
  }

  return {init, reset, receiveReport};
})();
