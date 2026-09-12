# 解读 120 · chorale.rs(一):合唱结构

> **解读对象**:`robotd/src/chorale.rs`(1320 行,本篇读 1-631 的结构主干)
> **需要的前置**:导览见[解读 12](12-电池声音与彩蛋.md);声部怎么唱见[解读 118](118-soundrs二合成混音.md);信标队列见[解读 10](10-意图层.md)

鸭子合唱的行为层:谁指挥、谁唱哪个声部、唱到第几拍。分工在文件头(chorale.rs:1-5):`btd` 管无线电不思考;这里思考不碰无线电,两者只过 `chorale.*` 信标。没有服务器、共同时钟、投票,四只鸭却能唱同一首歌。

## 1. 身份与曲单

`Chorale::new`(chorale.rs:198-228)定下信标身份:`register` 由嗓音的音高中心量化(chorale.rs:200,低音鸭天生是低音声部);`id` 取种子混洗后的十六位(chorale.rs:206)。注释记了一场事故:曾是 8 位,四鸭房间第一天就撞号,有只鸭从此加不进来(chorale.rs:201-205)。曲单是三个常量(chorale.rs:60-66):wistful、duck_strut,和如实标着"TEST ONLY — remove before release"的 outer_wilds。曲单的意义:不认识某 id 的鸭**继续听而不是加入**——瞎猜就是对唱两首歌(chorale.rs:56-59)。

## 2. `State`:四态装下全部人生

`Off / Listening{since} / Conducting{conductor, roster} / Following{…}`(chorale.rs:113-144)。最值得细读的是 `Following.conductor` 的注释(chorale.rs:127-138):指挥以**信标 id** 记,绝不以 radio 地址记——"这是让合唱永远同步不了的那个 bug,而且犯了两次";BLE 隐私地址几秒一换,跟着地址认指挥的鸭会拒收之后的每一拍,相位锁饿死,从此不唱。同状态的 `last_beat`(chorale.rs:142-143):信标一拍重播好几次,重读同一计数值不算又一拍,喂进去相位会拖后半个广播间隔(chorale.rs:360-365)。对外的 `Tick`(chorale.rs:147-164)里有个微妙的 `voices`:它不是 roster 长度——走出范围的鸭**保留座位**(裁掉它会把下面所有人换声部),那行谱只是空着(chorale.rs:158-163)。

## 3. `tick`:从旁听到指挥

每拍入口(chorale.rs:382-462)先裁掉 3 秒没音讯的同伴(`PEER_STALE`,chorale.rs:43)。`Listening` 两条出路:**有人在唱认识的曲子就加入**(chorale.rs:396-424)——第二个指挥不允许存在;**没人唱、自己 id 最小、过了 `SETTLE = 1.5 s`(chorale.rs:51)就开团**(chorale.rs:425-448)。低 id 指挥是确定性的:两只鸭从同样的信标推出同样的答案,没有选票可丢(chorale.rs:705 测试)。开团时 roster 按加入顺序收录、超 `MAX_ROSTER` 截断(chorale.rs:429-431);选曲先看操作者的钉子,没有就用时钟低位当硬币(chorale.rs:437-439)。`Conducting` 分支(chorale.rs:464-506)每拍把新鸭**追加**进 roster——只增不重排,已开唱的鸭才不会换声部;曲终判定 `position > 总拍数 + 2`(chorale.rs:491-496)——它曾经不会结束。`Following` 分支(chorale.rs:522-552)晚 6 拍才认输,把领路权留给指挥的重启;还没被排座的鸭报 `joining: true`(chorale.rs:155-157)。

## 4. 座位表、广播与表达

`heard`(chorale.rs:264-368)收信标:滤掉自己的回声(chorale.rs:269-271),按 id 合并同伴;指挥换曲或拍计数倒退(倒退 4..128 拍算重启,小前进只是漏拍,chorale.rs:326-330),跟随者换谱重建相位锁。`my_part`(chorale.rs:558-570)是座位表的消费端:拿自己在 roster 的序号,取 `seat_all` 按全体 register 排好的声部表——**人人重放同一张表**,不会有俩中音。广播被 `publish`(chorale.rs:586-597)限流到"变了才发":50 Hz 的循环、一秒一翻的拍,不限流就是百倍 D-Bus。彩蛋级函数 `head_expression`(chorale.rs:617-631):头部摇摆由**乐谱位置**而非本地时钟驱动——所有鸭从同一拍数算出同一摆动,编舞是同步的免费赠品;幅度刻意小,头上驮着 ToF。

## 你带走的收获

- 无时钟多机同步三件套:确定性选主(低 id)、权威方广播座位表、拍计数当时间基。
- 身份绝不下沉到会变的层:BLE 地址轮换,信标 id 才是指挥的身份证。
- 重复信标与倒退计数都是信息:去重靠 `last_beat`。
- 名册保留离席者座位:重排的代价高于一行空谱。
- 限流广播:载荷不变就不发。

## 延伸

- 曲子数据与音频渲染在下半场;声部合成:[解读 118](118-soundrs二合成混音.md);导览:[解读 12](12-电池声音与彩蛋.md)
- 本地:`/Volumes/dev/dev/microduck/robotd/src/chorale.rs`
