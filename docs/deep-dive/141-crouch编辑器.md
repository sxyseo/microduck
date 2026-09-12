# 解读 141 · crouch_pose_editor.py

> **解读对象**:`microduck-replica/upstream/microduck_rl/scripts/crouch_pose_editor.py`(99 行,全读:1 个函数 + 主干脚本)
> **需要的前置**:[解读 135](135-roller家族.md)(消费这份姿势的 RollerCrouch 任务)、[解读 127](127-constants逐段.md)(HOME_FRAME 常量)

训练 RollerCrouch 任务之前,得先回答"蹲下去是什么姿势"——14 个关节各多少弧度。这个脚本就是回答它的工具:打开 MuJoCo viewer,拖滑块把机器人摆成想要的蹲姿,关窗时自动打印一份 `CROUCH_POSE = {关节名: 弧度}` 字典。文件头(:1-12,法语 docstring)说明了两个物理约定:重力被关掉、基座被按住——你只管摆姿势,别的都不用管。产出的去向也写死在最后一行注释(:99):"Colle CROUCH_POSE ici et donne-le a Claude pour cabler la reward"——粘贴进 `microduck_roller_crouch_env_cfg.py:72` 的 `CROUCH_POSE`,接进 crouch 奖励。

## 搭台:重力归零与两个清单(26-63 行)

`home_value`(:26-30)是唯一的函数:拿关节名去 `HOME_FRAME.joint_pos` 里逐条正则匹配,返回命中项的值,都不中就回 0.0——HOME_FRAME 的键本来就是正则(`.*hip_pitch.*` 这类),所以直接 `re.search` 复用。模型不经过任何环境工厂,直接 `get_walk_rollers_spec().compile()`(:34)从 spec 编译;随后一行定调性:`model.opt.gravity[:] = [0, 0, 0]`(:37)——注释说"rien ne s'effondre":没有重力,姿势就不会自己垮,滑块拨到哪就停在哪,编辑器才像编辑器而不是物理沙盒。

两个清单决定交互范围:关节清单(:42-47)遍历所有铰链,跳过 freejoint 和所有 `passive_` 轮子,只留 14 个可摆的关节;执行器初始 ctrl 全部设为 HOME 姿势(:50-52)——打开时鸭子是站着的标准站姿,不是瘫着的随机姿势。若有自由基座,把它钉在 `z=0.14`、单位四元数(:55-58),这个高度后面还要用。

## 主循环:钉住、步进、贴地(70-90 行)

60 Hz 的 `while viewer.is_running()` 循环每拍做三层。第一层是"钉":viewer 里拖基座也许会改写 qpos,所以每步开头把平移、四元数、速度全部写回缓存值(:72-75)——基座永远纹丝不动。第二层是"走":`mj_step`(:76)让 position actuator 把每个关节拉向滑块目标,滑块就是 MuJoCo viewer 的 Control 面板里每个 actuator 的 ctrl 滑条。第三层是"贴地"(:82-88):重新算一遍 forward,然后 `zmin = min(geom_xpos[g, 2] - geom_rbound[g])`——所有几何体最低点(中心 z 减去包围球半径)到地面的距离;把 `qpos[2]` 减去这个 zmin 再 forward 一次,基座高度自动跟随姿势调整,**最低点永远贴着地面**。这正是文件头承诺的体验:"你看到的是躯干在下降"——屈膝时基座自动下沉,下沉量就是真实的蹲深。

## 收尾:从 viewer 到代码(92-99 行)

关窗后打印两样东西:逐关节的 `CROUCH_POSE = {name: qpos}` 字典,弧度保留 4 位小数(:94-95)——恰好是 reward 字典可直接粘贴的格式;外加一行基座最终高度 z 作参考(:97-98)。设计上它把"人类审美的姿势"到"机器可读的奖励目标"之间的翻译做成了自动的:人的输入是拖滑块,输出是精确到万分之一弧度的字典。对比 135 篇的 `crouch_pose` 奖励项:那份字典里的每个数字,理想流程里都来自这一次关窗。

## 你带走的收获

- 交互式标定工具的三件套:关重力、钉基座、贴地——把问题削减到只剩"摆姿势"这一件事。
- 用 `geom_xpos - rbound` 求最低点做地面贴合,是"让物体站上任意地形"的通用小技巧。
- 工具输出应该直接是下游代码的粘贴格式:4 位小数的 Python 字面量,零手工转换。
- 复用既有正则键(HOME_FRAME 的 `.*hip_pitch.*`)时,新工具不必发明新的参数表示。

## 延伸

- 字典的消费方(crouch_pose 奖励):[解读 135](135-roller家族.md) 的 RollerCrouch 段
- HOME_FRAME 的来历与 STAND 姿势:[解读 127](127-constants逐段.md)
- 本地路径:`microduck-replica/upstream/microduck_rl/scripts/crouch_pose_editor.py`、`.../tasks/microduck_roller_crouch_env_cfg.py`
