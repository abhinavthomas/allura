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

import logging
import re

import pkg_resources
from pylons import tmpl_context as c
from pylons import app_globals as g
from pylons import request
from formencode import validators
from tg import expose, redirect, validate, flash
import tg
from webob import exc
from jinja2 import Markup
from pytz import timezone
from datetime import datetime
from paste.deploy.converters import asbool

from allura import version
from allura.app import Application, SitemapEntry
from allura.lib import helpers as h
from allura.lib.security import require_access
from allura.lib.plugin import AuthenticationProvider
from allura.model import User, ACE, ProjectRole
from allura.controllers import BaseController
from allura.controllers.feed import FeedArgs, FeedController
from allura.controllers.rest import AppRestControllerMixin
from allura.lib.decorators import require_post
from allura.lib.widgets.user_profile import SendMessageForm

log = logging.getLogger(__name__)


class F(object):
    send_message = SendMessageForm()


class UserProfileApp(Application):

    """
    This is the Profile tool, which is automatically installed as
    the default (first) tool on any user project.
    """
    __version__ = version.__version__
    tool_label = 'Profile'
    max_instances = 0
    has_notifications = False
    icons = {
        24: 'images/home_24.png',
        32: 'images/home_32.png',
        48: 'images/home_48.png'
    }

    def __init__(self, user, config):
        Application.__init__(self, user, config)
        self.root = UserProfileController()
        self.templates = pkg_resources.resource_filename(
            'allura.ext.user_profile', 'templates')
        self.api_root = UserProfileRestController()

    @property
    @h.exceptionless([], log)
    def sitemap(self):
        return [SitemapEntry('Profile', '.')]

    def admin_menu(self):
        return []

    def main_menu(self):
        return [SitemapEntry('Profile', '.')]

    def is_visible_to(self, user):
        # we don't work with user subprojects
        return c.project.is_root

    def install(self, project):
        pr = ProjectRole.by_user(c.user)
        if pr:
            self.config.acl = [
                ACE.allow(pr._id, perm)
                for perm in self.permissions]

    def uninstall(self, project):  # pragma no cover
        pass

    @property
    def profile_sections(self):
        """
        Loads and caches user profile sections from the entry-point
        group ``[allura.user_profile.sections]``.

        Profile sections are loaded unless disabled (see
        `allura.lib.helpers.iter_entry_points`) and are sorted according
        to the `user_profile_sections.order` config value.

        The config should contain a comma-separated list of entry point names
        in the order that they should appear in the profile.  Unknown or
        disabled sections are ignored, and available sections that are not
        specified in the order come after all explicitly ordered sections,
        sorted randomly.
        """
        if hasattr(UserProfileApp, '_sections'):
            return UserProfileApp._sections
        sections = {}
        for ep in h.iter_entry_points('allura.user_profile.sections'):
            sections[ep.name] = ep.load()
        section_ordering = tg.config.get('user_profile_sections.order', '')
        ordered_sections = []
        for section in re.split(r'\s*,\s*', section_ordering):
            if section in sections:
                ordered_sections.append(sections.pop(section))
        UserProfileApp._sections = ordered_sections + sections.values()
        return UserProfileApp._sections


class UserProfileController(BaseController, FeedController):

    def _check_security(self):
        require_access(c.project, 'read')

    def _check_can_message(self, from_user, to_user):
        if from_user is User.anonymous():
            flash('You must be logged in to send user messages.', 'info')
            redirect(request.referer)

        if not (from_user and from_user.get_pref('email_address')):
            flash('In order to send messages, you must have an email address '
                  'associated with your account.', 'info')
            redirect(request.referer)

        if not (to_user and to_user.get_pref('email_address')):
            flash('This user can not receive messages because they do not have '
                  'an email address associated with their account.', 'info')
            redirect(request.referer)

        if to_user.get_pref('disable_user_messages'):
            flash('This user has disabled direct email messages', 'info')
            redirect(request.referer)

    @expose('jinja:allura.ext.user_profile:templates/user_index.html')
    def index(self, **kw):
        user = c.project.user_project_of
        if not user:
            raise exc.HTTPNotFound()
        provider = AuthenticationProvider.get(request)
        sections = [section(user, c.project)
                    for section in c.app.profile_sections]
        return dict(
            user=user,
            reg_date=provider.user_registration_date(user),
            sections=sections)

    def get_feed(self, project, app, user):
        """Return a :class:`allura.controllers.feed.FeedArgs` object describing
        the xml feed for this controller.

        Overrides :meth:`allura.controllers.feed.FeedController.get_feed`.

        """
        user = project.user_project_of
        return FeedArgs(
            {'author_link': user.url()},
            'Recent posts by %s' % user.display_name,
            project.url())

    @expose('jinja:allura.ext.user_profile:templates/send_message.html')
    def send_message(self):
        """Render form for sending a message to another user.

        """
        self._check_can_message(c.user, c.project.user_project_of)

        delay = c.user.time_to_next_user_message()
        expire_time = str(delay) if delay else None
        c.form = F.send_message
        return dict(user=c.project.user_project_of, expire_time=expire_time)

    @require_post()
    @expose()
    @validate(dict(subject=validators.NotEmpty,
                   message=validators.NotEmpty))
    def send_user_message(self, subject='', message='', cc=None):
        """Handle POST for sending a message to another user.

        """
        self._check_can_message(c.user, c.project.user_project_of)

        if cc:
            cc = c.user.get_pref('email_address')
        if c.user.can_send_user_message():
            c.user.send_user_message(
                c.project.user_project_of, subject, message, cc)
            flash("Message sent.")
        else:
            flash("You can't send more than %i messages per %i seconds" % (
                c.user.user_message_max_messages,
                c.user.user_message_time_interval), 'error')
        return redirect(c.project.user_project_of.url())


class UserProfileRestController(AppRestControllerMixin):
    @expose('json:')
    def index(self, **kw):
        user = c.project.user_project_of
        if not user:
            raise exc.HTTPNotFound()
        sections = [section(user, c.project)
                    for section in c.app.profile_sections]
        json = {}
        for s in sections:
            if hasattr(s, '__json__'):
                json.update(s.__json__())
        return json


class ProfileSectionBase(object):

    """
    This is the base class for sections on the Profile tool.

    .. py:attribute:: template

       A resource string pointing to the template for this section.  E.g.::

           template = "allura.ext.user_profile:templates/projects.html"

    Sections must be pointed to by an entry-point in the group
    ``[allura.user_profile.sections]``.
    """
    template = ''

    def __init__(self, user, project):
        """
        Creates a section for the given :param:`user` and user
        :param:`project`.  Stores the values as attributes of
        the same name.
        """
        self.user = user
        self.project = project

    def check_display(self):
        """
        Should return True if the section should be displayed.
        """
        return True

    def prepare_context(self, context):
        """
        Should be overridden to add any values to the template context prior
        to display.
        """
        return context

    def display(self, *a, **kw):
        """
        Renders the section using the context from :meth:`prepare_context`
        and the :attr:`template`, if :meth:`check_display` returns True.

        If overridden or this base class is not used, this method should
        return either plain text (which will be escaped) or a `jinja2.Markup`
        instance.
        """
        if not self.check_display():
            return ''
        try:
            tmpl = g.jinja2_env.get_template(self.template)
            context = self.prepare_context({
                'h': h,
                'c': c,
                'g': g,
                'user': self.user,
                'config': tg.config,
                'auth': AuthenticationProvider.get(request),
            })
            return Markup(tmpl.render(context))
        except Exception as e:
            log.exception('Error rendering profile section %s: %s', type(self).__name__, e)
            if asbool(tg.config.get('debug')):
                raise
            else:
                return ''


class PersonalDataSection(ProfileSectionBase):
    template = 'allura.ext.user_profile:templates/sections/personal-data.html'

    def prepare_context(self, context):
        context['timezone'] = self.user.get_pref('timezone')
        if context['timezone']:
            tz = timezone(context['timezone'])
            context['timezone'] = tz.tzname(datetime.utcnow())
        return context

    def __json__(self):
        auth_provider = AuthenticationProvider.get(request)
        return dict(
            username=self.user.username,
            name=self.user.display_name,
            joined=auth_provider.user_registration_date(self.user),
            localization=self.user.get_pref('localization')._deinstrument(),
            sex=self.user.get_pref('sex'),
            telnumbers=self.user.get_pref('telnumbers')._deinstrument(),
            skypeaccount=self.user.get_pref('skypeaccount'),
            webpages=self.user.get_pref('webpages')._deinstrument(),
            availability=self.user.get_pref('availability')._deinstrument())


class ProjectsSection(ProfileSectionBase):
    template = 'allura.ext.user_profile:templates/sections/projects.html'

    def get_projects(self):
        return [
            project
            for project in self.user.my_projects()
            if project != c.project
            and (self.user == c.user or h.has_access(project, 'read'))
            and not project.is_nbhd_project
            and not project.is_user_project]

    def prepare_context(self, context):
        context['projects'] = self.get_projects()
        return context

    def __json__(self):
        projects = [
            dict(
                name=project['name'],
                url=project.url(),
                summary=project['summary'],
                last_updated=project['last_updated'])
            for project in self.get_projects()]
        return dict(projects=projects)


class SkillsSection(ProfileSectionBase):
    template = 'allura.ext.user_profile:templates/sections/skills.html'

    def __json__(self):
        return dict(skills=self.user.get_skills())


class ToolsSection(ProfileSectionBase):
    template = 'allura.ext.user_profile:templates/sections/tools.html'


class SocialSection(ProfileSectionBase):
    template = 'allura.ext.user_profile:templates/sections/social.html'

    def __json__(self):
        return dict(
            socialnetworks=self.user.get_pref('socialnetworks')._deinstrument())
