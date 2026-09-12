# 解读 117 · sound.rs(一):播放管线

> **解读对象**:`robotd/src/sound.rs`(947 行,本篇读播放主干)
> **需要的前置**:导览见[解读 12](12-电池声音与彩蛋.md);WheeeHold 三态见[解读 10](10-意图层.md);合成那一半见[解读 118](118-soundrs二合成混音.md)

鸭子说话的方式很朴素:从 wav 银行的目录挑一个文件,喂给系统自带的 `aplay`(sound.rs:1)。一切结构都来自一个硬件事实:声卡 PCM **独占单客户端**,同一时刻只有一个声音能上台(sound.rs:3-8)。两条家规随之而来:同时只一个播放子进程,新声音杀旧的;一切播放走控制循环独占的 `Sound`。

## 1. `Ride`:PCM 归谁是五选一

`enum Ride { Off, Riding, Landing, Theremin, Singing }`(sound.rs:89-104)——不是 bool,理由写在字段注释里:普通 quack 不得翻转它;"落地中"(end 段在写、`aplay` 在排空)必须与"骑着"和"空闲"都区分,"否则触发器会重启一场还没收尾的骑乘"(sound.rs:181-184)。`Sound` 结构(sound.rs:174-197)记着 `child: Option<Child>`(标准库子进程句柄)、共享给写线程的 `wheee_held` 标志、以及 `ride`。

## 2. `play`:谁上台,谁被切

`play(tag, blocking)`(sound.rs:281-317)第一步是让路规则:ride 占线时 one-shot **被丢弃而非排队**——事件在 ride 结束时就过期了(sound.rs:282-293)。唯一例外是 `blocking: true` 的告别 peck:关机前最后一响,可抢 PCM,但受 `BLOCKING_PLAY_MAX = 1500 ms` 约束——"这是给卡死的 PCM 的天花板,不是播放预算"(sound.rs:40-42),`wait_bounded`(sound.rs:827-843)超时就杀。选文件是 `pick`(sound.rs:216-232):列目录、滤 `.wav`、按纳秒随机取一个——"和一只鸭子需要的随机度恰好一样"。找不到银行只警告一次,之后静默降级。`stop_child`(sound.rs:236-252)是通用清台:先放倒 `wheee_held` 与 `live` 标志(合成写线程靠它退出,见[解读 118](118-soundrs二合成混音.md)),再 kill 并 wait。

## 3. wheee:同一次骑乘,两种退场

三态的消费端在 `wheee`(sound.rs:674-694)的 match 里:`Held` 且没在骑 → `start_wheee`;`Released`(活着的客户端说停)→ `stop_child` **当场切**;`Decayed`(心跳停了)→ `land_ride` **放完落地**。`land_ride`(sound.rs:257-265)只清共享标志、不杀子进程——管道还开着,写线程走出循环后写完 end 段;`reap_landing`(sound.rs:269-277)在之后的拍里 `try_wait` 收尸。只有落地会播放 `wheee_end_*`(sound.rs:11-15),这正是[解读 10](10-意图层.md)三态存在的理由。特雷门或合唱占线时,骑乘请求直接忽略(sound.rs:679-681)。

`start_wheee`(sound.rs:708-820)最巧的是**文件名即乐谱**:`wheee_start_A / wheee_loop_A / wheee_end_A` 三段共用一个字母(sound.rs:711-741),启动时随机抽字母,循环无缝。写线程(sound.rs:771-819)三件事:屏蔽 SIGPIPE(否则写进死掉的 `aplay` 会一信号杀死整个守护进程,sound.rs:779-784);按 8192 字节一块、保持只领先回放 0.25 s 的步调写管道(sound.rs:787-798)——不压着,松手后 end 段要迟到囤积的那么久;start 放完进 `while held` 循环,标志清零后落出循环写 end。残缺银行走 `degraded_wheee`(sound.rs:702-705):退化为普通 one-shot,**但照样闩在 Riding**——否则按住的扳机会以每秒五十次 fork、exec、kill `aplay`(sound.rs:696-701)。

## 4. 读 wav 与测试

`read_wav_pcm`(sound.rs:847-869)是 40 行的最小 RIFF 解析:认 `RIFF/WAVE` 头,从 `fmt ` 块拿采样率、`data` 块拿 S16LE 载荷。测试(sound.rs:871-947)每个决定钉一条:往返一致(sound.rs:878)、缺银行静默不致命(sound.rs:893)、残缺银行闩住不重入(sound.rs:907)、衰减落地而松手即切(sound.rs:925)。

## 你带走的收获

- 独占资源先建状态枚举,行为问题(谁能上台、怎么退场)变成状态机问题。
- 事件撞上长占用:丢弃比排队诚实——过期的 chirp 不值得等。
- 同一个"停"拆成两种退场(切/落地),bool 在这里不够用。
- 流式写管道要压住领先量:领先多少,松手后就晚多少。
- 降级路径也要有状态,否则降级本身变成每秒五十次的资源风暴。

## 延伸

- 合成与混音(Live、写线程、合唱声部):[解读 118](118-soundrs二合成混音.md)
- 三态的意图侧:[解读 10](10-意图层.md);导览:[解读 12](12-电池声音与彩蛋.md)
- 本地:`/Volumes/dev/dev/microduck/robotd/src/sound.rs`
