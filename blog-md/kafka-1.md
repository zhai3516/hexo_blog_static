---
title: Kafka 基础（一）

tags:
  - kafka

categories:
  - Tech

comments: true
date: 2015-12-18 22:00:00

---
Kafka 是一款极其出色的分布式消息队列，其吞吐量高，易扩展，高可用，支持持久化，在日志收集、实时数据收集、流处理等场景下被广泛的应用，很多公司选用 kafka 做为日志收集工具的首选，其能很好的和 storm、spark 等流处理框架配合使用。

# 物理架构
首先介绍一下 kafka 的一些基本架构，kafka 是一个分布式系统，一个 kafka 集群整体上可以分为三部分：

- producer：消息的生产者
- broker：kafka 集群 server 实例，即一个 kafka 集群服务器由 N 个 broker 组成
- consumer：消息的消费者

kafka 还依赖 zookeeper，管理集群配置，选举leader，动态负载均衡consumer 等等。一个 kafka 集群架构如下：

![kafka 集群架构](http://om2dgc3yh.bkt.clouddn.com/WechatIMG1099.jpeg)

kafka 还有另外几个比较重要的概念：topic，partition，consumer group。

# Topic
kafka 通过 topic 实现一个物理集群支持多个逻辑上的 queue 的特性，从逻辑上看，一个 topic 就是一个 queue，producer 连接到到 kafka 后可以将消息发送到指定 topic，而 consumer 通过订阅某个/某些 topics 可以消费其中的消息。

然而在物理上，每个 topic 中的消息的存储是被分成一个或者多个 partition ，通过 consumer group 一个 topic 可以被一组或者多组 consumer 同时消费。

# Partition
每个 topic 中的消息在各个 partition 中是按序存储的（实际落地存储时一个 partition 对应一个文件目录）并且是通过顺序写写入磁盘，一经写入，不可更改，因此其写入性能爆炸。每个消息在 partition 内部会被分配一个唯一的 offset，用以标记消息。Topic-Partition 示意图如下：

![partition 示意图](http://om2dgc3yh.bkt.clouddn.com/WechatIMG1095.jpeg)


每个 partition 在存储时是被切割成若干个固定大小的文件， kafka 会在内存中维护一份各个文件起始 offset 的索引，根据索引能快速定位 consumer 消费 offset 所在的文件，并计算出 offset 所在的位置。

producer 写入 topic 中的消息可以指定写入某个具体的 partition，同时 consumer 也可以指定具体消费某个 partition 中的数据。一般情况下可以不指定 partition，这是消息会基于 rr 算法随机写入 partition，相对均匀分布。


# Consumer Group
每个 consumer 都属于一个 group（不指定则属于默认分组），一个 topic 可以同时被多个 group 消费，而区分消费记录的依据就是 offset。落实到具体上就是一个 partition 可以同时被多个 group 的 consumer 消费，如图所示：

![producer&consumer](http://om2dgc3yh.bkt.clouddn.com/WechatIMG1096.jpeg)

而每个 group 的 offset 则被记录在 zookeeper 中，以此记录每个 consumer 的消费进度，同时保证不重复消费。

但是一个 partition 同一时间只能被同一 group 下的最多一个consumer 消费，不支持并发，也就说如果同一组consumer group 下的 consumer client 数目大于 partition 数据时，是没有意义的，真正能同时消费数据的 consumers 数最多和 partition 数相同。

# 参考
<<大数据日知录：架构预算法>>
https://kafka.apache.org/intro
