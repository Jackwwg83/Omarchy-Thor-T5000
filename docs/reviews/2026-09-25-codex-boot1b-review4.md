# Codex review round 4: Slice 1b boot fixes (2026-09-25)

`codex exec -s read-only` over `git diff 5504a7c..f1febe9`. Final answer, verbatim:

1. **问题：第三轮三条最小修改已在代码层面解决，未发现本轮新增必须修的问题。**  
   **后果：**[thermal-guard:32](scripts/thor-rootfs/thermal-guard:32) 将双 force 放后台，消除了该调用同步阻塞保护循环的问题；[install-thor-boot.sh:111](scripts/install-thor-boot.sh:111) 去掉 `-q`，大映像误拒绝已修复；[install-thor-root.sh:78](scripts/install-thor-root.sh:78) 覆盖了 pcrlogin、TPM clear、PCR／factory-reset sockets 等第三轮遗漏。未发现新增直接写 QSPI、NVMe 分区表／ESP、JetPack 启动配置、UEFI 变量或 TPM NV 的路径。  
   **修正：**无必须修改。新增的 grubenv 检查拒绝非空 `next_entry`；允许空值与 GRUB 的默认启动逻辑一致。machine-id 和目标 `timeout -k` 检查也合理。

2. **问题：sysrq 最后一级可用性仍需实机确认，但不受 `kernel.sysrq=0` 限制。**  
   **后果：**[thermal-guard:35](scripts/thor-rootfs/thermal-guard:35) 通过 `/proc/sysrq-trigger` 调用；管理员走此接口不受键盘 SysRq 开关限制，但需要内核编译支持及接口可写。`b` 不同步、不卸载文件系统，损坏风险涉及当时所有可写挂载，不能绝对限定为 USB；当前配置未新增 NVMe 挂载。[内核官方说明](https://docs.kernel.org/admin-guide/sysrq.html)  
   前两级请求返回成功时会提前返回，因此“30 秒后 sysrq”仅适用于**进入双 force 分支以后**，不是所有重启请求的统一期限。  
   **修正（可选）：**有人值守时确认目标内核的 `CONFIG_MAGIC_SYSRQ` 和接口权限；文案明确上述适用范围。已接受人工断电兜底的本次测试无需因此阻止重跑安装器。

3. **问题：后台日志避免等待写盘，但没有限制未完成子进程数量。**  
   **后果：**[thermal-guard:22](scripts/thor-rootfs/thermal-guard:22) 在持续 I/O 卡死时，每轮仍可新增日志进程；若 sysrq 也失败，[32 行](scripts/thor-rootfs/thermal-guard:32) 的重启进程也可能累积。正常完成的后台进程并不等于持续泄漏；风险在长期阻塞。日志也可能丢失或乱序。此外，同步执行的 `date`、启动时 `mkdir` 仍意味着“磁盘卡住绝不影响 guard”承诺过强。  
   **修正（可选）：**限制同时在途的日志／立即重启进程，并收窄注释。对于本次短时有人值守测试，不构成新增必须修项。

4. **问题：MASK_RE 未发现误匹配普通启动必需单元，但扫描范围不能证明穷尽所有入口。**  
   **后果：**[install-thor-root.sh:320](scripts/install-thor-root.sh:320) 只枚举 `/usr/lib/systemd/system` 顶层；已覆盖这些名称的 service、socket、target 和模板，跳过依赖目录，固定 mask 的 sleep／firstboot／repart 不妨碍当前普通启动路径。其他目录独有单元、显式实例覆盖、不同名称或程序直接写入不由此正则保证隔离。当前没有证据显示存在这些遗漏。  
   [DECISIONS.md:193](docs/DECISIONS.md:193) 只有“41 个”的汇总，**没有逐项清单**，因此本轮不能声称已独立核验真实盘上全部 41 个。  
   **修正（可选）：**留存实际名称、mask 链接及相关依赖清单；将“Every … unit”改成准确的扫描范围描述。

5. **问题：验证结论限于只读检查，新增行为测试未实际运行。**  
   **后果：**三个脚本语法检查通过，18 个 `test_thor_boot` 测试通过；内存输入复现旧 prefix 管道退出 **141**、新管道退出 **0**。需要临时目录的三个行为测试套件未在只读沙箱运行，也未执行安装、重启或硬件验收。  
   **修正：**真实启动与恢复能力仍按 DECISIONS 的有人值守步骤验收；未发现需要先修改代码才能重跑安装器的问题。

可以执行（重跑 install-thor-root.sh 和 staged install，早上按 DECISIONS.md 的有人值守步骤测试）
