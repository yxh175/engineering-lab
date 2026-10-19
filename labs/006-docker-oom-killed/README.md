# 006 · 容器退出码 137，就一定是 OOMKilled 吗？

退出码如何与 cgroup OOM 事件联合判断？

## 实验方法

独立容器小内存限额，逐页触碰内存；对照 kill 与限额内分配；保存 inspect/cgroup。

## 环境

Python 3.12；PowerShell 7。

Docker Engine 的 Linux 容器模式及 Docker Compose。

## 运行

在仓库根打开 PowerShell，按顺序执行：

~~~powershell
cd labs/006-docker-oom-killed
./scripts/reproduce.ps1
./scripts/cleanup.ps1
~~~

目录内另提供 scripts/reproduce.sh；以脚本所需的系统和工具为准。

每次运行生成新的 results 子目录，包含 stdout、stderr、环境信息和校验清单；这些本机输出默认由 Git 忽略。预期的错误退出由实验验证器判定，不能只凭子进程退出码判断修复是否成立。

## 示例结果

Linux cgroup v2，64MiB内存限制且无可用swap。比较保留全部8MiB缓冲、重复使用一块8MiB缓冲、准备就绪后对实验容器发送SIGKILL。正式重跑每组10独立容器，共30，全部符合验收。

![006 实验结果](../../assets/006/01-exit-vs-oom.png)

图与 CSV 来自一次固定环境中的历史运行，供理解对照关系；新运行的精确时间、PID、内存和调度数据可能不同。此目录的复现入口会执行新的实验，不依赖历史原始日志。

## 代码入口

- [实现与领域验证](src)
- [实验入口](scripts/reproduce.ps1)
- [容器配置](docker-compose.yml)

清理脚本只作用于本实验的进程、容器、集群或工作目录；请先阅读脚本。实验中的固定口令用于本地演示环境。
