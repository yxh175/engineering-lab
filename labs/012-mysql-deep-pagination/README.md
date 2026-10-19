# 012 · 深分页的 Rows_examined 只有 60，为什么仍扫描了 50 万条？

OFFSET 扫描丢弃与 keyset 的访问成本如何增长？

## 实验方法

先 100 万行，按磁盘预算扩大；深度扫描；OFFSET、延迟关联、keyset 对照；固定排序。

## 环境

Python 3.12；PowerShell 7。

Docker Engine 的 Linux 容器模式及 Docker Compose。

## 运行

在仓库根打开 PowerShell，按顺序执行：

~~~powershell
cd labs/012-mysql-deep-pagination
./scripts/start.ps1
./scripts/reproduce.ps1
./scripts/cleanup.ps1
~~~

目录内另提供 scripts/reproduce.sh；以脚本所需的系统和工具为准。

每次运行生成新的 results 子目录，包含 stdout、stderr、环境信息和校验清单；这些本机输出默认由 Git 忽略。预期的错误退出由实验验证器判定，不能只凭子进程退出码判断修复是否成立。

## 示例结果

MySQL8.4.11/Docker，1000000行/128B payload，七组各十采集包，对比OFFSET、延迟关联、完整游标和缺失tie-breaker的Bad，70包全部符合预先验收标准。

![012 实验结果](../../assets/012/01-scan-and-time.png)

图与 CSV 来自一次固定环境中的历史运行，供理解对照关系；新运行的精确时间、PID、内存和调度数据可能不同。此目录的复现入口会执行新的实验，不依赖历史原始日志。

## 代码入口

- [实现与领域验证](src)
- [实验入口](scripts/reproduce.ps1)
- [SQL](sql)
- [容器配置](docker-compose.yml)

清理脚本只作用于本实验的进程、容器、集群或工作目录；请先阅读脚本。实验中的固定口令用于本地演示环境。
