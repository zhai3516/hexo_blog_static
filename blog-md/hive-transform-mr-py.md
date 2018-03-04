---
title: Hive-Transform-Python:快捷的Map/Reduce

tags:
  - hive
  - transform
  - map/reduce
  - python

categories:
  - Hive

comments: true
date: 2018-03-04 17:00:00
---
Hive 提供了 Transform 这一关键字，使用 python 脚本处理hive 的数据，实现 Map/Reduce 的效果，在一些场景下，相比直接编写 Hadoop MR 要方便不少。

# 简介
首先简要介绍一下 hive sql 语句的编写逻辑以及 python 脚本的编写方法。

## hive 部分编写

hive transform sql 的一个很常用的模式是：
- hive sql 通过查询语句获取输入源数据
- 调用 python 脚本 MAP、REDUCE 处理数据
- hive sql 将 python 的处理结果入库或其他操作后续操作

执行 hive 前要先加载 python 脚本，脚本可以上传到 hdfs 上，通过语句 `ADD FILE hdfs://xxxx` 加载。

比如从 表A 中 读取数据，通过 python MAP/REDUCE脚本处理后将处理结果写入表 B，对应的 hive 语句约为：
```hive
ADD FILE hdfs://xxxx;
FROM (
  FROM (
    SELECT *
            FROM TABLE-A
  ) T  
  MAP T.a, T.b, T.c
  USING 'python ./map.py'
  AS d, e, f
  CLUSTER BY d
) map_out
INSERT OVERWRITE TABLE-B
REDUCE map_out.d, map_out.e, map_out.f
USING 'python ./reduce.py'
AS (g ,h ,i)
```

## python 部分编写

python 脚本的处理逻辑大概可以分为三部分：
- 从 hive 获取输入数据
- map、reduce 操作
- 输出数据给 hive

其中输入、输出部分是利用系统标准输入输出流实现的，python 从 sys.stdin 中获取 hive 传入的数据，将处理结果通过 sys.stdout 传给 hive。

python 标准输入获取的每一行对应 hive sql 的一条数据，每一行通过 `\t` 区分 hive 表的各个字段值。同样的，输出给 hive 的每一行中不同的字段值也要通过 '\t' 连接，否则 hive 会解析错误。

以 map 处理为例，python 脚本通过用的模式如下：
```python
#!/usr/bin/env python
# coding: utf8
import sys

def map_field(a,b):
    return a+1, b+1

for line in sys.stdin:
    a, b = line.split('\t')
    c, d = map_field(a,b)
    print c + '\t' + d
```


# Example
下面介绍一个使用 hive-transform 统计用户 Get/Post 请求数的例子。在这个例子中将从一张记录所有用户请求记录的表 `member_source_request` 中读取源数据，并过滤掉 `OPTION` 等请求，只统计 `GET`,`POST`,`PUT`,`DELET` 四种请求。并将记录结果写入到一张 `member_method_count` 表中。

member_source_request 表 schema：

|   | Name | Type |   
| --- | --- | --- |
| 1 | member_id | int | 
| 2 | method | string | 
| 3 | url| string | 
| 4 | ip | string |   
| 5 | ...|... |

创建  member_method_count 表：
```hive
CREATE TABLE tmp.member_method_count(
    member_id INT,
    get_request BIGINT,
    put_request BIGINT,
    post_request BIGINT,
    delete_request BIGINT
)
partitioned by (`date` INT)
```

## Hive SQL
    ADD FILE hdfs:///member-method.py; 
    FROM (
        FROM (
            SELECT *
            FROM tmp.member_source_request
            WHERE member_id is not null
        ) T
        MAP T.member_id, T.method, T.url
        USING 'python ./member-method.py --mapper'
        AS member_id, method, url
        CLUSTER BY member_id
    ) map_out
    INSERT OVERWRITE TABLE tmp.member_method_count PARTITION (date=20180220)
    REDUCE map_out.member_id, map_out.method, map_out.url
    USING 'python ./member-method.py --reducer'
    AS member_id, get_request, put_request, post_request, delete_request

## python 脚本
 MemberRequestJob 为具体实现 map、reduce 逻辑，其父类可服用
```python
#!/usr/bin/env python
# coding: utf8
import sys
from collections import defaultdict

class MRJob(object):
    def __init__(self, sep='\t'):
        self.sep = sep

    def map(self, line):
        raise NotImplementedError()

    def reduce(self, key, value):
        raise NotImplementedError()

    def map_end(self):
        pass

    def reduce_end(self):
        pass

    def run_mapper(self):
        for line in sys.stdin:
            line = line.strip('\n').strip('\t')
            self.map(line)
        if hasattr(self, 'map_end'):
            self.map_end()

    def run_reducer(self):
        for line in sys.stdin:
            line = line.strip('\n').strip('\t')
            key, value = line.split(self.sep, 1)
            self.reduce(key, value)
        if hasattr(self, 'reduce_end'):
            self.reduce_end()

    def output(self, key=None, value=None):
        print str(key) + self.sep + str(value)

    def run(self):
        if len(sys.argv) <= 1:
            raise Exception('--mapper or --reducer must be set')
        self.args = tuple(sys.argv[2:])
        if sys.argv[1] == '--mapper':
            self.run_mapper()
        elif sys.argv[1] == '--reducer':
            self.run_reducer()


class FieldMRJob(MRJob):

    def __init__(self, field_sep='\t', sep='\t'):
        MRJob.__init__(self, sep)
        self.field_sep = field_sep

    def map_fields(fields):
        raise NotImplementedError()

    def reduce_fields(key, fields):
        raise NotImplementedError()

    def map(self, line):
        fields = line.split(self.field_sep)
        self.map_fields(fields)

    def reduce(self, key, value):
        values = value.split(self.field_sep)
        self.reduce_fields(key, values)

    def output(self, key=None, values=()):
        value = self.field_sep.join(map(str, values))
        MRJob.output(self, key, value)


class MemberRequestJob(FieldMRJob):
    def __init__(self):
        FieldMRJob.__init__(self)
        self.all_member = set()
        self.all_get_counts = defaultdict(int)
        self.all_post_counts = defaultdict(int)
        self.all_put_counts = defaultdict(int)
        self.all_delete_counts = defaultdict(int)

    def map_fields(self, fields):
        member_id, method, url = fields
        if method in ['GET', 'PUT', 'POST', 'DELETE']:
            self.output(member_id, (method, url))

    def reduce_fields(self, member_id, fields):
        method, url = fields
        self.all_member.add(member_id)
        if method == 'GET':
            self.all_get_counts[member_id] += 1
        elif method == 'POST':
            self.all_post_counts[member_id] += 1
        elif method == 'PUT':
            self.all_put_counts[member_id] += 1
        else:
            self.all_delete_counts[member_id] += 1

    def reduce_end(self):
        for member_id in list(self.all_member):
            self.output(member_id, (self.all_get_counts.get(member_id, 0),
                                    self.all_put_counts.get(member_id, 0),
                                    self.all_post_counts.get(member_id, 0),
                                    self.all_delete_counts.get(member_id, 0)
                                    )
                        )


if __name__ == '__main__':
    MemberRequestJob().run()
```
