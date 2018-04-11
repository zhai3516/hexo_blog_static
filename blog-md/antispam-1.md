---
title: Wukong—知乎反作弊系统性能优化(一)

tags:
  - antispam
  - 性能优化

categories:
  - antispam

comments: true
date: 2016-10-29 01:08:00

---
悟空是知乎反作弊系统的重要一环，它负责了离线spam的召回和处理。从2016年8月开始我们进行了局部重构（下称Wukong 3.0）。在这里分享一下重构过程中对于缓存的设计和优化思路。

# 名词解释

**Action**: 指用户的一次写行为，如ANSWER_CREATE, ANSWER_VOTE_UP,   QUESTION_CREATE等。Json结构，包含ActionType, UserID, UserIP,  UA,Created等信息

**Policy**: 策略，指由产品定义的spam召回策略。主要包含触发，执行两个部分，触发是指spam召回的触发条件，执行是指spam召回后的处理(如封号等)。两者都为一个python表达式。如图一所示，第一栏为策略名， 第二栏为召回触发条件，第三栏为触发后的处理。

![](https://upload-images.jianshu.io/upload_images/5915508-fc0f8ced87d42b35.png?imageMogr2/auto-orient/strip%7CimageView2/2/w/1240)


**recent_events**: Policy触发条件中的主要函数。主要用于在Policy的触发中召回最近一段时间内(如30分钟，1小时)与该策略相关维度(如ActionType相同，IP相同)的Action集。如图一中的same_type_events(60)表示召回近60分钟内与该Action的ActionType相同的事件集。

在wukong2.0中Action数据存储在mongodb中，因此所有的recent_events操作也从mongodb中读取。对于每一个Action平均都有10条左右的policy要处理，导致mongodb server的负载过高。

Wukong3.0主要目的是解决如下问题：

1. 减轻对mongodb的读压力。

2. 放开对mongodb读的条数限制。

3. 减少RPC调用。

对mongodb的读压力主要体现在两方面：大数据量的查询和很多接近于重复的查询。

接近重复的查询是指，对于相隔时间很短内的多个相同类型的Action，在某些Policy中（如图一的Policy），每一个Action都会调用mongodb查询近60分钟内相同类型的事件（same_type_events(60))。这样的多次mongodb查询，其返回结果大部分是相同，因而增加了网络延迟和处理时间，例如对于相隔10秒钟发生的两个ActionType为ANSWER_CREATE行为，在调用条件为“过去60分钟内ActionType相同“的Action集时，会2次调用mongodb进行查询，而两次查询的返回结果大概率是80%以上的Action相同，只有小部分Action不同。而从目前的统计数据来看，1分钟内的ANSWER_CREATE事件平均为100条。

*注: 这里只是对某些策略存在这些问题。对于其它策略如查询维度增加相同ip或相同member_id时，并不会存在这种问题，因为这类查询针对性强，召回数量较少，且后端对mongodb做了合理的index，mongodb的性能完全能跟上，所以对这些查询并不是本次升级所关注的点。*

大数据量的查询是指，命中条数大于等于200条的查询，过多的这些查询导致mongodb服务器负载过高。为了避免Spam爆发时由于mongodb的读性能问题造成处理队列阻塞，我们对mongodb的每次查询条数设了上限，默认为200条。由刚才提到的”从目前的统计数据来看，1分钟内的ANSWER_CREATE平均为100条。“可以发现设置上限为200条会造成“过去60分钟内ActionType为ANSWER_CREATE“的Action集的返回结果严重失准，但如果去除这个限制，则会导致mongodb的响应时间线性增长，同时随着返回结果集限制等放开，每条策略的平均处理时长会大大增加，系统的的处理性能会大幅下降。

# 解决方案

为了解决上述的两个问题，我们的想法是采用的加K-V缓存的方法，将接近重复的查询和大数据量查询从mongodb中剥离，mongodb中只负责数据量小的查询，使用 redis 做缓存。缓存数据库由Meta cache和Index cache两部分组成。Meta和Index数据都实时更新。Meta cache存储Action的相关信息，key为Action信息的md5值，value为Action的详细信息。

Index cache存储Action的索引信息，按照时间维度进行分片（默认10分钟）存储, key由time_sheet和index维度组成，value为该时间段内所有发生的该index维度的Actions的md5值，存储为双向链表。如存储ActionType的索引信息，对某个Created时间为12200的ANSWER_CREATE的Action, 存储时将其md5值插入到key为Index:20:ANSWER_CREATE所对应的list中。

![](https://upload-images.jianshu.io/upload_images/5915508-fd58a4d2e1734056.png?imageMogr2/auto-orient/strip%7CimageView2/2/w/1240)


MetaCache数据结构

![](https://upload-images.jianshu.io/upload_images/5915508-0fcbee3ee3de57b3.png?imageMogr2/auto-orient/strip%7CimageView2/2/w/1240)


IndexCache数据结构

对于一次recent_events查询，首先根据查询条件判断是否通过bigcache查询，如果是，我们将根据给定的查询duration和Action Created时间拆分成若干个时间分片，然后分片查询bigcache的Index表来获取md5列表，然后通过基于此查询Meta表获取到具体的Action信息并返回。而对于其它查询，依然通过mongodb返回如下图所示。

![](https://upload-images.jianshu.io/upload_images/5915508-9fc96f5b76a1824a.png?imageMogr2/auto-orient/strip%7CimageView2/2/w/1240)

**第一步**，使用Redis，设置数据过期时间为2小时。

我们对图一所示Policy的same_type_events(60)函数在wukong3.0和wukong2.0环境中分别做了平均执行时间的统计，测试对比结果如下表。

|   | Wukong 2.0 | Wukong 3.0 |
|---|---|---|
| 限定返回最大条数200 | 16ms | 60ms |
| 限定返回最大条数1000 | 90ms | 290ms |

从上表的结果可以发现使用bigcache后，recent_events的效率较wukong 2.0有比较严重的下滑，不符合预期效果。经测试该场景下获取md5和获取具体信息的时间如下表。

|   | IndexCache | MetaCache |
|---|---|---|
| 200条 | 6ms(查询了1个分片) | 54ms |
| 1000条 | 10ms(查询了2个分片) | 280ms |

注：IndexCache的获取时间与需查询的时间片数和每个时间片对应的actions list的长度有关，经测试，对于一个actions list长度为1000的key，查询平均耗时为8ms。

造成性能大幅下降的原因很容易理解，主要在于从Indexcache中获取到md5的list后对每个md5值都需分别请求Metacache查询Action具体信息，而wukong2.0中，mongodb只返回一次。造成了大量的网络请求消耗和IO等待。而且这并没有解决重复查询多次网络传输的问题。

**第二步，**

为了解决上述问题，我们采用了二级缓存的策略，采用LocalCache+redis的设计

LocalCache 采用2层的dict实现，第一层的key为时间分片，第二层存储具体的cache信息，这样做的好处是方便定时的清理过期缓存。

在本地同时缓存近1小时的Meta数据和近1小时内固定的Index数据(如以10分钟作为分片依据，那么查询近1小时数据可分为7片查询，而第0~5片的Index数据可以考虑为不再改变，存储到LocalCache中，因为我们的Action数据流是基本时间序的，假设时间延迟不会大于10分钟)。这样大部分的Index查询和Meta数据查询可以在LocalCache中完成，只有未命中的会查询IndexCache和MetaCache，而LocalCache的命中率极高，大大减少了对MetaCache和IndexCache的请求。流程图如下，

![](https://upload-images.jianshu.io/upload_images/5915508-48b1c8c1cf3be00d.png?imageMogr2/auto-orient/strip%7CimageView2/2/w/1240)

使用该改进后缓存方案的执行时间对比图如下表：

|   | Wukong 2.0 | Wukong 3.0 |
|---|---|---|
| 限定返回最大条数200 | 16ms | 5-8ms |
| 限定返回最大条数1000 | 90ms | 6-25ms |
| 限定返回最大条数为3000 |   | 6-40ms |

从上表可以发现采用LocalCache后性能有很大提升，尤其是当返回条数上限越大时。主要原因在于将热数据存储在本地减少了对同一数据70%以上的重复网络传输和查询且本地缓存命中率高。图表中Wukong3.0的查询返回时间是一个范围，主要取决于第一个时间分片中Action未在LocalCache中的数量。例如对ANSWER_CREATE这类1分钟只有平均100条左右更新的行为，返回时间始终能保持在6-7ms内，不随条数的限制而线性下降。而对于某些1分钟平均2000条左右的更新行为时，3000条的返回时间也能控制在25ms以内。因为我们在第一步中提到一次redis的查询的平均返回时间为2-3ms。

通过以上两步骤，基本可以解决本文开头提到的第一和第二个问题。下一篇文章中，我们将介绍对于第二步的进一步优化及RPC的优化。
