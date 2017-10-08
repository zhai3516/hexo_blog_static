---
title: Python 读写 hbase 数据的正确姿势（四）

tags:
  - hbase
  - happybase
  - python

categories:
  - Hbase

comments: true
date: 2017-10-08 19:00:00
---
问题4:  查询异常 TApplicationException: Missing result
======================
在上一篇文章中讨论了线上测试时出现 `[Errno 32] Broken pipe` 错误，这里继续分析另一个错误 `TApplicationException: Missing result`。

问题描述
-------------------
在解决了问题 3 后，又遇到了一个相似的错误： 查询的过程中发现了大量的 `TApplicationException: Missing result` 错误：
```
  File "/usr/local/lib/python2.7/site-packages/happybase/table.py", line 402, in scan
    self.name, scan, {})
  File "/usr/local/lib/python2.7/site-packages/thriftpy/thrift.py", line 198, in _req
    return self._recv(_api)
  File "/usr/local/lib/python2.7/site-packages/thriftpy/thrift.py", line 234, in _recv
    raise TApplicationException(TApplicationException.MISSING_RESULT)
thriftpy.thrift.TApplicationException: Missing result
```
同问题3类似，在大量出现此类错误之前都少量的伴有`timeout: timed out`超时提示：
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
在服务端也发现了一些`TIOStreamTransport`错误：
```java
2017-xx-xx xx:xx:xx,xxx WARN  [thrift-worker-4] transport.TIOStreamTransport: Error closing output stream.
java.net.SocketException: Socket closed
	at java.net.SocketOutputStream.socketWrite(SocketOutputStream.java:116)
	at java.net.SocketOutputStream.write(SocketOutputStream.java:153)
	at java.io.BufferedOutputStream.flushBuffer(BufferedOutputStream.java:82)
	at java.io.BufferedOutputStream.flush(BufferedOutputStream.java:140)
	at java.io.FilterOutputStream.close(FilterOutputStream.java:158)
	at org.apache.thrift.transport.TIOStreamTransport.close(TIOStreamTransport.java:110)
	at org.apache.thrift.transport.TSocket.close(TSocket.java:235)
	at org.apache.hadoop.hbase.thrift.TBoundedThreadPoolServer$ClientConnnection.run(TBoundedThreadPoolServer.java:299)
	at java.util.concurrent.ThreadPoolExecutor.runWorker(ThreadPoolExecutor.java:1142)
	at java.util.concurrent.ThreadPoolExecutor$Worker.run(ThreadPoolExecutor.java:617)
	at java.lang.Thread.run(Thread.java:745)
```
问题分析
-------------------
这种情况和上文问题 3 中`Broken pipe` + `TTransportException ` + `IllegalArgumentException ` 的错误组合模式非常类似，所以猜测timeout 是导致这种现象的导火索，为了验证猜想，在测试环境手动复现错误场景：
```python
conn_pool = None
TABLE = 'article'

def get_connetion_pool(timeout=2):
    global conn_pool
    if conn_pool is None:
        conn_pool = happybase.ConnectionPool(1, timeout=timeout)
    return conn_pool

def recent_events_v3(start, end, table=None, filter_str=None, limit=2000, timeout=2):
    # 为了复现错误，通过 pool 拿 conn 时重新设置 timeout
    with get_connetion_pool().connection(timeout) as conn:
        if table is not None:
            t = conn.table(table)
        else:
            t = conn.table(TABLE)
        start_row = 'ARTICLE' + str(start * 1000000)
        end_row = 'ARTICLE' + str(end * 1000000)
        return t.scan(row_start=start_row, row_stop=end_row, filter=filter_str, limit=limit)

def main():
    for i in range(10):
        try:
            results = recent_events_v3(start=0, end=1505646570, table="test_article_java_2", timeout=0.1)  # 根据情况设置timeout，我这里设置的是 0.1s
            print len([i for i in results])  # 期望值为2, 实际报错
        except Exception as e:
            print e
        time.sleep(2)
        print '##############################'
```
运行结果如下：

![复现 Missing result](http://upload-images.jianshu.io/upload_images/5915508-627f66ffae481463.png?imageMogr2/auto-orient/strip%7CimageView2/2/w/1240)

果然在印证了猜想 `TApplicationException: Missing result` 异常前一定出现过 timeout，此时基本可以确定的问题的发生过程：
- 首先，因为某种原因触发了 `timeout`，此时这条连接失效。
- 然后，后续的查询，先从连接池拿到了这条失效的连接，并用这条连接做查询。
- 最后，因为是一条无效的连接，所以客户端出现大量`TApplicationException: Missing result` 错误。


解决问题
----------------------
适当的增大 timeout 后，可以很大程度上减少这样的情况发生，但是  `timeout` 不同于上文的 `IllegalArgumentException ` 错误，在高并发的查询场景下不设置 timeout 是难以接受的，而使用 scan 的查询场景以及网络环境本身(在稳定的场景，仍有可能出现抖动导致超时) 又难以避免的会出现 timeout，所以无法通过问题 3 的解决方式搞定这个问题。

对比问题 3 和问题 4，存在一个共同点，即因为某种错误，导致连接池返回了一条无效的连接，然后用这条无效的连接发送请求，最后报错。然而可以换一种思路，在发现存在无效连接时重连并做一定次数的重试来避免这种情况的发生。

因为生产环境是多容器，每个容器单进程，在这种场景下连接池和初始化一条连接的意义相差不大，整个连接池同一时刻只会被一个进程使用(所以连接池只初始化了 1 条连接)，所以在发生 timeout 时，catch 住并重新初始化连接池然后重试：
```python
def main():
    for i in range(10):
       try:
           results = recent_events_v3(start=0, end=1505646570, table="test_article_java_2", timeout=0.01) 
           print len([i for i in results]) 
       except socket.timeout:
           conn_pool = None  
           # catch timeout 后，清空连接池
           # 下次使用时 `get_connetion_pool` 方法重新初始化连接池
           # 仅限单线程模型 !
           pass # 重试逻辑略

       # 不会在出现 `TApplicationException: Missing result` 错误
       time.sleep(2)
       print '###############################'
```
修改后运行测试代码只会出现 timeout，不会出现其他错误:

![timeout](http://upload-images.jianshu.io/upload_images/5915508-0aaefda143d370b4.png?imageMogr2/auto-orient/strip%7CimageView2/2/w/1240)


下期预告
================
上文文末提到一个疑惑: **" 为什么一条异常的连接会出现在 connect pool 中，而且总会拿到这条连接 ？**。这次同样是类似的情况，happybase 中的连接池是如何实现的，为什么出现了这样的问题？下一篇继续这个话题...
