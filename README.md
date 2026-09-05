# HyperLab — HinaLea imaging and analysis workbench

Phase 2 已实现英文 Qt 工作台、持久相机会话、当前帧保存、有限时序记录、
ROI/数值分析和可追溯的数据导出。**当前实机验收 BLOCKED：相机需要 USB
物理重连后重新检查通信。** 最近一次连接无法读取 GenCP 寄存器；本轮三个
持久 CameraSession benchmark 尝试均未产生帧，不能报告持续预览或采集性能通过。
本轮改造前的 Tk 基线另成功保存并回读了一个真实 RGB8 单帧，见 HANDOFF；
这项单帧结果与之后的持久会话失败分别记录。

此前真实 RGB8/BayerRG12 保存、回读及用户确认的遮挡实验通过了 **H1 传感器
成像验收**，这些历史原始证据保留不变。H0 机身型号/接口关联仍 PARTIAL；
H2 FP 扫描、H3 波长重建、H4 物理反射率验证仍 BLOCKED。RGB/Bayer 图像不是
高光谱数据立方体；NXP VCOM 控制口未打开。

当前状态、失败路径与后续验收见 [HANDOFF](HANDOFF.md)。实现细节见
[UI specification](docs/UI_SPEC.md)、[camera session](docs/CAMERA_SESSION.md)、
[architecture](docs/ARCHITECTURE.md)、[review fixes](docs/REVIEW_FIXES.md) 和
[test plan](docs/TEST_PLAN.md)。

## 启动

在 PowerShell 中粘贴命令，不要包含 `PS C:\...>` 或 `>>` 提示符：

```powershell
Set-Location C:\Project\HyperSpectral
.\Start-HyperLab.cmd
```

也可以双击 `Start-HyperLab.cmd`。它启动英文 Qt 工作台并立即归还终端。
程序启动不会自动打开相机。需要保留控制台错误输出时：

```powershell
.\.venv\Scripts\python.exe -X utf8 -m hyperlab app
```

PowerShell 脚本被 Restricted 策略拦截时，使用单个子进程的 Bypass：

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\Start-HyperLab.ps1
```

这些入口不修改用户或计算机的永久执行策略。Python 路径是
`.\.venv\Scripts\python.exe`，不是 `..venv\Scripts\python.exe`。
旧 Tk 界面仅保留为显式入口 `python -m hyperlab app --legacy`。

## 相机工作流与当前限制

USB 重连并通过短程通信检查后，在 Qt 窗口使用 **Connect camera → Start
preview**。曝光输入单位为 ms，增益为 dB；格式、范围和实际读回值由相机
验证，设置在下次开始采集时应用。GUI 的曝光/增益控制已经实现。

- **Save current frame** 保存正在显示的原始 Frame，不重新拍摄替代帧。
- **Freeze display** 只冻结显示，采集仍可继续；**Stop acquisition** 才请求
  停止采集并恢复临时设置。
- **Record** 根据帧数/时长和磁盘预算记录 `raw_sequence`；**Stop recording**
  可保留预览。溢出、帧缺口和写入错误保留部分数据及原因。
- 时间序列保存为 `sequence.npy` + `sequence.npy.json`，轴为 THW/THWC。
  从 Recent saves 或 Open data 重新打开；时间不会变成光谱波长。
- 模式明确显示 LIVE/FROZEN/STALE/REPLAY/SYNTHETIC，采集、显示、写盘速率及
  帧龄分别记录。尚无通过的本轮实机速率/稳定性结果。

安装的成像运行时是 Balluff Impact Acquire 3.7.2，已审批安装的驱动不需要
重复安装。生产者路径为
`C:\Program Files\Balluff\ImpactAcquire\bin\x64\mvGenTLProducer.cti`。
如需显式单帧检查，重连后可运行：

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\Capture-CandidateFrame.ps1 -CtiPath 'C:\Program Files\Balluff\ImpactAcquire\bin\x64\mvGenTLProducer.cti' -PixelFormat BayerRG12 -ExposureUs 50000 -Gain 0
```

该操作检查唯一目标和当前驱动状态、验证参数、保存原始数据/元数据并尝试
恢复设置；它是硬件操作，不是清单查询。不会写 UserSet、固件或 FP 命令。
实机性能检查使用显式 `python -m hyperlab.benchmark --hardware`，完整命令及
失败分母见 [test plan](docs/TEST_PLAN.md)，不能用合成帧替代 LIVE 验收。

## 只读诊断与离线使用

```powershell
.\.venv\Scripts\python.exe -X utf8 -m hyperlab doctor
.\.venv\Scripts\python.exe -X utf8 -m hyperlab probe --inventory
.\.venv\Scripts\python.exe -X utf8 -m hyperlab probe --standard-interfaces
.\.venv\Scripts\python.exe -X utf8 -m hyperlab.controller.diagnostics --output local\diagnostics\scanner-new-check
```

Inventory 不加载 CTI、不打开串口、不采集。控制器诊断单独执行有界的安装
目录/文件名/静态内容搜索；输出目录应使用新名称。`--snapshot PATH` 可复用
已有清单，`--asset-root PATH` 可指定授权的厂商备份目录。它不猜协议或执行
候选 DLL。扫描阻塞及最小缺失资料见 [scanner recovery](docs/SCANNER_RECOVERY.md)。

下面明确生成 SYNTHETIC 数据后执行离线操作：

```powershell
.\.venv\Scripts\python.exe -X utf8 -m hyperlab demo --no-gui --output local\synthetic\readme-demo\demo.npy
.\.venv\Scripts\python.exe -X utf8 -m hyperlab app local\synthetic\readme-demo\demo.npy
.\.venv\Scripts\python.exe -X utf8 -m hyperlab inspect local\synthetic\readme-demo\demo.npy
.\.venv\Scripts\python.exe -X utf8 -m hyperlab analyze local\synthetic\readme-demo\demo.npy capabilities
.\.venv\Scripts\python.exe -X utf8 -m hyperlab analyze local\synthetic\readme-demo\demo.npy roi --roi 0 0 32 32 --output local\exports\readme-roi.csv
.\.venv\Scripts\python.exe -X utf8 -m hyperlab analyze local\synthetic\readme-demo\demo.npy pca --output local\exports\readme-pca.npy
```

NPY/ENVI 支持内存映射，ENVI 支持 BSQ/BIL/BIP、标准 BBL/ignore/单位字段。
未标注的数组通过 CLI 的 `--axis-order KHW` 等参数显式指定轴；NPZ 需物化
所选数据。大文件优先 NPY/ENVI。时间序列使用专门 reader/Qt 回放，不能作为
Cube 输入到光谱分析命令。

GUI 支持两个可移动/缩放/命名的矩形 ROI、CSV、PCA、SAM、差值、比值以及
独立的数值 NPY/ENVI 和显示 PNG 导出。RGB 可做通道描述统计；单平面 Bayer
可做 DN/CFA 诊断，均不会启用伪光谱分析。具有有效轴和来源的外部光谱立方体
可以离线分析，不依赖本机 H3 恢复。诊断/定量质量策略、特征筛选、有效计数、
掩码和来源随结果保存。反射率计算需匹配参考与设置，不能恢复缺失的 FP 标定。
参见 [physical/data contract](docs/PHYSICS_AND_DATA.md) 和 [sources](docs/SOURCES.md)。

## 环境与验证

项目使用 Python 3.11 `.venv`，PySide6 6.10.3、pyqtgraph 0.14.0、Harvester
1.4.3。Python 包存在不代表驱动或设备已就绪。新环境安装方式：

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e '.[test,camera]'
```

离线测试不会打开相机：

```powershell
$env:QT_QPA_PLATFORM = 'offscreen'
.\.venv\Scripts\python.exe -X utf8 -m pytest -q
Remove-Item Env:QT_QPA_PLATFORM
```

最后一行恢复后续正常窗口显示。最终 Phase 2 测试数量、真实 GUI 截图、源代码
提交和远程 CI 状态由 [HANDOFF](HANDOFF.md) 的最终回执记录；此前的 56 项
测试/旧界面 CI 结果不代表当前代码验收。

## 本地数据与边界

`local/`、`.venv/`、原始图像、序列、标定、完整设备标识、日志、驱动包和许可
文本保持本地且被 Git 忽略。只发布审查后的源代码、脱敏文档、测试和合成数据
生成器。没有训练模型、下载大数据集、云端采集、猜测 NXP 串口、固件刷新或
永久校准更改。软件功能完成与 H0–H4 物理恢复状态分别报告。
