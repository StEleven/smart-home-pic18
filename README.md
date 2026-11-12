# 智慧小屋 · Smart Home PIC18

基于 PIC18F57Q43 Curiosity Nano 和 Curiosity Nano Explorer 的课程原型。板端采集温湿度、照度、雨滴、水浸等输入，并执行场景联动。桌面上位机通过 SH1 串口协议控制和查看状态，也能在不连接板卡时独立运行 3D 模拟。

- [SmartHomeHost](SmartHomeHost)：Python / Qt WebEngine 上位机、React / Three.js 场景、离线模拟、[SH1 串口协议](SmartHomeHost/PROTOCOL.md)及测试。
- [SmartHomeStuFull](SmartHomeStuFull)：项目原创固件扩展、与课程起始工程的集成改动、XC8 构建入口及原生 C 测试。

## 运行 3D 离线演示

在 Windows 上安装 64 位 Python 和 Node.js（验证版本：Python 3.14.3、Node.js 24.14.1）。建议将仓库放在较短的目录，例如 `C:\src\smart-home-pic18`，便于在未开启长路径的系统上安装 PySide6。首次在 PowerShell 中运行：

```powershell
cd SmartHomeHost
./setup.ps1
./.venv/Scripts/python.exe run.py --demo
```

桌面端支持旋转、缩放、显示或隐藏屋顶与外墙，并可切换场景、控制模型设备、在离线模式下注入模拟输入。连接真实板卡时运行 `run.py`，在界面中选择对应 COM 口。门、窗、风口和窗帘用舵机模拟，3D 动作表示控制输出；门窗位置没有独立的物理反馈。

## 构建板端固件

按[固件说明](SmartHomeStuFull/README.md)准备本地课程起始工程 `SmartHomeFrame.zip` 和 Microchip XC8。此仓库包含项目扩展和集成改动；课程框架、厂商生成文件、原始录音及编译产物不在发布范围内。公开固件构建使用合成提示音，上位机离线演示不依赖课程包。

## 许可

项目原创代码、集成改动和文档按 [MIT](LICENSE) 发布。模型、纹理及场景实现的第三方来源见 [第三方声明](SmartHomeHost/third_party/README.md)。本地课程工程和 Microchip 工具链适用其自身条款。
