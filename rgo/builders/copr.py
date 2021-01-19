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
    def __init__(self, owner, name=None, chroot=None, enable_net=False):
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

    def _build_url(self, build_id):
        return self.project_url + "/build/%s" % build_id

    def build_components(self, components):
        # A list of lists; the first list contains components that have no requires,
        # the second list contains components that require those from the first list and so on
        self.build_batches = [[]]
        todo_comps = []

        # prepare the build batches
        for c in components:
            self.build_batches[0].append(c) if not c.requires else todo_comps.append(c)

        i = 1
        built_reqs = set()
        while todo_comps:
            built_reqs.update([c.name for c in self.build_batches[i-1]])
            self.build_batches.append([])
            new_todo = []

            for c in todo_comps:
                self.build_batches[i].append(c) if c.requires.issubset(built_reqs) else new_todo.append(c)

            if not self.build_batches[i]:
                raise Exception("Requires of the following components cannot be satisfied: {}".format(
                    [c.name for c in todo_comps]
                ))

            todo_comps = new_todo
            i += 1

        if len(self.build_batches) > 1:
            LOGGER.info("Doing batched builds")
            for i in range(0, len(self.build_batches)):
                batch = self.build_batches[i]

                LOGGER.info("Batch %d:", i + 1)
                for c in batch:
                    LOGGER.info("  - %s", c.name)

        after_build_id = None
        for batch in self.build_batches:
            with_build_id = None
            for component in batch:
                with_build_id = self.build(
                    component,
                    with_build_id=with_build_id,
                    after_build_id=after_build_id if with_build_id is None else None
                )
                component.build_id = with_build_id
            after_build_id = with_build_id


    def build(self, component, with_build_id=None, after_build_id=None):
        """Build RPM(s) from SRPM.
        :param component: The component to build
        :param with_build_id: ID of the build to build "with" in Copr build batches
        :param after_build_id: ID of the build to build "after" in Copr build batches
        :return: the Copr build id
        """
        chroots = [self.chroot] if self.chroot is not None else list(self.project.chroot_repos.keys())
        buildopts = {
            "chroots": chroots,
            "with_build_id": with_build_id,
            "after_build_id": after_build_id,
        }

        build = self.client.build_proxy.create_from_file(self.owner, self.name, component.srpm, buildopts=buildopts)
        LOGGER.info('Submitted Copr build for %s chroots: %r %s%sURL: %s' % (
            component.name,
            chroots,
            "with: %s " % with_build_id if with_build_id is not None else "",
            "after: %s " % after_build_id if after_build_id is not None else "",
            self._build_url(build.id)
        ))

        return build.id

    def wait_for_results(self):
        failed = False

        for i in range(0, len(self.build_batches)):
            batch = self.build_batches[i]

            while True:
                if len(self.build_batches) > 1:
                    LOGGER.info("Batch %d:", i + 1)
                else:
                    LOGGER.info("Build status:")

                done = True
                for component in batch:
                    if component.done:
                        continue

                    build = self.client.build_proxy.get(component.build_id)

                    component.state = build.state
                    component.done = build.state not in ("waiting", "forked", "running", "pending", "starting", "importing")
                    component.success = build.state == "succeeded"

                    if component.done:
                        if component.success:
                            LOGGER.info("  build #%d - %s: succeeded", component.build_id, component.name)
                        else:
                            # failed/cancelled
                            LOGGER.info("  build #%d - %s: %s", component.build_id, component.name, component.state)
                            failed = True
                    else:
                        done = False
                        LOGGER.info("  build #%d - %s: %s", component.build_id, component.name, component.state)

                if done:
                    break

                time.sleep(10)

        if failed:
            LOGGER.info("Failed builds:")
            for batch in self.build_batches:
                for component in batch:
                    if not component.success:
                        LOGGER.info("  build #%d - %s (%s): %s",
                            component.build_id, component.name, component.state, self._build_url(component.build_id)
                        )

            raise Exception("Some builds have failed")

        rpms = []
        for batch in self.build_batches:
            for component in batch:
                # Parse results
                for build_chroot in self.client.build_chroot_proxy.get_list(component.build_id):
                    url_prefix = build_chroot.result_url
                    resp = requests.get(url_prefix)
                    if resp.status_code != 200:
                        raise Exception("Failed to fetch {!r}: {!s}".format(url_prefix, resp.text))
                    soup = bs4.BeautifulSoup(resp.text, "lxml")
                    for link in soup.find_all("a", href=True):
                        href = link["href"]
                        if href.endswith(".rpm") and not href.endswith(".src.rpm"):
                            rpms.append("{}/{}".format(url_prefix, href))

        return rpms
