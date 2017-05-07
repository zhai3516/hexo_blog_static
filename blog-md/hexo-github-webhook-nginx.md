---
title: 基于 github-webhook 的 hexo-blog 搭建方案

tags:
  - hexo
  - blog
  - github
  - webhook

categories:
  - Hexo

comments: true
date: 2017-05-06 20:00:00

---

之前的 blog 一直使用的是 wordpress，搭建使用起来还算方便。但是 wordpress  比较重，对于个人 blog 开发者来说维护起来比较麻烦，所以准备迁移到比较轻量的 hexo。

hexo是一套基于 nodejs 的简单轻量的blog框架，它可以直接从 markdown 文件生成 HTML 静态页面。本文的 blog 搭建思路是：
1. 本地编辑好具体的 md 文件后，预览没有问题后，直接将 md 文件上传到 github 存储。
2. 远程的私人服务器上通过 webhook 获取 github 的变化通知，当发现有更新时，则从 github 上拉取最新的 md 文件。
3. 拉取最新的文件后 hexo 生成新的静态文件
这套方案发布简单、无需维护存储，用起来比较方便。

Prepare
==================
在安装 hexo 之前，需要做一些前期的准备工作，安装一些必备的依赖和组件

（系统 Centos 7）
1. 安装 nodejs
``` sh
sudo yum install epel-release #基于epel源
sudo yum install nodejs
```
2. 安装 nginx
``` sh
sudo yum install nginx
```
3. 安装 git
``` sh
sudo yum install git
```
4. 创建拥有 sudo 权限的用户
``` sh
# 使用 root 用户
useradd blog
passwd blog # 设置blog用户的密码
usermod -aG wheel blog
```
5. 在 github 上为 hexo 创建一个 repo，用于存储编辑的 md 文件，注意要设置为 public，本文的 git repo：
```
https://github.com/zhai3516/hexo_blog_static.git
```


安装 Hexo
=====================
接下来就是正式安装 hexo的步骤，也很简单。
在安装前先从 root 用户前切换到 刚创建的 blog 用户：
```sh
sudo su blog
```

hexo需要安装两部分hexo-cli和hexo-server，其中cli提供了使用hexo的一些核心命令，是使用hexo最主要的部分，server提供了预览和测试的功能，以下是具体的安装过程：
1. 安装 hexo-cli
``` sh
sudo npm install hexo-cli -g
```
2. 安装 hexo-server
``` sh
sudo npm install hexo-server -g
```
3. 初始化 hexo
``` sh
hexo init ~/hexo_blog # 初始化一个blog的目录
cd ~/hexo_blog 
npm install # 安装依赖
```
此时，hexo 已经安装完成，并使用 hexo 创建了一个 blog 目录，接下来就是如何配置hexo。

配置 Hexo
==================
在刚创建的 hexo_blog 目录下存在一下文件
```
-rw-rw-r--   1 blog blog  1483 May  6 06:06 _config.yml
drwxrwxr-x 287 blog blog 12288 May  6 06:24 node_modules
-rw-rw-r--   1 blog blog   443 May  6 06:06 package.json
drwxrwxr-x   2 blog blog  4096 May  6 06:06 scaffolds
drwxrwxr-x   3 blog blog  4096 May  6 06:06 source
drwxrwxr-x   3 blog blog  4096 May  6 06:06 themes
```
其中 _config.yml 是核心配置文件，blog 中的大部分配置都在这里，比如 blog 的一些基本信息：
```
  5 # Site
  6 title: Zhaif's Blog
  7 subtitle: Learn For Yourself
  8 description: My Tech Blog
  9 author: Feng zhai
 10 language: zh
 11 timezone: Chinese (China)
```
更改 Url section 的配置，指定网站的ip(或域名)：
``` 
url: http://your_server_ip
```
更改 Writing section 的配置，default_layout 设为「draft」表示文章在发表前是保存为草稿状态的。：
```
default_layout: draft 
```
关于其他配置选项细节可以参考官方文档[Docs](https://hexo.io/docs/configuration.html)

配置 Nginx
==========
首先创建一个存放blog静态文件的系统目录：
``` sh
sudo mkdir -p /var/www/hexo
```
将目录的用户权限配置给 blog 用户
``` sh
sudo chown -R blog:blog /var/www/hexo
```
给目录增加写权限：
```sh
sudo chmod -R 755 /var/www/hexo
```
然后就是给 nginx 添加配置：
```
sudo vim /etc/nginx/nginx.cfg
```
添加以下配置，这里的配置是将 blog 配置在了 8080 端口 ：
```
    server {
        listen       8080 default_server;
        listen       [::]:8080 default_server;
        root         /var/www/hexo;
        index        index.html index.htm;
    }
```

配置完成后，reload 以下 nginx 的配置：
```
sudo nginx -s reload
```
配置 Github Webhook
===========
在 github 上配置一个 webhook：
 pass

在 vps 上启动一个 webhook server 脚本，这里用 python flask 写了一个简单的：
``` python
#!/usr/bin/env python
# -*- coding: utf-8 -*-
import json
import os
import traceback

from flask import Flask, request

app = Flask(__name__)

@app.route('/webhook', methods=['POST'])
def update():
    if request.method == 'POST':
        try:
            print request.headers
            print request.json
            print os.popen("sh ~/webhook.sh").read()
        except:
            print traceback.format_exc()

    return json.dumps({"msg": "error method"})

if __name__ == '__main__':
    app.run(host="0.0.0.0", port=8888, debug=False)
```
收到请求后执行的 webhook.sh 放在 ~/ 目录下，脚本如下：
``` bash
#!/usr/bin/env bash

cd ~/hexo_blog_static
git pull https://github.com/zhai3516/hexo_blog_static.git
rm -rf ~/hexo_blog/source/_posts/*
cp -r ~/hexo_blog_static/blog-md/* ~/hexo_blog/source/_posts/

cd ~/hexo_blog
hexo clean
hexo generate
rm -rf /var/www/hexo/*
cp -r ~/hexo_blog/public/* /var/www/hexo/
```
配置好后在 『~/』 目录下 git clone 一份 github 代码，最后 『~/』 目录下的结构如下：
``` bash 
[blog@zhaifeng-vps0 ~]$ ls
hexo_blog  hexo_blog_static  webhook-server.py  webhook.sh
``` 
其中 hexo_blog 是 hexo 初始化的 blog 目录，hexo_blog_static 是拉去的 github 代码，webhook-server.py 是启动的本地 web server 用以接收 github 的请求，webhook.sh 是接收到 github 请求后更新静态文件目录的 sh 脚本。

现在，直接在本地向 github push md 文件，远程服务器就会自动更新 blog了。

附：Hexo server 本地预览
====================
编写好 markdown 文件后，可以使用 hexo-server 实现本地预览，预览没问题后直接push 就可以~
1. 使用 hexo new 命令可以快速的创建一篇文章，注意在 hexo_blog 目录下运行，eg：
``` bash
[blog@zhaifeng-vps0 hexo_blog]$ hexo new hexo-gihub-nginx-blog
INFO  Created: ~/hexo_blog/source/_drafts/hexo-gihub-nginx-blog.md
```
这样，在  ~/hexo_blog/source/_drafts/ 目录下就创建好一个 md 文件，并且拥有初始化了格式，直接编辑就可以。编辑好后，文件仍处于草稿状态，需要发布出去，执行命令：
``` sh
[blog@zhaifeng-vps0 hexo_blog]$ hexo publish hexo-gihub-nginx-blog
INFO  Published: ~/hexo_blog/source/_posts/hexo-gihub-nginx-blog.md
```
发布后可以在本地预览发布的效果，命令
```
hexo server 
```
会在本地 4000 端口启动一个供测试用的server，直接访问 http://127.0.0.1:4000 可以预览发布的文章效果。

参考
===================
https://www.digitalocean.com/community/tutorials/how-to-create-a-blog-with-hexo-on-ubuntu-14-04
https://aaron67.cc/2017/02/19/hexo-backup-and-deploy-solution-based-on-gitlab-ci-and-webhook/
https://hexo.io/docs/
