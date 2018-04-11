---
title: (转)HBase架构深入解析

tags:
  - hbase

categories:
  - Hbase

comments: true
date: 2017-03-11 21:40:00
---

收藏一篇很详细介绍的 HBase 架构的文章，图文并茂，原文链接：

*   [英文原文地址](https://mapr.com/blog/in-depth-look-hbase-architecture/#.VdMxvWSqqko)
*   [译文地址](http://www.blogjava.net/DLevin/archive/2015/08/22/426877.html)

# HBase架构组成
HBase采用Master/Slave架构搭建集群，它隶属于Hadoop生态系统，由以下类型节点组成：HMaster节点、HRegionServer节点、ZooKeeper集群，而在底层，它将数据存储于HDFS中，因而涉及到HDFS的NameNode、DataNode等，总体结构如下：
![hbase 架构1](http://om2dgc3yh.bkt.clouddn.com/hbase-ar-1.jpeg)

![hbase 架构2](http://om2dgc3yh.bkt.clouddn.com/hbase-ar-2.jpeg)

其中HMaster节点用于：

1.  管理HRegionServer，实现其负载均衡。
2.  管理和分配HRegion，比如在 HRegion split 时分配新的 HRegion；在HRegionServer退出时迁移其内的 HRegion 到其他 HRegionServer 上。
3.  实现 DDL 操作（Data Definition Language，namespace 和 table 的增删改，column familiy 的增删改等）。
4.  管理 namespace 和 table 的元数据（实际存储在HDFS上）。
5.  权限控制（ACL）。

HRegionServer节点用于：

1.  存放和管理本地 HRegion。
2.  读写 HDFS，管理 Table 中的数据。
3.  Client 直接通过 HRegionServer 读写数据（从HMaster中获取元数据，找到RowKey所在的 HRegion/HRegionServer 后）。

ZooKeeper集群是协调系统，用于：

1.  存放整个 HBase集群的元数据以及集群的状态信息。
2.  实现HMaster主从节点的 failover。

## HRegion
HBase 使用 RowKey 将表水平切割成多个 HRegion，从 HMaster 的角度，每个HRegion 都纪录了它的 StartKey 和 EndKey（第一个 HRegion 的 StartKey 为空，最后一个 HRegion 的 EndKey 为空），由于 RowKey 是排序的，因而 Client可以通过 HMaster 快速的定位每个 RowKey 在哪个 HRegion 中。HRegion 由 HMaster 分配到相应的 HRegionServer 中，然后由 HRegionServer 负责 HRegion 的启动和管理，和 Client 的通信，负责数据的读(使用HDFS)。每个 HRegionServer 可以同时管理1000个左右的HRegion（这个数字怎么来的？没有从代码中看到限制，难道是出于经验？超过1000个会引起性能问题？）。
![hregion](http://om2dgc3yh.bkt.clouddn.com/hbase-ar-3.jpeg)

## HMaster
HMaster 没有单点故障问题，可以启动多个 HMaster，通过 ZooKeeper 的 Master Election 机制保证同时只有一个 HMaster 出于 Active 状态，其他的 HMaster 则处于热备份状态。一般情况下会启动两个 HMaster，非 Active 的 HMaster 会定期的和Active HMaster 通信以获取其最新状态，从而保证它是实时更新的，因而如果启动了多个 HMaster 反而增加了 Active HMaster 的负担。前文已经介绍过了 HMaster 的主要用于 HRegion 的分配和管理，**DDL(Data Definition Language，既Table的新建、删除、修改等)**的实现等，既它主要有两方面的职责：

1. 协调HRegionServer

- 启动时 HRegion 的分配，以及负载均衡和修复时 HRegion 的重新分配。
- 监控集群中所有 HRegionServer 的状态(通过 Heartbeat 和监听 ZooKeeper 中的状态)。

2. Admin职能
- 创建、删除、修改 Table 的定义。
![hmaster](http://om2dgc3yh.bkt.clouddn.com/hbase-ar-4.jpeg)

## ZooKeeper
ZooKeeper 为 HBase 集群提供协调服务，它管理着 HMaster 和 HRegionServer 的状态(available/alive等)，并且会在它们宕机时通知给 HMaster，从而 HMaster 可以实现 HMaster 之间的 failover，或对宕机的 HRegionServer 中的 HRegion 集合的修复(将它们分配给其他的 HRegionServer)。ZooKeeper 集群本身使用一致性协议(PAXOS协议)保证每个节点状态的一致性。
![zk](https://upload-images.jianshu.io/upload_images/5915508-35a49bbfd81623a6.png?imageMogr2/auto-orient/strip%7CimageView2/2/w/1240)

## How The Components Work Together
ZooKeeper协调集群所有节点的共享信息，在HMaster和HRegionServer连接到ZooKeeper后创建Ephemeral节点，并使用Heartbeat机制维持这个节点的存活状态，如果某个Ephemeral节点实效，则HMaster会收到通知，并做相应的处理。
![工作机制](https://upload-images.jianshu.io/upload_images/5915508-cb56b313a6459f8e.png?imageMogr2/auto-orient/strip%7CimageView2/2/w/1240)

# HBase 的第一次读写基本流程：
在 HBase 0.96 以前，HBase 有两个特殊的 Table：-ROOT- 和 .META.（现在只有 .META），其中 -ROOT- Table 的位置存储在 ZooKeeper，它存储了 .META. Table 的 RegionInfo 信息，并且它只能存在一个 HRegion，而 .META. Table 则存储了用户 Table 的 RegionInfo 信息，它可以被切分成多个 HRegion，因而对第一次访问用户 Table 时，首先从 ZooKeeper 中读取 -ROOT- Table 所在 HRegionServer；然后从该 HRegionServer 中根据请求的 TableName，RowKey 读取 .META. Table 所在 HRegionServer；最后从该 HRegionServer 中读取 .META. Table 的内容而获取此次请求需要访问的 HRegion 所在的位置，然后访问该 HRegionSever 获取请求的数据，这需要三次请求才能找到用户 Table 所在的位置，然后第四次请求开始获取真正的数据。当然为了提升性能，客户端会缓存- ROOT- Table 位置以及 -ROOT-/.META. Table 的内容。客户端在第一次访问用户Table的流程：

1.  从 ZooKeeper(/hbase/meta-region-server) 中获取 hbase:meta 的位置（HRegionServer的位置），缓存该位置信息。
2.  从 HRegionServer 中查询用户 Table 对应请求的 RowKey 所在的 HRegionServer，缓存该位置信息。
3.  从查询到 HRegionServer 中读取 Row。

从这个过程中，我们发现客户会缓存这些位置信息，然而第二步它只是缓存当前RowKey对应的HRegion的位置，因而如果下一个要查的RowKey不在同一个HRegion中，则需要继续查询hbase:meta所在的HRegion，然而随着时间的推移，客户端缓存的位置信息越来越多，以至于不需要再次查找 hbase:meta Table 的信息，除非某个 HRegion 因为宕机或 Split 被移动，此时需要重新查询并且更新缓存。
![hbase 第一次读写](https://upload-images.jianshu.io/upload_images/5915508-97aaf4be077f834a.png?imageMogr2/auto-orient/strip%7CimageView2/2/w/1240)


## HBase:meta表
HBase:meta 表存储了所有用户 HRegion 的位置信息，它的 RowKey 是：tableName, regionStartKey, regionId, replicaId 等，它只有 info 列族，这个列族包含三个列，他们分别是：info:regioninfo 列， 是 RegionInfo 的 proto 格式：regionId, tableName, startKey, endKey, offline, split, replicaId；info:server 格式：HRegionServer 对应的 server:port；info:serverstartcode 格式是HRegionServer 的启动时间戳。
![meta 表](http://upload-images.jianshu.io/upload_images/5915508-0388b2569e203453?imageMogr2/auto-orient/strip%7CimageView2/2/w/1240)

# HRegionServer详解
HRegionServer 一般和 DataNode 在同一台机器上运行，实现数据的本地性。HRegionServer 包含多个 HRegion，由 WAL(HLog)、 BlockCache、MemStore、HFile 组成。

1.  WAL 即 Write Ahead Log，在早期版本中称为 HLog，它是 HDFS 上的一个文件，如其名字所表示的，所有写操作都会先保证将数据写入这个 Log 文件后，才会真正更新 MemStore（内存），最后写入 HFile （硬盘）中。采用这种模式，可以保证HRegionServer 宕机后，我们依然可以从该 Log 文件中读取数据，Replay 所有的操作，而不至于数据丢失。这个 Log 文件会定期 Roll 出新的文件而删除旧的文件(那些已持久化到 HFile 中的 Log 可以删除)。WAL 文件存储在 /hbase/WALs/${HRegionServer_Name} 的目录中(在0.94之前，存储在 /hbase/.logs/ 目录中)，一般一个 HRegionServer 只有一个 WAL 实例，也就是说一个 HRegionServer 的所有 WAL 写都是串行的(就像 log4j 的日志写也是串行的)，这当然会引起性能问题，因而在HBase 1.0之后，通过HBASE-5699实现了 多个WAL并行写(MultiWAL) ，该实现采用HDFS的多个管道写，以单个HRegion为单位。关于 WAL 可以参考 Wikipedia 的 Write-Ahead Logging。

2. BlockCache 是一个读缓存（读性能的关键在于缓存），即“引用局部性”原理（也应用于 CPU，分空间局部性和时间局部性，空间局部性是指 CPU 在某一时刻需要某个数据，那么有很大的概率在一下时刻它需要的数据在其附近；时间局部性是指某个数据在被访问过一次后，它有很大的概率在不久的将来会被再次的访问），将数据预读取到内存中，以提升读的性能。HBase 中提供两种 BlockCache 的实现：默认 on-heap LruBlockCache 和 BucketCache(通常是off-heap)。通常BucketCache的性能要差于LruBlockCache，然而由于GC的影响，LruBlockCache的延迟会变的不稳定，而BucketCache 由于是自己管理 BlockCache，而不需要 GC，因而它的延迟通常比较稳定，这也是有些时候需要选用 BucketCache 的原因。这篇文章BlockCache101对on-heap和off-heap的BlockCache做了详细的比较。（现在默认两者搭配使用，称为 CombinedBlockCache，效果尤佳）

3. HRegion 是一个 Table 中的一个 Region 在一个 HRegionServer中的表达。一个Table 可以有一个或多个 Region，他们可以在一个相同的 HRegionServer 上，也可以分布在不同的 HRegionServer 上，一个 HRegionServer 可以有多个 HRegion，他们分别属于不同的 Table。HRegion 由多个 Store(HStore) 构成，每个 HStore 对应了一个 Table 在这个 HRegion 中的一个 Column Family（所以同属同一个 Column Family 的列必定存在同一个 HRegion 上），即每个 Column Family 就是一个集中的存储单元，因而最好将具有相近 IO 特性的 Column 存储在一个 Column Family，以实现高效读取(数据局部性原理，可以提高缓存的命中率)。HStore 是HBase 中存储的核心，它实现了读写 HDFS 功能，一个 HStore 由一个 MemStore 和0个或多个 StoreFile 组成。
-  MemStore 是一个写缓存 (In Memory Sorted Buffer) ，所有数据的写在完成 WAL 日志写后，会写入 MemStore 中，由 MemStore 根据一定的算法将数据 Flush 到地层 HDFS 文件中 (HFile)，通常每个 HRegion 中的每个 Column Family 有一个自己的MemStore。
- HFile(StoreFile) 用于存储 HBase 的数据 (Cell/KeyValue)。在 HFile 中的数据是按RowKey、Column Family、Column排序，相同的 Cell(即这三个值都一样)，则按timestamp倒序排列。
![region server 组成](https://upload-images.jianshu.io/upload_images/5915508-4d30bdfad880599b.png?imageMogr2/auto-orient/strip%7CimageView2/2/w/1240)

# HRegion Server 写的实现
当客户端发起一个 Put 请求时，首先它从 hbase:meta 表中查出该 Put 数据最终需要去的 HRegionServer。然后客户端将 Put 请求发送给相应的 HRegionServer，在 HRegionServer 中它首先会将该 Put 操作写入 WAL 日志文件中( Flush到磁盘中)。
![写 WAL](https://upload-images.jianshu.io/upload_images/5915508-882de951602fc059.png?imageMogr2/auto-orient/strip%7CimageView2/2/w/1240)

写完 WAL 日志文件后，HRegionServer 根据 Put 中的 TableName 和 RowKey 找到对应的 HRegion，并根据 Column Family 找到对应的 HStore，并将 Put 写入到该 HStore 的 MemStore 中。此时写成功，并返回通知客户端。
![写 region](https://upload-images.jianshu.io/upload_images/5915508-407767d8e4b4e184.png?imageMogr2/auto-orient/strip%7CimageView2/2/w/1240)

## MemStore Flush
MemStore 是一个 In Memory Sorted Buffer，在每个 HStore 中都有一个 MemStore，即它是一个 HRegion 的一个 Column Family 对应一个实例。它的排列顺序以 RowKey、Column Family、Column 的顺序以及 Timestamp 的倒序，如下所示：
![image.png](https://upload-images.jianshu.io/upload_images/5915508-4e8113b89e6ff787.png?imageMogr2/auto-orient/strip%7CimageView2/2/w/1240)


每一次 Put/Delete 请求都是先写入到 MemStore 中，当 MemStore 满后会 Flush 成一个新的 StoreFile(底层实现是HFile)，即一个 HStore(Column Family) 可以有0个或多个 StoreFile(HFile)。有以下三种情况可以触发 MemStore 的 Flush 动作，需要注意的是 MemStore 的最小 Flush 单元是 HRegion 而不是单个 MemStore。

1.  当一个 MemStore 的大小超过了 hbase.hregion.memstore.flush.size 的大小，默认128MB。此时当前的 HRegion 中所有的 MemStore 会 Flush 到 HDFS 中。
2.  当全局 MemStore 的大小超过了 hbase.regionserver.global.memstore.upperLimit 的大小，默认40％的内存使用量。此时当前 HRegionServer 中所有 HRegion 中的 MemStore 都会 Flush 到 HDFS 中，Flush 顺序是 MemStore 大小的倒序，直到总体的 MemStore 使用量低于hbase.regionserver.global.memstore.lowerLimit，默认38%的内存使用量。
3.  当前 HRegionServer 中 WAL 的大小超过了 hbase.regionserver.hlog.blocksize * hbase.regionserver.max.logs 的数量，当前 HRegionServer 中所有 HRegion 中的MemStore 都会 Flush 到 HDFS 中，Flush 使用时间顺序，最早的 MemStore 先Flush 直到 WAL 的数量少于 hbase.regionserver.hlog.blocksize * hbase.regionserver.max.logs。这里说这两个相乘的默认大小是2GB，查代码，hbase.regionserver.max.logs 默认值是 32，而 hbase.regionserver.hlog.blocksize 是 HDFS 的默认 blocksize，32MB。但不管怎么样，因为这个大小超过限制引起的Flush 不是一件好事，可能引起长时间的延迟，因而这篇文章给的建议：“Hint: keep hbase.regionserver.hlog.blocksize * hbase.regionserver.maxlogs just a bit above hbase.regionserver.global.memstore.lowerLimit * HBASE_HEAPSIZE.”。并且需要注意，这里给的描述是有错的(虽然它是官方的文档)。

在 MemStore Flush 过程中，还会在尾部追加一些 meta 数据，其中就包括 Flush 时最大的 WAL sequence 值，以告诉 HBase 这个 StoreFile 写入的最新数据的序列，那么在 Recover 时就直到从哪里开始。在 HRegion 启动时，这个 sequence 会被读取，并取最大的作为下一次更新时的起始 sequence。
![flush](https://upload-images.jianshu.io/upload_images/5915508-7b00a14e95dfeedb.png?imageMogr2/auto-orient/strip%7CimageView2/2/w/1240)

## HFile格式
HBase 的数据以 KeyValue(Cell) 的形式顺序的存储在 HFile 中，在 MemStore 的 Flush 过程中生成 HFile，由于 MemStore 中存储的 Cell 遵循相同的排列顺序，因而 Flush 过程是顺序写，我们知道磁盘的顺序写性能很高，因为不需要不停的移动磁盘指针。(同 kafka)
![hfile](https://upload-images.jianshu.io/upload_images/5915508-bb392b442b73e23a.png?imageMogr2/auto-orient/strip%7CimageView2/2/w/1240)

HFile 参考 BigTable 的 SSTable 和 Hadoop 的 TFile 实现，从 HBase 开始到现在，HFile 经历了三个版本，其中 V2 在 0.92 引入，V3 在 0.98 引入。首先我们来看一下V1的格式：
![v1](https://upload-images.jianshu.io/upload_images/5915508-4ab4fbfae58b31d4.png?imageMogr2/auto-orient/strip%7CimageView2/2/w/1240)

V1 的 HFile 由多个 Data Block、Meta Block、FileInfo、Data Index、Meta Index、Trailer 组成，其中 Data Block 是 HBase 的最小存储单元，在前文中提到的 BlockCache 就是基于 Data Block 的缓存的。一个 Data Block 由一个魔数和一系列的 KeyValue(Cell) 组成，魔数是一个随机的数字，用于表示这是一个Data Block类型，以快速监测这个 Data Block 的格式，防止数据的破坏。Data Block 的大小可以在创建 Column Family 时设置 (HColumnDescriptor.setBlockSize())，默认值是64KB，大号的Block有利于顺序Scan，小号Block利于随机查询，因而需要权衡（影响查询性能，因为 data block 是最小存储单元，在查询时是缓存在blockcache 中的最小单元）。Meta 块是可选的，FileInfo 是固定长度的块，它纪录了文件的一些Meta 信息，例如：AVG_KEY_LEN,  AVG_VALUE_LEN,  LAST_KEY,  COMPARATOR,  MAX_SEQ_ID_KEY 等。Data Index 和 Meta Index 纪录了每个 Data 块和 Meta 块的起始点、未压缩时大小、Key 等。Trailer 纪录了 FileInfo、Data Index、Meta Index 块的起始位置，Data Index 和 Meta Index 索引的数量等。其中 FileInfo 和 Trailer 是固定长度的。

HFile 里面的每个 KeyValue 对就是一个简单的 byte 数组。但是这个 byte 数组里面包含了很多项，并且有固定的结构。我们来看看里面的具体结构：
![](https://upload-images.jianshu.io/upload_images/5915508-3a6b80d816b93598.png?imageMogr2/auto-orient/strip%7CimageView2/2/w/1240)


开始是两个固定长度的数值，分别表示Key的长度和Value的长度。紧接着是Key，开始是固定长度的数值，表示 RowKey 的长度，紧接着是 RowKey，然后是固定长度的数值，表示 Family 的长度，然后是 Family，接着是 Qualifier，然后是两个固定长度的数值，表示 Time Stamp 和 Key Type（Put/Delete）。Value 部分没有这么复杂的结构，就是纯粹的二进制数据了。随着 HFile 版本迁移，KeyValue(Cell) 的格式并未发生太多变化，只是在V3版本，尾部添加了一个可选的Tag数组。

HFileV1 版本在实际使用过程中发现它占用内存多，并且 Bloom File 和 Block Index会变的很大，而引起启动时间变长。其中每个 HFile 的 Bloom Filter 可以增长到 100MB，这在查询时会引起性能问题，因为每次查询时需要加载并查询 Bloom Filter，100MB 的 Bloom Filerv会引起很大的延迟；另一个，Block Index 在一个 HRegionServer 可能会增长到总共 6GB，HRegionServer 在启动时需要先加载所有这些 Block Index，因而增加了启动时间。为了解决这些问题，在0.92版本中引入HFileV2版本：
![v2](https://upload-images.jianshu.io/upload_images/5915508-1da7fd9a5f36f12c.png?imageMogr2/auto-orient/strip%7CimageView2/2/w/1240)

在这个版本中，Block Index和Bloom Filter添加到了Data Block中间，而这种设计同时也减少了写的内存使用量；另外，为了提升启动速度，在这个版本中还引入了延迟读的功能，即在HFile真正被使用时才对其进行解析。

FileV3 版本基本和 V2 版本相比，并没有太大的改变，它在 KeyValue(Cell) 层面上添加了 Tag 数组的支持；并在 FileInfo 结构中添加了和 Tag 相关的两个字段。关于具体 HFile 格式演化介绍，可以参考这里。

对 HFileV2 格式具体分析，它是一个多层的类B+树索引，采用这种设计，可以实现查找不需要读取整个文件：
![v2 索引](https://upload-images.jianshu.io/upload_images/5915508-d73ed7046030c1a5.png?imageMogr2/auto-orient/strip%7CimageView2/2/w/1240)

Data Block 中的 Cell 都是升序排列，每个 block 都有它自己的 Leaf-Index，每个Block 的最后一个 Key 被放入 Intermediate-Index 中，Root-Index 指向 Intermediate-Index。在 HFile 的末尾还有 Bloom Filter 用于快速定位没有在某个 Data Block 中的 Row；TimeRange 信息用于给那些使用时间查询的参考。在 HFile 打开时，这些索引信息都被加载并保存在内存中，以增加以后的读取性能。

# HBase 读的实现
通过前文的描述，我们知道在 HBase 写时，相同 Cell(RowKey/ColumnFamily/Column相同) 并不保证在一起，甚至删除一个 Cell 也只是写入一个新的 Cell，它含有 Delete 标记，而不一定将一个 Cell 真正删除了，因而这就引起了一个问题，如何实现读的问题？要解决这个问题，我们先来分析一下相同的Cell 可能存在的位置：首先对新写入的 Cell，它会存在于 MemStore 中；然后对之前已经 Flush 到 HDFS 中的 Cell，它会存在于某个或某些 StoreFile(HFile) 中；最后，对刚读取过的 Cell，它可能存在于 BlockCache 中。既然相同的Cell可能存储在三个地方，在读取的时候只需要扫瞄这三个地方，然后将结果合并即可 (Merge Read)，在 HBase 中扫瞄的顺序依次是：BlockCache、MemStore、StoreFile(HFile)。其中 StoreFile 的扫瞄先会使用 Bloom Filter 过滤那些不可能符合条件的 HFile，然后使用 Block Index 快速定位 Cell，并将其加载到 BlockCache 中，然后从 BlockCache 中读取。我们知道一个 HStore 可能存在多个 StoreFile(HFile)，此时需要扫瞄多个 HFile，如果 HFile 过多又是会引起性能问题。
![hbase读](https://upload-images.jianshu.io/upload_images/5915508-73fad95ac4ef7d9c.png?imageMogr2/auto-orient/strip%7CimageView2/2/w/1240)


# Compaction
而过多的 HFile 会引起读的性能问题，HBase 采用 Compaction 机制来解决这个问题，有点类似 Java 中的 GC 机制，起初 Java 不停的申请内存而不释放，增加性能，然而天下没有免费的午餐，最终我们还是要在某个条件下去收集垃圾，很多时候需要 Stop-The-World，这种 Stop-The-World 有些时候也会引起很大的问题，因而设计是一种权衡，没有完美的。还是类似 Java 中的 GC，在 HBase 中 Compaction 分为两种：Minor Compaction 和 Major Compaction。

1. Minor Compaction 是指选取一些小的、相邻的 StoreFile 将他们合并成一个更大的 StoreFile，在这个过程中不会处理已经 Deleted 或 Expired 的 Cell。更少并且更大的StoreFile。（这个是对的吗？BigTable中是这样描述Minor Compaction的：As write operations execute, the size of the memtable in- creases. When the memtable size reaches a threshold, the memtable is frozen, a new memtable is created, and the frozen memtable is converted to an SSTable and written to GFS. This minor compaction process has two goals: it shrinks the memory usage of the tablet server, and it reduces the amount of data that has to be read from the commit log during recovery if this server dies. Incoming read and write operations can continue while compactions occur. 也就是说它将 memtable 的数据flush 的一个 HFile/SSTable 称为一次 Minor Compaction）

2. Major Compaction 是指将所有的 StoreFile 合并成一个 StoreFile，在这个过程中，标记为 Deleted 的 Cell 会被删除，而那些已经 Expired 的 Cell 会被丢弃，那些已经超过最多版本数的 Cell 会被丢弃。一次 Major Compaction 的结果是一个 HStore 只有一个 StoreFile 存在。Major Compaction 可以手动或自动触发，然而由于它会引起很多的IO操作而引起性能问题，因而它一般会被安排在周末、凌晨等集群比较闲的时间。

更形象一点，如下面两张图分别表示 Minor Compaction 和 Major Compaction。
![minor](https://upload-images.jianshu.io/upload_images/5915508-26b74143eab59846.png?imageMogr2/auto-orient/strip%7CimageView2/2/w/1240)

![major](https://upload-images.jianshu.io/upload_images/5915508-b5d06ee02ca6b849.png?imageMogr2/auto-orient/strip%7CimageView2/2/w/1240)

# HRegion Split
最初，一个 Table 只有一个 HRegion，随着数据写入增加，如果一个 HRegion 到达一定的大小，就需要 Split 成两个 HRegion，这个大小由 hbase.hregion.max.filesize 指定，默认为10GB。当 split 时，两个新的 HRegion 会在同一个 HRegionServer 中创建，它们各自包含父 HRegion 一半的数据，当 Split 完成后，父 HRegion 会下线，而新的两个子 HRegion 会向 HMaster 注册上线，处于负载均衡的考虑，这两个新的 HRegion 可能会被 HMaster 分配到其他的 HRegionServer 中。关于Split的详细信息，可以参考这篇文章：[《Apache HBase Region Splitting and Merging》。](https://hortonworks.com/blog/apache-hbase-region-splitting-and-merging/)
![split](https://upload-images.jianshu.io/upload_images/5915508-5b9c09d54e6f3431.png?imageMogr2/auto-orient/strip%7CimageView2/2/w/1240)


# HRegion负载均衡
在 HRegion Split 后，两个新的 HRegion 最初会和之前的父 HRegion 在相同的 HRegionServer 上，出于负载均衡的考虑，HMaster 可能会将其中的一个甚至两个重新分配的其他的 HRegionServer中，此时会引起有些
HRegionServer 处理的数据在其他节点上，直到下一次 Major Compaction 将数据从远端的节点移动到本地节点。
![hregion 负载均衡](https://upload-images.jianshu.io/upload_images/5915508-ad67b6bcd6103397.png?imageMogr2/auto-orient/strip%7CimageView2/2/w/1240)


# HRegionServer Recovery
当一台 HRegionServer 宕机时，由于它不再发送 Heartbeat 给 ZooKeeper 而被监测到，此时 ZooKeeper 会通知 HMaster，HMaster 会检测到哪台 HRegionServer 宕机，它将宕机的 HRegionServer 中的 HRegion 重新分配给其他的 HRegionServer，同时 HMaster 会把宕机的 HRegionServer 相关的 WAL 拆分分配给相应的
HRegionServer (将拆分出的WAL文件写入对应的目的 HRegionServer 的 WAL 目录中，并写入对应的 DataNode中），从而这些 HRegionServer 可以 Replay 分到的 WAL 来重建 MemStore。
![recovery](https://upload-images.jianshu.io/upload_images/5915508-6998fd8e7cbf4ea9.png?imageMogr2/auto-orient/strip%7CimageView2/2/w/1240)


# HBase架构简单总结
在NoSQL中，存在著名的CAP理论，即 Consistency、Availability、Partition Tolerance 不可全得，目前市场上基本上的 NoSQL 都采用 Partition Tolerance 以实现数据得水平扩展，来处理 Relational DataBase 遇到的无法处理数据量太大的问题，或引起的性能问题，因而只有剩下 C 和 A 可以选择。HBase 在两者之间选择了Consistency，然后使用多个 HMaster 以及支持 HRegionServer 的 failure 监控、ZooKeeper 引入作为协调者等各种手段来解决 Availability 问题，然而当网络的 Split-Brain(Network Partition) 发生时，它还是无法完全解决 Availability 的问题。从这个角度上，Cassandra 选择了A，即它在网络 Split-Brain 时还是能正常写，而使用其他技术来解决 Consistency 的问题，如读的时候触发 Consistency 判断和处理，这是设计上的限制。

