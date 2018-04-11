---
title: Storm－windowing 的一些尝试

tags:
  - storm
  - windowing

categories:
  - Storm

comments: true
date: 2017-02-10 23:00:00

---
Storm 在 1.x.x 版本后引入了 windowing 机制，使得开发者可以很方便的做一些统计计算。

最近由于工作内容变更，着手整合、开发公司的安全风控平台，又重拾 storm，使用storm清洗分发业务数据，并做相关计算。在接入 AntiCrawler（反爬虫）的业务需求时调研并使用了 storm 的 windowing 特性。

Windowing介绍
=====================
Sliding & Tumbling
--------------------------------
Storm官方文档抽象出两种类型的window：

（1）Sliding Window——一个tuple可以属于多个window，如下：![sliding-window](http://upload-images.jianshu.io/upload_images/5915508-78ee008d7b424653.jpeg?imageMogr2/auto-orient/strip%7CimageView2/2/w/1240)
（2）Tumbling Window——一个tuple只属于一个window，如下：![tumbling-window](http://upload-images.jianshu.io/upload_images/5915508-1885fbf8f3fcc26a.jpeg?imageMogr2/auto-orient/strip%7CimageView2/2/w/1240)

而定义一个 storm-window 的主要根据以下两点：window-length
 和 slide-interval。其中，window-length 是指这个窗口的长度，slide-interval 是指这个窗口每次滑动的距离他们可以通过两种维度计算：

（1）Count-即固定数量的tuple组成一个window
（2）Duration-即固定时间内所有的tuple组成一个window。


他们可以灵活的组合，以满足不同的需求，其具体接口可以参考storm-api（java-BaseWindowedBolt）。

Timestamp
-------------------
当使用 Duration 作为 window 的计算指标（length or interval）时，需要注意这样一个问题：每个 tuple 的 timestamp。Storm 根据 tuple 的 timestamp 来计算这个 tuple 是否属于这个 window。

默认的 storm 把 window-bolt 处理这个 tuple 的当前时间作为这个tuple 的时间戳。另外可以通过代码指定tuple的某个字段作为这个tuple的timestamp（java的api是***withTimestampField(String fieldName)***）**。**

个人不推荐使用默认值，最好使用 数据中自带的时间戳。因为在数据堆积的情况下，如果使用默认值，大量的历史堆积数据（对于实时计算来说在某种意义上已经是脏数据）会被当成实时值用以计算，导致数据不准确。

Out of order
----------------
如果使用tuple自带的字段作为 timestamp，在分布式场景中，由于各种因素，输出的tuples的timestamp是乱序的，参考如下场景：

>假设一个 Sliding window，其 window-length 是 10s，slide-interval 是5s。依次收到t1(10:00:10)，t2(10:00:14)，t3(10:00:12)，t4(10:00:16) 4个 tuple。

这种情况下storm会怎么做呢？默认的，storm在收到t3时发现其timestamp小于t2，则将其抛弃。并输出一条**INFO**级别的日志：

>INFO :  Received a late tuple {time=1488299337876} with ts 1488299337876. This will not processed.

这种情况显然不是我们希望的，所以 storm 提供了一个接口withLag (Duration duration)，通过这个接口，开发者可以通过这接口设置 window 可以接受的最大延时。此时，如果设置最大延时5s，则在上述情况下，t3则不会被抛弃。

所以，根据业务场景合理的设置withLag是有必要的。

Watermarks
-----------------
Watermark 是 storm 内部跟踪处理 window 的一个特性，其类似Flink、MillWheel。在处理带有timestamp的tuple时，storm内部包含一个由tuple的timestamp计算而来的watermarks。

它的计算方法是：storm 接受到得最新的 tuple 的 timestamp——Tmax 减去通过 withLat 设置的最大延时 L，`Max（T1…Tn）- L`。

Watermark 是用来评估是否结算窗口（**window calculation**），每当 window bolt 收到一个 Watermark，都会评估当前的 tuple 是否有需要结算的窗口，可以通withWatermarkInterval(Duration interval) 接口设置 watermark 的发送周期，其默认值是1s。以下官方给出的watermark机制的demo：
>*假设一个Slide window，其Window length = 20s, sliding interval = 10s, watermark interval = 1s, lag = 5s。*

**当前时间9:00:00，**e1(6:00:03), e2(6:00:05), e3(6:00:07), e4(6:00:18), e5(6:00:26), e6(6:00:36) 于 9:00:00 – 9:00:01到达。

那么 9:00:01 收到的 watermark 则为 6:00:36-lag(5) = 6:00:31，6:00:31 向下取整 6:00:30 以前的所有未结算windows都会结算，所以此时有三个window将会计算：

>5:59:50 – 06:00:10 with tuples e1, e2, e3
6:00:00 – 06:00:20 with tuples e1, e2, e3, e4
6:00:10 – 06:00:30 with tuples e4, e5

在 9:00:01 – 9:00:02，又有4个tuple，e7(8:00:25), e8(8:00:26), e9(8:00:27), e10(8:00:39)到达，则在 9:00:02（*watermark interval 是1s*）收到的 *watermark 是 8:00:39-lag(5) = 8:00:34，向下取整* 8:00:30以前的所有未结算window将会计算：
>6:00:20 – 06:00:40 with tuples e5, e6 (from earlier batch)
6:00:30 – 06:00:50 with tuple e6 (from earlier batch)
8:00:10 – 08:00:30 with tuples e7, e8, e9

Trident Windowing
-----------------------------
上文介绍的 windowing 主要是以 storm-core 为基础的，同样的，trident 也提供了类似的机制，同样包含 Sliding 和 Tumbling 两种类型，其使用方法和 storm-core 类似，具体 demo 可以参考官方提供的 examples （参见文末链接）。

Ps: 关于withTimestamp，withLag 和 watermark的测试验证测试代码可以参考：[storm-window-test 测试代码](https://github.com/zhai3516/storm-window-test)
相关资料：[storm-windowing 官方文档](http://storm.apache.org/releases/1.0.3/Windowing.html)
