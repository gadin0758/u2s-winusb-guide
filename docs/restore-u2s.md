# 将 WinUSB 恢复为 SPRD U2S Diag

恢复的是电脑驱动绑定，无需刷固件。操作前停止所有刷写、读取和下载模式工具；**任何分区写入尚未结束时不要拔线或切换驱动**。

## 一、在替换前保存原驱动

管理员 PowerShell：

**本步使用的脚本：** [Check-Drivers.ps1](../scripts/Check-Drivers.ps1) — 查看当前设备和驱动。

```powershell
.\scripts\Check-Drivers.ps1
pnputil.exe /enum-drivers
```

在设备管理器目标设备的“详细信息”中核对硬件 ID `USB\VID_1782&PID_4D00`、驱动 INF 名称、服务名。原 U2S 服务应是 `sprdvcom`，不是 WinUSB。

找到对应的实际 `oem数字.inf`，例如你电脑上若是 `oem123.inf`：

**本步使用的脚本：** [Export-U2SDriver.ps1](../scripts/Export-U2SDriver.ps1) — 保存原驱动包。

```powershell
.\scripts\Export-U2SDriver.ps1 -PublishedName oem123.inf -OutDirectory C:\F50Tools\original-driver
```

**这里的 oem123.inf 只是示例，必须替换为本机查询结果。** 导出目录包含原 INF/CAT/SYS，整份保留。如果已经替换过，使用之前保存的驱动或原厂 SPD 驱动包；不要下载来源不明的改签驱动。

## 二、安装原驱动包

可以运行原驱动包中的 `Win10\DPInst64.exe`，或管理员 PowerShell 安装正确架构的原 `sprdvcom.inf`：

**本步使用的脚本：** [Prepare-U2SDriver.ps1](../scripts/Prepare-U2SDriver.ps1) — 把原驱动安装回电脑。

```powershell
.\scripts\Prepare-U2SDriver.ps1 -DriverInf C:\F50Tools\original-driver\实际子目录\sprdvcom.inf
```

脚本会检查 INF 名称和目标 PID，再执行 `pnputil /add-driver ... /install`。这会把驱动放回 Windows 驱动库，但 **“安装成功”不等于目标设备已经改绑**。Windows 可能继续选择排名更高的 WinUSB INF。

## 三、为这一个设备手动指定 U2S

1. 打开设备管理器。没有刷写正在进行时，拔线、关机、再接同一电脑接口，使下载设备出现。可启用“查看 → 显示隐藏的设备”，但要确认操作的是本台 F50 的目标实例。
2. 找到下载设备，打开“属性 → 详细信息 → 硬件 ID”，确认 `VID_1782&PID_4D00`。不要选 RNDIS 网卡、MTP、ADB、摄像头或其他 SPRD 设备。
3. 右键“更新驱动程序 → 浏览我的电脑以查找驱动程序 → 让我从计算机上的可用驱动程序列表中选取 → 从磁盘安装”。
4. 指向完整原驱动包中的 **sprdvcom.inf**，选择匹配硬件 ID 的 **SPRD U2S Diag**。确认原包签名和架构正确，不关闭驱动签名验证来强装不匹配驱动。
5. 完成后再做一次关机插线，检查绑定保持正确。若“回退驱动程序”可用且明确回退到原 U2S，也可使用它，但仍要验证结果。

“从磁盘安装”能够明确选取本设备的原驱动；单纯重跑安装器往往不能改变已绑定 WinUSB 的设备。

## 四、确认恢复成功

| 检查位置 | 应有结果 |
| --- | --- |
| 设备管理器的下载设备 | SPRD U2S Diag（COM 编号以本机为准） |
| 硬件 ID | 仍为 `1782:4D00` |
| 驱动服务 | `sprdvcom` |
| INF | 本机实际的原 SPRD OEM INF，不再是目标 WinUSB INF |
| 再次关机接线 | 仍绑定原 U2S |

需要命令查询时，可把设备管理器中复制的**完整设备实例路径**填入：

**本步使用的工具：** Windows 自带的 `pnputil.exe`，这里没有调用本仓库脚本。

```powershell
pnputil.exe /enum-devices /instanceid "此处替换为本机完整设备实例路径" /drivers
```

部分 Windows 版本的 pnputil 不支持所有查询选项，改用设备管理器查看即可。

之后使用 `spd_dump_SPRD_Release` 或原串口刷机工具；不要要求已经回到 U2S 的设备继续由本仓库 LibUSB 脚本打开。

## 常见误区

- Zadig 右侧显示 WinUSB 只是“将要安装的驱动”，检查左侧当前驱动和设备属性。
- 不需要删除所有 WinUSB 驱动包。其他设备可能也依赖这些包；本教程只改目标绑定。
- 不需要修改注册表或禁用系统防护。
- USB 网络正常与下载端口的驱动正常是两个检查目标。
- 恢复 U2S 后原串口写入错误可能重新出现。恢复驱动成功不代表最初的 U2S 通信问题已经修复；需要备份/刷写时仍可再次按主教程使用 WinUSB。
