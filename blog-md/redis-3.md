---
title: Redis 分布式锁实现分析

tags:
  - redis
  - distributed-lock

categories:
  - Redis

comments: true
date: 2016-02-01 22:30:00

---

> 维基百科:
**分布式锁**，是控制[分布式系统](https://zh.wikipedia.org/wiki/%E5%88%86%E5%B8%83%E5%BC%8F%E7%B3%BB%E7%BB%9F "分布式系统")之间同步访问共享[资源](https://zh.wikipedia.org/wiki/%E8%B5%84%E6%BA%90 "资源")的一种方式。在分布式系统中，常常需要协调他们的动作。如果不同的系统或是同一个系统的不同主机之间共享了一个或一组资源，那么访问这些资源的时候，往往需要[互斥](https://zh.wikipedia.org/wiki/%E4%BA%92%E6%96%A5 "互斥")来防止彼此干扰来保证一致性，在这种情况下，便需要使用到分布式锁。
                 
常用的分布式锁主要包括：基于关系数据库的，基于缓存的，以及基于 zookeeper 的。这里主要介绍一下基于 redis 实现的分布式锁。

# 使用

以 python 为例，对应的 redis-py 库提供了一版基于 redis 实现的分布式锁：

> 库地址：[https://github.com/andymccurdy/redis-py](https://github.com/andymccurdy/redis-py)

其主要用法是通过 context manager 获取、释放锁，使用起来非常简便，示例代码如下：
```
redis_cli = redis.StrictRedis()
with redis_cli.lock(name="test", sleep=60) as lock:
    do_something()
```

其中 lock 函数会返回 [Lock class](https://github.com/andymccurdy/redis-py/blob/master/redis/lock.py) 对象，Lock class 的一些主要参数包括：

 ```
timeout: 锁的有效期，支持整数和浮点数，默认不过期，除非主动释放
sleep: 阻塞模式下，当锁被其他 client 获取时，当前 client 请求锁的间隔，默认 0.1s
blocking: 是否阻塞模式
blocking_timeout: 阻塞的超时时间，默认永久，直到获取锁
thread_local: lock token 存储在线程本地存储，避免线程级使用同样的 token，默认开启`
```

timeout 如果设置为永久，可以避免 client 因为超时而释放锁，导致其他 client 同时获取锁的意外场景。当然这样也存在一定的风险，当进程意外退出而没有释放锁时，lock 会永久存在，不会被释放，进而出现死锁，下面会进一步分析这个问题。

如果是多线程模型，最好开启 thread_local，否则可能会出现两个线程共用同一个 token 而出现同时获取锁的场景。

# 源码

redis-py Lock class 实现的分布式锁主要代码分为三部分，第一不是分 acquire lock 的逻辑，第二部分是 release lock 的逻辑，第三部分是 extend lock 的逻辑。前两部分通过 context manager 控制，保证

获取锁的[实现代码](https://github.com/andymccurdy/redis-py/blob/5109cb4f6b610e8d5949716a16435afbbf35075a/redis/lock.py#L90)逻辑归纳如下：

1.  首先，基于 uuid 随机生成唯一 token `token = b(uuid.uuid1().hex)`
2.  通过 set(key, value, nx=True, px=timeout) 实现获取锁，即如果不存在 key 则写 kv 到 redis，即获得锁，否则写失败，说明锁已经被获取。
3.  如果是非 blocking 模式，在 acquire lock 失败后会直接返回 false
4.  如果是 blocking 模式，则会基于当前时间以及block time，计算出停止尝试获取锁的超时时间（即 time.time() + block_time），然后根据设定的 sleep 时间定时重试，直到过期或者获得锁。

redis 的分布式锁主要是基于 set 接口实现，通过写成功与失败判定是否获得锁，通过 key 的 ttl 控制锁超时。

释放锁的[实现代码](https://github.com/andymccurdy/redis-py/blob/5109cb4f6b610e8d5949716a16435afbbf35075a/redis/lock.py#L130)逻辑归纳如下：

1.  首先从 redis 读取当前锁的 token （get key）
2.  对比 thread-local 存储的 token 和redis 读取得 token 是否一致，不同则无法删除，说明锁已经被其他 client 获取（compare token）
3.  删除锁 （del key）整个过程通过 redis transaction实现。

整个 get - compare - delete 的过程之所以使用 transaction 实现，是为了避免在 get - delete 这个时间差内，由于锁过期，而其他 client 获取锁，执行delete 操作时误删除了其他 client 的锁，这种特殊情况。

续期锁的[实现代码](https://github.com/andymccurdy/redis-py/blob/5109cb4f6b610e8d5949716a16435afbbf35075a/redis/lock.py#L149)逻辑归纳如下：

1.  校验 thread-local  token 是否存在
2.  校验是否为永久有效的锁
3.  从 redis 读取当前锁的 token （get key），并和 thread-local token 对比（同释放锁逻辑 1，2 步）
4.  获取锁的剩余时间，并重新设置 key 的过期时间

从实现逻辑可以发现，当获取的锁是永久有效时，如果进程此时发生异常（比如断电），锁是不会被释放的，所以此后这个锁就无法再被获取，即形成上文提到的死锁问题，此时只能通过手动删除这个 key 的方式释放资源。

线上环境可以采用带有 timeout 的模式，同时处理请求的场景设定相应的 timeout，让锁的 timeout 时间大于业务处理超时，避免发生死锁。

# 实现 Reset

extend 能续约锁，这里实现一个 reset 操作，实现刷新锁的持续时间:

```
from redis.lock import Lock
from redis.exceptions import LockError, WatchError
 
class RedisLock(Lock):
    def __init__(self, *args, **kwds):
        super(RedisLock, self).__init__(*args, **kwds)

    def reset(self, timeout):
    '''
    reset the timeout of an already acquired lock
    'timeout' can be specified as an integer of a float , both representing the number of seconds reset to the lock
    '''
      if self.local.token is None:
        raise LockError("Cannot reset an unlocked lock")
   
      return self.do_reset(timeout)

    def do_reset(self, timeout):
      pipe = self.redis.pipeline()
      pipe.watch(self.name)
      lock_value = pipe.get(self.name)
      if lock_value != self.local.token:
        raise LockError("Cannot reset a lock than is no longer owned")
      expiration = pipe.pttl(self.name)
      if expiration is None or expiration < 0:
        expiration = 0
      pipe.multi()
      pipe.pexpire(self.name, int(timeout*1000))
      try:
        response = pipe.execute()
      except WatchError:
        raise LockError("Reset failed, lock is invalid ,someone else acquired lock")
      if not response[0]:
        raise LockError("Reset failed, lock is invalid ,someone else acquired lock")

      return True
```
