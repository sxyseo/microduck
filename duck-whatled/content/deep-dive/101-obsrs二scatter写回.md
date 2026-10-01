# 解读 101 · obs.rs(二):`scatter_action` 写回

> **解读对象**:`duck-control/src/obs.rs`(406 行)
> **需要的前置**:[解读 02](02-观测拼装.md)(嘴槽位映射导览)、[解读 04](04-安全层.md)(写回去哪)

导览见解读 02,本篇逐函数下钻。策略只有 14 个输出,机器人有 15 个关节,嘴不归策略管——这一篇看 14 怎么摊回 15,以及摊开之后那串数在下游是什么意思。

## 1. `joint_of`:一个 const fn 管两个方向

全文件最短的核心(obs.rs:123-125):

```rust
const fn joint_of(slot: usize) -> usize {
    if slot < MOUTH_INDEX { slot } else { slot + 1 }
}
```

`const fn` 是能在编译期执行的函数,配 `#[inline]`(obs.rs:122)提示就地展开——它每 tick 读写各跑 14 次,必须零开销。`MOUTH_INDEX = 9`(model.rs:31):9 号之前的槽位直通,之后整体上移一格。注释给它立了规矩(obs.rs:117-121):写一次、双向使用——读方向 `policy_joints` 借它把 15 压成 14,写方向 `scatter_action` 借它把 14 摊回 15,两个方向走同一份映射,"就不可能对不上"。

## 2. `policy_joints`:读方向的宽度变换

签名(obs.rs:109):`fn policy_joints(values: &[f64; NUM_JOINTS]) -> [f64; OBS_JOINTS]`——参数与返回都是定长数组,宽度写进类型。文档解释了为什么不返回迭代器(obs.rs:105-108):过滤后的迭代器不是 `ExactSizeIterator`,数不出元素个数,下游 `fill` 就得在运行时数数。函数体两行:一行编译期断言(obs.rs:112)把"跳过一个合法下标,正好少一个"这个理由从注释升级成类型检查——`const { assert!(…) }` 在编译期执行,不成立就编不过;一行 `std::array::from_fn(|slot| values[joint_of(slot)])`(obs.rs:113),`from_fn` 用闭包按下标造数组,恰好是"映射"二字的字面实现。位置与 home 位各过一次它,再逐项相减,才有观测里"相对 home 的关节角"(见解读 100)。

## 3. `scatter_action`:写方向与下游语义

签名(obs.rs:237):`fn scatter_action(action: &[f32; ACTION_LEN]) -> [f64; NUM_JOINTS]`,收 14 维 f32 的引用,还 15 维 f64 数组。实现三行(obs.rs:238-244):数组从全零起,循环把每个策略输出 `as f64` 加宽(f32→f64 只补精度,不损值)后写到 `out[joint_of(slot)]`。嘴的槽位没人写,留在 0.0——测试 `scattering_an_action_skips_the_mouth`(obs.rs:371-386)用 1..14 的可区分值钉出这个"洞":`scattered[8]` 是 9.0 而 `scattered[10]` 是 10.0,9 号位是 0,错一格立刻现形。

那串数在下游是什么?`robotd/src/control.rs:606-610` 给出答案:

```rust
let offsets = Observation::scatter_action(&action);
targets[joint] = DEFAULT_POSITION[joint] + scale * offsets[joint];
```

scatter 的输出是**相对 home 位的偏移**,不是绝对目标:乘动作缩放后加到 `DEFAULT_POSITION`(model.rs:39)上。所以"嘴不动"的准确含义是零偏移——嘴留在 home 位;文档注释"its slot stays at whatever the caller had"(obs.rs:233-235)说的正是这件事在调用侧的表现。这也解释了返回值为何从全零初始化:没被写的槽位天然等于"零偏移",零在这里不是默认值的巧合,而是语义的一部分。

## 你带走的收获

- 互逆映射共用一个 `const fn` 是根治"读写各错各的"的办法;宽度进类型让错配编译期就炸。
- 过滤迭代器数不出长度:`ExactSizeIterator` 缺席时,返回定长数组比返回迭代器更诚实。
- 输出数组从零初始化不是偷懒:零 = 零偏移,是下游语义的一部分。
- 测试用可区分值,让"错位"表现为一个具体下标,而不是"机器人走路变差"。
- 策略输出是偏移量;缩放与 home 位相加发生在调用方——契约边界要能一句话说清。

## 延伸

- 61 维怎么逐块拼出来:[解读 100](100-obsrs一观测逐位.md)
- targets 进安全层的钳位与拒绝:[解读 103](103-safetyrs二apply.md)
- 课程对照:`/Volumes/dev/dev/microduck/docs/course/04-61到14-鸭子的神经回路.md`
