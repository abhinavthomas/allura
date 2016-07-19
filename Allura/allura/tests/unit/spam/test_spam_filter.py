# -*- coding: utf-8 -*-

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

import mock
import unittest

from allura.lib.spam import SpamFilter


class MockFilter(SpamFilter):

    def check(*args, **kw):
        raise Exception("test exception")
        return True


class TestSpamFilter(unittest.TestCase):

    def test_check(self):
        # default no-op impl always returns False
        self.assertFalse(SpamFilter({}).check('foo'))

    def test_get_default(self):
        config = {}
        entry_points = None
        checker = SpamFilter.get(config, entry_points)
        self.assertTrue(isinstance(checker, SpamFilter))

    def test_get_method(self):
        config = {'spam.method': 'mock'}
        entry_points = {'mock': MockFilter}
        checker = SpamFilter.get(config, entry_points)
        self.assertTrue(isinstance(checker, MockFilter))

    @mock.patch('allura.lib.spam.log')
    def test_exceptionless_check(self, log):
        config = {'spam.method': 'mock'}
        entry_points = {'mock': MockFilter}
        checker = SpamFilter.get(config, entry_points)
        result = checker.check()
        self.assertFalse(result)
        self.assertTrue(log.exception.called)
