# 解读 124 · mdp.py(三):reward 函数精选

> **解读对象**:`microduck-replica/upstream/microduck_rl/src/mjlab_microduck/tasks/mdp.py`,抽读五个代表性 reward 函数(全文件 7188 行)
> **需要的前置**:[解读 24](24-velocity配置下.md)(reward term 怎么配权重)、[解读 26](26-奖励函数库.md)(同文件 reward/事件库总览)

reward 函数是在给"什么算好"下定义。本篇挑五个,正好是五种典型手法:势函数、滞回税、一次性悬赏、频率窗、乘法门控。

## 势函数:upright_progress

`upright_progress`(546-572 行)奖励的是**每步的 Δcos(倾斜角)**,不是倾斜角本身。cos(tilt) 由四元数两行算出:`1 − 2(qx² + qy²)`;每环境缓存上一步的值,差值即奖励。docstring 点明原理:potential-based shaping(Ng 等人证明的结论——"只奖励势能变化"不会改变最优策略)使"保持任何姿势"都得零分,趴下要扣、起来赚回,没有可薅的状态;一次完整的趴→立全程共收约 +1。开头两步(`episode_length_buf <= 1`)强制清缓存,防止上一回合的姿势漏进差值。`height_progress`(575-601 行)是 z 轴姊妹篇,深度蹲起的"最后一公里"主要靠它。

## 滞回税:fallen_state_penalty

`fallen_state_penalty`(604-643 行)在摔倒时每步返回 1.0(配负权重用)。注释里有一句铁律:"罚坏状态是安全的;**门控在坏状态上的正奖励才会被薅**"。不带参数时就是简单的摔倒判据;传 `release_tilt_below_deg`/`release_z_above` 后变成滞回闸门 `_fallen_tax_armed`(635-642 行):真摔才布防,直到"倾角小于释放角**且**高度超过释放高度"才解除——否则policy学会在 40° 门下方找个低姿态歇脚,起身永远差最后一步。

## 一次性悬赏:recovery_success

`recovery_success`(646-680 行)在"完成起身"的那一帧发奖金:先摔倒(倾角 > 40°)累计满 0.5 秒(`min_fallen_s`)才布防,之后某帧同时满足倾角 < 25° 且躯干 z > 0.105 即触发一次。触发即撤防(`_recovery_armed &= ~fired`,679 行),在门口来回摇摆一分不得——给稠密塑形补上稀疏但强的终点梯度。

## 频率窗:contact_frequency_penalty

`contact_frequency_penalty`(1761-1831 行)治"小碎步"。它维护每环境的接触变化计数器和计时器(`_contact_change_count`/`_contact_change_timer`,1796-1818 行),每满 1 秒结算:每秒换脚超过 `max_contact_changes_per_sec=4.0` 的部分按平方罚。命令幅值低于 0.01(站着)不罚(1784-1790 行)。注意它也是 122 篇说的"挂 env 状态"家族成员,`reset_action_history` 里专门有清它的一段。

## 乘法门控:glide_reward

`glide_reward`(4744-4789 行)奖励轮滑的"单脚滑行":四个因子相乘——`single`(恰有一只刀架触地)× `forward_gate`(前进速度爬升到 vel_ref=0.2 才满分)× `stillness`(腿关节速度平方和的负指数,stillness_std=5.0)× `active`(cmd_x ≥ 0)。docstring 直言这是修 bug 的产物:早先版本漏了 single 因子,结果"双脚着地扭着滑"(swizzle)能把奖励薅走、步态倒退。乘法门控的哲学:每个因子单独看都能找到作弊解,连乘后必须同时满足才有钱。

## 你带走的收获

- 奖励"变化量"而不是"状态量"(Δcos),天然防薅还有理论背书(potential-based shaping 不改最优策略)。
- 正奖励要门控,门控要有滞回:布防/解除用不同阈值,否则门下就是免费休息区。
- 稀疏悬赏配稠密塑形:布防条件(摔够 0.5 s)防止单次事件反复领赏。
- 乘法门控优于加法叠加:想要"同时满足多个条件"时,连乘,别相加。

## 延伸

- 同文件奖励库总览与 NaN 补丁:[解读 26](26-奖励函数库.md)
- 这些函数在配置里的权重:[解读 24](24-velocity配置下.md);文件骨架:[解读 122](122-mdp一文件结构.md)
- 本地路径:`microduck-replica/upstream/microduck_rl/src/mjlab_microduck/tasks/mdp.py`
