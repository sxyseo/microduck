# 解读 100 · obs.rs(一):61 维观测逐位

> **解读对象**:`duck-control/src/obs.rs`(406 行)
> **需要的前置**:[解读 02](02-观测拼装.md)(布局与命令块导览)、[解读 06](06-姿态解算.md)(gyro/gravity 从哪来)

导览见解读 02,本篇逐函数下钻:先看输入端的三个类型,再进 `build` 看缓冲区怎么被切成六块,最后是三个生命周期小函数。

## 1. 输入端:`Command`、`BodyPose` 与模长

`Command`(obs.rs:76-83)是"客户端想让机器人做什么"的结构化形式:`twist` 三元组、`head` 四元组、`body` 三个 `f64`。文档点明它的身份(obs.rs:73-74):按物理单位持有,到扁平命令块的换算只发生在 `build` 里,"nowhere else"——换算只写一处,就不会有两处各错各的。`twist_magnitude`(obs.rs:87-89)三行算速度指令模长:

```rust
self.twist.iter().map(|v| v * v).sum::<f64>().sqrt()
```

它只看 twist:测试 `twist_magnitude_ignores_head_and_body`(obs.rs:391-405)把 head 与 body 全填 1.0,断言模长仍是 0——因为模长是走/站切换的唯一判据(见解读 97 的 `will_stand`),抬头不能被当成走路。`BodyPose`(obs.rs:95-99)只有 z/roll/pitch 三个字段,注释坦白 slice 2 尚不可指令(obs.rs:92-93):先占位,等 `pose` 意图落地,布局图先画完整。

## 2. `build`:把 61 个 f32 切成六块

签名(obs.rs:174-181)六个参数:IMU、绝对关节角、关节速度、home 位、上次动作(14 维 f32)、命令。核心手法是把缓冲区按布局表逐块"劈"出来(obs.rs:189-194):

```rust
let (gyro, rest) = data.split_first_chunk_mut::<3>().expect(LAYOUT);
let (gravity, rest) = rest.split_first_chunk_mut::<3>().expect(LAYOUT);
```

`split_first_chunk_mut::<N>()` 劈出前 N 个可变元素,返回 `Option`(劈不动即 `None`);这里各块宽度全是常量、总和恰为 61,`expect` 不会触发,还有测试 `the_layout_widths_sum_to_the_declared_input`(obs.rs:288)钉着总和。劈完每块都是定长数组,宽度进了类型,`fill`(obs.rs:134)就只可能收到同宽的源;它内部一行 `values.map(|value| value as f32)`(obs.rs:135)完成 f64→f32 收窄。位置块要过一道减法:关节角与 home 位各自压成 14 维,再逐项相减(obs.rs:199-201)——策略训练时看的是相对角。上一动作块连 `fill` 都不用(obs.rs:204-206):已是 f32、同宽,`*previous_action = *last_action` 纯拷贝。命令块是唯一"照文档手写"的段落:13 个字面量按布局表顺序排进数组字面量(obs.rs:210-227),注释说这正是目的——"这个块没有第二真相来源,所以它应该能对着文档用眼睛核对"(obs.rs:208-209)。

## 3. 三个生命周期小函数

`Observation` 本体是 `[f32; 61]` 而非 `Vec`(obs.rs:139-145):它每秒重建 50 次,不该访问堆分配器。围绕它的三个小函数:`as_slice`(obs.rs:155-157)把内部数组以切片借出,给 `policy.rs` 的有限性检查用;`zeroed`(obs.rs:163-167)造全零观测,注释强调它"不是有效机器人状态",只用于预热推理(obs.rs:160-162,见解读 03);`From<[f32; 61]>`(obs.rs:148-152)把一份已拼好的观测原样灌回来,文档标注用于离线策略回放(obs.rs:147)。三个函数合起来划出边界:观测要么由 `build` 从真实传感器造,要么由测试/回放显式注入,没有第三条路。

## 你带走的收获

- 命令按物理单位持有、扁平化只写一处;模长只取速度三元组,别的通道不得污染走/站判据。
- 用 `split_first_chunk_mut` 把缓冲区按表劈成定长块:宽度进类型,块宽错了编译不过。
- 没有第二真相来源的段落写成"照文档可核对"的字面量——可读性本身就是正确性手段。
- 热路径数据结构避开堆:定长数组每秒重建 50 次不碰分配器。
- 类型还可以表达"来路":build 产出、From 注入,两条构造路径都写在明面上。

## 延伸

- 布局表与命令块的三个坑:[解读 02](02-观测拼装.md)
- build 的产物喂给谁、切换阈值怎么用:[解读 97](97-policyrs三推理阈值.md)
- 14 维怎么摊回 15 个关节:[解读 101](101-obsrs二scatter写回.md)
- 课程对照:`/Volumes/dev/dev/microduck/docs/course/04-61到14-鸭子的神经回路.md`
