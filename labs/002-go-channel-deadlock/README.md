# 002 · 只有一个 goroutine，为什么发一条消息就死锁了？

无缓冲 channel 的发送为何不能先存起来？

## 实验方法

子进程运行自发自收 Bad；并发接收与有缓冲 Good 对比；保存 fatal、退出码和栈。

## 环境

Python 3.12；PowerShell 7。

Go 1.25.4 或兼容版本；脚本会记录实际版本。

如选择容器入口，另需 Docker Linux Engine 与 Compose。

## 运行

在仓库根打开 PowerShell，按顺序执行：

~~~powershell
cd labs/002-go-channel-deadlock
./scripts/reproduce.ps1
./scripts/cleanup.ps1
~~~

目录内另提供 scripts/reproduce.sh；以脚本所需的系统和工具为准。

每次运行生成新的 results 子目录，包含 stdout、stderr、环境信息和校验清单；这些本机输出默认由 Git 忽略。预期的错误退出由实验验证器判定，不能只凭子进程退出码判断修复是否成立。

## 示例结果

两环境四模式各 10 次全部符合预先验收标准。只启动受控批次子进程；无常驻服务。

![002 实验结果](../../assets/002/01-outcomes.png)

图与 CSV 来自一次固定环境中的历史运行，供理解对照关系；新运行的精确时间、PID、内存和调度数据可能不同。此目录的复现入口会执行新的实验，不依赖历史原始日志。

## 代码入口

- [实现与领域验证](src)
- [实验入口](scripts/reproduce.ps1)
- [容器配置](docker-compose.yml)

清理脚本只作用于本实验的进程、容器、集群或工作目录；请先阅读脚本。实验中的固定口令用于本地演示环境。
