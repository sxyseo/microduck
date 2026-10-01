# 解读 136 · slope_terrain.py:坡地生成

> **解读对象**:`microduck-replica/upstream/microduck_rl/src/mjlab_microduck/tasks/slope_terrain.py`(115 行)
> **需要的前置**:[解读 135](135-roller家族.md)(roller_slope 消费方)、[解读 23](23-velocity配置中.md)

## 一块地形 = 三个 box

这是全库最小的地形文件,也是 roller_slope 任务唯一的场景生成器(有趣的是注释是法文的)。`FlatRampTerrainCfg`(:34)继承 mjlab 的 `SubTerrainCfg`,`function()`(:55)沿 +x 摆三个 box:

1. **出发平段**:表面 z=0,长 `flat_length=2.0 m`,机器人在这里 reset(:71-75)。
2. **下坡段**:一个绕 +y 轴转 `angle` 角的 box;坡长 `ramp_length` 从 (3.0, 8.0) m 每块地形随机抽一次(:67),落高 `drop = ramp_length·tan(angle)`(:68)。
3. **出口平段**:表面在 z=-drop,长 4.0 m——"让机器人落在实地上而不是虚空"(:94-100)。

坡度由难度线性插值:`ramp_angle_by_difficulty()`(:26-31)把难度 0–1 映射到 `[RAMP_DEG_MIN, RAMP_DEG_MAX] = [2°, 20°]`(:22-23);roller_slope 铺 10 行地形就是 10 级坡度,课程推进难度。

## 一行几何修补最值得读

第 84 行:`ramp_cx = flat_length + ramp_length/2 - (t/2)·sin(angle)`。注释解释:不加这个 `-(t/2)·sin(angle)` 偏移,倾斜 box 的**上表面边缘**会越过平段终点,接缝处出现一条小缝;加了之后坡顶恰好贴住平台边缘、坡底恰好接上出口平段(:77-83)。同类细节还有 `surf_len = ramp_length/cos(angle)`(:83):box 尺寸沿坡面量,而 `ramp_length` 是水平投影,斜边要除以 cos——旋转几何的"表面"与"投影"差一个 sin/cos 因子,凡拼接处都要补这笔账。

返回的 `TerrainOutput` 还把出生点 `origin` 挪到坡上 0.3 m 处(`spawn_on_ramp`,z = -0.3·tan(angle),:105-107):机器人在斜面上出生,重力立刻让轮子滚起来——初始动量给到**轮子**上;roller_slope 因此不再注入基础速度,避开了"底座快、轮子不动"的打滑 → 接触尖峰 → NaN 链条。入口有断言(:58-61):`flat + ramp_max + runout` 必须装进 `size[0]`,roller_slope 用 15×4 m 的瓦片装下最长 14 m 还有余量。

## 你带走的收获

- 程序化地形的最小形态就是"box + 位置 + 四元数":一段坡 = 一个旋转的 box,不需要高度场。
- 接缝误差来自旋转体的表面边缘与包围盒差 `(t/2)·sin/cos` 一项——这是所有旋转几何拼接的通用坑。
- 把 spawn 点焊在地形特征上(坡面),比在环境层"给初速度"更物理、更不易 NaN。
- 难度参数化(角度 = f(difficulty))是地形课程的标准接口:生成器按难度铺行,课程只管推难度。

## 延伸

- 消费方配置(命令清零、NaN 消毒、`terrain_levels_slope` 课程):[解读 135](135-roller家族.md) 的 roller_slope 段
- velocity rough 地形里的另一族坡(高度场 `HfPyramidSlopedTerrainCfg`,0.03–0.10 坡比):`microduck_velocity_env_cfg.py:161-166`
- 可视化脚本:`scripts/view_slope_terrain.py`;本文件:`.../tasks/slope_terrain.py`
