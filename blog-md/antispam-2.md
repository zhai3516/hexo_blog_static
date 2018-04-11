---
title: Wukong—知乎反作弊系统性能优化(二)

tags:
  - antispam
  - wukong
  - 性能优化

categories:
  - antispam

comments: true
date: 2016-11-11 21:08:00

---
# 引

前一篇文章我们讨论了知乎反作弊系统Wukong遇到的一些性能瓶颈，以及一些解决方法和优化思路，本文将继续围绕上文提出的Wukong系统所面临的瓶颈，展开进一步讨论。

# **存储的进一步优化**

## **使用Redis-Pipeline**

前一篇文章讲到，我们通过增加二级缓存的思路——RedisCache-> LocalCache——极大的减少了系统对mongo的依赖，同时大幅提升了I/O效率，但这里仍然存在一些可以优化的点。

回顾上一篇中提到的只增加RedisCache时性能测试的表格：

|   | IndexCache | MetaCache |
|---|---|---|
| 最大返回条数200 | 6ms（查询了一个分片） | 54ms |
| 最大返回条数1000 | 10ms （查询了两个分片） | 280ms |

表一 ：仅使用RedisCache读取数据的耗时

从表中可以看到增加缓存后，时间没有减少，反而变大了，因为读取mongo，只有一次网络I/O，而读取redis，会有N次I/O，这里的N与我们想要的读取的数据条数成正比，因此我们增加了二级缓存——LocalCache，极大地减少了从redis读取的量，有效地减少耗时，大幅度的优化读取速度，并且放开读取数量的限制。

但是，这里仍有一个问题，LocalCache是从Redis中加载数据，更新缓存，所以当数据量很大时，仍然存在大量网络I/O的情况。比如，知乎每天的点赞量大概在100w左右，在每天上午10~11这一个小时内的点赞量大概在15w上下(每天上午10~12点，和晚上10~12点是全天高峰期)，处理点赞行为的容器大约为17个，所以在这个时段仍然存在大量的redis请求，不但产生大量的网络I/O，而且给redis带来的大量的负担。

所以，基于此情景，我们仍可以优化，从一次请求一条数据，变为一次请求一批数据，压缩网络I/O次数。Redis提供了Pipeline机制和LuaScripting机制可以实现批量操作，因为我们这里的情景，都是read请求，所以使用pipeline实现批量读取数据。（Redis相关内容可以参考[Pipelining](http://redis.io/topics/pipelining)）

|   | Wukong2.0 | Wukong3.0 |
|---|---|---
| 最大返回条数200 | 16ms | 20ms |
| 最大返回条数1000 | 90ms | 88ms |
表二 仅使用RedisCache读取数据，并使用pipeline方式的耗时

对比表一，表二是在仅使用RedisCache，不增加LocalCache，但使用redis-pipeline优化后的读取数据耗时，从数据对比中可以看到，使用pipeline后，从redis读取数据和耗时和mongo相近，数据量增大时略优于mongo。

## **增量更新**

在增加二级缓存和使用pipeline批量read后，Wukong系统的数据读取性能已经得到了极大的提升，数据读取量由默认200放开至3000，平均耗时也能控制在5~40ms左右（由于冷启动，所以在刚启动的前几秒耗时会长一些），但是从图一可以看出，时间仍然不是很平稳，呈波浪形，存在尖刺现象。
![图一 wukong_recent_events_bigcache 耗时曲线](https://upload-images.jianshu.io/upload_images/5915508-931c93ad43df208e.png?imageMogr2/auto-orient/strip%7CimageView2/2/w/1240)


经过调查分析，产生这种波浪现象的原因跟LocalCacha从RedisCache更新数据的策略模型有关。图二是wukong缓存组件bigcache的内部模型。其中，存储最新IndexKey的timesheet-0，每次都是从RedisCache全量的获取所有IndexKey，而其他的timesheet存储的IndexKey则直接存储在LocalCache中。
![图二 bigcache内部数据](https://upload-images.jianshu.io/upload_images/5915508-544810210f7ea136.png?imageMogr2/auto-orient/strip%7CimageView2/2/w/1240)

假设一次recent_event操作，读取近60min内的数据（目前线上策略大部分的时间范围是60min），一个时间分片的大小是10min，则大部分情况下其要读取的timesheet个数是7个，其中包括timesheet 0的部分数据，timesheet 1-5 的全量数据，和timesheet 6的部分数据，组合成60min这一个时间区间内的所有数据，如图三所示：
![图三 recent_event读取60min数据示意图](https://upload-images.jianshu.io/upload_images/5915508-f83d7b276647f149.png?imageMogr2/auto-orient/strip%7CimageView2/2/w/1240)

这样一来就会存在这样两个问题：

1.  在一个timesheet为10min的情况下，随着时间的增长，timesheet-0每次从redis获取的全量数据会逐渐增大，其数量增长模型与图一中的时间消耗模型是吻合的，所以很大程度上导致了这种尖刺现象。
2.  除了timesheet-0以外，其他timesheet默认都不会在从RedisCache更新，这里就可能存在因为延时而产生的数据遗漏问题。

对于此，我们使用增量更新的方式优化了bigcache。如图四，在最新的bigcache中，我们也缓存了timeshit-0的IndexKey到LocalCache，使用增量更新的方式，每次通过本地缓存的IndexKey数量计算出redis的增量索引，然后直接读取最新的数据，这样就大大减少了从redis读取数据的数据量，同时确保了数据的一致性。
![图四 更新后的bigcache 内部模型](https://upload-images.jianshu.io/upload_images/5915508-f50c04bdb10ec58b.png?imageMogr2/auto-orient/strip%7CimageView2/2/w/1240)

核心代码如下：
![图五 增量更新bigcache timeshit-0代码](https://upload-images.jianshu.io/upload_images/5915508-5d394317d7619fa4.png?imageMogr2/auto-orient/strip%7CimageView2/2/w/1240)

另外，因为有多个容器存在，每个容器检测action之前都会先save数据到mongo和redis，每次通过增量更新的方式获取到最新的数据中往往包含比当前数据更新的一些数据，而在反作弊检查场景中，是根据当前action，查找最近之前一段时间内，具有相似性的actions，所以这些更新的数据是不需要的。

如图六所示，这是一个从redis读取增量数据更新本地的timesheet 0后的整体数据，数据D是当前action所在位置。在这片数据中由于保存数据时可能存在数据延时，所以整片数据虽在在整体上是有序的，但是在局部会存在乱序现象，比如A-C中可能存在比D创建时间晚的数据，E-F中可能存在比D创建时间早的数据，所以需要进一步筛选出符合条件的数据。

![图六 从redis读取的增量cache数据排列示意图](https://upload-images.jianshu.io/upload_images/5915508-03245e6b42c95042.png?imageMogr2/auto-orient/strip%7CimageView2/2/w/1240)

之前使用全量检查action的created_time的策略来过滤这些过于新的数据，随着timesheet 0数据的增长，这同样会影响查询时间，成为导致图一尖刺现象的一个原因，所以现在改进为部分检查的方式，从最新的数据（即图六种的A）开始向后检查，在检查到第一个的的created_time小于等于当前action的创建时间的数据后，向后检查出N个都符合条件的数据，然后就不再检查，N根据经验目前是50，这样使recent_event的查询时间更加平稳。

![图七 优化后wukong_recent_events_bigcache 耗时曲线](https://upload-images.jianshu.io/upload_images/5915508-3cdd32934f5802df.png?imageMogr2/auto-orient/strip%7CimageView2/2/w/1240)

从图七可见，经过以上两点优化后，尖刺现象基本消除，使用bigcache读取3000条数据的时间稳定在4~6 ms左右（绿色），使用mongo读取200条数据的时间稳定在7~9ms（黄色）。

到此为止，关于存储的优化就告一段落。
