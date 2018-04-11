---
title: Wukong—知乎反作弊系统工具化

tags:
  - antispam
  - wukong

categories:
  - antispam

comments: true
date: 2017-01-17 22:00:00

---

# 引

Wukong 是知乎的离线反作弊系统，自2016年下半年以来，反作弊团队针对 Wukong2 中遇到的一些问题与麻烦，经过思考与实践，重磅推出 Wukong3，本文将就此聊聊wukong3。

在介绍Wukong3之前，先了解一下Wukong2中困扰我们的一些问题。

# Wukong_2 中遇到的麻烦

（关于wukong2的详细介绍：[戳这里](http://www.infoq.com/cn/presentations/zhihu-anti-cheat-system-evolution)）

## 性能问题

随着知乎业务规模的扩张，数据量急速增长，对wukong的性能要求愈发强烈，于此，Wukong3的一个重点就是性能优化，相关文章请参考前几篇文章。

## 效率问题

Wukong2 的主要工作模式是基于制定的反作弊策略，鉴定业务数据是否为spam，工作流程可以概括为：

1.  制定策略：产品同学分析数据之后，总结 spam 规律，制定相关策略
2.  编写策略：Wukong 是 python 编写的，其支持的策略也是 python 语法，在这里研发同学将相关策略用到的 python function 予以实现，并编写成 Wukong 可以识别的 python policy。
3.  部署策略：将编写好的策略提交给Wukong
4.  执行策略：Wukong 将接入的知乎相应业务的每一条数据进行**全策略**检测
5.  监控策略：研发同学上线策略后要监控策略是否有异常，比如检测时间过长、产生 exception 等。产品同学则要根据策略的过滤结果来验证策略的有效性，误伤概率等等指标，这是一个长期的过程。

从这个工作流中可以发现，一条反作弊策略上线的过程中产品、研发的工作相互交织，比较繁琐。并且有一些困扰我们的麻烦：

1.  由于策略的配置语法是基于python的，产品同学用起来比较麻烦，需要研发同学介入，所以每一次策略编写基本都需要研发同学帮忙。
2.  新策略上线后研发同学需要关注sentry、status等系统的相关指标，保证策略没有异常。
3.  策略上线后产品同学需要持续观察（几个小时甚至1天）策略的命中结果，并可能会一定程度的变动策略或调整参数，这个过程有时也需要研发同学给予一定的支持。

这些反馈出一个重要的问题，那就是 Wukong2 的工具化、自动化程度低，易用性差，为此，反作弊团队在 Wukong3 中重点优化了策略的上限流程，使之变得简单易用！

下面我们来看看 Wukong3 如何实践的。

# Wukong_3 的反思与实践

上文反复提到策略的编写需要研发同学的支持，我们首要的重点是优化策略的书写方式，将研发同学从这一环节剔除出去。

## 策略自动化配置

先来看一条典型的Wukong2策略：
`action == "ANSWER_CREATE" and len(user(same_register_ip(register_time(same_topics(same_type_events(10)),register_interval=3600)))) >= 3`

这条策略主要包括三类主体：

*   一条数据自带的一些数据，比如action是业务类型（绿色部分）。
*   策略判定的关联数据，比如recent_type_events(10) 是这条策略关联每条数据最近10min同类型的所有数据进行判定（红色部分）。
*   一些过滤条件，比如same_topics，register_time等，通过这一些列的条件从这条策略的关联数据中过滤出符合条件的结果，并根据这些结果的数量鉴定。（蓝色、粉色部分）

这种书写模式即便是对于研发同学来说也不是很友好，很多的括号和配参，容易出错。对此，我们经过总结抽象出一个Object模型，其包含三类操作filter，mapper，reducer，可以完整覆盖所有策略条件。
![图 Objects](https://upload-images.jianshu.io/upload_images/5915508-9420ca7a078b0359.png?imageMogr2/auto-orient/strip%7CimageView2/2/w/1240)

更新后策略的书写方式变成：

`action == "ANSWER_CREATE" and same_type_events(60).filter('same_register_ip').filter('register_time',register_interval=3600).filter('same_topics',mtype='AcceptID').mapper('userid').reducer('diff').length >= 3`

相比之前是不是清晰了许多？但是仍然需要手动书写！所以我们在前端做了一些小手脚(TokenField！)，最终达到如下效果：
![图 policy-auto](https://upload-images.jianshu.io/upload_images/5915508-bc4a695a6041de2a.png?imageMogr2/auto-orient/strip%7CimageView2/2/w/1240)

选定需要的函数类型，比如filter；根据关键字索引出需要的方法，比如member相关，最后从过滤菜单中选出你想要的function。

策略书写的麻烦解决后，下一个问题就是策略的验证和效果的评估。

## 策略测评

策略编写好后，接下来需要面对的问题就是验证策略正确性，以及评估策略命中的效果。在Wukong2中我们在策略上线后需要观察sentry和log，发现策略时候存在编写错误，也就是说需要在生产环境检验策略的正确性，从工程的角度讲是存在风险的，让人难以接受。另外在策略正确上线后，产品需要评估策略的命中效果是否能有效地命中 spam，同样的在Wukong2 中也需要在生产环境运行，通过线上实时数据观察策略的命中结果，这个过程往往需要几个小时甚至一天，这样就应对一些突发事件的时候就比较麻烦。

为此，我们在 Wukong3 提供了两种新特性**策略测试**和**策略试运行**来解决这两个问题。

### 策略测试

下图是策略测试的实际使用效果，选定业务数据类型，并配置好策略后，如果不指定特定的id，系统会随机从数据库中选择一条用以测试 policy。测试的结果会输出到下方，其主要包含两部分，第一部分是一个 bool 值表示策略是否命中，第二部分是命中的详细数据。

![图 policy-test](https://upload-images.jianshu.io/upload_images/5915508-259719de006ec74c.png?imageMogr2/auto-orient/strip%7CimageView2/2/w/1240)

如果策略有error或exception，则会报错，根据错误信息，使用者可以修正错误的policy。

不过这里测试一般都会**指定一条策略能命中的数据**用来测试，这样可以保证策略的所有function都被测试到。

### 策略试运行

Wukong3的另一个新特性就是策略的试运行，使用者可以指定一个时间区间，和业务类型，Wukong会将这个时间段内的相关业务处理抽取出来并执行这条策略最后将命中结果展示出来。

![图 试运行配置](https://upload-images.jianshu.io/upload_images/5915508-9c3a61d3a300d884.png?imageMogr2/auto-orient/strip%7CimageView2/2/w/1240)

![图 试运行细节](https://upload-images.jianshu.io/upload_images/5915508-80acac521f74544b.png?imageMogr2/auto-orient/strip%7CimageView2/2/w/1240)

相比策略测试，试运行对性能的要求较高，一般情况我们希望能在分钟级别的时间维度的内跑完20万的数据(各个业务平均一天数据量的平均值)。目前，试运行基于上文提到的Wukong3性能优化模型，设计结构如下图：

![图 设计结构](https://upload-images.jianshu.io/upload_images/5915508-9ab8f249bdbc14f7.png?imageMogr2/auto-orient/strip%7CimageView2/2/w/1240)

概要流程：

1.  首先从web配置的每一个试运行 task 放入一个 task-queue。
2.  其次 由唯一的 task-worker 从这个task-queue中消费，将这个 task 分解成试运行的子任务（pilot-job），每一个task最多对应上限为20万的 pilot-jobs，所以只需要一worker足矣，同时还能保证task执行的顺序性。
3.  由每个task 生成的所有 pilot-jobs 会放入另一个 pilot-queue，由后端的弹性容器组（pilot-worker）并发计算，并将计算结果保存到Mongo，保证速度。
4.  前端将实时展示计算结果

目前试运行每一个worker执行一条策略的平均时间大约在10ms~30ms之内，我们的 pilot-worker 容器组弹性上限设定为30，并发性能约为1000条/s，所以一个包含20万pilot-jobs的task可以控制在5min内完成计算。

另外，在试运行的这种设计结构中有一些细节需要注意，比如task-worker向task-queue中push task时需要控制速度，避免task-queue被瞬间打爆；同样的pilot-jobs的consumer worker也需要控制速度等等，这里就不展开描述了。

## 数据关联

相比日志等，统计数据和图形往往是能最直观的反应现实，帮助使用者快速发现、定位、解决问题，所以在Wukong3，我们添加了策略维度丰富的数据展示。

首先是直观显示Today的策略命中数据， 分别是策略的callback(这个是保存命中数据)的数量和ban,delete（锁定和删除处理）的数量。这种数据在清理临时策略、查找未处理策略时很有帮助。

![图 data-概览](https://upload-images.jianshu.io/upload_images/5915508-901f3978d21e4db8.png?imageMogr2/auto-orient/strip%7CimageView2/2/w/1240)

检测策略运行健康度有两个比较重要的实时指标，策略执行时间和策略错误数，通过这些数据使用者可以在上线策略后观察策略的健康状况：
![图：实时健康指标](https://upload-images.jianshu.io/upload_images/5915508-8df06e4210907f5a.png?imageMogr2/auto-orient/strip%7CimageView2/2/w/1240)

最后，还有策略近期的命中情况和误伤情况，可以帮助产品评估历史策略是否随着时间的变化需变更。
![图：历史误伤数据](https://upload-images.jianshu.io/upload_images/5915508-3ca10219afd0ef41.png?imageMogr2/auto-orient/strip%7CimageView2/2/w/1240)
