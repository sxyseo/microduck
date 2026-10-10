/*******************************************************************************
 *  @file                 LQ_LSM6DSV16X_Hard.c 本文件是LQ_AI8051U_Library 软件开源库文件的一部分
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

#include "LQ_LSM6DSV16X_Hard.h"
#include "include.h"

#if defined(LSM6DSV16X_HARD_SPI)
/*
 * @brief 初始化LSM60DSV16X传感器的硬件SPI接口
 */
void LSM60DSV16X_HARD_SPI_Init(void)
{
    SPI_InitTypeDef SPI_InitStruct; // SPI初始化结构体

    // 配置SPI参数
    SPI_InitStruct.SPI_SSIG = ENABLE;          // 使用软件片选
    SPI_InitStruct.SPI_Enable = ENABLE;        // 使能SPI
    SPI_InitStruct.SPI_FirstBit = SPI_MSB;     // 高位先发送
    SPI_InitStruct.SPI_Mode = SPI_Mode_Master; // 主机模式
    SPI_InitStruct.SPI_CPOL = SPI_CPOL_High;   // 时钟极性高
    SPI_InitStruct.SPI_CPHA = SPI_CPHA_2Edge;  // 第二个边沿采样
    SPI_InitStruct.SPI_Speed = SPI_Speed_8;    // SPI时钟分频
    SPI_Init(&SPI_InitStruct);                 // 初始化SPI
    NVIC_SPI_Init(DISABLE, Priority_0);        // 配置SPI中断，禁用中断    ESPI = 0; // 使能SPI中断

    // 初始化P4.0引脚为推挽输出// 初始化P4.1-P4.3引脚为双向口
    GPIO_Init(GPIO_P4, GPIO_Pin_1 | GPIO_Pin_2 | GPIO_Pin_3, GPIO_Mode_Out_IN);
    GPIO_Init(GPIO_P4, GPIO_Pin_0, GPIO_Mode_Out_PP);

    // 设置SPI引脚映射到P4.0-P4.3
    // SPI_S0 = 0; SPI_S1 = 1;
    // 00: P1.4 P1.5 P1.6 P1.7,
    // 01: P2.4 P2.5 P2.6 P2.7,
    // 10: P4.0 P4.1 P4.2 P4.3,
    // 11: P3.5 P3.4 P3.3 P3.2
    SPI_SW(SPI_P40_P41_P42_P43);             // 第3组
    LSM6DSV16X_CK_STA(LOW);                  // 初始时钟设置为低电平
    SPI_ClearFlag();                         // (SPIF和WCOL)清除SPI传输完成标志,清除写冲突标志
    HSPllClkConfig(MCKSEL_HIRC, PLL_96M, 4); // 系统时钟选择,PLL时钟选择,时钟分频系数
    HSSPI_Enable();
}

#elif defined(LSM6DSV16X_HARD_IIC)
/**
 * @brief 硬件I2C初始化LSM6DSV16X传感器
 */
void LSM60DSV16X_HARD_IIC_Init(void)
{
    I2C_InitTypeDef I2C_InitStr;

    // 配置I2C主机模式 - 400KHz (Fosc=40M)
    I2C_InitStr.I2C_Speed = 10;             // 总线速度=Fosc/2/(Speed*2+4) = 40M/2/(10*2+4) = 400KHz
    I2C_InitStr.I2C_Enable = ENABLE;        // 使能I2C
    I2C_InitStr.I2C_Mode = I2C_Mode_Master; // 主模式
    I2C_InitStr.I2C_MS_WDTA = DISABLE;      // 禁止自动发送
    I2C_Init(&I2C_InitStr);
    NVIC_I2C_Init(I2C_Mode_Master, DISABLE, Priority_0); // NVIC中断优先级配置

    // I2C引脚映射: SDA=P2_4, SCL=P2_3
    I2C_SW(I2C_P24_P23);
    GPIO_Init(GPIO_P2, GPIO_Pin_3 | GPIO_Pin_4, GPIO_Mode_Out_IN); // 准双向口
    gpio_init_pin(LSM6DSV16X_AD0_PIN, GPIO_Mode_Out_PP);           // 设置为推挽输出
    gpio_write_pin(LSM6DSV16X_AD0_PIN, LOW);                       // 设置为低电平
}

#endif

/******************************************************************
 * @brief 向LSM6DSV16X传感器写入寄存器值
 * @param reg 要写入的寄存器地址
 * @param val 要写入的寄存器值
 * @note 此函数通过SPI接口与LSM6DSV16X传感器通信
 *       1. 拉低片选信号
 *       2. 发送寄存器地址(bit7=0表示写操作)
 *       3. 发送要写入的数据
 *       4. 拉高片选信号
 *****************************************************************/
void Lsm6dsv16x_WriteReg(uint8_t reg, uint8_t val)
{
    LSM6DSV16X_CS_STA(LOW); // 拉低片选信号,选中主线占用
#if defined(LSM6DSV16X_HARD_SPI)
    SPI_WriteByte(reg); // 寄存器地址（bit7=0 表示写）
    SPI_WriteByte(val); // 数据
#elif defined(LSM6DSV16X_HARD_IIC)
    I2C_WriteNbyte(LSM6DSV16X_ADDR, reg, &val, 1);
#endif
    LSM6DSV16X_CS_STA(HIGH); // 拉高片选信号,解除主线占用
}

/********************************************************************
 * @brief 从LSM6DSV16X传感器读取指定寄存器的值
 *
 * @param reg 要读取的寄存器地址
 * @return u8 读取到的寄存器值
 *
 * @note 该函数通过SPI接口与LSM6DSV16X传感器通信
 *       1. 拉低CS片选信号开始通信
 *       2. 发送寄存器地址(bit7=1表示读操作)
 *       3. 读取寄存器值(需虚写一字节时钟)
 *       4. 拉高CS片选信号结束通信
 *******************************************************************/
uint8_t Lsm6dsv16x_ReadReg(uint8_t reg)
{
    uint8_t val;
    LSM6DSV16X_CS_STA(LOW);
#if defined(LSM6DSV16X_HARD_SPI)
    SPI_WriteByte(reg | 0x80); // bit7=1 表示读
    val = SPI_ReadByte();      // 虚写一字节时钟，同时读回数据
#elif defined(LSM6DSV16X_HARD_IIC)
    I2C_ReadNbyte(LSM6DSV16X_ADDR_READ, reg, &val, 1);
#endif
    LSM6DSV16X_CS_STA(HIGH);
    return val;
}

/*************************************************************************
 * @code    void Lsm6dsv16x_ReadNByte(uint8_t reg, uint8_t *buffer, uint8_t sizel)
 * @brief   读取 LSM6DSV16X 的连续寄存器数据
 * @return  none.
 * @date    2026-06-24.
 *************************************************************************/

void Lsm6dsv16x_ReadNByte(uint8_t reg, uint8_t *buffer, uint8_t sizel)
{
    LSM6DSV16X_CS_STA(LOW);
#if defined(LSM6DSV16X_HARD_SPI)
    SPI_Read_NByte(reg, buffer, sizel);
#elif defined(LSM6DSV16X_HARD_IIC)
    I2C_ReadNbyte(LSM6DSV16X_ADDR_READ, reg, buffer, sizel);
#endif
    LSM6DSV16X_CS_STA(HIGH);
}

/*************************************************************************
 * @code    void Lsm6dsv16x_Get_RawAcc(int16 *ax, int16 *ay, int16 *az)
 * @brief   读取 LSM6DSV16X 的三轴加速度原始数据
 * @param   ax : 存放 x 轴加速度数据的指针.
 * @param   ay : 存放 y 轴加速度数据的指针.
 * @param   az : 存放 z 轴加速度数据的指针.
 * @return  none.
 * @date    2026-06-24.
 * @example Lsm6dsv16x_Get_RawAcc(&ax, &ay, &az);
 *************************************************************************/
void Lsm6dsv16x_Get_RawAcc(int16 *ax, int16 *ay, int16 *az)
{
    uint8_t buf[6] = {0};

    Lsm6dsv16x_ReadNByte(LSM6DSV16X_OUTX_L_A, buf, 6);
    *ax = (int16)((buf[1] << 8) | buf[0]);
    *ay = (int16)((buf[3] << 8) | buf[2]);
    *az = (int16)((buf[5] << 8) | buf[4]);
}

/*************************************************************************
 * @code    void Lsm6dsv16x_Get_RawGyro(int16 *gx, int16 *gy, int16 *gz)
 * @brief   读取 LSM6DSV16X 的三轴陀螺仪原始数据
 * @param   gx : 存放 x 轴陀螺仪数据的指针.
 * @param   gy : 存放 y 轴陀螺仪数据的指针.
 * @param   gz : 存放 z 轴陀螺仪数据的指针.
 * @return  none.
 * @date    2026-06-24.
 * @example Lsm6dsv16x_Get_RawGyro(&gx, &gy, &gz);
 *************************************************************************/
void Lsm6dsv16x_Get_RawGyro(int16 *gx, int16 *gy, int16 *gz)
{
    uint8_t buf[6] = {0};

    Lsm6dsv16x_ReadNByte(LSM6DSV16X_OUTX_L_G, buf, 6);
    *gx = (int16)((buf[1] << 8) | buf[0]);
    *gy = (int16)((buf[3] << 8) | buf[2]);
    *gz = (int16)((buf[5] << 8) | buf[4]);
}

/*************************************************************************
 * @code    void Lsm6dsv16x_Get_RawData(int16 *ax, int16 *ay, int16 *az, int16 *gx, int16 *gy, int16 *gz)
 * @brief   读取 LSM6DSV16X 的六轴原始数据
 * @param   ax : 存放 x 轴加速度数据的指针.
 * @param   ay : 存放 y 轴加速度数据的指针.
 * @param   az : 存放 z 轴加速度数据的指针.
 * @param   gx : 存放 x 轴陀螺仪数据的指针.
 * @param   gy : 存放 y 轴陀螺仪数据的指针.
 * @param   gz : 存放 z 轴陀螺仪数据的指针.
 * @return  none.
 * @date    2026-06-24.
 * @example Lsm6dsv16x_Get_RawData(&ax, &ay, &az, &gx, &gy, &gz);
 *************************************************************************/
void Lsm6dsv16x_Get_RawData(int16 *ax, int16 *ay, int16 *az, int16 *gx, int16 *gy, int16 *gz)
{
    uint8_t buf[12] = {0};

    Lsm6dsv16x_ReadNByte(LSM6DSV16X_OUTX_L_G, buf, 12);
    *gx = (int16)((buf[1] << 8) | buf[0]);
    *gy = (int16)((buf[3] << 8) | buf[2]);
    *gz = (int16)((buf[5] << 8) | buf[4]);
    *ax = (int16)((buf[7] << 8) | buf[6]);
    *ay = (int16)((buf[9] << 8) | buf[8]);
    *az = (int16)((buf[11] << 8) | buf[10]);
}

/********************************************************************
 * @code  void LSM6DSV16X_Init()
 * @brief LSM6DSV16X传感器初始化
 * @param none
 * @return none
 * @note  此函数初始化SPI接口的参数，包括时钟频率、数据位宽等
 *******************************************************************/
void LQ_LSM60DSV16X_Init(void)
{
    // uint8_t regVal;
#if defined(LSM6DSV16X_HARD_SPI)
    LSM60DSV16X_HARD_SPI_Init();
#elif defined(LSM6DSV16X_HARD_IIC)
    LSM60DSV16X_HARD_IIC_Init();
#endif
    Lsm6dsv16x_WriteReg(LSM6DSV16X_CTRL3_C, LSM6DSV16X_SW_RESET); // 软件复位 (CTRL3_C bit0 = SW_RESET)
    delay_ms(10);                                                // 等待复位完成
    Lsm6dsv16x_WriteReg(LSM6DSV16X_CTRL3_C, LSM6DSV16X_BOOT);    // 触发BOOT重载校准参数 (CTRL3 bit7)
    delay_ms(20);

    // 配置CTRL3 - BDU + IF_INC, 同时清除BOOT
    Lsm6dsv16x_WriteReg(LSM6DSV16X_CTRL3_C, LSM6DSV16X_BDU | LSM6DSV16X_IF_INC);

    //  配置CTRL9_XL - 使能XL LPF2滤波器,其他默认
    Lsm6dsv16x_WriteReg(LSM6DSV16X_CTRL9_XL, 0x02);

    //  配置CTRL1_XL - 加速度计 240Hz, 高性能模式
    // odr_xl[3:0]=240Hz(0x7), op_mode_xl[6:4]=HP(0x3) => 0x37
    Lsm6dsv16x_WriteReg(LSM6DSV16X_CTRL1_XL, (LSM6DSV16X_XL_MODE_HP << 4) | LSM6DSV16X_XL_ODR_240Hz);

    // 配置CTRL2_G - 陀螺仪 240Hz, 高性能模式
    // odr_g[3:0]=240Hz(0x7), op_mode_g[6:4]=HP(0x3) => 0x37
    Lsm6dsv16x_WriteReg(LSM6DSV16X_CTRL2_G, (LSM6DSV16X_XL_MODE_HP << 4) | LSM6DSV16X_XL_ODR_240Hz);

    // 配置CTRL6_C - 陀螺仪量程 ±2000dps (fs_g[3:0]=0x4)
    // 同时使能陀螺仪LPF1滤波器 (lpf1_g_en bit0=1) => 0x04 | 0x01 = 0x05
    Lsm6dsv16x_WriteReg(LSM6DSV16X_CTRL6_C, LSM6DSV16X_GYRO_FS_2000 | 0x01);

    // 配置CTRL8_XL - 加速度计量程 ±2g
    Lsm6dsv16x_WriteReg(LSM6DSV16X_CTRL8_XL, LSM6DSV16X_XL_FS_2G);

    //  回读验证关键寄存器
    // regVal = Lsm6dsv16x_ReadReg(LSM6DSV16X_CTRL1_XL); // 应读到0x37
    // printf("CTRL1_XL:0x%02X\r\n", regVal);
    // regVal = Lsm6dsv16x_ReadReg(LSM6DSV16X_CTRL2_G);  // 应读到0x37
    // printf("CTRL2_G:0x%02X\r\n", regVal);
    // regVal = Lsm6dsv16x_ReadReg(LSM6DSV16X_CTRL3_C);  // 应读到0x44
    // printf("CTRL3_C:0x%02X\r\n", regVal);
}

/**
 * @brief 测试函数 - 读取LSM6DSV16X并通过LCD和UART显示
 */
void Test_LSM6DSV16X_Hard(void)
{
    u8 ID;                          // 设备ID
    int16_t ax, ay, az, gx, gy, gz; // 六轴原始数据
    char txt[32];

    UART_Init(UART1_P30_P31, 115200ul);
    GPIO_LED_Init();
    IPS_LCD_Init();
    LCD_CLS(u16_BLACK);
    // OLED_Init(); // LCD初始化
    delay_ms(100);
    //  OLED_CLS(); // LCD清屏

    LQ_LSM60DSV16X_Init(); // 完整初始化传感器（含接口初始化+寄存器配置）
    delay_ms(10);

    // 读取设备ID
    ID = Lsm6dsv16x_ReadReg(LSM6DSV16X_WHO_AM);
    sprintf(txt, "ID:0x%x", ID);
    LCD_ShowStr_16(2, 0, "LQ-LSM6DSV16X_Test", u16_WHITE, u16_BLACK);
    LCD_ShowStr_16(16, 1, txt, u16_WHITE, u16_BLACK);
    // OLED_P6x8Str(0, 1, txt);

    while (1)
    {
        Lsm6dsv16x_Get_RawData(&ax, &ay, &az, &gx, &gy, &gz);
        sprintf(txt, "ax:%06d", ax);
        LCD_ShowStr_16(1, 3, txt, u16_WHITE, u16_BLACK); // OLED_P6x8Str(0, 2, txt);
        sprintf(txt, "ay:%06d", ay);
        LCD_ShowStr_16(1, 4, txt, u16_WHITE, u16_BLACK); // OLED_P6x8Str(0, 3, txt);
        sprintf(txt, "az:%06d", az);
        LCD_ShowStr_16(1, 5, txt, u16_WHITE, u16_BLACK); // OLED_P6x8Str(0, 4, txt);
        sprintf(txt, "gx:%06d", gx);
        LCD_ShowStr_16(15, 3, txt, u16_WHITE, u16_BLACK); // OLED_P6x8Str(0, 5, txt);
        sprintf(txt, "gy:%06d", gy);
        LCD_ShowStr_16(15, 4, txt, u16_WHITE, u16_BLACK); // OLED_P6x8Str(0, 6, txt);
        sprintf(txt, "gz:%06d", gz);
        LCD_ShowStr_16(15, 5, txt, u16_WHITE, u16_BLACK); // OLED_P6x8Str(0, 7, txt);

        /* UART1打印结果 */
        sprintf(txt, "ax = %d  ay = %d  az = %d\r\n", ax, ay, az);
        UART1_PutStr(txt);
        sprintf(txt, "gx = %d  gy = %d  gz = %d\r\n", gx, gy, gz);
        UART1_PutStr(txt);

        LED_Ctrl(LED0, RVS);
        delay_ms(50);
    }
}
