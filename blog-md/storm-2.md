---
title: Strom入门系列之二：storm简单应用实例

tags:
  - storm

categories:
  - Storm

comments: true
date: 2016-04-30 23:00:00

---

上一篇文章概要的介绍的 storm 的一些知识，以及相关工作原理。本文将介绍本人在实际工作中实现的一个 Storm Topology。

需求
==================
先简要介绍一下业务场景——监控系统

监控系统架构简述
------------------------------
目前在一家 CDN 公司做监控系统的开发，整个监控系统负责做全网15000+设备的监控、CDN相关服务的监控以及其他业务的一些监控。整个监控系统结构大概如下图：

![图一：监控系统结构图](https://upload-images.jianshu.io/upload_images/5915508-48884043b1fcacfb.png?imageMogr2/auto-orient/strip%7CimageView2/2/w/1240)

在这个监控系统中，kafka 负责收集所有 agent 上报的消息，storm 消费 kafka。Storm 的一个 topology 负责将所有的消息转存到 redis 用以告警，同时还将消息转存的 opentsdb 时间序列数据库中用以展示数据序列。

业务数据聚合监控
-----------------------------
在上述结构中，对于某一项指标在某一台设备上的告警需求基本能全面覆盖，例如对设备的 Memory 的监控，agent 会定时上报设备的 memory 信息，storm 转存 redis 后，alarm 组件会定时的读取redis 中的数据判端相关监控项是否正常，这种监控我们称之为**设备监控。**

然而在更多的情况下这种单一设备维度的数据往往不能反应整个业务的服务状态，比如，对于某一个网站 "www.test.com" 的加速，通常由一个集群下的 N 个设备的 nginx 实现，而 nginx 日志中访问 "www.test.com" 的状态码是监控服务质量的一个重要指标。其中单台设备的 nginx 的 5xx，4xx 状态码数量和占比往往能反正这台设备是否服务正常，这个属于设备监控；但是，另一方面，某一设备的服务异常在整体上并不能反映集群的服务质量，整个集群的服务状态数据是需要聚合整个集群的实时数据计算的，这是设备监控所不能满足的需求。

在这里我们使用 storm 聚合数据，以频道（网站名称）为中心计算其在整个加速平台中的 5xx，4xx 状态码的占比和数量并监控，从整体上可以把控所有加速服务在这一指标上是否异常。

我们又实现了一个 topology 用于计算这种有数据聚合需求的监控，下面来看一下这个 topology 的实现。

设计
===================
kafka消息格式
------------------------
在讨论 storm topology 之前先聊聊 kafka 中的数据格式。因为CDN 服务的的核心是 nginx，很多服务和业务的核心数据是直接可以从 log 获取的，所以理想情况下能获得原始 log 然后各种分析是最理想的。但是考虑到全网 15000+ 的设备，在峰值时刻的带宽成本及其昂贵，所以我们采取了一下折中，通过部署在设备上的agent 实时跟踪 nginx 的日志流，将每条日志进行简要简析统计，将统计结果每 5min 上报的 kafka，这样基本解决的带宽成本（但是会带来 5min 的数据延时，可以根据不同的需求等级变更上报间隔）。上报的数据格式为：

![图二： 上报kafka消息格式](https://upload-images.jianshu.io/upload_images/5915508-10caa2f8ef1cbceb.png?imageMogr2/auto-orient/strip%7CimageView2/2/w/1240)

Spout设计
----------------
定义清楚消息格式后，可以开始设计 topology。Spout 这里比较简单，就是一个 kafka consumer 负责从 kafka 消费数据。目前，官方有提供现成的轮子 storm-kafka 包直接包含从 kafka 中读取数据的 [KafkaSpout](https://github.com/apache/storm/tree/master/external/storm-kafka)，官方版的直接应用 kafka 提供的 jave simple consumer 实现。

我们这里没有使用官方的包，是使用的 kafka 提供的高级 API 自建的 consumer。因为通过高级的 API 提供的 offset 的可以很方便的观察 kafka各个 partition 的消费情况，便于维护排障，而且当时而且官方的只支持 kafka-0.8.x 版本（使用中遇到过几个bug，不过后续修复了，现在也支持更高的版本了，推荐使用官方，否则要自己实现对kafka consume 的 ack）。

Bolt 设计
------------------
kafka 的每条消息是某一台设备近 5min 的被访问的所有频道的所有状态码的 count，也就是说以设备为中心，但需求是以频道为中心，所以在接到 spout 的 tuple 的第一个 bolt ——SplitBolt——需要做的就是将 tuple 的数据 split 成多条以频道为中心的 tuples，并将这些 tuples 通过 storm 的 fieldsGrouping 方式将 tuple 分组，保证频道相同的数据都落在后续的同一个 bolt 实例上。

第二个 bolt——ComputeBolt——收到频道为中心的数据后，在内存中通过map记录两类数据：
1. 每个频道在这一段时间内 2xx，4xx，5xx 等状态码的总量
2. 每个频道每个状态码的全网设备中 TopN 设备的详细数量和占比。

然后这个bolt 会定时（由于数据流式密集的，所以这个bolt自身维护一个时间戳，每次处理新的tuple的后根据设备时间判断是否超过5min，超过则像后续的bolt 发送数据，否则继续处理下一个tuple）的将统计结果分别提交给后续的 bolt 做存储和告警。这个bolt 的定时周期要和 agent 的上报周期相同，用以保证 storm 这里每一个汇集周期在正常情况下只会收到一台设备的一条数据。

另外三个 bolt——HbaseBolt，OpenTSDBBolt，TransferBolt——分别用于保存每 5min 的统计结果到对应的存储或服务，HbaseBolt 保存频道在全网 topN 设备的数据；OpenTSDBBolt 保存这个时间点频道的各个状态码总量和比例；TransferBolt负责将数据发送给告警服务（使用的小米开源的 Open-falcon 部分组件）。

这样，这个 topology 就初步完成了，从实际结果来看基本满足业务需求。下面来一下简要的代码。

实现
---------------------------------
整个topology的结构：

![图三： topology结构](https://upload-images.jianshu.io/upload_images/5915508-84e1979e17e64823.png?imageMogr2/auto-orient/strip%7CimageView2/2/w/1240)
（全部代码参见附录）

优化反思
=================
数据延时
----------------
在***设计***那一小节中我们说道：
这个 bolt 的定时周期要和 agent 的上报周期相同，用以保证 storm 这里每一个汇集周期在正常情况下只会收到一台设备的一条数据。

可以注意到这是一种理想情况。在生产环境中，往往因为网络情况机器负载等情况出现一些延时，这样在 ComputeBolt 的一个处理周期（5min）内可能会处理一台设备的两条甚至多条数据，这会一定程度上影响聚合统计结果的准确性，但是可以接受的。

首先这不会在总体上影响数据一的数量变化，其次，因为在数据传输的延时是 storm 无法保证的，少量的延时不会影响整个频道整体的数据趋势的，从实践效果来看基本不影响统计和告警，而大量的延时往往意味着服务集群整体故障、storm 集群集体故障亦或网络故障等，这种情况是很快会被设备告警发现的，所以不会影响告警。

但是在这个 topology 的设计中，计时是以数据在 storm 处理过程中的系统时间作为数据生成时间的，而不是使用数据自带的时间戳，所以数据堆积会影响统计结果，导致在某一小段时间内数据集中，不均匀，不过以目前的需求来说是可以接受的，如果希望严格分散则需要使用数据自带的时间戳，重新设计topology。

时间窗口（已更新1.0.x正式版新特性）
-----------------------------------------------------
在目前的机制中，Computebolt 是在计算完每一个 tuple 后查看系统时间，和 compute 内存中记录的上次发送时间做对比，如果超过 5min，则将统计结果 emit 到后面的 bolts 中。

很显然，这种设计方法会存在一定的误差，在数据密集时，这种误差很小，以线上的生产环境来看15000+设备，每 5min 发送一次数据，平均每秒50条数据，误差很小（根据观察在1s以内）。

但是数据稀疏时则会有较大几率产生高误差，比如当两条数据间隔超过 N 秒后，又恰巧这 N 秒内达到 5min 发送阈值，则可能会产生最大 N 秒的时间偏差，从而导致误差，或者数据缺失。

现在时间窗口在统计方面是一种很常见的需求，在 storm 的官方examples 中给出了一种解决方法来时间这种滑动窗口：新增一个spout，它每隔 5min 向 ComputeBolt 发送一个无意义的 tuple，使用 all-grouping 方式，保证每隔 ComputeBolt 都会接收到这个tuple，从而 ComputeBolt 根据 tuple 的来源判断是有意的统计数据还是一个 emit 统计结果的 flag tuple。

不过我个人认为这里可能仍然会出现问题，因为 storm 是保证最少处理一次，所以可能会发生重发这个无意义 tuple 的情景，这样可能出出现一些意外~

在storm发布1.0.x正式版后，新增的时间窗口功能，可以很方便的实现这种统计结果 Sliding Window 和 Tumbling Window 两种接口，可以根据接口灵活选择（相关文档参见附录）。

ps： 在后文会有一片关于window的使用介绍。

动态配置
-------------------
在 topology 有可能会出现另一种需求——不重启 topology，动态修改配置。其实这个方法的实现思路类似上文，是使用一个新的spout，这个 spout 是个 http-server 或 http-client，其可以接受或者定期拉取各种配置，将配置发送给 bolt，同时 bolt 根据 tuple 来源确定这是一个配置 tuple，用以更新自身配置。

小结
===========
本文简要的实现一个 topology，比较简单，可能还有坑。。。仅供参考。

Ps ：目前已经离职了，这里的优化其中一些在其他 topology 中使用了，但是这个 topology 一直没空改。。。github上就是没改过的。。。等有时间慢慢改吧。。。

附录
===========
[本文相关代码](http://github.com/zhai3516/kafka-storm-example)
[storm-windowing document ](http://storm.apache.org/releases/1.0.0/Windowing.html)
[storm-examples](https://github.com/apache/storm/blob/master/examples/storm-starter/README.markdown)
