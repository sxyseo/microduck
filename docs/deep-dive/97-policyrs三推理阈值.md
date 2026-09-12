# 解读 97 · policy.rs(三):推理路径与切换阈值

> **解读对象**:`duck-control/src/policy.rs`(811 行)
> **需要的前置**:[解读 03](03-策略加载.md)(加载与校验导览)、[解读 02](02-观测拼装.md)(61 维输入怎么来)

导览见解读 03,本篇逐函数下钻:一次推理在 `Network::run` 里过哪些关卡,五张网络之间怎么切换,换策略文件时 LSTM 状态怎么"过户"。

## 1. `Network::run`:每个 tick 的一次推理

签名(policy.rs:478):

```rust
fn run(&mut self, observation: &Observation) -> Result<[f32; ACTION_LEN], PolicyError>
```

`Result` 是 Rust 的"成功或失败"返回值,`?` 运算符遇到错误就地返回。第一道关卡不是张量而是有限性:观测里有一个 NaN 或无穷就返回 `non-finite observation`(policy.rs:480-482)——垃圾输入不进 ONNX Runtime。

输入张量在 policy.rs:483 组装:`Value::from_array(([1usize, OBS_LEN], …))`,形状 `[1, 61]`,1 是 batch 维,推理永远单发。随后按导出形态分叉(policy.rs:485-490):`self.state` 是 `Option`,`None` 走纯前馈只喂 `obs`,`Some(LstmState)` 则把 `h_in`/`c_in` 一起喂进去。输出按名字 `action_name` 取张量(policy.rs:492-494),长度不是 14 或含非有限值就报 `expected 14 finite actions`(policy.rs:495-497)。

LSTM 分支的收尾最讲究(policy.rs:515-522):`h_out`/`c_out` 先做形状与有限性检查——注释原话 "Check both before updating either"——两个都验过才 `copy_from_slice` 写回状态,半新半旧的隐状态比全旧更毒。会话本身用 `INTRA_THREADS = 1` 建立(policy.rs:36,在 open 的 policy.rs:591 应用):四核 A55 上线程池的同步开销大于并行收益,注释留了"在板上重测"的尾巴。

## 2. `Policy::infer`:网络切换的状态机

签名(policy.rs:336)收 `&mut self`(可变借用,允许改自身状态)、观测引用与一个 `Net` 枚举,返回 `[f32; 14]`。第一步是回退解析(policy.rs:343-349):`match` 是 Rust 的枚举匹配,这里把"请求了没加载的网络"统一改写成 `Net::Walk`。顺序有讲究(policy.rs:341-342):回退必须在比较 `active` **之前**做,否则每个 tick 请求缺失技能都会被误判成"切换了网络",把走路网络白白 reset。

然后 `changed = self.active != Some(net)`(policy.rs:350),用 `Option` 记住的"上一 tick 用哪张网"判定切换;切换就 `network.reset()`(policy.rs:358-360)——LSTM 的 h/c 清零,新技能从零状态起步。推理失败在 policy.rs:362-368 处理:同样 `reset()` 且 `self.active = None`,注释一句话:"Never carry a failed inference's state into another control tick"。

## 3. 阈值、查询与状态过户

走/站切换的判据只有三行,`will_stand`(policy.rs:310-314):

```rust
self.stand.is_some()
    && !self.standing_disabled
    && twist_magnitude <= self.standing_threshold
```

阈值 `DEFAULT_STANDING_THRESHOLD = 0.05`(policy.rs:28)是原型的数,测试 `the_standing_threshold_matches_the_prototype`(policy.rs:696)钉住它:阈值错,机器人换步态的速度就和调好的不一样。调用方(`robotd/src/control.rs:530`)拿同一个答案决定增益与动作缩放,所以它必须是独立查询,而不是 `infer` 的副产品——"问两次不能得到两个答案"(policy.rs:308-309)。

`carry_over`(policy.rs:375-411)解决热替换:旧网络的 LSTM 状态要不要带走?判据不是路径而是 `digest`——`open` 时算好的文件 SHA-256(policy.rs:588)。路径相同内容可能已变(原地覆盖),内容相同路径可能不同(坐姿换装);只有 digest 相等才把 h/c 张量拷过去(policy.rs:394-408),否则从零开始。`robotd` 在策略热替换时调用它(`robotd/src/control.rs:281`)。`reset`(policy.rs:415-427)用迭代器链把所有槽位一口气清零。

## 你带走的收获

- 推理入口的第一道检查是输入有限性:垃圾张量不该进运行时。
- LSTM 状态"都验过才写回",避免半新半旧的隐状态——它比全新或全旧都难查。
- "切换即 reset"要防误判:先解析回退、再比较 active,顺序本身就是正确性。
- 热替换的同一性判据用文件内容摘要,不用路径。

## 延伸

- 五张网怎么加载、panic 怎么变错误:[解读 03](03-策略加载.md)
- run 的 61 维输入怎么拼:[解读 02](02-观测拼装.md)
- 输出 14 维怎么落到电机:[解读 103](103-safetyrs二apply.md)、[解读 04](04-安全层.md)
- 课程对照:`/Volumes/dev/dev/microduck/docs/course/19-ONNX合同.md`
