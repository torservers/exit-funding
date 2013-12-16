#!/usr/bin/env python
# -*- coding: utf8 -*-
#
# country-factors-helpers.py: compute country factors using exit probabilities
# Copyright © 2013 Lunar <lunar@torproject.org>
#
# Permission is hereby granted, free of charge, to any person obtaining
# a copy of this software and associated documentation files (the
# "Software"), to deal in the Software without restriction, including
# without limitation the rights to use, copy, modify, merge, publish,
# distribute, sublicense, and/or sell copies of the Software, and to
# permit persons to whom the Software is furnished to do so, subject to
# the following conditions:
#
# The above copyright notice and this permission notice shall be
# included in all copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND,
# EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF
# MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND
# NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT HOLDERS BE
# LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION
# OF CONTRACT, TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION
# WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE SOFTWARE.

import json
import math
import numpy
import os
import os.path
import subprocess
import sys

try:
    COMPASS_DIR = os.environ['COMPASS_DIR']
except KeyError:
    COMPASS_DIR = '../compass'
COMPASS = os.path.join(COMPASS_DIR, 'compass.py')
sys.path = [COMPASS_DIR] + sys.path
import compass

results = json.loads(subprocess.check_output([COMPASS, '--json', '--top=-1', '--by-country']))['results']
p_exits = {}
for line in results:
    p_exits[line['cc'].lower()] = line['p_exit'] / 100.0

factors = {}

values = numpy.array(p_exits.values())
mean = float(numpy.mean(values))
std_dev = float(numpy.std(values))

b = 1.3
k = 2

for country, p_exit in p_exits.iteritems():
    std_score = (p_exit - mean) / std_dev
    factors[country] = k * math.pow(b, -std_score)

for country, factor in factors.iteritems():
    print "%s: %f" % (country, factor)
