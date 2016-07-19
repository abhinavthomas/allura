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
import json
import logging

from pylons import tmpl_context as c

from ming.orm import session, MappedClass

from allura import model as M

log = logging.getLogger(__name__)


def main():
    test = sys.argv[-1] == 'test'
    projects = M.Project.query.find().all()
    log.info('Restoring labels on projects')
    for p in projects:
        restore_labels(p, test)
    if not test:
        session(p).flush()
    log.info('Restoring labels on artifacts')
    for p in projects:
        if p.parent_id:
            continue
        c.project = p
        for name, cls in MappedClass._registry.iteritems():
            if not issubclass(cls, M.Artifact):
                continue
            if session(cls) is None:
                continue
            for a in cls.query.find():
                restore_labels(a, test)
        if not test:
            M.artifact_orm_session.flush()
        M.artifact_orm_session.clear()


def restore_labels(obj, test=True):
    if not obj.labels:
        return
    labels = obj.labels
    while True:
        if not labels or labels[0] != '[':
            return
        lbllen = map(len, labels)
        if max(lbllen) != 1:
            return
        if min(lbllen) != 1:
            return
        s = ''.join(labels)
        s = s.replace("u'", "'")
        s = s.replace('u"', '"')
        jobj = '{"obj":' + s.replace("'", '"') + '}'
        try:
            new_labels = json.loads(jobj)['obj']
        except ValueError:
            # some weird problem with json decoding, just erase the labels
            new_labels = []
        if not isinstance(new_labels, list):
            return
        for lbl in new_labels:
            if not isinstance(lbl, basestring):
                return
        log.info('%s: %s => %s', obj.__class__, labels, new_labels)
        labels = new_labels
        if not test:
            log.info('...actually restoring labels')
            obj.labels = new_labels

if __name__ == '__main__':
    main()
