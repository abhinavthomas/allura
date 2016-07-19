#       Licensed to the Apache Software Foundation (ASF) under one
#       or more contributor license agreements.  See the NOTICE file
#       distributed with this work for additional information
#       regarding copyright ownership.  The ASF licenses this file
#       to you under the Apache License, Version 2.0 (the
#       "License"); you may not use this file except in compliance
#       with the License.  You may obtain a copy of the License at
#
#         http://www.apache.org/licenses/LICENSE-2.0
#
#       Unless required by applicable law or agreed to in writing,
#       software distributed under the License is distributed on an
#       "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY
#       KIND, either express or implied.  See the License for the
#       specific language governing permissions and limitations
#       under the License.

from mock import patch

from datetime import datetime
from allura.lib import helpers


class TestAgo:

    def setUp(self):
        self.start_time = datetime(2010, 1, 1, 0, 0, 0)

    def test_that_empty_times_are_phrased_in_minutes(self):
        self.assertTimeSince('0 minutes ago', 2010, 1, 1, 0, 0, 0)

    def test_that_partial_minutes_are_rounded(self):
        self.assertTimeSince('less than 1 minute ago', 2010, 1, 1, 0, 0, 29)
        self.assertTimeSince('1 minute ago', 2010, 1, 1, 0, 0, 31)

    def test_that_minutes_are_rounded(self):
        self.assertTimeSince('1 minute ago', 2010, 1, 1, 0, 1, 29)
        self.assertTimeSince('2 minutes ago', 2010, 1, 1, 0, 1, 31)

    def test_that_hours_are_rounded(self):
        self.assertTimeSince('1 hour ago', 2010, 1, 1, 1, 29, 0)
        self.assertTimeSince('2 hours ago', 2010, 1, 1, 1, 31, 0)

    def test_that_days_are_rounded(self):
        self.assertTimeSince('1 day ago', 2010, 1, 2, 11, 0, 0)
        self.assertTimeSince('2 days ago', 2010, 1, 2, 13, 0, 0)

    def test_that_months_are_rounded(self):
        self.assertTimeSince('2010-01-01', 2010, 2, 8, 0, 0, 0)
        self.assertTimeSince('2010-01-01', 2010, 2, 9, 0, 0, 0)
        self.assertTimeSince('2010-01-01', 2010, 2, 20, 0, 0, 0)

    def test_that_years_are_rounded(self):
        self.assertTimeSince('2010-01-01', 2011, 6, 1, 0, 0, 0)
        self.assertTimeSince('2010-01-01', 2011, 8, 1, 0, 0, 0)

    def assertTimeSince(self, time_string, *time_components):
        assert time_string == self.time_since(*time_components)

    def time_since(self, *time_components):
        end_time = datetime(*time_components)
        with patch('allura.lib.helpers.datetime') as datetime_class:
            datetime_class.utcnow.return_value = end_time
            return helpers.ago(self.start_time)
