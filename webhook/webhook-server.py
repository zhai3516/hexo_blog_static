#!/usr/bin/env python
# -*- coding: utf-8 -*-
import json

from flask import Flask, request

app = Flask(__name__)

@app.route('/webhook')
def update():
    if request.method == 'POST':
	print request.header
        print request.body


    return json.dumps({"msg":"error method"})


if __name__ == '__main__':
    app.run(host="0.0.0.0", port=8888, debug=False)
