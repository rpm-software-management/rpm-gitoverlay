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

from datetime import datetime
import logging
import time

import bs4
import copr
import requests

from ..exceptions import OverlayException

class CoprBuilder(object):
    def __init__(self, chroots=("fedora-24-x86_64",), enable_net=False):
        """
        :param chroots: Project chroots
        :type chroots: tuple(str, ...)
        :param enable_net: Enable internet during build, it's better to disable
        :type enable_net: bool
        """
        self.client = copr.client_v2.client.CoprClient.create_from_file_config()
        self.chroots = chroots
        self.enable_net = enable_net

    def getproject(self, owner, name):
        self.client.projects.get_list(owner=owner, name=name, limit=1)
        if not projects:
            raise Exception("Project not found")
        return projects.projects[0]

    def mkproject(self, owner, name=None):
        """
        Create or get project in COPR.

        :param owner: Project owner
        :type owner: str
        :param name: Project name, if not specified will be generated randomly
        :type name: str | None
        """
        if name is None:
            now = datetime.now()
            name = "rpm-gitoverlay-{}".format(now.strftime("%Y%m%d%H%M%S%f"))
        projects = self.client.projects.get_list(owner=owner, name=name, limit=1)
        if not projects:
            project = self.client.projects.create(name=name,
                                                  owner=owner,
                                                  chroots=self.chroots,
                                                  build_enable_net=self.enable_net,
                                                  description="RPM git-overlay")
            logging.info("Created COPR project: %s/%s", owner, name)
        else:
            logging.info("Using existing project: %s/%s", owner, name)
            project = projects.projects[0]

        return project

    def build_from_srpm(self, project, srpm):
        """
        Build SRPM in COPR.

        :param project: COPR Project
        :type project: copr.client_v2.resources.Project
        :param srpm: Path to .src.rpm to build
        :type srpm: str
        :return: URLs to RPMs
        :rtype: list(str, ...)
        """
        if len(self.chroots) > 1:
            raise NotImplementedError

        build = project.create_build_from_file(file_path=srpm,
                                               chroots=self.chroots,
                                               enable_net=self.enable_net)

        success = True
        # Wait for build to complete
        while True:
            # Refresh info
            done = set()
            for task in build.get_build_tasks():
                _done = task.state not in ("running", "pending", "starting", "importing")
                if _done:
                    if task.state == "failed":
                        logging.warning("Build #%d (chroot: %r): failed",
                                        build.id, task.chroot_name)
                        success = False
                    elif task.state == "succeeded":
                        logging.info("Build #%d (chroot: %r): succeeded",
                                     build.id, task.chroot_name)
                    else:
                        raise OverlayException("Build #%d (chroot: %r): %r",
                                               build.id, task.chroot_name, task.state)
                        success = False
                else:
                    logging.debug("Build #%d (chroot: %r): %r",
                                  build.id, task.chroot_name, task.state)

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
            raise OverlayException("Build failed")

        return rpms
