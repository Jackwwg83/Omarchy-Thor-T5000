# RaytoneOS · Omarchy Thor T5000 版：架构与实施计划

## Context

在 RaytoneOS 下做一个版本：外观和使用体验就是 Omarchy（Hyprland + Quickshell），底座是 Arch Linux ARM，
跑在 Jetson AGX Thor 开发套件（T5000）上。参考 omarchy-spark（DGX Spark 的 Arch + Omarchy 移植），
但 Thor 和 Spark 不是同一个平台，内核、驱动、启动都要换成 Jetson 那一套。桌面层可以大量复用 omarchy-spark 的 ARM 适配。

已确认的约束：
- v1 装在外接 USB 盘（JZAO 231G，**已授权格式化**），JetPack 留在机身 NVMe 上原封不动，拔盘就回 JetPack
- 需要时可临时准备 x86 Linux 主机用于救砖
- v1 范围：Omarchy 桌面 + CUDA 开发环境 + Docker GPU 容器 + Ollama
- 关键动作前先和 Codex 商量
- 本方案已经过 Codex（12 条意见）和 Plan agent（15 条意见）两轮对抗审查

### 实机摸底（2026-09-24，测试机，只读）

| 项 | 实测 |
|---|---|
| 系统 | JetPack 7.2.1，L4T R39.2.1，Ubuntu 24.04.4，内核 `6.8.12-1021-tegra`（OOT 变体），4K 页 |
| 启动 | UEFI（QSPI）→ NVMe ESP 上的 `EFI/BOOT/BOOTAA64.efi`（L4TLauncher）→ `/boot/extlinux/extlinux.conf`；没有 FDT 行；无 ACPI |
| BootOrder | `0004`（USB，auto_created）→ `0001`（NVMe）→ Setup / Shell |
| 实际 cmdline | `rw rootwait rootfstype=ext4 mminit_loglevel=4 earlycon=tegra_utc,mmio32,0xc5a0000 console=ttyUTC0,115200 firmware_class.path=/etc/firmware fbcon=map:0 efi=runtime audit=1 audit_backlog_limit=8192 swiotlb=2048 video=efifb:off console=tty0`，外加 `root=PARTUUID=…` 和引导器注入的 `bl_prof_*` |
| GPU | `10de:2b00` "NVIDIA Thor"，OpenRM 595.78（与桌面版 open-gpu-kernel-modules 同源），nvidia-smi 正常，CUDA 13.2.2 |
| 显示 | `card3` = nv_platform（tegra264-display）承载接口，HDMI-A-1 接的是 2560×1440；`card2` = nvidia；`card1` = host1x；有 `nvidia-drm_gbm.so`；egl-gbm 1.1.0，egl-wayland 1.1.11 |
| 桌面 | GDM + GNOME Xorg |
| 内核配置 | `USB_XHCI_TEGRA` / `USB_STORAGE` / `EXT4` 内建；`NVME`、`UAS`、`DRM_TEGRA` 是模块 |
| 外设 | Wi-Fi RTL8852BE（rtw89），2.5GbE r8125，MGBE nvethernet（OOT），BT rtk_btusb，tegra-hda / APE 音频，板载调试串口 |
| NVIDIA 服务 | nvfancontrol、nvpmodel（120W）、nv-load-display-modules、nv-load-gpu-libs、nvpower、nvcpupowerfix、nvidia-cdi-refresh、nv-l4t-bootloader-config、nvfb-* 等约 30 个 |
| 容器 | nvidia-container-toolkit 1.19.1（CSV 模式 + CDI）；没装 docker |
| U 盘 | JZAO USB3.2 Gen1 231G，接在 A 口，实测 **5000M**（Type-C 口不认盘，与 NVIDIA 已知问题 5251623 一致） |
| sudo | 已设临时免密 `/etc/sudoers.d/raytone-temp`（验证通过） |

## 架构决策

1. **底层：直接用 NVIDIA L4T R39.2.1 的二进制，重新打成 Arch 包，v1 不自己编内核。**
   只有这一套栈能驱动 Thor 的 GPU 和显示，主线内核目前没有 Thor 的 GPU/显示支持。
   - 手法沿用 omarchy-spark `packages/cuda-dgx-spark/PKGBUILD:256-263`：bsdtar 解出 .deb 里的 data.tar
   - 路径改写：`/lib`、`/bin`、`/sbin`、`/usr/sbin` 转成 Arch 的 merged-/usr 布局；systemd unit 挪到 `/usr/lib/systemd/system`
   - 来源：`repo.download.nvidia.com/jetson/{common,som}` r39.2，版本和 sha256 锁定到 `manifests/l4t-r39.2.1.json`
   - **组合锁定要有证据**：用 `dpkg-query -S`、`apt-cache policy`、`modinfo -F vermagic` 从实机建立"文件 → 包 → 版本"映射
   - **maintainer 脚本台账**：逐个读 JetPack 上的 `/var/lib/dpkg/info/nvidia-l4t-*.{preinst,postinst,triggers}`，写进 `manifests/l4t-maintainer-ledger.md`。
     每条都要落实成 PKGBUILD 步骤、install 脚本，或者明确排除。典型的有：nvpmodel / nvfancontrol 的板级配置链接、
     `/dev/nvidia*` 和 nvmap 的 udev 权限、ld.so 配置、`/etc/nv_tegra_release`
   - `nv-load-gpu-libs` 的结果（OpenRM 那套库）直接固化进包；显示模块加载完整移植 variant 选择逻辑
   - `depmod.d` / `modprobe.d` 原样复制 JetPack 的（包括 `updates/opensource-gpu-disp` 的 override 和 nvgpu 黑名单）；
     目标安装时执行 `depmod -b "$root" 6.8.12-1021-tegra`
   - 包名统一加 `raytone-thor-` 前缀，避免和 AUR 撞名、被 yay "升级"掉：`raytone-thor-linux`（Image + 模块 + OOT + OpenRM + 头文件）、
     `-firmware`、`-core`、`-graphics`、`-cuda`。graphics 包声明 `provides=(nvidia-utils=595.78 opengl-driver vulkan-driver)` 和
     `conflicts=(nvidia-utils nvidia-open-dkms)`，防止 Arch 的 610 驱动被装进来
   - **库布局保持 NVIDIA 原样**（`/usr/lib/aarch64-linux-gnu/nvidia`、`/opt/nvidia/l4t-gpu-libs/openrm`），因为二进制里有写死的路径，
     容器 CSV 和 NGC 镜像也都依赖这些位置。**用白名单**控制 ld.so 搜索：不允许 L4T 自带的 libgbm、libEGL（glvnd）、libwayland、
     libdrm、libvulkan 盖掉 Arch 的版本。另外补一个 `/usr/lib/gbm/nvidia-drm_gbm.so` 链接
2. **启动：只写 U 盘。**
   - GPT 两个分区：`RAYTONE_ESP`（512M）+ `RAYTONE_ROOT`（ext4）。分区名刻意不用 `esp` / `APP`，免得和 NVIDIA 的查找逻辑混淆
   - GRUB 安装：`grub-install --target=arm64-efi --removable --no-nvram`。**任何 chroot 里 efivars 都只读挂载**
   - `grub.cfg` 由我们的包持有，内容固定，不让 grub-mkconfig 或 mkinitcpio 自动生成；不使用 GRUB 的 `devicetree` 命令，
     因为它会跳过 UEFI 的 overlay 步骤
   - 启动菜单：Arch、JetPack（chainload NVMe 上的 `EFI/BOOT/BOOTAA64.efi`，不拔盘也能回 JetPack）、UEFI 设置
   - cmdline 用实测 cmdline 逐字复制，只把 root 换成 U 盘的 `PARTUUID`。`bl_prof_*` 两位审查者意见相反，用 Slice 1a 实验决定
   - 最小 initramfs（mkinitcpio）：xhci-tegra、phy-tegra-xusb、typec / ucsi_ccg、i2c-tegra、usb-storage、uas、sd_mod、ext4，外加 `/etc/firmware` 里的早期固件
   - rootfs 里 ALARM 自带的 `linux-aarch64` 要卸掉，并在 pacman.conf 里 `IgnorePkg`
3. **桌面层从 omarchy-spark 搬。**
   - `packages/omarchy`、`packages/omarchy-settings` 和 `omarchy-spark-arm.patch` 里通用 ARM 的 hunk
   - Thor 分支：用 `/proc/device-tree/compatible` 里的 `nvidia,tegra264` 识别，在 NVIDIA 安装逻辑入口就结束（Thor 的 GPU 在 lspci 里能看到，
     不拦的话上游会去装 nvidia-open-dkms）。refresh 和升级路径同样要拦住
   - 覆盖 `nvidia.lua` 为桌面卡设的 VA-API 变量，并在这里设 `AQ_DRM_DEVICES`（用 udev 生成的、不带冒号的稳定链接）
   - SDDM 登录界面以 sddm 用户身份运行 Hyprland，需要前面台账里那套设备权限
   - v1 不用 Plymouth 启动动画；隐藏 Suspend 菜单项
   - `omarchy-refresh-pacman` 会覆盖 pacman.conf：把本地仓库和 `IgnorePkg` 写进 aarch64 模板
   - 修 `omarchy-settings/PKGBUILD:122-126` 的 checksum 清空 bug；16 个 A 类包原样复制，保留来源和许可声明
4. **AI 层**
   - CUDA 13.2.2 SBSA toolkit：按 cuda-dgx-spark 的手法重新锁版本；13.0 那个 glibc 补丁不照搬
   - `libcuda` 来自 L4T 的 cuda-openrm；主机编译器显式指定 gcc15；stub 库不进入运行时搜索路径
   - Ollama：用 `CMAKE_CUDA_ARCHITECTURES=110`，并核实它自带的 backend 真的收到了这个参数
   - Docker：在 Arch 上执行 `nvidia-ctk cdi generate`，检查 spec 里每个路径都存在，只走 CDI 一条注入路径；同时检查内核的 cgroup / overlayfs / netfilter 配置
   - 规避已知问题 5699079（超大 CUDA 分配可能导致整机重启）：给 ollama 和 docker 设 OOM 分数
5. **构建全在 Thor 本机完成。**
   - NVMe 上一个目录里的隔离 chroot：私有挂载传播、独立的 `/run`、efivars 只读、非特权 builder 用户
   - rootfs tarball 锁定 hash；任何必需包构建失败就非零退出
   - omarchy-spark 的 `clean-build.sh` 只借鉴本地仓库思路，要重写（原脚本依赖 Docker、用浮动的 latest 镜像、失败了还继续跑）
   - Mac 上的 `~/Projects/RaytoneOS` 是唯一源码，rsync 同步到 Thor 的 `~/raytone`

## 硬性禁止清单（防变砖，写进代码和测试）

- **包内容扫描测试**：检查每个构建出的包的文件列表，出现以下任何一项就测试失败：
  `nvidia-l4t-bootloader*`、`nvidia-l4t-kernel-partitions`、`nvbootctrl`、`nv_update_engine`、`nv_update_verifier`、
  `nv-l4t-bootloader-config`、`nvfb-*`、`nv-oobe`、firstboot、`*.Cap`、`UpdateCapsule`、fwupd
- **不执行**：capsule 投递、nvbootctrl 写操作、efibootmgr 写操作、`bootctl install/update`、任何 QSPI/MTD 写入。U 盘系统不自动挂载 NVMe
- **JetPack 侧**：v1 期间执行 `apt-mark hold nvidia-l4t-bootloader 'nvidia-l4t-kernel*'`（可撤销）。
  否则 JetPack 那边一次 `apt upgrade` 就可能把 QSPI 固件升到新版本，而新 UEFI 可能不再兼容我们冻结的 R39.2.1 内核
- **证据**：每次启动实验前后保存 `efibootmgr -v`、`nvbootctrl dump-slots-info`（只读）和 UEFI 固件版本做对比；
  Arch 开机时检测到固件版本变化就告警。能承诺的是"项目不主动写入"

## 实施阶段（纵切推进，前一步有真实证据才开下一步）

**Phase 0（最小化）**：在 Mac 上 `git init` RaytoneOS，建目录 `omarchy-thor-t5000/{packages,patches,scripts,manifests,tests,docs}`，
写入 `docs/THOR-INVENTORY.md`（摸底结果脱敏）和 `docs/DECISIONS.md`（记录每次会商），提交一次。
其余导入工作等 Gate 0 通过后再做：它们消除不了任何风险。

**Gate 0a：无打扰探针**（gdm 照常运行）
- 解开 Arch ARM rootfs 建 chroot，**把宿主的 L4T 库目录只读 bind 进去**。这一步先不重打包，看的是 Arch 用户态 + L4T 库能不能配合
- `drm_info` 查清楚：哪个 card 带接口、驱动名、支持的格式和 modifier、显示设备和渲染 GPU 是不是分开的（Orin 就是在这里失败的）
- `eglinfo -B -p gbm`、`vulkaninfo --summary`、nvidia_drm 的 modeset 参数；查清 GDM 为什么走 Xorg
- 同时导出"文件 → 包"映射和 maintainer 脚本台账（只读）

**Gate 0b：上屏探针**（执行前先和 Codex 会商）
- 准备：确认 SSH 和串口都可用；执行 `apt-mark hold`；设死人开关 `systemd-run --on-active=10min systemctl start gdm`。
  驱动卡死可能需要重启，这一点事先说明
- 停 gdm → `modetest` 输出测试图 → kmscube（GBM + atomic）→ Hyprland
  - Hyprland 以普通用户身份运行，`seatd -g video` 以 root 运行
  - bind 进 `/dev`、`/proc`、`/sys`，`/run/udev` 只读
  - 用的 Hyprland / aquamarine 版本与 Slice 2 完全一致
- egl-wayland 两个版本都测（L4T 的 1.1.11 和 Arch 的新版），看 explicit sync
- 客户端：foot、ghostty、GTK4 应用、quickshell、Chromium（Wayland，看 `chrome://gpu`）、Xwayland 下的 glxinfo、`vkcube --wsi wayland`
- 行为：熄屏再唤醒、HDMI 拔插、切换 VT
- 证据：
  - `AQ_TRACE=1 HYPRLAND_TRACE=1` 下的日志、dmesg 里的 NVRM/Xid 行
  - `/proc/$pid/maps` 里实际加载的 libEGL / libgbm / nvidia 库
  - **你肉眼确认屏幕上真的出了画面**（截图证明不了物理扫描输出）
- 写明 Gate 0 证明不了什么：启动流程、设备树、模块选择、logind/SDDM
- **不通过**：停下来汇报根因和选项（调环境变量 / 换胶水层版本 / 等 NVIDIA 修复 / 改走 X11 桌面），由你决定。EGLStream 版 Weston 只能用来诊断，不算通过

**Phase 0b**：导入 omarchy-spark 的 A 类包、`fetch-sources.py`、`audit-*.py`、测试框架（每批不超过 5 个文件，各自 commit）

**Slice 1a：U 盘上的 GRUB 启动 JetPack 自己的系统**（执行 make-thor-usb 和首次启动前各会商一次）
- `scripts/make-thor-usb.sh`（先写测试）
  - 身份校验：`TRAN=usb`、`TYPE=disk`、序列号、容量上下限、major:minor
  - 拒绝：承载 `/` 的盘、有挂载 / swap / holder 的盘
  - 默认 dry-run；每个破坏性步骤前重新校验；必须手动输入序列号确认；执行期间关闭自动挂载；写完再核对分区名
- GRUB 加载 NVMe 上 JetPack 的 Image、initrd 和 rootfs
- 验收：`/sys/firmware/fdt` 的 sha256 与正常启动时一致；`/proc/cmdline` 对比一致（`bl_prof_*` 在这里定）；GPU 和显示正常；
  `efibootmgr -v` 前后一致；U 盘上的 chainload 菜单能回到 JetPack

**Slice 1b：Arch 从 U 盘启动到命令行**
- 新包 `raytone-thor-linux` / `-firmware` / `-core`；移植必要的 NVIDIA 服务
  - 风扇和功耗：带上 T5000 的板级配置，**先用保守的功耗模式**，确认风扇转速随温度变化
  - nvpower、nvcpupowerfix 先读懂再决定
- 系统设置：屏蔽 sleep / hibernate 相关 target（已知问题 5525468）；开 timesyncd，保证时间同步早于 pacman 验签；网络按 MAC 配置
- 验收（全部在**断电冷启动**后）：
  - SSH 登录，贴出 `uname -r`、`modinfo -n nvidia nvidia_drm`（路径与 JetPack 一致）、`nvidia-smi`、`nvpmodel -q`、风扇转速、温度
  - Wi-Fi 和有线网通；按日志核对每个驱动要求的固件都已加载
  - `efibootmgr -v` 前后一致
  - 拔掉 U 盘能回到 JetPack

**Slice 2：Omarchy 桌面**（执行 omarchy-apply-system 前先会商）
- omarchy 相关包 + `raytone-thor-graphics`，然后 `omarchy-apply-system --first-install`
- 音频：PipeWire、WirePlumber；默认输出设为 HDMI，隐藏 APE 那一堆 PCM 设备
- 蓝牙：BlueZ，注意 rtk_btusb 的固件和 Arch `linux-firmware-realtek` 里的重名文件
- v1 只支持 HDMI（已知问题 6241469：USB-C 输出 DP 可能导致内核崩溃）
- 验收：你肉眼确认 SDDM → Hyprland + Quickshell；截图；`hyprctl monitors` 显示 2560×1440；GL renderer = NVIDIA Thor；
  锁屏、防火墙、HDMI 出声、蓝牙能配对、显示器热插拔

**Slice 3：AI 能力（依次推进）**
- CUDA：`tests/cuda-smoke.cu` 改为 sm_110，本机编译运行，统一内存校验通过
- Docker GPU：容器里跑同一个 smoke 程序
- Ollama：看加载日志、结果是否正确、GPU 利用率、tokens/s；持续负载下观察温度和降频

**v1 不做**：NVMe 安装和安装器 ISO、托管 pacman 仓库、完整的升级回滚、摄像头和多媒体编解码、QSFP 25G、MIG、
Secure Boot、固件更新、USB 设备模式救援网络（以后可作为 SSH 救援通道）。
冻结 BSP 组合：本项目的包只随项目一起升级；保留一份已知能启动的产物。

**粗略工作量**（取决于 Gate 0 的结果）：Gate 0 约半天到一天；Slice 1a+1b 约 1–3 天，启动调试的变数最大；Slice 2 约 1–2 天；Slice 3 约 1–2 天。

## 测试与证据
- TDD 的重点是**包内容的静态测试**：
  - 禁止清单扫描
  - 没有文件放在被符号链接的目录下
  - 不和 Arch 的包重叠文件
  - DT_NEEDED 在目标 root 内都能解析
  - glvnd / EGL platform / Vulkan ICD 的 JSON 都指向真实存在的文件
  - ld.so 白名单
- 其次是脚本的 unittest（用 stub 替代特权命令），沿用 omarchy-spark `tests/test_install_scripts.py` 的写法：
  make-thor-usb 的各种拒绝情形、`grub-install` 一定带 `--removable --no-nvram`、nvidia.sh 的 Thor 分支
- 硬件探针 `tests/check-*.sh` 在 Thor 上跑，不进 CI
- 每次汇报都标明各组件的状态：代码实现 / 部署路径 / 真实数据 / mock-empty

## Codex 会商点
统一用本机 `codex exec -s read-only`，意见和我的处理写进 `docs/DECISIONS.md`；和我有分歧时停下来交给你决定。
1. ✅ 方案本身（Codex 和 Plan agent 已审，两处分歧改用实验定：`bl_prof_*` 在 Slice 1a 测，egl-wayland 两版在 Gate 0b 都测）
2. Gate 0b 执行前（停 gdm、`apt-mark hold`）
3. make-thor-usb.sh 第一次格式化 U 盘前（脚本和测试一起给它看）
4. 启动配置（grub.cfg、cmdline、initramfs），首次从 U 盘启动前
5. 移植 NVIDIA 服务（风扇、功耗、显示模块加载）前
6. 在 U 盘系统上执行 omarchy-apply-system 前
7. 每个 Slice 宣布"通过"前：用 `/codex:review` 审 diff 和证据

## 安全与回滚
- 常规回滚：拔掉 U 盘，或者在 U 盘的 GRUB 菜单里选 JetPack
- 救砖：与 R39.2.x 固件匹配的 Jetson ISO（从 Mac 用 dd 写盘），或 x86 主机执行 `l4t_initrd_flash.sh`。两者都会覆盖 NVMe 甚至固件，**要单独授权**
- 显示黑屏时：调试口接 Mac，`screen /dev/tty.usbmodem* 115200` 看串口日志
- 项目结束时：删除 `/etc/sudoers.d/raytone-temp`，撤销 `apt-mark hold`
- 许可：只发布源码，recipe 在构建时从 NVIDIA 官方源下载并校验 hash
