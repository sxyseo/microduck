/* Read-only HD-1910 servo ID reference from microduck-servo-guide, served by the local
   service under /servo-guide. The labelled IDs are the project joint numbering by
   position, not values read from a real bus; nothing here opens a serial port or
   records project evidence. The 3D model (~20 MB) loads only when requested. */
window.ServoGuideStudio = (() => {
  const $ = id => document.getElementById(id);
  const esc = value => String(value ?? '').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  let payload = null, frame = null;

  const groupNames = {left: '左腿', right: '右腿', head: '头颈'};
  // The page may be hosted anywhere (e.g. Pages); guide assets always live on the local service.
  const guideUrl = path => StudioAPI.url(path);

  function referenceTable() {
    const rows = payload.reference.servos.map(s =>
      `<tr><td><code>${esc(s.id)}</code></td><td>${esc(s.label)}</td><td>${esc(groupNames[s.group] || s.group)}</td><td class="muted">${esc(s.description)}</td></tr>`).join('');
    return `<div class="servo-ref-table"><table><thead><tr><th>ID</th><th>名称</th><th>区域</th><th>位置（装配对照）</th></tr></thead><tbody>${rows}</tbody></table></div>
<p class="muted">大腿同板配对：右侧 12 / 13，左侧 22 / 23；11 / 21 靠躯干负责侧摆，12 / 22 在大腿负责俯仰，不要互换。</p>`;
  }

  function fillBenchQuickRef() {
    const host = $('servoguide-quickref');
    if (!host || !payload?.available || !payload.reference) return;
    host.innerHTML = `<summary>HD-1910 版编号速查 · 装配对照，不是实机已写入的 ID</summary>${referenceTable()}<p class="muted">完整 3D 对照见“装配与标定 → 舵机编号 3D 对照”，或打开 <a href="${esc(guideUrl(payload.index || '/servo-guide/'))}" target="_blank" rel="noopener">/servo-guide/</a>。</p>`;
    host.hidden = false;
  }

  function renderAssemblyCard() {
    const body = $('servoguide-body');
    if (!body) return;
    if (!payload || !payload.available) {
      body.innerHTML = `<p class="muted">编号对照资源未找到，此功能不可用；其他工作台功能不受影响。</p>${payload?.searched ? `<details class="advanced"><summary>已查找的位置</summary><ul>${payload.searched.map(p => `<li><code>${esc(p)}</code></li>`).join('')}</ul></details>` : ''}`;
      return;
    }
    if (!payload.reference) {
      body.innerHTML = `<p class="inline-note warning">对照资源已找到，但模型清单解析失败：${esc(payload.reference_error || '未知原因')}。3D 页面可能同样无法载入舵机标注。</p>`;
      return;
    }
    const r = payload.reference;
    body.innerHTML = `<p class="muted">${esc(r.source || '来源未标注')} · ${esc(String(r.servo_count))} 颗舵机 · ${esc(String(r.part_instances))} 个零件实例。编号是项目关节编号的位置对照，不代表实机已写入的 ID；装配姿态也不是零位，不能据此归零或执行动作。</p>
${referenceTable()}
<p><button id="servoguide-load" class="primary">载入 3D 对照（首次约 20 MB）</button>
<a class="servo-guide-newtab" href="${esc(guideUrl(payload.assembly_viewer || '/servo-guide/assembly.html'))}" target="_blank" rel="noopener">在新窗口打开完整页面 ↗</a></p>
<p class="guide-model-note">模型 <a href="${esc(guideUrl('/servo-guide/credits.html'))}" target="_blank" rel="noopener">CC BY-NC-SA 4.0 · 来源与许可</a> · 纯查看工具，不连接舵机。</p>
<div id="servoguide-frame-slot"></div>`;
    $('servoguide-load').onclick = () => {
      if (frame) return;
      frame = document.createElement('iframe');
      frame.title = 'MicroDuck 舵机装配 3D 对照';
      frame.className = 'servo-guide-frame';
      frame.src = guideUrl(payload.assembly_viewer || '/servo-guide/assembly.html');
      $('servoguide-frame-slot').replaceChildren(frame);
      $('servoguide-load').disabled = true;
      $('servoguide-load').textContent = '3D 模型载入中…';
      frame.onload = () => { $('servoguide-load').textContent = '3D 对照已载入'; };
    };
  }

  async function init() {
    const benchHost = document.createElement('details');
    benchHost.id = 'servoguide-quickref';
    benchHost.className = 'advanced';
    benchHost.hidden = true;
    $('card-probe').append(benchHost);
    try {
      const response = await StudioAPI.fetch('/api/servo-guide');
      payload = await response.json();
    } catch {
      payload = {available: false};
    }
    renderAssemblyCard();
    fillBenchQuickRef();
  }

  return {init};
})();
