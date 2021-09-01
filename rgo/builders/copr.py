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
    def __init__(
        self,
        owner,
        name=None,
        chroots=[],
        enable_net=False,
        delete_after_days=None,
        additional_repos=None,
        build_with=None
    ):
        """Build RPMs in COPR.
        :param str owner: Project owner
        :param str name: Project name
        :param str chroots: A list of chroots to build for
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

        for chroot in chroots:
            if chroot not in self.client.mock_chroot_proxy.get_list():
                raise Exception("{!r} is not an active chroot".format(chroot))
        self.chroots = chroots

        self.enable_net = enable_net

        try:
            self.project = self.client.project_proxy.get(owner, name)
            LOGGER.info("Using existing COPR project: %s/%s", self.project.ownername, self.project.name)

            if len(chroots) == 0:
                self.chroots = self.project.chroot_repos.keys()

            # add the build chroots to the project's chroots and extend its expiration time
            self.client.project_proxy.edit(
                owner,
                name,
                chroots=list(set(list(self.project.chroot_repos.keys()) + chroots)),
                delete_after_days=delete_after_days,
                additional_repos=additional_repos
            )

        except copr.exceptions.CoprNoResultException:
            if not self.chroots:
                raise Exception("Project {!r} doesn't exist, --chroots needs to be specified".format(name))

            self.project = self.client.project_proxy.add(
                owner,
                name,
                self.chroots,
                enable_net=self.enable_net,
                delete_after_days=delete_after_days,
                additional_repos=additional_repos,
                unlisted_on_hp=True
            )
            LOGGER.info("Created COPR project: %s/%s", self.project.ownername, self.project.name)

        if build_with:
            for chroot in self.chroots:
                self.client.project_chroot_proxy.edit(owner, name, chroot, with_opts=build_with)

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

    def _create_copr_build(self, chroots, srpm, name, buildopts):
        buildopts["chroots"] = list(chroots)
        build = self.client.build_proxy.create_from_file(self.owner,
                                                         self.name,
                                                         srpm,
                                                         buildopts=buildopts)
        LOGGER.info('Submitted Copr build for %s chroots: %s %s%sURL: %s' % (
            name, ", ".join(buildopts["chroots"]),
            "with: %s " % buildopts["with_build_id"] if buildopts["with_build_id"] is not None else "",
            "after: %s " % buildopts["after_build_id"] if buildopts["after_build_id"] is not None else "",
            self._build_url(build.id)
        ))
        return build.id


    def build(self, component, with_build_id=None, after_build_id=None):
        """Build RPM(s) from default SRPM and from distgit-overrides SRPMs (it also sets their build ids).
        :param component: The component to build
        :param with_build_id: ID of the build to build "with" in Copr build batches
        :param after_build_id: ID of the build to build "after" in Copr build batches
        :return: the Copr build id of the first build created
        """
        buildopts = {
            "with_build_id": with_build_id,
            "after_build_id": after_build_id,
        }

        first_build_id = None

        overriden_chroots = set()
        for override in component.distgit_overrides:
            overriden_chroots.update(override.chroots)

        default_build_chroots = list(set(self.chroots) - overriden_chroots)
        # if we have atleast one default (not overriden) chroot do the default build
        if (default_build_chroots):
            first_build_id = self._create_copr_build(default_build_chroots, component.srpm, component.name, buildopts)

        for override in component.distgit_overrides:
            # if we haven't yet configured buildopts["with_build_id"] and we have a first_build_id use it
            if buildopts["with_build_id"] is None and first_build_id:
                buildopts["with_build_id"] = first_build_id

            # use override only if we build for its chroots
            override_chroots = set(override.chroots) & set(self.chroots)
            if override_chroots:
                override.build_id = self._create_copr_build(override_chroots, override.srpm, component.name, buildopts)
                if not first_build_id:
                    first_build_id = override.build_id

        return first_build_id

    @staticmethod
    def _report_build_proxy_and_get_status(build_proxy, name):
        """
        Report status of the build through LOGGER and return its status
        :param ProxyBuild build_proxy: Copr object representing a build
        :param str name: Name of the build
        :return: Bool whether build ended and a Bool whether if faild or succeeded
        :rtype: bool, bool
        """
        if build_proxy.ended_on:
            if build_proxy.state == "succeeded":
                LOGGER.info("  build #%d - %s: succeeded", build_proxy.id, name)
                return True, False
            else:
                # failed/cancelled
                LOGGER.info("  build #%d - %s: %s", build_proxy.id, name, build_proxy.state)
                return True, True
        else:
            LOGGER.info("  build #%d - %s: %s", build_proxy.id, name, build_proxy.state)
            return False, False


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
                    if component.build_id:
                        if not component.done:
                            component.build_proxy = self.client.build_proxy.get(component.build_id)
                            component.done, build_failed = CoprBuilder._report_build_proxy_and_get_status(
                                component.build_proxy,
                                component.name)
                            if not component.done:
                                done = False
                            if build_failed:
                                failed = True
                    for override in component.distgit_overrides:
                        if override.build_id:
                            if not override.done:
                                override.build_proxy = self.client.build_proxy.get(override.build_id)
                                override.done, build_failed = CoprBuilder._report_build_proxy_and_get_status(
                                        override.build_proxy,
                                        ", ".join(override.chroots) + " distgit-override " + component.name)
                                if not override.done:
                                    done = False
                                if build_failed:
                                    failed = True
                if done:
                    break

                time.sleep(10)

        if failed:
            LOGGER.info("Failed builds:")
            for batch in self.build_batches:
                for component in batch:
                    if not component.build_proxy.state == "succeeded":
                        LOGGER.info("  build #%d - %s (%s): %s",
                                    component.build_id,
                                    component.name,
                                    component.build_proxy.state,
                                    self._build_url(component.build_id))
                    for override in component.distgit_overrides:
                        if not override.build_proxy.state == "succeeded":
                            LOGGER.info("  distgit-override build #%d - %s (%s): %s",
                                        override.build_id,
                                        component.name,
                                        override.build_proxy.state,
                                        self._build_url(override.build_id))


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
