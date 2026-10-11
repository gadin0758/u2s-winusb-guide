# WinUSB 下完整备份

U2S 串口无法写入时，原串口备份脚本也会失败。WinUSB 配合 LibUSB 可提供另一条通信路径，但仍需正确进入 FDL2。先按 [主教程](../README.md) 切换目标驱动并加载 FDL2。

## 备份范围

本仓库的“完整”指：**GPT 中所有有效分区 + 256 KiB splloader**，另存最前方 32 KiB `pgpt.bin`。不是只读系统或只读活动槽位。

包含两套 `nr_modem_*` / `nr_phy_*`、`nr_*nv*` / `l_*nv*`、prodnv、calinv、miscdata、persist、ztecfg、ztepersist、启动镜像、super、cache、blackbox、userdata 等，以本机 GPT 为准。不会改写或重置这些分区。RPMB、eFuse、未映射空间、备份 GPT 和其他 eMMC 硬件区不属于此备份范围，不能称为整颗芯片镜像。

原案例读取 75 个 GPT 分区，加 splloader 为 76 个镜像，合计 **31,269,847,040 字节**，另有 pgpt。userdata 本身 **24,985,468,928 字节**，其物理起点超过 4 GB；备份必须支持 64 位读取。这个数量与大小只代表案例设备，不要求其他机型相同。

## 为什么不用 `r all`

固定版本的 [上游说明](https://github.com/TomKing062/spreadtrum_flash/blob/2a202404a7512026d146b62624f089aceb408520/README_zh.md) 明确列出 `r all` 跳过 blackbox、cache、userdata。该版本 [dump_partition](https://github.com/TomKing062/spreadtrum_flash/blob/2a202404a7512026d146b62624f089aceb408520/common.c#L867-L904) 对名称含 nv1 的请求还会转向 nv2，并跳过 512 字节头部。

所以本脚本根据已验证 GPT，以 `user_partition` 和物理偏移读取，保留两份 NV 各自的原始内容和头部。它只发送 READ_START/MIDST/END，读回数据必须满足长度与帧校验要求。

## 执行与检查

1. 磁盘不能是 FAT32。保留至少 35 GB 空间；若还要刷写并保存读回镜像，建议预留更多。脚本根据本机分区总大小检查剩余空间。
2. 上游工具已显示 `FDL2 >`，在空闲提示符按 Ctrl+C 退出主机程序，不拔线、不重启。
3. 使用一个**不存在的新输出目录**：

```powershell
python .\scripts\f50.py backup --dll C:\F50Tools\spd_dump_LibUSB_Release\libusb-1.0.dll --out C:\F50Tools\backups\B15-original
```

4. 等待全部读取结束。每隔约 30 秒显示进度，大文件读取可能持续较久；案例约需二十余分钟，具体取决于接口和磁盘。不要因短暂没有新输出而断电。
5. 离线校验：

```powershell
python .\scripts\f50.py verify-backup --backup C:\F50Tools\backups\B15-original
```

看到 `BACKUP VERIFIED` 才表示 GPT、清单覆盖范围、文件长度与 SHA-256 全部通过。查看目录中的 `verified-manifest.json` 和 `SHA256SUMS.txt`。清单必须为 `complete: true`。

## 失败、续读与保存

脚本不覆盖既有镜像，也不自动续读。失败时保留 `.partial` 和不完整清单，**不能把它们当作可恢复备份**。排查连接后重新加载 FDL2，选一个新的目录完整重读；不要通过手工改 `complete` 绕过校验。

本案例最初使用的是现场脚本。发布版清单包含额外的范围字段，旧备份不能直接改名冒充新清单。需要逐项确认映射再转换，不能删除保护检查。

备份完成后，复制到另一个磁盘，再对复制品执行相同校验。保留整套原镜像和清单，不要只留 modem：恢复网络还可能需要 PHY、NV、persist、启动链等。

**备份只保存在本地。** 不公开 NV、设备序列号、IMEI、后台密码、userdata、原始日志或设备截图。MIT 许可证不授权发布第三方固件，也不授权公开他人的设备数据。
