---
title: Python 读写 hbase 数据的正确姿势（二）

tags:
  - hbase
  - happybase
  - python

categories:
  - Hbase

comments: true
date: 2017-09-17 18:00:00
---
问题1：小续
=========================
上一篇文章中讨论了，在使用 filter 查询 hbase 的过程中，使用python 容易忽略的一个问题：存储整型数据的时候，容易忽略将整型数据转换成 bytes 数据进行存储，进而使用 java filter 过滤时无法过滤出正确的结果。

仔细分析这个问题的发生的过程：
1. 使用 python 将整型数据使用 `str()` 强转成字符串存入 hbase
2. 使用 java 的相关 filter，传入参数时直接使用 `Bytes.toBytes(1)` 方法将整型转成 bytes 查询
3. 无法得出正确的结果

其发生的根本原因是: 存入 hbase 的 `1` 这个值是 `str(1)` ，而使用 java 查的时候传入的过滤参数是 `int(1)` 转成的 bytes，这两者本身就不是一个类型，所以才会查出异常的结果。因此如果想用 java 在这种场景下查出正确的结果还有另一种方法，即传入的过滤参数是`str(1)` 转成的 bytes！
```java
SingleColumnValueFilter filter1 = new SingleColumnValueFilter(Bytes.toBytes("basic"),
				Bytes.toBytes("ArticleTypeID"), 
                CompareOp.EQUAL, Bytes.toBytes("1"));
                // 注意这里将传入的是字符串"1"，而不是1L 这个整数
		
// Scan python table `test_article_1`
System.out.println("Prepare to scan !");
ResultScanner scanner = table.getScanner(s);
int num = 0;
for (Result rr = scanner.next(); rr != null; rr = scanner.next()) {
	num++;
}
System.out.println("Found row: " + num);// 预期 50，结果为 50，查询到了正确的结果
```

不过在使用的过程中对于各种类型的数据最好还是通过相应的方法直接转成 bytes 存储比较好，因为字符串存储占据更大的空间。

问题2：scan 指定 start 和 end 时返回异常的结果
================
问题1讨论了一个 filter 过滤异常的问题，这次在使用 scan 指定 start、stop 做过滤时，又遇到了一个小问题。

问题重现
-------------------
上文曾经提到查询频繁的场景是：按时间序列查出某一段时间创建的 articles，所以将 rowkey 设为  "ARTICLE" + 微秒级时间戳的形式，便于使用 scan 时指定 rowstart 和 rowstop。

但是在使用 python 查询的过程中又发生了一个有趣的问题，指定 rowstart 和 rowstop 分别是：
>'ARTICLE' + str(1505024365 * 1000000)
>'ARTICLE' + str((1505024365+10) * 1000000)

因为测试数据是每秒写入一条，所以不加任何 filter ，指定以上 start 和 stop 时，预期结果数应为 10。

但是使用 python 查询出的结果确是错误的—— 0，而同样的代码去查询由使用 java 写入的数据时确能查到正确的结果。

寻找原因
------------------------------
很明显，使用 python 写入数据的逻辑仍然存在问题，再一次对比 python 和 java 写入 hbase 的数据。

使用上一篇文章中修正后的 python 代码(对应函数`save_main_v2`) 写入 hbase 的数据：
![python 写入的数据](http://upload-images.jianshu.io/upload_images/5915508-cd4f524280c1fc28.png?imageMogr2/auto-orient/strip%7CimageView2/2/w/1240)

使用 java (对应函数`test_hbase_filter1 `) 写入 hbase 的数据：
![java 写入的数据](http://upload-images.jianshu.io/upload_images/5915508-72699dfbfb9d7787.png?imageMogr2/auto-orient/strip%7CimageView2/2/w/1240)

观察数据，可以发现： column、timestamp、value 部分经过修复已经一致了，但是 rowkey 区别很明显，python中 rowkey 是这样的：
>ARTICLE1.50502434609e+15

java 中 rowkey 确是这样的：
>ARTICLE1505030804083000

而 python scan hbase 的代码中，预期的 rowkey 格式和 java 写入的格式是对应的，但和 python 写入的格式则完全不一致。
```python
    print  start_row 
    #  结果为 'ARTICLE1505030804083000' 
    #  和scan start 和 stop 对应
    #  所以从 java 写入 hbase 的数据中查询得到正确结果
```

而上文中 python 的写入代码，其构造 rowkey 时的逻辑如下：
```python
    timestamp = time.time() + i
    rowkey = "ARTICLE" + str(timestamp * 1000000)
    print rowkey
    # 结果为 'ARTICLE1.50502434609e+15' 
    # 是科学计数法表示的
    # 所以无法匹配 scan 的逻辑
```

综上，可以得出结论，因为 python 中 `time.time()` 返回值为 float型，在其 `timestamp * 1000000` 扩展到微秒后，python 是采用科学计数法表示的，所以存入 hbase 中的值并不是预期的结果，从而导致后续查询异常。

正确的 scan 姿势
------------------------
确定原因后问题就很好解决了，因为写入的 rowkey 中数值部分是 float 型，最终以科学计数法表示，所以可以 scan 查询时将传入的参数也变成 float 型，这样查询时传入的 rowkey 最终也会变成科学计数法表示的格式。
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

def main():
    results = recent_events_v1(start=0.0, end=1505024364.0, table="test_article_2")
    # 这里传入的是 `1505024364.0` 而不是 `1505024364`，下同
    print len([i for i in results])  # 期望值为50, 实际值为50
    results = recent_events_v1(start=1505024365.0, end=1505024365.0 + 10, table="test_article_2")
    print len([i for i in results])  # 期望值为10, 实际值为10
```

使用科学计数法存储的 rowkey 在 hbase 虽然也能 scan 出预期的效果，但是在对以科学计数法表示的 rowkey scan 时，rowkey 的前段和末段是相同的，不同的是中间 N 位，这样在按序 scan 时相比单调递增的 rowkey 不是很理想，参考 OpenTSDB 使用 Hbase 的方式，还是以数字型的时间戳结尾存储更加理想。

所以，更好地解决方案是，在写入 hbase 时，将 `time.time()` 返回的 float 型，转成整型后传入，使得 rowkey 以 "ARTICLE" + " int-timestamp-us" 型存储，然后使用原来的 scan 方法去查询。

拓展思考
============
Hbase 要求使用 bytes，因为 bytes 更节省存储空间，更适合海量存储的场景。在上面的场景中，rowkey 的时间戳部分是微秒型，如果使用字符串存储，其长度为：
```python
In [37]: len(bytes('ARTICLE1505645391083000'))
Out[37]: 23
```
如果将时间戳部分以整型转化成 bytes 在和前半部分拼接在一起作为 rowkey 存储显然能节省不少空间：
```python
In [41]: len(bytes('ARTICLE\x00\x05Y`b\xb1u\xf8'))
Out[41]: 15
```
那在 scan 的时候，hbase 是否也支持这种混合二进制的字典序？是否也能按指定的 start、stop 查询到正确的结果？一试便知：
```python
def save_main_v3():
    datas = dict()
    for i in range(100):
        article_type_id = i % 2
        timestamp = time.time() + i
        rowkey = "ARTICLE" + struct.pack('>q', timestamp * 1000000)
        data = {
            "basic:" + "ArticleID": str(i),
            "basic:" + "ArticleTypeID": struct.pack('>q', article_type_id),
            "basic:" + "Created": str(timestamp),
        }
        datas[rowkey] = data
    save_batch_events(datas, table="test_article_3")

def main():
    # 问题2思考
    save_main_v3()  # 导入100 条数据，50条ArticleTypeID=0，50条ArticleTypeID=1
    results = recent_events_v2(start=0, end=1505027700, table="test_article_3")
    print len([i for i in results])  # 期望值为50, 实际值为50
    results = recent_events_v2(start=1505027700, end=1505027700 + 10, table="test_article_3")
    print len([i for i in results])  # 期望值为10, 实际值为10
```

Hbase 中存储的数据：
![Hbase 中的 bytes rowkey](http://upload-images.jianshu.io/upload_images/5915508-a4d2015d7f9752db.png?imageMogr2/auto-orient/strip%7CimageView2/2/w/1240)

从以上结果能看出，使用 bytes 转化成整型的 rowkey 也是按字典序排列的，scan 可以得出预期的结果，当然这样的存储对人来说看起来比较别扭，可读性比较低，但这不影响机器，能大量的节省存储空间，明显是更优的选择。
