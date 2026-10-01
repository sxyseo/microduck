# 解读 96 · policy.rs(二):`validate` 与加载门

> **解读对象**:`duck-control/src/policy.rs`(811 行;`validate` 在 450–453,`open` 在 583–687)
> **需要的前置**:[解读 95](95-policy一Net与技能.md)(`Net` 与技能枚举)、[解读 03](03-策略加载.md)(导览篇)

`validate`(policy.rs:450-453)只有两行:`ensure_runtime()?` 之后 `catching_ort_panics(|| open(path).map(drop))`。学问一半在注释里(policy.rs:430-449),一半在被它调用的 `open` 里——文件真正的大门:一个 `.onnx` 要过八道检查才能变成 `Network`。

## 1. `validate`:回答一个问题,不开一场会

两个调用方,需求的两端:IPC 的 `robot.loadPolicy` 要**同步**回答客户端,而真正的切换发生在几秒后的 home pose——在这里先验,才能把"接受了却没生效"变成一句即时的 `observation width is 51, expected 61`;启动检查则逐槽验证 override,让一个坏槽只废那一槽,不废整个策略(policy.rs:434-439)。

它刻意**不做预热推理**:"这是对文件的问题,不是对即将被驱动的会话"(policy.rs:441-443)。所以它证明的更少——能打开且形状对,不等于能跑;没人把通过当保证,home pose 加载失败时控制器保留旧策略。成本也写在注释里:**开会话要几十毫秒,tick 只有 20**,所以绝不进 tick,IPC 调用方用自己的 runtime 跑(policy.rs:447-449)。

## 2. `open`:八道门逐道走

`Result<T, E>` 是 Rust 的"可能失败"类型(`Ok`/`Err` 两个变体),`?` 把错误向上返回。`open`(policy.rs:583-687)就是一条 `Result` 流水线:

1. **读文件**(584-587):失败进 `PolicyError::Read`,错误里带路径;
2. **算指纹**(588):`Sha256` 摘要存进 `Network.digest`,`carry_over` 靠它判断"是不是同一份模型字节"(policy.rs:395);
3. **开会话**(589-596):优化级别 Level3、单线程(`INTRA_THREADS = 1`,policy.rs:36——四核 A55 上线程池的同步开销大于收益);
4. **观测宽度**(600):`check_matrix(…, "obs", OBS_LEN = 61)`;
5. **输入/输出契约**(601-612):`(1,1)` 是前馈,`(3,3)` 是 LSTM(obs/h_in/c_in → actions/h_out/c_out),**其他数量直接拒**,错误消息把合法契约写出来;
6. **动作宽度**(619):输出 14;
7. **LSTM 状态形状**(621-651):h/c 四个张量的 `[层数, 批, 隐宽]` 必须一致,层数/隐宽为正,批可动态 `-1`;
8. **配额与分配**(653-676):状态元素数上限 `1_048_576`(policy.rs:656)——损坏的模型不能让它申请无穷内存;全过才分配两个全零张量当状态缓冲。

## 3. 三把尺子与错误的讲究

`tensor_shape`(policy.rs:539-553)要求张量且 `float32`,否则报出实际类型。`outlet`(policy.rs:555-568)按名字找张量,签名 `outlet<'a>(path, outlets: &'a [Outlet], name) -> Result<&'a Outlet, _>` 里的 `'a` 是**生命周期标注**:告诉编译器"返回的引用与传入的切片活一样久"——借来的东西不能比原件活得长。`check_matrix`(policy.rs:570-581)只收二维 `[1 或 -1, width]`:最后一维必须精确,前导维是批,可以是动态 `-1`。

错误侧同样讲究。`PolicyError::Shape`(policy.rs:54-60)同时带 `expected` 和 `got`——"错误的策略文件"和"错误的守护进程"长得一样,不报两个数分不开;`path()`(policy.rs:83-92)让 `RuntimeMissing`/`RuntimePanic` **不怪罪任何文件**:缺运行库是装机问题,报成"这个文件坏了"会骗人去换一个没坏的文件。panic 契约测试(policy.rs:743-765)钉着一块真板子的案发记录:`expected version >= '1.23.x', got '1.20.1'`——两个版本号就是全部诊断,必须活着抵达调用方。

## 你带走的收获

- "验形"与"能跑"是两个证明等级:`validate` 只卖前者,定价是同步、廉价、可立刻报错。
- 契约检查枚举合法形状而非拉黑坏的:`(1,1)`/`(3,3)` 之外全拒,新格式须显式开门。
- 对外部输入设资源配额:状态张量上限是给溢出和恶意文件画的线。
- 错误要带 `expected/got` 两个数,还要带"该怪谁"的判断——不是所有错误都姓"文件"。
- 加载时校验的全部意义:把失败挪到机器人还站着、还能说话的时候。

## 延伸

- `Net` 与技能枚举(上半场):[解读 95](95-policy一Net与技能.md)
- 导览版三道门与预热:[解读 03](03-策略加载.md)
- 校验失败的消费端(健康与回滚):[解读 09](09-主循环.md)
- 本地:`/Volumes/dev/dev/microduck/duck-control/src/policy.rs`
