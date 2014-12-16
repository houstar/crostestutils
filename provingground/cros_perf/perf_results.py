#!/usr/bin/python
# Copyright 2014 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import argparse
import csv
from io import BytesIO
import json
import pycurl
from urllib import urlencode


_PERF_DASHBOARD_URL = 'https://chromeperf.appspot.com/graph_json'
_PERF_RESULT_FILE = 'mstone.csv'
_VALUE_ERROR = -1


def main():
    """Retrieves perf data from Chrome perf dashboard.

    Script to retrieve performance data from the Chrome perf dashboard. Test
    and bots configuration needs to be stored in a json file with expected
    format. Check perf.json for a sample config file. On a successful data
    retrieval, the results will be stored in mston.csv file which can be
    imported in Google Sheet.
    """
    usage_desc = ("""
         This script retrieves ChromeOS performance data from Chrome perf
         dashboard. Device and test configuration should be stored into a json
         file in the expected format.
         e.g.
         python perf_results.py -c perf.json -s 2171026063 -e 10360631002200
         Revision numbers can be captured from the perf dahsboard by hovering
         on perf data points.""")
    parser = argparse.ArgumentParser(description=usage_desc)
    parser.add_argument('-c', '--config', dest='perf_config_file',
                        help='Json file with device and test config.')
    parser.add_argument('-s', '--start_rev', dest='start_rev',
                        help='Start revision point from the dashboard.')
    parser.add_argument('-e', '--end_rev', dest='end_rev',
                        help='End revision point from the dashboard.')
    arguments = parser.parse_args()

    if not arguments.perf_config_file:
        parser.error('Config file is missing.')
    if not arguments.start_rev or not arguments.start_rev.isdigit():
        parser.error('Start revision is missing or not valid.')
    if not arguments.end_rev or not arguments.end_rev.isdigit():
        parser.error('End revision is missing or not valid.')

    try:
        with open(arguments.perf_config_file) as f:
            conf = json.loads(f.read())
    except IOError:
        print 'Config file is not found.'
        return

    start_rev = arguments.start_rev
    end_rev = arguments.end_rev

    bots = [conf['bots'][i]['device_name'] for i in range(len(conf['bots']))]
    tests = conf['tests']
    curl_request = init_curl()
    curl_buffer = BytesIO()

    result_file = open(_PERF_RESULT_FILE, 'w')
    try:
        writer = csv.writer(result_file)
        writer.writerow([' '] + bots)
        for test in tests:
            test_results = []
            test_results.append(test['test_name'])
            for bot in bots:
                postfields = construct_post_data(bot, test, start_rev, end_rev)
                mean = process_curl_query(curl_buffer, curl_request, postfields)
                if mean == _VALUE_ERROR:
                    test_results.append('ERR')
                else:
                    test_results.append(round(mean, 2))
            writer.writerow(test_results)
    finally:
        curl_request.close()
        result_file.close()


def init_curl():
    c = pycurl.Curl()
    c.setopt(pycurl.URL, _PERF_DASHBOARD_URL)
    return c


def process_curl_query(curl_buffer, curl_request, postfields):
    """Executes the curl request and generates mean for the test/bot."""
    curl_request.setopt(curl_request.POSTFIELDS, postfields)
    curl_request.setopt(curl_request.WRITEFUNCTION, curl_buffer.write)
    curl_request.perform()
    packet = curl_buffer.getvalue()
    curl_buffer.truncate(0)
    curl_buffer.seek(0)
    return packet_to_mean(packet)


def packet_to_mean(packet):
    """Extracts perf values and returns the mean."""
    try:
        values_set = json.loads(packet)['data']
    except ValueError:
        return _VALUE_ERROR

    if (len(values_set) == 0) or \
            (len(values_set[0]) == 0) or \
            (len(values_set[0]['data']) == 0):
        return _VALUE_ERROR
    values = values_set[0]['data']
    return sum([values[i][1] for i in range(len(values))]) / len(values)


def construct_post_data(bot, test, start_rev, end_rev):
    graphs = {
        "masters": [test['masters']],
        "bots": [bot],
        "tests": [test['test_name']],
        "start_rev": start_rev,
        "end_rev": end_rev,
    }
    post_data = {"graphs": json.dumps(graphs)}
    return urlencode(post_data)


if __name__ == "__main__":
    main()
