/* Same-origin Color Studio integration. Device actions remain in the execution service. */
window.VisualStudio = (() => {
  const $ = id => document.getElementById(id);
  const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const clone = value => structuredClone(value);
  const options = (values, selected) => Object.entries(values).map(([value,label]) => `<option value="${esc(value)}" ${value === String(selected) ? 'selected' : ''}>${esc(label)}</option>`).join('');
  const split = value => value.split('\n').map(x => x.trim()).filter(Boolean);
  const number = value => value.trim() === '' ? null : Number(value);
  const statuses = {pending:'待检查', passed:'通过（需证据）', failed:'失败', blocked:'被阻塞', not_applicable:'不适用'};
  const materialStatuses = {unknown:'待核实',missing:'缺少',ordered:'已下单',received:'已到货',used:'已使用'};
  let project = null, generation = 0, metadata = null, frame = null, api = null, selected = null;
  let versions = [], revision = 0, visualDraft = null, visualDirty = false, visualLoaded = false, loadingFrame = false, applying = false;
  let assembly, calibration, dirty = {assembly:false,calibration:false}, rawDirty = {}, activeView = location.hash.slice(1);
  const draftKey = id => `microduck-studio:visual-draft:${id}`;
  const emptyAssembly = () => ({title:'第一次结构试装',source_refs:[],materials:[],checks:[]});
  const emptyCalibration = () => ({joints:[],operator:'',verified:false});
  const state = text => { $('visual-save-state').textContent = text; };
  async function request(url, options) {
    const response = await fetch(url, options);
    let data; try { data = await response.json(); } catch { throw new Error('本地服务返回了不可用的内容'); }
    if (!response.ok) throw new Error(typeof data.detail === 'string' ? data.detail : `请求失败（${response.status}）`);
    return data;
  }
  function stash() {
    if (!project) return;
    try { sessionStorage.setItem(draftKey(project), JSON.stringify({visual:visualDirty ? visualDraft : null, revision, raw:{assembly:rawDirty.assembly ? $('assembly-data').value : null,calibration:rawDirty.calibration ? $('calibration-data').value : null}, assembly:dirty.assembly ? assembly : null, calibration:dirty.calibration ? calibration : null})); }
    catch { state('草稿暂存失败，请保存到项目或导出备份'); }
  }
  function reset() {
    stash(); generation++; project = null; api = null; selected = null; loadingFrame = false; visualLoaded = false; versions = []; revision = 0; visualDraft = null; visualDirty = false;
    frame?.remove(); frame = null;
    $('visual-host').innerHTML = '<div class="empty-state">选择项目后，载入它的配色与装配。</div>';
    $('visual-save').disabled = true; $('visual-add-check').disabled = true; $('visual-name').value = '';
    $('visual-selected-name').textContent = '点击模型或零件列表，选择要检查的部件';
    $('visual-selected-meta').textContent = '配色与预览不构成装配验收证据。';
    state('选择项目后开始'); dirty = {assembly:false,calibration:false}; rawDirty = {};
    assembly = emptyAssembly(); calibration = emptyCalibration(); renderForms(); renderVersions();
  }
  function snapshot() {
    if (!api) return visualDraft;
    return {palette:{...api.getPalette(),name:$('visual-name').value.trim() || api.getPalette().name},inventory:api.getInventory()};
  }
  function changed() {
    if (applying || !api) return;
    visualDraft = snapshot(); visualDirty = true; stash(); state(`未保存的更改 · 当前项目 v${revision}`);
  }
  function renderVersions() {
    $('visual-version').innerHTML = versions.length ? versions.map(x => `<option value="${x.revision}">v${x.revision} · ${esc(x.data.palette.name)} · ${esc(new Date(x.created_at).toLocaleString('zh-CN'))}</option>`).join('') : '<option value="">尚无保存版本</option>';
    $('visual-load-version').disabled = !versions.length; $('visual-reload').disabled = !project;
  }
  function selectPart(id) {
    selected = metadata?.model.parts.find(p => p.id === id) || null;
    $('visual-selected-name').textContent = selected?.name || '请选择模型零件';
    $('visual-selected-meta').textContent = selected ? `${selected.assembly} · ${selected.printable ? '打印件实例' : '硬件参考实例'} · ${selected.id}` : '';
    $('visual-add-check').disabled = !selected || !project;
  }
  function applyDraft(data) {
    if (!api || !data) return;
    applying = true;
    try {
      // Both payloads were validated by the service or the same editor before stashing.
      api.importPalette(data.palette); api.setInventory(data.inventory);
      $('visual-name').value = data.palette.name;
      visualDraft = snapshot();
    } finally { applying = false; }
  }
  function frameError(message) {
    state(message); $('visual-save').disabled = true;
    $('visual-host').innerHTML = `<div class="empty-state"><strong>3D 工作区暂不可用</strong><p>${esc(message)}</p><button id="visual-retry">重新载入模型</button></div>`;
    api = null; frame = null; loadingFrame = false;
    $('visual-retry').onclick = () => ensureFrame();
  }
  function ensureFrame() {
    if (activeView !== 'visual' || !project || !visualLoaded || !metadata || frame || loadingFrame) return;
    if (!metadata.available) return frameError('请先构建本地 Color Studio 前端，再重启 Studio 服务。');
    loadingFrame = true;
    const token = generation, id = project;
    frame = document.createElement('iframe');
    frame.title = 'Microduck 3D 配色与装配参考模型'; frame.className = 'color-studio-frame';
    // The child has no access to global Color Studio localStorage in this mode.
    frame.src = '/color-studio/?embed=studio';
    const localFrame = frame;
    frame.onload = () => {
      if (generation !== token || project !== id) return;
      const child = localFrame.contentWindow;
      if (child.document.body.dataset.renderError) return frameError(child.document.body.dataset.renderError);
      const ready = () => {
        if (generation !== token || api || !child.colorStudio) return;
        api = child.colorStudio; loadingFrame = false;
        try {
          if (visualDraft) applyDraft(visualDraft);
          else { visualDraft = snapshot(); $('visual-name').value = visualDraft.palette.name; }
          child.addEventListener('colorstudio:change', () => { if (generation === token) changed(); });
          child.addEventListener('colorstudio:inventory', () => { if (generation === token) changed(); });
          child.addEventListener('colorstudio:selection', event => { if (generation === token) selectPart(event.detail.id); });
          const current = metadata.model.parts.find(p => p.role === metadata.model.colorGroups[0]?.id) || metadata.model.parts[0];
          selectPart(current.id);
          $('visual-save').disabled = false;
          state(visualDirty ? '已恢复未保存草稿' : revision ? `已载入项目版本 v${revision}` : '尚无外观版本 · 默认配色未保存');
          const resize = () => { if (generation === token) localFrame.style.height = `${Math.max(780, child.document.body.scrollHeight + 2)}px`; };
          const observer = new ResizeObserver(resize); observer.observe(child.document.body); resize();
          requestAnimationFrame(() => { if (generation === token) api?.setView('three-quarter'); });
          child.addEventListener('unload', () => observer.disconnect(), {once:true});
        } catch (error) { frameError(`项目配色载入失败：${error.message}。原记录与暂存草稿已保留。`); }
      };
      child.addEventListener('colorstudio:ready', ready, {once:true}); ready();
      // A renderer failure is visible instead of being mistaken for an empty project.
      child.addEventListener('colorstudio:error', event => { if (generation === token) frameError(event.detail); });
    };
    $('visual-host').replaceChildren(frame); state('正在载入 70 个模型实例…');
  }
  async function loadProjectVisual(token, id, draft) {
    try {
      const data = await request(`/api/projects/${id}/visual-configs`);
      if (generation !== token || project !== id) return;
      versions = data.versions; revision = versions[0]?.revision || 0;
      visualDraft = draft?.visual || versions[0]?.data || null; visualDirty = !!draft?.visual;
      if (draft?.visual && draft.revision !== revision) {
        // Preserve the old expected revision so save cannot silently replace newer work.
        revision = draft.revision; state('草稿基于旧版本，请核对项目版本后再保存');
      }
      visualLoaded = true; renderVersions(); ensureFrame();
    } catch (error) { state(`项目外观读取失败：${error.message}。点击“重新读取项目版本”重试。`); }
  }
  function receiveReport(report) {
    const id = report.project?.id;
    if (!id) return;
    if (id !== project) {
      reset(); project = id; const token = generation;
      let draft = null;
      try { draft = JSON.parse(sessionStorage.getItem(draftKey(id)) || 'null'); } catch { /* Unreadable draft is ignored; durable server versions remain available. */ }
      assembly = draft?.assembly || clone(report.assemblies?.[0]?.data || emptyAssembly());
      calibration = draft?.calibration || clone(report.calibrations?.[0]?.data || emptyCalibration());
      dirty = {assembly:!!draft?.assembly,calibration:!!draft?.calibration};
      renderForms();
      for (const kind of ['assembly','calibration']) if (draft?.raw?.[kind]) { $(`${kind}-data`).value = draft.raw[kind]; rawDirty[kind] = true; dirty[kind] = true; }
      $('visual-reload').disabled = false;
      loadProjectVisual(token, id, draft);
    } else {
      if (!dirty.assembly && report.assemblies?.length) { assembly = clone(report.assemblies[0].data); renderAssembly(); }
      if (!dirty.calibration && report.calibrations?.length) { calibration = clone(report.calibrations[0].data); renderCalibration(); }
    }
  }
  function onNavigate(view) { activeView = view; ensureFrame(); }
  function fieldsChanged(kind) {
    dirty[kind] = true; rawDirty[kind] = false;
    $(`${kind}-data`).value = JSON.stringify(kind === 'assembly' ? assembly : calibration, null, 2); stash();
  }
  function partOptions(ids) {
    const group = ids?.length > 1;
    return (group ? `<option value="__group__" selected disabled>已关联 ${ids.length} 个零件（更改将替换为单件）</option>` : '') +
      '<option value="">不关联模型零件</option>' + (metadata?.model.parts || []).map(p => `<option value="${esc(p.id)}" ${!group && ids?.includes(p.id) ? 'selected' : ''}>${esc(p.assembly)} / ${esc(p.name)}</option>`).join('');
  }
  function checkRow(check, index) {
    return `<article class="assembly-check" data-check="${index}"><div class="check-number">${String(index+1).padStart(2,'0')}</div><div class="check-fields"><input data-field="title" value="${esc(check.title)}" aria-label="检查项 ${index+1} 名称" placeholder="例如：检查右壳与舵机的间隙"><div class="check-controls"><select data-field="status" aria-label="检查项 ${index+1} 状态">${options(statuses,check.status || 'pending')}</select><select data-field="part" aria-label="检查项 ${index+1} 关联零件">${partOptions(check.part_ids)}</select>${check.part_ids?.length ? `<button data-model-part="${esc(check.part_ids[0])}" type="button">在 3D 中定位 ↗</button>` : ''}</div><textarea rows="2" data-field="evidence" aria-label="检查项 ${index+1} 证据" placeholder="每行一条实测记录或照片路径；通过必须有证据">${esc((check.evidence || []).join('\n'))}</textarea>${check.part_ids?.length > 1 ? `<small>关联 ${check.part_ids.length} 个模型实例，可在 JSON 中查看全部。</small>` : ''}</div><button class="row-remove" data-remove-check="${index}" aria-label="删除检查项 ${index+1}">×</button></article>`;
  }
  function renderAssembly() {
    const data = assembly || emptyAssembly(), checks = data.checks || [];
    $('assembly-editor').innerHTML = `<div class="editor-heading"><div><span class="eyebrow">ASSEMBLY PLAN</span><p>从一个部件开始，把检查与证据放在一起。</p></div><button data-view="visual">在 3D 中选择零件 ↗</button></div><div class="form-grid"><label>本次装配名称<input id="assembly-title" value="${esc(data.title)}" placeholder="例如：第一次结构试装"></label><label>资料来源（每行一条）<textarea id="assembly-sources" rows="2">${esc((data.source_refs || []).join('\n'))}</textarea></label></div><div class="editor-section-title"><h3>检查清单 <span class="count">${checks.length}</span></h3><button id="assembly-add-row">＋ 添加检查项</button></div><div class="assembly-progress">${checks.length ? checks.map(c => `<span class="${esc(c.status || 'pending')}" title="${esc(c.title)} · ${esc(statuses[c.status] || '待检查')}"></span>`).join('') : '<span></span>'}</div><p class="muted">${checks.filter(c=>c.status === 'passed').length} 项记录为通过 / ${checks.length} 项 · 人工检查证据由服务端复核</p><div id="assembly-checks">${checks.length ? checks.map(checkRow).join('') : '<div class="editor-empty">从 3D 中选一个零件，或添加你的第一项装配检查。</div>'}</div><div class="editor-section-title"><h3>实际物料</h3><button id="material-add-row">＋ 添加物料</button></div><p class="muted">模型实例用于定位，实际采购数量由你填写。</p><div class="table-scroll"><table class="editor-table"><thead><tr><th>物料 / 规格</th><th>数量</th><th>状态</th><th>来源 / 单价</th><th></th></tr></thead><tbody id="material-rows">${(data.materials || []).map((m,i) => `<tr data-material-row="${i}"><td><input data-field="name" value="${esc(m.name)}" aria-label="物料 ${i+1} 名称" placeholder="物料名称"><input data-field="spec" value="${esc(m.spec)}" aria-label="物料 ${i+1} 规格" placeholder="规格 / 型号"></td><td><input type="number" min="0.001" step="any" data-field="quantity" value="${esc(m.quantity)}" aria-label="物料 ${i+1} 数量" placeholder="待填写"></td><td><select data-field="status" aria-label="物料 ${i+1} 状态">${options(materialStatuses,m.status || 'unknown')}</select></td><td><input data-field="source" value="${esc(m.source)}" aria-label="物料 ${i+1} 来源" placeholder="资料或采购来源"><input type="number" min="0" step="any" data-field="price" value="${esc(m.price)}" aria-label="物料 ${i+1} 单价" placeholder="单价（可选）"></td><td><button data-remove-material="${i}" class="row-remove" aria-label="删除物料 ${i+1}">×</button></td></tr>`).join('')}</tbody></table></div><label>装配备注<textarea id="assembly-notes" rows="2" placeholder="记录实测尺寸、间隙与尚未解决的问题">${esc(data.notes)}</textarea></label>`;
    $('assembly-data').value = JSON.stringify(data,null,2);
  }
  function jointRow(joint, index) {
    const limits = joint.limits_deg || [], span = Number(limits[1]) - Number(limits[0]);
    const position = joint.zero_deg != null && span > 0 ? Math.max(0,Math.min(100,(joint.zero_deg-limits[0])/span*100)) : null;
    return `<tr data-joint="${index}"><td><input data-field="name" value="${esc(joint.name)}" aria-label="关节 ${index+1} 名称" placeholder="实际关节名称"></td><td><input type="number" min="0" max="253" step="1" data-field="id" value="${esc(joint.id)}" aria-label="关节 ${index+1} ID" placeholder="ID"></td><td><select data-field="direction" aria-label="关节 ${index+1} 方向">${options({'':'待确认','1':'＋ 正向','-1':'− 反向'},joint.direction ?? '')}</select></td><td><input type="number" step="any" data-field="zero_deg" value="${esc(joint.zero_deg)}" aria-label="关节 ${index+1} 零位" placeholder="待测量"></td><td><div class="limits-inputs"><input type="number" step="any" data-field="lower" value="${esc(limits[0])}" aria-label="关节 ${index+1} 下限" placeholder="下限"><span>→</span><input type="number" step="any" data-field="upper" value="${esc(limits[1])}" aria-label="关节 ${index+1} 上限" placeholder="上限"></div><div class="joint-range" aria-hidden="true">${position == null ? '' : `<i style="left:${position}%"></i>`}</div></td><td><button data-remove-joint="${index}" class="row-remove" aria-label="删除关节 ${index+1}">×</button></td></tr>`;
  }
  function renderCalibration() {
    const data = calibration || emptyCalibration();
    $('calibration-editor').innerHTML = `<div class="editor-heading"><div><span class="eyebrow">JOINT MAP</span><p>按实物填写 ID、方向与测量值。所有角度单位为 °。</p></div><button id="joint-add-row">＋ 添加关节</button></div><div class="table-scroll"><table class="editor-table joint-table"><thead><tr><th>关节名称</th><th>舵机 ID</th><th>方向</th><th>零位 °</th><th>下限 → 上限 °</th><th></th></tr></thead><tbody>${(data.joints || []).map(jointRow).join('')}</tbody></table></div>${data.joints?.length ? '' : '<div class="editor-empty">还没有关节记录。请添加关节并填写实际标定值。</div>'}<div class="imu-editor"><div class="imu-axis" aria-hidden="true"><svg viewBox="0 0 130 105"><path d="M62 60L112 78M62 60L22 90M62 60L62 13" fill="none" stroke="#9aa58c" stroke-width="2"/><circle cx="62" cy="60" r="5" fill="#798c5d"/><text x="115" y="84">X</text><text x="9" y="102">Y</text><text x="59" y="10">Z</text></svg><small>坐标轴示意</small></div><div class="imu-fields"><label class="check-row"><input type="checkbox" id="imu-enabled" ${data.imu ? 'checked' : ''}>记录 IMU 安装姿态</label><div class="form-grid" ${data.imu ? '' : 'hidden'} id="imu-values"><label>参考坐标系<input id="imu-frame" value="${esc(data.imu?.frame)}" placeholder="例如 base_link"></label>${['Roll','Pitch','Yaw'].map((name,i) => `<label>${name} °<input id="imu-angle-${i}" type="number" step="any" value="${esc(data.imu?.rpy_deg?.[i])}" placeholder="待测量"></label>`).join('')}</div></div></div><div class="form-grid"><label>测试电压 V（可选）<input id="calibration-voltage" type="number" step="any" value="${esc(data.conditions?.voltage_v)}" placeholder="不可用时留空"></label><label>测试温度 °C（可选）<input id="calibration-temperature" type="number" step="any" value="${esc(data.conditions?.temperature_c)}" placeholder="不可用时留空"></label><label>记录 / 验证人<input id="calibration-operator" value="${esc(data.operator)}" placeholder="实际操作人"></label><label class="check-row"><input type="checkbox" id="calibration-verified" ${data.verified ? 'checked' : ''}>我已完成实物标定验证</label></div><label>标定备注<textarea id="calibration-notes" rows="2" placeholder="适用条件、测量工具与异常">${esc(data.notes)}</textarea></label>`;
    $('calibration-data').value = JSON.stringify(data,null,2);
  }
  function renderForms() { renderAssembly(); renderCalibration(); }
  function setupForm(kind) {
    const area = $(`${kind}-data`), label = area.closest('label'), details = label.closest('details') || document.createElement('details');
    if (!details.parentElement) { details.className = 'advanced'; details.innerHTML = '<summary>高级：查看或导入 JSON</summary>'; label.before(details); details.append(label); }
    const apply = document.createElement('button'); apply.textContent = '将 JSON 应用到表单'; details.append(apply);
    function parseRaw() {
      const data = JSON.parse(area.value);
      if (!data || typeof data !== 'object' || !Array.isArray(kind === 'assembly' ? data.checks : data.joints)) throw new Error(kind === 'assembly' ? '装配数据需要 checks 数组' : '标定数据需要 joints 数组');
      const rows = kind === 'assembly' ? data.checks : data.joints;
      if (rows.some(row => !row || typeof row !== 'object' || Array.isArray(row))) throw new Error('每个条目必须为对象');
      if (kind === 'assembly' && ['source_refs','materials'].some(key => data[key] != null && !Array.isArray(data[key]))) throw new Error('source_refs 与 materials 必须为数组');
      if (kind === 'assembly' && rows.some(row => ['part_ids','evidence'].some(key=>row[key] != null && !Array.isArray(row[key])))) throw new Error('part_ids 与 evidence 必须为数组');
      if (kind === 'assembly' && (data.materials || []).some(row=>!row || typeof row !== 'object')) throw new Error('物料必须为对象');
      if (kind === 'calibration' && rows.some(row => row.limits_deg != null && !Array.isArray(row.limits_deg))) throw new Error('limits_deg 必须为数组');
      if (kind === 'assembly') assembly = data; else calibration = data;
      fieldsChanged(kind); kind === 'assembly' ? renderAssembly() : renderCalibration();
    }
    area.addEventListener('input', () => { rawDirty[kind] = true; dirty[kind] = true; stash(); });
    apply.onclick = () => { try { parseRaw(); } catch (error) { window.Studio.result(`JSON 格式错误：${error.message}`); } };
    // Replace only the record-save handler; this never invokes a device operation.
    $(`${kind}-save`).onclick = async () => {
      const button = $(`${kind}-save`), token = generation, id = project;
      if (!id) return window.Studio.result('请先选择项目');
      if (button.disabled) return;
      try {
        if (rawDirty[kind]) parseRaw();
        const data = clone(kind === 'assembly' ? assembly : calibration), before = JSON.stringify(data);
        button.disabled = true; button.setAttribute('aria-busy','true');
        const result = await request(`/api/projects/${id}/${kind === 'assembly' ? 'assemblies' : 'calibrations'}`, {method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({data})});
        if (generation !== token) return;
        if (JSON.stringify(kind === 'assembly' ? assembly : calibration) === before) { dirty[kind] = false; stash(); }
        $('status').textContent = JSON.stringify(result,null,2); window.Studio.result(result); $('report').click();
      } catch (error) { if (generation === token) window.Studio.result(`保存失败：${error.message}`); }
      finally { button.disabled = false; button.removeAttribute('aria-busy'); }
    };
  }
  function init() {
    assembly = emptyAssembly(); calibration = emptyCalibration(); renderForms(); setupForm('assembly'); setupForm('calibration');
    request('/api/visual/model').then(data => { metadata = data; if (!rawDirty.assembly) renderAssembly(); ensureFrame(); }).catch(error => state(`模型清单读取失败：${error.message}`));
    $('visual-name').addEventListener('input', changed);
    $('visual-save').onclick = async () => {
      if (!api || !project || !visualLoaded) return;
      const token = generation, id = project, data = snapshot(), before = JSON.stringify(data);
      if (!$('visual-name').value.trim()) return state('请填写外观方案名称');
      $('visual-save').disabled = true;
      try {
        const result = await request(`/api/projects/${id}/visual-configs`, {method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({data,expected_revision:revision})});
        if (generation !== token) return;
        versions.unshift(result); revision = result.revision;
        if (JSON.stringify(snapshot()) === before) visualDirty = false;
        stash(); renderVersions(); state(`已保存到当前项目 · v${revision}${visualDirty ? ' · 仍有新修改' : ''}`);
      } catch (error) { if (generation === token) state(`保存失败：${error.message}。草稿已保留。`); }
      finally { if (generation === token) $('visual-save').disabled = false; }
    };
    $('visual-load-version').onclick = () => {
      const item = versions.find(v => String(v.revision) === $('visual-version').value); if (!item) return;
      try { applyDraft(item.data); revision = versions[0].revision; visualDirty = true; stash(); state(`已载入 v${item.revision} 为草稿，保存将创建新版本`); }
      catch (error) { state(`版本载入失败：${error.message}`); }
    };
    $('visual-reload').onclick = async () => {
      const token = generation, id = project; if (!id) return;
      try {
        const data = await request(`/api/projects/${id}/visual-configs`); if (generation !== token) return;
        versions = data.versions; renderVersions();
        if (!visualLoaded) { await loadProjectVisual(token,id,{visual:visualDraft,revision}); return; }
        state('项目版本已重新读取；当前草稿保留。可选择版本并载入。');
      } catch (error) { if (generation === token) state(`读取失败：${error.message}`); }
    };
    $('visual-add-check').onclick = () => {
      if (!selected || !project) return;
      assembly.model_binding = metadata.reference;
      assembly.checks ||= [];
      assembly.checks.push({id:`part-${crypto.randomUUID().slice(0,8)}`,title:`${selected.name} · 试装检查`,status:'pending',evidence:[],part_ids:[selected.id]});
      fieldsChanged('assembly'); renderAssembly(); window.Studio.navigate('assembly','assembly');
    };
    $('assembly-editor').addEventListener('input', event => {
      const input = event.target, row = input.closest('[data-check]'), material = input.closest('[data-material-row]'), field = input.dataset.field;
      if (row) {
        const check = assembly.checks[Number(row.dataset.check)];
        if (field === 'evidence') check.evidence = split(input.value);
        else if (field === 'part') {
          if (input.value) { check.part_ids = [input.value]; assembly.model_binding = metadata.reference; }
          else delete check.part_ids;
        } else check[field] = input.value;
      } else if (material) {
        const item = assembly.materials[Number(material.dataset.materialRow)];
        if (['quantity','price'].includes(field)) { if (input.value === '') delete item[field]; else item[field] = number(input.value); }
        else if (!input.value && ['spec','source'].includes(field)) delete item[field];
        else item[field] = input.value;
      } else if (input.id === 'assembly-title') assembly.title = input.value;
      else if (input.id === 'assembly-sources') assembly.source_refs = split(input.value);
      else if (input.id === 'assembly-notes') assembly.notes = input.value;
      fieldsChanged('assembly');
    });
    $('assembly-editor').addEventListener('change', event => { if (['part','status'].includes(event.target.dataset.field)) renderAssembly(); });
    $('assembly-editor').addEventListener('click', event => {
      const button = event.target.closest('button'); if (!button) return;
      if (button.dataset.modelPart) { window.Studio.navigate('visual'); const target = button.dataset.modelPart; if (api) api.selectPart(target); else { const current = generation; const timer = setInterval(() => { if (current !== generation) clearInterval(timer); else if (api) { api.selectPart(target); clearInterval(timer); } },100); setTimeout(()=>clearInterval(timer),15000); } return; }
      if (button.id === 'assembly-add-row') (assembly.checks ||= []).push({id:crypto.randomUUID(),title:'',status:'pending',evidence:[]});
      else if (button.id === 'material-add-row') (assembly.materials ||= []).push({name:'',status:'unknown'});
      else if (button.dataset.removeCheck !== undefined) assembly.checks.splice(Number(button.dataset.removeCheck),1);
      else if (button.dataset.removeMaterial !== undefined) assembly.materials.splice(Number(button.dataset.removeMaterial),1);
      else return;
      fieldsChanged('assembly'); renderAssembly();
    });
    $('calibration-editor').addEventListener('input', event => {
      const input = event.target, row = input.closest('[data-joint]'), field = input.dataset.field;
      if (row) {
        const joint = calibration.joints[Number(row.dataset.joint)];
        if (field === 'name') joint.name = input.value;
        else if (['lower','upper'].includes(field)) { joint.limits_deg ||= [null,null]; joint.limits_deg[field === 'lower' ? 0 : 1] = number(input.value); }
        else joint[field] = number(input.value);
      } else if (input.id === 'imu-enabled') {
        if (input.checked) calibration.imu = {frame:'',rpy_deg:[null,null,null]}; else delete calibration.imu;
        fieldsChanged('calibration'); renderCalibration(); return;
      } else if (input.id === 'imu-frame') calibration.imu.frame = input.value;
      else if (input.id.startsWith('imu-angle-')) calibration.imu.rpy_deg[Number(input.id.slice(-1))] = number(input.value);
      else if (['calibration-voltage','calibration-temperature'].includes(input.id)) {
        const key = input.id.endsWith('voltage') ? 'voltage_v' : 'temperature_c'; calibration.conditions ||= {};
        if (input.value === '') delete calibration.conditions[key]; else calibration.conditions[key] = number(input.value);
      } else if (input.id === 'calibration-operator') calibration.operator = input.value;
      else if (input.id === 'calibration-verified') calibration.verified = input.checked;
      else if (input.id === 'calibration-notes') calibration.notes = input.value;
      fieldsChanged('calibration');
    });
    $('calibration-editor').addEventListener('input', event => {
      const row = event.target.closest('[data-joint]'); if (!row) return;
      const joint = calibration.joints[Number(row.dataset.joint)], limits = joint.limits_deg || [], range = row.querySelector('.joint-range');
      const span = limits[0] != null && limits[1] != null ? limits[1]-limits[0] : 0;
      const position = joint.zero_deg != null && span > 0 ? Math.max(0,Math.min(100,(joint.zero_deg-limits[0])/span*100)) : null;
      range.innerHTML = position == null ? '' : `<i style="left:${position}%"></i>`;
    });
    $('calibration-editor').addEventListener('click', event => {
      const button = event.target.closest('button'); if (!button) return;
      if (button.id === 'joint-add-row') (calibration.joints ||= []).push({name:'',id:null,direction:null,zero_deg:null,limits_deg:[null,null]});
      else if (button.dataset.removeJoint !== undefined) calibration.joints.splice(Number(button.dataset.removeJoint),1);
      else return;
      fieldsChanged('calibration'); renderCalibration();
    });
    window.addEventListener('pagehide', stash);
    window.addEventListener('beforeunload', stash);
  }
  function addGuideCheck(title, ids, reference) {
    if (!project || !metadata || reference.manifest_sha256 !== metadata.reference.manifest_sha256) throw Error('请等待项目模型加载，再添加检查');
    if (!Array.isArray(ids) || ids.some(id=>!metadata.model.parts.some(p=>p.id===id))) throw Error('教程包含未知零件');
    assembly.model_binding=metadata.reference;
    assembly.checks ||= [];
    assembly.checks.push({id:`guide-${crypto.randomUUID().slice(0,8)}`,title:`${title} · 安装验收`,status:'pending',evidence:[],part_ids:ids});
    fieldsChanged('assembly');renderAssembly();window.Studio.navigate('assembly','assembly');
  }
  return {init,reset,receiveReport,onNavigate,addGuideCheck};
})();
