# Codex review round 3: Slice 1b boot fixes (2026-09-25)

`codex exec -s read-only` over `git diff 71f8d5c..5504a7c`. Final answer, verbatim:

只读审查完成。**第二轮的失败安装发布问题已解决，EFI 早期写入问题已针对已知路径修复；thermal guard 仍有阻塞缺口，prefix 检查新增了可复现的误拒绝。** 未发现本轮新增直接写 QSPI、NVMe 分区表／ESP或 JetPack 启动配置的代码路径，但不能把 MASKED 列表视为完整的 TPM 写入隔离。

1. **问题：最后一级强制重启仍可能阻塞保护循环。**  
   [thermal-guard:25](scripts/thor-rootfs/thermal-guard:25) 没有 timeout，和“所有外部命令都有硬上限”的描述不符。systemd 261 的双 `--force` 会进入 `halt_now()`，默认先执行 `sync()`；因此它并非一定立即到达 reboot 系统调用。[上游实现](https://github.com/systemd/systemd/blob/v261/src/systemctl/systemctl-util.c#L893)

   **后果：**若返回失败，当前脚本确实会继续下一轮，第二轮的“失败后永久成功退出”已修复；但若卡在同步等操作，后续检查不会发生。高温情况下，这仍是具体的保护缺口。

   **修正：**最后一级也加 `timeout -k`，记录其失败并保留循环；若要覆盖同步卡住，明确设置最后的 `--no-sync` 应急升级及其 USB 文件系统损坏代价。补测“双 force 返回失败”和“双 force 挂起”。不要再宣称 timeout 能处理所有内核不可中断等待。

   `timeout` 不存在时，温度读取全部失败、前两级重启根本不会执行，随后直接调用双 force。内存 stub 验证了这一流程及失败后的重复调用。这是偏向停机的退化行为，但可能让正常机器被强制重启；安装验收应验证目标里的 `timeout -k` 可用，不能只依赖测试机 PATH。

2. **问题：MASKED 仍漏了 TPM 写入入口，但须区分条件触发与普通启动必然执行。**  
   [install-thor-root.sh:78](scripts/install-thor-root.sh:78) 没有 `systemd-pcrlogin@.service`。systemd 261 的 logind 会在用户首次登录时主动拉起该模板，将用户记录扩展到 `login` NvPCR；它不需要通过常规 `enable` 启用。[logind 实现](https://github.com/systemd/systemd/blob/v261/src/login/logind-user.c#L351)、[NvPCR 写入实现](https://github.com/systemd/systemd/blob/v261/src/pcrextend/pcrextend.c#L339)

   **后果：**这违反了 [DECISIONS.md:177](docs/DECISIONS.md:177) 所述“不依赖 measured-os 条件”的防护原则。不过 logind 和测量程序都有 measured-os 检查，**不能断言当前 GRUB 非 UKI 路径会触发写入**；仅有 `/dev/tpm0` 也不足以证明触发条件成立。

   另外，上游 preset 默认启用 `systemd-tpm2-clear.service`，列表也未覆盖它。它属于 factory-reset 路径，请求固件下次启动清 TPM，并非普通启动自动清除。相关 `systemd-factory-reset-request`／`complete` 和 factory-reset generator 也需要纳入条件路径盘点。[v261 preset](https://github.com/systemd/systemd/blob/v261/presets/90-systemd.preset#L36)、[官方 factory-reset 说明](https://systemd.io/FACTORY_RESET/)

   **修正：**至少补 mask `systemd-pcrlogin@.service` 并逐个验证。若保持“禁用所有此类持久化写入入口”的承诺，再覆盖 TPM clear 和 factory-reset 相关单元／目标。`pcrfs-root`／`pcrfs@` 写的是普通 PCR 15，不能误报为 TPM NV；当前 GPT 自动发现关闭、fstab 没有 `x-systemd.pcrfs`，也没有证据表明它们会被拉起。[v261 测量说明](https://github.com/systemd/systemd/blob/v261/man/systemd-pcrphase.service.xml)

   **实际 USB root 的完整单元、preset 和 generator 输出尚未取得，不能宣称已经穷尽发行版默认项。**

3. **问题：prefix 精确匹配新增了 `pipefail`／SIGPIPE 误拒绝。**  
   [install-thor-boot.sh:110](scripts/install-thor-boot.sh:110) 使用 `tr … | grep -qxF …`；`grep -q` 命中后提前关闭管道，尚在输出的 `tr` 可收到 SIGPIPE。

   **后果：**在 `set -o pipefail` 下，合法映像会被报告为 prefix 错误。我用“合法 NUL prefix＋1 MiB 尾部数据”的内存输入复现了退出状态 **141**。[测试 stub:50](tests/test_install_thor_boot.py:50) 的映像太小，覆盖不到。此问题会阻止 install／publish，属于安全拒绝，不会直接越界写盘。

   **修正：**最小修正是使用不提前退出的 `grep -xF "$PREFIX" >/dev/null`。若要真正按 NUL 字段匹配，直接解析二进制 NUL 字段；当前 `tr` 也会保留原有换行，严格说不是完整的 NUL 字段验证。增加大映像回归用例。

4. **问题：raytone-ready 已解决第二轮主缺口，但不绑定 grubenv 内容。**  
   [install-thor-boot.sh:123](scripts/install-thor-boot.sh:123) 在改动前撤销记录，完成后写哈希，publish 验证并消费，逻辑正确。失败重装遗留 `.staged` 已不能单靠存在性通过发布。

   **后果：**[144 行](scripts/install-thor-boot.sh:144) 未包含 grubenv，publish 只检查其大小；若 staged 后先 `arm-once`，可以带着一次性条目发布。这不影响 DECISIONS 当前“先 publish 验证默认路径、再 arm-once”的顺序，但就绪记录不能证明环境块仍是安装时的空状态。

   **修正：**建议将 grubenv 纳入首次发布哈希，或 publish 验证环境块合法且没有 `next_entry`。这是补强项，不是第二轮失败安装问题仍未解决。

5. **问题：machine-id 的处理可用，但原诊断需要纠正。**  
   [DECISIONS.md:178](docs/DECISIONS.md:178) 将“存在但为空”直接等同首次启动，不符合 systemd 261 语义：空文件**不算** first boot；不存在或内容为 `uninitialized` 才会触发相应首次启动逻辑。不能由空文件单独推出 firstboot 提示或 preset-all。[v261 官方说明](https://github.com/systemd/systemd/blob/v261/man/machine-id.xml#L107)

   **后果：**这不否定生成 ID、写 `KEYMAP=us` 和 mask firstboot 的处理，但测试名称和决策说明夸大了已证明的因果关系。

   **修正：**纠正文案即可。chroot 内的 `systemd-machine-id-setup` 会保留有效既有 ID，也可能采用目标 root 内的 D-Bus ID，否则生成随机 ID；正常识别 chroot 时不会借用宿主 `/run/machine-id` 或固件身份。当前私有 `/run`、目标 `/etc` 和随机设备绑定，没有自动复制 JetPack ID 的路径。[生成实现](https://github.com/systemd/systemd/blob/v261/src/shared/machine-id-setup.c#L55)

   共享宿主内核随机源不意味着生成相同 ID。建议把 [337 行](scripts/install-thor-root.sh:337) 的“非空”检查加强为合法非零 32 位十六进制，并仅记录“与 JetPack 不同”的比较结果；已有目标 D-Bus ID 是否来自模板，当前证据尚未验证。

6. **问题：离线 mask 本身没有发现阻塞项；不能把 unit mask 当成 generator mask。**  
   [install-thor-root.sh:323](scripts/install-thor-root.sh:323) 的离线 `systemctl mask` 是文件操作，可以处理 `.target` 和不存在的合法单元名，生成 `/etc/systemd/system/名称 -> /dev/null`，不需要运行中的 PID 1。逐个 `readlink` 验证合理；已有冲突文件导致失败，也应停止安装。[v261 实现](https://github.com/systemd/systemd/blob/v261/src/shared/install.c#L2156)

   **后果：**mask sleep 系列目标会拒绝相应睡眠事务，不会因此破坏普通 multi-user 启动。generator 可执行文件则属于另一个搜索目录，不能用 `systemctl mask 某某-generator` 禁用。

   **修正：**现有 mask 方法保留。重跑后检查真实目标里的链接、默认依赖和相关生成结果；无需仅因目标是 `.target` 或单元暂不存在而改变做法。

本轮实际验证：两个安装脚本和 guard 语法检查通过，18 个 `thor_boot` 测试通过，并完成上述内存复现。三个需要临时目录的行为测试套件未在只读沙箱运行；没有执行安装、写盘、重启或真实硬件验收。

不建议执行（最小修改：为 thermal guard 最后一级重启补上限时与失败测试；修复 prefix 管道的 SIGPIPE 误拒绝；补 mask 并验证 systemd-pcrlogin@.service，核对实际 USB root 的 TPM／factory-reset 默认入口）。
