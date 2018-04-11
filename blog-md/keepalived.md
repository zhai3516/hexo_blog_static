---
title: Keepalived HA & LB 配置

tags:
  - Keepalived
  - High-availability
  - Loadbalance
  - LVS


categories:
  - Tech

comments: true
date: 2015-12-03 18:00:00

---

# 简介
Keepalived 是一款由 C 编写的路由软件，其提供了简单快捷的配置，实现系统级高可用，比如常见的 keepalived+nginx 高可用，keepalived+mysql 双主模式等，以及 LVS 负载均衡配置。

# 高可用（ high-availability）
Keepalived 实现高可用主要基于 `VRRP（Virtual Router Redundancy Protocol）`协议。简单来说 VRRP协议规定，由 N 台设备组成一个路由分组，整个路由分组对外提供一个 virtual ip ，对调用方而言可以主要方位 virtual 即可。

在整个分组内部，有两种角色，一种是 master，其持有这个 virtual ip，当调用方来访问时，其实访问的是 master；另一种角色 backup，当 keepalived 的 health checker 检测到 master 不可用是，backup 会竞争成为 master，获取 virtual ip，从而避免 master 挂掉出现单点故障。

## keepalived + nginx  原理
keepalived + nginx 的高可用模式就是两台设备分别配置成 Master 和 Backup，并且安装、启动相同配置的 nginx，对外提供一个 virtual ip 给客户端使用，当客户端访问 virtual ip 时，实际访问的是 master 上的 nginx，而当 master 挂掉时，backup 竞选成为 master 接管 virtual ip，此时客户端访问的就是 backup 上的 nginx 了。

这里将 192.168.1.104，192.168.1.105 两台设备分别配置 keepalived 的 master 和 backup，配置一个 virtual ip 192.168.1.106 的路由分组。

## 安装
下面以 centos 6 为例安装 keepalived
```shell
wget http://www.keepalived.org/software/keepalived-1.2.13.tar.gz

yum install kernel-devel openssl-devel libnl-devel

tar xzvf keepalived-1.2.13.tar.gz

cd keepalived-1.2.13

./configure --prefix=/usr/local/keepalived -disable-fwmark   #（keepalived安装在 /usr/local/keepalived/ 目录下)

make && make install

mkdir /etc/keepalived

cp /usr/local/keepalived/etc/keepalived/keepalived.conf /etc/keepalived/

cp /usr/local/keepalived/etc/rc.d/init.d/keepalived /etc/init.d/

cp /usr/local/keepalived/etc/sysconfig/keepalived /etc/sysconfig/

ln -s /usr/local/keepalived/sbin/keepalived /sbin/

chkconfig keepalived on   #开机自启动
```

安装好后可以通过命令 `/etc/init.d/keepalived start`  或者 `service keepalived start` 启动

## 配置
安装好后，可以修改配置文件 /etc/keepalived/keepalived.conf 更改配置实现高可用：

```
# 全局配置
global_defs {
    #表示keepalived在发生诸如切换操作时发送Email给哪些地址，邮件地址可以多个，每行一个
    notification_email {
        admin@example.com
    }
    #表示发送通知邮件时邮件源地址是谁
    notification_email_from admin@example.com
    #表示发送email时使用的smtp服务器地址，这里可以用本地的sendmail来实现
    smtp_server 127.0.0.1
    #连接smtp连接超时时间
    smtp_connect_timeout 30
    #机器标识
    router_id MySQL-HA
}
vrrp_script {
    script “ “
    interval 5
    weight -2
}
vrrp_instance nginx-ha {
    state BACKUP           #state指定instance的初始状态，但这里指定的不算，还是得通过优先级竞选来确定。两台配置此处均是BACKUP。
    interface eth0         #实例绑定的网卡，因为在配置虚拟IP的时候必须是在已有的网卡上添加的
    virtual_router_id 81   #这里设置VRID，这里非常重要，相同的VRID为一个组，他将决定多播的MAC地址
    priority 100           #设置本节点的优先级，优先级高的为master
    advert_int 1           #检查间隔，默认为1秒，组播间隔
    authentication {       #这里设置认证
        auth_type PASS
        auth_pass 1111
    }
    virtual_ipaddress {    #这里设置的就是VIP，也就是虚拟IP地址
        192.168.1.106
    }
    track_script {
check
    }
}
```
## Tips
配置中有一些要注意（踩过的坑。。。）：

- 分组是通过属性 `virtual_router_id` 实现，所以同意分组 virtual_router_id 一定要相同。
- `state BACKUP / MASTER` 不能真正决定其角色，而是通过 priority 选举实现的，所以一定要避免出现 priority 相同的情况
- 设置的 `virtual_ipaddress` 不能被占用
- 组播间隔 `advert_int` 设置一定要相同，否则可能会出现 backup 的 priority 低，却在 master 健康的时候竞选成为 master，比如master为5秒,backup为1秒,结果是backup生效,master的keepalived失效,此时只有backup在发组播包。

# 负载均衡（Loadbalance）
Keepalived 实现负载均衡主要利用的大名鼎鼎的 `Linux Virtual Server (LVS)` 技术，和 nginx、haproxy 不同的是 LVS 提供的“Layer 4 load balancing”，而不是 “Layer 7”，所以其最大的优点是性能爆炸，因为其直接将 TCP、UDP 包直接转发，而不需要像 nginx 或 haproxy 一样解析组 http 包，消耗 cpu 极低。

要配置 LVS，linux 系统需要安装 ipvsadm 模块，配置 keepalived lb 本质上就是配置 ipvsadm 的规则。

keepalived + LVS 是一套实现高可用负载均衡通用方案。

## Deractor & RealService
整个 LVS 集群中包含两种角色：Director 和 Real Service，其中Director 负责转发流量，Real Service 是真正处理请求的服务端。

一般选择大于等于两台配置好 HA keepalived 设备作为 Director，再配置 N 台真正处理请求的 Real Service 处理请求。这里在上文配置好 virtual ip 192.168.1.106 的基础上增加 keepalived 的配置文件中RealService <192.168.1.101, 192.168.1.102, 192.168.1.103> 的配置。

## keepalived 配置
在上文配置好 HA后，继续添加 real service 的配置：
```
virtual_server 192.168.1.106 1000 {
    delay_loop 2  #每个2秒检查一次real_server状态
    lb_algo wrr    # 负载均衡算法，wrr 是加权轮训。
    lb_kind DR     #  负载均衡类型 ，NAT|DR|TUN ，
    persistence_timeout 60   #会话保持时间
    protocol TCP  # 协议类型
    real_server 192.168.1.101 1000 {
        weight 3
        TCP_CHECK {
            connect_timeout 10     #连接超时时间
            nb_get_retry 3         #重连次数
            delay_before_retry 3   #重连间隔时间
            connect_port 1000      #健康检查端口
        }
    }
real_server 192.168.1.102 1000 {
        weight 3
        TCP_CHECK {
            connect_timeout 10     #连接超时时间
            nb_get_retry 3         #重连次数
            delay_before_retry 3   #重连间隔时间
            connect_port 1000      #健康检查端口
        }
    }
    real_server 192.168.1.103 1000 {
        weight 3
        TCP_CHECK {
            connect_timeout 10     #连接超时时间
            nb_get_retry 3         #重连次数
            delay_before_retry 3   #重连间隔时间
            connect_port 1000      #健康检查端口
        }
    }
}
```
上文配置的虚拟 ip 是 192.168.1.106，加上这段配置后，发往192.168.1.106:1000 的请求会被转发到 192.168.1.101，192.168.1.102，192.168.1.103 三台 real server 上。

## Real service 配置
分别在  192.168.1.101，192.168.1.102，192.168.1.103 三台 real server 上配置 lookback：

```
touch /etc/sysconfig/network-scripts/ifcfg-lo101 # 其他两台 ifcfg-lo102，ifcfg-lo103
```
然后编辑文件 ifcfg-lo101，ifcfg-lo102，ifcfg-lo103:

```
DEVICE=lo:101  # 其他为lo:102, lo:103

IPADDR = 192.168.1.101 # 对应给子设备的 ip

NETMASK = 255.255.255.255

# If you're having problems with gated making 127.0.0.0/8 a martian,

# you can change this to something else (255.255.255.255, for example)

#BROADCAST=127.255.255.255

#ONBOOT=yes # 开始自动启动，尝试配置的时候最好不要打开此配置，容易出现故障时无法通过跳板机登录，需要机房直接服务器该配置，不要问我怎么知道的。。。！！！

#NAME=loopback
```

配置好后分别通过命令 ifup lo:101， ifup lo:102， ifup lo:103 启动，如果需要下线则使用 ifdown lo:101, ifdown lo:102, ifdown lo:103。

## 查看状态
ipvsadm 提供了相关的命令查看添加当前的负载均衡状态：

- ipvsadm -l n  查看 ipvsadm 的转发规则（通过keepalived 配置的）以及当前各节点状态
- ipvsadm -L c 查看当前转发分配

# 附录
http://www.keepalived.org/

http://www.keepalived.org/doc/index.html
