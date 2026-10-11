# 命令与行为说明

本文对应 [stable_20250726_0012](https://github.com/TomKing062/spreadtrum_flash/releases/tag/stable_20250726_0012)，源码提交 `2a202404a7512026d146b62624f089aceb408520`。其他版本的行为需要重新核对。

## 连接与读取

**对应脚本：** [Start-Fdl2.ps1](../scripts/Start-Fdl2.ps1) 负责建立连接，[f50.py](../scripts/f50.py) 负责连接请求和备份读取，[f50lib.py](../scripts/f50lib.py) 提供配套 USB 读写功能。下表中的 `spd_dump` 指令由外部工具执行。

| 操作 | 含义与限制 |
| --- | --- |
| mode 2 握手 | 先发控制请求 `0x21/34/0x601`，再发 `7e 00 00 00 00 08 00 fe 82 7e`，等新枚举后交接；本案例无需 ADB 或短接 |
| `spd_dump --wait 30 --verbose 0` | 在 mode 2 交接后开始上游加载流程；只适用于本机支持的 AutoD 路径 |
| `spd_dump --wait 30 --stage 99 --verbose 0` | 接管现有 FDL2；上游明确 FDL2 只支持重连一次，不是无限重试按钮 |
| `timeout 30000` | 读写命令等待上限（毫秒） |
| `blk_size 65024` | 案例使用的传输块大小 |
| `partition_list connected-gpt.xml` | 读取分区表，工具同时生成 pgpt，用其哈希匹配备份 |
| `read_part NAME OFFSET SIZE FILE` | 名称读取；注意上游有 NV1 重定向等特例 |
| 原生 `0x10/0x11/0x12` | READ_START/MIDST/END；本仓库按 GPT 物理读取完整备份，保留 NV 头部 |

握手只能用于支持此下载模式的设备，不代表绕过固件认证。FDL 的内存发送/执行不是镜像持久化写入。若上游自动加载失败，本教程没有提供其他型号的 FDL 或任意地址。

## 系统写入

**对应脚本：** [f50.py](../scripts/f50.py) 的 `plan` 生成命令清单，[run_spd_plan.py](../scripts/run_spd_plan.py) 执行计划并检查结果。下面的 `w`、`read_part` 是外部 `spd_dump.exe` 的交互命令，不是 Python 脚本命令。

```text
w boot_a "C:\F50Tools\runs\B09-first\images\boot_a.bin"
read_part boot_a 0 实际分区字节数 "C:\F50Tools\runs\B09-first\readback\boot_a.bin"
```

第一行是“把文件写进设备”，第二行是“再从设备读出来，检查有没有写对”。这里是语法示例，`实际分区字节数` 要由计划填写，不能原样执行。**不能只刷 boot_a 后重启**，要按计划完成全部 14 项系统和启动文件。

`e metadata`、`e cache` 是清掉旧系统的加密相关记录和缓存；用户数据另一步处理。`set_active a` 是告诉设备“下次从刚刷好的 A 套系统启动”，只改启动选择记录，不是把整个 misc 都换掉。

### 怎么判断写入有没有完成？

**分三步看：这一项写完了没有、读回来是不是一样、整个计划有没有完成。** 不用自己算这些数字，自动脚本会检查；手工操作时也可以让 AI 对照本次计划和日志逐项核对。

| 窗口里看到什么 | 代表什么 | 怎么判断、接下来怎么做 |
| --- | --- | --- |
| `PLAN ONLY` 或 `DRY RUN` | 只是生成或预览计划，还没刷 | 不能当成写入成功 |
| 百分比或速度还在变化 | 正在处理当前文件 | 继续等，不拔线、不重启；短暂没有新文字不能单独说明卡死 |
| `Write Part Done: boot_a, target: ..., written: ...` | 工具报告这一项写完了 | 名称必须是当前计划里的目标；`target` 和 `written` 都要等于计划里这项文件的大小，才算这一项写入完成 |
| `Read Part Done: boot_a+0x0, target: ..., read: ...` | 工具报告这一项读回了 | 名称要对应，`+0x0` 表示从开头读；`target` 和 `read` 都要等于这项的整个分区大小，还要继续检查内容是否一致 |
| `VERIFIED boot_a` | 这一项读回内容检查通过 | 这里只通过了一项，要等全部 14 项；不能看到一行 VERIFIED 就重启 |
| 自动脚本最后显示 `System verified. FDL2 stays loaded. No userdata wrapper or reboot executed.`，并正常结束 | 系统写入和读回检查阶段完成 | 核对本次检查报告，再按刷写教程继续清用户数据、检查保留内容和重启；这条消息本身没有重启设备 |
| `STOPPED:`、`Incomplete write/read`、`Readback differs`、超时或程序意外退出 | 某一步没完成，或检查没通过 | 停在这里，保留本次日志；不要直接重启，也不要重新跑整套命令赌一次 |

上面的 `...` 只是省略数字的示意，不是程序实际打印的内容。日志里的大小常写成 `0x` 开头的数字，和计划里的普通数字可能看起来不同。比如 `0x100000` 就是 1,048,576 字节，可以让 AI 换算后比较，不能只看字符是否一样。**写入时对比文件大小，完整读回时对比分区大小，这两个大小可能不同。** `plan.json` 中对应字段分别是 `size` 和 `partition_size`。

另外，清缓存的命令应分别出现 `Erase Part Done: metadata`、`Erase Part Done: cache`。设置启动位置后，本版本会显示 `Write Part Done: misc`，表示启动选择记录已写入；**这一条不能证明整个系统已经刷好，也不能证明设备已经能正常开机**。只重新出现 `FDL2 >` 也不够，要核对前面的完成消息。

### 怎么判断读回检查通过？

自动脚本已经包含这一步。手工执行完整计划后，在 `FDL2 >` 空闲提示符关闭电脑上的上游程序，保持数据线连接，再运行下面的检查命令；路径换成你本次的计划目录：

**本步使用的脚本：** [f50.py](../scripts/f50.py) — `verify-system` 检查系统读回文件。 配套文件：[f50lib.py](../scripts/f50lib.py)，请保留在同一 scripts 目录。

```powershell
python .\scripts\f50.py verify-system --plan C:\F50Tools\runs\B09-first
```

它会逐项检查：读回文件有没有读全，以及刚写入的那部分内容和原文件是否一致。需要看到全部 14 项 `VERIFIED`，命令正常结束，并生成本次的 `system-verification.json`。用记事本打开报告，确认 `all_match` 为 `true`，`images` 中有计划里的全部 14 项，每项 `source_prefix_matches` 都为 `true`。报告要来自**本次运行目录**，旧报告不能代替本次检查，也不能自己改成 true。

检查的是源文件实际覆盖的内容；如果分区比源文件大，多出来的尾部不要求和源文件相同。**这一步通过，只说明系统文件写入检查通过。** 还需要完成 [刷写教程](flashing.md) 后面的用户数据清理、保留内容检查和重启，再看设备能否正常开机、联网，才能判断最终结果。

如果不知道报错该怎么看，可以让 AI 读取本次 `plan.json`、`spd-session.log` 和检查报告，要求它列出“哪项完成、哪项没完成、判断依据是什么”。没有完成消息或报告缺失时，不能靠猜测补成成功。

## 特别注意：`e userdata` 的封装行为

固定版本的 [erase_partition 源码](https://github.com/TomKing062/spreadtrum_flash/blob/2a202404a7512026d146b62624f089aceb408520/common.c#L1232-L1258) 说明：当名称为 userdata 时，工具会向 misc 写入 `boot-recovery` 和 `--wipe_data`，随后请求擦除 **persist**。因此它不是“直接只擦 userdata”。

从 recovery 命令可判断设计意图是让恢复模式执行数据清除，但源码本身未说明额外擦 persist 的机型适用理由。**不能把它解释成 B15 基带专用优化。** 本仓库不调用这条封装，改用原生 `0x0A`、UTF-16LE 分区名 userdata、长度 0，并要求 ACK 和空白抽查。

现场曾运行一次这个封装命令，随后在重启前从刷前快照恢复 persist、清除恢复命令，并校验恢复结果；详见 [案例记录](case-study.md)。发布脚本不自动复现这项恢复处理。

## 本教程不使用的批量命令

| 命令 | 不采用的原因 |
| --- | --- |
| `write_parts .\data\` | 会把目录中所有可匹配镜像交给工具，可能覆盖基带、NV、启动加载器，无法满足保留要求 |
| `r all` 当作完整备份 | 明确跳过部分分区，不能满足包含 userdata 的要求 |
| `e userdata` | 有 misc/persist 副作用 |
| `erase_all` / `repartition` | 与本案例目标无关，会破坏当前布局或更多数据 |
| 写入别人的 NV/persist | 可能带来身份/校准冲突，本案例要求保留本机数据 |
| 一串命令最后自动 `reset` | 前面的写入/读回失败时可能仍继续重启，本仓库重启单独受校验约束 |

`--kick`/`--kickto 2` 是上游支持的连接选项，但案例 Windows LibUSB 构建存在热插拔路径限制，采用本仓库分阶段 mode 2 交接。没有验证成功的注册表绕过不列为推荐步骤。
