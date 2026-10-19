# 007 · 建了联合索引，SQL 为什么还是读了很多行？

谓词顺序、最左前缀和数据分布如何影响访问路径？

## 实验方法

确定性笛卡尔积200000行；联合索引前缀、WHERE重排、skip scan开关及范围谓词；EXPLAIN ANALYZE与同结果索引修复。

## 环境

Python 3.12；PowerShell 7。

Docker Engine 的 Linux 容器模式及 Docker Compose。

## 运行

在仓库根打开 PowerShell，按顺序执行：

~~~powershell
cd labs/007-mysql-composite-index
./scripts/start.ps1
./scripts/reproduce.ps1
./scripts/cleanup.ps1
~~~

目录内另提供 scripts/reproduce.sh；以脚本所需的系统和工具为准。

每次运行生成新的 results 子目录，包含 stdout、stderr、环境信息和校验清单；这些本机输出默认由 Git 忽略。预期的错误退出由实验验证器判定，不能只凭子进程退出码判断修复是否成立。

## 示例结果

固定MySQL镜像digest，实际8.4.11；200000行确定性数据，七组各10次，共70个正式客户端采集包全部通过。不是十次数据库冷启动。

![007 实验结果](../../assets/007/01-candidates-vs-results.png)

图与 CSV 来自一次固定环境中的历史运行，供理解对照关系；新运行的精确时间、PID、内存和调度数据可能不同。此目录的复现入口会执行新的实验，不依赖历史原始日志。

## 代码入口

- [实现与领域验证](src)
- [实验入口](scripts/reproduce.ps1)
- [SQL](sql)
- [容器配置](docker-compose.yml)

清理脚本只作用于本实验的进程、容器、集群或工作目录；请先阅读脚本。实验中的固定口令用于本地演示环境。
