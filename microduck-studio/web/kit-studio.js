/* Community-kit board debugger bridge. The HLS servo debugger runs on the duck's core
   board and owns the serial bus; studio only checks reachability (server-side, GET only)
   and turns the recorded servo ID map into a calibration draft. Writing registers,
   connecting the port and calibrating happen in the board tool's own page. */
window.KitStudio = (() => {
  const $ = id => document.getElementById(id);
  const esc = value => String(value ?? '').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const KEY = 'microduckKitUrl';
  let project = null, lastStatus = null;

  const request = async (url, body) => {
    const r = await StudioAPI.fetch(url, body === undefined ? {} : {method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
    const j = await r.json();
    if (!r.ok) throw Error(typeof j.detail === 'string' ? j.detail : '请求未完成');
    return j;
  };

  function reset() { project = null; lastStatus = null; }

  function receiveReport(report) { project = report.project.id; }

  function savedUrl() { try { return localStorage.getItem(KEY) || ''; } catch { return ''; } }

  function renderStatus(value) {
    lastStatus = value;
    const box = $('kit-status');
    if (value.reachable) {
      const t = value.tool || {};
      const count = t.joint_count;
      box.innerHTML = `<strong>核心板调试台在线</strong> · <a href="${esc(value.ui)}" target="_blank" rel="noopener">打开 ${esc(value.base_url)}</a>
${count !== null && count !== undefined ? ` · 关节表 ${esc(String(count))} 台${t.expected_joint_count && count !== t.expected_joint_count ? `<span class="pill warning">预期 ${esc(String(t.expected_joint_count))}</span>` : ''}` : ''}
<p class="muted">${esc(value.boundary_note || '')}</p>`;
      box.className = 'inline-note';
    } else {
      box.innerHTML = `<strong>核心板调试台不可达</strong><p class="muted">${esc(value.note || '')}${value.error ? `（${esc(value.error)}）` : ''}</p><p class="muted">${esc(value.boundary_note || '')}</p>`;
      box.className = 'inline-note warning';
    }
    box.hidden = false;
  }

  function buildDraft(entries) {
    if (!entries || !entries.length) throw Error('先在「整机称重与 ID 对照」保存 ID 映射，再生成标定草稿。');
    return {
      joints: entries.map(entry => ({
        name: entry.joint,
        id: entry.servo_id,
        direction: 1,
        zero_deg: 0.0,
        limits_deg: [-120.0, 120.0],
      })),
      operator: '',
      verified: false,
      notes: '草稿：由 ID 映射生成。direction / zero_deg / limits_deg 全部是占位值，必须按核心板校准台逐台实测修改后再保存；verified 需要操作者核验后勾选。',
    };
  }

  function init() {
    $('kit-url').value = savedUrl();
    $('kit-check').onclick = guard(async () => {
      const url = $('kit-url').value.trim();
      try { if (url) localStorage.setItem(KEY, url); else localStorage.removeItem(KEY); } catch {}
      const value = await request(`/api/community-kit/status${url ? `?base_url=${encodeURIComponent(url)}` : ''}`);
      renderStatus(value);
    });
    $('kit-open').onclick = () => {
      const url = ($('kit-url').value.trim() || lastStatus?.base_url || '').replace(/\/+$/, '');
      if (!/^https?:\/\//.test(url)) return status('先填写调试台地址并检查状态。', true);
      window.open(url + '/', '_blank', 'noopener');
    };
    $('kit-draft').onclick = guard(async () => {
      if (!project) return status('先选择项目。', true);
      const maps = await request(`/api/projects/${project}/servo-id-maps`);
      const draft = buildDraft(maps.id_maps[0]?.data?.entries || []);
      $('calibration-data').value = JSON.stringify(draft, null, 2);
      window.Studio.navigate('assembly', 'calibration');
      window.Studio.result('已按 ID 映射生成 15 关节标定草稿：占位值必须逐台实测修改后再保存。');
    });
  }

  const status = (message, warning = false) => {
    const box = $('kit-status');
    box.className = `inline-note${warning ? ' warning' : ''}`;
    box.textContent = message;
    box.hidden = false;
  };
  const guard = fn => async () => { try { await fn(); } catch (e) { status(e.message, true); } };

  return {init, reset, receiveReport};
})();
