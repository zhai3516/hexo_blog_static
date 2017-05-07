---
title: 基于 github-webhook 的 hexo blog 搭建方案

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
``` shell
sudo yum install epel-release #基于epel源
sudo yum install nodejs
```
2. 安装 nginx
``` shell
sudo yum install nginx
```
3. 安装 git
``` shell
sudo yum install git
```
4. 创建拥有 sudo 权限的用户
``` shell
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
```shell
sudo su blog
```

hexo需要安装两部分hexo-cli和hexo-server，其中cli提供了使用hexo的一些核心命令，是使用hexo最主要的部分，server提供了预览和测试的功能，以下是具体的安装过程：
1. 安装 hexo-cli
``` shell
sudo npm install hexo-cli -g
```
2. 安装 hexo-server
``` shell
sudo npm install hexo-server -g
```
sudo npm install hexo-deployer-git --save 
3. 初始化 hexo
``` shell
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
``` shell
sudo mkdir -p /var/www/hexo
```
将目录的用户权限配置给 blog 用户
``` shell
sudo chown -R blog:blog /var/www/hexo
```
给目录增加写权限：
```shell
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
Pass


Hexo server 本地预览
====================
使用 hexo new 命令可以快速的创建一篇文章，eg：
```
# 注意在 hexo_blog 目录下运行
[blog@zhaifeng-vps0 hexo_blog]$ hexo new hexo-gihub-nginx-blog
INFO  Created: ~/hexo_blog/source/_drafts/hexo-gihub-nginx-blog.md
```
这样，在  ~/hexo_blog/source/_drafts/ 目录下就创建好一个 md 文件，并且拥有初始化了格式，直接编辑就可以。编辑好后，文件仍处于草稿状态，需要发布出去，执行命令：
``` shell
[blog@zhaifeng-vps0 hexo_blog]$ hexo publish hexo-gihub-nginx-blog
INFO  Published: ~/hexo_blog/source/_posts/hexo-gihub-nginx-blog.md
```
发布后可以在本地预览发布的效果，命令
```
hexo server 
```
会在本地 4000 端口启动一个供测试用的server，直接访问 http://127.0.0.1:4000 可以预览发布的文章效果。


