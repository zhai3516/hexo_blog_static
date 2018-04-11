---
title: Storm入门系列之一：storm核心概念及特性

tags:
  - storm
  - core

categories:
  - Storm

comments: true
date: 2016-04-23 23:00:00

---
本文的将介绍一些 storm 入门的基础知识，包括 storm 的核心概念，storm 的并发机制和消息可靠处理机制基于 storm 1.0.x版本。

什么是Storm？
=====================
Strom 是一款开源的分布式实时计算框架，是一种基于数据流的实时处理系统，数据吞吐量大，实时性高。

为什么使用Storm?
=====================
来自官方的回答：
>It is scalable, fault-tolerant, guarantees your data will be processed, and is easy to set up and operate.

确实如官方所言，本人在使用 storm 的过程中深有感触，其可以帮助开发人员很**容易**的针对海量数据实现**实时**、**可靠**的数据处理。

Storm的核心概念
==================

Storm 计算结构中的几个核心概念为 topology，stream，spout，bolt，下面我们将依次介绍。

Topology
------------------------------
Topology 是 storm 中最核心的概念，其是运行在 storm 集群上的一个实时计算应用，相当于 hadoop 中的一个 job，区别于 job 的时，job 会有明确的开始和结束，而 topology 由于实时的流式计算的特殊性，从启动的那一刻起会永远的运行下去，直到手动停止。

Topology 由 stream，spouts，bolts 组成，可以描述为一个有向无环图，如下：
![图一 topology 示例](http://upload-images.jianshu.io/upload_images/5915508-78eb7b74470e781f.jpeg?imageMogr2/auto-orient/strip%7CimageView2/2/w/1240)

Stream
------------------------

Stream 是 storm 中对数据流的抽象，是由无限制的 tuple 组成的序列。Tuple 可以理解为包含一个或多个键值对的 hash。Tuples 在 stream 中流经 bolts，被逐步处理，最终得到预设的结果。

Stream 可比作一条源源不绝的河流，tuple 就是组成这条河流的无数水滴。每一个 stream 在 storm 中都有一个唯一标示的 id。

Spout
-----------------

从图一可以看出，spout 是一个 topology 的数据源，负责连接数据源，并将数据转化为 tuple emit 到 topology中，经由 bolts 处理。

Spout 提供了一对核心方法<ack, fail>来保障 storm 在数据没有被正确处理的情况下，不会被丢弃，仍能被重新处理，当然这是可选的，我们也可以不关心 tuple 是否被正确的处理，只负责向topology 中 emit 数据（在某些场景下可能不需要）。具体实现原理在后文会详细介绍。

Storm + Kakfa 是很常见的组合，storm提供了storm-kafka扩展，封装了多个可用的 kafka spouts 供直接使用，相关文档可以参考***[这里](http://storm.apache.org/releases/1.0.0/storm-kafka.html)***。

Bolt
-------------
Bolt 是 topology 中的数据处理单元，每个 bolt 都会对 stream 中的 tuple 进行数据处理。复杂的数据处理逻辑一般拆分成多个简单的处理逻辑交由每个 Bolt 负责。

Bolt 可以执行丰富的数据处理逻辑，如过滤，聚合，链接，数据库操作等等。

Bolt 可以接受任意个数据流中的 tuples，并在对数据进行处理后选择性的输出到多个流中。也就是说，bolt 可以订阅任意数量的spouts 或其他 bolts emit 的数据流，这样最终形成了复杂的数据流处理网络，如图一。

理解了 storm 的核心概念后，下文将介绍storm的并发机制。

Storm 的并发
=================

上文提到 storm 是 scalable 的，是因为 storm 能将计算切分成多个独立的 tasks 在集群上并发执行，从而支持其在多台设备水平扩容。那 storm 的并发是如何实现的呢？回答这个问题之前先来看一下 topology 是如何运行在 storm 集群中的：

![图二  topology运行示意图](http://upload-images.jianshu.io/upload_images/5915508-23ad74b9d5c5d878.jpeg?imageMogr2/auto-orient/strip%7CimageView2/2/w/1240)

上图中包含三个核心概念：
>worker: 一个 worker 对应一个进程，是一个 topology 的子集，在 storm 集群中的一个node上可根据配置启动N个 worker。

>Executor：一个 executor 是运行在一个 worker 进程上的线程，executor 可以执行同一个 spout 或 bolt 的一个或多个 task ，默认的一个 executor 会分配一个 task。

>Task：task负责真正的数据处理逻辑，一个 task 实质上是一个spout 或者 bolt 的实例。

所以，一个物理设备上可以运行多个 worker ，一个 worker 内部又可以启动多个 executor ，每个 executor 可以执行一个或多个task。

Strom的并发度是用来描述所谓的 "parallelism hint"，它是指一个 component（spout or bolt）的初始启动时的 executor 数量。通过下图我们来看一个 topology 的并发示例：

![图三 storm并发度示例](http://upload-images.jianshu.io/upload_images/5915508-cc7d90d12f5fdacd.jpeg?imageMogr2/auto-orient/strip%7CimageView2/2/w/1240)

上图的 topology 有一个 spout 和两个 bolt 组成。其中 blue spout 包含两个 executor，每个 executor 各执行一个 blue spout 的 task；green bolt 包含了两个 executor，每个 executor 各执行两个task；yellow bolt 包含6个 executor，每个 executor 各执行一个task。

整个 topology 启动了两个 worker，共包含 12 个task，每个worker 包含5个 executor，也就是5个 Thread。所以其 parallelism hint 是10。

从上例可以看出，增加分配给 topology 的 worker 数和 executor
 数是直接增加其计算能的简单办法。Storm 提供了相关的 **API** 或通过**配置文件**来修改一个 topology 的 woker 数，同样的
 storm 提供了相关 **API** 控制 executor 的数量和每个 executor执行的 task 数量用以控制并发。

Stream grouping 数据分组
========================

除了spout 和 bolt外，定义一个 topology 还有一个重要的组成，那就是 stream grouping，它规定了 topology 中的每一个 bolt 实例（也即是task）要接收什么样的 stream 作为输入。
具体来说，stream group 定义了一个 stream 中的 tuple 最终被emit 到哪个 bolt task 上被处理，是一个数据分组机制。storm 提供了八种内置的 stream grouping 类型(storm 1.o.x版本的内置类型，)：
1. Shuffle grouping : 随机分组，随机的分发 tuple 到每个 bolt 的各个 task，每个 task 接收的 tuples 数量相同。
2. Fields grouping : 按字段分组，会根据 tuple 的 某一个字段（可以理解为 tuple 这个 hash 的 key）分组，同一个字段的 tuple 永远被分配给同一个 task 处理。
3. Partial Key grouping : 类似2，但实现了 stream 下游的两个
 bolts 间的负载均衡，在 tuple 的字段分布不均匀时提供了更好的资源利用效果。
4. All grouping : 全复制分组，所有的 tuple 复制后，都会分发给所有的 bolt 的 task 进行处理。
5. Global grouping : 全局分组，所有的 tuples 都 emit 到唯一的一个 task 上，如果为一个 bolt 设置了多个 task，会选择 task id 最小的 task 来接收数据，此时设置的并发是没有意义的。
6. None grouping : 不分组，功能上同1，是预留接口。
7. Direct grouping : 指定分组，数据源会调用 emitDerect 方法来判断一个 tuple 将发送到哪个 cosumer task 来接收这个 tuple。这种分组只能在被声明为指向性的数据流上使用。
8. Local or shuffle grouping : 本地随机分组，和1类似，但是在随机分组的过程中会，如果在同一个 woker 内包含 consumer task，则在 woker 内部的 consumer tasks 中进行随机分组，否则同1。

另外，可以通过扩展[CustomStreamGrouping](http://storm.apache.org/releases/1.0.0/javadocs/org/apache/storm/grouping/CustomStreamGrouping.html)实现自定义的分组方式。

Strom的消息可靠处理机制
=====================
Storm可靠性分类
--------------------------

在这之前，我们需要介绍一个概念 "fully processed"。一条message 自从它由 spout emit 到 topology，被这个 tuple 途径的整个DAG 中的所有 bolt 都处理过，storm 认为这个 message 是被 "fully processed"。Storm 的消息保障处理机制是针对 "fully processed" 而言的。

在系统级，storm 提供了 "best effort"，"at least once"，"exactly once" 三种类型。其中 "best effort" 是**不保证每条消息都被处理**，"at least once" 是保障消息**最少能被处理一次**，可能会被多次处理，"exactly once" 是保证消息**被处理且只被处理一次**。

"best effort" 这种类型没什么可说的，就是每条消息 storm 都会按程序逻辑走下去，但是不会关注其是否成功。"at least once"，是storm-core 提供的可靠性级别，即保证每条 message 至少会被处理一次，可能会出现多次处理的情况，下文将详细介绍其实现原理。

至于 "exactly once" 其实是由 storm 的高级抽象 Trident 实现的，我们会在后文对其介绍。

Storm实现可靠性的API
-----------------------------------
现在，我们介绍一下 storm 保证可靠性的实现接口。在 storm 中要保障消息被处理你需要做以下两件事才能保证 spout 发出 tuple 被处理：
1. 无论在什么节点，每当你新创建一个 tuple 是都要告知 storm
2. 无论在什么节点，每当你处理完成一个 tuple 都需要告知 storm

对于spout，storm的提供了非常简单的API保证可靠性：
- nextTuple：这个接口负责emit tuple，为了保证可靠性需要为每个 tuple 生成一个唯一 ID，在通过 collector emit tuple 时，是需要带上这个 ID。同时会将这个 tuple 和 ID 保存在一个 hash 中，以等待 tuple 被完全处理后相应的操作.
- ack：这个接口负责处理成功的应答，一般当收到成功处理这个tuple 的消息后，删除 hash 中这个 tuple 的记录。
- fail: 这个接口复杂处理失败的应答，当某个 tuple 处理失败而超时后会调用这个接口，一般选择重新 emit 这条消息。

而对于 bolt 要做的则是，当接收到一个 tuple 后，如果有新生成tuple 则需要将新生成的 tuple 与输入 tuple 锚定，当处理成功或失败后分别确认应答或报错。锚定通过 collector.emit 方法实现：

```java
this.collector.emit(input_tuple, output_tuple)
```
确认和失败则分别调用 collector 的 ack 和 fail 方法。其中调用 fail方法能让这个 tuple 对应的 spout tuple 快读失败，不必让 spout task 等待超时后才处理它。
```java
this.collector.ack(input_tuple)this.collector.fail(input_tuple)
```
Storm高效实现可靠性的原理
---------------------------------------
在 storm 中有这样一个special "acker" tasks，它负责跟踪所有由spout 发出的 tuple产生的 DAG。当一个 tuple 成功的在 DAG
 中完成整个生命周期，这个 task 会通知 emit 这个 tuple 的 spout task 这个 tuple 被处理了。所以如果期望消息至少被处理一次，最少要启动一个 acker task，当然你可以启动任意个。

Storm 会通过 "mod hashing" 的方法将一个 tuple 分配到合适的acker 去跟踪，因为每一个 tuple 都对应一个64位的唯一ID，并且在锚定 tuple 时这个ID也会随之传给新生成的 tuple，所以 DAG 中的每个节点根据这个 ID 可以判断应答消息发送给哪个 acker。同样 acker 也能从在应答消息中确认哪个 tuple 的状态被更新了，当一个 tuple 的整个 DAG 完成，acker 会发送确认消息给源 spout。

Acker 不会明确的追踪整个 DAG，否则当 DAG 越发复杂时其负担越重。Acker 的追踪算法非常之简洁高效，并且只对于每个追踪的tuple 只会占用大约20B的固定空间。

Storm 会在系统中维护一个表，这个表的 key 是 acker 追踪的每个 tuple 的 ID，value 的初始值也是这个 ID。当 DAG 中的下游节点处理了这个 tuple 后，acker 接到确认信息后会做一个 XOR 运算，用 XOR 的运算结果来更新这个 ID 在表中对应的 val。

在这里需要说明一下在 DAG 中每个新生成 tuple 都会有一个64位的随机值ID（注意：不是其锚定的tuple传来的spout emit的那个tuple 的ID。也就是说每个新生成的 tuple 会有一个唯一 ID，新生成的 tuple 锚定某一个 tuple 后也会知晓 spout tuple 的那个 ID），在每个计算节点，storm 会将这个计算节点**生成的所有 tuple 的 ID** 与**所有输入 tuple 的 ID** 以及这个 DAG 所追踪的 tuple 在**系统表中对应的 value** 做 XOR 操作，得到一个结果，并用这个结果更新系统表中对应的 value。

因为XOR操作的特殊性：
>N XOR N = 0
>N XOR 0 = N

所以当一个 tuple 在在整个 DAG 中运行完成后这个 tuple 在系统表中对应 value 一定为 0，通过这点可以判定一个 tuple 是否被成功处理。我们通过实例来计算一下：

![图四：spout可靠性原理示意图](http://upload-images.jianshu.io/upload_images/5915508-e4d85163db3cd383.jpeg?imageMogr2/auto-orient/strip%7CimageView2/2/w/1240)

Storm在各种失败场景下的保障方法:

- 情景1：DAG 中某个节点挂掉没有正常发送 fail msg。这时其对应的根节点的 tuple 最后会因超时而被 spout 重发。
- 情景2：跟踪 tuple 的 acker task 挂了。此时，这个acker跟踪的所有task都会因为超时而重发（因为 acker 不会更新其在系统中对应的value）。
- 情景3：spout 挂了。因为spout的输入往往来自队列，当 spout 挂掉后，这个 spout 没有对队列中的消息做确认回应，所以队列不会认为这个 spout 提走的数据被正常消费了，而作"出队"处理(其实是将执行中并没有确认的数据重新归队)。

小结
===================
本文简要的介绍了 storm 的核心概念 topology，并介绍 topology
 的组成，topology 中的数据流分组方式，topology 在 storm 集群中如何并发运行，以及 storm 是如何保障消息可靠执行的。在下一章我们将会介绍一个生产环境中的简单实例。

参考资料
==============
（已更新为storm-1.0.0版本的文档）
[http://storm.apache.org/releases/1.0.0/Concepts.html](http://storm.apache.org/releases/1.0.0/Concepts.html)[http://storm.apache.org/releases/1.0.0/Understanding-the-parallelism-of-a-Storm-topology.html](http://storm.apache.org/releases/1.0.0/Understanding-the-parallelism-of-a-Storm-topology.html)[http://storm.apache.org/releases/1.0.0/Guaranteeing-message-processing.html](http://storm.apache.org/releases/1.0.0/Guaranteeing-message-processing.html)
