---
title: Structured Streaming Tips （一）

tags:
  - spark
  - structured-streaming
  - tips
  - gc
  - 优化

categories:
  - Spark

comments: true
date: 2018-04-15 00:30:00
---
# 前言

Spark / Storm 简单对比：

*   storm 的特点是延时更低，而 spark 吞吐更高
*   spark 支持 sql 形式的 streaming 开发，批处理场景和流处理场景可以很大程度上的公用代码，开发效率高，而 storm 不支持批处理且 sql 式 streaming 仍处理 beta 阶段，所以其开发成本更高
*   相比 storm 的资源调度，spark 的资源调度可以基于 yarn、mesos 等，其资源利用率更加高效

# kryo 序列化

`tuning a Spark application – most importantly, data serialization and memory tuning` 官方文档指出，序列化和内存调整是整个优化 spark 程序的最重要的两点。

spark 默认使用 [Java serialization](https://docs.oracle.com/javase/6/docs/api/java/io/Serializable.html) ,相比 [Kryo serialization](https://github.com/EsotericSoftware/kryo)， 其序列化速度、压缩都[差距非常大](https://github.com/eishay/jvm-serializers/wiki) ，最大速度相差约 `10x`，压缩 `5x`。使用 kryo 序列化能极大的提升内存的使用效率，以及处理速度，是程序优化的第一步！

## spark kryo demo

1.带序列化的 class 实现 [java.io](http://java.io/).Serializable:

![image.png](http://om2dgc3yh.bkt.clouddn.com/spark-tips-1.png)


2.实现注册Kyro序列化类，将待序列化的类注册，这一步是可选的，如果未注册，Kryo 仍然可以工作，但它必须存储每个对象的完整类名称，这是浪费的。所以最好注册

![image.png](http://om2dgc3yh.bkt.clouddn.com/spark-tips-2.png)

3.修改 spark session 序列化相关的配置 `spark.serializer` 以及`spark.kryo.registrator` :
 
![image.png](http://om2dgc3yh.bkt.clouddn.com/spark-tips-3.png)


## 参考

[https://blog.csdn.net/leen0304/article/details/78732171](https://blog.csdn.net/leen0304/article/details/78732171)
[https://github.com/holdenk/learning-spark-examples/blob/master/src/main/java/com/oreilly/learningsparkexamples/java/BasicAvgWithKryo.java](https://github.com/holdenk/learning-spark-examples/blob/master/src/main/java/com/oreilly/learningsparkexamples/java/BasicAvgWithKryo.java)

# 内存优化

## 内存管理机制

spark 在1.6 版本以后引入了新的内存管理机制——[UnifiedMemoryManager](https://github.com/apache/spark/blob/branch-1.6/core/src/main/scala/org/apache/spark/memory/UnifiedMemoryManager.scala)，其内存管理模型大致可以分为三部分 `Reserved Memory`,`User Memory`,`Spark Memory`，如下：

![image.png](http://om2dgc3yh.bkt.clouddn.com/spark-tips-4.png)

*   Reserved Memory 默认 300M，系统预留，需要重新编译 spark 才能更改。官方介绍为 测试使用的，一般情况下我们无需关心。（上图紫色部分）

*   UserMemory，用户内存。其被用来存储用户自己的数据，完全由你操作，比如 input data，map 操作后的 transform data，这部分内存在SparkMemory 分配后才会分配。（上图蓝色部分）

*   SparkMemory，这部分内存的用途又被分为两类：

*   Storage Memory：主要用来缓存 spark data 以及作为 ‘unrool’ 序列化数据的临时空间，以及存储 broadcast vars。当这部分内存不足时，unroll 以及 broadcast 的存储会落磁盘，不会OOM，当然代价是性能的损失。在资源不足时，牺牲一定的性能，保证稳定的前提下，可以适当的降低此部分的内存消耗。

*   Execution Memory: 主要用来存储Spark task执行需要的对象，比如 shuffle、join、union、sort 等操作 buffer。这块内存会 OOM，且无法被其他tasks clean。注意保证此块足够内存可用。

在我们的应用场景中，主要特点是：

*   大量的 kafka input data（15w qps）

*   按 5min 的 window 以及访问的 uuid（id+url）为 group  key，然后 count。

在这种场景中，不需要缓存，storage 的主要用途为 unroll 以及 broadcast，所以 Storage Memory 可以降低到很低的值。

![image.png](http://om2dgc3yh.bkt.clouddn.com/spark-tips-5.png)

另外使用 execution memory 的部分主要是 groupby shuffle，在我们的处理逻辑中 group by 之前会 filter无意义的http request，同时以一个更小的 CountUnit 对象（仅仅保留 http request 的 host，正则匹配后的url，event timestamp，ip，id）做 frequency 的 count，进最大程度的缩减存储，控制 shuffle 传输的数据量，所以 execution 部分也可以设置的很小，如下图 executor storage memory 的使用占比以及 shuffle 的使用占比。

![image.png](http://om2dgc3yh.bkt.clouddn.com/spark-tips-13)

spark memory 中 storage 和 execution 的最大占比分配通过 ` spark.memory.storageFraction` 控制，默认值为 0.5 即，各占一半。为什么说是最大占比的？因为整个 spark memory 是共享的，即可以互相侵占，这个参数配置的是 storage memory 在整个 spark memory 中的最小占比。因为 storage 是可以被 execution 驱逐，所以这个参数设定了一个被驱逐的底线，即留给 storage 的最小空间。反之 execution 无法被 storage 驱逐，但 execution 空闲时，是可以被 spark memory 使用的，最大可能的提高内存利用率。

在不同的场景下，需要根据不同的需求调整 `spark.memory.storageFraction` 。

从上文storage memory 和 execution memory 的占比可以看出，我们的程序对 spark memory 的依赖相对较低。为什么说相对较低呢，因为相对整个 kafka input 的数据的入队量较低，kafka input 的原始数据是一个完成的 http request，以当前 qps 15w + 5min window 来看，着实不是一个小数据量，而这部分数据量占用的是 user memory，所以说相对 user memory 而言对spark memory 依赖较低。

User memory 和 spark memory 在整个 heap 的分配是通过 `spark.memory.fraction` 参数配置的，默认是 0.6(2.0 及以上版本，1.6 是0.75)，即 user memory 占约 0.4 * executor memory(比这个值略低，实际为 0.6 * （ Executor Memory - Reserved Memory)）， spark memory 占约 0.6 executor memory，根据不同的场景，调整此值能最大化的优化资源利用。

在我们 frequency-count 的实际生产环境（qps 15w + 5min window group）中，设置每个 executor memory 为 10g 时，发现运行较慢的 task 日志中多次出现 Full GC，开始认为是 GC 问题，经过不断调参优化，虽然有一点提升，但当运行一段时间后，仍然会频繁出现 FULL GC，task 执行耗时越来越大（几十分钟）。后来仔细观察 GC 日志发现，GC 后 整个 old gen 仍然处于一个很大的值，趋于占满其上限，GC 回收效率一般，这是因为 user memory 不足，从kafka 源源不断的读取数据，由于 user memory 不足，导致不断 gc 回收空间分配给 input data。

![image.png](http://om2dgc3yh.bkt.clouddn.com/spark-tips-7.png)

增大 User memory 的两个方法，一是调大 executor memory， 而是提升 user memory 在整个  executor memory 的占比。因为我们的场景中对 spark memory 的依赖较小，所以在适当增大 executor memory （10g ->16g ）配置后，并通过降低 `spark.memory.fraction` 的值（默认 0.6 -> 0.2）提升的 user memory 的大小。

整个 streaming  job 运行了 24h 后，每个 stage 不会再出现之前最大执行几十分钟的情况了，因为 task 的GC 日志中不会再频繁出现 FULL GC，但没有释放太多资源的情况。在 input data 波峰时，最慢的 stage 也可以再分钟级完成（之前运行 1个小时后，就会出现某个 stage 的某个 task GC 耗时达到 30min 的情况）。

## 参考

Spark Memory Management ：[https://0x0fff.com/spark-memory-management/](https://0x0fff.com/spark-memory-management/)
spark memor configuration： [http://spark.apache.org/docs/latest/configuration.html#memory-management](http://spark.apache.org/docs/latest/configuration.html#memory-management)
Spark 内存管理详解：[https://www.ibm.com/developerworks/cn/analytics/library/ba-cn-apache-spark-memory-management/index.html](https://www.ibm.com/developerworks/cn/analytics/library/ba-cn-apache-spark-memory-management/index.html)
spark 内存管理：[https://wongxingjun.github.io/2016/05/26/Spark%E5%86%85%E5%AD%98%E7%AE%A1%E7%90%86/](https://wongxingjun.github.io/2016/05/26/Spark%E5%86%85%E5%AD%98%E7%AE%A1%E7%90%86/)

# GC 优化

生产环境中，我们的 streaming job 在运行时间长时间后（12h）发现仍会出现执行7.8 min 的 task，查看其 GC 日志发现又出现了 FULL GC，虽然可以接受这种个位数分钟级的延时，但是生产环境最好还是避免 FULL GC。

![image.png](http://om2dgc3yh.bkt.clouddn.com/spark-tips-8.png)

下面聊一聊生产环境的 GC 优化过程。

## GC 参数调整

在生产环境数据量较大的场景下(15wqps )，GC 是一个不可避免的问题，默认 spark 使用 Parallel GC，尽管 Parallel GC 是多线程并发执行，但受限于传统的JVM 内存管理和HEAP结构（如下图），其不可避免的受 Full GC 影响，易出现较大时间的停顿。

![image.png](http://om2dgc3yh.bkt.clouddn.com/spark-tips-9.png)

对于流式场景而言显然长时间的 “stop the world” 是难以接受的，[spark 官方推荐在 streaming 场景更推荐使用 G1GC](https://spark.apache.org/docs/2.2.1/tuning.html#garbage-collection-tuning)。G1GC 是 oracle 推出的以取代 CMS 为目标的 GC（当然现在已经做到）并在 JAVA 1.9 中成为默认 GC ，其特点是 `low-pause`, `server-style`，在实现高吞吐量的同时，尽肯能的控制暂停时间。个人理解是 Parallel GC 和 CMS GC 的综合体。G1GC 的 HEAP 结构和传统的不同，更加高效，如下：

![image.png](http://om2dgc3yh.bkt.clouddn.com/spark-tips-10.png)

spark executor gc 配置，通过 --conf spark.executor.extraJavaOptions 指定：

```shell
spark-submit --conf spark.executor.extraJavaOptions="-XX:+UseG1GC" xxx.jar
```

同时最好添加以下配置打印 GC 日志，方便 G1GC相关参数的调整：

```shell
-XX:+PrintFlagsFinal -XX:+PrintReferenceGC -verbose:gc -XX:+PrintGCDetails -XX:+PrintGCTimeStamps -XX:+PrintAdaptiveSizePolicy
```

在生产环境 GC 日志可以发现发生了 FULL GC：

![image.png](http://om2dgc3yh.bkt.clouddn.com/spark-tips-11.png)

G1GC 只提供了 YONG GC 和 Mixed GC，当 Mixed GC 无法满足进程的内存分配时会触发 serial old GC（full GC），其效率相比 Parallel GC 是差很多的。所以可以通过提早 Mixed GC，以及加快 Mixed GC 来尽量规避 FULL GC，添加参数如下:

```shell
-XX:InitiatingHeapOccupancyPercent=35  # 触发标记周期的 Java 堆占用率阈值, 默认 45%，注意是 `non_young_capacity_bytes，包括 old+humongous` 的占比
-XX:ConcGCThreads=20 #  并行标记的线程数，会占用一定资源
```

另外，日志中如出现：

![image.png](http://om2dgc3yh.bkt.clouddn.com/spark-tips-12.png)

则表示有 humongous object，这些 obj 只有在 FULL GC 才会回收，所以可以，增大`G1HeapRegionSize` 相关配置的值，尽量减少 Humongous Area 区域在 heap 中的创建：

```shell
-XX:G1HeapRegionSize=16m #  G1 区域的大小。值是 2 的幂，范围是 1 MB 到 32 MB 之间。目标是根据最小的 Java 堆大小划分出约 2048 个区域
```

G1的 evacuation pause 在几十到一百甚至两百毫秒都很正常。所以最好不要把MaxGCPauseMillis 设得太低，不然G1跟不上目标就容易导致垃圾堆积，反而更容易引发full GC而降低性能。

```shell
-XX:把MaxGCPauseMillis=1000 # 默认是 200ms，在以分钟为处理单位的生产环境可以接受秒级的暂停  
```

整个 spark executor 的完整配置:

```shell
--conf spark.executor.extraJavaOptions="-XX:+UseG1GC -verbose:gc -XX:+PrintGCDetails -XX:+PrintFlagsFinal -XX:+PrintReferenceGC -XX:+PrintGCTimeStamps -XX:+PrintAdaptiveSizePolicy -XX:InitiatingHeapOccupancyPercent=35 -XX:ConcGCThreads=20 -XX:G1HeapRegionSize=16m"
```

## 尽可能少的减少内存占用

GC的成本与 Java 对象的数量成正比，因此使用较少对象的数据结构大大降低了此成本。

1\. Java中，有三种类型比较耗费内存：

* 对象，每个Java对象都有对象头、引用等额外的信息，因此比较占用内存空间。

* 字符串，每个字符串内部都有一个字符数组以及长度等额外信息。

* 集合类型，比如HashMap、LinkedList等，因为集合类型内部通常会使用一些内部类来封装集合元素，比如Map.Entry。

因此Spark官方建议，尽量不要使用上述三种数据结构：

*   使用字符串替代对象，

*   使用原始类型（比如Int、Long）替代字符串，

*   使用数组替代集合类型（Spark 官方推荐使用 [fastutil](http://fastutil.di.unimi.it/) 中提供的集合类型）

2\. 对于包含 filter 算子的场景，尽可能早的 filter，然后在 map、reduce，减少在 map、reduce 过程中创建对象或其他变量的数量。

3\. 拼接字符串时，避免隐式的String字符串，String字符串是我们管理的每一个数据结构中不可分割的一部分。它们在被分配好了之后不可以被修改。比如”+”操作就会分配一个链接两个字符串的新的字符串。更糟糕的是，这里分配了一个隐式的StringBuilder对象来链接两个String字符串。eg:
```Java
       StringBuilder tmp = new StringBuilder(“test”);
       tmp.append("#").append(”test“);
```
以上的目的主要为了尽可能地减少内存占用，从而降低GC频率，提升性能。

## 参考

spark 官方推荐 G1GC:[http://www.bijishequ.com/detail/492289?p=70-69](http://www.bijishequ.com/detail/492289?p=70-69)
Java GC 分类：[https://www.bridgeli.cn/archives/342](https://www.bridgeli.cn/archives/342)
G1GC oracle 官方doc : [http://www.oracle.com/technetwork/articles/java/g1gc-1984535.html](http://www.oracle.com/technetwork/articles/java/g1gc-1984535.html)
G1GC 实现基本原理：[https://tech.meituan.com/g1.html](https://tech.meituan.com/g1.html)
G1GC 实现讨论：[http://hllvm.group.iteye.com/group/topic/44381](http://hllvm.group.iteye.com/group/topic/44381)， [http://hllvm.group.iteye.com/group/topic/21468](http://hllvm.group.iteye.com/group/topic/21468)
spark gc 调优实践: [https://www.csdn.net/article/2015-06-01/2824823](https://www.csdn.net/article/2015-06-01/2824823)
[https://www.infoq.com/articles/G1-One-Garbage-Collector-To-Rule-Them-All](https://www.infoq.com/articles/G1-One-Garbage-Collector-To-Rule-Them-All)
[https://www.infoq.com/articles/tuning-tips-G1-GC](https://www.infoq.com/articles/tuning-tips-G1-GC)
[http://www.bijishequ.com/detail/492289?p=70-69](http://www.bijishequ.com/detail/492289?p=70-69)
