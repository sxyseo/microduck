/* Interactive URT2 bench console. The browser owns the serial port via Web Serial; the Python
   service never opens it, and nothing done here is recorded as project evidence. Features ported
   from duck-whatled/public/tools/servo-debug-web.html (解读 203 台架实测版). */
window.ServoDebug = (() => {
  const $ = id => document.getElementById(id);
  const REG = {FIRM:0,ID:5,BAUD:6,DELAY:7,RESP:8,AMIN:9,AMAX:11,TMAX:13,VMAX:14,VMIN:15,TQMAX:16,
               P:21,D:22,I:23,OFFSET:31,MODE:33,LOCK:55,TORQUE:40,ACCEL:41,GOAL:42,SPEED:46,
               POS:56,SPDNOW:58,LOAD:60,VOLT:62,TEMP:63,STATUS:65,MOVING:66,CUR:69};
  const MODELS = {
    '2915': {name:'HL-2915-C001', vrec:'12V', warnBelow:9.0, vdef:16.0, vtop:14.0},
    '1910': {name:'HL-1910-C001', vrec:'7.4V(2S)', warnBelow:4.5, vdef:8.4, vtop:8.4},
    'gen': {name:'磁编码通用型号', vrec:'规格书值', warnBelow:4.5, vdef:16.0, vtop:16.0}
  };
  const CONNECTED_BUTTONS = ['sd-ping','sd-reboot','sd-init','sd-telem','sd-stop','sd-goal-send','sd-ton','sd-toff','sd-cal',
    'sd-gain','sd-gain-read','sd-eeprom','sd-eeprom-read','sd-read','sd-write','sd-scan',
    'sd-refresh-all','sd-all-center','sd-all-ton','sd-all-toff','sd-setid','sd-disc'];
  let port = null, reader = null, keepReading = false, buf = new Uint8Array(0);
  let sid = 1, txN = 0, toN = 0, telemTimer = null, found = [], logEntries = [];

  const model = () => MODELS[$('sd-model').value];
  const u16 = (lo, hi) => lo | (hi << 8);
  const deg = c => ((c - 2048) * 360 / 4096).toFixed(1);
  const sleep = ms => new Promise(r => setTimeout(r, ms));
  const hex = bytes => Array.from(bytes).map(b => b.toString(16).padStart(2, '0')).join(' ');

  function log(message, isError) {
    logEntries.push({time: new Date().toLocaleTimeString('zh-CN', {hour12: false}), text: message});
    if (logEntries.length > 500) logEntries.shift();
    const line = document.createElement('div');
    if (isError) line.className = 'err';
    const time = document.createElement('span');
    time.className = 't';
    time.textContent = `[${logEntries[logEntries.length - 1].time}] `;
    line.append(time, document.createTextNode(message));
    const box = $('sd-log');
    box.appendChild(line);
    box.scrollTop = box.scrollHeight;
  }

  /* Errors stay in the console log; handlers stay synchronous so the workbench busy-wrapper
     never re-enables the connect-gated buttons behind this card's back. */
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
    throw Error('舵机无应答(ID/线序/波特率/电源?)');
  }
  const rd = (addr, len) => transact(sid, 0x02, [addr, len], len);
  const wr = (addr, data) => transact(sid, 0x03, [addr, ...data], 0);
  async function writeNoReply(id, addr, data) {
    const writer = port.writable.getWriter();
    await writer.write(packet(id, 0x03, [addr, ...data]));
    writer.releaseLock();
    await sleep(40);
  }

  function showTorque(on) {
    $('sd-tstate').textContent = on ? '开' : '关';
    $('sd-tstate').className = `pill ${on ? 'passed' : 'insufficient_evidence'}`;
  }
  function statusBits(value) {
    const names = {0: '过压/欠压', 1: '磁编码', 2: '过热', 3: '过流', 5: '过载'};
    return Object.entries(names).map(([bit, label]) => {
      const hit = (value >> bit) & 1;
      return `<span class="${hit ? 'hit' : ''}">${label}${hit ? '!' : ''}</span>`;
    }).join('') || '<span>正常</span>';
  }
  function showTelemetry(d) {
    const pos = u16(d[0], d[1]), spd = u16(d[2], d[3]) & 0x7FFF, load = u16(d[4], d[5]) & 0x7FFF;
    const volt = d[6] / 10, temp = d[7], status = d[8], current = (u16(d[11], d[12]) & 0x7FFF) * 6.5;
    $('sd-pos').textContent = pos;
    $('sd-deg').textContent = `/ ${deg(pos)}°`;
    const m = model();
    $('sd-volt').textContent = `${volt.toFixed(1)} V${volt < m.warnBelow ? ` ⚠ 低于 ${m.vrec} 工作区` : ''}`;
    $('sd-temp').textContent = `${temp} °C`;
    $('sd-cur').textContent = `${current.toFixed(0)} mA(口径待验证)`;
    $('sd-spd').textContent = `${spd} 步/s / ${load} (0.1%)`;
    $('sd-stat').innerHTML = statusBits(status);
    $('sd-loss').textContent = `${toN} / ${txN}`;
  }
  async function telemOnce() {
    try { showTelemetry(await rd(REG.POS, 14)); } catch { /* timeout counts as a lost reply */ }
    $('sd-loss').textContent = `${toN} / ${txN}`;
  }
  function toggleTelem() {
    if (telemTimer) {
      clearInterval(telemTimer); telemTimer = null;
      $('sd-telem').textContent = '开始遥测';
      return;
    }
    $('sd-telem').textContent = '停止遥测';
    telemTimer = setInterval(telemOnce, 150);
    telemOnce();
  }
  function setConnected(on) {
    for (const id of CONNECTED_BUTTONS) $(id).disabled = !on;
    const state = $('sd-state');
    state.textContent = on ? '已连接' : '未连接';
    state.className = `pill ${on ? 'passed' : 'insufficient_evidence'}`;
  }

  async function connect() {
    if (!('serial' in navigator)) return log('此浏览器不支持 Web Serial,请用 Chrome/Edge 打开本机工作台。', true);
    try {
      port = await navigator.serial.requestPort();
      await port.open({baudRate: Number($('sd-baud').value), dataBits: 8, parity: 'none', stopBits: 1, flowControl: 'none'});
    } catch (error) { log(`连接失败:${error.message}`, true); return; }
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
    sid = Number($('sd-sid').value) || 1;
    txN = toN = 0;
    setConnected(true);
    const m = model();
    log(`已连接 ${Number($('sd-baud').value).toLocaleString()} bps · ${m.name} · ID=${sid};先 PING,再开始遥测`);
    try {
      const f = await rd(REG.FIRM, 2);
      log(`固件 v${f[0]}.${f[1]} | ID 寄存器=${(await rd(REG.ID, 1))[0]} | 电压窗 ${(await rd(REG.VMIN, 1))[0] / 10}–${(await rd(REG.VMAX, 1))[0] / 10}V`);
      showTorque((await rd(REG.TORQUE, 1))[0]);
    } catch (error) { log(`读固件信息失败:${error.message}`, true); }
    toggleTelem();
  }
  async function disconnect() {
    keepReading = false;
    try { if (reader) await reader.cancel(); } catch {}
    try { await port.close(); } catch {}
    port = null;
    if (telemTimer) { clearInterval(telemTimer); telemTimer = null; $('sd-telem').textContent = '开始遥测'; }
    found = []; renderTable();
    $('sd-scan-status').textContent = '未扫描';
    $('sd-scan-result').textContent = '扫描会逐个 PING ID 1–253,约需 30 秒。';
    setConnected(false);
    log('已断开');
  }

  async function ping() {
    sid = Number($('sd-sid').value) || 1;
    await transact(sid, 0x01);
    log(`PING ID=${sid} 成功,舵机在线`);
  }
  async function reboot() {
    if (!window.confirm(`REBOOT 会复位舵机 ID=${sid}(清锁保护、参数回出厂、多圈计数清零)。确认?`)) return;
    const writer = port.writable.getWriter();
    await writer.write(packet(sid, 0x08));
    writer.releaseLock();
    log('REBOOT 已发送,等待 2.5 秒……');
    await sleep(2500);
    try {
      const p = await rd(REG.POS, 2);
      log(`✓ REBOOT 完成,位置 ${u16(p[0], p[1])}`);
    } catch { log('⚠ REBOOT 后无应答——再点一次 PING 确认通信', true); }
  }
  async function gentleInit() {
    await wr(21, [16]); await wr(22, [0]); await wr(23, [0]);
    await wr(41, [0xF4, 0x01]);
    await wr(48, [0x2C, 0x01]);
    await wr(40, [1]);
    showTorque(true);
    log('✓ 温和参数已写入:P=16 D=0 I=0 加速度500 扭矩限30% 扭矩开');
  }
  async function estop() {
    await wr(REG.TORQUE, [0]);
    showTorque(false);
    log('⛔ 急停:扭矩已关');
  }
  async function sendGoal() {
    const goal = Number($('sd-goal').value), speed = Number($('sd-speed').value), accel = Number($('sd-accel').value);
    const limited = $('sd-limit').checked, current = Number($('sd-pos').textContent);
    if (Number.isNaN(goal) || goal < 0 || goal > 4095) return log('目标位置超出 0–4095', true);
    if (limited && current && Math.abs(goal - current) > 600) return log(`已拦截:与当前位置差 ${Math.abs(goal - current)} 步,超出 ±600 步安全限幅(取消勾选可解除)`, true);
    await wr(REG.ACCEL, [accel & 0xFF, (accel >> 8) & 0xFF]);
    await wr(REG.SPEED, [speed & 0xFF, (speed >> 8) & 0xFF]);
    await wr(REG.TORQUE, [1]);
    showTorque(true);
    await wr(REG.GOAL, [goal & 0xFF, (goal >> 8) & 0xFF]);
    log(`目标 ${goal} 步(${deg(goal)}°) · 速度 ${speed} · 加速度 ${accel}`);
    // 到位即停:±6 步或 3 秒超时后扭矩关,防止持续旋转。
    const start = performance.now();
    while (performance.now() - start < 3000) {
      await sleep(150);
      try {
        const d = await rd(REG.POS, 2);
        const pos = u16(d[0], d[1]);
        if (Math.abs(pos - goal) <= 6) {
          await wr(REG.TORQUE, [0]);
          showTorque(false);
          log(`✓ 到位 ${pos},扭矩自动关`);
          return;
        }
      } catch {}
    }
    try {
      await wr(REG.TORQUE, [0]);
      showTorque(false);
      log('⚠ 3 秒未到位,扭矩自动关(防持续旋转)', true);
    } catch {}
  }
  async function calibrate() {
    if (!window.confirm('写 40=128:舵机会把当前位置校正为中位 2048,输出轴会动作!确认空载/安全位姿?')) return;
    await wr(REG.TORQUE, [128]);
    log('校准指令已写(40=128)');
  }
  async function writeGains() {
    const p = Number($('sd-p').value), d = Number($('sd-d').value), i = Number($('sd-i').value);
    if ([p, d, i].some(v => v < 0 || v > 255)) return log('增益范围 0–255', true);
    await wr(REG.P, [p]); await wr(REG.D, [d]); await wr(REG.I, [i]);
    log(`增益已写:P=${p} D=${d} I=${i}(RAM,掉电不保存)`);
  }
  async function readGains() {
    const p = await rd(REG.P, 1), d = await rd(REG.D, 1), i = await rd(REG.I, 1);
    $('sd-p').value = p[0]; $('sd-d').value = d[0]; $('sd-i').value = i[0];
    log(`读回增益:P=${p[0]} D=${d[0]} I=${i[0]}`);
  }
  async function writeEeprom() {
    const lock = await rd(REG.LOCK, 1);
    if (lock[0] !== 0) return log(`55 号锁位=${lock[0]},EEPROM 已锁定;先写 55=0(改动掉电保存,谨慎)`, true);
    const amin = Number($('sd-amin').value), amax = Number($('sd-amax').value);
    const vmax = Math.round(Number($('sd-vmax').value) * 10), tmax = Number($('sd-tmax').value), tq = Number($('sd-tqmax').value);
    await wr(REG.AMIN, [amin & 0xFF, (amin >> 8) & 0xFF]);
    await wr(REG.AMAX, [amax & 0xFF, (amax >> 8) & 0xFF]);
    await wr(REG.VMAX, [vmax & 0xFF]);
    await wr(REG.TMAX, [tmax & 0xFF]);
    await wr(REG.TQMAX, [tq & 0xFF, (tq >> 8) & 0xFF]);
    log(`EEPROM 已写:行程[${amin},${amax}] 电压上限${vmax / 10}V 温度上限${tmax}°C 最大扭矩${tq}`);
  }
  async function readEeprom() {
    const amin = await rd(REG.AMIN, 2), amax = await rd(REG.AMAX, 2);
    const v = await rd(REG.VMAX, 1), t = await rd(REG.TMAX, 1), tq = await rd(REG.TQMAX, 2);
    $('sd-amin').value = u16(amin[0], amin[1]);
    $('sd-amax').value = u16(amax[0], amax[1]);
    $('sd-vmax').value = (v[0] / 10).toFixed(1);
    $('sd-tmax').value = t[0];
    $('sd-tqmax').value = u16(tq[0], tq[1]);
    log('EEPROM 参数已读回并填入表单');
  }
  async function readRaw() {
    const addr = Number($('sd-raddr').value), len = Number($('sd-rlen').value);
    log(`寄存器 ${addr} 起 ${len}B:${hex(await rd(addr, len))}`);
  }
  async function writeRaw() {
    const addr = Number($('sd-waddr').value);
    const data = $('sd-wdata').value.trim().split(/\s+/).map(x => parseInt(x, 16)).filter(x => !Number.isNaN(x));
    if (!data.length) return log('数据格式:hex 空格分隔,如 01 或 E8 03', true);
    const dump = hex(data);
    if (!window.confirm(`向寄存器 ${addr} 写 ${data.length} 字节:${dump}?`)) return;
    await wr(addr, data);
    log(`已写 ${addr} ← ${dump}`);
  }

  async function pingId(id) {
    try { await transact(id, 0x01, [], 0); return true; } catch { return false; }
  }
  async function telemAt(id) {
    try {
      const d = await transact(id, 0x02, [56, 14], 14);
      return {pos: u16(d[0], d[1]), load: u16(d[4], d[5]) & 0x7FFF, volt: d[6] / 10, temp: d[7], status: d[8]};
    } catch { return null; }
  }
  async function scan() {
    $('sd-scan').disabled = true;
    found = [];
    $('sd-scan-status').textContent = '扫描中…';
    $('sd-scan-result').textContent = '';
    for (let id = 1; id <= 253; id++) {
      $('sd-scan-status').textContent = `扫描 ${id}/253…`;
      if (await pingId(id)) {
        found.push(id);
        $('sd-scan-result').textContent += `ID ${id} ✓ `;
      }
    }
    $('sd-scan-status').textContent = `完成,发现 ${found.length} 只`;
    $('sd-scan-result').textContent = found.length ? `已发现:${found.join(', ')}` : '未发现(查接线/共地/波特率)';
    // 扫描中途可能已断开:只有仍在线时才恢复按钮。
    $('sd-scan').disabled = !port;
    for (const id of ['sd-refresh-all', 'sd-all-center', 'sd-all-ton', 'sd-all-toff', 'sd-setid']) $(id).disabled = !port || !found.length;
    if (port && found.length) refreshAll();
  }
  async function centerOne(id) {
    await writeNoReply(id, 40, [1]);
    await writeNoReply(id, 42, [2048 & 0xFF, 2048 >> 8]);
    log(`ID ${id} → 2048`);
  }
  function servoRow(id, t) {
    const row = document.createElement('tr');
    const idCell = document.createElement('td');
    idCell.textContent = id;
    row.appendChild(idCell);
    if (!t) {
      const cell = document.createElement('td');
      cell.colSpan = 7;
      cell.className = 'sd-noanswer';
      cell.textContent = '无应答';
      row.appendChild(cell);
      return row;
    }
    for (const value of [t.pos, `${deg(t.pos)}°`, `${t.volt.toFixed(1)}V`, `${t.temp}°C`, t.load]) {
      const cell = document.createElement('td');
      cell.textContent = value;
      row.appendChild(cell);
    }
    const status = document.createElement('td');
    const tag = document.createElement('span');
    tag.className = `pill ${t.status === 0 ? 'passed' : 'failed'}`;
    tag.textContent = t.status === 0 ? '正常' : `⚠${t.status}`;
    status.appendChild(tag);
    row.appendChild(status);
    const actions = document.createElement('td');
    actions.className = 'sd-row-actions';
    const pick = document.createElement('button');
    pick.textContent = '选择';
    pick.className = 'sd-mini';
    pick.addEventListener('click', () => { $('sd-sid').value = id; sid = id; log(`已选 ID ${id}`); });
    const center = document.createElement('button');
    center.textContent = '回中';
    center.className = 'sd-mini dangerous-start';
    center.addEventListener('click', guard(() => centerOne(id)));
    actions.append(pick, center);
    row.appendChild(actions);
    return row;
  }
  function renderTable() {
    const body = $('sd-servo-rows');
    body.replaceChildren();
    if (!found.length) {
      const row = document.createElement('tr');
      const cell = document.createElement('td');
      cell.colSpan = 8;
      cell.textContent = '连接并扫描后,这里显示总线上每只舵机的实时遥测。';
      row.appendChild(cell);
      body.appendChild(row);
      return;
    }
    for (const id of found) body.appendChild(servoRow(id, null));
  }
  async function refreshAll() {
    const body = $('sd-servo-rows');
    body.replaceChildren();
    for (const id of found) body.appendChild(servoRow(id, await telemAt(id)));
  }
  async function allCenter() {
    for (const id of found) {
      await writeNoReply(id, 40, [1]);
      await writeNoReply(id, 42, [2048 & 0xFF, 2048 >> 8]);
    }
    log(`全部 ${found.length} 只 → 2048`);
    refreshAll();
  }
  async function allTorque(on) {
    for (const id of found) await writeNoReply(id, 40, [on ? 1 : 0]);
    log(on ? '全部扭矩开' : '全部扭矩关');
  }
  async function setId() {
    const old = Number($('sd-old-id').value), next = Number($('sd-new-id').value);
    if (!(next >= 1 && next <= 253)) return log('ID 范围 1–253', true);
    if (old === next) return log('新旧 ID 相同', true);
    if (!window.confirm(`将 ID ${old} 改为 ${next}?\n⚠ 一次只接一只!写完 REBOOT 后用新 ID 通信。`)) return;
    await writeNoReply(old, 55, [0]);
    await writeNoReply(old, 5, [next]);
    await writeNoReply(old, 55, [1]);
    log(`✓ ID ${old} → ${next} 已写入。REBOOT 后用新 ID 验证。`);
    found = found.map(x => (x === old ? next : x));
  }
  function exportLog() {
    const blob = new Blob([logEntries.map(entry => `[${entry.time}] ${entry.text}`).join('\n') + '\n'], {type: 'text/plain'});
    const link = document.createElement('a');
    link.href = URL.createObjectURL(blob);
    link.download = `servo-debug-${new Date().toISOString().slice(0, 19).replace(/[:T]/g, '')}.log`;
    link.click();
    URL.revokeObjectURL(link.href);
  }

  function buildCard() {
    const card = document.createElement('section');
    card.id = 'card-servodebug';
    card.className = 'card';
    card.innerHTML = `<h2><svg class="icon" aria-hidden="true"><use href="#i-servo"/></svg>URT2 调试台(Web Serial 直连)</h2>
    <p class="muted">把 duck.whatled.com 的网页版调试台搬进工作台:浏览器经 Web Serial 直连 URT2 调试板,遥测、位置控制、增益与限位即时生效。串口由浏览器持有,服务端不会打开它;这里的操作是台架实操,不进入项目证据。</p>
    <div class="inline-note warning" id="sd-serial-note" hidden></div>
    <div class="sd-fields">
      <label>舵机型号<select id="sd-model">
        <option value="2915" selected>HL-2915-C001(9–14V · 推荐 12V)</option>
        <option value="1910">HL-1910-C001(4–8.4V · 推荐 7.4V 2S)</option>
        <option value="gen">其他磁编码型号(自行核对)</option>
      </select></label>
      <label>波特率<select id="sd-baud">
        <option value="1000000" selected>1,000,000(默认)</option>
        <option value="500000">500,000</option>
        <option value="115200">115,200</option>
      </select></label>
      <label>舵机 ID<input id="sd-sid" type="number" min="1" max="253" value="1"></label>
    </div>
    <div class="sd-actions">
      <button id="sd-connect" class="primary">🔌 连接舵机</button>
      <button id="sd-disc" disabled>断开</button>
      <span class="pill insufficient_evidence" id="sd-state">未连接</span>
      <button id="sd-ping" disabled>PING</button>
      <button id="sd-reboot" class="dangerous-start" disabled title="清除跑飞/堵转后的锁死保护状态(相当于断电重启)">REBOOT 清锁</button>
      <button id="sd-init" class="dangerous-start" disabled title="写入温和参数:P=16 加速度500 扭矩限30%">一键初始化</button>
    </div>
    <div class="sd-actions">
      <button id="sd-telem" disabled>开始遥测</button>
      <button id="sd-stop" class="sd-estop" disabled>⛔ 急停(扭矩关)</button>
    </div>
    <p class="muted">连接前:主电源已上电并<b>限流 0.5A</b>(HL-2915=12V / HL-1910=7.4V 2S),URT2 共地;端口列表为空时拔插 USB。Web Serial 仅 Chrome/Edge 支持。</p>
    <div class="sd-telemetry">
      <div>
        <div class="sd-position"><span id="sd-pos">----</span></div>
        <div class="sd-position-deg" id="sd-deg">/ --.-°</div>
        <div class="sd-kv"><span class="k">丢包 / 发送</span><span class="v" id="sd-loss">0 / 0</span></div>
      </div>
      <div>
        <div class="sd-kv"><span class="k">电压</span><span class="v" id="sd-volt">--</span></div>
        <div class="sd-kv"><span class="k">温度</span><span class="v" id="sd-temp">--</span></div>
        <div class="sd-kv"><span class="k">电流</span><span class="v" id="sd-cur">--</span></div>
        <div class="sd-kv"><span class="k">速度 / 负载</span><span class="v" id="sd-spd">--</span></div>
        <div class="sd-kv"><span class="k">状态位</span><span class="sd-status-bits v" id="sd-stat">--</span></div>
      </div>
    </div>
    <h3 class="section-title">位置控制</h3>
    <div class="sd-fields">
      <label>目标位置(步)<input id="sd-goal" type="number" min="0" max="4095" value="2048"></label>
      <label>目标速度(步/s)<input id="sd-speed" type="number" value="300"></label>
      <label>加速度(×100 步/s²)<input id="sd-accel" type="number" value="500"></label>
    </div>
    <input type="range" id="sd-goal-range" min="1448" max="2648" value="2048" aria-label="目标位置滑条">
    <div class="sd-actions">
      <button id="sd-mid">回中 2048</button>
      <label class="sd-check"><input type="checkbox" id="sd-limit" checked> 限幅 ±600 步</label>
      <button id="sd-goal-send" class="dangerous-start" disabled>▶ 发送目标</button>
      <button id="sd-ton" class="dangerous-start" disabled>扭矩开</button>
      <button id="sd-toff" disabled>扭矩关</button>
      <span class="pill" id="sd-tstate">--</span>
      <button id="sd-cal" class="dangerous-start" disabled title="写 40=128,当前位置校正为中位,输出轴会动作">校准当前为 2048</button>
    </div>
    <div class="sd-cols">
      <div>
        <h3 class="section-title">位置环增益(21/22/23 · RAM)</h3>
        <div class="sd-fields">
          <label>P(21)<input id="sd-p" type="number" min="0" max="255" value="32"></label>
          <label>D(22)<input id="sd-d" type="number" min="0" max="255" value="0"></label>
          <label>I(23)<input id="sd-i" type="number" min="0" max="255" value="0"></label>
        </div>
        <div class="sd-actions">
          <button id="sd-gain" disabled>写增益</button>
          <button id="sd-gain-read" disabled>读回</button>
        </div>
        <p class="muted">HL 系列 P/D/I 为单字节 0–255;过大可能震荡,失力状态(limp)参考 P≈50。P 的运行时映射因固件而异(解读 201 的 0.16 系数案例)。</p>
      </div>
      <div>
        <h3 class="section-title">行程与保护(EEPROM · 掉电保存)</h3>
        <div class="sd-fields">
          <label>角度下限(9)<input id="sd-amin" type="number" value="0"></label>
          <label>角度上限(11)<input id="sd-amax" type="number" value="4095"></label>
          <label>电压上限(14)<input id="sd-vmax" type="number" step="0.1" value="16.0"></label>
          <label>温度上限(13)<input id="sd-tmax" type="number" value="80"></label>
          <label>最大扭矩(16)<input id="sd-tqmax" type="number" value="1000"></label>
        </div>
        <div class="sd-actions">
          <button id="sd-eeprom" disabled>写入 EEPROM(需 LOCK=0)</button>
          <button id="sd-eeprom-read" disabled>读回</button>
        </div>
        <p class="muted">写入前自动检查 55 号锁位;供电前确认电压上限 ≥ 实际电源电压(HL-2915@12V → ≥13.0V;HL-1910 默认 8.4V)。写错行程可能造成撞击。</p>
      </div>
    </div>
    <details class="advanced">
      <summary>高级:原始寄存器读写</summary>
      <div class="sd-fields">
        <label>读起始地址(0–69)<input id="sd-raddr" type="number" min="0" max="69" value="56"></label>
        <label>读长度(1–30)<input id="sd-rlen" type="number" min="1" max="30" value="14"></label>
      </div>
      <div class="sd-actions"><button id="sd-read" disabled>读取寄存器</button></div>
      <div class="sd-fields">
        <label>写地址<input id="sd-waddr" type="number" min="0" max="69" value="40"></label>
        <label>写数据(hex,空格分隔)<input id="sd-wdata" value="01"></label>
      </div>
      <div class="sd-actions"><button id="sd-write" class="dangerous-start" disabled>写入(危险)</button></div>
    </details>
    <h3 class="section-title">总线扫描与多舵机总览</h3>
    <div class="sd-actions">
      <button id="sd-scan" disabled>🔍 扫描总线(ID 1–253)</button>
      <span class="muted" id="sd-scan-status">未扫描</span>
    </div>
    <p class="muted" id="sd-scan-result">扫描会逐个 PING ID 1–253,约需 30 秒。</p>
    <div class="table-scroll">
      <table class="sd-table">
        <thead><tr><th>ID</th><th>位置(步)</th><th>角度</th><th>电压</th><th>温度</th><th>负载</th><th>状态</th><th>操作</th></tr></thead>
        <tbody id="sd-servo-rows"></tbody>
      </table>
    </div>
    <div class="sd-actions">
      <button id="sd-refresh-all" disabled>🔄 刷新遥测</button>
      <button id="sd-all-center" class="dangerous-start" disabled>全部回中 2048</button>
      <button id="sd-all-ton" class="dangerous-start" disabled>全部扭矩开</button>
      <button id="sd-all-toff" disabled>全部扭矩关</button>
    </div>
    <div class="sd-fields">
      <label>出厂 ID<input id="sd-old-id" type="number" min="1" max="253" value="1"></label>
      <label>新 ID(1–253)<input id="sd-new-id" type="number" min="1" max="253" placeholder="如 21"></label>
    </div>
    <div class="sd-actions">
      <button id="sd-setid" class="dangerous-start" disabled>⚙ 写入新 ID(EEPROM)</button>
    </div>
    <p class="muted">改 ID 一次只接一只:拔掉其他舵机 → 接上要设的这只 → 写入 → REBOOT → 用新 ID PING 验证,逐只操作。</p>
    <h3 class="section-title">日志</h3>
    <div class="sd-log" id="sd-log" role="log" aria-live="polite"></div>
    <div class="sd-actions">
      <button id="sd-export">导出日志(.log)</button>
      <button id="sd-clear-log" class="ghost">清空日志</button>
    </div>`;
    $('card-probe').after(card);
  }

  function init() {
    buildCard();
    renderTable();
    $('sd-model').addEventListener('change', () => {
      const m = model();
      $('sd-vmax').value = m.vdef.toFixed(1);
      log(`型号切换:${m.name} · 工作窗 ${m.warnBelow}–${m.vtop}V · 推荐 ${m.vrec}`);
    });
    $('sd-goal-range').addEventListener('input', event => { $('sd-goal').value = event.target.value; });
    $('sd-goal').addEventListener('input', event => {
      const value = Number(event.target.value);
      if (value >= 0 && value <= 4095) $('sd-goal-range').value = value;
    });
    $('sd-mid').addEventListener('click', () => { $('sd-goal').value = 2048; $('sd-goal-range').value = 2048; });
    $('sd-connect').addEventListener('click', guard(connect));
    $('sd-disc').addEventListener('click', guard(disconnect));
    $('sd-ping').addEventListener('click', guard(ping));
    $('sd-reboot').addEventListener('click', guard(reboot));
    $('sd-init').addEventListener('click', guard(gentleInit));
    $('sd-telem').addEventListener('click', toggleTelem);
    $('sd-stop').addEventListener('click', guard(estop));
    $('sd-goal-send').addEventListener('click', guard(sendGoal));
    $('sd-ton').addEventListener('click', guard(async () => { await wr(REG.TORQUE, [1]); showTorque(true); }));
    $('sd-toff').addEventListener('click', guard(async () => { await wr(REG.TORQUE, [0]); showTorque(false); }));
    $('sd-cal').addEventListener('click', guard(calibrate));
    $('sd-gain').addEventListener('click', guard(writeGains));
    $('sd-gain-read').addEventListener('click', guard(readGains));
    $('sd-eeprom').addEventListener('click', guard(writeEeprom));
    $('sd-eeprom-read').addEventListener('click', guard(readEeprom));
    $('sd-read').addEventListener('click', guard(readRaw));
    $('sd-write').addEventListener('click', guard(writeRaw));
    $('sd-scan').addEventListener('click', guard(scan));
    $('sd-refresh-all').addEventListener('click', guard(refreshAll));
    $('sd-all-center').addEventListener('click', guard(allCenter));
    $('sd-all-ton').addEventListener('click', guard(() => allTorque(true)));
    $('sd-all-toff').addEventListener('click', guard(() => allTorque(false)));
    $('sd-setid').addEventListener('click', guard(setId));
    $('sd-export').addEventListener('click', exportLog);
    $('sd-clear-log').addEventListener('click', () => { logEntries = []; $('sd-log').replaceChildren(); });
    if (!('serial' in navigator)) {
      const note = $('sd-serial-note');
      note.hidden = false;
      note.innerHTML = '<span>当前浏览器不支持 Web Serial。调试台需要 Chrome/Edge,并从 <code>http://127.0.0.1:8765</code> 访问工作台。</span>';
      $('sd-connect').disabled = true;
    }
    setConnected(false);
    log('调试台就绪。连接后先看遥测电压——若低于推荐工作区,说明主电源未上,位置指令不会动作。');
  }
  return {init};
})();
