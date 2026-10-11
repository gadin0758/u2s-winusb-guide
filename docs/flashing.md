# 保留原基带/NV 的 B15 → B09 示例

**会更改系统，并清除 userdata、metadata、cache，原数据无法保留。** 本页只适用于案例 F50、原 B15、配套 B09 整套镜像和 A 槽。单独看到压缩包名包含 B09，不能据此确认固件匹配。驱动教程可以参考，其他机型的刷写清单不能照搬。

先完成 [完整备份](backup.md)，保留原始镜像。刷写期间不拔线、不切驱动、不手动重启；任何校验失败都先停下检查。本仓库不会下载或分发固件。

## 一、检查包和基带搭配

实测包名为 `[一键刷机无需小助手]F50_B09系统一键刷机_自带原版B15基带_一键ROOT`，结构包含 `data` 镜像目录及 `bin/f50b09_t.bin`。

本脚本要求包中的 `nr_modem_a.bin`、`nr_phy_a.bin` 与**这台设备原 B15 备份**完全同哈希。如果不一致，停止，不能强行绕过。匹配只能证明这两份镜像相同，不能证明所有 B15 基带组合都兼容 B09。

系统按包里的配套 boot/vendor_boot、验证链和整份 super 写入，不单独拼装 system。作者批处理会在批量写入后覆盖 trustos；所以若 `bin/f50b09_t.bin` 存在，计划采用该最终镜像。没有明确作者说明的 NV/persist/基带“优化”不自行加入。[案例说明](case-study.md) 记录了核对结果和无法确认的部分。

## 二、离线生成计划

下列路径都是示例，在仓库根目录执行。`plan` 不接触设备：

```powershell
python .\scripts\f50.py plan --backup C:\F50Tools\backups\B15-original --package C:\F50Tools\B09-package --out C:\F50Tools\runs\B09-first
python .\scripts\run_spd_plan.py --plan C:\F50Tools\runs\B09-first --tool C:\F50Tools\spd_dump_LibUSB_Release\spd_dump.exe
```

第二条默认仅预览。审阅 `plan.json`、`reviewed-commands.txt`、镜像来源及大小。完整备份校验可能需要时间，不能删去这个检查。

系统白名单固定为 14 个目标：

```text
trustos_a  sml_a  teecfg_a  boot_a  vendor_boot_a  dtbo_a  common_rs1_a
vbmeta_a  vbmeta_system_a  vbmeta_vendor_a  vbmeta_system_ext_a
vbmeta_product_a  vbmeta_odm_a  super
```

不刷 nr_ / l_ 基带和 NV，不刷 prodnv、calinv、miscdata、persist、ztecfg、ztepersist、SPL/UBoot/pm_sys。super 包含逻辑分区，读取其元数据和校验不能代替解包审计全部系统文件。脚本也不能仅凭 super 结构证明版本一定为 B09，需要用户确认包来源。

## 三、保留刷前基带/NV 快照

保持已加载的 FDL2；若已重启，先重新按主教程进入 FDL2，再在空闲提示符 Ctrl+C 关闭上游进程。

```powershell
python .\scripts\f50.py snapshot --dll C:\F50Tools\spd_dump_LibUSB_Release\libusb-1.0.dll --plan C:\F50Tools\runs\B09-first
```

快照保存在 `pre-protected`，禁止覆盖。NV 等运行中可能变化，所以刷后与**此次刷前快照**比较；基带/PHY 和启动加载器还要求与原备份一致。脚本检查连接 GPT，并保存所有保护分区的实际读取哈希。

## 四、执行系统白名单并读回

保持设备和 FDL2 会话。不要提前再运行 `Start-Fdl2.ps1 -Reconnect`，以下脚本会消耗一次上游 FDL2 重连：

```powershell
python .\scripts\run_spd_plan.py --plan C:\F50Tools\runs\B09-first --tool C:\F50Tools\spd_dump_LibUSB_Release\spd_dump.exe --execute
```

脚本逐项检查写入完成消息和实际字节数，擦除 metadata/cache、设置 A 槽，然后完整读回 14 个目标，检查源镜像覆盖的前缀 SHA-256。尾部没有被源镜像覆盖的空间单独记录整分区哈希，不声称尾部等于源文件。

写入前还读回所有保护分区，与刷前快照逐一比较：**相同 GPT 并不能证明是同一台设备**。任何差异都停止，不刷入新镜像。

成功后生成 `system-verification.json`，不自动清 userdata 或重启。中途失败可能留下不完整系统，不能直接重启或盲目重复整个计划。重复运行会被拒绝，应先根据本地日志检查状态；新计划也不等于自动安全恢复。

## 五、只清除 userdata

不要执行上游 `e userdata`，该固定版本的封装有额外行为，详见 [命令说明](commands.md)。本脚本直接发送仅命名 userdata 的原生擦除请求：

```powershell
python .\scripts\f50.py erase-userdata --dll C:\F50Tools\spd_dump_LibUSB_Release\libusb-1.0.dll --plan C:\F50Tools\runs\B09-first --confirm ERASE_USERDATA
```

要求系统读回已通过、保护快照完整、当前保护分区仍相同、misc 没有 `boot-recovery` 命令，且本次没有先前擦除尝试。擦除响应必须 ACK，并抽查起点、中点、末端各 64 KiB 是否为空白。**抽查不等于读取验证每个字节，也不作为安全销毁数据的保证。**

若脚本检测到恢复模式命令，停下查明来源。本仓库不自动覆盖 misc 或恢复 persist，避免把其他设备的异常状态当成本案例。

## 六、比较保护分区，再重启

```powershell
python .\scripts\f50.py audit --dll C:\F50Tools\spd_dump_LibUSB_Release\libusb-1.0.dll --plan C:\F50Tools\runs\B09-first
python .\scripts\f50.py reset --dll C:\F50Tools\spd_dump_LibUSB_Release\libusb-1.0.dll --plan C:\F50Tools\runs\B09-first --confirm REBOOT
```

`audit` 保存 `post-protected`，全部相同才生成通过报告。发布版把 pm_sys_a/b 也纳入保护，实际数量由计划决定；现场原型比较了 21 项，两者不能混为同一份测试报告。

`reset` 再检查当前保护内容，并发送原生重启命令。ACK 只证明下载程序接受请求。首次启动可能较慢，之后在设备后台分别确认系统版本、基带初始化、网络注册、移动数据、USB 网络。两个灯一起亮不能单独判定成功或失败。切换到 WinUSB 或刷 B09 都不能证明 ADB/Root 已启用。

## 手工执行

熟悉上游工具者可以在现有 FDL2 中只重连一次，在交互提示符逐行运行生成的 `reviewed-commands.txt`，每条核对结果。自动化和手工执行二选一，不能连续把两份都跑一遍。

```powershell
.\scripts\Start-Fdl2.ps1 -ToolDirectory C:\F50Tools\spd_dump_LibUSB_Release -Reconnect
```

该文件含系统写入/metadata/cache 清除/A 槽设置/读回命令，**不含 userdata 或 reset**。完成后在空闲提示符关闭上游进程，运行 `verify-system` 再按第五、六步处理。整个流程不要重新冷启动，以免丢失现有 FDL2 会话。
