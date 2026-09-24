1. **问题：没有可靠的无人值守恢复路径。** 后果：`panic=10` 只处理 panic；`rootwait`、驱动卡死、启动成功但 SSH 不通，都可能一直失联。清除 `next_entry` 不会主动触发重启。**修正：今晚不做首次启动实验；待有人能拔 USB 恢复时再测。顺序应先 5、再 4、最后再做一次 5**，先证明默认返回路径，再试新内核路径。

2. **问题：`exit 1` 不保证返回 EFI 错误，当前依据反而表明会返回成功。** GRUB 2.14 的 `grub_exit(void)` 固定传递 `EFI_SUCCESS`；Arch Linux ARM 打包补丁没有加入退出状态支持。后果：edk2 可能进入 Boot Manager 菜单，而不是继续 NVMe；x86 ISO 被跳过不能证明这条路径安全。**修正：撤销“exit 1 会尝试下一启动项”的假设；若依赖该机制，必须使用确实返回 EFI 错误的实现，并验证目标固件行为。** [GRUB 2.14 源码](https://sources.debian.org/src/grub2/2.14-3/grub-core/kern/efi/efi.c/)、[ALARM 打包定义](https://raw.githubusercontent.com/archlinuxarm/PKGBUILDs/master/core/grub/PKGBUILD)、[edk2 返回处理](https://raw.githubusercontent.com/tianocore/edk2/master/MdeModulePkg/Universal/BdsDxe/BdsEntry.c)

3. **问题：`fallback="firmware-next"` 无效，且 `search` 失败后仍继续加载。** 后果：GRUB 的 fallback 解析数字索引；链加载失败后可能回到无倒计时菜单。更严重的是，搜索失败时旧 `root` 可能仍是 USB，随后链加载同路径的 USB GRUB，形成递归。**修正：生成有效数字索引；每个 `search`、`linux`、`initrd`、`chainloader` 都使用显式成功分支，失败立即进入已验证的恢复路径，禁止沿用旧 root。** [GRUB 2.14 菜单实现](https://sources.debian.org/src/grub2/2.14-3/grub-core/normal/menu.c/)

4. **问题：没有检查 `save_env` 成功就启动试验项。** 后果：USB 写失败时，磁盘上的 `next_entry` 仍存在，panic 重启后重复试验。普通 USB FAT 上预分配的有效 grubenv 可以在内核运行前写入；主机端 `grub-editenv` 成功并不证明固件阶段写入成功。**修正：只在 `save_env` 成功后才把 default 切到试验项；失败保持正常入口。限定 `load_env` 只导入 `next_entry`，并先用正常入口验证一次“清除—重启—回读”闭环。** [环境块写入实现](https://raw.githubusercontent.com/rhboot/grub2/master/grub-core/commands/loadenv.c)

5. **问题：“不写 NVMe／UEFI 变量”的边界没有成立。** 后果：`--no-nvram` 与无 efivarfs 只约束安装阶段；`mkdir "$tools/..."`、工具临时文件可能写入 NVMe 上的 chroot，而试验命令行明确以 `rw` 启动 NVMe 根文件系统，正常服务也会写盘。固件自身维护变量也不受 chroot 限制。**修正：工具环境使用 RAM/USB 或只读根加 tmpfs；禁止测试环境变量绕过隔离。若禁令字面包含正常系统写盘，则步骤 4、5 本身不符合要求，不能执行。未发现直接刷写 QSPI 固件的命令，但不能据此承诺全过程零写入。**

6. **问题：自动挂载防护存在时间窗口。** 后果：`not_in_use` 只在早期检查；reload udev 规则不会自动更新既有设备属性，安装脚本也没有防自动挂载措施。格式化前若被挂载，可能破坏 USB 文件系统。**修正：在目标设备上应用规则并 settle，再检查占用；每次破坏性操作前同时复核身份和占用。安装及 arm 阶段持续抑制自动挂载。现有 USB transport、整盘名称和序列号检查能挡住普通 NVMe 误选，但不能消除检查与使用之间的竞争。**

7. **问题：`check_layout` 把对齐输出当作单空格格式。** 后果：`lsblk -ln` 仍可能补齐列宽，`grep -qx "${name}1 RAYTONE_ESP vfat"` 会拒绝正确布局，格式化后停在未安装状态。**修正：使用 `lsblk --json` 或 `--raw --noheadings` 解析字段，并核验分区父设备、分区类型和挂载源；不要通过删除检查来绕过失败。**

8. **问题：ESP 安装没有完整的提交与持久化验收。** 后果：EFI 文件先出现、配置随后写入，中途失败会留下固件愿意启动但无法正常工作的 USB；“存在任意 `.mod`”也不能证明模块齐全。**修正：先准备并检查配置、环境块、必要模块和 AArch64 EFI 文件，最后发布 removable 启动文件；显式同步、正常卸载、只读重挂后核对内容与 FAT 状态。任何失败都不得接着 reboot。**

9. **问题：链加载与 DT 等价性尚未经过目标版本验证。** 原理上 GRUB 会设置被加载映像的设备句柄，L4TLauncher 据此寻找同盘 APP，因此从 NVMe ESP 链加载具有合理依据；但这不是 R39.2.1 实测保证，`BootCurrent` 也仍可能是 USB。没有 `FDT` 行不能单独证明绕过 L4TLauncher 后 DT 完全相同。**修正：有人值守时先验证默认链加载，再验证直接启动及 DT；不要为此把 L4TLauncher 复制到 USB，改变其设备定位上下文。** [GRUB 链加载实现](https://raw.githubusercontent.com/rhboot/grub2/master/grub-core/loader/efi/chainloader.c)、[NVIDIA 当前源码，非目标版本证明](https://github.com/NVIDIA/edk2-nvidia/blob/main/Silicon/NVIDIA/Application/L4TLauncher/L4TLauncher.c)

10. **问题：配置生成器未验证所有实际渲染字段。** 后果：JSON 的标题、ID、路径、UUID、cmdline 可引入语法错误；`cmdline()` 的检查并未应用到 JSON 渲染路径。**修正：统一字段验证和转义，运行 `grub-script-check` 并检查实际文件。`timeout=3` 本身不需要键盘；常见 “Press any key” 路径有约 10 秒上限，真正危险的是其后进入无超时菜单或配置缺失导致提示符。** [GRUB 2.14 超时实现](https://sources.debian.org/src/grub2/2.14-3/grub-core/normal/menu.c/)

不建议执行（最小改动：今晚取消 arm-once 和 reboot；修复回退与清除失败处理后，待有人可现场恢复时先验证步骤 5）。
