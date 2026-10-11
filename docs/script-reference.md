# 每条脚本指令的作用

本仓库只发布自编源码和说明。上游刷写工具、USB DLL、Zadig、驱动安装器、固件镜像均需从各自来源取得，**不上传或打包到本仓库**。下载链接与版本见 [主教程](../README.md#2-准备工具和原驱动)。

本文中的 `python` 表示你安装的 Python。所有文件路径是示例；设备实例路径、实际 OEM INF 编号、基带哈希和备份数据由用户在本地填写/生成，仓库不公开任何个人设备读数。

## 一、电脑驱动相关指令

| 指令 | 每个参数的作用 | 实际改变 |
| --- | --- | --- |
| `Check-Drivers.ps1` | 无参数；列出电脑已连接设备的驱动信息，筛选下载设备及相关接口 | 只读电脑设备信息 |
| `Export-U2SDriver.ps1 -PublishedName oem数字.inf -OutDirectory 路径` | PublishedName 是本机原 sprdvcom 驱动的实际 OEM INF 名；OutDirectory 是保存完整驱动包的本地目录 | 复制电脑驱动到指定目录，不改设备绑定 |
| `Prepare-U2SDriver.ps1 -DriverInf 路径\sprdvcom.inf` | DriverInf 指向完整原驱动包中的 INF，不是 Zadig 生成的 INF | 将原驱动加入 Windows 驱动库并请求安装；可能仍需设备管理器手动绑定 |

这几个脚本内部用到：

| Windows 命令 | 作用 |
| --- | --- |
| `pnputil /enum-devices /connected /drivers` | 查询目前已连接设备及匹配驱动 |
| `pnputil /enum-drivers` | 查询第三方驱动包的实际 OEM 名称 |
| `pnputil /enum-devices /instanceid "本机实例路径" /drivers` | 仅查询指定设备实例，实例路径不应公开 |
| `pnputil /export-driver oem数字.inf 目录` | 导出指定驱动包，用于后续恢复 |
| `pnputil /add-driver sprdvcom.inf /install` | 将指定驱动包加入电脑，并请求安装到匹配设备；不保证覆盖现有 WinUSB 绑定 |

不使用 `/delete-driver`，不删除其他设备的驱动。具体绑定和确认步骤见 [恢复 U2S](restore-u2s.md)。

## 二、建立下载会话

| 指令 | 参数含义 | 对设备的作用 |
| --- | --- | --- |
| `Start-Fdl2.ps1 -ToolDirectory 目录 [-Python python路径]` | ToolDirectory 内必须同时有 LibUSB 版 spd_dump.exe 和配套 DLL；Python 可指定解释器 | 等关机插线，发 mode 2 请求，交接给上游加载 RAM 中的 FDL；不刷分区 |
| `f50.py connect --dll DLL路径 --wait 300` | dll 是本地 libusb-1.0.dll；wait 为等待秒数，默认 300 | 仅完成 mode 2 和重枚举交接，不加载 FDL、不备份、不写分区 |
| `Start-Fdl2.ps1 -ToolDirectory 目录 -Reconnect` | Reconnect 表示设备已有 FDL2；不得关机或再运行模式探测 | 重连已有 FDL2，一次会话最多使用一次上游重连 |

`Start-Fdl2.ps1` 已调用 connect，不要先手动 connect 再把完整 Start-Fdl2 又跑一遍。模式请求会改变设备运行状态，但不是持久化镜像写入。

## 三、备份与离线计划

| Python 子命令 | 必需参数 | 作用与输出 |
| --- | --- | --- |
| `f50.py backup` | `--dll DLL --out 新目录` | 在现有 FDL2 按物理范围读取所有 GPT 分区及 SPL；输出镜像、完整性清单、SHA256SUMS；只读设备 |
| `f50.py verify-backup` | `--backup 备份目录` | 离线校验 complete 标记、GPT CRC、分区覆盖范围、大小、哈希；无需 USB |
| `f50.py plan` | `--backup 备份目录 --package 固件包目录 --out 新目录` | 离线验证备份和配套 modem/PHY，暂存 14 项系统镜像，生成 plan.json 和 reviewed-commands.txt；不刷写 |
| `f50.py snapshot` | `--dll DLL --plan 计划目录` | 读取此次刷前全部保护分区，保存 pre-protected；只读、拒绝覆盖基线 |
| `run_spd_plan.py` | `--plan 计划目录 --tool spd_dump.exe路径` | 默认只显示待执行指令；不打开 USB、不刷写 |
| `f50.py verify-system` | `--plan 计划目录` | 离线比较 14 项读回镜像的长度与源覆盖范围哈希；保存 system-verification.json |
| `f50.py audit` | `--dll DLL --plan 计划目录` | 读取刷后全部保护分区与刷前比较，保存 post-protected 和通过报告；只读设备 |

`--out` 要求不存在的新目录；脚本拒绝覆盖备份或计划。`--plan` 指整个计划目录，不是 plan.json 文件。`--package` 是同时包含 data 和可选 bin 目录的固件包根目录。

## 四、会改变系统或删除数据的指令

| 指令 | 作用 | 前置条件 |
| --- | --- | --- |
| `run_spd_plan.py --plan 目录 --tool EXE --execute` | 重连 FDL2，核对备份/当前保护内容，写入 14 项系统目标，擦 metadata/cache，设 A 槽并读回校验 | 完整备份、完整刷前快照、源哈希、设备保护内容都通过；已尝试的计划不能直接重复 |
| `f50.py erase-userdata --dll DLL --plan 目录 --confirm ERASE_USERDATA` | 原生请求只擦 userdata，删除用户数据，读回三点检查空白 | 系统读回通过、当前保护内容不变、无 recovery wipe 命令、未曾尝试本次擦除 |
| `f50.py reset --dll DLL --plan 目录 --confirm REBOOT` | 原生请求重启设备；不刷镜像 | 系统和保护分区报告通过，userdata 擦除检查通过，当前保护内容再次匹配 |

`--execute` 才会真正刷写；`--confirm` 必须与表内字符串完全一致。任何报错停止后，不能把确认词当作绕过检查的方式。失败时脚本不会自动 reset。

## 五、计划中每条上游指令的作用

以下说明针对 `reviewed-commands.txt` 中生成的命令，路径和字节数由本地计划填写：

| 指令 | 作用 |
| --- | --- |
| `timeout 30000` | 将读写等待时间设为 30 秒 |
| `blk_size 65024` | 设置每块传输的数据字节数 |
| `w TARGET "镜像路径"` | 把文件写入明确命名的目标；每条必须匹配目标名、目标字节数和实际写入字节数 |
| `e metadata` | 清除旧数据加密元数据；旧用户数据不可依赖它继续解密 |
| `e cache` | 清除缓存分区 |
| `set_active a` | 写 misc 的槽位控制信息，选择已刷 A 槽启动 |
| `read_part TARGET 0 分区大小 "读回路径"` | 完整读取刚写过的目标到本地，检查长度和源覆盖范围哈希；不写设备 |

自动执行器还在写入前调用 `partition_list connected-gpt.xml` 并读取保护分区，目的分别是核对 GPT 与保护内容。上游进程只在全部步骤完成或发生错误时于电脑端关闭，不以 reset 收尾。

### 14 个写入目标分别是什么

通用 Android 分区用途可参考 [AOSP 分区说明](https://source.android.com/docs/core/architecture/partitions) 和 [vendor_boot 说明](https://source.android.com/docs/core/architecture/partitions/vendor-boot-partitions)。下表中厂商专有项只说明本计划如何使用，不声称已经完整反编译。

| `w` 目标 | 本计划用途 |
| --- | --- |
| `trustos_a` | 配套可信执行环境镜像；优先采用作者最终覆盖的 f50b09_t.bin |
| `sml_a` | 厂商配套安全启动链镜像；未独立解码，随整套系统匹配保留 |
| `teecfg_a` | 厂商配套 TEE 配置镜像；未独立解码，不能随意换成其他包 |
| `boot_a` | A 槽系统启动镜像，含内核等启动内容 |
| `vendor_boot_a` | A 槽厂商启动部分，含设备相关 ramdisk/设备树等，须与 boot/system 配套 |
| `dtbo_a` | A 槽设备树覆盖镜像，描述硬件相关配置 |
| `common_rs1_a` | 包里的厂商配套镜像；内部用途未独立确认，按原包完整搭配使用 |
| `vbmeta_a` | A 槽启动验证元数据 |
| `vbmeta_system_a` | system 相关的配套验证元数据 |
| `vbmeta_vendor_a` | vendor 相关的配套验证元数据 |
| `vbmeta_system_ext_a` | system_ext 相关的配套验证元数据 |
| `vbmeta_product_a` | product 相关的配套验证元数据 |
| `vbmeta_odm_a` | odm 相关的配套验证元数据 |
| `super` | 动态逻辑分区容器；整份写入包中配套系统与厂商逻辑分区，不只抽取 system |

这些镜像并非全部都在每个 Android 设备上存在。只读备份按本机 GPT 获取列表，写入白名单则专为本案例布局固定。

### 为什么没有 userdata 的上游命令

固定工具版本的 `e userdata` 还会写 misc 恢复命令并擦 persist，故不出现在计划中。本仓库单独的 erase-userdata 直接发送仅指定 userdata 的原生请求。更多说明见 [命令行为](commands.md)。
