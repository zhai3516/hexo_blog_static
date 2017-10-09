---
title: Python 读写 hbase 数据的正确姿势（四）

tags:
  - hbase
  - happybase
  - python

categories:
  - Hbase

comments: true
date: 2017-10-08 16:00:00
---
问题4:  查询异常 TApplicationException: Missing result
======================
在上一篇文章中讨论了线上测试时出现 `[Errno 32] Broken pipe` 错误，这里继续分析另一个错误 `TApplicationException: Missing result`。

问题描述
-------------------
在解决了问题 3 后，又遇到了古怪的错误：在查询的过程中，出现了大量的 `TApplicationException: Missing result` 错误：
```
  File "/usr/local/lib/python2.7/site-packages/happybase/table.py", line 402, in scan
    self.name, scan, {})
  File "/usr/local/lib/python2.7/site-packages/thriftpy/thrift.py", line 198, in _req
    return self._recv(_api)
  File "/usr/local/lib/python2.7/site-packages/thriftpy/thrift.py", line 234, in _recv
    raise TApplicationException(TApplicationException.MISSING_RESULT)
thriftpy.thrift.TApplicationException: Missing result
```
而且，在大量出现此类错误之前伴有 `timeout: timed out` 超时：
```
File "/usr/local/lib/python2.7/site-packages/happybase/table.py", line 415, in scan
scan_id, how_many)
File "/usr/local/lib/python2.7/site-packages/thriftpy/thrift.py", line 198, in _req
return self._recv(_api)
File "/usr/local/lib/python2.7/site-packages/thriftpy/thrift.py", line 210, in _recv
fname, mtype, rseqid = self._iprot.read_message_begin()
File "thriftpy/protocol/cybin/cybin.pyx", line 429, in cybin.TCyBinaryProtocol.read_message_begin (thriftpy/protocol/cybin/cybin.c:6325)
File "thriftpy/protocol/cybin/cybin.pyx", line 60, in cybin.read_i32 (thriftpy/protocol/cybin/cybin.c:1546)
File "thriftpy/transport/buffered/cybuffered.pyx", line 65, in thriftpy.transport.buffered.cybuffered.TCyBufferedTransport.c_read (thriftpy/transport/buffered/cybuffered.c:1881)
File "thriftpy/transport/buffered/cybuffered.pyx", line 69, in thriftpy.transport.buffered.cybuffered.TCyBufferedTransport.read_trans (thriftpy/transport/buffered/cybuffered.c:1948)
File "thriftpy/transport/cybase.pyx", line 61, in thriftpy.transport.cybase.TCyBuffer.read_trans (thriftpy/transport/cybase.c:1472)
File "/usr/local/lib/python2.7/site-packages/thriftpy/transport/socket.py", line 108, in read
buff = self.sock.recv(sz)
timeout: timed out
```
服务端没有任何异常。

问题分析
-------------------
看起来这种情况和上文问题 3 中`Broken pipe` + `TTransportException ` 的错误组合模式比较类似，**所以猜测timeout 是导致这种现象的导火索**，为了验证猜想，尝试在测试环境手动复现错误场景：
```python
conn_pool = None
TABLE = 'article'

# 本地环境 timeout 设置为1 时 超时较多
# 生产环境为 10
def get_connetion_pool(timeout=1):
    global conn_pool
    if conn_pool is None:
        conn_pool = happybase.ConnectionPool(1, timeout=timeout)
    return conn_pool

def recent_events_v3(start, end, table=None, filter_str=None, limit=2000):
    with get_connetion_pool().connection() as conn:
        if table is not None:
            t = conn.table(table)
        else:
            t = conn.table(TABLE)
        start_row = 'ARTICLE' + str(start * 1000000)
        end_row = 'ARTICLE' + str(end * 1000000)
        return t.scan(row_start=start_row, row_stop=end_row, filter=filter_str, limit=limit)

def main():
    # 问题4复现
    for i in range(100):
    # 有timeout，有 Missing result，有正常查询
        try:
            results = recent_events_v3(start=0, end=1505646570, table="test_article_java_2")
            print len([i for i in results])
        except Exception as e:
            print e
        print '#########################################'
```
运行结果如下：

![image.png](http://upload-images.jianshu.io/upload_images/5915508-d8e5ae1a59dac5c7.png?imageMogr2/auto-orient/strip%7CimageView2/2/w/1240)

而当把 timeout 增加到一个较大值时则不会出现这种情况。印证了猜想 `TApplicationException: Missing result` 异常前一定出现过 `timeout`。

解决问题
----------------------
增大 timeout 后，可以很大程度上减少这样的情况发生，但是 `timeout` 不同于问题 3 的 `IllegalArgumentException ` 错误，可以主动控制，使用 scan 的查询场景以及网络环境本身(在稳定的场景，仍有可能出现抖动导致超时) 难以避免的会出现 timeout，所以仅仅增加 timeout 值，仍然后可能会出现这种情况。

问题 3 会出现 `Broken Pipe` 错误是因为之前发生错误导致连接失效，后续再使用异常连接时则会报错。问题 4 是否也是因为 timeout 后导致连接出问题，然后出现这种情况呢？

尝试验证这种猜想：在发生 timeout 时，catch 住并重新初始化连接池然后重试：
```python
def main():
    # 问题4修复
    for i in range(30):
        # 没有 Missing result，只有 timeout 和 有正常查询
        try:
            results = recent_events_v3(start=0, end=1505646570, table="test_article_java_2")
            print len([i for i in results])  # 期望值为2, 实际报错
        except socket.timeout:
            conn_pool = None  # catch timeout 后, 清空连接池，下次使用时重新初始化, 仅限单线程模型 !
            print 'time out: reinit conn pool!'
            # print traceback.format_exc()
        # 不会在出现 `TApplicationException: Missing result` 错误
    print '#########################################'
```
修改后运行测试代码只会出现 timeout，不会出现其他错误:


![timeout re init](http://upload-images.jianshu.io/upload_images/5915508-79a8434ce0c8b8e9.png?imageMogr2/auto-orient/strip%7CimageView2/2/w/1240)

因为生产环境是多容器，每个容器单进程，在这种场景下连接池和一个全局变量连接的意义相差不大，整个连接池同一时刻只会被一个进程使用(所以连接池只初始化了 1 条连接)，所以直接重置连接池是可以的，此时可以彻底避免 `Missing results` ~

继续思考
================
上文文末提到一个疑惑 ：**为什么一条异常的连接会出现在 connect pool 中，而且总会拿到这条连接 ?** 。

这次同样还有另一个问题值得思考：**timeout 后为什么会出现大量的 `Missing results` 错误？是否如同猜测的那样 timeout 后连接池中的连接失效了？**

下篇文章见~
