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
import copr.v3 as copr
import requests
from .. import LOGGER

class CoprBuilder(object):
    def __init__(self, owner, name=None, chroot=None, no_wait=False, enable_net=False):
        """Build RPMs in COPR.
        :param str owner: Project owner
        :param str name: Project name
        :param str chroot: Project chroot
        :param bool enable_net: Enable internet during build (better to disable)
        """
        # FIXME: implement support for groups
        if owner.startswith("@"):
            raise NotImplementedError("Group projects are not implemented")
        self.owner = owner

        if not name:
            name = "rpm-gitoverlay-{:f}".format(time.time())
        self.name = name

        self.client = copr.Client.create_from_config_file()

        if chroot is not None and \
                chroot not in self.client.mock_chroot_proxy.get_list():
            raise Exception("{!r} doesn't seem to be active chroot".format(chroot))
        self.chroot = chroot

        self.no_wait = no_wait
        self.enable_net = enable_net

        try:
            self.project = self.client.project_proxy.get(owner, name)
            LOGGER.info("Using existing COPR project: %s/%s", self.project.ownername, self.project.name)

            if self.chroot is not None and self.chroot not in self.project.chroot_repos:
                raise Exception("{!r} chroot is not enabled for COPR project: ".format(self.chroot))
        except copr.exceptions.CoprNoResultException:
            if self.chroot is None:
                raise Exception("Project {!r} doesn't exist, --chroot needs to be specified".format(name))

            self.project = self.client.project_proxy.add(owner, name, [self.chroot], enable_net=self.enable_net)
            LOGGER.info("Created COPR project: %s/%s", self.project.ownername, self.project.name)

        LOGGER.info("COPR Project URL: %r", self.project_url)

    @property
    def project_url(self):
        url = "/coprs/{p.ownername}/{p.name}"

        return urljoin(self.client.config["copr_url"], url.format(p=self.project))

    def build(self, srpm):
        """Build RPM(s) from SRPM.
        :param str srpm: Path to .src.rpm to build
        :return: URL(s) to RPM(s)
        :rtype: list
        """
        chroots = [self.chroot] if self.chroot is not None else list(self.project.chroot_repos.keys())
        build = self.client.build_proxy.create_from_file(self.owner, self.name, srpm, buildopts={"chroots": chroots})

        if self.no_wait:
            return []

        success = True
        # Wait for build to complete
        while True:
            build = self.client.build_proxy.get(build.id)

            done = build.state not in ("waiting", "forked", "running", "pending", "starting", "importing")
            if done:
                if build.state == "failed":
                    success = False
                    LOGGER.warning("Build #%d: failed", build.id)
                elif build.state == "succeeded":
                    LOGGER.info("Build #%d: succeeded", build.id)
                else:
                    success = False
                    raise Exception("Build #{:d}: {!s}".format(build.id, task.state))
            else:
                LOGGER.debug("Build #%d: %s", build.id, build.state)

            if done:
                break

            time.sleep(5)

        # Parse results
        rpms = []
        for build_chroot in self.client.build_chroot_proxy.get_list(build.id):
            url_prefix = build_chroot.result_url
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
