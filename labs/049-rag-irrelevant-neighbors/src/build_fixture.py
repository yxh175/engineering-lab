import json
from pathlib import Path
LAB=Path(__file__).resolve().parents[1]
facts=[
('D1','松果服务缓存空结果时设置15秒TTL，避免不存在的订单被反复查数据库。','缓存不存在订单的结果多久过期？','松果服务查不到订单后，空值缓存的生存时间是多少？'),
('D2','松果服务的Kafka消费者每次处理不超过200毫秒，max.poll.interval.ms配置为2000。','松果消费者的最大poll间隔配置是多少？','松果服务Kafka的max.poll.interval.ms设置的数值是什么？'),
('D3','松果服务在MySQL账户转账中检查两条UPDATE的受影响行数；任意一条不是1就ROLLBACK。','松果转账UPDATE没有更新一行时怎么处理？','松果服务转账遇到受影响行数不是1，事务会提交还是回滚？'),
('D4','松果服务HTTP重试共享250毫秒总context预算，每次调用结束读取并关闭响应Body。','松果HTTP重试使用多少总预算？','松果服务各次HTTP重试共用的context时限是多少毫秒？'),
('D5','松果服务创建子进程后由父进程调用waitpid回收；正常退出状态通过WEXITSTATUS读取。','松果父进程用什么函数回收子进程？','松果服务要收集子进程退出结果，父进程调用哪个函数？'),
('D6','松果服务向量表使用pgvector HNSW；过滤后数量不足时对照精确搜索，并评估strict_order迭代扫描。','松果向量过滤结果不足时怎样核对基线？','松果服务HNSW加过滤后少于K条，拿什么搜索结果做对照？'),
('D7','松果服务保存Go大切片的32字节片段时使用bytes.Clone复制，不保留原32MiB底层数组。','松果保存小片段用哪个Go复制方法？','松果服务长期保存32字节子切片时，使用什么函数脱离大数组？'),
('D8','松果服务测试集群只有一个节点，CPU allocatable是24核；应用的CPU request是20m。','松果测试节点可分配多少CPU？','松果服务测试集群的status.allocatable.cpu实际是多少核？')]
cal_negative=[
('今天成都的天气预报是什么？','语料没有天气数据'),
('如何制作提拉米苏？','语料没有烹饪说明'),
('火星到地球的实时距离是多少？','语料没有天文数据'),
('梵高向日葵现在的拍卖价格是多少？','语料没有艺术市场数据'),
('松果服务Redis部署在哪个机房？','语料只有空值TTL，没有部署机房'),
('松果Kafka消费者的维护者电话号码是什么？','语料没有人员联系信息'),
('松果MySQL账户转账手续费是多少元？','语料没有手续费'),
('松果测试集群节点的购买价格是多少？','语料没有购买价格')]
test_negative=[
('深圳明天会不会下雨？','语料没有天气数据'),
('怎样烘焙法式可颂？','语料没有烹饪说明'),
('木星今晚在上海几点升起？','语料没有天文数据'),
('莫奈睡莲的最新成交价是多少？','语料没有艺术市场数据'),
('松果缓存空结果时具体用了哪个Redis主机IP地址？','语料没有IP地址'),
('松果服务HTTP重试的全年费用预算是多少？','语料只有毫秒时限，没有金钱预算'),
('松果服务pgvector HNSW的索引创建日期是哪一天？','语料没有索引创建日期'),
('松果服务Go大切片复制的代码由谁负责维护？','语料没有人员归属')]
docs=[{'id':d,'text':t} for d,t,_,_ in facts]
queries=[]
for split,negatives,index in [('calibration',cal_negative,2),('test',test_negative,3)]:
    prefix='C' if split=='calibration' else 'T'
    for n,f in enumerate(facts,1):
        queries.append({'id':f'{prefix}{n:02}','split':split,'text':f[index],'answerable':True,'relevant':[f[0]],'evidence':f[1],'label_note':'完整自建文档含答案，相关文档人工标注'})
    for n,(q,note) in enumerate(negatives,9):
        queries.append({'id':f'{prefix}{n:02}','split':split,'text':q,'answerable':False,'relevant':[],'evidence':'','label_note':note})
out=LAB/'data/fixture.json';out.parent.mkdir(exist_ok=True)
out.write_text(json.dumps({'kind':'self-authored fictional service fixture, not production facts','docs':docs,'queries':queries},ensure_ascii=False,indent=2)+'\n',encoding='utf-8',newline='\n')
