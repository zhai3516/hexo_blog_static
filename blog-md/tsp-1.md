---
title: TSP—知乎流量安全反作弊平台的流量管家

tags:
  - tsp
  - antispam
  - anticrawl
  - security

categories:
  - antispam

comments: true
date: 2017-04-18 23:00:00

---

# TSP ( Trust and Safety Platform ) 是什么
TSP 流量平台是知乎基于全站的镜像流量，为安全、反作弊系统提供数据支撑的一套解决方案，主要实现了业务方自动化的接入反作弊、反爬虫系统以及提供一些常用数据。

# TSP 的意义
为什么会有 TSP 平台呢？

首先，敏感数据的安全隐患。比如反爬系统之前是订阅的 Nginx log ，获得用户和 ip 的访问记录，但是对于一些敏感数据（Cookie 等）不适合写入日志。

其次，业务接入的复杂性。不同的业务对数据的维度侧重点不同，检测逻辑也不同，各个业务有独立的接入方案，如调用业务RPC接口、订阅业务消息队列、Nginx 日志等，整个接入逻辑和业务代码强耦合在一起，维护和管理成本较高。

最后，数据完整性。数据的获取很大程度上依赖于业务方，并且获取方式多样复杂，数据完整性也无法保证。

综上，我们通过使用物理手段：**在机房的入口网关处，从交换机上直接分出流量的镜像，并将流量打到几台用于分析流量机器的万兆网卡上，然后在这几台镜像设备上直接运行解析流量程序，解析出流入全站的 HTTP 请求。** 基于这部分数据，下游统一实现业务接入以及生成一些常用数据。

# TSP 的实现
整个 TSP 平台由旁路流量处理模块、GateWay 实时拦截模块、策略配置管理模块、数据展示模块组成，结构图如下：

![TSP 架构图](https://upload-images.jianshu.io/upload_images/5915508-bd9667b4b8834001.png?imageMogr2/auto-orient/strip%7CimageView2/2/w/1240)

## 旁路流量处理
- 镜像机流量解析
此部分实现了镜像流量的捕获以及解析，并将解析出的 HTTP 请求发送到 kafka 集群。

- Kafka 缓存队列
缓存全流量的队列，作为 Storm 处理的数据源。

- Storm 数据处理
负责对流量的清洗，解析，汇聚，以满足不同的业务需求，比如反爬系统需要按时间窗口聚合 member/ip 的统计频率。

- ActionQueue
存储离线识别出的风险的 IP， UserID 等不同封禁维度的队列。以供给 Gateway 对实时流量进行风险识别。

## Gateway 实时流量拦截
Gateway 是 HTTP 服务，主要目的是与入口的 Nginx 交互，并利用离线风险识别的结果，实时判断的每一条流量是否存在异常或风险，以达到阻断异常流量进入业务层的效果。

该模块使用 HAProxy 做负载均衡，利用 Nginx 将实时流量的 header 通过 HTTP 请求打给 Gateway 模块，Gateway 模块从实时流量中提取出 UserID, IP, Device ID 等并判断是否需要处理并将处理结果写入Response Header 返回 Nginx。

![gateway 数据流](https://upload-images.jianshu.io/upload_images/5915508-1e59287ea0dd3bcd.png?imageMogr2/auto-orient/strip%7CimageView2/2/w/1240)

上图展示了一条流量经过 Gateway 处理的几个步骤：
1. 接收 Nginx 转发的实时流量的 header，解析 IP，Ticket，UA 等参数。
2. 根据 Ticket 信息解析出该流量对应的 memberId 和 deviceId 信息。
3. 获取member、ip 状态，包括被反作弊处理、反爬处理、帐号安全处理等等。
4. 根据 robot 和 account-status 结果组装 response 返回给 nginx。

另外，为了业务的用户体验，此次交互的 Timeout 时间为 **10ms**，同时为了兼顾拦截效果，超时的量需要控制在 **0.01%** 以内。

## 策略配置管理平台
提供给简单快捷的接入配置管理，比如接入反爬系统的 url 匹配规则管理，包括 url router，策略优先级，命名等。
![反爬系统接入匹配规则](https://upload-images.jianshu.io/upload_images/5915508-07847715bdc3b2f9.png?imageMogr2/auto-orient/strip%7CimageView2/2/w/1240)

对于要接入反爬虫系统的业务，只要提供其对应的 url router ，storm 会根据配置，将 router 匹配到的 url 转换成对应的业务名称，输出到下游，在整个过程中，我们要做的只是添加这样一条配置，storm 会动态的、准实时的更新配置并生效。同时，还配备了相关工具，测试正则逻辑以及当前的策略匹配结果：
![反爬匹配策略校验工具](https://upload-images.jianshu.io/upload_images/5915508-be76e24a8bb1735f.png?imageMogr2/auto-orient/strip%7CimageView2/2/w/1240)

在之前的方案中，如果需要加入新的数据维护，或者新接入业务 url ，都需要调整 nginx 输出日志的逻辑并重新上线。整个过程的自动化程度相当低，抛开重复的更改代码的成本，还存在敏感数据外泄的隐患。

## 数据存储及展示
Storm 输出的数据，ActionQueue 的风险数据，以及 Gateway 的拦截数据都会存储一份在 ElasticSearch中以供人工查询，分析。

# 小结
基于 TSP ：
1. 统一接入模式，并根据各业务不同的特点定制化、自动化接入安全反作弊平台，在接入层与各业务解耦。
2. 在整个流量入口实现了异常、风险流量的阻断，使业务对风险无感，在处理层与各业务解耦。
3. 基于全部流量，可以简单、便捷的生成用户、IP 的行为数据，比如用户的读写行为特征、常用地常用城市信息、最近访问记录、IP 离散度等等，在数据层一定程度上与业务解耦。
