**结论：L4T 二进制重打包适合作为 v1；USB GRUB + 固件 DT 也是合理路线。但当前计划还不能保证“拔盘即恢复”，Gate 0 也只能验证部分图形兼容性。**以下按严重程度排序。实机数据按你提供的事实接受；我未连接设备，也未检查实际 `.deb` 内容，涉及其内部行为的地方明确保留不确定性。

1. **必须把“禁止固件更新”落实到包、服务和写入接口。**  
   **问题：**“不执行 maintainer scripts”不等于不会更新固件；解出的服务、启动脚本、payload 同样可能在首次启动时执行。  
   **失败场景：**USB 系统启动后运行 bootloader 配置、capsule 更新或槽位管理，改变共享 QSPI／UEFI 状态；拔盘无法撤销。  
   **具体修正：**禁止引入 `nvidia-l4t-bootloader`、`nvidia-l4t-kernel-partitions` 的更新内容；逐项审查 bootloader-utils，禁止启用 `nv-l4t-bootloader-config.service`、自动刷写／firstboot／OTA 服务。禁止 capsule 投递、`nvbootctrl` 写操作、`efibootmgr` 写操作及自动 `bootctl install/update`；不向构建环境暴露可写 efivarfs、MTD 和内部块设备。GRUB 显式使用 `--removable --no-nvram`，ESP 和 boot-directory 都指向 USB。不能承诺固件自身绝不更新变量，应承诺“项目不主动写入”，并记录启动前后状态。[NVIDIA 更新机制](https://docs.nvidia.com/jetson/archives/r39.2.1/DeveloperGuide/SD/Bootloader/UpdateAndRedundancy.html)

2. **Gate 0 并非“只动 `~/raytone`”，chroot 也不是硬件隔离。**  
   **问题：**停止 GDM 会终止桌面会话；chroot 与 JetPack 共用内核、GPU、设备和通常的网络命名空间。  
   **失败场景：**包 hook 对宿主执行 `modprobe`、防火墙操作；绑定宿主 `/run` 后误连其 systemd／D-Bus；图形探针令驱动卡死，GDM 无法恢复。  
   **具体修正：**构建阶段与硬件探针分开：私有挂载传播、独立 `/run`，不整体绑定宿主 `/run`，不运行完整 Omarchy 安装器，不卸载／替换宿主驱动。硬件阶段只放行必要设备与明确选择的 seat 接口。停止 GDM 前保存工作，验证 SSH 和串口；由**宿主**设置超时恢复及退出清理。驱动挂死可能仍需重启，不能称为无影响探针。

3. **“同为 R39.2.1”不足以保证内核、OOT、OpenRM 二进制匹配。**  
   **问题：**尚未证明仓库中拟下载的内核包，就是实机 `6.8.12-1021-tegra` 的来源；仅按包名前缀分组危险。  
   **失败场景：**Ubuntu ABI 内核与另一构建的 L4T 模块混装，出现 `invalid module format`、符号 CRC 不匹配，或加载到错误的同名 `nvidia.ko`。  
   **具体修正：**用 `dpkg-query -S`、`apt-cache policy` 和 `modinfo -n/-F vermagic` 建立实机文件→包版本→仓库映射；锁定 Image、内核配置、基础模块、OOT、OpenRM、固件及用户态驱动的完整组合。保留模块目录和 depmod override 语义，目标安装时运行 `depmod -b "$root" "$kernel_release"`，不能省略 release 而使用构建宿主的 `uname -r`。R39 的 variant 服务还负责模块选择和 depmod 配置，不能简化成几个 `modprobe`。[官方服务说明](https://docs.nvidia.com/jetson/archives/r39.2.1/DeveloperGuide/SD/Kernel/DisplayConfigurationAndBringUp/NvLoadDisplayModulesService.html)

4. **GRUB 不写 `devicetree` 可以成立，但不能把 L4TLauncher 的行为直接等同于 GRUB。**  
   **问题：**EFI stub 可以接收固件 DT；GRUB 却不会自动执行 extlinux 的 `APPEND ${cbootargs}`、FDTOVERLAYS 等逻辑。实际 R39.2.1 固件与所选 Arch GRUB 的 DT 交接仍需验证。  
   **失败场景：**Image 启动成功，但缺少平台参数、保留内存信息或必要 DT 修正，随后显示／USB／电源初始化失败。  
   **具体修正：**先保存 `/proc/cmdline`、extlinux 配置和运行时 DT。以**实机展开后的 cmdline**为基线：替换全部旧 `root=` 为 USB 标识，保留 `rootwait rootfstype=ext4`；保留实际串口 `console=`、`firmware_class.path=/etc/firmware`。若实机存在 `clk_ignore_unused`、`pd_ignore_unused`、`efi=runtime`、平台/IOMMU/显示参数及 nouveau 禁用项，首轮先保留，再逐项验证能否删；不要凭示例补入不存在的参数。移除旧 `resume=`、安装器参数，明确 `ro/rw` 策略。**缺少完整 cmdline，无法给出可信的全部必需参数清单。**  
   官方已有不带 `devicetree` 的 GRUB 路径，因此可以首选 GRUB；匹配版本的 L4TLauncher+extlinux 可作对照，但必须验证它实际选择 USB 文件系统，没有回退读取 NVMe。[NVIDIA GRUB 支持](https://docs.nvidia.com/jetson/archives/r39.2.1/DeveloperGuide/SD/Bootloader/UEFI.html#grub-support)

5. **“三个驱动内建，因此不需要 initramfs”证据不足。**  
   **问题：**还缺 SCSI 磁盘、PHY、供电、控制器固件等完整依赖链；当前由 `usb-storage` 工作，也不代表换桥接器后不会需要 `uas`。  
   **失败场景：**UEFI 能读取 Image，Linux 接管 USB 后丢盘；或者用 `root=UUID=…`，却没有 initramfs 用户态解析文件系统 UUID。  
   **具体修正：**v1 建议提供针对该内核生成的最小 initramfs，包含 USB 根盘所需模块、固件和发现根盘逻辑；`/etc/firmware` 中的早期固件也要纳入。坚持无 initramfs 时使用 `root=PARTUUID=… rootwait`，逐项证明完整依赖内建，并通过断电冷启动验证，不能用 chroot 结果替代。

6. **重打包方向正确，但 v1 不宜同时重构 NVIDIA 库目录。**  
   **问题：**移动到 `/usr/lib/nvidia-l4t` 会增加与二进制兼容性无关的变量。`ld.so.conf` 不能修复脚本、JSON、GBM 插件搜索路径、绝对软链接、CSV/CDI 中的旧路径。  
   **失败场景：**`nv-load-gpu-libs.service` 又创建另一套链接；EGL 加载正确而 GBM 后端找不到；Vulkan loader 或 GLVND 被 vendor 同名库抢占。  
   **具体修正：**首版优先保留 `/usr/lib/aarch64-linux-gnu/nvidia`、`/opt/nvidia/l4t-gpu-libs/openrm` 的 vendor 布局，补充必要搜索配置；实际链接关系需读 `.deb` 和服务脚本，**目前不确定**。明确每个文件归属：Arch 提供 GLVND dispatcher、Vulkan loader，以及选定的 `libgbm`；L4T 提供 vendor 实现和后端，避免重复安装通用 loader。每种 egl-wayland／egl-gbm 实现只启用一套对应注册项。将 Debian `/lib`、`/usr/lib` 布局转换为 Arch 的 merged-/usr 规则，保留 SONAME 链接；检查 `DT_NEEDED`、实际进程映射和 JSON 加载路径。读取 maintainer scripts 后，以白名单方式重现必要的链接、ldconfig、udev 和 tmpfiles 行为。

7. **`card3` + kmscube 不能充分证明 Hyprland 可用，失败也不能直接归因于驱动。**  
   **问题：**`nv_platform` 显示节点和 NVIDIA 渲染节点的关系尚未证明；编号不稳定。kmscube 的默认路径也不一定覆盖 Hyprland 使用的 atomic KMS、modifier 和跨设备导入路径。  
   **失败场景：**强制只用 `card3` 丢失渲染设备；或者 cube 可见，但 Hyprland 在 dma-buf 导入、同步、鼠标平面或客户端呈现时失败。  
   **具体修正：**顺序改为：JetPack 原生基线 → DRM/sysfs/connector/render-node 映射及权限检查 → chroot 中无显示占用的 EGLDevice／surfaceless、Vulkan 查询 → 停 GDM → KMS 测试图 → GBM/EGL kmscube（另测 atomic 路径）→ 最小配置 Hyprland → 原生 Wayland、Xwayland、Quickshell、锁屏及热插拔。使用稳定设备链接；`AQ_DRM_DEVICES` 是否需要多个节点根据拓扑决定。显式配置 libseat/logind 或 seatd、VT、私有 D-Bus、`XDG_RUNTIME_DIR`，排除权限假阴性。  
   egl-wayland 版本影响客户端路径；升级它不能替代 compositor／DRM syncobj 能力验证。截图不证明物理 scanout，更不证明 explicit sync。EGLStream Weston 是另一条诊断或降级路线，不能算 Omarchy 验收通过。[Hyprland 设备选择](https://wiki.hypr.land/0.54.0/Configuring/Multi-GPU/)；[NVIDIA Wayland 平台库要求](https://github.com/NVIDIA/egl-wayland2)

8. **散热服务“带上”还不够，必须验证板级配置及失败行为。**  
   **问题：**`nvfancontrol`、`nvpmodel` 依赖配置、传感器、sysfs 和执行顺序；120W 是当前状态，不应直接成为未验收系统的负载目标。  
   **失败场景：**服务显示 active，却使用错误风扇配置；功耗模式切换失败或要求重启；编译、CUDA 压测时持续降频或过热关机。  
   **具体修正：**随包携带匹配 T5000 的配置、链接和运行目录，先选该板支持的保守模式，验证转速随温度响应、功耗限制及持续负载温度。逐个确认 `nvpower`、`nvcpupowerfix` 的实际作用，不能凭名字照搬。v1 在 **Arch 内**禁用自动 suspend、hibernate、hybrid-sleep 和 suspend-then-hibernate，并移除 Omarchy 对应入口；待 USB 根盘和显示恢复专项通过后再开放。这是验收策略，不是断言 Thor 不支持休眠。

9. **USB 写盘防护和“最坏恢复”描述仍有漏洞。**  
   **问题：**`by-id/usb-*` 加“未挂载”不能覆盖 swap、dm/LVM/RAID holder、子分区占用和检查后换盘；重新分区也可能使现有 Boot0004 的设备路径失效。  
   **失败场景：**误清除正在使用的设备，或新盘无法自动启动；把 Jetson ISO 当作无损修复工具，安装过程反而覆盖 NVMe／升级固件。  
   **具体修正：**解析真实设备，核对 `TYPE=disk`、USB 拓扑、序列号、容量、major:minor，以及所有后代挂载、swap、holders；每次破坏性步骤前复核身份，关闭相关自动挂载。验证重新分区后的 removable-path 启动，不仅看旧 BootOrder。USB 系统不配置内部盘自动挂载。验收必须包含断电启动、拔盘返回 JetPack。Mac `dd` 只是制作安装介质；ISO 安装和 `l4t_initrd_flash.sh` 都属于另行授权的恢复动作。R39.2.x 固件也不能随便使用旧 ISO。[固件／ISO 兼容表](https://docs.nvidia.com/jetson/agx-thor-devkit/user-guide/0.1.0/twa_uefi_iso_compatibility.html)

10. **桌面可用性的外设验收不足，不能把全部音频需求推给“后期多媒体”。**  
    **问题：**驱动存在不代表 firmware、ALSA 路由、UCM、蓝牙配置和用户态服务齐全。  
    **失败场景：**HDMI 有画面无声音、BT 能枚举不能连接、Wi-Fi 冷启动缺固件、网络接口重命名导致 SSH 失联。  
    **具体修正：**从实机提取各驱动实际请求的 firmware 名称及加载日志，覆盖 `rtw89`、`rtk_btusb` 和 NVIDIA 固件路径；保留所需压缩格式支持。加入 ALSA UCM／板级配置、PipeWire、WirePlumber、BlueZ，验证 HDMI/DP 音频、USB 音频和所需麦克风路径。网络按 MAC/稳定身份配置，检查 `r8125` 与其他候选驱动绑定冲突。Gate 0 会继承宿主已加载的固件，因此这些必须在 USB 冷启动后重新验收。

11. **CUDA 选择基本合理；Docker 的“CSV/CDI 模式”必须具体化。**  
    **问题：**CSV 是发现／注入相关机制，CDI 是设备描述与消费接口，不能用斜杠略过接线。移动库路径后直接复制 CSV 尤其危险。  
    **失败场景：**主机 CUDA 正常，容器拿不到正确库或设备；传统 runtime hook 与 CDI 重复注入；Ollama 安装成功但退回 CPU。  
    **具体修正：**明确选择并验证一条 Docker 注入路径；在 USB 系统中、驱动和库链接初始化后生成 CDI，检查 spec 内所有 hostPath 和设备，再从实际容器执行 smoke。检查 cgroup、overlayfs、bridge/netfilter 的内核配置。SBSA CUDA 13.2、GCC15 和 `sm_110` 的方向有官方依据，但 Spark 的 CUDA 13.0 glibc 补丁不能机械复用；显式指定 host compiler，保证 stub 库不进入运行时搜索路径。Ollama 还要核实其实际 vendored backend 接收该架构参数，并以加载日志、正确结果及 GPU 运行证据验收。[CUDA 编译器支持](https://docs.nvidia.com/cuda/archive/13.2.0/pdf/CUDA_Installation_Guide_Linux.pdf)；[CDI 生成机制](https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/latest/cdi-support.html)

12. **参考项目并非可原样移植的构建和桌面基线。**  
    **问题：**实读 `scripts/clean-build.sh`：它依赖 Docker、使用浮动 `latest` 镜像，并在单包失败后继续，最终输出 DONE 不保证整体失败退出；这与“不装 Docker”的方案不一致。`omarchy-settings` 清空 checksum 的问题确实存在。  
    **失败场景：**得到不完整仓库仍继续部署；通用 ARM 包夹带 Spark 依赖；后续 Omarchy 更新重新安装桌面 NVIDIA 驱动或写入启动配置。  
    **具体修正：**只复用其本地仓库思路，重写成非特权 builder 的隔离 chroot 流程；固定 rootfs、源码和包版本，任一必需包失败即非零退出。Thor 分支应在 NVIDIA 安装逻辑入口明确匹配后结束，覆盖升级／refresh 路径。锁定并共同验证 Hyprland、Aquamarine、Quickshell、配置及兼容包；替换 Omarchy 仓库时保留 Thor 本地仓库。即使 v1 不做完整升级回滚，也要冻结 BSP 栈、保留已知可启动产物，避免滚动升级把唯一可用组合拆散。
