# -*- coding: utf-8 -*-
#
# Copyright © 2016 Igor Gnatenko <ignatenko@redhat.com>
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program. If not, see <http://www.gnu.org/licenses/>.

import time
from urllib.parse import urljoin
import bs4
import copr
import requests
from .. import LOGGER

class CoprBuilder(object):
    def __init__(self, owner, name=None, chroot=None, enable_net=False):
        """Build RPMs in COPR.
        :param str owner: Project owner
        :param str name: Project name
        :param str chroot: Project chroot
        :param bool enable_net: Enable internet during build (better to disable)
        """
        # FIXME: python-copr doesn't support group projects
        # https://bugzilla.redhat.com/show_bug.cgi?id=1337247
        if owner.startswith("@"):
            raise NotImplementedError("Group projects are not supported in python-copr")

        self.client = copr.create_client2_from_file_config()
        if chroot is not None and chroot not in (c.name for c in self.client.mock_chroots.get_list(active_only=True)):
            raise Exception("{!r} doesn't seem to be active chroot".format(chroot))
        self.enable_net = enable_net
        if not name:
            name = "rpm-gitoverlay-{:f}".format(time.time())
        projects = self.client.projects.get_list(owner=owner, name=name, limit=1)
        if not projects:
            if chroot is None:
                raise Exception("Project {!r} doesn't exist, --chroot needs to be specified".format(name))

            self.project = self.client.projects.create(owner=owner, name=name,
                                                       chroots=[chroot],
                                                       build_enable_net=self.enable_net)
            LOGGER.info("Created COPR project: %s/%s",
                        self.project.owner, self.project.name)
        else:
            self.project = projects[0]
            LOGGER.info("Using existing COPR project: %s/%s",
                        self.project.owner, self.project.name)
            if chroot is not None and chroot not in (c.name for c in self.project.get_project_chroot_list()):
                raise Exception("{!r} chroot is not enabled for COPR project".format(chroot))
        self.chroot = chroot
        LOGGER.info("COPR Project URL: %r", self.project_url)

    @property
    def project_url(self):
        # FIXME: uncomment once upstream will implement it
        #if project.group:
        #    url = "/coprs/g/{p.group}/{p.name}"
        #else:
        url = "/coprs/{p.owner}/{p.name}"
        return urljoin(self.client.root_url, url.format(p=self.project))

    def build(self, srpm):
        """Build RPM(s) from SRPM.
        :param str srpm: Path to .src.rpm to build
        :return: URL(s) to RPM(s)
        :rtype: list
        """
        chroots = [self.chroot] if self.chroot is not None else self.project.get_project_chroot_list()
        build = self.project.create_build_from_file(file_path=srpm, chroots=chroots, enable_net=self.enable_net)

        success = True
        # Wait for build to complete
        while True:
            # Refresh info
            done = set()
            for task in build.get_build_tasks():
                _done = task.state not in ("waiting", "forked", "running",
                                           "pending", "starting", "importing")
                if _done:
                    if task.state == "failed":
                        success = False
                        LOGGER.warning("Build #%d: failed", build.id)
                    elif task.state == "succeeded":
                        LOGGER.info("Build #%d: succeeded", build.id)
                    else:
                        success = False
                        raise Exception("Build #{:d}: {!s}".format(build.id, task.state))
                else:
                    LOGGER.debug("Build #%d: %s", build.id, task.state)

                done.add(_done)

            if all(done):
                break

            time.sleep(5)

        # Parse results
        rpms = []
        for task in build.get_build_tasks():
            url_prefix = task.result_dir_url
            resp = requests.get(url_prefix)
            if resp.status_code != 200:
                raise Exception("Failed to fetch {!r}: {!s}".format(url_prefix, resp.text))
            soup = bs4.BeautifulSoup(resp.text, "lxml")
            for link in soup.find_all("a", href=True):
                href = link["href"]
                if href.endswith(".rpm") and not href.endswith(".src.rpm"):
                    rpms.append("{}/{}".format(url_prefix, href))

        if not success:
            # TODO: improve message
            raise Exception("Build failed")

        return rpms
