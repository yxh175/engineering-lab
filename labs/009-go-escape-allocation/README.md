# 009 · 返回一个指针，就一定比返回值更慢吗？

逃逸分析的判断如何对应实际分配？

## 实验方法

24B Record的指针/值/interface局部消费或全局发布，显式noinline及当前包-l对照；两平台-m=2与各120独立benchmem进程。

## 环境

Python 3.12；PowerShell 7。

Go 1.25.4 或兼容版本；脚本会记录实际版本。

如选择容器入口，另需 Docker Linux Engine 与 Compose。

## 运行

在仓库根打开 PowerShell，按顺序执行：

~~~powershell
cd labs/009-go-escape-allocation
./scripts/start.ps1
./scripts/reproduce.ps1
./scripts/cleanup.ps1
~~~

目录内另提供 scripts/reproduce.sh；以脚本所需的系统和工具为准。

每次运行生成新的 results 子目录，包含 stdout、stderr、环境信息和校验清单；这些本机输出默认由 Git 忽略。预期的错误退出由实验验证器判定，不能只凭子进程退出码判断修复是否成立。

## 示例结果

六种调用上下文、默认与仅当前包禁内联，两平台各120独立benchmark进程、共240，全部通过。真实-m=2诊断、benchmem和校验和保留。

![009 实验结果](../../assets/009/01-escape-context.png)

图与 CSV 来自一次固定环境中的历史运行，供理解对照关系；新运行的精确时间、PID、内存和调度数据可能不同。此目录的复现入口会执行新的实验，不依赖历史原始日志。

## 代码入口

- [实现与领域验证](src)
- [实验入口](scripts/reproduce.ps1)
- [容器配置](docker-compose.yml)

清理脚本只作用于本实验的进程、容器、集群或工作目录；请先阅读脚本。实验中的固定口令用于本地演示环境。
