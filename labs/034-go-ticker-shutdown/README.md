# 034 · Ticker已经Stop，worker为什么还不退出？

Ticker.Stop是否关闭C以及如何通知工作goroutine结束？

## 实验方法

收到首tick握手后Stop-only/Stop+显式exit/持续tick控制各十；观察100ms原stack，最后所有组close exit并join。

## 环境

Python 3.12；PowerShell 7。

Go 1.25.4 或兼容版本；脚本会记录实际版本。

## 运行

在仓库根打开 PowerShell，按顺序执行：

~~~powershell
cd labs/034-go-ticker-shutdown
./scripts/start.ps1
./scripts/reproduce.ps1
./scripts/cleanup.ps1
~~~

每次运行生成新的 results 子目录，包含 stdout、stderr、环境信息和校验清单；这些本机输出默认由 Git 忽略。预期的错误退出由实验验证器判定，不能只凭子进程退出码判断修复是否成立。

## 示例结果

Go1.25.4 Windows/amd64、P1。三组各十进程：首tick握手后只Stop/Stop+exit/持续tick控制。Bad观察100ms仍select等待，Good全部done，控制继续收到tick；最后全部close exit、join、Stop，无遗留worker。

![034 实验结果](../../assets/034/01-ticker-and-worker.png)

图与 CSV 来自一次固定环境中的历史运行，供理解对照关系；新运行的精确时间、PID、内存和调度数据可能不同。此目录的复现入口会执行新的实验，不依赖历史原始日志。

该实现的历史数据来自 Windows/amd64；未据此声明 Linux 环境得到同一组数值。

## 代码入口

- [实现与领域验证](src)
- [实验入口](scripts/reproduce.ps1)

清理脚本只作用于本实验的进程、容器、集群或工作目录；请先阅读脚本。实验中的固定口令用于本地演示环境。
