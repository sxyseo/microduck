# 解读 42 · Robot HAT C1:官方开源板怎么读

> **解读对象**:pollen-robotics/elec_RPI_Robot_HAT(本仓引用,Apache-2.0)+ `microduck-replica/docs/硬件方案逆向.md` §四
> **需要的前置**:[解读 41](41-电控架构总览.md)。第一次打开 KiCad 工程的话,读图五步法见[第 08 课](../course/08-看懂电路图.md)。

## 先讲一个勘误:它其实开源了

本仓 2026-09-03 之前的记录写的是"这块板未开源、需逆向"。**这是错的**:板子在 `pollen-robotics/elec_RPI_Robot_HAT` 有完整开源工程——KiCad 9 原理图与 PCB、Gerber、BOM、贴片坐标、STEP。漏掉的原因很典型:只检索了 `microduck` 主仓,没查同组织下 `elec_` 前缀的硬件仓库(`microduck-replica/PROGRESS.md` 勘误记录原文:"判断某项目有没有开源某部分时,必须检索整个组织")。

**结论:这块板不用画,直接用 `production/` 目录的 Gerber 打样。** 逆向文档 §四保留为"逆向 vs 实物"的对照记录——两相比较也很有价值:逆向推出的 I2C 地址 0x18、上拉位号 R12/R13,与官方 BOM 逐项命中。

## KiCad 工程里有什么

主图纸 `main.kicad_sch` 只实例化四张子图:`audio / dynamixel / power / sensors`。逐张能读到:

- **dynamixel 页**:TTL 三针座 J13/J14(JST EH 2.5mm,串 TH1 100Ω 热敏)+ RS-485 四针座 J3/J11(U8 SIT3088E 驱动)——一块板双制式,原理图旁注 **"3A max"**。
- **power 页**:U9 AP63205 降压 + L4 6.8µH → +5V;U10 LM5050-1 理想二极管。注意 LM5050-1 在 buck **之后**的 +5V 一路,不在电池输入端(2026-09-04 勘误,按符号 X 坐标排序核实)。
- **audio/sensors 页**:TLV320AIC3104 codec、LGA-16 的 BMI088(焊了但软件不用)、J5–J8 四个 Qwiic 座。

板子物理规格(取自官方 KiCad 与 Gerber,见 `microduck-replica/docs/硬件规格速查.md`):**65.0 × 30.9 mm、板厚 1.0 mm、4 层**(F.Cu/In1.Cu/In2.Cu/B.Cu),BOM **47 行 123 颗**。贴片位数两处文档口径不一:逆向文档记 118 个贴片位,电控采购清单记实际贴装 113 个位置(DNP 9 颗之差,待按官方 BOM 复核)——无论哪个数,结论一致:**必须走 SMT 贴片**。

## 打样前必读的四条警告

1. **板上没有充电电路。** 仓库里的 `pwr_supply_charge.kicad_sch` 是**孤儿图纸**——`main.kicad_sch` 没实例化它,标题栏写的还是别的项目(Chromapi)。BOM 里搜不到充电 IC、USB-C 母座。**电池必须外部充电。**
2. **打开工程要另装库。** 原理图引用 `Library_Pollen` 等符号库,在 `pollen-robotics/lib_KiCAD` 仓库;只打样则不需要,直接用 Gerber。
3. **四层板 + VQFN/LGA 封装,必须走 SMT 贴片**,手焊不现实。
4. **U4(CAT24C32 EEPROM)是 DNP 不贴** → 这不是自识别 HAT,设备树 overlay 要手动配。

## 你带走的收获

1. **开源 ≠ 买得到**:有完整 Gerber 仍需自己送厂制造(Rhoban/microban 的 BOM 原话),但"能打样"和"要设计"是两个难度级别。
2. **孤儿图纸的识别方法**:看顶层图纸实例化了哪些子图;再对 BOM 核对图纸上的器件是否真的在单。
3. **DNP 是刻意的省略**:不贴 EEPROM = 放弃 HAT 规范的自动识别,换取省料——读 BOM 时 DNP 行要单独过一遍。
4. **逆向与官方资料对照是双向校验**:代码推出来的位号能命中,说明方法可信;官方图里多出来的器件(功放、麦克风)则是纯代码看不出来的部分。

## 延伸

- [解读 41](41-电控架构总览.md):HAT 在整机架构中的位置
- [解读 45](45-电源树.md):HAT 上那颗 buck 的来龙去脉
- [解读 49](49-打样流程.md):拿到 Gerber 之后怎么下单
- 本地:`microduck-replica/docs/硬件方案逆向.md` §四、`microduck-replica/PROGRESS.md`(勘误记录)
