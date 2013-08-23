#!/usr/bin/env python
# -*- coding: utf-8 -*-
#
# exit-probability-factors.py
# ---------------------------
# Script for generating factors for multiplying monetary compensation of Tor
# Exit Node operators. 
#
# From JSON data taken from Compass, [0] it creates a multidimensional array
# of country codes and the probability of exiting from that country. Then, it
# generates a windorized standard deviation and a trimmed standard deviation
# of the probabilities within that array. Next, it takes the standard
# deviation of all combined exit-by-country probabilities, subtracts either
# the winsorized or trimmed standard deviation of all combined exit-by-country
# probabilities, adds the probability of for exiting in that country, takes
# the absolute value of this whole mess and computes the inverse squared: This
# gives us an incentivization factor for disbursal of funds to exit relay
# operators in countries with less exit relays. 

# Q: "Why all the maths?"
#
# A: "Without this, say for example if we just took the inverse of probability
# of exiting in each country, the distribution of incentivizaton factors would
# be severely skewed on each end of the spectrum. 
#
# Simple English Wikipedia Version: "Without the maths, the numbers on each
# end of the spectum are too extreme: operators in the USA and Germany would
# get pennies for running relays, and we would be highly incentivizing a
# ratrace to run Tor exit relays in places like Trinidad & Tobago and Jersey.
# (Who knew New Jersey get kicked out of the Union?! And, can we kick out
# states like Arkansas too?)
#
# Q: "Qu'est-ce que fuck do I do with this script?"
#
# A: "If you're normal, nothing. Otherwise, you run this script, and the
# factors and their country CCs are stored in
# ~/compass-incentive-factors.json. If you have €1000 to give to exit relay
# operators this month, you divide that €1000 by the number of operators
# you're donating to, let's say 42 operators:
#     €1000 / 42 = €23.81
# Then you take each operator and whatever country their exit relay is running
# in, find the factor for that relay, and multiply to get the ammount you
# should give them."
#
# BEWARE: LIKELY INSANELY BUG- AND BADSTATISTICS- INFESTED.
#
# [0]: https://gitweb.torproject.org/compass.git
#
# :authors: Isis <isis@torproject.org> 0xA3ADB67A2CDB8B35
# :license: Three-clause BSD
# :copyright: (c) 2013 Isis Agora Lovecruft, The Tor Project, Inc.

from __future__ import print_function

import numpy
import os
import os.path
import simplejson
import subprocess
import sys

try:
    COMPASS_DIR = os.environ['COMPASS_DIR']
except KeyError:
    COMPASS_DIR = '../compass'
COMPASS = os.path.join(COMPASS_DIR, 'compass.py')
sys.path = [COMPASS_DIR] + sys.path
import compass

compass_json = simplejson.loads(subprocess.check_output([COMPASS, '--json', '--top=-1', '--by-country']))

countries = [country for country in compass_json.items()[1][1]]
crange    = xrange(len(countries))

def get_field(field):
    """Get the JSON `field` for every country in the list."""
    return [countries[x].get(field) for x in crange]

def sort_by_column(array):
    """Sort a two-dimensional array by the values in the second column."""
    return array[array[:,1].argsort()]

def winsorized_std_deviation(sorted_array, min_percentile, max_percentile):
    """Calculate the winsorized standard deviation, given a one-dimensional
    pre-sorted array and the cutoff percentiles.

    :type sorted_array: A :class:`numpy.array` or something passably so.
    :param sorted_array: A one-dimensional N-array of floats, corresponding to
        probabilities of exiting from a given country, pre-sorted from lowest
        (first) to highest (last).
    :param float min_percentile: The minimum percentile (i.e. '0.05)' for
        the 5th percentile), for which all values below should be replaced
        with the first value in the array which is above the min_percentile.
    :param float min_percentile: The maximum percentile, ibidem.
    """
    numcc = float(len(sorted_array))
    print("Number of countries calculated for: %d" % numcc )
    low  = numpy.round(min_percentile * numcc)
    high = numpy.round((1. - max_percentile) * numcc)
    print("Winsorization discarding", int(low),
          "elements beneath minimum percentile", min_percentile, "...")
    print("Winsorization discarding", int(high),
          "elements above maximum percentile", max_percentile, "...")

    ## XXX ↓ not working
    # xmin = numpy.float(sorted_array.item( (low,) ))
    # xmax = numpy.float(sorted_array.item( (high,) ))
    # print("xmin =", xmin, "; xmax =", xmax)
    # new = []
    # for i in xrange(numcc):
    #     if (low <= sorted_array.item(i) < high):
    #         new.append(sorted_array.item(i))
    #     elif (low > sorted_array.item(i)):
    #         new.append(xmin)
    #     elif (high <= sorted_array.item(i)):
    #         new.append(xmax)
    # print("New array:", new)
    # print("Clipped:", numpy.asarray(sorted_array.clip(xmin, xmax)))
    ## XXX ↑ none of this works, we need to use dtype() and argsort():
    ## http://docs.scipy.org/doc/numpy/reference/generated/numpy.argsort.html#numpy.argsort

    return sorted_array[int(low):int(high)].std(ddof=0)

def trimmed(array, min_percent, max_percent):
    """Calculate the trimmed standard deviation."""
    tmp = numpy.asarray(array)
    return tmp[(min_percent <= tmp) & (tmp < max_percent)].std()

def incentive(array, weight_factor):
    """Calculate the incentivization factor, for encouraging Tor exit relay
    operators in countries with less exit relays to run more nodes.

    :param array: A two-dimensional 3xN array of country codes, exit
        probabilities, and factors.
    :param float weight_factor: Should be winsorized standard deviation of
        exit probabilities, or trimmed standard deviation of exit
        probabilities.
    """
    array_copy  = numpy.asarray(array[:,1], dtype=numpy.float)
    main_stddev = numpy.float(array_copy.std())

    incentivized = list()
    for ccname, pexit, _ in array[::]:
        ccname = numpy.string_(ccname)  ## oh, Python2.x, how i despise you…
        pexit  = numpy.float(pexit)

        weighted = main_stddev - weight_factor + pexit
        inverted = 1. / (abs(weighted)**2)
        shifted  = inverted * 10.
        factor   = shifted

        incentivized.append({'cc': ccname,
                             'p_exit': pexit,
                             'incentive_factor': factor})
    return incentivized


cc_list      = get_field('cc')
p_exit_list  = get_field('p_exit')
p_exit_array = numpy.asarray(p_exit_list)

cc_array = numpy.asarray(zip(cc_list, p_exit_list, [float(0) for x in crange]))
p_exit_i = numpy.asarray(zip(crange, p_exit_list))
## XXX probably don't need this next one ↓ after all, unless we want to resort by
## weight and country code the indexed arrays now.
cc_i     = numpy.asarray(zip(crange, cc_list))

sorted_p_exits      = numpy.asarray(sort_by_column(p_exit_i))
sorted_p_exits_col2 = numpy.asarray(sorted_p_exits[:,1])

winsorized_p_exits = winsorized_std_deviation(sorted_p_exits_col2, 0.10, 0.95)
print("Winsorized standard deviation: ", winsorized_p_exits)

## the trimmed standard deviation of exit probabilities by country:
trimmed_std = trimmed(sorted_p_exits_col2, 0.02, 6.50)
print("Trimmed standard deviation: ", trimmed_std)

incentivized = incentive(cc_array, trimmed_std)
for d in incentivized:
    print("%s: %f" % (d['cc'], d['incentive_factor']))
