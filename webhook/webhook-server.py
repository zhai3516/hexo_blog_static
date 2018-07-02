#!/usr/bin/env python
# -*- coding: utf-8 -*-
import time
import json
import os
import Queue
import traceback
import thread


from flask import Flask, request


tasks = Queue.Queue(100)
def update_blog():
    print "Run backgroud process to update blog"
    while True:
        result = tasks.get()
        if result:
            try:
                print os.popen("sh /home/blog/webhook.sh").read()
            except:
                print traceback.format_exc()
        time.sleep(1)
thread.start_new_thread(update_blog, tuple())

app = Flask(__name__)

@app.route('/webhook', methods=['POST'])
def update():
    if request.method == 'POST':
        try:
            print request.headers
            print request.json
            tasks.put(1)
        except:
            print traceback.format_exc()

    return json.dumps({"msg": "error method"})


if __name__ == '__main__':
    app.run(host="0.0.0.0", port=8888, debug=False)
