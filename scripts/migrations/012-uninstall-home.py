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

import sys
import logging

from pylons import tmpl_context as c
from ming.orm import session
from bson import ObjectId
from mock import Mock, patch

from allura.lib import helpers as h
from allura.lib import utils
from allura import model as M
from forgewiki import model as WM
from allura.ext.project_home import ProjectHomeApp

log = logging.getLogger('uninstall-home')
log.addHandler(logging.StreamHandler(sys.stdout))


def main():
    test = sys.argv[-1] == 'test'
    log.info('Removing "home" tools')
    affected_projects = 0
    possibly_orphaned_projects = 0
    solr_delete = Mock()
    notification_post = Mock()
    for some_projects in utils.chunked_find(M.Project, {'neighborhood_id': {
            '$ne': ObjectId("4be2faf8898e33156f00003e")}}):
        for project in some_projects:
            c.project = project
            old_home_app = project.app_instance('home')
            if isinstance(old_home_app, ProjectHomeApp):

                # would we actually be able to install a wiki?
                if M.ProjectRole.by_name('Admin') is None:
                    log.warning('project %s may be orphaned' %
                                project.shortname)
                    possibly_orphaned_projects += 1
                    continue

                affected_projects += 1

                # remove the existing home tool
                if test:
                    log.info('would remove "home" tool from project ' +
                             project.shortname)
                else:
                    log.info('removing "home" tool from project ' +
                             project.shortname)
                    with patch('allura.app.g.solr.delete', solr_delete):
                        project.uninstall_app('home')

                # ...and put a Wiki in its place (note we only create a Wiki if we deleted the old home)
                if test:
                    log.info('would create Wiki "home" for project ' +
                             project.shortname)
                else:
                    log.info('creating Wiki "home" for project ' +
                             project.shortname)
                    home_title = project.homepage_title or 'Home'
                    wiki_text = project.description or ''
                    if wiki_text == 'You can edit this description in the admin page':
                        wiki_text = 'You can edit this description'

                    # re-number all the mounts so the new Wiki comes first
                    mounts = project.ordered_mounts()
                    with patch('forgewiki.model.wiki.Notification.post', notification_post):
                        new_home_app = project.install_app(
                            'Wiki', 'home', 'Home')
                    mounts = [{'ordinal': 0, 'ac': new_home_app.config}] + \
                        mounts
                    for i, mount in enumerate(mounts):
                        if 'ac' in mount:
                            mount['ac'].options['ordinal'] = i
                            session(mount['ac']).flush()
                        elif 'sub' in mount:
                            mount['sub'].ordinal = i
                            session(mount['sub']).flush()

                    # make it look as much like the old home tool as possible
                    new_home_app.config.options['show_left_bar'] = False
                    new_home_app.config.options['show_discussion'] = False

                    # now let's fix the home page itself
                    log.info('updating home page to "%s"' % home_title)
                    new_home_page = WM.Page.query.find(
                        dict(app_config_id=new_home_app.config._id)).first()
                    with h.push_config(c, app=new_home_app):
                        if new_home_page is None:
                            # weird: we didn't find the existing home page
                            log.warning(
                                'hmmm, actually creating the home page ("%s") for project "%s" from scratch' %
                                (home_title, project.shortname))
                            new_home_page = WM.Page.upsert(home_title)
                            new_home_page.viewable_by = ['all']
                        new_home_page.title = home_title
                        new_home_page.text = wiki_text
                        with patch('forgewiki.model.wiki.Notification.post', notification_post):
                            new_home_page.commit()
                    assert new_home_page is not None
                    assert new_home_page.title == home_title
                    assert new_home_page.version == 2

                    # if we changed the home page name, make sure the Wiki
                    # knows that's the root page
                    new_home_app.root_page_name = home_title

                session(project).flush()
            session(project).clear()
    if test:
        log.info('%s projects would be updated' % affected_projects)
    else:
        log.info('%s projects were updated' % affected_projects)
    if possibly_orphaned_projects:
        log.warning('%s possibly orphaned projects found' %
                    possibly_orphaned_projects)
    if not test:
        assert solr_delete.call_count == affected_projects, solr_delete.call_count
        assert notification_post.call_count == 2 * \
            affected_projects, notification_post.call_count

if __name__ == '__main__':
    main()
