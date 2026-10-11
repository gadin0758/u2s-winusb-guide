# 命令与行为说明

本文对应 [stable_20250726_0012](https://github.com/TomKing062/spreadtrum_flash/releases/tag/stable_20250726_0012)，源码提交 `2a202404a7512026d146b62624f089aceb408520`。其他版本的行为需要重新核对。

## 连接与读取

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

```text
w boot_a "C:\F50Tools\runs\B09-first\images\boot_a.bin"
read_part boot_a 0 实际分区字节数 "C:\F50Tools\runs\B09-first\readback\boot_a.bin"
```

这里是语法示例，**不能只刷 boot_a 后重启**。实际由计划生成完整 14 项白名单及真实大小。

`e metadata`、`e cache` 清除旧加密元数据和缓存；用户数据随后独立清除。`set_active a` 修改 misc 偏移 `0x800` 的槽位控制信息，让设备从已刷 A 槽启动。它不等于写入整份 misc。

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
