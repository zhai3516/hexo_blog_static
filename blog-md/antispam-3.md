---
title: Wukong—知乎反作弊系统性能优化(三)

tags:
  - antispam
  - wukong
  - 性能优化

categories:
  - antispam

comments: true
date: 2016-11-30 21:00:00

---
# **RPC优化**

前一篇文章提到，Policy是wukong检测spam的主要方法。其触发判定分大致可分为两步：

1.  recent_events读取关联actions数据
2.  对获取的actions进行filter判定

前文重点介绍了recent_events的缓存优化方案，使得Policy通过recent_events相关方法能在极短时间内的查询的数据量增到3000，从而极大的解决的存储I/O方面的瓶颈。然而，又产生了另一方面的问题， 在对actions进行过滤的过程中，wukong系统会根据每一个过滤条件逐条检测数据，检测的过程中依赖了许多服务，存在很多计算。

Wukong如流式系统一样处理每一个新生成的action，通过recent_events获取的关联数据则近似一个滑动窗口，每处理一个同类型的action时，这个滑动窗口向前移动一次。很容易就可以发现，在这种情景下，会有大量重复的计算。在wukong2.0中计算的结果短期内是cache在redis中的，但在wukong3.0的场景下，处理每个action时由于获取的关联actions数量增大，相应的计算量和查询量也会大幅增加，检测时间变长，带给redis极大的压力，这种问题在数据查询量增值1000时已经尤为明显了（对redis的压力几乎成正比）。

所以又是同样的问题—redis-cache！

同样的解决思路，使用LocalCache+RedisCache二级缓存思路，减少网络I/O。基于滑动窗口式的处理模型，我们这里使用的是FIFO的缓存策略（关于LocalCache的实现代码参考[python3.5functions_tool中的lru_cache方法](https://hg.python.org/cpython/file/3.5/Lib/functools.py) 这里不在详细阐述）。

图一 wukong 策略处理一条数据的时间

上图是增加二级缓存后每条策略处理`3000`条actions的时间，可见增加二级缓存后每条策略处理`3000`条数据的平均时间在`10ms`左右。

在接入LocalCache后，我们同时不得不考虑另一个问题，那就数缓存大小，目前wukong系统一个Context Worker（处理action数据的进程，每个Worker跑在一个单独的容器上）缓存一个小时的数据量在峰值时期超过1G，加上程序自身需要的内存，一个Worker所需的内存要超过1.5G，这是一个很难接受的数据，所以下一个待解决的问题就是压缩存储空间。

目前Worker处理一条数据的流程如图，每个Worker缓存近一个小时内所有的数据，会对任意类型的action检测所有策略。

图二 Worker处理action的数据流程图

可以发现，在处理一个answer类型的数据时，缓存的其他类型例如question，vote等相关数据对它来说是无效或者无用的，也就是说有虽然缓存命中率很高，但是有效缓存占比很低。基于这一点，我们增加一个Checker，Checker会根据action的类型，将之分配到不同的任务队列，这样每个Worker只会处理一种类型的数据，所以也只会缓存一种类型的数据，如图九。

图三 优化后Worker处理action的数据流程图
