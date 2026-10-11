/* IMU bench panel. The imu_to_dxl node rides the servo bus as ID 200, so the browser reads
   attitude straight off the same bus with Web Serial — no robotd, no backend, and nothing here
   is recorded as project evidence. Register contract is the FT6 15-byte block at 56..70
   (Microduck-kissqy firmware/firmware/imu-source/README_FT6_SYNC15.md; microduck-community-kit
   firmware/v1 docs/imu_to_dxl_protocol.md §6): gyro xyz i16 LE ±500 dps (17.5 mdps/LSB),
   quaternion xyz IEEE half LE with w = √(1−x²−y²−z²), sample count, FT6 status byte
   (bit0 not-ready, bit1 stale >30 ms, bit2 error, bit3 ≥5 fresh samples since last read,
   bit4–7 reserved), one reserved 0 byte. Bus rules: half-duplex, one master at a time — stop
   robotd before connecting, and this panel shares the serial port with the URT2 console. */
window.ImuPanel = (() => {
  const $ = id => document.getElementById(id);
  const ADDR_BLOCK = 56, BLOCK_LEN = 15, ADDR_INFO = 0, INFO_LEN = 4;
  const GYRO_DPS_PER_COUNT = 0.0175;
  const DRIFT_LIMIT_DPS = 2.865; // 0.05 rad/s,docs/deep-dive/68 五步数字验收门槛
  const CHART_POINTS = 240, CSV_ROWS = 6000;
  const CONNECTED_BUTTONS = ['imu-disc', 'imu-stream', 'imu-drift'];
  let port = null, reader = null, keepReading = false, buf = new Uint8Array(0);
  let sid = 200, txN = 0, toN = 0, streaming = false;
  let lastQuat = null, counts = [], reservedWarned = false;
  const chart = {roll: [], pitch: [], gx: [], gy: [], gz: []};
  let csv = [], rateCount = 0, rateAt = 0, lastDraw = 0, drift = null, logEntries = [];

  const sleep = ms => new Promise(r => setTimeout(r, ms));
  const u16 = (lo, hi) => lo | (hi << 8);
  const s16 = v => (v >= 0x8000 ? v - 0x10000 : v);
  const half = (lo, hi) => {
    const h = lo | (hi << 8), sign = h & 0x8000 ? -1 : 1, exp = (h >> 10) & 0x1F, frac = h & 0x3FF;
    if (exp === 0x1F) return frac ? NaN : sign * Infinity;
    if (exp === 0) return sign * frac * 2 ** -24;
    return sign * (frac / 1024 + 1) * 2 ** (exp - 15);
  };
  const deg = rad => rad * 180 / Math.PI;
  const f1 = v => v.toFixed(1), f2 = v => v.toFixed(2), f3 = v => v.toFixed(3);

  function log(message, isError) {
    logEntries.push({time: new Date().toLocaleTimeString('zh-CN', {hour12: false}), text: message});
    if (logEntries.length > 500) logEntries.shift();
    const line = document.createElement('div');
    if (isError) line.className = 'err';
    const time = document.createElement('span');
    time.className = 't';
    time.textContent = `[${logEntries[logEntries.length - 1].time}] `;
    line.append(time, document.createTextNode(message));
    const box = $('imu-log');
    box.appendChild(line);
    box.scrollTop = box.scrollHeight;
  }

  /* Errors stay in the console log; handlers stay synchronous so nothing re-enables the
     connect-gated buttons behind this card's back. */
  const guard = fn => (...args) => {
    try {
      const result = fn(...args);
      if (result instanceof Promise) result.catch(error => log(`✗ ${error.message}`, true));
    } catch (error) { log(`✗ ${error.message}`, true); }
  };

  const packet = (id, instr, params = []) => {
    const body = [id, params.length + 2, instr, ...params];
    let sum = 0;
    for (const b of body) sum += b;
    return new Uint8Array([0xFF, 0xFF, ...body, (~sum) & 0xFF]);
  };
  async function transact(id, instr, params = [], rxParams = 0) {
    if (!port) throw Error('未连接');
    txN++;
    const writer = port.writable.getWriter();
    await writer.write(packet(id, instr, params));
    writer.releaseLock();
    const want = 6 + rxParams, deadline = performance.now() + 300;
    while (performance.now() < deadline) {
      for (let i = 0; i <= buf.length - want; i++) {
        if (buf[i] === 0xFF && buf[i + 1] === 0xFF && buf[i + 2] === id) {
          const total = 4 + buf[i + 3];
          if (i + total <= buf.length) {
            let sum = 0;
            for (let j = i + 2; j < i + total - 1; j++) sum += buf[j];
            if (((~sum) & 0xFF) === buf[i + total - 1]) {
              const got = buf.slice(i + 5, i + total - 1);
              buf = buf.slice(i + total);
              if (got.length !== rxParams) throw Error(`应答参数 ${got.length}B,期望 ${rxParams}B`);
              return got;
            }
          }
        }
      }
      await sleep(4);
    }
    toN++;
    throw Error('IMU 节点无应答(ID/线序/波特率/电源?)');
  }

  function setPill(id, text, good) {
    const pill = $(id);
    pill.textContent = text;
    pill.className = `pill ${good ? 'passed' : 'insufficient_evidence'}`;
  }
  function resetPills() {
    setPill('imu-pill-ready', '—', false);
    setPill('imu-pill-stale', '—', false);
    setPill('imu-pill-frozen', '—', false);
  }
  function setConnected(on) {
    for (const id of CONNECTED_BUTTONS) $(id).disabled = !on;
    const state = $('imu-state');
    state.textContent = on ? '已连接' : '未连接';
    state.className = `pill ${on ? 'passed' : 'insufficient_evidence'}`;
    if (!on) {
      resetPills();
      $('imu-rate-now').textContent = '—';
    }
  }

  function statusText(st) {
    const bits = [[0, '未就绪'], [1, '过期>30ms'], [2, '错误'], [3, '新样本≥5']];
    const hits = bits.filter(([bit]) => st & (1 << bit)).map(([, label]) => label);
    if (st & 0xF0) hits.push(`保留位${((st >> 4) & 0xF).toString(2).padStart(4, '0')}`);
    return hits.length ? hits.join(' · ') : '正常';
  }

  function drawChart(svgId, series) {
    const svg = $(svgId);
    svg.replaceChildren();
    const all = series.flatMap(s => s.data);
    if (!all.length) return;
    let low = Math.min(...all), high = Math.max(...all);
    const pad = (high - low) * 0.1 || 0.5;
    low -= pad; high += pad;
    const span = high - low, n = Math.max(...series.map(s => s.data.length)) - 1 || 1;
    for (const s of series) {
      const points = s.data.map((v, i) => `${8 + i * 284 / n},${92 - (v - low) * 84 / span}`).join(' ');
      const line = document.createElementNS('http://www.w3.org/2000/svg', 'polyline');
      line.setAttribute('points', points);
      line.setAttribute('fill', 'none');
      line.setAttribute('stroke', s.color);
      line.setAttribute('stroke-width', '2');
      svg.appendChild(line);
    }
  }
  function drawCharts() {
    drawChart('imu-chart-att', [{data: chart.roll, color: '#17633a'}, {data: chart.pitch, color: '#2563a8'}]);
    drawChart('imu-chart-gyro', [{data: chart.gx, color: '#17633a'}, {data: chart.gy, color: '#2563a8'}, {data: chart.gz, color: '#c26a1c'}]);
  }

  function startDrift() {
    if (!streaming) return log('先连接并开始遥测,再跑静态零漂检查。', true);
    if (drift) return;
    drift = {end: performance.now() + 10000, n: 0, sx: 0, sy: 0, sz: 0};
    $('imu-drift').disabled = true;
    log('静态零漂检查开始:保持模块完全静止 10 秒……');
  }
  function finishDrift() {
    const gx = drift.sx / drift.n, gy = drift.sy / drift.n, gz = drift.sz / drift.n;
    const bad = [gx, gy, gz].some(v => Math.abs(v) > DRIFT_LIMIT_DPS);
    log(`零漂结果(n=${drift.n}):x ${f2(gx)} y ${f2(gy)} z ${f2(gz)} °/s —— ${bad ? `✗ 超出 ±${DRIFT_LIMIT_DPS} °/s(0.05 rad/s)门槛` : '✓ 通过(±0.05 rad/s 内)'}`, bad);
    drift = null;
    $('imu-drift').textContent = '静态零漂检查(10s)';
    $('imu-drift').disabled = !port;
  }

  function onSample(d) {
    rateCount++;
    const gx = s16(u16(d[0], d[1])) * GYRO_DPS_PER_COUNT;
    const gy = s16(u16(d[2], d[3])) * GYRO_DPS_PER_COUNT;
    const gz = s16(u16(d[4], d[5])) * GYRO_DPS_PER_COUNT;
    let qx = half(d[6], d[7]), qy = half(d[8], d[9]), qz = half(d[10], d[11]);
    const cnt = d[12], st = d[13];
    if (d[14] !== 0 && !reservedWarned) {
      reservedWarned = true;
      log(`⚠ 保留字节=${d[14]}(FT6 契约应为 0),节点固件可能不是 FT6 人格,状态位解读未必适用。`, true);
    }
    // 全零四元数或未就绪位 = 融合尚未收敛:沿用上一份有效姿态,不要把全 0 当成单位四元数。
    const norm2 = qx * qx + qy * qy + qz * qz;
    let valid = true;
    if ((st & 0x01) || (!qx && !qy && !qz) || norm2 > 1.001) {
      valid = false;
      if (lastQuat) ({x: qx, y: qy, z: qz} = lastQuat);
      else qx = qy = qz = null; // 还没有任何有效姿态:曲线不画假零。
    } else {
      const w = Math.sqrt(Math.max(0, 1 - norm2));
      const n = Math.hypot(qx, qy, qz, w);
      qx /= n; qy /= n; qz /= n;
      lastQuat = {x: qx, y: qy, z: qz, w};
    }
    const qw = lastQuat ? lastQuat.w : null;
    const roll = qw === null ? null : deg(Math.atan2(2 * (qw * qx + qy * qz), 1 - 2 * (qx * qx + qy * qy)));
    const pitch = qw === null ? null : deg(Math.asin(Math.min(1, Math.max(-1, 2 * (qw * qy - qz * qx)))));
    const yaw = qw === null ? null : deg(Math.atan2(2 * (qw * qz + qx * qy), 1 - 2 * (qy * qy + qz * qz)));
    // 连续 3 次相同计数 = 采样停住(255→0 回绕属正常)。
    counts.push(cnt);
    if (counts.length > 3) counts.shift();
    const frozen = counts.length === 3 && counts[0] === counts[1] && counts[1] === counts[2];

    setPill('imu-pill-ready', valid ? '姿态就绪' : '融合未就绪', valid);
    setPill('imu-pill-stale', st & 0x02 ? '数据过期' : '数据新鲜', !(st & 0x02));
    setPill('imu-pill-frozen', frozen ? '疑似冻结' : '计数正常', !frozen);
    $('imu-roll').textContent = roll === null ? '--' : f1(roll);
    $('imu-pitch').textContent = pitch === null ? '--' : f1(pitch);
    if (roll !== null) {
      $('imu-horizon').setAttribute('transform',
        `rotate(${(-roll).toFixed(2)} 60 60) translate(0 ${(pitch * 1.1).toFixed(2)})`);
    }
    $('imu-yaw').textContent = roll === null ? '--' : `${f1(yaw)}°(相对,漂移)`;
    $('imu-gyro').textContent = `x ${f2(gx)} · y ${f2(gy)} · z ${f2(gz)} °/s`;
    $('imu-quat').textContent = qw === null ? '等待收敛…'
      : `${f3(qx)} ${f3(qy)} ${f3(qz)} ${f3(qw)}`;
    $('imu-cnt').textContent = `${cnt} · ${statusText(st)}`;
    $('imu-loss').textContent = `${toN} / ${txN}`;

    if (roll !== null) {
      const push = (arr, v) => { arr.push(v); if (arr.length > CHART_POINTS) arr.shift(); };
      push(chart.roll, roll); push(chart.pitch, pitch);
      push(chart.gx, gx); push(chart.gy, gy); push(chart.gz, gz);
    }
    csv.push([Date.now(), gx.toFixed(4), gy.toFixed(4), gz.toFixed(4),
      qw === null ? '' : qx.toFixed(5), qw === null ? '' : qy.toFixed(5),
      qw === null ? '' : qz.toFixed(5), qw === null ? '' : qw.toFixed(5),
      roll === null ? '' : roll.toFixed(3), pitch === null ? '' : pitch.toFixed(3),
      yaw === null ? '' : yaw.toFixed(3), cnt, st]);
    if (csv.length > CSV_ROWS) csv.shift();

    if (drift) {
      drift.n++; drift.sx += gx; drift.sy += gy; drift.sz += gz;
      $('imu-drift').textContent = `检查中 ${Math.max((drift.end - performance.now()) / 1000, 0).toFixed(1)}s`;
      if (performance.now() >= drift.end) finishDrift();
    }
    if (performance.now() - lastDraw >= 100) {
      const now = performance.now();
      $('imu-rate-now').textContent = `${Math.round(rateCount * 1000 / (now - rateAt))} Hz`;
      rateCount = 0; rateAt = now; lastDraw = now;
      drawCharts();
    }
  }

  async function runStream() {
    while (streaming && port) {
      const t0 = performance.now();
      try { onSample(await transact(sid, 0x02, [ADDR_BLOCK, BLOCK_LEN], BLOCK_LEN)); } catch { /* timeout counts as a lost reply */ }
      const wait = 1000 / Number($('imu-rate').value) - (performance.now() - t0);
      if (wait > 2) await sleep(wait);
    }
  }
  function toggleStream() {
    if (streaming) {
      streaming = false;
      $('imu-stream').textContent = '开始遥测';
      log(`遥测已停止(丢包 ${toN} / 发送 ${txN})`);
      return;
    }
    if (!port) return;
    streaming = true;
    $('imu-stream').textContent = '停止遥测';
    rateCount = 0; rateAt = performance.now();
    log(`开始遥测:READ 56 起 ${BLOCK_LEN}B @ ID ${sid},目标 ${$('imu-rate').value} Hz`);
    runStream();
  }

  async function connect() {
    if (!('serial' in navigator)) return log('此浏览器不支持 Web Serial,请用 Chrome/Edge 打开本机工作台。', true);
    try {
      port = await navigator.serial.requestPort();
      await port.open({baudRate: Number($('imu-baud').value), dataBits: 8, parity: 'none', stopBits: 1, flowControl: 'none'});
    } catch (error) {
      port = null;
      const busy = /already open|InvalidState|Busy/i.test(error.message);
      log(`连接失败:${error.message}${busy ? '——URT2 调试台或其他页面可能正占用这个串口,先断开那边的连接。' : ''}`, true);
      return;
    }
    keepReading = true; buf = new Uint8Array(0);
    reader = port.readable.getReader();
    (async () => {
      try {
        while (keepReading) {
          const {value, done} = await reader.read();
          if (done) break;
          const merged = new Uint8Array(buf.length + value.length);
          merged.set(buf); merged.set(value, buf.length); buf = merged;
          if (buf.length > 1024) buf = buf.slice(-512);
        }
      } catch {}
    })();
    sid = Number($('imu-id').value) || 200;
    txN = toN = 0; counts = []; lastQuat = null; reservedWarned = false;
    setConnected(true);
    log(`已连接 ${Number($('imu-baud').value).toLocaleString()} bps · IMU 节点 ID=${sid};先读节点身份`);
    try {
      const info = await transact(sid, 0x02, [ADDR_INFO, INFO_LEN], INFO_LEN);
      const model = u16(info[2], info[3]);
      $('imu-node').textContent = `固件 v${info[0]}.${info[1]} · 型号 0x${model.toString(16).toUpperCase()}`;
      // 0x4D49 = 'IM',imu_to_dxl 节点的型号寄存器(community-kit 协议文档 §7.2)。
      if (model === 0x4D49) log(`✓ IMU 节点在线:固件 v${info[0]}.${info[1]},型号 'IM'`);
      else log(`⚠ 型号 0x${model.toString(16).toUpperCase()} 不是 'IM'(imu_to_dxl),确认总线上这块板是谁。`, true);
    } catch {
      $('imu-node').textContent = '未识别';
      log('⚠ 身份寄存器无应答:确认 imu_to_dxl 节点已上电、在总线上,且 robotd 已停止。遥测仍可尝试。', true);
    }
    toggleStream();
  }
  async function disconnect() {
    keepReading = false;
    streaming = false;
    try { if (reader) await reader.cancel(); } catch {}
    try { await port.close(); } catch {}
    port = null;
    if (drift) {
      drift = null;
      $('imu-drift').textContent = '静态零漂检查(10s)';
    }
    $('imu-stream').textContent = '开始遥测';
    setConnected(false);
    log('已断开');
  }

  function exportCsv() {
    if (!csv.length) return log('还没有样本:连接并开始遥测后再导出。', true);
    const rows = ['time_ms,gx_dps,gy_dps,gz_dps,qx,qy,qz,qw,roll_deg,pitch_deg,yaw_deg,count,status',
      ...csv.map(row => row.join(','))];
    const blob = new Blob([rows.join('\n') + '\n'], {type: 'text/csv'});
    const link = document.createElement('a');
    link.href = URL.createObjectURL(blob);
    link.download = `imu-${new Date().toISOString().slice(0, 19).replace(/[:T]/g, '')}.csv`;
    link.click();
    URL.revokeObjectURL(link.href);
    log(`已导出 ${csv.length} 行样本(CSV,环形缓冲最多保留 ${CSV_ROWS} 行)。台架数据,不进项目证据。`);
  }
  function exportLog() {
    const blob = new Blob([logEntries.map(entry => `[${entry.time}] ${entry.text}`).join('\n') + '\n'], {type: 'text/plain'});
    const link = document.createElement('a');
    link.href = URL.createObjectURL(blob);
    link.download = `imu-${new Date().toISOString().slice(0, 19).replace(/[:T]/g, '')}.log`;
    link.click();
    URL.revokeObjectURL(link.href);
  }
  function clearData() {
    for (const key of Object.keys(chart)) chart[key] = [];
    csv = []; counts = []; txN = toN = 0;
    drawCharts();
    $('imu-loss').textContent = '0 / 0';
    if (!streaming) $('imu-rate-now').textContent = '—';
    log('已清空曲线与样本缓存');
  }

  function buildCard() {
    const card = document.createElement('section');
    card.id = 'card-imu';
    card.className = 'card';
    card.innerHTML = `<h2><svg class="icon" aria-hidden="true"><use href="#i-cpu"/></svg>IMU 姿态台架(Web Serial 直连 ID 200)</h2>
    <p class="muted">imu_to_dxl 节点把六轴姿态伪装成舵机总线上的 ID 200,与 15 颗 HD-1910 共用同一条 1 Mbps 半双工总线。这里用 Web Serial 直读它的 FT6 契约块(寄存器 56–70,15 字节:陀螺 + 四元数 + 计数 + 状态),服务端不碰串口、不进项目证据。LSM6DSV16X 片上融合(SFLP)输出游戏四元数,上电后约 1.5 秒收敛,期间显示"融合未就绪"并保持上一份有效姿态。</p>
    <div class="inline-note warning" id="imu-serial-note" hidden></div>
    <div class="imu-fields">
      <label>节点 ID<input id="imu-id" type="number" min="0" max="252" value="200"></label>
      <label>波特率<select id="imu-baud">
        <option value="1000000" selected>1,000,000(默认)</option>
        <option value="500000">500,000</option>
        <option value="115200">115,200</option>
      </select></label>
      <label>目标采样率<select id="imu-rate">
        <option value="50" selected>50 Hz</option>
        <option value="20">20 Hz</option>
        <option value="10">10 Hz</option>
      </select></label>
    </div>
    <div class="imu-actions">
      <button id="imu-connect" class="primary">🔌 连接 IMU 节点</button>
      <button id="imu-disc" disabled>断开</button>
      <span class="pill insufficient_evidence" id="imu-state">未连接</span>
      <button id="imu-stream" disabled>开始遥测</button>
      <button id="imu-drift" disabled title="静止 10 秒,逐轴陀螺均值应小于 0.05 rad/s">静态零漂检查(10s)</button>
    </div>
    <div class="imu-actions">
      <span class="pill insufficient_evidence" id="imu-pill-ready">—</span>
      <span class="pill insufficient_evidence" id="imu-pill-stale">—</span>
      <span class="pill insufficient_evidence" id="imu-pill-frozen">—</span>
    </div>
    <p class="muted">连接前提:①机器人上的 <b>robotd 已停止</b>(总线同一时刻只允许一个主站);②URT2 调试台与本面板共用物理串口,不能同时连接;③USB 转接板支持 1 Mbps 半双工。Web Serial 仅 Chrome/Edge 支持。</p>
    <div class="sd-telemetry">
      <div>
        <svg viewBox="0 0 120 120" role="img" aria-label="姿态仪" class="imu-attitude">
          <defs><clipPath id="imu-att-clip"><circle cx="60" cy="60" r="50"/></clipPath></defs>
          <g clip-path="url(#imu-att-clip)"><g id="imu-horizon" transform="rotate(0 60 60)">
            <rect x="-100" y="-140" width="320" height="200" fill="#cfe0ef"></rect>
            <rect x="-100" y="60" width="320" height="200" fill="#d8c3a5"></rect>
            <line x1="-100" y1="60" x2="220" y2="60" stroke="#54604f" stroke-width="1.6"></line>
          </g></g>
          <circle cx="60" cy="60" r="50" fill="none" stroke="#9aa793" stroke-width="1.5"></circle>
          <g stroke="#c23b22" stroke-width="2.5" stroke-linecap="round"><line x1="36" y1="60" x2="51" y2="60"></line><line x1="69" y1="60" x2="84" y2="60"></line></g>
          <circle cx="60" cy="60" r="2.4" fill="#c23b22"></circle>
        </svg>
        <div class="imu-big"><span id="imu-roll">--</span>° / <span id="imu-pitch">--</span>°</div>
        <div class="muted imu-big-label">roll / pitch(右倾、抬头为正)</div>
      </div>
      <div>
        <div class="sd-kv"><span class="k">偏航 yaw</span><span class="v" id="imu-yaw">--</span></div>
        <div class="sd-kv"><span class="k">陀螺 °/s</span><span class="v" id="imu-gyro">--</span></div>
        <div class="sd-kv"><span class="k">四元数 x y z w</span><span class="v" id="imu-quat">--</span></div>
        <div class="sd-kv"><span class="k">计数 · 状态位</span><span class="v" id="imu-cnt">--</span></div>
        <div class="sd-kv"><span class="k">节点身份</span><span class="v" id="imu-node">未识别</span></div>
        <div class="sd-kv"><span class="k">实际速率 / 丢包·发送</span><span class="v"><span id="imu-rate-now">—</span> · <span id="imu-loss">0 / 0</span></span></div>
      </div>
    </div>
    <h3 class="section-title">姿态角(°)</h3>
    <svg id="imu-chart-att" class="metric-chart" viewBox="0 0 300 100" preserveAspectRatio="none" aria-label="roll/pitch 曲线"></svg>
    <p class="imu-legend"><span><i style="background:#17633a"></i>roll</span><span><i style="background:#2563a8"></i>pitch</span></p>
    <h3 class="section-title">陀螺角速度(°/s)</h3>
    <svg id="imu-chart-gyro" class="metric-chart" viewBox="0 0 300 100" preserveAspectRatio="none" aria-label="陀螺曲线"></svg>
    <p class="imu-legend"><span><i style="background:#17633a"></i>x</span><span><i style="background:#2563a8"></i>y</span><span><i style="background:#c26a1c"></i>z</span></p>
    <h3 class="section-title">日志</h3>
    <div class="sd-log" id="imu-log" role="log" aria-live="polite"></div>
    <div class="imu-actions">
      <button id="imu-csv">导出 CSV</button>
      <button id="imu-export">导出日志(.log)</button>
      <button id="imu-clear-log" class="ghost">清空数据</button>
    </div>`;
    $('card-servodebug').after(card);
  }

  function init() {
    buildCard();
    $('imu-connect').addEventListener('click', guard(connect));
    $('imu-disc').addEventListener('click', guard(disconnect));
    $('imu-stream').addEventListener('click', guard(toggleStream));
    $('imu-drift').addEventListener('click', guard(startDrift));
    $('imu-csv').addEventListener('click', guard(exportCsv));
    $('imu-export').addEventListener('click', exportLog);
    $('imu-clear-log').addEventListener('click', clearData);
    if (!('serial' in navigator)) {
      const note = $('imu-serial-note');
      note.hidden = false;
      note.innerHTML = '<span>当前浏览器不支持 Web Serial。IMU 台架需要 Chrome/Edge,并从 <code>http://127.0.0.1:8765</code> 访问工作台。</span>';
      $('imu-connect').disabled = true;
    }
    setConnected(false);
    log('IMU 台架就绪。读不到节点时,先确认板子已上电、robotd 已停、波特率 1 Mbps。');
  }
  return {init};
})();
