# 003 · 计数器结果碰巧正确，就能证明没有 data race 吗？

最终数值与 race detector 各自证明什么？

## 实验方法

64 worker屏障读旧值后放行普通写，与1P下数值正确的普通++及atomic Add对照；normal/-race六组各10次，保存实际报告并验证预期行为。

## 环境

Python 3.12；PowerShell 7。

Go 1.25.4 或兼容版本；脚本会记录实际版本。

此批量入口需要 Docker Linux Engine 与 Compose；normal 与 race 两种构建均在实验容器中执行。

## 运行

在仓库根打开 PowerShell，按顺序执行：

~~~powershell
cd labs/003-go-data-race
./scripts/reproduce.ps1
./scripts/cleanup.ps1
~~~

目录内另提供 scripts/reproduce.sh；以脚本所需的系统和工具为准。

每次运行生成新的 results 子目录，包含 stdout、stderr、环境信息和校验清单；这些本机输出默认由 Git 忽略。预期的错误退出由实验验证器判定，不能只凭子进程退出码判断修复是否成立。

## 示例结果

三种 counter 实现对照 normal 与 -race 构建，最新六组各 10 次验收通过。每个 worker 只增加一次，64 workers。

![003 实验结果](../../assets/003/01-count-vs-race.png)

图与 CSV 来自一次固定环境中的历史运行，供理解对照关系；新运行的精确时间、PID、内存和调度数据可能不同。此目录的复现入口会执行新的实验，不依赖历史原始日志。

## 代码入口

- [实现与领域验证](src)
- [实验入口](scripts/reproduce.ps1)
- [容器配置](docker-compose.yml)

清理脚本只作用于本实验的进程、容器、集群或工作目录；请先阅读脚本。实验中的固定口令用于本地演示环境。
