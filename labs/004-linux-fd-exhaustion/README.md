# 004 · 打开文件失败，为什么不是磁盘满了？

EMFILE 怎样定位到进程句柄上限？

## 实验方法

实验子进程设置低 RLIMIT_NOFILE，不关闭文件与及时 close 对照；采 /proc 和 errno。

## 环境

Python 3.12；PowerShell 7。

Docker Engine 的 Linux 容器模式及 Docker Compose。

## 运行

在仓库根打开 PowerShell，按顺序执行：

~~~powershell
cd labs/004-linux-fd-exhaustion
./scripts/reproduce.ps1
./scripts/cleanup.ps1
~~~

目录内另提供 scripts/reproduce.sh；以脚本所需的系统和工具为准。

每次运行生成新的 results 子目录，包含 stdout、stderr、环境信息和校验清单；这些本机输出默认由 Git 忽略。预期的错误退出由实验验证器判定，不能只凭子进程退出码判断修复是否成立。

## 示例结果

Linux专用Demo，通过只降低自身RLIMIT_NOFILE软限制复现EMFILE。三模式×两限制×10次，共60次实际运行均符合验收。

![004 实验结果](../../assets/004/01-fd-lifetime.png)

图与 CSV 来自一次固定环境中的历史运行，供理解对照关系；新运行的精确时间、PID、内存和调度数据可能不同。此目录的复现入口会执行新的实验，不依赖历史原始日志。

## 代码入口

- [实现与领域验证](src)
- [实验入口](scripts/reproduce.ps1)
- [容器配置](docker-compose.yml)

清理脚本只作用于本实验的进程、容器、集群或工作目录；请先阅读脚本。实验中的固定口令用于本地演示环境。
