#!/usr/bin/env python
# -*- coding: utf8 -*-
#
# exit-funding.py: compute financial support for torservers.net organizations
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

import sys

import yaml
import pickle
import os.path
import operator
from prettytable import PrettyTable
import subprocess
from tarfile import TarFile
import textwrap
import urllib2

try:
    import stem
except ImportError:
    sys.path = ['../stem'] + sys.path
    import stem

from stem.control import Controller
from stem.descriptor.reader import DescriptorReader

MAX_MONTHLY_FINANCIAL_SUPPORT = 500
TERM_WIDTH = 72
ARCHIVE_DIR = os.path.join(os.path.dirname(os.path.realpath(__file__)), 'archives')
PARTNERS_FILE = os.path.join(os.path.dirname(os.path.realpath(__file__)), 'partners.yaml')
COUNTRY_FACTORS_FILE = os.path.join(os.path.dirname(os.path.realpath(__file__)), 'country-factors.yaml')

BUF_SIZE = 2**15
def download_and_uncompress(url, dest):
    response = urllib2.urlopen(url)
    try:
        with open(dest, 'w') as archive:
            process = subprocess.Popen(['xz', '-dc'], stdin=subprocess.PIPE, stdout=archive, stderr=sys.stderr)
            buf = None
            bytes_read = 0
            while buf != '':
                buf = response.read(BUF_SIZE)
                bytes_read += len(buf)
                process.stdin.write(buf)
                print >>sys.stderr, "Download %s: %d bytes read…\r" % (url, bytes_read),
            process.stdin.close()
            retcode = process.poll()
            if retcode:
                raise ValueError("Invalid content at %s" % (url,))
    finally:
        response.close()
    print >>sys.stderr, ""

def download_metrics_archive(path):
    if not os.path.exists(os.path.dirname(path)):
        os.mkdir(os.path.dirname(path))
    url = 'https://collector.torproject.org/archive/relay-descriptors/%s.xz' % (os.path.relpath(path,ARCHIVE_DIR),)
    download_and_uncompress(url, path)

class Partner(object):
    def __init__(self, partner_info):
        self.name = partner_info['name']
        self.contacts = partner_info['contacts']
        self.relays = []
        self.total_bandwidth = None
        self.support = None
    def patch(self):
        self.total_bandwidth = None
        self.support = None

class Relay(object):
    def __init__(self, processor, relay_desc):
        self.nickname = relay_desc.nickname
        self.fingerprint = relay_desc.fingerprint
        self.country = processor.get_country(relay_desc.address)
        self.status_entries_seen = 0
        self.total_reported_bandwidth = 0
        self.support = None

    def patch(self):
        self.support = None

    def record_status_entry_bandwidth(self, status_entry):
        self.status_entries_seen += 1
        if not status_entry.exit_policy.is_exiting_allowed():
            print >>sys.stderr, " + skip %s on %s: not an exit" % (status_entry.fingerprint, status_entry.published)
            return
        if status_entry.is_unmeasured:
            print >>sys.stderr, " + skip %s on %s: unmeasured bandwidth" % (status_entry.fingerprint, status_entry.published)
            return
        print >>sys.stderr, " + record %s on %s" % (status_entry.fingerprint, status_entry.published)
        self.total_reported_bandwidth += status_entry.bandwidth

class VerboseDescriptorReader(object):
    def __init__(self, targets, *args, **kwargs):
        self._targets = targets
        self._entries_seen = 0
        self._reader = DescriptorReader(targets, *args, **kwargs)

    def __iter__(self):
        for d in self._reader:
            self._entries_seen += 1
            if self._entries_seen % 25 == 0:
                print >>sys.stderr, "%d documents parsed…\r" % (self._entries_seen,),
            yield d

    def __enter__(self):
        self._reader.start()
        return self

    def __exit__(self, exit_type, value, traceback):
        self._reader.stop()

class ExitFundingProcessor(object):
    def __init__(self, month, monthly_amount):
        self.month = month
        self.monthly_amount = monthly_amount
        self.country_factors = None
        # Stem Controller, used to perform GeoIP lookup against Tor database
        self.controller = Controller.from_port(port=9151)
        self.controller.authenticate()
        # Dictionary of partner_id → Partner object
        self.partners = None
        # Dictionary of contact string → Partner object
        self.contacts = None
        # Dictionary of relay fingerprint → Relay object
        self.relays = None

    def process_metrics(self):
        cached = self.load_cache()
        if not cached:
            self.load_partners()
            self.download_data()
            self.parse_metrics()
            self.save_cache()

    def load_partners(self):
        self.partners = {}
        self.contacts = {}
        for partner_id, info in yaml.safe_load(file(PARTNERS_FILE)).iteritems():
            partner = Partner(info)
            self.partners[partner_id] = partner
            for contact in partner.contacts:
                self.contacts[contact] = partner

    def download_data(self):
        for path in [self.descriptors_path, self.consensuses_path]:
            if not os.path.exists(path):
                download_metrics_archive(path)
            else:
                print >>sys.stderr, "%s already present. Skipping download." % (os.path.basename(path),)

    @property
    def descriptors_path(self):
        return os.path.join(ARCHIVE_DIR, 'server-descriptors', 'server-descriptors-%s.tar') % (self.month,)

    @property
    def consensuses_path(self):
        return os.path.join(ARCHIVE_DIR, 'consensuses', 'consensuses-%s.tar') % (self.month,)

    @property
    def cache_path(self):
        return os.path.join(ARCHIVE_DIR, 'exit-funding-%s.pickle') % (self.month,)

    def get_country(self, address):
        return self.controller.get_info('ip-to-country/%s' % address)

    def parse_descriptors(self):
        with VerboseDescriptorReader([self.descriptors_path]) as reader:
            for relay_desc in reader:
                if relay_desc.contact in self.contacts:
                    partner = self.contacts[relay_desc.contact]
                    if not relay_desc.fingerprint in self.relays:
                        relay = Relay(self, relay_desc)
                        self.relays[relay_desc.fingerprint] = relay
                        partner.relays.append(relay)

    def parse_consensuses(self,):
        with VerboseDescriptorReader([self.consensuses_path]) as reader:
            for status_entry in reader:
                if status_entry.fingerprint in self.relays:
                    self.relays[status_entry.fingerprint].record_status_entry_bandwidth(status_entry)

    def parse_metrics(self):
        self.relays = {}
        self.parse_descriptors()
        self.parse_consensuses()

    def load_country_factors(self):
        self.country_factors = yaml.safe_load(open(COUNTRY_FACTORS_FILE))

    def compute_total_bandwidths(self):
        grand_total = 0
        for partner in self.partners.itervalues():
            partner.patch()
            partner.total_bandwidth = 0
            for relay in partner.relays:
                relay.patch()
                partner.total_bandwidth += relay.total_reported_bandwidth
            grand_total += partner.total_bandwidth
        return grand_total

    def compute_supports(self):
        self.load_country_factors()
        total_partners_bandwidth = self.compute_total_bandwidths()
        for partner in self.partners.itervalues():
            partner.support = 0
            for relay in partner.relays:
                frac = relay.total_reported_bandwidth / float(total_partners_bandwidth)
                relay.support = self.monthly_amount * frac * self.country_factors[relay.country]
                partner.support += relay.support
            partner.support = min(partner.support, MAX_MONTHLY_FINANCIAL_SUPPORT)

    def print_results(self):
        partners = self.partners.values()
        partners.sort(key=operator.attrgetter('support'), reverse=True)
        for partner in partners:
            mark = "=" * ((TERM_WIDTH - len(partner.name) - 1) / 2)
            print "%s %s %s" % (mark, partner.name, mark)
            t = PrettyTable(['Relay', 'Exit bandwidth', 'Country', 'Financial support'])
            t.align['Exit bandwidth'] = 'r'
            t.align['Financial support'] = 'r'
            relays = list(partner.relays)
            relays.sort(key=operator.attrgetter('support'), reverse=True)
            for relay in relays:
                t.add_row([relay.nickname,
                           "%0.02f Mbit/s" % (relay.total_reported_bandwidth * 8 / 1000000.0,),
                           relay.country, "%0.02f €" % relay.support])
            print t
            print "Financial support: %0.02f €" % (partner.support,)
            print ""

    def load_cache(self):
        if not os.path.exists(self.cache_path):
            return False
        d = pickle.load(file(self.cache_path))
        self.partners = d['partners']
        self.contacts = d['contacts']
        self.relays = d['relays']
        return True

    def save_cache(self):
        with file(self.cache_path, 'w') as f:
            try:
                pickle.dump({'partners': self.partners,
                             'contacts': self.contacts,
                             'relays': self.relays}, f)
            except:
                try:
                    os.unlink(self.cache_path)
                except OSError:
                    pass # files has not been created, also good
                raise

def usage():
    print >>sys.stderr, "Usage: %s YYYY-MM MONTHLY_AMOUNT" % sys.argv[0]

def main():
    if len(sys.argv) < 3:
        usage()
        sys.exit(1)

    month = sys.argv[1]
    monthly_amount = int(sys.argv[2])
    processor = ExitFundingProcessor(month, monthly_amount)
    processor.process_metrics()
    processor.compute_supports()
    processor.print_results()

if __name__ == '__main__':
    main()
