---
title: Storm入门系列之四：Storm 架构原理简析

tags:
  - storm
  - ha
  - nimbus

categories:
  - Storm

comments: true
date: 2017-02-08 22:00:00
---

# 集群架构
storm 集群的构成比较简单，主要包括三部分：
- Nimbus
- Supervisor
- Zookeeper

具体的构成如图：
![storm 架构图（新）](https://upload-images.jianshu.io/upload_images/5915508-a2eb3ee3d4c90756.png?imageMogr2/auto-orient/strip%7CimageView2/2/w/1240)

在 storm 中，有一个概念——worker， 它是真正运行 storm topology 的进程，实现业务逻辑，Nimbus 和 Supervisor 合作完成 topology 到 worker 的调度分配。

Nimbus 是storm 集群的控制核心，不会运行任何 topology，其接收用户 submit 到集群的 topology  jar，然后将任务分配到 supervisor 的 worker 上，并监控每个 topology 任务的运行状态，保证任务的正常运行。另一方面，nimbus 会监控所有 Supervisor 的状态，当 Supervisor 故障时，将分配给其的任务分配到其他 Supervisor 上，同时保证保证 topology 均匀的运行在所有 Supervisor 进群上。

Supervisor 是一个守护进程，根据 Nimbus 分配的任务启动相应的 worker，并监听 worker 的正常运行。当某些 worker down 并会尝试重启，如果连续的重启失败一定次数后，Supervisor 会将 worker 的情况告知 Nimbus 重新分配。

Zookeeper 则是整个进群的协调者， Nimbus 和 Supervisor 之间的通信主要是通过 Zookeeper 完成的。 Zookeeper 存储着 Supervisor 以及 worker 的心跳信息，保证 Nimbus 能监控整个集群的运行状态。另外，其存储了 topology 的基础信息、状态信息以及任务调度信息，同时还保存的一些 error 信息。Zookeeper 的具体目录结构如下：
![storm-zookeeper 目录结构](https://upload-images.jianshu.io/upload_images/5915508-0ca9d006bb7e631d.png?imageMogr2/auto-orient/strip%7CimageView2/2/w/1240)

一个 topology 从 submit 到运行整个流程大致如下：
>   1. client 提交 topology jar （通过 thrift rpc ）
>   2. Nimbus 收到 submit 请求，校验 topology （比如重名等等），并将 topology 基本信息，以及任务调度信息，写入到 Zookeeper
>   3. Supervisor 订阅 Zookeeper ，发现又新提交的 topology ，启动 worker 执行相关任务，同时 Supervisor 会从 Nimbus 下载 jar 包

在 提交成功后， nimbus 仍然会有一个 thread 定时检测 Supervisor 以及 topology ，根据情况触发重新调度。

# Storm HA

## worker/supervisor
对于 worker 而言，其本质是一个进程，当某个 worker 异常时，Supervisor 作为一个守护进程为监听到这种情况，然后重启 worker 继续运行，保证 worker 层面是高可用的。

对于 Supervisor 而言，当某个 Supervisor 挂了时，会触发 Nimbus 的重新调度，其会将这个

## Nimbus HA

在早期的 storm 版本（1.x 版本前？）中 nimbus 是一个单点，即整个集群只有一个 Nimbus 进程，并不支持 HA。不过因为 Nimbus 本身不执行任务业务 topology 任务，所以，当 Nimbus 宕机时，如果 Supervisor 以及 worker 运行正常，所有 topology 的运行状态依旧是正常的，不受干扰，只不过无法新提交 topology，也不会触发 topology 的重新调度。

在新的版本中 storm 给出了 Nimbus HA 的方案，再集群中可以启动多个 Nimbus。 

### Leader 的选举
Storm Nimbus 中由 leader 负责响应各种请求，完成各种调度，其他 Nimbus 实例作为热备。
![election and failover](https://upload-images.jianshu.io/upload_images/5915508-6563d880581290c6.png?imageMogr2/auto-orient/strip%7CimageView2/2/w/1240)

Nimbus 提供一组 ILeaderElector 接口用以实现选举，官方实现了上图阐述了 Nimbus 依赖 zookeeper 实现 leader 选举的时序过程。大概流程如下

1. 在 Nimbus 启动初始化时，每个 Nimbus 实例会检查是否具有全部激活的 topology jar 包，如果具有，则这个 Nimbus 实例具有成为 leader 的条件，他会 调用 `addToLeaderLockQueue`，加入到leader 候选队列中。
2. 同时 Nimbus 实例会在后台启动一个 thread，不断的同步 topology code。
3. 当某一时间 leader died，zk 选择其他 nimbus 实例成为 leader 时，对应的 nimbus 会check 自己是否具有成为 leader 的条件，即拥有全部激活的 topology jar 包，只有符合条件时，其才会接受成为 master。
4. 之后，因缺少 topology jar 而未成为 leader 的 Nimbus 实例会从其他 Nimubus 拉取 topology jar 包，当它又具备成为其他的条件时，会再次 addToLeaderLockQueue。


# 参考
http://storm.apache.org/releases/1.0.0/Lifecycle-of-a-topology.html
http://storm.apache.org/releases/1.0.0/nimbus-ha-design.html
https://blog.csdn.net/asdfsadfasdfsa/article/details/77855622
