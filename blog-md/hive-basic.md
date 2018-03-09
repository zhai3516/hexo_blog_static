---
title: Hive 基本语法

tags:
  - hive

categories:
  - Hive

comments: true
date: 2018-01-20 21:00:00
---
建表
============

通用建表
-------------
```
CREATE TABLE IF NOT EXISTS `Db.Table`(
  `uuid` string, 
  `user_id` int, 
  `user_ip` string, 
  `created` int, 
  `user_agent` string, 
  `device_id` bigint,
  `referer` string)
COMMENT 'This is a test table'
PARTITIONED BY (ptdate string)
CLUSTERED BY(userid) SORTED BY(created) INTO 64 BUCKETS
ROW FORMAT DELIMITED 
  FIELDS TERMINATED BY '\t'
  COLLECTION ITEMS TERMINATED BY ','
  MAP KEYS TERMINATED BY  ':'
STORED AS TEXTFILE
LOCATION  'hdfs://localhost:8020/user/test/logs/a'
```

利用查询结果建表
---------------------------
```
CREATE TABLE IF NOT EXISTS `Db.Select` AS
  SELECT * 
  FROM TABLE_TEST
  WHERE XX=XX
```

建表并复制表结构
------------------------
```
CREATE TABLE  IF NOT EXISTS `Db.Table` LIKE `Db.Tablelike`
```

Tips
----------
1. `TABLE` 和 `EXTERNAL TABLE` 主要区别在于表数据的存储位置，`TABLE` 创建表后会到 HDFS 加载数据，并将数据移动到数据仓库目录下，因次删除表时对应的 HDFS 和表的元数据一起被删除，但是 `EXTERNAL TABLE` 的实际数据仍在存在 `LOCATION  'hdfs://localhost:8020/user/test/logs/a'` 对应的 HDFS 路径下，所以删表时 HDFS 数据仍在存在，只是 hive 表的元数据被删除。另外还有 `TEMPORARY TABLE`，只在当前登录用户 session 有效，失效后被删除。
2. PARTITIONED BY(XX type) 指定 Hive 表按指定字段分区，一个 partition 对应数仓下表的一个目录，可以理解为设置的 partition 列的索引，一个通用的 case 就是 hive 表数据按天切成多个 partition。
3. CLUSTERED BY 指定了 hive 表按指定列基于 hash 分桶并按在桶内按指定列排序，桶是比分区更细粒度的数据划分，同时支持排序，在一些查询场景下（比如抽样）查询处理效率更高。
4. ROW FORMAT `DELIMITD` 指定了数据行的格式，表示支持列分隔符，每行数据通过 `\t` 区分 filed ，每个 filed 内如果是 array 则通过 `,` 分区元素，如果是 map 则通过  `:` 区分 key 和 value。ROW FORMAT 还支持其他格式，eg:
JSON:
```
ROW FORMAT SERDE 
  'org.openx.data.jsonserde.JsonSerDe'
```
正则：
```
ROW FORMAT SERDE 
  'org.apache.hadoop.hive.serde2.RegexSerDe'
WITH SERDEPROPERTIES (
  "input.regex" = " (-|[0-9]*) (-|[0-9]*)(?: ([^ \"]*|\".*\") ?"
)
```
5. STORED AS TEXTFILE，指定了数据的存储格式，表示以纯文本形式存储。其他还包括：
```
# 文件存储格式 
  : SEQUENCEFILE
  | TEXTFILE    -- (Default, depending on hive.default.fileformat configuration)
  | RCFILE      -- (Note: Available in Hive 0.6.0 and later)
  | ORC         -- (Note: Available in Hive 0.11.0 and later)
  | PARQUET     -- (Note: Available in Hive 0.13.0 and later)
  | AVRO        -- (Note: Available in Hive 0.14.0 and later)
  | INPUTFORMAT input_format_classname OUTPUTFORMAT output_format_classname
```

修改表
==============

hive 新增列
--------------------
```
ALTER TABLE `Db.Table` ADD COLUMNS user_level INT
```

hive 改列
-------------
修改列的类型
```
ALTER TABLE `Db.Table` CHANGE user_id user_id STRING
```
修改列名
```
ALTER TABLE `Db.Table` CHANGE user_id new_user_id INT
```
修改列名后改变列在表中的位置
```
放在最前:
ALTER TABLE `Db.Table` CHANGE user_id new_user_id INT FIRST
放在列 uuid 后:
ALTER TABLE `Db.Table` CHANGE user_id new_user_id INT AFTER uuid
```

hive 新增分区
--------------
```
ALTER TABLE `Db.Table`  ADD PARTITION ( ptdate='2017-09-28')
LOCATION 'hdfs://localhost:8020/user/test/logs/a/2017-09-28';
```

hive 删分区
-----------------
```
ALTER TABLE `Db.Table`  DROP PARTITION ( ptdate='2017-09-28')

```
删表
==============

清空全表数据
--------------
```
TRUNCATE TABLE `Db.Table` 
```

清空表指定 partition 数据
--------------
```
TRUNCATE TABLE `Db.Table` PARTITION (ptdate='2017-09-28')
```

hive 删表
---------------
```
DROP TABLE IF EXISTS `Db.Table`
```

写入数据到表
=================

文件数据写入
------------------
```
# `OVERWRITE` 表示覆盖原表 partition
LOAD DATA INPATH "hdfs://localhost:8020/user/test/logs/test.txt"
OVERWRITE INTO TABLE `Db.Table` PARTITION (ptdate='2017-09-28')
```
注意：test.txt 文件格式要符合建表时 ROW FORMAT 配置， eg: 使用上面建表的 ROW FORMAT 配置，则下表中 array 类型 的 ip  和 map 类型的 request 格式如下：

| user_id(int) | \t | created(int) | \t | ip(array<string>) | \t | request(map<int:int>) |
|----------------|----|---------------|---|------------------------|----| -------|
|123|	|456|	|11.11.11.11,22.22.22.22|	|1:1,2:2|

查询结果写入
---------------------
```
# `OVERWRITE` 表示覆盖原表 partition
INSERT OVERWRITE TABLE `Db.Table` PARTITION (ptdate='2017-09-28')
  SELECT user_id, created, ip, request
  FROM `Db.TableSource`
  WHERE ptdate='2017-09-28' and user_id=123
```
or
```
FROM `Db.TableSource`
INSERT OVERWRITE TABLE `Db.Table` PARTITION (ptdate='2017-09-28')
  SELECT user_id, created, ip, request
  WHERE ptdate='2017-09-28' and user_id=123
```
