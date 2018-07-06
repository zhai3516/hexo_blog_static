---
title: GFS 小结

tags:
  - GFS
  - 分布式

categories:
  - paper
  - 分布式

comments: true
date: 2017-06-12 17:00:00

---
提到分布式系统，有一个无法绕开的话题—— Google 三驾马车。本文就  [GFS](https://research.google.com/archive/gfs-sosp2003.pdf)  概括介绍。

# 设计思路
与传统的分布式系统相比，在大方向上，GFS 同样追求高性能、高可靠性、高可用性，同时 Google 基于自身的生产环境、技术环境，有一些特殊的设计思路。

1. 组件失效是常态化的，而非意外。在 GFS 成百上千的集群中，随时随地都可能发生故障导致机器宕机甚至无法恢复，所以，监控、容灾、自动恢复是必须整合在 GFS 中的。

2. 文件巨大。GB 级别的数据非常普遍，所以设计的过程中 I/O、Block 尺寸等指标应以此为参考。

3. 绝大多数文件的写操作都是追加（Append），而非修改（Overwrite）。通常的文件场景是顺序写，且顺序读。

4. 应用程序 client 和 GFS API 协同设计，提高灵活性。

# 设计架构
GFS 架构比较简单，一个 GFS 集群一般由一个 master 、多个 chunkserver 和多个 clients 组成，在 GFS 中，所有文件被切分成若干个 chunk，并且每个 chunk 拥有唯一不变的标识（在 chunk 创建时，由 master 负责分配），所有 chunk 都实际存储在 chunkserver 的磁盘上。为了容灾，每个 chunk 都会被复制到多个 chunkserver。
系统架构如下：
![GFS 架构](https://upload-images.jianshu.io/upload_images/5915508-5e4df9d9d8236577.png?imageMogr2/auto-orient/strip%7CimageView2/2/w/1240)

在整个集群中，为了简化设计，master 是单节点，它管理着所有文件系统的所有 metadata：命名空间、访问控制信息、文件和 chunk 的映射关系、chunk 的存储位置。同时 master 还管理系统范围内的各种活动：chunk 创建、复制、迁移、回收，chunk lease 等等，是系统中最核心的部分，后面会继续进一步描述 master 是如何工作的。

Chunkserver 真正存储着所有 chunk，chunkserver 依托于 linux 文件系统，所以它本身不需要缓存文件数据，直接利用 linux 系统的数据缓存，简化了设计。

# Master 详解
Master 是整个 GFS 的核心，这里重点介绍下 master 的存储以及工作。
## Metadata
所有的元数据都存储在 Master 的内存中，以保证 Master 的性能。大部分元数据同时会以变更记录的形式保存到操作日志中，操作日志会在本地磁盘中持久化同时被复制到其他的 Master 上（虽然是 single master，但是会有备份节点备份 Master 的相关数据，比如操作日志、checkpoint 文件，以保证可靠性）。

Master 会在后台周期性的扫描所保存的状态信息，因为全部在内存中，所以效率非常高。通过这种周期性的扫描，master 实现 chunk 回收、chunkserver 宕机时 chunk 的复制、以及迁移 chunk ，实现 chunkserver 的负载均衡。 

但是， chunk 的位置信息不会被持久化，而是在每次 master 启动时（以及启动后定期执行），或有 chunkserver 加入时，master 会轮训所有 chunkserver 获取所有的 chunk 信息然后保存在内存中。这种方式简化了 master 和 chunkserver 的数据同步，当然数据定期轮训的缺点就是实时性稍差。

操作日式是元数据唯一的持久化记录，它还定义了并发操作的执行顺序的逻辑时间线，所以操作日志的完整性得到保证，才能保证 GFS 的可靠性，否则会丢失文件或者 client 的操作。因此操作日志会被复制到多台备份节点，而且，只有 master 把操作日志持久化到本地并且复制到远程之后，才会响应客户端的请求，保证数据不丢失。

随着时间的增长，操作日志会越来越大，当日止增长到一定量时，master 会将所有的系统状态做一次 checkpoint（可以理解为持久化某一个时间点的全部状态数据），后续的操作变更会写入到新的日志文件，这样在重启或灾难恢复时，master 只需要加载最新的 checkpoint 文件到内存，然后重新执行最新的一部分操作日志即可。（这也是比较通用的一种灾备方法，定期做 checkpoint，然后重新记录操作日志，恢复时基于 checkpoint + operation log）

Checkpoint 文件以压缩 B- 树的结构存储，能直接映射到内存，无需额外解析，大幅提升了速度。同时创建 checkpoint 时，master 会启动独立的线程，不会阻塞正在进行的操作。

## Operation
Master 节点执行所有的命名空间管理、chunk管理以及负责垃圾回收。

### 命名空间管理
Master 在操作命名空间是基于锁实现的，在操作对应的文件或目录时，会给对应的文件/目录加读锁以及读写锁，eg：对于一个 /home/usr/zhaif 的操作，会依次给父目录 /home，/home/usr 加读锁，读锁可以防止正在读取得文件、父目录被删除、改名，同时给  /home/usr/zhaif 加读锁或写锁（根据操作类型），当对操作目标的操作是修改类操作时，会加写锁，保证并发场景下互斥写。

### Chunk 管理
上文提到，master 会负责 chunk 副本的存储位置，即存储在哪些 chunkserver 上，master 会最大化的保证数据可靠性，同时最大化利用网络带宽。

在创建一个 chunk 时，master 选择存储空副本的初始位置时，会考虑一下几点：
1. 倾向于选择硬盘使用率低于平均水平的 chunkserver
2. 限制每个 chunkserver 最近一段时间的创建次数。因为创建后往往意味着后续大量的写入。
3. 分散在多机架

除了管理 chunk 副本的存储位置，master 会在 chunk 有效副本数小于指定数量时重新复制 chunk 副本，以保证数据可靠性。

最后，Master 会定期对所有副本负载均衡，检查当前副本分布情况，然后移动副本位置以更搞笑的利用硬盘空间和负载。

### 垃圾回收
GFS 的文件删除不会立刻回收物理空间，而是惰性的（现如今，惰性回收在存储系统中是一种比较常见的策略，比如 redis 回收过期数据，分配的内存空间）。这种回收机制使系统更简单、更可靠、更高效。

当一个文件被删除时，master 只是将文件改名，标记为已删除。Master 会对命名空间做定期扫描，会删除一定时间前标记删除的文件，同时删除其在命名空间中的记录以及相关元数据，此时一个文件才被真正的删除。

Master 在常规定期扫描的过程中会发现一些孤儿 chunk，即不被任何文件包含的 chunk，然后删除他们的元数据。Chunkserver 在和 master 定期交互时，汇报了其所有的 chunk 信息，master 会告知其不存在的 chunk，chunkserver 得知后会删除这些 chunk 副本。

这种惰性删除的主要问题是空间利用率，尤其的在存储空间紧缺时。所以 GFS 也提供了通过显示的再删除一次已经删除的文件来加速空间回收，另外也允许用户根据需要对不同的目录设置不同的回收策略，eg：指定用些目录的删除策略为即时删除，而不是惰性删除。

### 失效副本检测
Master 的写操作是基于 lease 机制（后文介绍），当 master 每次分配 lease 时都会增加对应的 chunk 的版本号，然后所用最新的副本，通过版本号区分当前的和过期的副本。

# 读写操作实现
GFS 在设计是采用 client 和 API 协同设计的思路，所以在读写过程中 client 也不单纯是发读请求或写请求，还包括其他一些操作。
## 读实现
Client 不通过 master 节点读写文件，而是从 master 那获取读写操作的需要联系的 chunkserver，为了避免频率的和 master 联系，client 会缓存 从 master 获取的 metadata，后续操作直接和 chunkserver 沟通实现读写。一次简单的读流程如下：

1. Client 把要读去的文件名和 offset，根据配置的 chunk 大小，计算出文件的 chunk 索引，然后加文件名和索引一起发送到 master，master 会返回对应 chunk 副本位置信息，client 以文件名+chunk索引作为 key 缓存此数据。

2. 之后 client 会直接和包含此 chunk 的 chunkserver 联系获得文件数据。

3. 实际上，client 一般会在一次请求中查询多个 chunk 信息，而 master 的 response 中也一般会包含所请求 chunk 之后的一些 chunk 信息，以尽量减少 client 和 master 之间的通讯。 

## 写实现
相较于读操作，写实现更为复杂一些。所有的写入操作会在所有 chunk 的副本上执行，GFS 采用 `lease` 机制来保证多个 chunk 副本之间变更顺序一致。

Master 会选择一个副本分配 lease，拥有这个 lease 的 chunk 被称为 primary，其他副本则是 secondary。Primary 会将对 chunk 的操作序列化，然后其他 secondary 按也这个序列执行修改，从而保证所有副本变更一致。

Lease 有效期初始为 60s，primary chunk 在完成修改操作后可以申请延长 lease 有效期，同样的 master 在一些情况下可以提起取消 lease。Master 和 chunkserver 之间会有定期的心跳监测，传递心跳信息是可以带上这些 lease 的验证请求或者批准信息。Lease 机制极大的简化的 master 的负担，将写操作保证数据一致性的工作分担给 chunkserver，使得 master 变得很轻量。

下图是一次写操作的流程： 
![写实现](https://upload-images.jianshu.io/upload_images/5915508-4391c3dcc9fa248b.png?imageMogr2/auto-orient/strip%7CimageView2/2/w/1240)
1. Client 向 master 询问要修改的 chunk 被哪个 chunkserver 持有 lease，以及 chunk 其他副本的位置信息。
2. Master 返回 primary 以及 secondary 给 client。
3. Client 把所有数据推送给 primary 和 secondary，注意这里推送的只有数据。
4. 当所有副本都确认收到数据后，client 发送写请求给 primary，primary 为来自不同 client 的操作分配序号，保证操作顺序执行。
5. Primary 把写请求发送到 secondary，secondary 按照 primary 分配的序号顺序执行所有操作
6. 当 Secondary 执行完后回复 primary 执行结果。
7. Primary 回复 client 执行结果。

GFS 将写操作拆分为数据流（对应3）和控制流（对应4），数据流以 Pipline 的方式推送到所有副本。

## 原子记录追加
GFS 同时提供了一个种原子的写入操作——记录追加。相比普通的写入操作，追加只需指定要写入的数据，不需要提供偏移量（即要写入的位置）。GFS 会保证追加操作至少一次原子性写入。记录追加的控制流程同上文描述基本相同，却别在于 primary 会检测此次追加后 chunk 是否超过最大值，如果达到最大值，primary 会先将当前 chunk 填充满，然后同步给 secondary 同样操作，然后回复 client 要求其对下一个 chunk 重新执行追加操作。 

原子记录追加操作在避免了使用一个分布式锁带来的开销，对于多 producer，单 consumer的场景以及合并多个来源文件的场景很契合。

## 一致性
GFS 是一个分布式系统，为了更好的 AP，一定程度上降低了对 C 的要求，其一致性模型是比较宽松。下图是变更后文件状态，其中：
- consistent 表示所有 client 从任意副本读取得数据相同
- defined 表示在数据变更后，如果是 consistent，并且 client 能够读取到它的所有变更
![文件 region 相关操作后的状态](https://upload-images.jianshu.io/upload_images/5915508-21218b1b6b39f650.png?imageMogr2/auto-orient/strip%7CimageView2/2/w/1240)

从上文的写入数据流程可以发现，串行的写数据secondary 和 primary 操作顺序是一直的，如果成功，则一定是 defined，如果失败，则不一致，比如 primary 写成功了，而有一个 secondary 写失败。同样的道理，在并行场景下，写失败会不一致，但是成功的话只能保证一致，因为并发操作可能会导致一个文件 region 内包含来自多个 client 的写操作，所以是 undefined.

记录追加操作是原子的，GFS对于此操作能保证的是 `至少一次成功` 语义，所以有可能会在某个副本上发生多次追加，但是 GFS 返回给 client 的 offset 都是 defined region 的起点，如果这期间在某个副本的操作被重复追加了，此时它的 offset 会比其他大，后续的操作对所有副本都会从这个最大的 offset 开始追加，或者被追加到其他 chunk 上，因此对于记录追加操作而言，如果执行成功，文件 region 状态是定义的但会有部分不一致。

GFS 通过 Checksum 叫校验数据是否损坏，比如因为宕机丢失了一些修改操作而导致失效，此时 master 会标记失效，不在返回给 client 失效的副本位置信息，并尽快回收。 对于已经被 client 缓存的失效副本信息，当 client 访问这个失效副本时，一个失效副本会返回提前结束的 chunk，从而 client 能得知重新联系 master 获取最新的位置信息。

另外，正如上文所述， master 也会和 chunkserver 通过心跳来检测宕机，并校验数据有效性，在发现问题后会尽快恢复。

# 高可用性
GFS 通过快速恢复和复制保证整个集群的高可用性，无论 master 还是 chunkserver 都可以在数秒内重启并恢复状态。

## Chunk 复制
Chunk 会被复制到不同的机架上的不同 chunkserver，当某台 chunkserver 失效或者其上的 chunk 已损坏时，master 会继续复制已有的副本，保证每个 chunk 的可用性。

## Master 复制
Master 服务器的状态会被复制，它所有的操作日志、checkpoint 文件都会被复制到多台机器，对 master 服务器的状态的任何操作都要等操作日志被复制到备份节点后本机磁盘后才会被提交生效。所以 Master 宕机后，重启后不会有任何数据丢失，如果无法重启或磁盘故障，则可以选择拥有全部操作日志的备份节点启动一个新的 master 进程。由此可以保证 master 的可靠性。

同时，还存在一些 `shadow master`，在 master 宕机时能可以提供 read-only 服务，但要比 master 慢一些（通常不到 1s），它们通过读取操作日志副本的并顺序执行方式保证其和 master 以相同的方式变更。同样的，shadow master 也会和 chunkserver 定期交互检测 chunkserver状态、拉取数据。
