---
title: 反爬小述

tags:
  - 反爬
  - antispider
  - anticrawler

categories:
  - Tech

comments: true
date: 2018-04-01 14:00:00

---

反爬虫是一个持续、对抗的过程，没有一劳永逸的方法，需要不断的投入，所以，无法完全的防治爬虫，而反爬虫要做的其实归纳起来很简单：不断提升爬虫爬取成本。

# 前端保护
很多网站的对于核心数据在前端展示时都做了一些数据隐藏、编码等手段（比如图片替换文字、字符映射），对于爬虫而言，即使拿到 html，但是解析其中的内容也比较复杂。部分网站还采用动态 url生成的防范机制，难度更高。

前端做保护工作在一定程度上能提高对核心数据的保护，不断的更新前端保护机制，爬虫也需要不断研究破解机制，对爬虫来说是非常耗时的操作。

## Example
### 猫眼
猫眼电影的一些数值类数据，包括票房、票价等都是通过 “stonefont” 控制，并不是真正的数字，需要通过对应的字体字符集映射回去，而且每次请求下发的映射都是动态的：

![猫眼票价隐藏](http://om2dgc3yh.bkt.clouddn.com/antispider-1.jpeg)

所以爬取时需要兼顾爬取 html 以及字符映射关系，然后自行解析。

### 去哪儿
去哪儿票价通过前段 html 多个元素叠加合成，要是稍不注意，爬取的就是脏数据：
![去哪儿机票隐藏](http://om2dgc3yh.bkt.clouddn.com/antispider-2.jpeg)

# 后端特征

## Header 
以 web 端访问为例，正常的浏览器请求包含有效的 UA，cookie，referer 等常规信息，爬虫要完全兼顾此类信息成本较高。同样的，此类方法由于不同的浏览器特质（比如微信内浏览器）也相对容易出现误伤。

设备指纹在安全风控反作弊领域常用手段之一，通过采集设备、浏览器的信息来唯一的标识设备，通过此属性能很大程度的标识是否是无头浏览器、模拟器以及直接通过后端接口爬取数据。

通过 header 的检测方法实时性更强，其无需大量的数据积累，在兼顾准确性与误伤的同时，能更快的识别爬虫，而代价为了控制误伤就是遗漏率略高。

## 频次特征
访问频次是爬虫检测最基本的手段之一，正常用户的在浏览内容时，在单位时间内（比如1min，10 min，1hour）访问某个 path 的数值不会超过过某一阈值，这一阈值和访问具体 path 也相关，比如 zl 内容一般较多，所以阈值相对较低，而 comment 则相对较高。但是爬虫、尤其是初级爬虫，毕竟是机器访问很容易突破这一阈值，被反爬系统限制。

访问频次的检测手段对于不同的维度 member、ip、device 要有不同的阈值，尤其是 ip 维度，因为存在 “网关 ip” 这种特例，阈值相对 member 要高一些，但这样仍会会存在爬虫混在正常用户的群体中的 demo，比如校园出口 ip，学生是初级爬虫的主要生产者之一，所以 ip 访问频次的阈值虽然要相对 member、device 要大一些，但仍不能过被爬虫钻空子。

这种情况下，在限制爬虫时可以区分对待，当限制主体为 ip 时，对于已经登录的用户不会产生影响，但未登录用户会被限制，而登录用户则在以 member、device 为识别限制主体。

通过频次识别爬虫在应对初级爬虫或首次爬虫时效果较明显，能起到一定的保护后端服务以及数据的效果，但当爬虫通过调试后，能够逐渐摸索出我们的访问阈值从而控制自身的访问频率，避免被识别。此时，爬虫通分布式多 ip 策略仍能够大量、快速的爬取数据。

对于此类情况，基于行为特征的识别能发挥更大的作用。

## 访问规律
对于爬虫而言，其行为相较正常访问用户，易出现以下特点：
- 访问 url 种类单一
- 某一类 url 访问量占比高
- 访问间隔相对稳定
- 单位时间内访问数相似
…...

通过此类特征能搞很好检测出因为访问频率低而被频率策略遗漏的爬虫。比如对于爬取用户信息的爬虫，其访问特征很明显，不同于正常用户基于内容的访问，其大部分访问集中在用户类的 url 上，所以在其整体访问较集中、访问 url 的离散度过低，通过这一特点很容易可以识别出此类爬虫。

对于暴露后端接口的服务，很多爬虫通过直接拉取后端接口的方式既可获得结构化的数据，这种网站简直是爬虫的最爱，省去的解析 html 的过程。当然这类爬虫也相对比较好防治，相对正常的浏览器访问，这类防虫不会访问一些浏览器必定会触发的 ajax 请求，所以通过对比两类数据可以相对比较容易识别。

对于抓取内容的爬虫，其和正常用户最大的不同在于，用户会受内容质量、个人兴趣习惯等多种因素的影响，导致其对于不同内容的停留时间不同，请求之间的访问间隔不一，单位时间内访问量不规律，而爬虫在这一点上模仿难度较高，普通一些的爬虫在这些特征的表现比较明显，通过制定简单的策略规则既可以识别，高级一些的爬虫会使用随机访问等掩护手段，在这时普通的规则效果较差，可以通过算法模型比如 SVM、HMM 等模型分析。

# IP
对于爬虫而言，更换 ip 是非常普及的一个手段，通过代理 ip 爬取更是爬虫的通用手段，很多代理 ip 网站都提供免费的代理 ip，github 上也有很多实时爬取这些代理网站 ip 并验证可用的资源，获取成本极低。对于反爬而言，收集这类资源同样有必要，和上述特征结合使用，能极大的提高准确率，当然有条件的可以购买一些第三方的数据情报。
![西刺代理](http://om2dgc3yh.bkt.clouddn.com/antispider-3.jpeg)


除了代理 Ip 外，爬虫另外一个通用的手段就是动态拨号，对于这类ip ，需要注意控制误伤，避免长期封禁对正常用户的影响：
![动态拨号ip](http://om2dgc3yh.bkt.clouddn.com/antispider-4.jpeg)

其他更换 ip 的手段还包括 “tor 洋葱网络（已被墙，延时较高）”，相对前两者使用人数较少。

# 验证、拦截
## 403
比较通用的反爬拦截手段就是直接拦截掉用户的请求，返回 403 （或者其他状态码），切断爬虫的访问，但是这种情况比较适用于识别准确率较高的场景，对于疑似爬虫的请求一般采用验证码方式拦截。

## 验证码
验证码是各大厂拦截爬虫比较通用的手段之一，从最简单的字符验证码到 js 拖动验证码等等，通过算法也是一一被攻克：
![GitHub 开源资源](http://om2dgc3yh.bkt.clouddn.com/antispider-5.jpeg)

除了算法破解，还有打码平台的存在，直接人工识别，更是大大降低了验证码的效果：
![人工打码平台](http://om2dgc3yh.bkt.clouddn.com/antispider-6.jpeg)

现在单纯的通过验证码已经能比较容易的被破解，google 的新式验证码效果极佳，对于误伤用户的体验也很好，他直接提供一个点击框，通过对比用户的行为特征、采集浏览器信息等（还有一些google 没有透漏的特征）能比普通验证码效果更好（据说区分人类和机器之间的微妙差异，在于他/她/它在单击之前移动鼠标的那一瞬间。），目前 stackoverflow 也使用了类似的验证码。所以在验证码页面采集多采集一些行为信息，设备信息等等可以作为进一步识别爬虫的依据。

## 投毒
投毒就是对于爬虫和正常人的返回不同的结果，给爬虫以假象，让其自己为爬取到了真实数据。这同样要求识别率较高，否则造成误伤对用户体验过差。

# 其他
## 蜜罐
蜜罐也是安全圈中比较常见的一种手段，但是对于细心的爬虫来说，往往不易上当。

## 黑名单
对于被准确识别出来的爬虫，其 ip、member 信息可以构建一套自己的黑名单库，积累这种资源类数据，毕竟代理 ip、失控帐号这类数据复用相对还是比较高的。

# 一些反爬虫的资料
 
## 爬虫识别
[http://www.freebuf.com/articles/web/137763.html](http://www.freebuf.com/articles/web/137763.html)
[http://bigsec.com/bigsec-news/anan-16825-Antireptile-zonghe](http://bigsec.com/bigsec-news/anan-16825-Antireptile-zonghe)
[https://www.zhuyingda.com/blog/article.html?id=8](https://www.zhuyingda.com/blog/article.html?id=8)
[http://www.sohu.com/a/166364494_505779](http://www.sohu.com/a/166364494_505779)
[http://www.cqvip.com/main/export.aspx?id=672889284&](http://www.cqvip.com/main/export.aspx?id=672889284)
[https://github.com/equalitie/learn2ban](https://github.com/equalitie/learn2ban)
[https://patents.google.com/patent/CN103631830A/zh](https://patents.google.com/patent/CN103631830A/zh)
[http://www.xueshu.com/jsjyxdh/201704/28789559.html](http://www.xueshu.com/jsjyxdh/201704/28789559.html)
[http://www.sohu.com/a/207384581_609376](http://www.sohu.com/a/207384581_609376)
[https://www.zhuyingda.com/blog/b17.html](https://www.zhuyingda.com/blog/b17.html)

## 代理 ip 收集
[https://github.com/luyishisi/Anti-Anti-Spider/blob/master/7.IP%E6%9B%B4%E6%8D%A2%E6%8A%80%E6%9C%AF/README.md](https://github.com/luyishisi/Anti-Anti-Spider/blob/master/7.IP%E6%9B%B4%E6%8D%A2%E6%8A%80%E6%9C%AF/README.md)
[https://github.com/SpiderClub/haipproxy](https://github.com/SpiderClub/haipproxy)

## 验证码
[https://www.urlteam.org/2017/03/tensorflow%E8%AF%86%E5%88%AB%E5%AD%97%E6%AF%8D%E6%89%AD%E6%9B%B2%E5%B9%B2%E6%89%B0%E5%9E%8B%E9%AA%8C%E8%AF%81%E7%A0%81-%E5%BC%80%E6%94%BE%E6%BA%90%E7%A0%81%E4%B8%8E98%E6%A8%A1%E5%9E%8B/](https://www.urlteam.org/2017/03/tensorflow%E8%AF%86%E5%88%AB%E5%AD%97%E6%AF%8D%E6%89%AD%E6%9B%B2%E5%B9%B2%E6%89%B0%E5%9E%8B%E9%AA%8C%E8%AF%81%E7%A0%81-%E5%BC%80%E6%94%BE%E6%BA%90%E7%A0%81%E4%B8%8E98%E6%A8%A1%E5%9E%8B/)

## 前端反爬
[http://imweb.io/topic/595b7161d6ca6b4f0ac71f05](http://imweb.io/topic/595b7161d6ca6b4f0ac71f05)
[https://www.urlteam.org/2016/11/%E5%9B%9B%E5%A4%A7%E8%A7%86%E9%A2%91%E7%BD%91%E7%AB%99%E5%8F%8D%E7%88%AC%E8%99%AB%E6%8A%80%E6%9C%AF%E7%A0%94%E7%A9%B6/](https://www.urlteam.org/2016/11/%E5%9B%9B%E5%A4%A7%E8%A7%86%E9%A2%91%E7%BD%91%E7%AB%99%E5%8F%8D%E7%88%AC%E8%99%AB%E6%8A%80%E6%9C%AF%E7%A0%94%E7%A9%B6/)
