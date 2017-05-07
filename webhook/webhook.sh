#!/usr/bin/env bash

cd ~/hexo_blog_static
git pull https://github.com/zhai3516/hexo_blog_static.git
rm -rf ~/hexo_blog/source/_posts/*
cp ~/hexo_blog_static/blog-md/* ~/hexo_blog/source/_posts/

cd ~/hexo_blog
hexo clean
hexo generate
rm -rf /var/www/hexo/*
cp ~/hexo_blog/public/* /var/www/hexo/
