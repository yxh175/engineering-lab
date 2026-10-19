# 014 · 表里没有这条记录，INSERT 为什么还在等锁？

范围锁如何限制并发插入？

## 实验方法

三持续会话RR/RC空范围、唯一命中/未命中、next-key及提前释放六组×10；data_locks/data_lock_waits、实际1205与重试完整结果。

## 环境

Python 3.12；PowerShell 7。

Docker Engine 的 Linux 容器模式及 Docker Compose。

## 运行

在仓库根打开 PowerShell，按顺序执行：

~~~powershell
cd labs/014-mysql-gap-lock
./scripts/start.ps1
./scripts/reproduce.ps1
./scripts/cleanup.ps1
~~~

目录内另提供 scripts/reproduce.sh；以脚本所需的系统和工具为准。

每次运行生成新的 results 子目录，包含 stdout、stderr、环境信息和校验清单；这些本机输出默认由 Git 忽略。预期的错误退出由实验验证器判定，不能只凭子进程退出码判断修复是否成立。

## 示例结果

MySQL8.4.11/Linux Docker，三行PRIMARY数据10/20/30，六场景各十次60组全部符合验收。空范围、唯一键未命中、next-key三组共30次真实1205；RC与唯一键命中各10次在释放前插入成功，提前释放同RR范围十次由等待恢复。

![014 实验结果](../../assets/014/01-waits-and-results.png)

图与 CSV 来自一次固定环境中的历史运行，供理解对照关系；新运行的精确时间、PID、内存和调度数据可能不同。此目录的复现入口会执行新的实验，不依赖历史原始日志。

## 代码入口

- [实现与领域验证](src)
- [实验入口](scripts/reproduce.ps1)
- [SQL](sql)
- [容器配置](docker-compose.yml)

清理脚本只作用于本实验的进程、容器、集群或工作目录；请先阅读脚本。实验中的固定口令用于本地演示环境。
