# Codex review: Slice 1b boot configuration (2026-09-25)

`codex exec -s read-only`, prompt: entries-1b.json, grub.cfg.dry-run, kernel-provenance.md, install-thor-{root,boot}.sh, thor_boot.py. Final answer, verbatim:

只读审查完成：两个 shell 脚本语法检查通过，重新渲染与 `grub.cfg.dry-run` 完全一致；未执行安装、写盘或重启。以下区分明确缺陷与尚缺证据的风险。

1. **问题：staged install 存在提前发布窗口。**  
   [install-thor-boot.sh:103–105](scripts/install-thor-boot.sh:103) 先由 `grub-install` 写出正式 `EFI/BOOT/BOOTAA64.EFI`，成功返回后才改名。  
   **后果：**命令部分失败、进程中断或断电，都可能留下可启动文件及未完成配置；下次开机 USB 优先，机器可能停在 GRUB。这与“publish 前不可启动”的承诺不符。  
   **修正：**在固件不会扫描的临时目录生成 EFI，完成后放到 `.staged`；只有 `publish` 能创建正式路径。失败出口也必须检查正式路径不存在。

2. **问题：initramfs 备用条目没有覆盖早期失败的自动重启。**  
   [install-thor-root.sh:161–165](scripts/install-thor-root.sh:161) 使用 `base udev`，不是 systemd initramfs；[entries-1b.json:28–33](docs/evidence/slice1b/entries-1b.json:28) 只有 `rootwait=20 panic=10`。  
   **后果：**找不到根盘、挂载失败或 fsck 失败时，mkinitcpio 可以进入交互 shell；此时没有 kernel panic，也尚未启动 USB root 的 deadman／emergency 单元。`rootwait=20` 不能充当这个用户态流程的总超时。[上游实现](https://github.com/archlinux/mkinitcpio/blob/master/init_functions)。  
   **修正：**检查实际生成镜像中的 `/init`、`init_functions`，加入有界等待和失败重启的 emergency hook，覆盖挂载、fsck、缺失 init 等出口；否则暂时移除这个备用条目。当前 [usb-root-inspect.txt:90](docs/evidence/slice1b/usb-root-inspect.txt:90) 的 initramfs 检查内容为空，生成成功日志不能替代该检查。

3. **问题：deadman 等单元能请求重启，但不能保证机器一定复位。**  
   [install-thor-root.sh:193–226](scripts/install-thor-root.sh:193) 最终调用普通 `systemctl reboot`；[DECISIONS.md:145–147](docs/DECISIONS.md:145) 已明确硬件 watchdog 未验证。  
   **后果：**早期内核挂死、PID 1 尚未启动、重启第一阶段卡住，都可能不能自动返回。PID 1 仍能喂狗时，其他服务卡住也不一定触发硬件复位；`RebootWatchdogSec` 主要覆盖重启第二阶段。[systemd 说明](https://github.com/systemd/systemd/blob/main/man/systemd-system.conf.xml)。此外，默认链加载失败会重启后再次选择同一条目，不会自动绕过 USB。  
   **修正：**保留“默认 JetPack 路径先验证”的顺序；有人在场时实际验证一次不创建 keep 标记的超时回退，并核对 watchdog 设备、PID 1 生效配置和复位行为。配置正常重启失败后的有界升级路径；首次测试仍须具备拔 USB／断电恢复条件，不能承诺所有故障自动恢复。

4. **问题：禁止 UEFI 写入的保证目前只覆盖安装 chroot，不覆盖 Arch 启动。**  
   [install-thor-root.sh:18–22](scripts/install-thor-root.sh:18) 以未安装 efibootmgr 等作为说明，但三个 Arch 条目均保留 `efi=runtime`，没有启动后的 efivarfs 防写措施。  
   **后果：**尚不能证明整个测试不会主动写 UEFI 变量。例如，**若**启用了 EFI pstore，panic 日志可以直接写非易失 EFI 变量，不依赖 efibootmgr，甚至不依赖可写 efivarfs。[Linux EFI pstore 实现](https://github.com/torvalds/linux/blob/v6.8/drivers/firmware/efi/efi-pstore.c)。这是条件风险，现有证据没有证明本机启用了它。  
   **修正：**核对两个内核的 `CONFIG_EFI_VARS_PSTORE*`、实际 pstore 后端及 USB root 的相关服务；Arch 测试条目可显式加 `efi_pstore.pstore_disable=1`，并在 initramfs／真实 root 两阶段限制 efivarfs 写入。检查启动相关服务的实际启用状态。未发现所审脚本直接刷 QSPI 或修改 NVMe 分区表、ESP 的命令，但不能将此扩大成全过程零写入保证。

5. **问题：不带 initramfs 的核心依据存在错误推断。**  
   [kernel-provenance.md:26–37](docs/evidence/slice1b/kernel-provenance.md:26) 的内建存储驱动、非 UAS 证据有价值；但“固件日志早于 `Run /init`，所以不来自 initramfs”不成立。内核会先解包 initramfs，内建驱动可以在执行 `/init` 前读取其中固件；固件加载器明确调用 `wait_for_initramfs()`。[Linux 6.8 源码](https://github.com/torvalds/linux/blob/v6.8/drivers/base/firmware_loader/main.c)。  
   **后果：**原版内核可能无法建立 USB root 路径。且 `rootwait=20` 只限制特定根设备等待循环，不限制此前驱动探测及所有异步等待，不能推出“最多约 30 秒一定重启”。[根挂载实现](https://github.com/torvalds/linux/blob/v6.8/init/do_mounts.c)。  
   **修正：**核对 Thor 对应 xHCI 驱动实际固件来源、JetPack initrd 内容、内建固件配置，并补查无 initramfs 所需的 `CONFIG_DEVTMPFS_MOUNT`。证据补齐前，无 initramfs 只能作为有人值守的实验，不能称启动依据充分；备用 initramfs 也要确认确实包含所需固件。

6. **问题：thermal guard 只有一次检查，而且诊断命令可能阻断保护动作。**  
   [install-thor-root.sh:248–275](scripts/install-thor-root.sh:248) 只在启动后检查一次；写日志时先执行无超时的 `nvpmodel -q`，之后才判断是否重启，还排序在 nvpmodel 服务之后。  
   **后果：**nvpmodel 启动或查询卡住时，保护可能迟迟不执行；90 秒后风扇故障、温度上升也不会再次检查。`nvfancontrol=active` 不能证明实际转速正常，touch keep 后尤其容易误认为仍有持续保护。  
   **修正：**先判断温度和风扇失败，再做带超时的辅助诊断；改成周期检查，并限制上游服务等待时间。解除 deadman 前确认真实转速、温度趋势和保护服务状态。

7. **问题：厂商内核与原版模块的兼容性结论说得过满，但 GRUB 读 NVMe 本身不是写盘风险。**  
   [kernel-provenance.md:12–16](docs/evidence/slice1b/kernel-provenance.md:12) 证明了当前 JetPack 已加载模块组合的实用兼容性，不能证明所有模块、所有路径均兼容。磁盘文件的 `dpkg --verify` 也不直接证明当前已加载模块的来源。  
   **后果：**Arch 额外加载的模块、已知不同的蓝牙模块可能失败；相同 `uname -r` 无法区分两份内核。`modinfo -n` 只显示候选文件，不证明加载成功。  
   **修正：**记录 `uname -v`／完整构建标识、Image 完整哈希、实际已加载模块及 dmesg 的符号／版本错误，禁止强制加载不匹配模块。该条目 [entries-1b.json:36–41](docs/evidence/slice1b/entries-1b.json:36) 的 `root=` 仍指向 USB；GRUB 的 ext2/ext4 驱动只读且忽略 journal，**不会像 Linux 挂载那样回放 journal、更新 atime**。[GRUB 源码说明](https://github.com/rhboot/grub2/blob/master/grub-core/fs/ext2.c)。正常关机可避免它读取未恢复的文件系统状态。

8. **问题：fstab 和 cmdline 基本合理，但不足以证明首次启动没有额外发现和写入。**  
   [install-thor-root.sh:182–188](scripts/install-thor-root.sh:182) 只配置 USB 根分区和持久 journal。machine-id、随机种子、首次启动服务状态、journal 等通常写入 USB 的 `/etc`、`/var`，不会因此去写 NVMe。`systemd-gpt-auto-generator` 在真实 root 阶段主要发现**根文件系统同一物理盘**的分区；不能断言它会扫描并自动使用另一块 NVMe 的 swap。[官方说明](https://github.com/systemd/systemd/blob/main/man/systemd-gpt-auto-generator.xml)。  
   **后果：**仍需排除独立 `.mount/.automount/.swap`、自定义服务等；另外，无 initramfs 配合 `rw` 会让常规 `systemd-fsck-root` 因根已可写而跳过，fstab 的 `0 1` 不保证执行检查。[fsck 单元条件](https://github.com/systemd/systemd/blob/main/units/systemd-fsck-root.service.in)。  
   **修正：**首次测试可给 Arch 条目加 `systemd.gpt_auto=0 rd.systemd.gpt_auto=0`，检查已启用挂载／swap 单元，启动后记录 `findmnt`、`swapon --show` 和 generator 输出。无 initramfs 条目宜用 `ro`，让根检查后再按 fstab 重挂可写；带 mkinitcpio fsck 的条目可保留 `rw`。`firmware_class.path=/etc/firmware` 不排斥默认搜索路径，`audit=1` 本身没有越界写盘问题，可以保留。

9. **问题：FDT 和启动成功的判定需要收紧，避免把不同实验混为一谈。**  
   [thor_boot.py:12](scripts/thor_boot.py:12) 不指定 devicetree，只说明使用 UEFI 交付的树，不证明与 L4TLauncher 路径完全等价。  
   **后果：**删除整个 `/chosen` 后比较，会同时漏掉 initrd 地址、stdout、bootargs 等有意义差异；厂商内核启动成功也不能算 NVIDIA 原版内核通过。  
   **修正：**保留完整原始 FDT，再对已知动态字段做规范化比较；`/chosen` 单独审阅，不整体丢弃。每次记录所选条目、实际根分区、内核构建标识和 cmdline。现有 fallback 数字 `5`、search 失败重启、save_env 成功后才切换 default 均正确，不需要重做。

不建议执行（最小修改：消除 staged 提前发布窗口；补齐或暂时移除 initramfs 失败重启路径；核实早期固件来源与 EFI pstore／efivarfs 写入边界；有人在场验证实际超时回退后再解除 deadman）。
