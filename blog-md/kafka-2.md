---
title: Kafka 基础（二）

tags:
  - kafka

categories:
  - Tech

comments: true
date: 2015-12-20 21:00:00

---

上文简单的介绍了 kafka 的架构以及基本概念，了解了这些基本就可以上手使用了，在使用的过程中，可以发现更多 kafka 的优秀之处(是我们整个系统中最稳定的组件，用了一年多没挂过，除了 python 的客户端不太友好以外！）

这篇文章我们将进一步介绍 kafka 的一些实现机制，包括容灾、性能优化 。

# Replication

kafka 通过 Replication 保证了高可用，在部分 broker 宕机的情况下数据不会丢失。

kafka replication 的实现单元不是 topic，而是 partition，什么意思呢？简单说就是，replication 是基于 partition 的，而不是基于 topic 的，也就是说 partition 是最小处理单元，kafka replication 中 leader/ Slave 的概念是对于 topic-partition 而言的。

这个比较好理解，正如前一篇文章所说，Partition 才是 kafka 物理存储的“最小单元”（更确切的说应该是 segment，partition 对应的是文件目录，而segment 是目录中的文件），topic 是逻辑上的 message queue，提供给 producer 和 consumer 更简单的接口。

对于拥有多个 partition 的 topic，kafka 会尽量将每个 topic 的 replicate partition 尽量均匀的分配到每个 brokers 上，避免出现大量集中在一个 broker 上而因此出现 broker 宕机导致 HA 失效。

kafka 的消息的读写都是由每个 partition 的 leader 完成的，slave 作为 consumer 去消费 leader 的数据保持同步。为了保证 producer 产生的数据不丢失，kafka 会根据配置，等待相应 slave 都数据同步完成才会返回 ack  给客户端。（当然，对于对消息丢失容忍度没有那么高的场景，比如请求日志，可以设置 producer commit 后不等待 leader ack。）

Kafka 的 replication 机制叫做 `in-sync replicas`，它将 slave 分为两类，其中一类叫 ISR，他们的数据即时和 leader 保持一致，即 leader ack 消息前会保证这一类 slave 同步数据成功，而另一类则允许其数据状态短暂的落后于 leader，主备切换的时候也只会从 ISR 中选举 leader。

这种复制方式相比 Paxos 的投票机制而言，在保持相同容错副本个数的前提下，所需要维护的一致的 slave 更少，效果更高。比如 5 个 slave 的场景下，ISR slave 为 2 即可，其余 3 个 slave 无需同步的和 leader 同步数据，参与选举即可。即 Paxos 要保证 5 个 slave 多完成数据同步后才会 ack 消息，而 ISR 复制只需要两个ISR slave 数据同步即可 ack 消息。

# 性能优化

kafka 性能优化的主要手段可以归纳为以下几点：

1.  每个 topic 可以对应多个 partition，通过多 partition 可以实现更高的并发。
2.  每个 partition 的写都是磁盘顺序写不是随机写，在一些场景下顺序写性能堪比内存。（producer 生产数据是文件追加的方式，而 consumer 消费数据同样基于 offset 顺序读。）
3.  broker 文件存储支持多目录，所以服务器可以通过多 Disk Drive 将磁盘挂载在多个kafka的存储目录，利用多 driver 提升磁盘利用率。
4.  当然对于任何系统而言，缓存基本上是必不可少的优化手段，kafka 利用 pagecache 在一定程度上使得实时消费直接走 pagecahe 而不必走磁盘，从而提升效率。
5.  另外，kafka 在将文件在网络中传输时，利用了 linux 的 SendFile系统调用，大幅减少了数据复制次数以及系统调用次数。
6.  kafka 网络 I/O 效率很高，其支持 batch 批量读写操作，同时支持数据压缩，能大幅减少 I/O 次数。

# SendFile 高效分析

在了解 SendFile 特性前，先了解下传统情况下将文件在网络中传输的过程：

*   首先，系统从磁盘将数据加载入内核的页缓存（内核态Buffer）
*   其次，应用将数据从页缓存拷贝到应用空间的缓存（用户态Buffer）
*   然后，应用将数据从其应用缓存拷贝到内核 socket 缓存（内核态Buffer）
*   最后，系统从 socket 缓存中拷贝数据到网卡缓存，然后通过网络发出

在以上过程中，涉及 4次数据拷贝以及2次系统调用，而利用linux 系统的 SendFile，系统可以直接将数据从页缓存复制到网卡，所以能做到大幅提效。

# 结束

到这里 关于 kafka 的一些基本介绍就结束了，最后推荐一款 kafka 管理工具：https://github.com/yahoo/kafka-manager 超赞！

# 参考

<<大数据日知录：架构预算法>>
[官方文档](https://kafka.apache.org/intro)
两篇很详细介绍 kafka 的资料：[kafka HA](http://www.jasongj.com/2015/04/24/KafkaColumn2/) && [kafka 高性能分析](http://www.jasongj.com/kafka/high_throughput/)
