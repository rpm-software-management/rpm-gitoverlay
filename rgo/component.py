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
from . import LOGGER, utils
from .git import PatchesAction

SRPM_RE = re.compile(r".+\.(?:no)?src\.rpm")

class Component(object):
    def __init__(self, name, git=None, distgit=None):
        """
        :param str name: Name of component
        :param rgo.git.Git: Git repository
        :param rgo.git.DistGit: Dist-Git repository
        """
        assert git or distgit
        self.name = name
        self.git = git
        self.distgit = distgit
        self.cloned = False

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
        self.cloned = True

    def make_srpm(self, cwd):
        """
        Build SRPM.

        :param str cwd: Working directory (for spec, sources)
        """
        assert self.cloned
        import rpm
        if self.distgit:
            spec = os.path.join(self.distgit.cwd, "{!s}.spec".format(self.name))
            patches = self.distgit.patches
        else:
            spec = os.path.join(self.git.cwd, self.git.spec_path or "{!s}.spec".format(self.name))
            patches = PatchesAction.keep

        rpmspec = rpm.spec(spec)
        _spec_path = os.path.join(cwd,
                                  "{!s}.spec".format(rpmspec.sourceHeader["Name"].decode("utf-8")))
        if self.git:
            # Get version and release
            version, release = self.git.describe(self.name)

            # If spec is located in upstream it's possible that version can be changed
            # which means we also should align it here
            if not self.distgit:
                _version = rpmspec.sourceHeader["Version"].decode("utf-8")
                LOGGER.debug("Version in upstream spec file: %r", _version)
                if rpm.labelCompare((None, _version, None), (None, version, None)) == 1:
                    # Version in spec > than from git tags
                    LOGGER.debug("Setting version from upstream spec file")
                    version = _version
                    # FIXME: Add prefix 0. to indicate that it was not released yet
                    # There are no reliable way to get in which commit version was set
                    # except iterating over commits
                    release = "0.{!s}".format(release)

            # Prepare archive
            if release == "1":
                # tagged version, no need to add useless numbers
                nvr = "{!s}-{!s}".format(self.name, version)
            else:
                nvr = "{!s}-{!s}-{!s}".format(self.name, version, release)
            archive = os.path.join(cwd, "{!s}.tar.xz".format(nvr))
            LOGGER.debug("Preparing archive %r", archive)
            proc = subprocess.run(["git", "archive", "--prefix={!s}/".format(nvr),
                                   "--format=tar", self.git.ref],
                                  cwd=self.git.cwd, check=True,
                                  stdout=subprocess.PIPE)
            with open(archive, "w") as f_archive:
                subprocess.run(["xz", "-z", "--threads=0", "-"],
                               check=True, input=proc.stdout, stdout=f_archive)

            # Prepare new spec
            with open(_spec_path, "w") as specfile:
                prepared = "{!s}\n{!s}".format(
                    utils.prepare_spec(spec, version, release, nvr, patches),
                    utils.generate_changelog(self.git.timestamp, version, release))
                specfile.write(prepared)
        else:
            # Just copy spec from distgit
            shutil.copy2(spec, _spec_path)
        spec = _spec_path

        _sources = []
        for src, _, src_type in rpm.spec(spec).sources:
            if src_type == rpm.RPMBUILD_ISPATCH:
                if patches == PatchesAction.keep:
                    _sources.append(src)
            elif src_type == rpm.RPMBUILD_ISSOURCE:
                # src in fact is url, but we need filename. We don't want to get
                # Content-Disposition from HTTP headers, because link could be not
                # available anymore or broken.
                src = os.path.basename(src)
                if self.git and src == os.path.basename(archive):
                    # Skip sources which are just built
                    continue
                _sources.append(src)
        if _sources and not self.distgit:
            raise NotImplementedError("Patches/Sources are applied in upstream")
        # Copy sources/patches from distgit
        for source in _sources:
            shutil.copy2(os.path.join(self.distgit.cwd, source),
                         os.path.join(cwd, source))

        # Build .(no)src.rpm
        try:
            result = subprocess.run(["rpmbuild", "-bs", _spec_path, "--nodeps",
                                     "--define", "_topdir {!s}".format(cwd),
                                     "--define", "_sourcedir {!s}".format(cwd)],
                                    check=True, universal_newlines=True,
                                    stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        except subprocess.CalledProcessError as err:
            LOGGER.critical("Failed to build (no)source RPM:\n%s", err.output)
            raise
        else:
            LOGGER.debug(result.stdout)
        srpms_dir = os.path.join(cwd, "SRPMS")
        srpms = [f for f in os.listdir(srpms_dir) if SRPM_RE.search(f)]
        assert len(srpms) == 1, "We expect 1 .(no)src.rpm, but we found: {!r}".format(srpms)
        srpm = os.path.join(srpms_dir, srpms[0])
        LOGGER.info("Built (no)source RPM: %r", srpm)
        return srpm
