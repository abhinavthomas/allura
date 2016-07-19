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

from tg import config
from mock import Mock
from nose.tools import assert_equal

from allura.config.app_cfg import ForgeConfig
from alluratest.controller import setup_config_test


def strip_space(s):
    return ''.join(s.split())


class TemplateTest(object):
    def setUp(self):
        setup_config_test()
        forge_config = ForgeConfig()
        forge_config.setup_jinja_renderer()
        self.jinja2_env = config['pylons.app_globals'].jinja2_env


class TestRelatedArtifacts(TemplateTest):

    def _render_related_artifacts(self, artifact):
        html = self.jinja2_env.from_string('''
            {% import 'allura:templates/jinja_master/lib.html' as lib with context %}
            {{ lib.related_artifacts(artifact) }}
        ''').render(artifact=artifact)
        return strip_space(html)

    def test_none(self):
        artifact = Mock(related_artifacts = lambda: [])
        assert_equal(self._render_related_artifacts(artifact), '')

    def test_simple(self):
        other = Mock()
        other.url.return_value = '/p/test/foo/bar'
        other.project.name = 'Test Project'
        other.app_config.options.mount_label = 'Foo'
        other.link_text.return_value = 'Bar'
        artifact = Mock(related_artifacts = lambda: [other])
        assert_equal(self._render_related_artifacts(artifact), strip_space('''
            <h4>Related</h4>
            <p>
            <a href="/p/test/foo/bar">Test Project: Foo: Bar</a><br>
            </p>
        '''))

    def test_non_artifact(self):
        # e.g. a commit
        class CommitThing(object):
            type_s = 'Commit'

            def link_text(self):
                return '[deadbeef]'

            def url(self):
                return '/p/test/code/ci/deadbeef'

        artifact = Mock(related_artifacts = lambda: [CommitThing()])
        assert_equal(self._render_related_artifacts(artifact), strip_space('''
            <h4>Related</h4>
            <p>
            <a href="/p/test/code/ci/deadbeef">Commit: [deadbeef]</a><br>
            </p>
        '''))
