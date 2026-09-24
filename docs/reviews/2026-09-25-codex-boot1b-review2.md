# Codex re-review: Slice 1b boot fixes (2026-09-25)

`codex exec -s read-only` over `git diff 3740f65..71f8d5c`. Final answer, verbatim:

只读审查完成。**原有主要方向正确，但还有三个需要补齐的缺口：EFI 早期写入竞态、thermal guard 失败退出、失败安装仍可被 publish。** 两个安装脚本及 thermal guard 语法检查通过，18 个 `thor_boot` 测试通过，菜单重渲染与提交文件完全一致；未执行安装、写盘或重启。需要创建临时文件的安装器测试未运行。

1. **问题：efivarfs 的 `ro` 会生效，但“运行系统不能写 EFI 变量”的结论仍过强。**  
   [install-thor-root.sh:187](scripts/install-thor-root.sh:187) 的配置确实会被 `systemd-remount-fs` 应用：efivarfs 属于 API 文件系统，remount 程序会处理它。但 PID 1 最初仍将其挂成可写。参见 [systemd v261 挂载实现](https://github.com/systemd/systemd/blob/v261/src/shared/mount-setup.c)、[重挂载实现](https://github.com/systemd/systemd/blob/v261/src/remount-fs/remount-fs.c)。

   **后果：**存在具体的条件写入路径：`systemd-hibernate-clear.service` 在真实 root 上清理遗留 `HibernateLocation`，没有 `After=systemd-remount-fs.service`，上游在启用相应构建选项时将它链接到 `sysinit.target.wants`。**变量存在且系统身份校验通过时**，它可能抢在 remount 前删除变量；不是每次启动都会写，也不能断言本次必然触发。[服务定义](https://github.com/systemd/systemd/blob/v261/units/systemd-hibernate-clear.service.in)、[身份检查及删除入口](https://github.com/systemd/systemd/blob/v261/src/hibernate-resume/hibernate-resume.c)。

   PID 1 早期的 `lock_down_efi_variables()` 还会修改 `LoaderSystemToken` 文件权限和 immutable 标志；**这属于 efivarfs inode 元数据操作，不能误报为写入变量内容或 BootOrder**。[实现](https://github.com/systemd/systemd/blob/v261/src/core/efi-random.c)。

   **修正：**首次实验至少 mask `systemd-hibernate-clear.service`，检查 USB root 实际安装、拉起的其他 EFI 写入服务，并收窄 [DECISIONS.md:161](docs/DECISIONS.md:161) 的保证。若要求从 PID 1 开始就强制禁止 efivarfs 写入，需要在执行 systemd 前将它挂成只读；普通 service 的排序无法覆盖 PID 1 自身。`CONFIG_EFI_VARS_PSTORE` 未启用，已经解决上轮提出的 EFI pstore 条件风险。

2. **问题：thermal guard 的周期检查已实现，但保护仍能被诊断阻塞，且重启失败会永久退出。**  
   [thermal-guard:26](scripts/thor-rootfs/thermal-guard:26) 在判断已经读到的高温之前，仍查询服务状态、读取 hwmon；后者没有超时。`timeout 5 nvpmodel` 也没有 `--kill-after`，遇到忽略 SIGTERM 的进程不构成硬上限。更明确的是 [thermal-guard:34](scripts/thor-rootfs/thermal-guard:34)：无论 `systemctl reboot` 是否失败，最终都 `exit 0`。

   **后果：**重启请求被拒绝或失败后，`Restart=on-failure` 不会重启保护。内存中的 shell stub 验证了这一点：模拟 `systemctl reboot` 返回 1，guard 仍返回 0。已有 [测试:73](tests/test_thermal_guard.py:73) 的“后来过热”测试实际启动了两次进程，也没有覆盖同一进程持续运行中的变化。

   **修正：**高温／无温度读数直接进入保护分支；RPM 等辅助读取放到决策后并限时；外部命令加 TERM→KILL 上限；重启请求失败必须非零退出或继续重试，不能成功退出。补充请求失败、忽略 TERM、同一进程后续升温测试。周期检查、移除 watched-service 排序已经解决上轮相应部分；RPM 当前仅记录，不能宣称检测了机械停转。

3. **问题：提前发布窗口已关闭，但失败安装没有使“可发布状态”失效。**  
   [install-thor-boot.sh:108](scripts/install-thor-boot.sh:108) 将旧正式 loader 改成 `.staged`；[119 行](scripts/install-thor-boot.sh:119) 又在菜单和 grubenv 完成前放入新 `.staged`。后续失败时，该文件仍可能存在。

   **后果：**随后执行 `publish`，只检查 prefix、菜单语法、grubenv 大小和模块存在。它不能辨别“本轮安装完整成功”与“旧 loader＋部分更新的模块／菜单／旧 next_entry”。后者仍可能通过检查并进入 GRUB 救援界面或启动旧的一次性条目。失败本身不会自动发布，这与上一轮的直接窗口已经不同。

   **修正：**开始修改前撤销发布就绪标记；旧 loader 保存为不可发布的备份；所有内容完成、验证并同步后，最后建立就绪标记。`publish` 必须验证这个状态，最好绑定相关文件哈希。增加“已有安装→本轮失败→publish 必须拒绝”的测试。

4. **问题：ESP 子目录方案成立；prefix 检查有用，但不是完整的 core 映像验证。**  
   [install-thor-boot.sh:114](scripts/install-thor-boot.sh:114) 的两个目录参数职责不同：`efi-directory` 决定 EFI 文件放置位置，`boot-directory` 决定 GRUB 数据目录。**显式指定 ESP 子目录是可接受的**；你的 GRUB 2.14 FAT loop 实验已直接证明这一点。上游实现也仅在自动寻找 EFI 目录时要求挂载点，显式目录则查其所在设备和文件系统，并在其下追加 `EFI/BOOT`。[grub-install 实现](https://github.com/rhboot/grub2/blob/master/util/grub-install.c)。

   **后果：**保持 `--boot-directory=/mnt/raytone-esp/boot` 时，相对路径仍应为 `/boot/grub`。无分区表的 `()/boot/grub` 与 GPT 第一分区的 `(,gpt1)/boot/grub` 并不矛盾；后者省略的是启动磁盘名，不是分区号。不过 [check_prefix:103](scripts/install-thor-boot.sh:103) 只是子串搜索，`(,gpt1)/boot/grub-other` 也能通过，更不能证明命中的字符串就是生效的 prefix、映像未截断或模块匹配。

   **修正：**至少检查完整 NUL 终止的 prefix，严格验证则解析 GRUB prefix 模块并核对 ARM64 EFI 映像结构。**现有检查足以作为此次目录调整的回归告警，不足以单独证明可启动。**无需因 GPT loop 实验没完成而否定此方案；仍应在真实 U 盘 staged 产物上检查，并先完成有人值守的默认 JetPack 路径测试。

5. **问题：新固件证据足以支持有人值守实验，但仍不是固件来源的完整证明。**  
   [kernel-provenance.md:35](docs/evidence/slice1b/kernel-provenance.md:35) 已纠正“早于 `/init` 就不来自 initramfs”的错误。2025 年运行固件与已检查的 2020 年文件不符，加上空 `CONFIG_EXTRA_FIRMWARE`、内建存储驱动和 `DEVTMPFS_MOUNT=y`，明显加强了无需 initramfs 的依据。

   **后果：**它支持“启动固件预装了控制器固件”的推断，却没有完整排除厂商其他加载机制，也不能证明 NVIDIA 原版内核在冷启动和 GRUB 路径下同样能接管控制器。文中“boot firmware … boots from USB”也不应由这些证据推出。

   **修正：**将确定语气改成推断，保留文件扫描、initrd 清单、固件头解析和运行日志原始输出。**不必为有人值守实验强制恢复 initramfs 条目**；测试仍须保留拔盘／断电恢复条件，并分别记录原版和厂商内核结果。

6. **问题：五分钟重启升级补上了一部分，但不覆盖重启请求之前的失败。**  
   [install-thor-root.sh:235](scripts/install-thor-root.sh:235) 的 `JobTimeoutSec=5min` 和 `JobTimeoutAction=reboot-force` 能约束已经排队的 `reboot.target` 作业。

   **后果：**PID 1 未运行、无响应、请求未成功排队、内核挂死，都不会因此获得五分钟保证；强制重启也可能留下 USB 文件系统待恢复。这没有越界写 NVMe 的新路径，但不能替代硬件 watchdog 验证。

   **修正：**保留 [DECISIONS.md:181](docs/DECISIONS.md:181) 的一次真实 deadman 回退测试，并分别记录“普通超时重启成功”和“硬件 watchdog 已验证”。上轮这一条可按**部分解决、剩余风险由有人值守承担**处理。

7. **问题：initramfs、`ro` 和 GPT 自动发现的修正正确，没有发现相互冲突。**  
   [entries-1b.json:24](docs/evidence/slice1b/entries-1b.json:24) 已移除两个 Arch 条目的 initrd；JetPack 的 Slice 1a initrd 是另一个实验，不是被移除的 Arch 备用路径。

   **后果：**Arch 不再走那个未经处理的 mkinitcpio emergency shell。无 initramfs 时，内核依据显式 `root=PARTUUID` 挂载 USB root，`ro` 允许 `systemd-fsck-root` 执行；随后 remount 按 [fstab:186](scripts/install-thor-root.sh:186) 重挂可写。`systemd.gpt_auto=0` 不禁用 fstab generator，因此不会阻止这条路径；无需为不存在的 initramfs 增加 `rd.systemd.gpt_auto=0`。[fsck 条件](https://github.com/systemd/systemd/blob/v261/units/systemd-fsck-root.service.in)、[remount 排序](https://github.com/systemd/systemd/blob/v261/units/systemd-remount-fs.service.in)。

   **修正：**这部分无需再改；首次启动记录 fsck/remount 日志、实际根设备、挂载与 swap。关闭 GPT 自动发现仍不能代替检查其他独立挂载／swap 单元。

8. **问题：模块兼容性和 FDT 的修正文案合理，验收仍待实际启动。**  
   [kernel-provenance.md:12](docs/evidence/slice1b/kernel-provenance.md:12) 已限制兼容性结论；[boot-marker:279](scripts/install-thor-root.sh:279) 增加 `uname -v`；[DECISIONS.md:167](docs/DECISIONS.md:167) 不再整体丢弃 `/chosen`。删除条目后 fallback 已正确变为 `4`。

   **后果：**这些改动没有新增越界写入路径，但不能把计划记录当成已验证结果；厂商内核成功仍不代表 NVIDIA 原版通过。

   **修正：**按现有步骤保存完整 Image 哈希、原始 FDT、实际 cmdline/root、已加载模块与错误日志即可。

不建议执行（最小修改：排除 efivarfs 重挂载前的 EFI 写入服务；让 thermal guard 在诊断阻塞或重启请求失败时保持保护；使失败／中断的 staged install 无法通过 publish）。
