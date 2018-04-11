---
title: Storm入门系列之三：storm-trident 简介

tags:
  - storm
  - trident

categories:
  - Storm

comments: true
date: 2016-05-07 22:00:00

---

引
======================

最近在用 Trident 做各个 url 的访问统计 (实时统计各个 url 各个状态码的数量)，顺带补上这个空了好久的坑！

Trident 是在 storm-core 之上的一个高级抽象，其可以保证 message 保证被处理且只被处理一次的语义，即 **"exactly once"**。

本文将简要介绍 Trident 的一些核心概念以及使用方法。

在 storm-core 中，有两个核心概念：spout  和 bolt，相似的 Trident 也包含 spout，其作用和在 storm-core 中相同，是整个 topology 的数据源。Trident 中没有bolt，但有一个 operations 的概念，其作用和 bolt 相似，主要是实现一些对 message 的处理，下面将逐一介绍。

Spout
=============
和 storm-core 类似，Trident 也以 spout 作为整个 stream 的源头。

Zookeeper
------------------
在 topology 中每个 spout 都会拥有一个唯一标识，且在整个集群中都唯一，这个标识是 spout 在 zookeeper 中记录的元数据的唯一标识。

默认的 Spout 会使用 storm 集群的 zookeeper 集群，当然也可以通过以下配置使用单独的集群：
>transactional.zookeeper.serverstransactional.zookeeper.porttransactional.zookeeper.root

Pipline
----------------
在 Trident 中，Spout emit message 不再是一条一条的，而是以一个 batch 的形式一次 emit 一组 messages。默认的，storm 在同一只时间只会处理一个 batch，直到其成功或失败，通过：
>topology.max.spout.pending

这个配置可以配置其并发处理 batch 的个数，但是 Trident 仍然会按顺序更新 batch 的 state 以保证**『exactly once』**语义（关于 state 的实现原理会单独详细介绍，这里不再详细描述）。

Spout 类型
--------------------
Spout 根据事务性可分为三类：
non-transactional spout （非事务性）transactional spout （透明事务性）opaque transactional spout （不透明事务性）

其一次对应的 java 接口为：
*[IBatchSpout](http://github.com/apache/storm/blob/v1.0.3/storm-core/src/jvm/org/apache/storm/trident/spout/IBatchSpout.java)、**[IPartitionedTridentSpout](http://github.com/apache/storm/blob/v1.0.3/storm-core/src/jvm/org/apache/storm/trident/spout/IPartitionedTridentSpout.java)、**[IOpaquePartitionedTridentSpout](http://github.com/apache/storm/blob/v1.0.3/storm-core/src/jvm/org/apache/storm/trident/spout/IOpaquePartitionedTridentSpout.java)*

另外，还有一个通用的非事务性接口 IRichSpout。

Kafka-Spout
--------------------
一个比较通用的场景是从 kafka 读取数据，然后 storm 做实时处理。Storm-Kafka 提供了很简单的接口实现 kafka 数据的接入和管理，eg：
```java
TridentTopology topology = new TridentTopology();
BrokerHosts zk = new ZkHosts("localhost"); // 使用zookeeper 链接
kafkaTridentKafkaConfig spoutConf = new TridentKafkaConfig(zk, "test-topic"); // 配置一些Kafka的参数
spoutConf.scheme = new SchemeAsMultiScheme(new StringScheme());
OpaqueTridentKafkaSpout spout = new OpaqueTridentKafkaSpout(spoutConf);
```
在第一次连接 kafka 消费时，可以使用以下两个配置，选择从topic 最早的 offset 或 最近的 offset 开始消费，storm 会把消费的 state 信息存在 zookeeper 中( / + ‘spout_id’ 目录下)，所以后续的消费会直接从 zookeeper 中读取消费记录继续消费，也就是说**以下**配置只会在第一次消费时生效，当然如果手动在 zookeeper 中删除消费记录，还是会生效的。

>kafka.api.OffsetRequest.EarliestTime()
>kafka.api.OffsetRequest.LatestTime()

Operations
=================
Trident 包含5中常用的 operation:
- Partition-local operations
- Repartitioning operations
- Aggregation operations
- Operations on grouped streams
- Merges and joins

接下来，依次了解各个 operation。

Partition-local operations
----------------------------------------
这个 operation 包含的操作都是本地的，即**不会发生网络传输**，这类操作都是独立的对每个 batch 生效的。这一类是很通用的操作，其包含很多种类，常用的为以下 5 类：

**1. Functions**

Functions 是最通用的一类操作，这类操作对于每个待处理的 tuple，可以 emit 任意个结果，但是其不能删除或者变更 tuple 中已有的 fields，只能新增 fields。

比如收到 tuple ：[1, 2]，根据自己编写的 function 的逻辑，可以不 emit 任何结果直接 pass，或者 emit 1个结果 [1, 2 ,3]。也可以emit 多个结果 [1, 2, 3], [1, 2, 4], [1, 2, 5]。

**2. Filters**

Filter 与 Functions 不同，它是用来做过滤的，即处理的每个 tuple 只有两个选择：允许这个 tuple 继续向下传输或者不传输任何结果。比如收到 tuple ：[1, 2]，则此 filter 能 emit 的数据只有 [1, 2], 或者不 emit 任何结果。

**3. Map and FlatMap**

Map 会处理接收到的 tuple，并 emit 一个新的 value，其是 1-1 的处理方式，即接收一个且 emit 一个。

FlatMap 和 map 类似，唯一的区别在于它会提交一组 values，即是 1-N 的处理方式，会 emit 一个 List<Values>。

**4. min and minBy 和 max and maxBy**

前面提到，trident 是以一个小 batch 为单位处理处理 stream 中的数据的，这 4个类型的操作就是针对每次处理的这个 batch 计算过最小/最大值。

**5. Windowing**

Trident 也提供了时间窗口的处理方式，和 storm-core 非常类似，通过 windowing 可以对同一时间窗口内的 batchs 进行计算、处理。关于windowing 这里不再单独介绍，后面会单独写一篇文章介绍。

**6. partitionAggregate**
这类运算同样是针对每个 batch 而言的，它可以重新组合每个 batch 中的 tuples， 并 emit 任意结果。Trident提供了3类**partitionAggregate：**
CombinerAggregator：只会 emit 一个 tuple，且这个 tuple 只有一个 **field**
ReducerAggregator：也只会 emit 一个 tuple，这个 tuple 只有一个 **value**
Aggregator:  可以 emit 包含任意 fields 的任意数量 tuples，是一个比较通用的接口

Repartitioning operations
-----------------------------------------------
和Partition-local operations 相反，这类操作**一定会发生网络上的传输。**

**1.shuffle**

类似 storm-core 中的 shuffle grouping， 基于 Random Round Robin 算法随机将 tuples 均匀的传给目标 partition。

**2. broadcast**

类似 storm-core 的 all grouping，每个tuple 都会复制发送到后续所有的 partition。

**3.partitionBy**

类似 storm-core 的 Fields grouping，保证相同 fields 值数据被分配到统一个 partiton。

**4.global**

类似 storm-core 的 Global grouping，所有 tuples 被分配到同一个 partion。

**5.batchGlobal**

和 global 类似，但其会保证同一个 batch 的 tuples 被分配到同一个 partition。

Aggregation operations
------------------------------------
注意与上文的 partitionAggregate 区别，这类操作是作用于 streams 之上的，而partitionAggregate 仅仅是对单个 batch的，即一个 batch 所拥有的本地操作。

这类操作可以分成两种：

- 1.aggregate：以 batch 为单位，每个 batch 独立实现相应的聚合计算。
- 2.persistentAggregate：与  aggregate  相反，
 persistentAggregate 则是基于所有 batch  的所有 tuples 在全局实现聚合。

常用的聚合操作包括：ReducerAggregator、CombinerAggregator 以及通用的 Aggregator。其中 ReducerAggregator 和 Aggregator 会操作会将 stream repartition 到一个单独的 partition，在这个 partition 上实现聚合操作。而CombinerAggregator 则会现在每个 partition 上做实现 partial aggregation，然后将每个 partition 的结果在 repartition 到一个单独的 partition 实现聚合操作。

所以相比而言 CombinerAggregator 性能会更好。
 
Operations on grouped streams
------------------------------------------------
这个操作只有一种，即 “groupby” ，功能类似 sql 中的 groupby，基于指定的 fields 分组，此后的操作，比如 “persistentAggregate” 则不在以 batch 为单位，而是以不同的 group。

Merges and joins
------------------------------
这一类操作主要用于不同 stream 之间的计算，包含两种操作 “merge” 和 “join”。

参考
==================
[trident-api docs](http://storm.apache.org/releases/1.0.0/Trident-API-Overview.html)
[trident-examples](https://github.com/apache/storm/tree/v1.0.0/examples/storm-starter/src/jvm/org/apache/storm/starter/trident)
