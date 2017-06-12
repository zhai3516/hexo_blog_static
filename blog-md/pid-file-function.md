---
title: 从一次事故谈谈 pid 文件的作用

tags:
  - pid

categories:
  - Tech

comments: true
date: 2017-05-26 20:00:00

---

很多程序在启动后会在 /var/run 目录下创建一个文件 xxx.pid 文件，用以保存这个进程的进程号。之前一直以为这个文件仅仅是用来控制进程的启动和关闭，直到最近遇到的一个惨痛的教训...

# 先讲个故事(也是个事故...)
最近手头的一个工作是分析全站的镜像流量，流程大概是抓取网卡的所有帧逐层解析，最终是在应用层实现重组 http 会话，将重组后的数据发送到 kafka 供后端分析。（程序的代码在 [http-capture](https://github.com/zhai3516/http_capture)）

程序的细节这里不谈，直接进入事故...

一开始这个程序是直接跑在后台的，为了保证程序的可靠性，准备托管给 [supervisor](https://github.com/Supervisor/supervisor)。于是巴拉巴拉把 supervisor 的配置文件写好，然后 supervisorctl update，把程序跑起来了。

嗯，supervisorctl status 看一下，http-capture 状态变成 running，没毛病，非常稳！再 ps 查看一下进程的大概情况，我了个去有两个 http-capture 进程在工作，原来之前运行在后台的进程忘记关掉了！

由于是使用 ansible 批量操作的，所以全部的12台设备都是启动了两个进程，也就是说每台设备同时输出了两份相同的数据！再一看kafka 那边的入队情况，果然 double 了。oh，my god！

事故整个复盘就是这么简答，后续的处理、恢复工作就先不谈了。

# 事后分析
整个事故直接原因总结起来很简单，就是操作人员大意，误操作导致的。但是深究背后的程序是否存在问题呢，当然存在很多问题的。

- 首先，我在操作过程中测试成功后直接使用 ansible 全量上线。更合适的方式应该是先ansible 操作1~2台设备上线，然后待观察稳定后全量上线。

- 其次，**就是程序本身存在问题，逻辑不够严谨**，这种要保证一台服务器上只能唯一启动的进程，在程序启动逻辑中就应该验证这个条件。

- 另外，就是问题的发现过程，是偶然的通过 ps 命令查看进程此发现的此问题，缺少统一的监控、告警工具。

- 最后，发现问题后，没有快速的回滚机制，只能通过命令依次全部 kill 掉后，但是此时有大量的数据走入后端了，容错能力不足。

总体说在，就是在程序启动、运行、关闭的过程中缺少必要的检测、容错和恢复手段。其他的不谈，这里重点说说第二点，程序自身的问题，如何实现程序自身的启动检测。

# Pid 文件的作用
pid 文件是什么呢？打开系统(Linux) 的 "/var/run/" 目录可以看到有很多已 ".pid"  为结尾的文件，如下：
![/var/run 目录下的 pid 文件](http://om2dgc3yh.bkt.clouddn.com/pid-blog-1.jpeg)

这些文件只有一行，它记录的是相应进程的 pid，即进程号。所以通过 pid 文件可以很方便的得到一个进程的 pid，然后做相应的操作，比如检测、关闭。

那 pid 文件是不是只是存储呢？当然不是！它还有另一个更重要的作用，那就是**防止进程启动多个副本**。通过文件锁，可以保证一时间内只有一个进程能持有这个文件的写权限，所以在程序启动的检测逻辑中加入获取pid 文件锁并写pid文件的逻辑就可以防止重复启动进程的多个副本了。

下面是实现这个逻辑的一段 c 代码，在程序的启动检测逻辑中调用这个函数即可保证程序唯一启动。

```c
void writePidFile(const char *szPidFile)
{
    /* 获取文件描述符 */
    char str[32];
    int pidfile = open(szPidFile, O_WRONLY|O_CREAT|O_TRUNC, 0600);
    if (pidfile < 0) {
        printf("pidfile is %d", pidfile);
        exit(1);
    }
   
    /* 锁定文件，如果失败则说明文件已被锁，存在一个正在运行的进程，程序直接退出 */
    if (lockf(pidfile, F_TLOCK, 0) < 0) {
        fprintf(stderr, "File locked ! Can not Open Pid File: %s", szPidFile);
        exit(0);
    }

    /* 锁定文件成功后，会一直持有这把锁，知道进程退出，或者手动 close 文件
       然后将进程的进程号写入到 pid 文件*/
    sprintf(str, "%d\n", getpid()); // \n is a symbol.
    ssize_t len = strlen(str);
    ssize_t ret = write(pidfile, str, len);
    if (ret != len ) {
        fprintf(stderr, "Can't Write Pid File: %s", szPidFile);
        exit(0);
    }
}
```

# 参考文档
https://unix.stackexchange.com/questions/12815/what-are-pid-and-lock-files-for
https://www.zhihu.com/question/20289583
https://stackoverflow.com/a/13651761/5126723
http://www.man7.org/tlpi/code/online/dist/filelock/create_pid_file.c.html

