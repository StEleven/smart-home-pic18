# PIC18F57Q43 固件扩展

本目录包含温湿度与干湿输入、场景和联动策略、SH1 UART 通信及其集成改动。`config.mcc/` 仅存放独立的项目模块；`integration.json` 存放对指定课程框架的逐行编辑内容和校验值。

基础实验的 58 个实际补写点按 `LAB_STAGE=1…9` 整理在 [BasicLabs](../BasicLabs/README.md)，可直接定位集成代码，或按阶段提取、核对和本地构建；它们依赖课程起始框架，不是完整独立工程。

## 构建

准备课程提供的 `SmartHomeFrame.zip`、Python 3.10 或更新版本、XC8 3.10，以及 Microchip PIC18F-Q_DFP 1.30.487。课程框架压缩包 SHA-256 为 `d75db15412e094c86d09c50b8b1280c3ad9faf8e26df6f895db25f86e01ef3fc`；脚本不会修改原压缩包。将 `xc8-cc` 加入 PATH，或使用 `--xc8` 提供编译器路径。

```powershell
cd SmartHomeStuFull
python build_firmware.py --base-archive 'C:\path\to\SmartHomeFrame.zip'
```

默认从用户目录的 `.mchp_packs/Microchip/PIC18F-Q_DFP/1.30.487/xc8` 查找器件包；其他位置用 `--dfp` 指向该版本的 `xc8` 子目录。脚本在忽略的 `_work` 目录中组装源码并生成 `_work/out/default.hex` 和 `default.elf`。两段音频由脚本以 8 kHz 合成，保留原有 PCM 播放接口。课程框架与 Microchip 生成驱动从本地包读取。

## 接口

| 外设 | 默认配置 |
| --- | --- |
| SHT30 | 实购模块标称2.4～5 V、湿度0～100%RH（±3%RH）；I²C1，0x44，RB1=SCL / RB2=SDA；用于湿度，温度由 MCP9808 测量 |
| 照度 | 板载 VCNL4200 |
| 雨滴 DO / 水浸 DO | 两套3～5 V电阻式探板与比较板，提供AO/DO；读取RA1 / RA2的DO，干高、湿低，独立采样 |
| 门 / 窗 / 风口 / 窗帘 | RA0 / RF4 / RD3 / RA3，舵机模拟 |
| UART1 | RF0=TX / RF1=RX，115200/8N1，通过虚拟串口连接上位机 |

硬件配置集中在 `config.mcc/extension_config.h`。门窗软件状态由输出命令和角度进度推导，无门磁输入。照明、空调和家电由板载灯光与显示模拟。板端接线、舵机角度和传感器读数应在实物上验收。

独立RGB温度灯升温至30.0°C变黄，至31.5°C变为红色2秒呼吸；降温至31.0°C退黄、至29.5°C退绿，回差0.5°C。旋钮设温与自动制冷独立运行。11月6日拍摄曾临时使用24.0/24.8°C及0.2°C回差，11月12日恢复正常使用参数后已重新构建，尚未烧录到板卡。

## 软件检查

先按照[上位机说明](../SmartHomeHost/README.md)安装 Python 依赖，准备 VS C++ Build Tools 和含 `clang.exe`、`lld.exe` 的 LLVM，再运行：

```powershell
./test.ps1 -BaseArchive 'C:\path\to\SmartHomeFrame.zip' -ClangDirectory 'C:\Program Files\LLVM\bin'
```

测试覆盖场景策略、输入处理、SH1 协议及四路舵机调度；使用本机 C 编译器和硬件替身，无需连接板卡。
