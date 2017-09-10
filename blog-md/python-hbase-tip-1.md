---
title: Python 读写 hbase 数据的正确姿势（一）

tags:
  - hbase
  - happybase
  - python

categories:
  - Hbase

comments: true
date: 2017-09-09 19:00:00
---
之前操作 hbase 大都是用 java 写，或者偶尔用 python 写几个一些简单的 put、get 操作。最近在使用 `happybase` 库批量向 hbase 导入数据，并实现一些复杂的搜索时（scan+filter），遇到了一些有趣的问题。

实验版本
================
Hbase 版本：xxx
Happybase 版本：1.1.0
Python 版本：2.7.13

问题1：filter 过滤失败
================
问题重现
-------------------
hbase 的使用场景大概是这样的：
>有一个 hbase table，存储一些文章的基本信息，包括创建时间、文章ID、文章类别ID等，同属于一个column family，"article"。
>
>查询的场景则是查找"指定的时间范围"，"文章类型ID为N" 的所有文章数据。

根据以上场景，设计如下 table：
1. hbase table 为 article 。
2. rowkey 是 "ARTICLE" + 微秒级时间戳（类似OpenTSDB 的rowkey，便于按时间序列查到某一段时间创建的 articles），即 "ARTICLE1504939752000000"。
3. family 为 "basic"，包含 "ArticleID"， "ArticleTypeID"， "Created"， 三个 column。

查询时通过指定 rowkey start 和 rowkey stop，可以 scan 某一个时间段的数据(因为 rowkey 中包含数值型的时间戳)，通过 hbase filter 实现"ArticleTypeID" == N 的过滤条件。

开始导入数据、准备查询，以下是导入数据部分代码 demo：

```python
def save_batch_events(datas, table=None):
    with get_connetion_pool().connection() as conn:
        if table is not None:
            t = conn.table(table)
        else:
            t = conn.table(TABLE)
        b = t.batch(transaction=False)
        for row, data in datas.items():
            b.put(row, data)
        b.send()

def save_main_v1():
    datas = dict()
    for i in range(100):
        article_type_id = i % 2
        timestamp = time.time() + i
        rowkey = "ARTICLE" + str(timestamp * 1000000)
        data = {
            "basic:" + "ArticleID": str(i),
            "basic:" + "ArticleTypeID": str(article_type_id),
            "basic:" + "Created": str(timestamp),
        }
        datas[rowkey] = data
    save_batch_events(datas)
```
查看一下 hbase 的数据，100 条数据全部正常导入，其中50条数据 "ArticleTypeID" 为`0`，50条为`1` ：

![图 1：python-happyhbase 写入的数据](http://upload-images.jianshu.io/upload_images/5915508-24741b37893ee8a0.png?imageMogr2/auto-orient/strip%7CimageView2/2/w/1240)

接下来就是用 hbase filter 过滤的过程了，假设查询 "ArticleTypeID" 为0 的数据，则传给 hbase 的过滤 filter 为:
```python
filter_str = "SingleColumnValueFilter('basic', 'ArticleTypeID', =, 'binary:0')" 
```
通过以下代码实现过滤查询，查询 ArticleTypeID 为 1 的数据：
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

if __name__ == '__main__':
    filter_str = "SingleColumnValueFilter('basic', 'ArticleTypeID', =, 'binary:1')"
    results = recent_events_v1(start=0, end=1505023900, filter_str=filter_str)
    print len([i for i in results])  # 期望值为50, 实际值为 0
```
问题出现：期望的查询结果为 50 条，但是查出的结果却是 0 条!

寻找原因
-----------------------
为什么会出现这种情况呢？是不是 filter 写错了呢，为了验证这一点，特意用 java 实现了相同的查询逻辑，结果也同样是 `0`。

可以确定 java 的读操作是没有问题的，那难道是 python 写入的时候出现了问题？为了验证这一点特意用 java 实现了导入数据的逻辑，然后用再用 java 查询验证，查询结果为 50 条，正确。

那 python 写入的代码是哪里出问题了呢？为此分别对比一下 python 和 java 写入 hbase 的数据：


![图 2：java 写入的数据
](http://upload-images.jianshu.io/upload_images/5915508-c1a6839eeeb3d6fd.png?imageMogr2/auto-orient/strip%7CimageView2/2/w/1240)

观察图 1 和图 2 中的数据可以发现，python 写入的数据中对应的 ArticleTypeID 值为 `0` 或 `1`，而 java 则是一串 bytes。突然意识到一个问题，hbase 读写的时候要求传入的数据类型为 bytes，而使用 python 传输的过程中这种整形数据是直接通过 `str()` 方法转成字符串存储到 hbase 中的，并不是以 bytes 的形式存于 hbase，所以使用 filter 才没能得到预期的结果。

正确的 filter 姿势
-----------------------
既然找到了原因，解决问题就比较简单了，存储的时候将整型数据全部都通过 `struct.pack` 方法转成 bytes 存入，查询的时候也将 filter 中的整型数值替换成 bytes 格式。

写入的代码：
```python
def save_main_v2():
    datas = dict()
    for i in range(100):
        article_type_id = i % 2
        timestamp = time.time() + i
        rowkey = "ARTICLE" + str(timestamp * 1000000)
        data = {
            "basic:" + "ArticleID": str(i),
            "basic:" + "ArticleTypeID": struct.pack('>q', article_type_id),
            "basic:" + "Created": str(timestamp),
        }
        datas[rowkey] = data
    save_batch_events(datas, table="test_article_2")
```
查询是的filter：
```python
filter_str = "SingleColumnValueFilter('basic', 'ArticleTypeID', =, 'binary:{value}')".format(value=struct.pack('>q', 1))
```
这样通过 filter 就能过滤出正确的结果了，同时使用上文的 java 代码可以得出正确的结果~

总结
--------------------
使用 python 读写 hbase 数据，直接传输`整型`参数时，hbase 的 thrift 接口会抛出 `TDecodeException: Field 'value(3)' of 'Mutation' needs type 'STRING'` 异常，被告知只接受 `string` 类型的数据。这时注意将整型数据转化成 bytes 形式的 str，而不要直接使用 str() 方法强转，否则难以避免的会出现一些非预期的结果。
