# 基础实验补写代码

这里按 `LAB_STAGE=1…9` 索引本项目实际补写的基础代码。58 个填空点均已包含在 [integration.json](../SmartHomeStuFull/integration.json) 中；各阶段计数为 3、3、9、7、8、6、12、5、5。下列“查看补写”直接定位唯一代码源，避免在多个目录维护相同 C 代码。

这些是课程框架上的新增或替换语句，依赖框架提供的函数、状态机、驱动和类型。它们不是九个独立工程；课程框架、教师课件和 Microchip 生成文件不在本目录分发。基础代码与整机拓展保存在同一集成数据中，部分原填空点还包含后续拓展适配。

## 查看与提取

在仓库根目录运行，输出仅从公开集成数据读取，无需课程包：

```powershell
python BasicLabs/labs.py show --stage 2
python BasicLabs/labs.py show --block S03-07
```

不加筛选参数会依次输出全部 58 个补写点。输出为带来源和编号的 Markdown 代码片段，不包含完整函数或外侧框架。

## 本地阶段构建

准备 [固件说明](../SmartHomeStuFull/README.md) 中指定的课程起始压缩包、XC8 与器件包，然后运行：

```powershell
python BasicLabs/labs.py build --stage 1 --base-archive 'C:\path\to\SmartHomeFrame.zip'
```

可选择 1～9 阶段。脚本在忽略的 `BasicLabs/_work/stage-XX/` 内组装完整依赖，设置 `LAB_STAGE` 为指定阶段、`SMART_HOME_EXTENSIONS_ENABLE=0`，并生成 `out/default.hex` 与 `default.elf`。它保留后续阶段的补写，仅按现有条件编译选择调度路径；不会将项目回滚为早期历史快照。仅组装源码可加 `--prepare-only`。编译器和器件包位置可用 `--xc8`、`--dfp` 指定。

整机仍使用 `SmartHomeStuFull/build_firmware.py` 的默认拓展流程。基础阶段构建沿用当前机构驱动、定制参数及合成 PCM 提示音，不能将编译成功写作实物验收。

## 覆盖核对

```powershell
python BasicLabs/labs.py verify --base-archive 'C:\path\to\SmartHomeFrame.zip'
```

检查课程包与集成数据校验值、58 个填空点和编辑位置，以及全部 27 个集成文件的输出校验值。可另加 `--source-root 'C:\path\to\SmartHomeStuFull\config.mcc'`，逐字节核对本地实际整机源码（仅统一换行）。`index.json` 只保存编号、文件名及编辑索引，没有复制课程代码；集成数据变化后会拒绝沿用旧索引。

## 阶段索引

### 1 · 按键与 LED

| 编号 | 本项目补写 | 代码源 |
| --- | --- | --- |
| S01-01 | 摇杆上方向点亮 LED | [查看补写](../SmartHomeStuFull/integration.json#L198) |
| S01-02 | 摇杆下方向熄灭 LED | [查看补写](../SmartHomeStuFull/integration.json#L203) |
| S01-03 | 摇杆按下翻转 LED | [查看补写](../SmartHomeStuFull/integration.json#L208) |

### 2 · 异步温度采样

| 编号 | 本项目补写 | 代码源 |
| --- | --- | --- |
| S02-01 | 启动一次异步温度读取 | [查看补写](../SmartHomeStuFull/integration.json#L816) |
| S02-02 | 查询当前读取事务 | [查看补写](../SmartHomeStuFull/integration.json#L821) |
| S02-03 | 提交新温度与有效标志 | [查看补写](../SmartHomeStuFull/integration.json#L826) |

### 3 · 页面路由与显示

| 编号 | 本项目补写 | 代码源 |
| --- | --- | --- |
| S03-01 | 退出旧页面 | [查看补写](../SmartHomeStuFull/integration.json#L163) |
| S03-02 | 更新当前页与切换计数 | [查看补写](../SmartHomeStuFull/integration.json#L168) |
| S03-03 | 进入新页面 | [查看补写](../SmartHomeStuFull/integration.json#L178) |
| S03-04 | 保存返回页并打开菜单 | [查看补写](../SmartHomeStuFull/integration.json#L183) |
| S03-05 | 执行 GOTO | [查看补写](../SmartHomeStuFull/integration.json#L188) |
| S03-06 | 执行 BACK | [查看补写](../SmartHomeStuFull/integration.json#L193) |
| S03-07 | 处理菜单入口 | [查看补写](../SmartHomeStuFull/integration.json#L223) |
| S03-08 | 运行页面任务并执行返回动作 | [查看补写](../SmartHomeStuFull/integration.json#L258) |
| S03-09 | 构建并提交显示内容 | [查看补写](../SmartHomeStuFull/integration.json#L273) |

### 4 · 欢迎页与 PCM 播放

| 编号 | 本项目补写 | 代码源 |
| --- | --- | --- |
| S04-01 | 设置欢迎页截止时间 | [查看补写](../SmartHomeStuFull/integration.json#L400) |
| S04-02 | 启动单次欢迎音 | [查看补写](../SmartHomeStuFull/integration.json#L405) |
| S04-03 | 退出时停止播放并清除标志 | [查看补写](../SmartHomeStuFull/integration.json#L410) |
| S04-04 | 播放结束后切页 | [查看补写](../SmartHomeStuFull/integration.json#L415) |
| S04-05 | 超时后切页 | [查看补写](../SmartHomeStuFull/integration.json#L420) |
| S04-06 | 按键提前跳过 | [查看补写](../SmartHomeStuFull/integration.json#L425) |
| S04-07 | 生成欢迎页显示 | [查看补写](../SmartHomeStuFull/integration.json#L430) |

### 5 · 电位器与环境页

| 编号 | 本项目补写 | 代码源 |
| --- | --- | --- |
| S05-01 | 平滑 ADC 采样 | [查看补写](../SmartHomeStuFull/integration.json#L676) |
| S05-02 | 换算百分比并四舍五入 | [查看补写](../SmartHomeStuFull/integration.json#L681) |
| S05-03 | 启动 ADC 转换 | [查看补写](../SmartHomeStuFull/integration.json#L686) |
| S05-04 | 查询 ADC 转换 | [查看补写](../SmartHomeStuFull/integration.json#L691) |
| S05-05 | 更新原始值与滤波值 | [查看补写](../SmartHomeStuFull/integration.json#L696) |
| S05-06 | 切换至 PM2.5 演示 | [查看补写](../SmartHomeStuFull/integration.json#L16) |
| S05-07 | 切回湿度页 | [查看补写](../SmartHomeStuFull/integration.json#L21) |
| S05-08 | 读取百分比并生成环境页 | [查看补写](../SmartHomeStuFull/integration.json#L26) |

### 6 · 音乐控制

| 编号 | 本项目补写 | 代码源 |
| --- | --- | --- |
| S06-01 | 提交选中的曲目 | [查看补写](../SmartHomeStuFull/integration.json#L86) |
| S06-02 | 停止当前播放 | [查看补写](../SmartHomeStuFull/integration.json#L91) |
| S06-03 | 启动选中曲目 | [查看补写](../SmartHomeStuFull/integration.json#L96) |
| S06-04 | 提交增加后的音量 | [查看补写](../SmartHomeStuFull/integration.json#L101) |
| S06-05 | 提交减小后的音量 | [查看补写](../SmartHomeStuFull/integration.json#L106) |
| S06-06 | 生成播放状态显示 | [查看补写](../SmartHomeStuFull/integration.json#L111) |

### 7 · 接近检测与人员会话

| 编号 | 本项目补写 | 代码源 |
| --- | --- | --- |
| S07-01 | 平滑接近值 | [查看补写](../SmartHomeStuFull/integration.json#L707) |
| S07-02 | 记录进入状态与事件 | [查看补写](../SmartHomeStuFull/integration.json#L712) |
| S07-03 | 记录离开状态与事件 | [查看补写](../SmartHomeStuFull/integration.json#L717) |
| S07-04 | 启动接近值读取 | [查看补写](../SmartHomeStuFull/integration.json#L722) |
| S07-05 | 查询接近值事务 | [查看补写](../SmartHomeStuFull/integration.json#L727) |
| S07-06 | 更新接近缓存 | [查看补写](../SmartHomeStuFull/integration.json#L732) |
| S07-07 | 开启人员会话与显示许可 | [查看补写](../SmartHomeStuFull/integration.json#L228) |
| S07-08 | 唤醒显示并启动彩灯 | [查看补写](../SmartHomeStuFull/integration.json#L233) |
| S07-09 | 离开时关闭机构与 RGB | [查看补写](../SmartHomeStuFull/integration.json#L238) |
| S07-10 | 休眠显示并关闭灯光 | [查看补写](../SmartHomeStuFull/integration.json#L243) |
| S07-11 | 启动新人员会话 | [查看补写](../SmartHomeStuFull/integration.json#L248) |
| S07-12 | 结束人员会话 | [查看补写](../SmartHomeStuFull/integration.json#L253) |

### 8 · 温控状态与迟滞

| 编号 | 本项目补写 | 代码源 |
| --- | --- | --- |
| S08-01 | 应用 Cold 输出 | [查看补写](../SmartHomeStuFull/integration.json#L278) |
| S08-02 | 应用 Hot 输出 | [查看补写](../SmartHomeStuFull/integration.json#L283) |
| S08-03 | 应用 Comfort 输出 | [查看补写](../SmartHomeStuFull/integration.json#L288) |
| S08-04 | 判断退出 Hot 后的状态 | [查看补写](../SmartHomeStuFull/integration.json#L303) |
| S08-05 | 判断 Cold/Comfort 的后续状态 | [查看补写](../SmartHomeStuFull/integration.json#L313) |

### 9 · 完整基础调度

| 编号 | 本项目补写 | 代码源 |
| --- | --- | --- |
| S09-01 | 处理人员进入与离开 | [查看补写](../SmartHomeStuFull/integration.json#L333) |
| S09-02 | 解释当前按键事件 | [查看补写](../SmartHomeStuFull/integration.json#L338) |
| S09-03 | 处理温控状态 | [查看补写](../SmartHomeStuFull/integration.json#L343) |
| S09-04 | 推进当前页面任务 | [查看补写](../SmartHomeStuFull/integration.json#L353) |
| S09-05 | 刷新显示并设置下次刷新时间 | [查看补写](../SmartHomeStuFull/integration.json#L363) |

## 当前源码的差异

- 阶段 2 的三个温度补写点位于原 `END` 注释之后，仍在对应状态分支内。核对脚本显式检查这一位置，不会把空的标记区域当作缺失实现。
- S03-07 的原标记已被菜单处理语句替换。当前普通页菜单键为 SW3，欢迎页仍支持 PUSH / SW1 跳过；不能照旧填空说明推断现有按键。 [对应改动](../SmartHomeStuFull/integration.json#L218)
- S03-09 包含基础显示提交和后续整机显示适配；S05-08 同时包含基础电位器模拟页与 SHT30 真实湿度分支，按拓展开关选择。
- 接近检测当前默认进入/离开阈值为 5000 / 4800。 [对应改动](../SmartHomeStuFull/integration.json#L748)
- 人员进入时彩灯设置为 80%，轮色呼吸周期为 3000 ms；当前调色表包含十种颜色。 [对应改动](../SmartHomeStuFull/integration.json#L842)
- 基础温控当前 Cold 阈值为 30.0°C，Hot 进入/退出为 31.5°C / 30.5°C；Cold / Comfort / Hot 的 RGB 实际分别为绿 / 红 / 蓝。这些是当前源码的定制值。 [对应改动](../SmartHomeStuFull/integration.json#L138)
