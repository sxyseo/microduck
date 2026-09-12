# 解读 119 · theremin.rs:特雷门琴彩蛋

> **解读对象**:`robotd/src/theremin.rs`(489 行,通读)
> **需要的前置**:导览见[解读 12](12-电池声音与彩蛋.md);ToF 见[解读 17](17-ToF驱动.md);合成见[解读 118](118-soundrs二合成混音.md)

特雷门琴是唯一不碰就能演奏的乐器:手离天线越近,音越高。鸭子的版本:喙前一台 8×8 ToF 深度传感器,手靠近,鸭子边张嘴边唱——音高、音量、嘴型全是同一个数;说是彩蛋,代码没有一处含糊:三种采样率在一处会合(theremin.rs:1-9)——深度帧 15 Hz 来自 `tofd` 的 socket,循环 50 Hz 独占嘴,音频 48 kHz 在写线程。

## 1. reader 线程:停在一个 socket 上,永远

`Theremin::spawn`(theremin.rs:100-110)起的 `tof-reader` 线程**不管有没有人用都跑**——懒连接会让"拿起乐器"多等一次握手(theremin.rs:97-99)。`read_frames`(theremin.rs:220-231)是外层:断线就**清空槽**再睡 2 秒(`RECONNECT`,theremin.rs:51)重连——别让一个音符悬在传感器临终前说的最后一句话上(theremin.rs:225-228)。`stream_frames`(theremin.rs:234-278)是一次连接的一生:发一条 JSON 订阅,逐行读;第一行应答报传感器名,之后每行一帧,塞进 `ArcSwapOption` 槽(theremin.rs:272-276)。`Frame`(theremin.rs:61-65)刻意保持生料——距离和**状态字节**都不解释:"哪些状态算数是 `hand::Config` 的决定,在这里解释就把它埋了"(theremin.rs:58-60)。

## 2. `tick`:从帧到 Note

`tick(&mut self, now) -> Option<Note>`(theremin.rs:153-195)由循环调用,**永不阻塞**;没拿起乐器返回 `None`——循环不该替没人要的功能指挥嘴。拿起后只有一次判断,针对**传感器**:帧比 `FRAME_STALE = 500 ms`(theremin.rs:46)新吗?不新就静音,但乐器仍在手上(theremin.rs:162-174)——帧回来自己续上;切断是第一版在真鸭上最响的毛病。新,就交给 `Tracker`(`kinematics::hand` 把 64 区折成 0..1 的 `closeness`),产出 `Note`(theremin.rs:72-82):`mouth`、一行 `robot.state`、`closeness`。`Note` **刻意不是频率**(theremin.rs:68-71)——closeness 映成哪个音是鸭嗓子的事(`theremin_hz_at`,见[解读 118](118-soundrs二合成混音.md)),深度传感器没资格定。而 `mouth: closeness.unwrap_or(0.0)`(theremin.rs:179-181)是全文件的核心:**一个数,三处用**——"嘴的开合和音高是字面意义的一个数;各调各的,就是嘴型动画贴在声音上"(theremin.rs:11-15)。

## 3. 为什么没有"武装"了

模块注释(theremin.rs:17-24)记了返工史:第一版会"武装"——抓面前的深度当背景,好区分手和墙。台架上行,真鸭上不行:哪个区的状态可用逐帧都在变,同一动作这秒认得、下秒不认。重写后只剩拿起/放下两态,唯一判断是传感器新鲜度。补偿是诊断:`describe`(theremin.rs:200-217)把状态字节做成直方图行(如 `32 usable · 4*:32`),星号标出本构建采信的码,"在说话但没听"与"没说话"一眼可分(theremin.rs:186-189)。`set_active`(theremin.rs:142-150)放下即 `tracker.reset()`。

## 4. 测试:返工史的化石

`it_plays_on_the_first_frame_after_being_picked_up`(theremin.rs:322)钉"拿起即响";`a_hand_past_thirty_centimetres_plays`(theremin.rs:337)把回归 bug 钉死——40 cm 处带"一致性失败"码 4/13 的手,在 0.35–0.60 m 都必须出声;`the_mouth_opens_with_the_note`(theremin.rs:356)验证嘴与音是同一个数;`a_flickering_sensor_does_not_chop_the_note`(theremin.rs:444)推 20 帧好坏交替,全部发声;`a_stale_frame_is_silence_and_the_instrument_stays_up`(theremin.rs:416)验证静音不落;`putting_it_down_forgets_the_held_note`(theremin.rs:473)验证放下即忘。工程小节:`new`(theremin.rs:113-117)不起线程、专供测试——起线程的版本会清掉测试刚推进的帧。

## 你带走的收获

- 跨速率会合的标准形:后台线程把最新值放进原子槽,节拍方一次 load 永不阻塞。
- 信号停了是淡出不是闸门:陈旧阈值管"多旧算哑",恢复即续。
- 一个感知量驱动多个执行量,曲线才不会彼此穿帮。
- 原始数据别急着解释:"哪些状态算数"留给配置层,埋雷变诊断。
- 返工史写进注释与测试。

## 延伸

- closeness 变声音:[解读 118](118-soundrs二合成混音.md);ToF 驱动:[解读 17](17-ToF驱动.md);同款槽模式:[解读 10](10-意图层.md)
- 本地:`/Volumes/dev/dev/microduck/robotd/src/theremin.rs`
