# -*- coding: utf-8 -*-
#
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

import os
import shutil
import stat
import unittest
import pkg_resources
import datetime

import mock
from pylons import tmpl_context as c, app_globals as g
import tg
from ming.base import Object
from ming.orm import ThreadLocalORMSession, session
from nose.tools import assert_equal, assert_in
from testfixtures import TempDirectory
from datadiff.tools import assert_equals

from alluratest.controller import setup_basic_test, setup_global_objects
from allura.lib import helpers as h
from allura.tasks.repo_tasks import tarball
from allura.tests import decorators as td
from allura.tests.model.test_repo import RepoImplTestBase
from allura import model as M
from allura.model.repo_refresh import send_notifications
from allura.webhooks import RepoPushWebhookSender
from forgegit import model as GM
from forgegit.tests import with_git
from forgewiki import model as WM


class TestNewGit(unittest.TestCase):

    def setUp(self):
        setup_basic_test()
        self.setup_with_tools()

    @with_git
    @td.with_wiki
    def setup_with_tools(self):
        setup_global_objects()
        h.set_context('test', 'src-git', neighborhood='Projects')
        repo_dir = pkg_resources.resource_filename(
            'forgegit', 'tests/data')
        c.app.repo.fs_path = repo_dir
        c.app.repo.name = 'testgit.git'
        self.repo = c.app.repo
        self.repo.refresh()
        self.rev = self.repo.commit('master')
        ThreadLocalORMSession.flush_all()
        ThreadLocalORMSession.close_all()

    def test_commit(self):
        assert self.rev.primary() is self.rev
        assert self.rev.index_id().startswith('allura/model/repo/Commit#')
        self.rev.author_url
        self.rev.committer_url
        assert self.rev.tree._id == self.rev.tree_id
        assert self.rev.summary == self.rev.message.splitlines()[0]
        assert self.rev.shorthand_id() == '[1e146e]'
        assert self.rev.symbolic_ids == (
            ['master'], ['foo']), self.rev.symbolic_ids
        assert self.rev.url() == (
            '/p/test/src-git/ci/'
            '1e146e67985dcd71c74de79613719bef7bddca4a/')
        all_cis = list(self.repo.log(self.rev._id, id_only=True))
        assert len(all_cis) == 4
        c.lcid_cache = {}
        self.rev.tree.ls()
        # print self.rev.tree.readme()
        assert_equal(self.rev.tree.readme(), (
            'README', 'This is readme\nAnother Line\n'))
        assert self.rev.tree.path() == '/'
        assert self.rev.tree.url() == (
            '/p/test/src-git/ci/'
            '1e146e67985dcd71c74de79613719bef7bddca4a/'
            'tree/')
        self.rev.tree.by_name['README']
        assert self.rev.tree.is_blob('README') == True
        ThreadLocalORMSession.close_all()
        c.app = None
        converted = g.markdown.convert('[1e146e]')
        assert '1e146e' in converted, converted
        h.set_context('test', 'wiki', neighborhood='Projects')
        pg = WM.Page(
            title='Test Page', text='This is a commit reference: [1e146e]')
        ThreadLocalORMSession.flush_all()
        M.MonQTask.run_ready()
        for ci in pg.related_artifacts():
            assert ci.shorthand_id() == '[1e146e]', ci.shorthand_id()
            assert ci.url() == (
                '/p/test/src-git/ci/'
                '1e146e67985dcd71c74de79613719bef7bddca4a/')

        assert_equal(self.rev.authored_user, None)
        assert_equal(self.rev.committed_user, None)
        user = M.User.upsert('rick')
        email = user.claim_address('rcopeland@geek.net')
        email.confirmed = True
        session(email).flush(email)
        rev = self.repo.commit(self.rev._id)  # to update cached values of LazyProperty
        assert_equal(rev.authored_user, user)
        assert_equal(rev.committed_user, user)
        assert_equal(
            sorted(rev.webhook_info.keys()),
            sorted(['id', 'url', 'timestamp', 'message', 'author',
                    'committer', 'added', 'removed', 'renamed', 'modified', 'copied']))


class TestGitRepo(unittest.TestCase, RepoImplTestBase):

    def setUp(self):
        setup_basic_test()
        self.setup_with_tools()

    @with_git
    def setup_with_tools(self):
        setup_global_objects()
        h.set_context('test', 'src-git', neighborhood='Projects')
        repo_dir = pkg_resources.resource_filename(
            'forgegit', 'tests/data')
        c.app.repo.fs_path = repo_dir
        c.app.repo.name = 'testgit.git'
        self.repo = c.app.repo
        self.repo.refresh()
        ThreadLocalORMSession.flush_all()
        ThreadLocalORMSession.close_all()

    @property
    def merge_request(self):
        cid = '5c47243c8e424136fd5cdd18cd94d34c66d1955c'
        return M.MergeRequest(
            downstream={'commit_id': cid},
            source_branch='zz',
            target_branch='master')

    def test_init(self):
        repo = GM.Repository(
            name='testgit.git',
            fs_path=g.tmpdir + '/',
            url_path='/test/',
            tool='git',
            status='creating')
        dirname = os.path.join(repo.fs_path, repo.name)
        if os.path.exists(dirname):
            shutil.rmtree(dirname)
        repo.init()
        shutil.rmtree(dirname)

    def test_fork(self):
        repo = GM.Repository(
            name='testgit.git',
            fs_path=g.tmpdir + '/',
            url_path='/test/',
            tool='git',
            status='creating')
        repo_path = pkg_resources.resource_filename(
            'forgegit', 'tests/data/testgit.git')
        dirname = os.path.join(repo.fs_path, repo.name)
        if os.path.exists(dirname):
            shutil.rmtree(dirname)
        repo.init()
        repo._impl.clone_from(repo_path)
        assert not os.path.exists(
            os.path.join(g.tmpdir, 'testgit.git/hooks/update'))
        assert not os.path.exists(
            os.path.join(g.tmpdir, 'testgit.git/hooks/post-receive-user'))
        assert os.path.exists(
            os.path.join(g.tmpdir, 'testgit.git/hooks/post-receive'))
        assert os.stat(
            os.path.join(g.tmpdir, 'testgit.git/hooks/post-receive'))[0] & stat.S_IXUSR

    def test_clone(self):
        repo = GM.Repository(
            name='testgit.git',
            fs_path=g.tmpdir + '/',
            url_path='/test/',
            tool='git',
            status='creating')
        repo_path = pkg_resources.resource_filename(
            'forgegit', 'tests/data/testgit.git')
        dirname = os.path.join(repo.fs_path, repo.name)
        if os.path.exists(dirname):
            shutil.rmtree(dirname)
        repo.init()
        repo._impl.clone_from(repo_path)
        assert len(list(repo.log()))
        assert not os.path.exists(
            os.path.join(g.tmpdir, 'testgit.git/hooks/update'))
        assert not os.path.exists(
            os.path.join(g.tmpdir, 'testgit.git/hooks/post-receive-user'))
        assert os.path.exists(
            os.path.join(g.tmpdir, 'testgit.git/hooks/post-receive'))
        assert os.stat(
            os.path.join(g.tmpdir, 'testgit.git/hooks/post-receive'))[0] & stat.S_IXUSR
        with open(os.path.join(g.tmpdir, 'testgit.git/hooks/post-receive')) as f:
            c = f.read()
        self.assertIn(
            'curl -s http://localhost:8080/auth/refresh_repo/p/test/src-git/\n', c)
        self.assertIn('exec $DIR/post-receive-user\n', c)
        shutil.rmtree(dirname)

    @mock.patch('forgegit.model.git_repo.git.Repo.clone_from')
    def test_hotcopy(self, clone_from):
        with h.push_config(tg.config, **{'scm.git.hotcopy': 'True'}):
            repo = GM.Repository(
                name='testgit.git',
                fs_path=g.tmpdir + '/',
                url_path='/test/',
                tool='git',
                status='creating')
            repo.app.config.options['hotcopy'] = True
            repo_path = pkg_resources.resource_filename(
                'forgegit', 'tests/data/testgit.git')
            dirname = os.path.join(repo.fs_path, repo.name)
            if os.path.exists(dirname):
                shutil.rmtree(dirname)
            repo.init()
            repo._impl.clone_from(repo_path)
            assert not clone_from.called
            assert len(list(repo.log()))
            assert os.path.exists(
                os.path.join(g.tmpdir, 'testgit.git/hooks/update'))
            assert os.path.exists(
                os.path.join(g.tmpdir, 'testgit.git/hooks/post-receive-user'))
            assert os.path.exists(
                os.path.join(g.tmpdir, 'testgit.git/hooks/post-receive'))
            assert os.stat(
                os.path.join(g.tmpdir, 'testgit.git/hooks/post-receive'))[0] & stat.S_IXUSR
            with open(os.path.join(g.tmpdir, 'testgit.git/hooks/post-receive')) as f:
                c = f.read()
            self.assertIn(
                'curl -s http://localhost:8080/auth/refresh_repo/p/test/src-git/\n', c)
            self.assertIn('exec $DIR/post-receive-user\n', c)
            shutil.rmtree(dirname)

    def test_index(self):
        i = self.repo.index()
        assert i['type_s'] == 'Git Repository', i

    def test_log_id_only(self):
        entries = list(self.repo.log(id_only=True))
        assert_equal(entries, [
            '1e146e67985dcd71c74de79613719bef7bddca4a',
            'df30427c488aeab84b2352bdf88a3b19223f9d7a',
            '6a45885ae7347f1cac5103b0050cc1be6a1496c8',
            '9a7df788cf800241e3bb5a849c8870f2f8259d98'])

    def test_log(self):
        entries = list(self.repo.log(id_only=False))
        assert_equal(entries, [
            {'authored': {'date': datetime.datetime(2010, 10, 7, 18, 44, 11),
                          'email': u'rcopeland@geek.net',
                          'name': u'Rick Copeland'},
             'committed': {'date': datetime.datetime(2010, 10, 7, 18, 44, 11),
                           'email': u'rcopeland@geek.net',
                           'name': u'Rick Copeland'},
             'id': '1e146e67985dcd71c74de79613719bef7bddca4a',
             'message': u'Change README\n',
             'parents': ['df30427c488aeab84b2352bdf88a3b19223f9d7a'],
             'refs': ['HEAD', 'foo', 'master'],
             'size': None,
             'rename_details': {}},
            {'authored': {'date': datetime.datetime(2010, 10, 7, 18, 44, 1),
                          'email': u'rcopeland@geek.net',
                          'name': u'Rick Copeland'},
             'committed': {'date': datetime.datetime(2010, 10, 7, 18, 44, 1),
                           'email': u'rcopeland@geek.net',
                           'name': u'Rick Copeland'},
             'id': 'df30427c488aeab84b2352bdf88a3b19223f9d7a',
             'message': u'Add README\n',
             'parents': ['6a45885ae7347f1cac5103b0050cc1be6a1496c8'],
             'refs': [],
             'size': None,
             'rename_details': {}},
            {'authored': {'date': datetime.datetime(2010, 10, 7, 18, 43, 26),
                          'email': u'rcopeland@geek.net',
                          'name': u'Rick Copeland'},
             'committed': {'date': datetime.datetime(2010, 10, 7, 18, 43, 26),
                           'email': u'rcopeland@geek.net',
                           'name': u'Rick Copeland'},
             'id': '6a45885ae7347f1cac5103b0050cc1be6a1496c8',
             'message': u'Remove file\n',
             'parents': ['9a7df788cf800241e3bb5a849c8870f2f8259d98'],
             'refs': [],
             'size': None,
             'rename_details': {}},
            {'authored': {'date': datetime.datetime(2010, 10, 7, 18, 42, 54),
                          'email': u'rcopeland@geek.net',
                          'name': u'Rick Copeland'},
             'committed': {'date': datetime.datetime(2010, 10, 7, 18, 42, 54),
                           'email': u'rcopeland@geek.net',
                           'name': u'Rick Copeland'},
             'id': '9a7df788cf800241e3bb5a849c8870f2f8259d98',
             'message': u'Initial commit\n',
             'parents': [],
             'refs': [],
             'size': None,
             'rename_details': {}},
        ])

    def test_log_unicode(self):
        entries = list(self.repo.log(path=u'völundr', id_only=False))
        assert_equal(entries, [])

    def test_log_file(self):
        entries = list(self.repo.log(path='README', id_only=False))
        assert_equal(entries, [
            {'authored': {'date': datetime.datetime(2010, 10, 7, 18, 44, 11),
                          'email': u'rcopeland@geek.net',
                          'name': u'Rick Copeland'},
             'committed': {'date': datetime.datetime(2010, 10, 7, 18, 44, 11),
                           'email': u'rcopeland@geek.net',
                           'name': u'Rick Copeland'},
             'id': '1e146e67985dcd71c74de79613719bef7bddca4a',
             'message': u'Change README\n',
             'parents': ['df30427c488aeab84b2352bdf88a3b19223f9d7a'],
             'refs': ['HEAD', 'foo', 'master'],
             'size': 28,
             'rename_details': {}},
            {'authored': {'date': datetime.datetime(2010, 10, 7, 18, 44, 1),
                          'email': u'rcopeland@geek.net',
                          'name': u'Rick Copeland'},
             'committed': {'date': datetime.datetime(2010, 10, 7, 18, 44, 1),
                           'email': u'rcopeland@geek.net',
                           'name': u'Rick Copeland'},
             'id': 'df30427c488aeab84b2352bdf88a3b19223f9d7a',
             'message': u'Add README\n',
             'parents': ['6a45885ae7347f1cac5103b0050cc1be6a1496c8'],
             'refs': [],
             'size': 15,
             'rename_details': {}},
        ])

    def test_commit(self):
        entry = self.repo.commit('HEAD')
        assert str(entry.authored.name) == 'Rick Copeland', entry.authored
        assert entry.message
        # test the auto-gen tree fall-through
        orig_tree = M.repository.Tree.query.get(_id=entry.tree_id)
        assert orig_tree
        # force it to regenerate the tree
        M.repository.Tree.query.remove(dict(_id=entry.tree_id))
        session(orig_tree).flush()
        # ensure we don't just pull it from the session cache
        session(orig_tree).expunge(orig_tree)
        # ensure we don't just use the LazyProperty copy
        session(entry).expunge(entry)
        entry = self.repo.commit(entry._id)
        # regenerate the tree
        new_tree = entry.tree
        assert new_tree
        self.assertEqual(new_tree._id, orig_tree._id)
        self.assertEqual(new_tree.tree_ids, orig_tree.tree_ids)
        self.assertEqual(new_tree.blob_ids, orig_tree.blob_ids)
        self.assertEqual(new_tree.other_ids, orig_tree.other_ids)

    def test_notification_email(self):
        send_notifications(
            self.repo, ['1e146e67985dcd71c74de79613719bef7bddca4a', ])
        ThreadLocalORMSession.flush_all()

        n = M.Notification.query.find({'subject': u'[test:src-git] New commit by Rick Copeland'}).first()
        assert n
        assert_in('Change README', n.text)
        send_notifications(
            self.repo, ['1e146e67985dcd71c74de79613719bef7bddca4a', 'df30427c488aeab84b2352bdf88a3b19223f9d7a'])
        ThreadLocalORMSession.flush_all()
        assert M.Notification.query.find(
            dict(subject=u'[test:src-git] 2 new commits to Git')).first()

    def test_tarball(self):
        tmpdir = tg.config['scm.repos.tarball.root']
        if os.path.isfile(os.path.join(tmpdir, "git/t/te/test/testgit.git/test-src-git-HEAD.zip")):
            os.remove(
                os.path.join(tmpdir, "git/t/te/test/testgit.git/test-src-git-HEAD.zip"))
        assert_equal(self.repo.tarball_path,
                     os.path.join(tmpdir, 'git/t/te/test/testgit.git'))
        assert_equal(self.repo.tarball_url('HEAD'),
                     'file:///git/t/te/test/testgit.git/test-src-git-HEAD.zip')
        self.repo.tarball('HEAD')
        assert os.path.isfile(
            os.path.join(tmpdir, "git/t/te/test/testgit.git/test-src-git-HEAD.zip"))

    def test_all_commit_ids(self):
        cids = list(self.repo.all_commit_ids())
        heads = [
            '1e146e67985dcd71c74de79613719bef7bddca4a',  # master
            '5c47243c8e424136fd5cdd18cd94d34c66d1955c',  # zz
        ]
        self.assertIn(cids[0], heads)  # repo head comes first
        for head in heads:
            self.assertIn(head, cids)  # all branches included
        # repo root comes last
        self.assertEqual(cids[-1], '9a7df788cf800241e3bb5a849c8870f2f8259d98')

    def test_ls(self):
        c.lcid_cache = {}  # else it'll be a mock
        lcd_map = self.repo.commit('HEAD').tree.ls()
        self.assertEqual(lcd_map, [{
            'href': u'README',
            'kind': 'BLOB',
            'last_commit': {
                    'author': u'Rick Copeland',
                'author_email': u'rcopeland@geek.net',
                'author_url': None,
                'date': datetime.datetime(2010, 10, 7, 18, 44, 11),
                'href': u'/p/test/src-git/ci/1e146e67985dcd71c74de79613719bef7bddca4a/',
                'shortlink': u'[1e146e]',
                'summary': u'Change README'},
            'name': u'README'}])

    def test_tarball_status(self):
        tmpdir = tg.config['scm.repos.tarball.root']
        if os.path.isfile(os.path.join(tmpdir, "git/t/te/test/testgit.git/test-src-git-HEAD.zip")):
            os.remove(
                os.path.join(tmpdir, "git/t/te/test/testgit.git/test-src-git-HEAD.zip"))
        if os.path.isfile(os.path.join(tmpdir, "git/t/te/test/testgit.git/test-src-git-HEAD.tmp")):
            os.remove(
                os.path.join(tmpdir, "git/t/te/test/testgit.git/test-src-git-HEAD.tmp"))
        if os.path.isdir(os.path.join(tmpdir, "git/t/te/test/testgit.git/test-src-git-HEAD/")):
            os.removedirs(
                os.path.join(tmpdir, "git/t/te/test/testgit.git/test-src-git-HEAD/"))
        self.repo.tarball('HEAD')
        assert_equal(self.repo.get_tarball_status('HEAD'), 'complete')

        os.remove(
            os.path.join(tmpdir, "git/t/te/test/testgit.git/test-src-git-HEAD.zip"))
        assert_equal(self.repo.get_tarball_status('HEAD'), None)

    def test_tarball_status_task(self):
        assert_equal(self.repo.get_tarball_status('HEAD'), None)

        # create tarball task in MonQTask and check get_tarball_status
        tarball.post('HEAD', '')

        # task created
        assert_equal(self.repo.get_tarball_status('HEAD'), 'ready')

        task = M.MonQTask.query.get(**{
            'task_name': 'allura.tasks.repo_tasks.tarball',
            'args': ['HEAD', ''],
            'state': {'$in': ['busy', 'ready']},
        })

        # task is running
        task.state = 'busy'
        task.query.session.flush_all()
        assert_equal(self.repo.get_tarball_status('HEAD'), 'busy')

        # when state is complete, but file don't exists, then status is None
        task.state = 'complete'
        task.query.session.flush_all()
        assert_equal(self.repo.get_tarball_status('HEAD'), None)

    def test_is_empty(self):
        assert not self.repo.is_empty()
        with TempDirectory() as d:
            repo2 = GM.Repository(
                name='test',
                fs_path=d.path,
                url_path='/test/',
                tool='git',
                status='creating')
            repo2.init()
            assert repo2.is_empty()
            repo2.refresh()
            ThreadLocalORMSession.flush_all()
            assert repo2.is_empty()

    def test_default_branch_set(self):
        self.repo.default_branch_name = 'zz'
        assert_equal(self.repo.get_default_branch('master'), 'zz')

    def test_default_branch_non_standard_unset(self):
        with mock.patch.object(self.repo, 'get_branches') as gb,\
             mock.patch.object(self.repo, 'set_default_branch') as set_db:
            gb.return_value = [Object(name='foo')]
            assert_equal(self.repo.get_default_branch('master'), 'foo')
            set_db.assert_called_once_with('foo')

    def test_default_branch_non_standard_invalid(self):
        with mock.patch.object(self.repo, 'get_branches') as gb,\
             mock.patch.object(self.repo, 'set_default_branch') as set_db:
            self.repo.default_branch_name = 'zz'
            gb.return_value = [Object(name='foo')]
            assert_equal(self.repo.get_default_branch('master'), 'foo')
            set_db.assert_called_once_with('foo')

    def test_default_branch_invalid(self):
        with mock.patch.object(self.repo, 'get_branches') as gb,\
             mock.patch.object(self.repo, 'set_default_branch') as set_db:
            self.repo.default_branch_name = 'zz'
            gb.return_value = [Object(name='foo'), Object(name='master')]
            assert_equal(self.repo.get_default_branch('master'), 'master')
            set_db.assert_called_once_with('master')

    def test_default_branch_no_clobber(self):
        with mock.patch.object(self.repo, 'get_branches') as gb:
            gb.return_value = []
            self.repo.default_branch_name = 'zz'
            assert_equal(self.repo.get_default_branch('master'), 'zz')

    def test_default_branch_clobber_none(self):
        with mock.patch.object(self.repo, 'get_branches') as gb:
            gb.return_value = []
            self.repo.default_branch_name = None
            assert_equal(self.repo.get_default_branch('master'), 'master')

    def test_clone_url(self):
        assert_equal(
            self.repo.clone_url('rw', 'nobody'),
            'ssh://nobody@localhost:8022/scm-repo/p/test/testgit')
        assert_equal(
            self.repo.clone_url('https', 'nobody'),
            'https://nobody@localhost:8022/scm-repo/p/test/testgit')
        with h.push_config(self.repo.app.config.options, external_checkout_url='https://$username@foo.com/'):
            assert_equal(
                self.repo.clone_url('https', 'user'),
                'https://user@foo.com/')

    def test_webhook_payload(self):
        user = M.User.upsert('cory')
        email = user.claim_address('cjohns@slashdotmedia.com')
        email.confirmed = True
        session(email).flush(email)
        user = M.User.upsert('rick')
        email = user.claim_address('rcopeland@geek.net')
        email.confirmed = True
        session(email).flush(email)

        sender = RepoPushWebhookSender()
        cids = list(self.repo.all_commit_ids())[:2]
        payload = sender.get_payload(commit_ids=cids, ref='refs/heads/zz')
        expected_payload = {
            'size': 2,
            'ref': u'refs/heads/zz',
            'after': u'5c47243c8e424136fd5cdd18cd94d34c66d1955c',
            'before': u'df30427c488aeab84b2352bdf88a3b19223f9d7a',
            'commits': [{
                'id': u'5c47243c8e424136fd5cdd18cd94d34c66d1955c',
                'url': u'http://localhost/p/test/src-git/ci/5c47243c8e424136fd5cdd18cd94d34c66d1955c/',
                'timestamp': datetime.datetime(2013, 3, 28, 18, 54, 16),
                'message': u'Not repo root',
                'author': {'name': u'Cory Johns',
                           'email': u'cjohns@slashdotmedia.com',
                           'username': 'cory'},
                'committer': {'name': u'Cory Johns',
                              'email': u'cjohns@slashdotmedia.com',
                              'username': 'cory'},
                'added': [u'bad'],
                'removed': [],
                'modified': [],
                'copied': [],
                'renamed': [],
            }, {
                'id': u'1e146e67985dcd71c74de79613719bef7bddca4a',
                'url': u'http://localhost/p/test/src-git/ci/1e146e67985dcd71c74de79613719bef7bddca4a/',
                'timestamp': datetime.datetime(2010, 10, 7, 18, 44, 11),
                'message': u'Change README',
                'author': {'name': u'Rick Copeland',
                           'email': u'rcopeland@geek.net',
                           'username': 'rick'},
                'committer': {'name': u'Rick Copeland',
                              'email': u'rcopeland@geek.net',
                              'username': 'rick'},
                'added': [],
                'removed': [],
                'modified': [u'README'],
                'copied': [],
                'renamed': [],
            }],
            'repository': {
                'name': u'Git',
                'full_name': u'/p/test/src-git/',
                'url': u'http://localhost/p/test/src-git/',
            },
        }
        assert_equals(payload, expected_payload)

    def test_can_merge(self):
        mr = mock.Mock(downstream_repo=Object(full_fs_path='downstream-url'),
                       source_branch='source-branch',
                       target_branch='target-branch',
                       downstream=mock.Mock(commit_id='cid'))
        git = mock.Mock()
        git.merge_tree.return_value = 'clean merge'
        self.repo._impl._git.git = git
        assert_equal(self.repo.can_merge(mr), True)
        git.fetch.assert_called_once_with('downstream-url', 'source-branch')
        git.merge_base.assert_called_once_with('cid', 'target-branch')
        git.merge_tree.assert_called_once_with(
            git.merge_base.return_value,
            'target-branch',
            'cid')
        git.merge_tree.return_value = '+<<<<<<<'
        assert_equal(self.repo.can_merge(mr), False)

    @mock.patch('forgegit.model.git_repo.tempfile', autospec=True)
    @mock.patch('forgegit.model.git_repo.git', autospec=True)
    @mock.patch('forgegit.model.git_repo.GitImplementation', autospec=True)
    @mock.patch('forgegit.model.git_repo.shutil', autospec=True)
    def test_merge(self, shutil, GitImplementation, git, tempfile):
        mr = mock.Mock(downstream_repo=mock.Mock(
                           full_fs_path='downstream-url',
                           url=lambda: 'downstream-repo-url'),
                       source_branch='source-branch',
                       target_branch='target-branch',
                       url=lambda: '/merge-request/1/',
                       downstream=mock.Mock(commit_id='cid'))
        _git = mock.Mock()
        self.repo._impl._git.git = _git
        self.repo.merge(mr)
        git.Repo.clone_from.assert_called_once_with(
            self.repo.full_fs_path,
            to_path=tempfile.mkdtemp.return_value,
            bare=False,
            shared=True)
        tmp_repo = GitImplementation.return_value._git
        assert_equal(
            tmp_repo.git.fetch.call_args_list,
            [mock.call('origin', 'target-branch'),
             mock.call('downstream-url', 'source-branch')])
        tmp_repo.git.checkout.assert_called_once_with('target-branch')
        assert_equal(
            tmp_repo.git.config.call_args_list,
            [mock.call('user.name', 'Test Admin'),
             mock.call('user.email', 'allura@localhost')])
        msg = u'Merge downstream-repo-url branch source-branch into target-branch'
        msg += u'\n\nhttp://localhost/merge-request/1/'
        tmp_repo.git.merge.assert_called_once_with('cid', '-m', msg)
        tmp_repo.git.push.assert_called_once_with('origin', 'target-branch')
        shutil.rmtree.assert_called_once_with(
            tempfile.mkdtemp.return_value,
            ignore_errors=True)

    @mock.patch('forgegit.model.git_repo.tempfile')
    @mock.patch('forgegit.model.git_repo.shutil')
    @mock.patch('forgegit.model.git_repo.git')
    def test_merge_raise_exception(self, git, shutil, tempfile):
        self.repo._impl._git.git = mock.Mock()
        git.Repo.clone_from.side_effect = Exception
        with self.assertRaises(Exception):
            self.repo.merge(mock.Mock())
        shutil.rmtree.assert_has_calles()

    @mock.patch.dict('allura.lib.app_globals.config',  {'scm.commit.git.detect_copies': 'false'})
    @td.with_tool('test', 'Git', 'src-weird', 'Git', type='git')
    def test_paged_diffs(self):
        # setup
        h.set_context('test', 'src-weird', neighborhood='Projects')
        repo_dir = pkg_resources.resource_filename(
            'forgegit', 'tests/data')
        repo = GM.Repository(
            name='weird-chars.git',
            fs_path=repo_dir,
            url_path='/src-weird/',
            tool='git',
            status='creating')
        repo.refresh()
        ThreadLocalORMSession.flush_all()
        ThreadLocalORMSession.close_all()

        # spaces and unicode filenames
        diffs = repo.paged_diffs('407950e8fba4dbc108ffbce0128ed1085c52cfd7')
        expected = {
            'removed': [],
            'changed': [],
            'renamed': [],
            'added': [u'with space.txt', u'привіт.txt'],
            'copied': [],
            'total': 2,
        }
        assert_equals(diffs, expected)

        diffs = repo.paged_diffs('f3de6a0e7601cdde326054a1cc708afdc1dbe70b')
        expected = {
            'added': [],
            'removed': [],
            'copied': [],
            'renamed': [],
            'changed': [u'привіт.txt'],
            'total': 1,
        }
        assert_equals(diffs, expected)

        # initial commit is special, but must work too
        diffs = repo.paged_diffs('afaa6d93eb5661fb04f8e10e9ba1039b7441a6c7')
        expected = {
            'added': [u'README.md'],
            'removed': [],
            'changed': [],
            'copied': [],
            'renamed': [],
            'total': 1,
        }
        assert_equals(diffs, expected)

        # pagination
        diffs = repo.paged_diffs('407950e8fba4dbc108ffbce0128ed1085c52cfd7', start=0, end=1)
        expected = {
            'added': [u'with space.txt'],
            'removed': [],
            'copied': [],
            'renamed': [],
            'changed': [],
            'total': 2,
        }
        assert_equals(diffs, expected)
        diffs = repo.paged_diffs('407950e8fba4dbc108ffbce0128ed1085c52cfd7', start=1, end=2)
        expected = {
            'added': [u'привіт.txt'],
            'removed': [],
            'copied': [],
            'renamed': [],
            'changed': [],
            'total': 2,
        }
        assert_equals(diffs, expected)
        diffs = repo.paged_diffs('346c52c1dddc729e2c2711f809336401f0ff925e')  # Test copy
        expected = {
            'added': [u'README.copy'],
            'removed': [],
            'copied': [],
            'renamed': [],
            'changed': [u'README'],
            'total': 2,
        }
        assert_equals(diffs, expected)
        diffs = repo.paged_diffs('3cb2bbcd7997f89060a14fe8b1a363f01883087f')  # Test rename
        expected = {
            'added': [u'README'],
            'removed': [u'README-copy.md'],
            'copied': [],
            'renamed': [],
            'changed': [],
            'total': 2,
        }
        assert_equals(diffs, expected)

    @mock.patch.dict('allura.lib.app_globals.config',  {'scm.commit.git.detect_copies': 'true'})
    @td.with_tool('test', 'Git', 'src-weird', 'Git', type='git')
    def test_paged_diffs_with_detect_copies(self):
        # setup
        h.set_context('test', 'src-weird', neighborhood='Projects')
        repo_dir = pkg_resources.resource_filename(
            'forgegit', 'tests/data')
        repo = GM.Repository(
            name='weird-chars.git',
            fs_path=repo_dir,
            url_path='/src-weird/',
            tool='git',
            status='creating')
        repo.refresh()
        ThreadLocalORMSession.flush_all()
        ThreadLocalORMSession.close_all()

        diffs = repo.paged_diffs('346c52c1dddc729e2c2711f809336401f0ff925e')  # Test copy
        expected = {
            'added': [],
            'removed': [],
            'copied': [{'new': u'README.copy', 'old': u'README', 'ratio': 1.0}],
            'renamed': [],
            'changed': [u'README'],
            'total': 2,
        }
        assert_equals(diffs, expected)
        diffs = repo.paged_diffs('3cb2bbcd7997f89060a14fe8b1a363f01883087f')  # Test rename
        expected = {
            'added': [],
            'removed': [],
            'copied': [],
            'renamed': [{'new': u'README', 'old': u'README-copy.md', 'ratio': 1.0}],
            'changed': [],
            'total': 1,
        }
        assert_equals(diffs, expected)

    def test_merge_base(self):
        res = self.repo._impl.merge_base(self.merge_request)
        assert_equal(res, '1e146e67985dcd71c74de79613719bef7bddca4a')

    def test_merge_request_commits(self):
        res = self.repo.merge_request_commits(self.merge_request)
        expected = [
            {'authored': {
                'date': datetime.datetime(2013, 3, 28, 18, 54, 16),
                'email': u'cjohns@slashdotmedia.com',
                'name': u'Cory Johns'},
             'committed': {
                 'date': datetime.datetime(2013, 3, 28, 18, 54, 16),
                 'email': u'cjohns@slashdotmedia.com',
                 'name': u'Cory Johns'},
             'id': '5c47243c8e424136fd5cdd18cd94d34c66d1955c',
             'message': u'Not repo root\n',
             'parents': ['1e146e67985dcd71c74de79613719bef7bddca4a'],
             'refs': ['zz'],
             'rename_details': {},
             'size': None}]
        assert_equals(res, expected)

    def test_merge_request_commits_tmp_dir(self):
        """
        repo.merge_request_commits should return the same result with and
        without scm.merge_list.git.use_tmp_dir option enabled
        """
        mr = self.merge_request
        res_without_tmp = self.repo.merge_request_commits(mr)
        opt = {'scm.merge_list.git.use_tmp_dir': True}
        with h.push_config(tg.config, **opt):
            res_with_tmp = self.repo.merge_request_commits(mr)
        assert_equals(res_without_tmp, res_with_tmp)

    def test_cached_branches(self):
        with mock.patch.dict('allura.lib.app_globals.config', {'repo_refs_cache_threshold': '0'}):
            rev = GM.Repository.query.get(_id=self.repo['_id'])
            branches = rev._impl._get_refs('branches')
            assert_equal(rev.cached_branches, branches)

    def test_cached_tags(self):
        with mock.patch.dict('allura.lib.app_globals.config', {'repo_refs_cache_threshold': '0'}):
            rev = GM.Repository.query.get(_id=self.repo['_id'])
            tags = rev._impl._get_refs('tags')
            assert_equal(rev.cached_tags, tags)

class TestGitImplementation(unittest.TestCase):

    def test_branches(self):
        repo_dir = pkg_resources.resource_filename(
            'forgegit', 'tests/data/testgit.git')
        repo = mock.Mock(full_fs_path=repo_dir)
        repo.__ming__ = mock.Mock()
        repo.cached_branches = []
        impl = GM.git_repo.GitImplementation(repo)
        self.assertEqual(impl.branches, [
            Object(name='master',
                   object_id='1e146e67985dcd71c74de79613719bef7bddca4a'),
            Object(name='zz',
                   object_id='5c47243c8e424136fd5cdd18cd94d34c66d1955c')
        ])

    def test_tags(self):
        repo_dir = pkg_resources.resource_filename(
            'forgegit', 'tests/data/testgit.git')
        repo = mock.Mock(full_fs_path=repo_dir)
        repo.__ming__ = mock.Mock()
        repo.cached_tags = []
        impl = GM.git_repo.GitImplementation(repo)
        self.assertEqual(impl.tags, [
            Object(name='foo',
                   object_id='1e146e67985dcd71c74de79613719bef7bddca4a'),
        ])

    def test_last_commit_ids(self):
        repo_dir = pkg_resources.resource_filename(
            'forgegit', 'tests/data/testrename.git')
        repo = mock.Mock(full_fs_path=repo_dir)
        impl = GM.git_repo.GitImplementation(repo)
        lcd = lambda c, p: impl.last_commit_ids(mock.Mock(_id=c), p)
        self.assertEqual(lcd('13951944969cf45a701bf90f83647b309815e6d5', ['f2.txt', 'f3.txt']), {
            'f2.txt': '259c77dd6ee0e6091d11e429b56c44ccbf1e64a3',
            'f3.txt': '653667b582ef2950c1954a0c7e1e8797b19d778a',
        })
        self.assertEqual(lcd('259c77dd6ee0e6091d11e429b56c44ccbf1e64a3', ['f2.txt', 'f3.txt']), {
            'f2.txt': '259c77dd6ee0e6091d11e429b56c44ccbf1e64a3',
        })

    def test_last_commit_ids_threaded(self):
        with h.push_config(tg.config, lcd_thread_chunk_size=1):
            self.test_last_commit_ids()

    @mock.patch('forgegit.model.git_repo.GitImplementation._git', new_callable=mock.PropertyMock)
    def test_last_commit_ids_threaded_error(self, _git):
        with h.push_config(tg.config, lcd_thread_chunk_size=1, lcd_timeout=2):
            repo_dir = pkg_resources.resource_filename(
                'forgegit', 'tests/data/testrename.git')
            repo = mock.Mock(full_fs_path=repo_dir)
            _git.side_effect = ValueError
            impl = GM.git_repo.GitImplementation(repo)
            lcds = impl.last_commit_ids(
                mock.Mock(_id='13951944969cf45a701bf90f83647b309815e6d5'), ['f2.txt', 'f3.txt'])
            self.assertEqual(lcds, {})


class TestGitCommit(unittest.TestCase):

    def setUp(self):
        setup_basic_test()
        self.setup_with_tools()

    @with_git
    def setup_with_tools(self):
        setup_global_objects()
        h.set_context('test', 'src-git', neighborhood='Projects')
        repo_dir = pkg_resources.resource_filename(
            'forgegit', 'tests/data')
        c.app.repo.fs_path = repo_dir
        c.app.repo.name = 'testgit.git'
        self.repo = c.app.repo
        self.repo.refresh()
        self.rev = self.repo.commit('HEAD')
        ThreadLocalORMSession.flush_all()
        ThreadLocalORMSession.close_all()

    def test_url(self):
        assert self.rev.url().endswith('ca4a/')
        assert self.repo._impl.url_for_commit('master').endswith(
            'master/'), self.repo._impl.url_for_commit('master')

    def test_committer_url(self):
        assert self.rev.committer_url is None

    def test_primary(self):
        assert self.rev.primary() == self.rev

    def test_shorthand(self):
        assert len(self.rev.shorthand_id()) == 8

    def test_diff(self):
        diffs = (self.rev.diffs.added
                 + self.rev.diffs.removed
                 + self.rev.diffs.changed
                 + self.rev.diffs.copied)
        for d in diffs:
            print d

    def test_log(self):
        # path only
        commits = list(self.repo.log(id_only=True))
        assert_equal(commits, [
            "1e146e67985dcd71c74de79613719bef7bddca4a",
            "df30427c488aeab84b2352bdf88a3b19223f9d7a",
            "6a45885ae7347f1cac5103b0050cc1be6a1496c8",
            "9a7df788cf800241e3bb5a849c8870f2f8259d98",
        ])
        commits = list(self.repo.log(self.repo.head, 'README', id_only=True))
        assert_equal(commits, [
            "1e146e67985dcd71c74de79613719bef7bddca4a",
            "df30427c488aeab84b2352bdf88a3b19223f9d7a",
        ])
        commits = list(
            self.repo.log("df30427c488aeab84b2352bdf88a3b19223f9d7a", 'README', id_only=True))
        assert_equal(commits, [
            "df30427c488aeab84b2352bdf88a3b19223f9d7a",
        ])
        commits = list(self.repo.log(self.repo.head, '/a/b/c/', id_only=True))
        assert_equal(commits, [
            "6a45885ae7347f1cac5103b0050cc1be6a1496c8",
            "9a7df788cf800241e3bb5a849c8870f2f8259d98",
        ])
        commits = list(
            self.repo.log("9a7df788cf800241e3bb5a849c8870f2f8259d98", '/a/b/c/', id_only=True))
        assert_equal(commits, [
            "9a7df788cf800241e3bb5a849c8870f2f8259d98",
        ])
        commits = list(
            self.repo.log(self.repo.head, '/does/not/exist/', id_only=True))
        assert_equal(commits, [])


class TestGitHtmlView(unittest.TestCase):

    def setUp(self):
        setup_basic_test()
        self.setup_with_tools()

    @with_git
    def setup_with_tools(self):
        setup_global_objects()
        h.set_context('test', 'src-git', neighborhood='Projects')
        repo_dir = pkg_resources.resource_filename(
            'forgegit', 'tests/data')
        c.app.repo.fs_path = repo_dir
        c.app.repo.name = 'testmime.git'
        self.repo = c.app.repo
        self.repo.refresh()
        self.rev = self.repo.commit('HEAD')
        ThreadLocalORMSession.flush_all()
        ThreadLocalORMSession.close_all()

    def test_html_view(self):
        b = self.rev.tree.get_blob_by_path('README')
        assert b.has_html_view
        b = self.rev.tree.get_blob_by_path('test.jpg')
        assert not b.has_html_view
        b = self.rev.tree.get_blob_by_path('ChangeLog')
        assert b.has_html_view
        b = self.rev.tree.get_blob_by_path('test.spec.in')
        assert b.has_html_view


class TestGitRename(unittest.TestCase):

    def setUp(self):
        setup_basic_test()
        self.setup_with_tools()

    @with_git
    def setup_with_tools(self):
        setup_global_objects()
        h.set_context('test', 'src-git', neighborhood='Projects')
        repo_dir = pkg_resources.resource_filename(
            'forgegit', 'tests/data')
        c.app.repo.fs_path = repo_dir
        c.app.repo.name = 'testrename.git'
        self.repo = c.app.repo
        self.repo.refresh()
        self.rev = self.repo.commit('HEAD')
        ThreadLocalORMSession.flush_all()
        ThreadLocalORMSession.close_all()

    def test_renamed_file(self):
        # There was a file f.txt, then it was renamed to f2.txt.
        commits = list(self.repo.log(id_only=False, path='/f2.txt'))
        self.assertEqual(len(commits), 4)
        rename_commit = commits[1]
        self.assertEqual(rename_commit['rename_details']['path'], '/f.txt')
        self.assertEqual(
            rename_commit['rename_details']['commit_url'],
            '/p/test/src-git/ci/fbb0644603bb6ecee3ebb62efe8c86efc9b84ee6/'
        )
        self.assertEqual(rename_commit['size'], 19)
        self.assertEqual(commits[2]['size'], 19)

    def test_merge_commit(self):
        merge_sha = '13951944969cf45a701bf90f83647b309815e6d5'
        commit = self.repo.log(revs=merge_sha, id_only=False).next()
        self.assertEqual(commit['rename_details'], {})