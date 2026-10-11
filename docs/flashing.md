# 保留原基带/NV 的 B15 → B09 示例

**会更改系统，并清除 userdata、metadata、cache，原数据无法保留。** 本页只适用于案例 F50、原 B15、配套 B09 整套镜像和 A 槽。单独看到压缩包名包含 B09，不能据此确认固件匹配。驱动教程可以参考，其他机型的刷写清单不能照搬。

先完成 [完整备份](backup.md)，保留原始镜像。刷写期间不拔线、不切驱动、不手动重启；任何校验失败都先停下检查。本仓库不会下载或分发固件。

## 一、自行准备系统包，先检查能不能用

**系统包请自行寻找，选择明确适合自己设备的包。** 本教程不提供或推荐具体包体。常见失败原因包括型号不符、下载不完整、混用不同包的文件、系统与原基带不兼容，以及遗漏必要补丁；如何判断见 [系统包可能失败的原因](case-study.md#系统包自己找留意这些失败原因)。

下面的脚本只支持案例里的包结构和分区布局，并不是任意系统包都能用。它要求包内有 `data` 镜像目录，还会把 `nr_modem_a.bin`、`nr_phy_a.bin` 与**你这台设备的原 B15 备份**进行比较。不一致就停止，不能跳过检查。即使一致，也只能说明这两份文件相同，不能保证整个系统一定兼容。

系统和启动文件要使用同一套，不要从不同包里拼装。这个脚本还有一项针对案例包的处理：如果存在 `bin/f50b09_t.bin`，就把它作为最终的 trustos 启动文件。其他包的刷机步骤可能不同，必须先对照作者说明和实际脚本核实，不能把这个规则直接套过去。额外的基带、联网配置或“优化”操作，如果用途不清楚，就先停下查明。

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

## 四、写入系统，再读回来检查

保持数据线连接，不拔线、不重启，让设备继续留在下载模式。下面的脚本会自己接回刚才的 FDL2 连接，**不用先运行 `Start-Fdl2.ps1 -Reconnect`**。这个版本的上游工具只支持一次 FDL2 重连；如果提前手动重连，再运行下面的脚本可能连不上。

```powershell
python .\scripts\run_spd_plan.py --plan C:\F50Tools\runs\B09-first --tool C:\F50Tools\spd_dump_LibUSB_Release\spd_dump.exe --execute
```

脚本会先把计划里的 14 项系统和启动文件逐个写进去，检查每项是否写完，再清掉旧系统的加密相关记录和缓存，设置从 A 套系统启动。之后把这 14 个分区完整读回电脑，检查刚写进去的内容和原文件是否一致。

如果一个分区比准备写入的文件大，就只把文件对应的那部分拿来比较；后面多出来的空间不能当成原文件的一部分。脚本另外会为整个读回分区保存校验值，方便记录，但不会把这个值当成尾部内容正确的证明。

在真正写入之前，脚本还会重新读取原基带、联网配置等需要保留的内容，与第三步保存的记录逐项比较。**两台设备的分区排列可能一样，所以只看分区表，不能确认连接的还是原来那台设备。** 这些内容只要有一项不一致，就先停止，不开始写入。

全部检查通过后，会生成本次的 `system-verification.json`。这一步只完成系统写入和检查，用户数据还没清，设备也不会自动重启；接下来按第五、六步继续。

如果中途报错，系统可能只写了一部分。**不要直接重启，也不要把整套命令再跑一遍。** 先让 AI 查看本次日志，确认停在哪一步。脚本会拒绝直接重复执行；换个新目录也不能解决已经发生的错误，要先查清原因。

不知道窗口里的结果该怎么看，可以对照 [系统写入的判断方法](commands.md#怎么判断写入有没有完成)：单项写入完成、读回检查通过和整套系统能正常启动，是不同阶段，要分别确认。

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
