---
title: Python 读写 hbase 数据的正确姿势（五）

tags:
  - hbase
  - happybase
  - python

categories:
  - Hbase

comments: true
date: 2017-10-31 23:00:00
---

为什么一条异常的连接会出现在 connect pool 中，而且总会拿到这条连接 ？
=============================
在本系列第**三**篇文章末尾提出了这样一个问题 **『 为什么一条异常的连接会出现在 connect pool 中，而且总会拿到这条连接 』**，本文将继续深入这个问题，找到其根本原因。

问题分析
---------------------
弄清这个问题，要深入 happybase 的代码看一下具体实现逻辑。

happybase 的连接池要求必须要使用 context manager，以下是其通过 context manager 获取/归还 Connection 的源码：
```python
    @contextlib.contextmanager
    def connection(self, timeout=None):
        # 获取一个 Connection 对象
        connection = getattr(self._thread_connections, 'current', None)
        return_after_use = False
        if connection is None：
            return_after_use = True
            connection = self._acquire_connection(timeout)
            with self._lock:
                self._thread_connections.current = connection

        try:
            # 打开连接，并返回一个可用的连接给contextmanager
            connection.open()
            yield connection
        except (TException, socket.error):
            # 捕获 Trhift 和 socket 的异常和错误，则需要 refresh thrift client，保证最后归还的 Connection 的 thrift client 是可用的。
            logger.info("Replacing tainted pool connection")
            connection._refresh_thrift_client()
            connection.open()
            raise
        finally:
            # 最终会归还这条连接
            if return_after_use:
                del self._thread_connections.current
                self._return_connection(connection)
```

实现逻辑大概可以归纳为：
* 在 pool 初始化的时候构建一个包含若干 Connection 的 queue 以及一个 lock。
* 当向连接池请求连接时，open 一个 Connection 并返回，在这个过程中会 catch TException 以及 socket.error。
* 如果 catch 到以上 error/exception 则会刷新 Connection 对象的thrift_client，保证在退出 context manager 时返回给队列的 Connection 是可用的。
* 退出 context manager 前将 Connection 返还。

从以上逻辑可以发现，happybase 是通过 context manager 保证 Connection 在退出时是正常的，而我们的场景中出现了 socket.error 却并没有被 catch 住，说明有可能是错误发生在 context manager 之外，回到代码：
```python
def recent_events_v1(start, end, table=None, filter_str=None, limit=2000):
    with get_connetion_pool().connection() as conn:
        if table is not None:
            t = conn.table(table)
        else:
            t = conn.table(TABLE)
        start_row = 'ARTICLE' + str(start * 1000000)
        end_row = 'ARTICLE' + str(end * 1000000)
        return t.scan(row_start=start_row, row_stop=end_row, filter=filter_str, limit=limit)
```
从代码可以发现，再使用连接池的过程中，退出 context manager  前直接 return table.scan() ，而 scan 方法会创建一个 scanner ，最终返回一个 **generator**，到这里基本可以说是水落石出了！

问题原因
------------------

因为 generator 的特性，在退出 context manager 前并没有发生真正的查询，所以这时返回给 connent pool 的 Connection 仍然是没有问题的。只用在真正遍历这个 generator 时才会发生数据查询，而这个过程肯定在 context manager 之外，所以此时如果出现 error 则不会再有类似的 catch 逻辑去保证这条 Connection 在发生异常时去刷新 thrift_client，最终导致这条已经归还给 pool 的 Connection 失效了。

同时这里还会存在另一个问题，在并发场景下，遍历 generator 发生查询时可能这个 Connection 已经被分配给其他线程使用了，导致这个 Connection 同时被两个线程所有，出现一些难以预测的问题。

解决问题
================
既然发现了问题的根因，解决起来就比较简单了，只要保证所有使用 Connection 的逻辑都发生在 context manager 内就好，所以这里可以把遍历generator 的逻辑放在 context manager 内，最终返回一个 list 对象而不是 generator，代码如下：
```python
def recent_events_v4(start, end, table=None, filter_str=None, limit=2000):
    with get_connetion_pool().connection() as conn:
        if table is not None:
            t = conn.table(table)
        else:
            t = conn.table(TABLE)
        start_row = 'ARTICLE' + str(start * 1000000)
        end_row = 'ARTICLE' + str(end * 1000000)
        result_generator = t.scan(row_start=start_row, row_stop=end_row, filter=filter_str, limit=limit)
        return [l for l in result_generator]
```

从下图可以看出，修正后的代码在运行的过程中出现 `TTransportException`后，不会在出现 `Broken pipe `。

![不会在出现 Broken pipe](http://upload-images.jianshu.io/upload_images/5915508-6c7a54b7995022fe.png?imageMogr2/auto-orient/strip%7CimageView2/2/w/1240)

继续思考
--------------------
上面分析了**『为什么一条异常的连接会出现在 connect pool 中』**，那 **『而且总会拿到这条连接 』** 又是为什么?

仔细观察 happybase 获取 connection 的前半部分逻辑可以发现，其是优先从` self._thread_connections ` 获取链接对象，当获取不到时才通过 `self._acquire_connection`  从 pool 中取。

这个 `self._thread_connections` 是个什么东西？这是一个 thread local 变量，即线程自有的局部变量，其他线程不可访问，happybase 源码：
```python
self._thread_connections = threading.local()
```

某个线程第一次请求获取 Connection 时，通过这个 thread local 变量，把分配给它的 Connection 记录下来，当下次这个线程再请求时，则优先把这个 thread local 变量记录的 Connection 返回给线程。

因为我们是单线程场景，所以每次返回给主进程的都是同一个有问题的 Connection 对象，这就解释了 **『总会拿到问题链接』** 这个问题。

小结
==============
综上，在使用连接池的场景中，注意类似 scan 这种具有延时行的操作，一定要放在 context mananer 内，才能保证连接池内的连接可用~
