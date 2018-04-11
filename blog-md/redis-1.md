---
title: Redis 高可用之 Replication 部署与原理

tags:
  - redis
  - replication

categories:
  - Redis

comments: true
date: 2016-01-10 23:00:00

---
Redis 是一款开源的内存db，属于 nosql，可以被用作存储、缓存、消息队列等，非常受青睐！Redis 性能优异，并且提供了非常丰富的数据结构，使开发变得简单，同时其提供了內建的数据持久化方案、主从复制机制，能可靠保证数据。

HA 是 database 不可避免的一个话题，官方在 3.x 版本提供的高可用方案是 Replication + Sentinel，本文将介绍 Replication 的原理以及配置方案，下一篇文章会介绍 Sentinel 的原理以及使用。

# 原理
Redis 提供的主从复制包含 一台 master，若干 slaves，slaves 会不断的复制 master 上的数据，redis 主从复制的过程简单来说可以分成两部分：同步和命令传播。

同步又分为全量同步和部分同步，同步的过程是将 slave 的状态更新到和 master 一致
当状态一致后，进入命令传播阶段，这里一阶段，master 会将所有收到的写命令同步给 slave，持续的保证主从状态一致。
这种主从复制的模式和 mysql 主从复制相似，首先通过 mysqldump 导出主的数据到从，然后通过 binlog 做后续的数据同步。

## 全量同步
全量同步的逻辑比较简单：

1. master 收到同步请求后，如果判断执行全量同步，其会执行 bgsave 命令，在后台生成一个 rdb 文件，同时会 buffer 这之后所有来自 clients 的 写命令。
2. bgsave 命令完成后，master 将生成的 rdb 文件发送给 slave ，slave 会接收并加载这部分数据，然后 master 会把 buffer 的那部分写请求命令发送给 slave，slave 执行这些命令后将和 master 数据状态达成一致，全量同步完成，之后会进入命令传播阶段
3. 全量同步很消耗资源，因为每次都要触发 bgsave 操作，在生产环境中 14 gb 的数据 bgsave 耗时超过 2min，还要发生网络传输， 所以在要尽量避免（第一层同步除外）。在 redis 在 2.8 之后引入了增量同步，增量同步可以有效避免由于网络问题等因素导致主从链接断线重连后（短时间场景下）频繁的全量同步。

当然 slave 首次连接 master 请求同步时，不可避免的会发生全量同步。

## 增量同步
增量同步的实现依赖于两个关键点 “offset” 和 “backlog”，这个 offset 主、从各自会维护一份，master 每次在向 slave 同步数据后会相应的增大自身的 offset，slave 每次接受数据后也会增大自己的 offset，通过对比主从 offset 可以确定主从同步的数据状态。backlog 的功能则类似（mysql binlog），只不过其只是缓存最近的写命令。

backlog 结构类似：

| offset | 1000 |1001 |1002 | ... |
|---|---|---|---|---|
|byte  |   s    |   e    |   t    |...|

增量同步逻辑如下：

1. master 会维护一组` Replication ID，offset` 数据，id 作为当前 master 的唯一表示，offset 则记录 master 的偏移量（递增的），同时会维护一个 `replication backlog`,  它是一个 FIFO queue，如上文所说，缓存最近的写命令。
当 slave 重连 master 后（增量同步一定发生在重连场景下），会再次向 master 发送同步命令，命令包含 master 的 id，以及 slave 当前的 offset。
2. master 收到 slave 同步请求并判断需要执行增量同步（下文会分析何时触发）时，会将 backlog 中slave offset 后的所有数据发送给 slave
3. slave 接受到master 之后的数据后和 master 数据状态又会达到一致，之后再次进入命令传播阶段

## 全量同步 or 增量同步
当使用 slave of 命令后，或 slave 启动时其配置文件中包含 slave of 相关内容，会触发 Replication ，进入同步过程，这一阶段slave 会根据自身同步状态发送不同的 psync 参数，master 也会根据 psync 参数，判断全量同步还是增量同步。

同步过程由 slave 发起，其会向 master 发送 psync 命令请求同步，分为两种情况：
- 当一个 slave 之前没有向一个 master 同步过，会向 master 发送一个 “psync ？ -1” 命令
- 反之，则表明之前 slave 已经复制过某个 master ，slave 会向 master 发送一个 “psync id offset” 的命令，其中 id 是其之前同步的 master 的id，offset 是 slave 同步的偏移量（作为标记）

当 master 接受到 psync 后会判断执行全量同步 or 部分同步：
- 如果命令是第一种情况，则表明这是一个新的 slave，会触发全量同步，
- 第二种情况下，master 会判断命令中的 id 和 offset 参数，如果 id 是当前 master id 且 offset 存在于 master 的 backlog 内（即 slave offset >= min(backlog offset)），这时触发全量同步，否则增量同步。

## 命令传播
命令传播阶段也很简单，master 单纯的将命令写入 backlog，同时同步给 slave，slave 负责接收并执行即可。

这一阶段还会定时的发生 slave 向 master 的心跳监测，默认配置是 slave 每1秒向 master 发送一次心跳，并包含 slave 当前的 offset，master 会记录每个从的数据。这些指标可以通过 info Replication 命令查看到，参考下文部署阶段。

# 部署
首先正常启动一个 master 实例：
```
zhaif@mbp ~> redis-server /usr/local/etc/redis.conf
```

连接到 master，通过 info replication 命令可以看到 master 正常启动：
```
127.0.0.1:6379> info replication
# Replication
role:master
connected_slaves:0
master_replid:f9e9064f780bc4647d18867da0b99682d8255270
master_replid2:0000000000000000000000000000000000000000
master_repl_offset:0
second_repl_offset:-1
repl_backlog_active:0
repl_backlog_size:1048576
repl_backlog_first_byte_offset:0
repl_backlog_histlen:0
```

修改 slave 的 conf 文件中的 “slaveof” 配置，指定 master 的 ip 和 port
```
# slaveof <masterip> <masterport>
slaveof 127.0.0.1 6379
```

启动 slave，并连接到 slave，通过“info replication” 命令可以发现 slave 正常启动：
```
127.0.0.1:6380> info replication
# Replication
role:slave
master_host:127.0.0.1
master_port:6379
master_link_status:up
master_last_io_seconds_ago:9
master_sync_in_progress:0
slave_repl_offset:28
slave_priority:100
slave_read_only:1
connected_slaves:0
master_replid:07fb79941eb848159a9acf1aed2e79999ff2368e
master_replid2:0000000000000000000000000000000000000000
master_repl_offset:28
second_repl_offset:-1
repl_backlog_active:1
repl_backlog_size:1048576
repl_backlog_first_byte_offset:1
repl_backlog_histlen:28
```

同时，连接 master，使用 “info replication” 命令可以看到master 和 slave 的 offset 以及 lag，其中 lag 是上次 slave 向 master 发送心跳到现在的时间间隔，单位是秒，这个值大于 1 就不正常了。
```
127.0.0.1:6379> info replication
# Replication
role:master
connected_slaves:1
slave0:ip=127.0.0.1,port=6380,state=online,offset=230,lag=0
master_replid:07fb79941eb848159a9acf1aed2e79999ff2368e
master_replid2:0000000000000000000000000000000000000000
master_repl_offset:230
second_repl_offset:-1
repl_backlog_active:1
repl_backlog_size:1048576
repl_backlog_first_byte_offset:1
repl_backlog_histlen:230
```

# Tips
同步过程中应该尽量避免全量同步，如果在生产环境频繁的发生全量同步，可以适当的增大 backlog，默认 1MB 的配置在高频的写场景偏低。

# 参考文档：
https://redis.io/topics/replication
