# U2S → WinUSB：连接、完整备份与刷写指南

当 `SPRD U2S Diag` 能被识别，却在备份或进入下载模式时出现 `Error writing to serial port`，可以尝试将**目标下载设备**绑定到 WinUSB，再使用 LibUSB 版工具通信。本仓库记录一次实测过程，并提供可审阅的脚本。

**先备份，再刷写。** 只解决连接问题或只做备份，停在备份步骤即可。切换驱动本身不会刷入系统，也不保证 ADB、Root 或其他机型可用。

> 实测范围：Windows、F50 原 B15、下载设备 `1782:4D00`、接口 0、Bulk OUT `01` / IN `81`，随后刷入配套 B09 系统并保留原 B15 基带/NV。本仓库的刷写脚本只针对这个分区布局和 A 槽；其他机型不能直接套用。发布版脚本经过离线测试，重构后的整套自动流程尚未重新做硬件回归。

- [WinUSB 下的完整备份](docs/backup.md)
- [WinUSB 恢复为 U2S](docs/restore-u2s.md)
- [B15 → B09：保留基带/NV 的刷写步骤](docs/flashing.md)
- [命令说明与禁用命令](docs/commands.md)
- [每条脚本指令、参数与写入目标的作用](docs/script-reference.md)
- [实测案例、问题和处理结果](docs/case-study.md)
- [校验与测试范围](docs/validation.md)

## 1. 判断问题发生在哪一步

典型日志：

```text
Successfully connected to port: 5
Successfully connected to port: 5
Error writing to serial port
```

这说明工具找到了串口，但串口写入没有完成；**仅凭这条日志不能确定是驱动损坏，也不能认为已经刷坏系统**。先关闭其他串口/刷机程序，使用能传数据的线直连电脑，检查设备硬件 ID 和原驱动绑定，再考虑 WinUSB 路线。实测中原 SPRD 驱动已安装正确，串口写入仍报错；换成 WinUSB 后通信成功。

| 驱动绑定 | 配套程序 | 预期表现 |
| --- | --- | --- |
| `sprdvcom` / SPRD U2S Diag | `spd_dump_SPRD_Release` | 通过 COM 串口通信 |
| `WinUSB` | `spd_dump_LibUSB_Release` | 直接 USB 通信；下载设备没有 COM 口属正常 |

USB 网络的 RNDIS、ADB、MTP、摄像头是不同设备/接口，不能一起替换驱动。

这里的 VID/PID 是公开的 USB 硬件类型编号，供核对驱动目标使用，不是本机唯一标识。本仓库不公开个人设备的序列号、IMEI、MAC、USB 实例路径、基带读数或镜像哈希；设备匹配与哈希校验只在运行脚本的电脑本地进行。

## 2. 准备工具和原驱动

从原作者/官方页面自行下载：

- [spreadtrum_flash 实测版本 stable_20250726_0012](https://github.com/TomKing062/spreadtrum_flash/releases/tag/stable_20250726_0012)：使用 `spd_dump_LibUSB_Release` 中的程序和配套 `libusb-1.0.dll`，不要混用 SPRD 版本。
- [上游中文说明](https://github.com/TomKing062/spreadtrum_flash/blob/2a202404a7512026d146b62624f089aceb408520/README_zh.md)。本文按该固定版本编写，更新后应重新检查命令行为。
- [Zadig 官方网站](https://zadig.akeo.ie/)：用于绑定 WinUSB。
- [Python](https://www.python.org/downloads/windows/)：本仓库测试使用 3.11，Python、DLL 应为相同位数，推荐 x64。
- 原厂 SPD 驱动包，保留完整 INF/CAT/SYS。实测包为 `SPD_Driver_R4.20.4201`，驱动版本显示 `4.20.42.134`；驱动版本号和压缩包名称不必一致。本仓库不提供驱动或固件镜像。

建议把本仓库解压到 `C:\F50Tools\u2s-winusb-guide`，将外部工具放在另一个目录，例如 `C:\F50Tools\spd_dump_LibUSB_Release`。刷写暂存目录必须使用纯英文路径，磁盘支持大于 4 GB 的文件，并预留完整备份与读回校验的空间。

**替换前保留原驱动**：管理员 PowerShell 运行 `scripts\Check-Drivers.ps1`，找到目标设备的实际 `oem数字.inf`，再按 [恢复教程](docs/restore-u2s.md) 导出。不同电脑的 OEM 编号不同，不能照抄他人的编号。

## 3. 将目标下载设备切换为 WinUSB

1. 先确认没有备份或刷写正在运行，关闭会占用 USB/串口的程序。
2. 启动 Zadig，选择 `Options → List All Devices`。
3. F50 拔线、关机，再接电脑数据线。插线自动开机是本机正常表现，目标端口只可能短暂出现。
4. 选择 `SPRD U2S Diag`，**同时核对 USB ID 为 `1782 4D00`**。不要只凭名称，也不要改设备名称来冒充目标。
5. 左侧应是目标原驱动 `sprdvcom`，右侧选 `WinUSB`，点击 `Replace Driver`，等安装完成。
6. 关闭成功提示后重新核对目标硬件 ID 和当前驱动。安装成功窗口本身不能证明绑定到了正确的设备：设备消失后，Zadig 下拉框可能自动跳到摄像头等其他设备。

如果目标没有出现，先检查关机插线的时机和数据线。不要对摄像头、USB 网络适配器或其他 ID 执行替换。本路线不需要短接。

## 4. 先启动等待程序，再关机插线

在仓库根目录打开 PowerShell：

```powershell
.\scripts\Start-Fdl2.ps1 -ToolDirectory C:\F50Tools\spd_dump_LibUSB_Release
```

程序显示 `READY` 后，才操作设备：**拔线 → 关机 → 插回电脑同一 USB 接口**。保持线路稳定。脚本先发起 mode 2 请求、等待重新枚举，再交给上游工具。无需开启 ADB。

实测机型通过上游的 SPRD4 AutoD 路径自动进入 FDL2。只有看到 `FDL2 >` 才能继续；如果要求手动指定 FDL、报签名错误或一直超时，停止，不要猜测其他机型的 FDL 地址。

FDL 加载到 RAM 与刷写存储分区不同。这一步只建立连接并加载下载程序，没有写入系统分区。脚本针对本案例的端点和模式编写，并非通用下载模式破解器。

## 5. WinUSB 下先完成完整备份

在 `FDL2 >` 空闲提示符处按 Ctrl+C，关闭电脑上的上游程序，**保持设备连接，不要断电或重启**。随后运行：

```powershell
python .\scripts\f50.py backup --dll C:\F50Tools\spd_dump_LibUSB_Release\libusb-1.0.dll --out C:\F50Tools\backups\B15-original
python .\scripts\f50.py verify-backup --backup C:\F50Tools\backups\B15-original
```

此脚本接管已加载的原始帧 FDL2 会话，按 GPT 的物理范围读取全部分区，再读 `splloader`，不依赖 U2S 串口。包括 userdata、cache、blackbox、两套基带/PHY、NV、persist 和启动镜像。大于 4 GB 的范围使用 64 位偏移。

每个文件完成后检查读取长度、USB 数据流 SHA-256 与磁盘文件 SHA-256；GPT 检查头部和分区项 CRC。只有全部完成，`verified-manifest.json` 才标记 `complete: true`。**创建目录、生成少量文件、出现过 connected 都不代表备份完成。**

上游 `r all` 会跳过 blackbox/cache/userdata；部分按名称的 NV 读取会改变实际读取对象/偏移。因此本仓库完整备份使用 `user_partition` 物理读取，保留原 NV 头部。详见 [备份专章](docs/backup.md)。

备份完成后另存一份到其他磁盘。备份中的 NV、用户数据可能包含设备身份、密码等，禁止上传 GitHub。本仓库不备份 RPMB、eFuse、未映射区域或完整 eMMC 物理介质。

## 6. 后续刷写或恢复驱动

只需要备份的人，到这里即可。需要 B15 → B09 且保留原基带/NV，请先阅读 [刷写专章](docs/flashing.md)，不要直接运行固件包里的整目录刷写脚本。

需要重新使用串口工具时，按 [恢复 U2S 教程](docs/restore-u2s.md) 绑定原 `sprdvcom` 驱动。恢复的是电脑上的 USB 驱动，不是设备固件；原串口错误也可能再次出现。

## 脚本一览

| 文件 | 用途 | 是否写入设备存储 |
| --- | --- | --- |
| `Check-Drivers.ps1` | 查看当前驱动 | 否 |
| `Export-U2SDriver.ps1` | 导出本机原驱动 | 否 |
| `Prepare-U2SDriver.ps1` | 安装原驱动包到电脑；仍需确认绑定 | 否 |
| `Start-Fdl2.ps1` | mode 2 握手、加载 FDL | 无分区刷写 |
| `f50.py backup / verify-backup` | 全部分区备份/离线校验 | 否 |
| `f50.py plan` | 离线生成系统白名单和校验清单 | 否 |
| `f50.py snapshot / audit` | 读取基带/NV 等保护分区并比较 | 否 |
| `run_spd_plan.py` | 默认预览；`--execute` 才刷入系统、擦 metadata/cache、设置 A 槽 | 是 |
| `f50.py erase-userdata` | 独立确认后仅擦 userdata | 是，丢失用户数据 |
| `f50.py reset` | 校验通过后重启 | 不刷镜像 |

## 致谢与许可

本仓库的自编脚本和文档采用 [MIT](LICENSE)。第三方程序、固件、驱动的权利归其作者，本仓库不打包它们。

协议及工具参考：[TomKing062/spreadtrum_flash](https://github.com/TomKing062/spreadtrum_flash)、其上游 [ilyakurdyukov/spreadtrum_flash](https://github.com/ilyakurdyukov/spreadtrum_flash)。

其他小功能请访问原作者的 [UFI-TOOLS](https://github.com/kanoqwq/UFI-TOOLS)。本仓库仅提供该链接，不包含其代码、安装脚本、APK 或模块，也不宣称本案例已经安装成功。
