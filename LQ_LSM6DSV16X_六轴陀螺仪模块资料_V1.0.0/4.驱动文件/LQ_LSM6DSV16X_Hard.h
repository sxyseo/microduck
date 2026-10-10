/*******************************************************************************
 *  @file                 LQ_LSM6DSV16X_Hard.h 本文件是LQ_AI8051U_Library 软件开源库文件的一部分
 *  @copyright            版权所有 (C) 2025-2026 北京龙邱科技有限公司
 *  @website              http://www.lqist.cn
 *  @taobao               http://longqiu.taobao.com
 *
 *  @description          龙邱科技 AI8051U核心板驱动库声明
 *
 * 开发环境配置:
 *   - 开发平台 : Keil C251 v5.6.0
 *   - 文件编码 : GB2312
 *   - 目标芯片 : STC AI8051U (@  64K flash ROM, 34K SRAM(2KB SRAM(edata)+32KBRAM(xdata)))
 *   - 外置晶振 : 无 (使用后内部高速IRC)
 *   - 系统PLL : 40MHz (可超频使用)
 *
 * 本文件遵循GPL-3.0开源协议发布，旨在为AI8051U芯片嵌入式系统设计提供快速上手开发应用程序的参考实现
 * 商业用途（包括单位使用）需提前联系作者获得授权
 *
 * GPL-3.0 许可证声明摘要:
 * 1. 允许自由使用、修改、分发本软件
 * 2. 分发修改后的版本时，必须以相同许可证发布
 * 3. 必须保留原始版权声明和许可证信息
 * 4. 不提供任何担保，使用风险自负
 * 5. 完整协议文本请参见项目根目录 LICENSE 文件
 *
 * @author               Guard_Byte
 * @version              V2.1.0
 * @update               2026年6月24日
 *******************************************************************************/

#ifndef __LQ_LSM6DSV16X_HARD_H
#define __LQ_LSM6DSV16X_HARD_H

#include "include.h"

#define LSM6DSV16X_HARD_SPI // 硬件SPI方式读取LSM6DSV16X六轴陀螺仪
// #define LSM6DSV16X_HARD_IIC           // 硬件IIC方式读取LSM6DSV16X六轴陀螺仪,暂未完善->不可用

#define LSM6DSV16X_CK_HARD_IO         P43
#define LSM6DSV16X_DI_HARD_IO         P41
#define LSM6DSV16X_DO_HARD_IO         P42
#define LSM6DSV16X_CS_HARD_IO         P40

#define LSM6DSV16X_CK_STA(n) GPIO_Set_Bit(LSM6DSV16X_CK_HARD_IO, n)
// #define LSM6DSR_DI_STA(n)   GPIO_Set_Bit(LSM6DSR_DI_HARD_IO,n)  // 硬件自动完成
// #define LSM6DSR_DO_STA(n)   GPIO_Set_Bit(LSM6DSR_DO_HARD_IO,n)  // 硬件自动完成
#define LSM6DSV16X_CS_STA(n) GPIO_Set_Bit(LSM6DSV16X_CS_HARD_IO, n)

/*
 * 使用 I2C 通信方式时，七位地址其中 SDA[0] 与 AD0 脚有关，AD0 接低电平则为 0，AD0 接高电平则为 1
 * LSM6DSV16X I2C地址（7-bit）
 */

typedef enum
{
    LSM6DSV16X_AD0_PIN      = P4_2,     /* IIC  通信时ADO 所用引脚来确定设备ID */
    LSM6DSV16X_ADO          = LOW,      /* 根据 ADO 引脚电平，选择低还是高     */

    LSM6DSV16X_BASE_ADDR    = (0x6A | LSM6DSV16X_ADO), // 7-bit I2C地址（ADO=0）
    /* ADO=0 → 7-bit:0x6A, 8-bit写:0xD4, 8-bit读:0xD5  (ADDR_7BIT << 1) */
    /* ADO=1 → 7-bit:0x6B, 8-bit写:0xD6, 8-bit读:0xD7  (ADDR_7BIT << 1 | 1) */
    LSM6DSV16X_ADDR         = (LSM6DSV16X_BASE_ADDR << 1),
    LSM6DSV16X_ADDR_READ    = (LSM6DSV16X_ADDR | 0x01), // I2C 8-bit读地址

    LSM6DSV16X_DRV_ID       = 0x70,  /* 设备ID */
    LSM6DSV16X_WHO_AM       = 0x0F,  /* 设备ID寄存器 */

    LSM6DSV16X_FUNC_CFG     = 0X01,  /* 功能配置访问(含SW_POR)寄存器 */
    LSM6DSV16X_PIN_CTRL     = 0x02,  /* 引脚控制 */
    LSM6DSV16X_IF_CFG       = 0x03,  /* 接口配置 */

    LSM6DSV16X_CTRL1_XL     = 0X10,  // 加速度计控制1 (ODR, op_mode)
    LSM6DSV16X_CTRL2_G      = 0X11,  // 陀螺仪控制2 (ODR, op_mode)
    LSM6DSV16X_CTRL3_C      = 0X12,  // 控制3 (SW_RESET, BDU, IF_INC)
    LSM6DSV16X_CTRL4_C      = 0X13,  // 控制4
    LSM6DSV16X_CTRL5_C      = 0X14,  // 控制5
    LSM6DSV16X_CTRL6_C      = 0X15,  // 控制6 (Gyro FS)
    LSM6DSV16X_CTRL7_G      = 0X16,  // 陀螺仪控制7
    LSM6DSV16X_CTRL8_XL     = 0X17,  // 加速度计控制8 (XL FS)
    LSM6DSV16X_CTRL9_XL     = 0X18,  // 加速度计控制9
    LSM6DSV16X_CTRL10_C     = 0X19,  // 控制10

    LSM6DSV16X_STATUS_REG   = 0X1E,

    LSM6DSV16X_OUT_TEMP_L   = 0x20, // 温度低字节
    LSM6DSV16X_OUT_TEMP_H   = 0x21, // 温度高字节

    LSM6DSV16X_OUTX_L_G     = 0x22, // 陀螺仪X低字节
    LSM6DSV16X_OUTX_H_G     = 0x23, // 陀螺仪X高字节
    LSM6DSV16X_OUTY_L_G     = 0x24, // 陀螺仪Y低字节
    LSM6DSV16X_OUTY_H_G     = 0x25, // 陀螺仪Y高字节
    LSM6DSV16X_OUTZ_L_G     = 0x26, // 陀螺仪Z低字节
    LSM6DSV16X_OUTZ_H_G     = 0x27, // 陀螺仪Z高字节

    LSM6DSV16X_OUTX_L_A     = 0x28, // 加速度X低字节
    LSM6DSV16X_OUTX_H_A     = 0x29, // 加速度X高字节
    LSM6DSV16X_OUTY_L_A     = 0x2A, // 加速度Y低字节
    LSM6DSV16X_OUTY_H_A     = 0x2B, // 加速度Y高字节
    LSM6DSV16X_OUTZ_L_A     = 0x2C, // 加速度Z低字节
    LSM6DSV16X_OUTZ_H_A     = 0x2D, // 加速度Z高字节

    // LSM6DSV16X CTRL3_C 位定义
    LSM6DSV16X_SW_RESET     = (1 << 0),   // 软件复位
    LSM6DSV16X_IF_INC       = (1 << 2),   // 地址自动递增
    LSM6DSV16X_BDU          = (1 << 6),   // 块数据更新
    LSM6DSV16X_BOOT         = (1 << 7),   // 重启

    // LSM6DSV16X CTRL1_XL ODR值 (bits [3:0])
    LSM6DSV16X_XL_ODR_OFF      = 0x00,
    LSM6DSV16X_XL_ODR_1Hz875   = 0x01,
    LSM6DSV16X_XL_ODR_7Hz5     = 0x02,
    LSM6DSV16X_XL_ODR_15Hz     = 0x03,
    LSM6DSV16X_XL_ODR_30Hz     = 0x04,
    LSM6DSV16X_XL_ODR_60Hz     = 0x05,
    LSM6DSV16X_XL_ODR_120Hz    = 0x06,
    LSM6DSV16X_XL_ODR_240Hz    = 0x07,
    LSM6DSV16X_XL_ODR_480Hz    = 0x08,
    LSM6DSV16X_XL_ODR_960Hz    = 0x09,
    LSM6DSV16X_XL_ODR_1920Hz   = 0x0A,
    LSM6DSV16X_XL_ODR_3840Hz   = 0x0B,
    LSM6DSV16X_XL_ODR_7680Hz   = 0x0C,

    // LSM6DSV16X CTRL1_XL op_mode (bits [6:4])
    LSM6DSV16X_XL_MODE_OFF     = 0x00,
    LSM6DSV16X_XL_MODE_LP      = 0x01,
    LSM6DSV16X_XL_MODE_HP      = 0x03,
    LSM6DSV16X_XL_MODE_OS      = 0x05,

    // LSM6DSV16X CTRL6_C Gyro FS (bits [3:0])
    LSM6DSV16X_GYRO_FS_125     = 0x00,
    LSM6DSV16X_GYRO_FS_250     = 0x01,
    LSM6DSV16X_GYRO_FS_500     = 0x02,
    LSM6DSV16X_GYRO_FS_1000    = 0x03,
    LSM6DSV16X_GYRO_FS_2000    = 0x04,
    LSM6DSV16X_GYRO_FS_4000    = 0x07,

    // LSM6DSV16X CTRL8_XL XL FS (bits [1:0])
    LSM6DSV16X_XL_FS_2G        = 0x00,
    LSM6DSV16X_XL_FS_4G        = 0x01,
    LSM6DSV16X_XL_FS_8G        = 0x02,
    LSM6DSV16X_XL_FS_16G       = 0x03,
} LSM6DSV_Reg_emu;

/*
 * CTRL1_XL寄存器中的 FS_XL[1:0]两位用来配置加速度计的最大量程选择
 量程(g)-----------------应用场景---------------------------------说明-------------------------------------
 ±2g 》16384 健康监测(如步行、跑步分析)        》|适用于人体运动检测，能够精确捕捉较小的加速度变化。
 ±4g 》8192  消费电子产品(如智能手机、平板电脑)》|能够覆盖日常使用中的大多数动作，包括倾斜、摇晃等。
 ±8g 》4096  运动设备(如智能手表、健身追踪器)  》|更广泛的运动范围，适合于更剧烈的体育活动，如篮球、足球等。
 ±16g》2048  汽车碰撞检测、工业震动监测        》|适用于高冲击环境，如汽车安全气囊触发机制，或者重型机械的振动分析。

 * CTRL1_XL寄存器中的ODR_XL[3:0]四位用来配置加速度计的数据输出速率
 */

void Lsm6dsv16x_WriteReg(uint8_t reg, uint8_t val);                                            // 向LSM6DSV16X寄存器写入数据
uint8_t Lsm6dsv16x_ReadReg(uint8_t reg);                                                       // 从LSM6DSV16X寄存器读取数据
void Lsm6dsv16x_Get_RawAcc(int16 *ax, int16 *ay, int16 *az);                                   // 获取加速度原始数据
void Lsm6dsv16x_Get_RawGyro(int16 *gx, int16 *gy, int16 *gz);                                  // 获取陀螺仪原始数据
void Lsm6dsv16x_Get_RawData(int16 *ax, int16 *ay, int16 *az, int16 *gx, int16 *gy, int16 *gz); // 获取加速度和陀螺仪原始数据

void LQ_LSM60DSV16X_Init(void); // 初始化LSM6DSV16X六轴陀螺仪

void Test_LSM6DSV16X_Hard(void); // 测试硬件SPI读取LSM6DSV16X六轴陀螺仪

#endif
