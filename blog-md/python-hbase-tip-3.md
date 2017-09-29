---
title: Python 读写 hbase 数据的正确姿势（三）

tags:
  - hbase
  - happybase
  - python

categories:
  - Hbase

comments: true
date: 2017-09-28 23:00:00
---
问题3:  查询异常 [Errno 32] Broken pipe
======================
这篇文章将继续 python-hbase 这一话题，讨论一个在线上环境中出现的很有意思的问题。

问题描述
------------------------
同样是前面文章中描述的类似查询场景，生产测试，在调用 hbase thrift 接口时，日志中捕获到大量的 [Errno 32] Broken pipe 错误，具体如下：
```
  File "/usr/local/lib/python2.7/site-packages/happybase/table.py", line 402, in scan
    self.name, scan, {})
  File "/usr/local/lib/python2.7/site-packages/thriftpy/thrift.py", line 195, in _req
    self._send(_api, **kwargs)
  File "/usr/local/lib/python2.7/site-packages/thriftpy/thrift.py", line 206, in _send
    self._oprot.write_message_end()
  File "thriftpy/protocol/cybin/cybin.pyx", line 463, in cybin.TCyBinaryProtocol.write_message_end (thriftpy/protocol/cybin/cybin.c:6845)
  File "thriftpy/transport/buffered/cybuffered.pyx", line 80, in thriftpy.transport.buffered.cybuffered.TCyBufferedTransport.c_flush (thriftpy/transport/buffered/cybuffered.c:2147)
  File "/usr/local/lib/python2.7/site-packages/thriftpy/transport/socket.py", line 129, in write
    self.sock.sendall(buff)
  File "/usr/local/Cellar/python/2.7.13/Frameworks/Python.framework/Versions/2.7/lib/python2.7/socket.py", line 228, in meth
    return getattr(self._sock,name)(*args)
error: [Errno 32] Broken pipe
```
问题分析
------------------------
`[Errno 32] Broken pipe` 往往意味着连接问题，连接的一端已经关闭连接，但是另一端仍然使用这个连接向对方发送数据。

经过和平台组同学的排查测试，排除了生产环境中链路质量的问题以及 hbase thrift server 稳定性的问题。如果不是网络问题导致，那有没有可能是 hbase 处理请求的过程中发生了错误，主动关闭了连接？为了进一步追查问题，在本地还原了线上场景，复现错误。

果不其然，还原现场后客户端最早收到了一个额外的异常，这之后才收到大量的 Broken Pipe 错误，新的异常：
```
  File "/usr/local/lib/python2.7/site-packages/happybase/table.py", line 402, in scan
    self.name, scan, {})
  File "/usr/local/lib/python2.7/site-packages/thriftpy/thrift.py", line 198, in _req
    return self._recv(_api)
  File "/usr/local/lib/python2.7/site-packages/thriftpy/thrift.py", line 210, in _recv
    fname, mtype, rseqid = self._iprot.read_message_begin()
  File "thriftpy/protocol/cybin/cybin.pyx", line 429, in cybin.TCyBinaryProtocol.read_message_begin (thriftpy/protocol/cybin/cybin.c:6325)
  File "thriftpy/protocol/cybin/cybin.pyx", line 60, in cybin.read_i32 (thriftpy/protocol/cybin/cybin.c:1546)
  File "thriftpy/transport/buffered/cybuffered.pyx", line 65, in thriftpy.transport.buffered.cybuffered.TCyBufferedTransport.c_read (thriftpy/transport/buffered/cybuffered.c:1881)
  File "thriftpy/transport/buffered/cybuffered.pyx", line 69, in thriftpy.transport.buffered.cybuffered.TCyBufferedTransport.read_trans (thriftpy/transport/buffered/cybuffered.c:1948)
  File "thriftpy/transport/cybase.pyx", line 61, in thriftpy.transport.cybase.TCyBuffer.read_trans (thriftpy/transport/cybase.c:1472)
  File "/usr/local/lib/python2.7/site-packages/thriftpy/transport/socket.py", line 125, in read
    message='TSocket read 0 bytes')
TTransportException: TTransportException(message='TSocket read 0 bytes', type=4)
```
这个异常的大概意思是 server 端发生了异常并没有返回任何数据，扒一下 hbase server 的日志，又发现了一个有趣的异常：
```
java.lang.IllegalArgumentException: Incorrect Filter String
	at org.apache.hadoop.hbase.filter.ParseFilter.extractFilterSimpleExpression(ParseFilter.java:226)
	at org.apache.hadoop.hbase.filter.ParseFilter.parseFilterString(ParseFilter.java:174)
	at org.apache.hadoop.hbase.thrift.ThriftServerRunner$HBaseHandler.scannerOpenWithScan(ThriftServerRunner.java:1481)
	at sun.reflect.GeneratedMethodAccessor2.invoke(Unknown Source)
	at sun.reflect.DelegatingMethodAccessorImpl.invoke(DelegatingMethodAccessorImpl.java:43)
	at java.lang.reflect.Method.invoke(Method.java:498)
	at org.apache.hadoop.hbase.thrift.HbaseHandlerMetricsProxy.invoke(HbaseHandlerMetricsProxy.java:67)
	at com.sun.proxy.$Proxy9.scannerOpenWithScan(Unknown Source)
	at org.apache.hadoop.hbase.thrift.generated.Hbase$Processor$scannerOpenWithScan.getResult(Hbase.java:4613)
	at org.apache.hadoop.hbase.thrift.generated.Hbase$Processor$scannerOpenWithScan.getResult(Hbase.java:4597)
	at org.apache.thrift.ProcessFunction.process(ProcessFunction.java:39)
	at org.apache.thrift.TBaseProcessor.process(TBaseProcessor.java:39)
	at org.apache.hadoop.hbase.thrift.TBoundedThreadPoolServer$ClientConnnection.run(TBoundedThreadPoolServer.java:289)
	at java.util.concurrent.ThreadPoolExecutor.runWorker(ThreadPoolExecutor.java:1142)
	at java.util.concurrent.ThreadPoolExecutor$Worker.run(ThreadPoolExecutor.java:617)
	at java.lang.Thread.run(Thread.java:745)
```
这个异常中出现了解决问题的核心关键词 `Incorrect Filter String`，从字面理解来看是传到 hbase 的 filter 不正确，导致解析失败。

找到这条有问题的 filter：
>"SingleColumnValueFilter('basic', 'ArticleTypeID', =, 'binary:\x00\x00\x00\x00\x03'T\xc9')"

从语法上来看感觉并没有什么问题，同样的逻辑使用 java client 则完全正确。为了一探究竟拉出 hbase 抛错部分的源码看看为什么：

```java
  public byte [] extractFilterSimpleExpression (byte [] filterStringAsByteArray,
                                                int filterExpressionStartOffset)
    throws CharacterCodingException {
    int quoteCount = 0;
    for (int i=filterExpressionStartOffset; i<filterStringAsByteArray.length; i++) {
      if (filterStringAsByteArray[i] == ParseConstants.SINGLE_QUOTE) {
        if (isQuoteUnescaped(filterStringAsByteArray, i)) {
          quoteCount ++;
        } else {
          // To skip the next quote that has been escaped
          i++;
        }
      }
      if (filterStringAsByteArray[i] == ParseConstants.RPAREN && (quoteCount %2 ) == 0) {
        byte [] filterSimpleExpression = new byte [i - filterExpressionStartOffset + 1];
        Bytes.putBytes(filterSimpleExpression, 0, filterStringAsByteArray,
                       filterExpressionStartOffset, i-filterExpressionStartOffset + 1);
        return filterSimpleExpression;
      }
    }
    throw new IllegalArgumentException("Incorrect Filter String");
  }
```
从源码中可以看到在两种情况下会 raise exception：

1. filter 不是以 `ParseConstants.RPAREN` 结尾，即不是以 `)` 结尾
2. `quoteCount`不是偶数, 即单引号的数量不是偶数

到此，可以真相大白了，从代码中可以看到 hbase parse 的过程中是通过单引号提取参数的，而我的 filter 中有一个整型参数在转成 bytes 后包含单引号，影响了 hbase 解析 filter 参数，并最终导致 quoteCount 不是偶数，然后抛出异常。

解决问题
-------------------
定位到问题根本后，解决问题就 so easy 了。解析 filter 的源码中用到了 escape quote 的方法 `isQuoteUnescaped `，具体实现如下：
```java
 public static boolean isQuoteUnescaped (byte [] array, int quoteIndex) {
    if (array == null) {
      throw new IllegalArgumentException("isQuoteUnescaped called with a null array");
    }

    if (quoteIndex == array.length - 1 || array[quoteIndex+1] != ParseConstants.SINGLE_QUOTE) {
      return true;
    }
    else {
      return false;
    }
  }
```
逻辑很简单，判断单引号下一下字符是否仍然是单引号，如果是则被转义，跳过检查。所以我们的filter 只需要通过 `两个单引号` 替换参数中的 `一个单引号`即可，eg:
```
hbase_int_filter_template = "SingleColumnValueFilter('a', '{property}', {symbol}, 'binary:{threshold}')"
f = hbase_int_filter_template.format(property=params[0], symbol=flag, threshold=struct.pack('>q', threshold).replace("'", "''"))
```
单引号转义后，没有再出现这两类 exception。

后续分析
===================
回头来看，因为 filter 使用错误，导致 hbase 解析 filter 异常，hbase server 抛出异常，并中断连接，client 收到 TTransportException 异常，此时这条连接已经失效，但是仍在 connection pool 中，所有后续从 connection pool 中获取连接时拿到这条连接后，再向 hbase 发送请求时 client 端不断收到 [Errno 32] Broken pipe 错误。

**出现了一个新的思考题，为什么一条异常的连接会出现在 connect pool 中，而且总会拿到这条连接 ？**

题外话
==================
仔细想想 filter 中单引号需要转义这种情况按理说 hbase 会在官方的 Document 中提到才对，翻翻 user guide ，果然找到了 [Filter Language](http://hbase.apache.org/book.html#thrift.filter_language)

![hbase filter language](http://upload-images.jianshu.io/upload_images/5915508-48c8729b6bcde125.png?imageMogr2/auto-orient/strip%7CimageView2/2/w/1240)

使用前用心看看官方文档还是很有必要的，可以少踩许多坑...
