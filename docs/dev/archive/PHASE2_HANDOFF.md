> Historical Phase 2 record, preserved verbatim where possible. Superseded by [current handoff](../HANDOFF.md). Do not execute its physical-recovery instruction in Phase 3.

# HyperLab Phase 2 handoff — 2026-09-05

## 当前状态

**英文 Qt 工作台和持久采集/分析软件已实现；当前实机持续采集验收 BLOCKED，
等待相机 USB 物理重连后重新检查通信。** 最近一次打开失败于 GenCP
MaxDeviceResponseTime 寄存器读取。本轮三个持久 CameraSession benchmark 尝试
均在开始采集之前失败或中断，共获得 0 帧，无可报告的持续预览/记录性能结果。
本轮改造前 Tk 基线另有一次真实 RGB8 单帧保存/回读成功，见下方独立证据行。

此前 H1 单帧保存、回读和用户确认遮挡实验的 PASS 保留为历史实物证据。
它不保证当前 USB 会话健康，也不表示已经恢复高光谱扫描。未更换/重装驱动，
未写固件、EEPROM、UserSet、永久标定或 NXP 控制口命令。

| 项目 | 状态 | 证据与限制 |
|---|---|---|
| Phase 2 软件实现 | 离线 PASS；实机整体验收 PARTIAL | Qt/UI、持久相机 API、时序记录、分析/I/O 修复、控制器诊断；189 项离线测试通过 |
| 当前持久实机预览/记录 | BLOCKED | 3 次尝试、0 帧；重连后的短程及持续验收尚未完成 |
| H0 机身/接口身份 | PARTIAL | OEM 成像型号已识别；机身标签不可见，第二线缆关联未知 |
| H1 传感器成像 | 历史 PASS | RGB8/BayerRG12、保存回读、遮挡响应、停止释放和设置恢复 |
| H2 FP 原始扫描 | BLOCKED / NOT_TESTED | 缺匹配协议/应用、状态确认、稳定等待和帧关联 |
| H3 波长重建 | BLOCKED / NOT_TESTED | 缺本机响应/重建标定与真实波长映射 |
| H4 物理反射率验证 | BLOCKED / NOT_TESTED | 缺 H3 和匹配参考/实验条件及独立验证 |

## 直接使用

```powershell
Set-Location C:\Project\HyperSpectral
.\Start-HyperLab.cmd
```

默认是英文 PySide6/pyqtgraph 窗口，启动本身不连接相机。CMD 可双击且立即
归还终端。需要控制台输出时运行
`.\.venv\Scripts\python.exe -X utf8 -m hyperlab app`。PowerShell 脚本入口：

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\Start-HyperLab.ps1
```

Bypass 仅作用于子进程，不更改永久执行策略。路径是 `.\.venv`，不是
`..venv`；不要粘贴终端提示符。旧 Tk 仅通过 `app --legacy` 显式启动。

当前可直接使用离线 Open data、ROI/导出及合成演示。相机恢复通信后的正常
流程为 Connect camera → Start preview；曝光 ms/增益 dB 可配置且显示实际
读回。Save current frame 保存显示的同一个 Frame；Freeze display 不停止
采集；Stop acquisition 才停止；Record 有帧数/时长/磁盘预算。记录使用
`sequence.npy` + `sequence.npy.json`，THW/THWC 时间轴不冒充光谱轴。
完整可复制的诊断、单帧、分析和测试命令见 [README](../../../README.md)。

## Phase 2 已实现范围

- 默认英文 Qt 工作台：持久 row-major 图像、缩放/平移/Fit/1:1、两 ROI 及数字精调、
  DN/RGB/CFA 显示门槛、直方图/描述性聚焦值、数值图与独立显示导出、近期保存、
  模式和采集/显示/写盘/帧龄状态、两个保存文件的统计比较。固定两个 ROI 槽位；
  没有任意新增/删除或缩略图库。
- 单线程拥有的 CameraSession，持久 producer/handle、有限 fetch、latest 槽位、
  有界命令/快照/写盘队列、真实 stop/close、临时设置读回恢复及独立清理回执。
  借用 buffer 内只做校验/复制/证据提取，归还后才分析/写盘。
- 不可变 Frame、当前显示帧快照、有限时序记录、持久前缀检查点、溢出/磁盘错误/
  帧缺口的部分数据、重开内容验证和 Windows mmap 释放。真实 FP scan 未实现。
- R1–R9 对应修复：共同特征集、反射率元数据域、共享能力限制、清理故障、ENVI
  标准字段/独立 reader、定量质量政策和计数、内存预算、分块输出与数值精度。
- 参考登记/设置一致性检查、时间均值/SD/漂移统计；只做描述，不宣称材料/温度
  判断或物理反射率校准。外部有证据的谱立方体可独立分析。
- 单独的有界控制器资产/拓扑诊断，官方资料复核及物理数据模型说明。没有找到
  可执行的匹配 FP 协议资产，未打开 NXP 口。

详细契约：[ARCHITECTURE](../ARCHITECTURE.md)、[UI_SPEC](../UI_SPEC.md)、
[CAMERA_SESSION](../CAMERA_SESSION.md)、[REVIEW_FIXES](../REVIEW_FIXES.md)、
[PHYSICS_AND_DATA](../PHYSICS_AND_DATA.md)。

## 本轮基线与持久会话失败证据

| 本地路径 | 真实结果 |
|---|---|
| `local/diagnostics/phase2-baseline-pnp/snapshot.json` | 本轮基线只读清单：成像接口和 NXP VCOM 为 code 0；不证明 native open 正常 |
| `local/exports/raw_frame_20260905T155322198944/frame.npy` | 本轮改造前 Tk 基线单帧 PASS：RGB8、1216×1936×3 uint8；sidecar 确认 save_reopen_verified、stop_returned、device_released 均 true；非持续预览验收 |
| `local/diagnostics/phase2-camera-smoke/receipt.json` | FAIL：ICategory 无直接 `.name`；连接/已审查节点读取成功，stream 未开始，0 帧，正常释放成功 |
| `local/diagnostics/phase2-camera-smoke-v2/interruption.json` | INTERRUPTED：全节点值读取卡在 native 调用，stream 未开始，0 帧；只终止指定 benchmark 进程，正常释放 NOT_CONFIRMED |
| `local/diagnostics/phase2-camera-smoke-v3/receipt.json` | FAIL：AccessDenied / GenCP MaxDeviceResponseTime 读取失败；未建会话、0 帧；打开失败后不能确认相机释放 |

已修正 typed INode 名称获取，并将导出限定为缓存名称/类型加 reviewed
`FEATURES` 的值/访问/范围；未知节点标记 NOT_READ_UNREVIEWED_NODE，不读取
未知值/访问状态、不执行命令、不更改选择器。离线故障回归已加入。**修正后
真实导出 PENDING，XML 为 NOT_EXPORTED**，不能称为完整 GenICam/XML 导出。

第一次的已知节点证据包括 1936×1216、BayerRG、零 offsets；ReverseX/Y
不可读，故不假定 CFA 翻转状态。BlackLevelAuto 为 Continuous；配置值
AcquisitionFrameRate=4000 不等于实测 FPS。实际固件是 2.28.1323.0，不能把
较新在线手册的全部节点当成当前固件功能。

## 控制器调查与最小下一步

实际有界搜索报告：
`local/diagnostics/scanner-phase2/expanded-registry-scope/scanner_report.json`。
检查 261 个系统/用户相关根目录的顶层条目，以及已知 Balluff 树内 506 个
文件；3 条相关安装记录属于驱动/Impact Acquire，不是 3 套 FP 软件。
相关 XML/配置/头文件的补充内容搜索无匹配，记录于
`local/diagnostics/scanner-phase2/installed-text-search.json`。无全盘搜索，
没有发现匹配控制/重建资产；这不证明所有二进制或备份中都不存在资料。

1. **当前成像阻塞：** 用户完成相机 USB 物理重连后，重新只读 probe，再用
   新输出目录运行短程 real benchmark。只有连接/真实帧/记录回读/释放成功后
   才进入持续预览、记录、10 次开始停止及 GUI 关闭验收。不得用合成数据补足。
2. **H0：** 可读机身/接口照片，或用户确定的线缆关联与前后 PnP 对照。
3. **H2：** 授权且匹配的 TruScope/控制器软件、API/示例，或明确包括线控行为、
   状态确认和同步规则的协议。给出具体备份目录即可继续有界静态检查。
4. **H3：** 本机对应响应/重建矩阵或运行时，连同状态顺序、波长单位、几何/CFA/
   温度适用范围；缺失时需独立窄带/功率/光谱标准重新校准。

详细事实、来源适用性和未做项目见 [SCANNER_RECOVERY](../SCANNER_RECOVERY.md)
及 [SOURCES](../SOURCES.md)。无需通过重装驱动或猜串口命令绕过这些阻塞。

## 软件与桌面验证回执

| 项目 | 当前记录 |
|---|---|
| Phase 2 源代码提交 | `e80079a`；分支 `feature/live-workbench-v2`，基线 `1e27c89`；正常 push 已完成 |
| 最终离线套件 | PASS — 189 passed，9.77 s，exit 0；`local/diagnostics/phase2-final-189-tests.log` 和同名 XML |
| Qt 真实桌面验收 | 已测流程 PASS；完整验收 PARTIAL — 英语界面，当前 125% 缩放；`local/diagnostics/ui-phase2/acceptance.json` |
| 真实预览/记录 benchmark | BLOCKED — USB 重连待完成；3 次尝试、0 帧 |
| 修正后的节点导出 | PENDING；XML NOT_EXPORTED |
| 持续性能/10 cycles/录制时关闭 | NOT_TESTED — 先完成短程实机检查 |
| Phase 2 远程 CI | 最终源代码 `e80079a` [PASS](https://github.com/sgyliu8/Hyper/actions/runs/33978247352)；此前缺 Linux libEGL 的失败已保留并修复 |

Qt 前后比较基线保留在 `local/diagnostics/ui-phase2/before-tk.png`、
`before-tk-real.png` 和 `before-tk-roi-export.png`。最终英语截图同目录：
`final-english-roi.png`、`final-english-derived.png`、`after-english-save-reopen.png`、
`final-saved-comparison.png`、`final-roi-precision-applied.png`、`final-sample-registration.png`。
已实际操作回放、拖动 ROI、数字精调 `(400,389,736,693)`、ROI CSV、原始副本保存/
近期列表重开、数值差分、独立 PNG 导出、两个保存文件比较及 sample 参考登记。
数值核验见 `ui-phase2/export-verification.json`：两 ROI 均值与独立 NumPy 计算一致；
原始副本逐像素一致；按声明 HWK 轴读取的差分与原始 R−G 逐像素一致。
文件比较使用同一历史 RGB 帧的两个副本作控件检查，不作为两次独立采集。
最终版本的参考登记已核对：登记的是当前打开的副本，原始来源另存于
`declared_source_files`，未填写的实物条件保留 unknown，不称为暗场或标定。

实际产物包括 `local/experiments/roi_20260905T160211180176Z/`、
`derived_20260905T160345443764Z.npy`、`copy_20260905T160839665860Z.npy`、
`display_20260905T161654491196Z.png` 和
`saved_comparison_20260905T162522802236Z.json` 和
`reference_20260905T164245177672Z.json`，均未提交到公共仓库。
当前屏幕为 2048×1152 逻辑像素、DPR 1.25；其他分辨率/100/150/200% 组合 NOT_TESTED。

实机 benchmark 计划使用 BayerRG12、50 ms、0 dB，但三个持久会话尝试都未开始流：
实际流时长 0、有效帧 0；capture/display/writer FPS、帧龄分布、drop/overflow、
内存趋势和 Stop 延迟均为 NOT_TESTED，不填成 0 或 PASS。没有进行 10 分钟预览、
真实有限录制或 10 次 start/stop。最近磁盘检查约有 112 GiB 可用；它不是写盘性能结果。
帧龄的实现定义为 host monotonic 当前时间减接收时间，不是设备到显示的绝对延迟。

其余明确限制：ROI 是两个固定槽位；参考列表/近期列表不跨重启恢复；反射率校正
仅通过科学 API；真实 FP 扫描与重建没有可用协议/标定资产。不能据此称仪器已完整恢复。
Headless benchmark 不代表显示 FPS，GUI timer 间隔也不是相机 FPS。
[TEST_PLAN](../TEST_PLAN.md) 记录验收要求和软件/物理证据的区分。

## 历史证据附录：Phase 1 / 启动修复

以下是先前已完成的结果，不用于把本轮失败重新标成 PASS。

- 安装审批/日志：`local/diagnostics/install-20260905T132833738.log.json`，exit 0、
  无需重启，成像驱动 code 28→0。静态来源证据为
  `local/downloads/driver-review/readiness.json` 和 `local/downloads/cti-review/review.json`。
- 最初清单：`local/diagnostics/20260905T131703438/snapshot.json`；安装后清单：
  `local/diagnostics/20260905T132950698/snapshot.json`；能力读取：
  `local/diagnostics/pixel_capabilities_20260905T123613Z.json`。
- H1 原始图像：`local/acquisitions/scene-ready-rgb/frame.npy`、
  `local/acquisitions/scene-ready-bayer12/frame.npy` 和
  `local/acquisitions/occluded-bayer12/frame.npy`，各有原始 payload/sidecar/preview。
  两个 Bayer 帧为 1216×1936 uint16、BayerRG12/100000 µs/0 dB；用户确认遮挡后
  平均 DN **817.567→4.599**。比较回执 `local/diagnostics/scene-validation.json`。
  已验证正常停止/释放、回读及恢复 RGB8/20000 µs。场景帧饱和 1.686%，不是定量
  科研合格帧；原始 sidecar 的初始 NOT_TESTED 保留，未被后续比较篡改。
- 旧 Tk 正常窗口单帧：`local/exports/raw_frame_20260905T135317666950/frame.npy`，
  真实截图 `local/diagnostics/gui-real-capture.png`。旧 UI callback 检查目录：
  `ui_smoke_20260905T1326`、`ui_color_smoke_20260905`、
  `ui_session_controls_smoke_20260905`（均在 `local/diagnostics/`）。
- 旧测试 **56 PASS**，`local/diagnostics/offline-tests.txt`。源检查点 `80d572d`
  的旧 CI：[run 33967270876](https://github.com/sgyliu8/Hyper/actions/runs/33967270876)。
  该结果不覆盖 Phase 2 工作树。
- 启动修复 `1e27c89`：Restricted PowerShell 下 CMD 启动和直接 Python inventory
  成功；child Bypass 捕获参数检查在故意缺失的 CTI 处停止，没有新采集。
  回执 `local/diagnostics/startup-policy-fix.json`，永久策略未改。
- 原 code 28、PowerShell 模块路径、RGB 轴解码、只读 Harvester stream 创建及
  pythonw UTF8 失败均保留于 [HARDWARE_FINDINGS](../HARDWARE_FINDINGS.md) 和对应
  私有日志。没有删除或重新命名失败以提高通过率。

环境沿用项目 Python 3.11.9 x64 `.venv`；Phase 2 加入 PySide6 6.10.3、
pyqtgraph 0.14.0。Harvester 1.4.3/GenICam 1.6.0 与 Balluff 3.7.2 为已识别组合。
MATLAB R2025a 的历史 `imaqhwinfo` 无 adaptor；它不提供缺失的 FP 协议。

## Git 与隐私

远程为 `https://github.com/sgyliu8/Hyper.git`；本轮分支已从历史 recovery 分支
切到 `feature/live-workbench-v2`。只允许精确审查源文件、脱敏文档、测试和合成
生成器。`local/` 与 `.venv/` 被忽略；原始测量、标定、完整标识、日志、驱动、
许可和二进制不上传。最终提交/CI 单独填入，不以旧结果冒充；无自动合并、
强制推送或可见性更改。
