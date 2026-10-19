# Engineering Lab

50 个后端工程实验，围绕一个具体问题构造最小环境，对比故障实现与修复实现，并检查实际结果。

覆盖 Go 并发与内存、HTTP、MySQL、Redis、Linux/Docker/Kubernetes、Kafka，以及检索与工具调用边界。

## 从这里开始

需要 Python 3.12 和 PowerShell 7。按实验安装 Go、Docker、kubectl、kind 等工具；具体环境见各目录 README。部分实验入口使用 Windows 专用进程和依赖实现，不保证所有脚本都能直接跨平台执行。

建议先运行 001，再阅读 Bad/Good 源码及验证条件：

~~~powershell
cd labs/001-go-goroutine-leak
./scripts/reproduce.ps1
~~~

需要后台服务的实验按各目录中的 start → reproduce → cleanup 顺序执行。不要并行启动使用同一名称的实验环境。023、024、046 使用专用 kind 集群；025 为 026、027、047 准备共用 Kafka Python 环境；028 为 049 准备固定模型与本地推理依赖。

## 实验目录

|编号|方向|问题|运行环境|
|---|---|---|---|
|001|Go|[请求已经取消，goroutine 为什么还留在进程里？](labs/001-go-goroutine-leak)|Go 1.25.4；原生及 Docker Linux|
|002|Go|[只有一个 goroutine，为什么发一条消息就死锁了？](labs/002-go-channel-deadlock)|Go；独立子进程|
|003|Go|[计数器结果碰巧正确，就能证明没有 data race 吗？](labs/003-go-data-race)|Go + Linux CGO 工具链；Docker|
|004|Linux|[打开文件失败，为什么不是磁盘满了？](labs/004-linux-fd-exhaustion)|Docker Linux；Python/Go；仅降低子进程 ulimit|
|005|网络/Go|[HTTP 请求都成功了，连接池为什么越来越忙？](labs/005-http-client-reuse)|Go；HTTP/1.1 本地服务；可容器化|
|006|Docker|[容器退出码 137，就一定是 OOMKilled 吗？](labs/006-docker-oom-killed)|Docker Linux；固定 memory limit|
|007|MySQL|[建了联合索引，SQL 为什么还是读了很多行？](labs/007-mysql-composite-index)|MySQL 8.4 Compose；版本和镜像 digest 固定|
|008|MySQL|[只多查一个字段，为什么 SQL 变慢了？](labs/008-mysql-covering-index)|MySQL 8.4；固定数据规模和缓冲条件|
|009|Go|[返回一个指针，就一定比返回值更慢吗？](labs/009-go-escape-allocation)|固定 Go 版本；避免死代码消除的 sink|
|010|Go|[sync.Pool 里的对象，为什么 GC 后找不到了？](labs/010-go-sync-pool-gc)|Go；关闭非实验 GC 干扰的受控阶段|
|011|Go|[CPU 没跑满，Go 服务吞吐为什么上不去？](labs/011-go-mutex-contention)|Go；受控并发；记录 CPU 和 GOMAXPROCS|
|012|MySQL|[深分页的 Rows_examined 只有 60，为什么仍扫描了 50 万条？](labs/012-mysql-deep-pagination)|MySQL 8.4；生成器；预热及重复采样|
|013|MySQL|[数据已经更新，长事务为什么还读到旧值？](labs/013-mysql-mvcc-long-transaction)|MySQL 8.4；独立数据卷|
|014|MySQL|[表里没有这条记录，INSERT 为什么还在等锁？](labs/014-mysql-gap-lock)|MySQL 8.4；显式事务；短 lock_wait_timeout|
|015|MySQL|[MySQL返回1213以后，只重试报错那条UPDATE为什么还会少改一行？](labs/015-mysql-deadlock)|MySQL8.4.11固定digest；Docker Linux2CPU/1GiB/128MiB；Python标准库+mysqlCLI force|
|016|Redis|[不存在的key反复回源，负缓存加上以后为什么又挡住了新数据？](labs/016-redis-cache-penetration)|Redis7.4.11与MySQL8.4.11固定digest Compose；Python标准库RESP2/持续CLI；Redisloopback动态端口|
|017|Redis|[已经加了互斥锁，为什么热点 key 仍回源 32 次？](labs/017-redis-cache-breakdown)|Redis7.4.11固定镜像；Go1.25.4 Windows actor/Linux受控HTTP源站|
|018|Redis|[给整批 key 加了随机 TTL，为什么还是一起过期？](labs/018-redis-cache-avalanche)|Redis7.4.11固定镜像；Go1.25.4 Linux HTTP源站；Python3.12.7客户端|
|019|Redis|[Redis 锁用了 owner Lua，为什么旧任务还是覆盖了新值？](labs/019-redis-expired-lock)|Redis7.4.11固定镜像；Go1.25.4 Linux内存资源；Python3.12.7 Windows双线程|
|020|网络/Linux|[CLOSE_WAIT 越来越多，该改内核参数还是先查 close？](labs/020-tcp-close-wait)|Go1.25.4/Linux6.18.40.1 WSL2；Docker network none loopback；iproute2 6.1.0-3；双角色同PID|
|021|Linux|[Load 很高，就一定是 CPU 不够用吗？](labs/021-linux-cpu-load)|Go1.25.4/GCC12.2.0/procps4.0.2/Linux6.18.40.1 WSL2；1CPU/128MiB cgroup；networknone；load为共享VM全局|
|022|Linux|[df 显示还有空间，创建空文件为什么仍然 No space left？](labs/022-linux-inode-exhaustion)|Go1.25.4/Linux6.18.40.1/Docker29.1.3/coreutils9.1；专用tmpfs；未启用noswap且未测swap|
|023|Kubernetes|[服务一直启动不完，是程序坏了还是探针杀得太早？](labs/023-k8s-startup-probe)|kind0.31.0/K8s1.34.3固定node digest/kubectl1.34.1/Go1.25.4；独立kubeconfig；单节点，无Service/Ingress|
|024|Kubernetes|[滚动更新时的几次 502，能不能稳定复现出来？](labs/024-k8s-graceful-shutdown)|kind0.31/K8s1.34.3/Go1.25.4/标准库HTTP反代，独立kubeconfig；旧Podfinalizer仅保API观察；8s grace，普通HTTP在途|
|025|Kafka|[消费者处理成功后突然退出，消息为什么又来了？](labs/025-kafka-duplicate-consumption)|固定 Kafka KRaft 镜像；MySQL；Go/Python 客户端版本锁定|
|026|Kafka|[消息都在同一分区，重试后为什么业务顺序还是乱了？](labs/026-kafka-retry-order)|Kafka KRaft；固定 partition/key；受控消费日志|
|027|Kafka|[生产者收到成功，就能保证故障后消息还在吗？](labs/027-kafka-acks-failure)|Kafka3.9.1固定digest，三broker/单controller各1CPU/512MiB；Windows native client2.11.1|
|028|AI Application Engineering|[Chunk 切得更大，RAG 召回就一定更好吗？](labs/028-rag-chunk-recall)|Windows CPython3.12/PyTorch2.6.0+cpu/Transformers4.49.0；BGE-small-zh-v1.5 revision7999e1d...a620；离线推理|
|029|AI Application Engineering|[语义检索漏了错误码，混合检索能找回来吗？](labs/029-rag-hybrid-search)|PostgreSQL17.10/pgvector0.8.2固定digest/专用1CPU256MiB容器；Python标准库读取冻结NPY，不重复推理|
|030|AI Application Engineering|[恶意工具调用到了执行器，参数合法就能放行吗？](labs/030-agent-tool-boundary)|Windows CPython3.12.7标准库，160专用私有sandbox，无LLM/外部接口/真实秘密|
|031|Go|[只留下32字节，为什么32MiB数组还活着？](labs/031-go-subslice-retention)|Go1.25.4 Windows，标准库pprof|
|032|Go|[父函数有recover，为什么子goroutine的panic仍让进程退出？](labs/032-go-goroutine-panic)|Go1.25.4；隔离二进制子进程|
|033|Go|[map的key都不同，为什么并发写仍然fatal？](labs/033-go-concurrent-map)|Go1.25.4；GOMAXPROCS2；受控写入|
|034|Go|[Ticker已经Stop，worker为什么还不退出？](labs/034-go-ticker-shutdown)|Go1.25.4；ticker/握手；仅自己的进程|
|035|网络/Go|[每次都设了超时，重试为什么仍超出请求总预算？](labs/035-http-retry-total-budget)|Go1.25.4 HTTP/1.1 loopback|
|036|MySQL|[查字符串列时传了数字，为什么结果和索引都变了？](labs/036-mysql-implicit-conversion)|MySQL8.4.11固定镜像；独立Compose|
|037|MySQL|[LIMIT只要20行，MySQL为什么仍要排序更多数据？](labs/037-mysql-order-limit-sort)|MySQL8.4.11；固定数据与资源|
|038|MySQL|[两个请求都返回成功，库存为什么只扣了一次？](labs/038-mysql-lost-update)|MySQL8.4.11；持续CLI；受控并发|
|039|MySQL|[事务正常COMMIT，转账为什么仍然少了钱？](labs/039-mysql-zero-row-transfer)|MySQL8.4.11；私有两账户fixture|
|040|Redis|[用了Pipeline，为什么中间状态还会被别的请求看到？](labs/040-redis-pipeline-interleaving)|Redis7.4.11；原始RESP；明确发包屏障|
|041|Redis|[Lua脚本报错了，前面写进去的值为什么还在？](labs/041-redis-lua-no-rollback)|Redis7.4.11；固定Lua；私有key|
|042|Redis|[写入没有报错，旧key为什么自己不见了？](labs/042-redis-maxmemory-eviction)|Redis7.4.11；独立受限容器，不触碰用户Redis|
|043|Redis|[Redis明明不忙，GET为什么排在BLPOP后面？](labs/043-redis-blocking-connection)|Redis7.4.11；RESP2 TCP；有限阻塞超时|
|044|Linux|[子进程已经退出，为什么ps里还留着Z？](labs/044-linux-zombie-wait)|Linux Docker；GCC12.2；仅专用父子|
|045|Docker/Linux|[CPU limit设成半核，为什么任务耗时不止看CPU百分比？](labs/045-docker-cpu-throttling)|Linux cgroupv2；Docker；固定Go或C计算|
|046|Kubernetes|[节点CPU很闲，Pod为什么仍然Pending？](labs/046-k8s-unschedulable-request)|kind0.31/K8s1.34.3；独立kubeconfig|
|047|Kafka|[消费者还活着，为什么分区已经分给别人？](labs/047-kafka-max-poll-interval)|Kafka3.9.1；native client2.11.1；独立topic/group|
|048|Kafka|[发送顺序是1到4，跨分区消费为什么变成另一种顺序？](labs/048-kafka-cross-partition-order)|Kafka3.9.1；明确key/partition与日志offset|
|049|AI Application Engineering|[没有答案的问题，向量检索为什么仍给出三个结果？](labs/049-rag-irrelevant-neighbors)|028固定BGE revision/CPU；新增自建fixture，校准与测试分开|
|050|AI Application Engineering|[向量查询LIMIT10，为什么加过滤后只返回几行？](labs/050-pgvector-filtered-ann)|PostgreSQL17.10/pgvector0.8.2；独立Compose；明确合成数值向量非模型输出|

## 目录与结果

- labs：实现、固定输入、运行脚本和各实验说明。
- shared/scripts：环境采集、协议交互、重复运行及本次结果清单校验工具。
- assets：每个实验的一张示例结果图及对应的汇总 CSV。

示例图与 CSV 是历史运行的汇总，精确数值受版本、平台、调度和资源限制影响。它们用于解释实验，不代表生产容量或通用性能结论。完整历史运行档案没有包含在此仓库中，因此这里不提供历史原始证据的完整重建承诺。

新运行会在各实验的 results 下保存原始输出和 manifest.json。可用以下工具检查本次清单中列出的文件是否保持一致：

~~~powershell
python shared/scripts/audit_evidence.py <本次运行的manifest.json>
~~~

该校验检查文件与清单的一致性；业务结果由各实验自身的验证器判断。运行输出、缓存、模型、虚拟环境和本机配置默认忽略。

RAG 实验使用自建虚构语料及固定标注。028、049 下载 BAAI/bge-small-zh-v1.5 的固定 revision，模型权重不随仓库分发；029 随附同一模型的一小组固定向量作为数据库查询输入。030 使用固定轨迹演示工具权限检查，没有调用 LLM。

## 本地检查

~~~powershell
python tools/check_repository.py
~~~

此命令检查目录、Python 语法、运行依赖引用、图表和本地文档链接，不会启动实验环境。运行故障实验前，阅读对应 README 和 cleanup 脚本，并使用独立环境。
