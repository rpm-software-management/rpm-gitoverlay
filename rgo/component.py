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


import os
import re
import shutil
import subprocess

import rpm

from . import LOGGER, utils
from .git import PatchesAction


SRPM_RE = re.compile(r".+\.(?:no)?src\.rpm")

class Component(object):
    def __init__(self, name, version_from=None, git=None, distgit=None, requires=None, distgit_overrides=None):
        """
        :param str name: Name of component
        :param rgo.git.Git: Git repository
        :param rgo.git.DistGit: Dist-Git repository
        """
        assert git or distgit
        self.name = name

        self.git = git
        self.distgit = distgit
        self.version_from = version_from

        if self.version_from is None:
            if self.distgit:
                self.version_from = "git"
            else:
                self.version_from = "spec"

        if requires is None:
            requires = []
        self.requires = set(requires)
        self.cloned = False

        if distgit_overrides is None:
            distgit_overrides = []
        self.distgit_overrides = set(distgit_overrides)

        self.build_id = None
        self.done = None
        self.srpm = None
        self.state = None
        self.success = None

    def __repr__(self): # pragma: no cover
        return "<Component {0.name!r}: git({0.git!r}) distgit({0.distgit})>".format(self)

    def clone(self, dest):
        """
        :param str dest: Directory for git repos to clone in
        """
        if self.git:
            self.git.clone(os.path.join(dest, self.name))
        if self.distgit:
            self.distgit.clone(os.path.join(dest, "{!s}-distgit".format(self.name)))
        for override in self.distgit_overrides:
            override.clone(os.path.join(dest, "{!s}-override-{!s}".format(self.name, override.src)))
        self.cloned = True

    def _make_srpm(self, tmpdir, distgit, patches_action):
        """
        Build SRPM.
        :param str tmpdir: Dir where to create the new srpm
        :param str distgit: Distgit repository if specified used for Specfile and pathes
        :param PatchesAction patches_action: What to do with patches
        :return: Path to the built srpm
        :rtype: str
        """
        workdir = os.path.join(tmpdir, self.name)
        os.mkdir(workdir)

        spec_name = distgit.spec_path or "{!s}.spec".format(self.name)

        # extract spec file from specified branch and save it in temporary location
        original_spec_path = os.path.join(workdir, "original.spec")
        with open(original_spec_path, "w") as f_spec:
            subprocess.run(["git", "cat-file", "-p", "{}:{}".format(distgit.ref, spec_name)],
                           cwd=distgit.cwd, check=True, stdout=f_spec)

        original_rpmspec = rpm.spec(original_spec_path)

        spec_name = original_rpmspec.sourceHeader["Name"]
        if isinstance(spec_name, bytes):
            spec_name = spec_name.decode("utf-8")

        spec_version = original_rpmspec.sourceHeader["Version"]
        if isinstance(spec_version, bytes):
            spec_version = spec_version.decode("utf-8")

        final_spec_path = os.path.join(workdir, "{!s}.spec".format(spec_name))

        # PREPARE SPECFILE AND ARCHIVE
        if self.git:
            version, release = self.git.describe(self.name, spec_version=spec_version, version_from=self.version_from)

            # Prepare nvr
            if release == "1":
                # tagged version, no need to add useless numbers
                nvr = "{!s}-{!s}".format(self.name, version)
            else:
                nvr = "{!s}-{!s}-{!s}".format(self.name, version, release)

            # Prepare archive from git (compressed tarball)
            archive = os.path.join(workdir, "{!s}.tar.xz".format(nvr))
            LOGGER.debug("Preparing archive %r", archive)
            proc = subprocess.run(["git", "archive", "--prefix={!s}/".format(nvr),
                                   "--format=tar", self.git.ref],
                                  cwd=self.git.cwd, check=True,
                                  stdout=subprocess.PIPE)
            with open(archive, "w") as f_archive:
                subprocess.run(["xz", "-z", "--threads=0", "-"],
                               check=True, input=proc.stdout, stdout=f_archive)

            # Prepare new spec
            with open(final_spec_path, "w") as specfile:
                prepared = "{!s}\n{!s}".format(
                    utils.prepare_spec(original_spec_path, version, release, nvr, patches_action),
                    utils.generate_changelog(self.git.timestamp, version, release, self.git.get_rpm_changelog()))
                specfile.write(prepared)
        else:
            # If no git specified use distgit for both specfile and source code.
            # We could simply copy specifile like this:
            # shutil.copy2(original_spec_path, final_spec_path)
            # but getting the source code (tarball) is not so simple.
            raise NotImplementedError("Getting a tarball from distgit is not implemented")

        # PREPARE SPECFILE PATCHES
        if patches_action == PatchesAction.keep:
            _sources = []
            for src, _, src_type in rpm.spec(final_spec_path).sources:
                if src_type == rpm.RPMBUILD_ISPATCH:
                    _sources.append(src)

            if _sources and not distgit:
                raise NotImplementedError("Patches are applied in upstream")
            else:
                # Copy sources/patches from distgit
                for source in _sources:
                    shutil.copy2(os.path.join(distgit.cwd, distgit.patches_dir, source),
                                 os.path.join(workdir, source))

        # RPMBUILD SRPM
        try:
            result = subprocess.run(["rpmbuild", "-bs", final_spec_path, "--nodeps",
                                     "--define", "_topdir {!s}".format(workdir),
                                     "--define", "_sourcedir {!s}".format(workdir)],
                                    check=True, universal_newlines=True,
                                    stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        except subprocess.CalledProcessError as err:
            LOGGER.critical("Failed to build (no)source RPM:\n%s", err.output)
            raise
        else:
            LOGGER.debug(result.stdout)

        srpms_dir = os.path.join(workdir, "SRPMS")
        srpms = [f for f in os.listdir(srpms_dir) if SRPM_RE.search(f)]
        assert len(srpms) == 1, "We expect 1 .(no)src.rpm, but we found: {!r}".format(srpms)
        srpm_path = os.path.join(srpms_dir, srpms[0])

        # CLEAN UP WORKDIR
        name_prefix = ""
        if hasattr(distgit, 'chroots'):
            name_prefix = "-".join(distgit.chroots) + "-"

        final_moved_out_srpm = os.path.join(tmpdir, name_prefix + srpms[0])
        shutil.move(srpm_path, final_moved_out_srpm)
        LOGGER.info("Built (no)source RPM: %r from %r", final_moved_out_srpm, distgit.ref_info())
        shutil.rmtree(workdir)

        return final_moved_out_srpm

    def make_srpms(self, tmpdir):
        """
        Build SRPM and if any distgit_overrides are configured build SRPMs for them as well.

        :param str tmpdir: Temporary directory to work in
        """
        assert self.cloned
        LOGGER.info("Building (no)source RPM for component {}".format(self.name))
        if self.distgit:
            spec_git = self.distgit
            patches = self.distgit.patches
        else:
            spec_git = self.git
            patches = PatchesAction.keep

        # Build default srpm
        self.srpm = self._make_srpm(tmpdir, spec_git, patches)
        # Build distgit_overrides srpms
        for distgit_override in self.distgit_overrides:
            distgit_override.srpm = self._make_srpm(tmpdir, distgit_override, distgit_override.patches)

        return self.srpm
