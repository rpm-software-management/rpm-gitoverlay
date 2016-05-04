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
import enum
import os
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile

import pygit2
import rpm

from . import logger
from .exceptions import OverlayException

# FIXME: use pygit2.write_archive(), but now it looses permissions on files
# https://github.com/libgit2/pygit2/issues/616
ARCHIVE_TYPE = "tar" # pygit2

class PatchesPolicy(enum.Enum):
    keep = 0
    drop = 1

class Component(object):
    def __init__(self, node):
        if "git" not in node and "distgit" not in node:
            raise Exception("Neither 'git' nor 'distgit' specified")
        self.name = node.pop("name")

        self.git = None
        self.branch = None
        self.distgit = None
        self.distbranch = None
        self.patches = PatchesPolicy.keep
        self.distpatches = []

        if "git" in node:
            self.git = node.pop("git")
            if "branch" in node:
                self.branch = node.pop("branch")
        else:
            if "branch" in node:
                raise Exception("'branch' specified, but 'git' is not")

        if "distgit" in node:
            distgit = node["distgit"]
            self.distgit = distgit.pop("git")
            if "branch" in distgit:
                self.distbranch = distgit.pop("branch")

            if "patches" in distgit:
                self.patches = distgit.pop("patches")
                for p in PatchesPolicy:
                    if self.patches == p.name:
                        self.patches = p
                        break
                if not isinstance(self.patches, PatchesPolicy):
                    raise Exception("Wrong patches policy: {!r}".format(self.patches))

            if self.patches == PatchesPolicy.keep:
                if "keep-patches" in distgit:
                    raise Exception("patches: keep and keep-patches at the same time")
                if "drop-patches" in distgit:
                    self.distpatches = distgit.pop("drop-patches")
            if self.patches == PatchesPolicy.drop:
                if "drop-patches" in distgit:
                    raise Exception("patches: drop and drop-patches at the same time")
                if "keep-patches" in distgit:
                    self.distpatches = distgit.pop("keep-patches")

            if not distgit:
                node.pop("distgit")

        if node:
            raise Exception("Some parameters are still in node: {!r}".format(node))

        self.repo = None
        self.distrepo = None

    def _clone_repo(self, url, cwd, suffix=None, branch=None):
        if suffix is None:
            path = os.path.join(cwd, self.name)
        else:
            path = os.path.join(cwd, "{}{}".format(self.name, suffix))
        assert not os.path.isdir(path)
        logger.info("Cloning %r into %r", url, path)
        repo = pygit2.clone_repository(url, path, checkout_branch=branch)
        logger.info("Cloning done")
        return repo

    def clone(self, workdir):
        """
        Clone component's repos.

        :param workdir: Directory to clone in
        :type workdir: str
        """
        if self.git is not None:
            assert self.repo is None
            self.repo = self._clone_repo(self.git, workdir,
                                         suffix="-git",
                                         branch=self.branch)

        if self.distgit is not None:
            assert self.distrepo is None
            self.distrepo = self._clone_repo(self.distgit, workdir,
                                             suffix="-distgit",
                                             branch=self.distbranch)

    @staticmethod
    def _get_ver_rel(repo, pkg=None):
        """
        Get version and release from upstream git repository.

        :param repo:
        :type repo: pygit2.Repository
        :param pkg: Package name (used for stripping out)
        :type pkg: str | None
        :return: Version and Release
        :rtype: tuple(str, str)
        """
        ver = repo.describe(describe_strategy=pygit2.GIT_DESCRIBE_TAGS)
        if pkg is not None and ver.startswith("{}-".format(pkg)):
            ver = ver[len(pkg) + 1:]
        if ver.startswith("v"):
            ver = ver[1:]
        short_commit = str(repo.head.target)[:7]
        if ver.endswith("-g{}".format(short_commit)):
            # -X-gYYYYYYY
            tmp = ver.rsplit("-", 2)
            version = tmp[0]
            release = "{}{}".format(tmp[1], tmp[2])
        elif ver == short_commit:
            # YYYYYYY
            version = "0"
            # Number of commits since the beginning (as we didn't had tags yet)
            _commits_num = len([x for x in repo.walk(repo.head.target)])
            release = "{}g{}".format(_commits_num, short_commit)
        else:
            version = ver
            release = "1"
        # Sometimes there is "-" in version which is not allowed
        version = version.replace("-", "_")
        return (version, release)

    @staticmethod
    def _gen_changelog(ver, rel):
        """
        Generate dumb changelog entry.

        :param ver: Version
        :type ver: str
        :param rel: Release
        :type rel: str
        :return: Changelog entry
        :rtype: str
        """
        out = []
        out.append("* {} - rpm-gitoverlay {}-{}".format(datetime.now().strftime("%a %b %d %Y"),
                                                        ver, rel))
        out.append("- Built using rpm-gitoverlay")
        return "\n".join(out)

    def _prepare_spec(self, spec, version, release, archive, directory):
        """
        Do some magic on spec file.

        :param spec: Path to RPM spec file
        :type spec: str
        :return: Spec file contents
        :rtype: str
        """
        rpmspec = rpm.spec(spec)
        # Patches to keep
        patches = {}
        _distpatches = self.distpatches.copy()
        for src, src_num, src_type in rpmspec.sources:
            if src_type == rpm.RPMBUILD_ISPATCH:
                if self.patches == PatchesPolicy.keep:
                    if src not in _distpatches:
                        logger.debug("Keeping patch: %r", src)
                        patches[src] = src_num
                    else:
                        logger.debug("Dropping patch: %r", src)
                        _distpatches.remove(src)
                elif self.patches == PatchesPolicy.drop:
                    if src in _distpatches:
                        logger.debug("Keeping patch: %r", src)
                        patches[src] = src_num
                        _distpatches.remove(src)
                    else:
                        logger.debug("Dropping patch: %r", src)
                else:
                    raise NotImplementedError
            elif src_type == rpm.RPMBUILD_ISSOURCE:
                if src_num != 0:
                    raise NotImplementedError
            else:
                raise NotImplementedError

        if _distpatches:
            _plist = " ".join(_distpatches)
            if self.patches == PatchesPolicy.drop:
                # XXX: probably we should take it from directory
                raise Exception("Patches were required to keep, but not found: {}".format(_plist))
            elif self.patches == PatchesPolicy.keep:
                logger.warning("Patches are already deleted: %s", _plist)
            else:
                raise NotImplementedError
            del _plist
            del _distpatches

        with open(spec, "r") as specfile:
            _spec = specfile.readlines()

        # Wipe out changelog
        chlog_index = _spec.index("%changelog\n")
        _spec = _spec[:chlog_index + 1]

        out = []
        # Templatify Version, Release, etc.
        patch_tag_re = re.compile(r"^Patch(\d+):")
        patch_prep_re = re.compile(r"^%patch(\d+) ")
        for line in _spec:
            line = line.rstrip()
            patch_match = patch_tag_re.match(line)
            if line.startswith("Version:"):
                line = "Version: {}".format(version)
            elif line.startswith("Release:"):
                line = "Release: {}%{{?dist}}".format(release)
            elif patch_match:
                if int(patch_match.group(1)) not in patches.values():
                    continue
            elif line.lstrip().startswith("%patch"):
                if int(patch_prep_re.match(line.lstrip()).group(1)) not in patches.values():
                    continue
            elif line.lstrip().startswith("%autopatch"):
                if not patches:
                    continue
            elif line.startswith("Source0:"):
                line = "Source0: {}".format(archive)
            elif line.startswith(("%setup", "%autosetup")):
                line = "{} -n {}".format(line, directory)
            out.append(line)

        out.extend(self._gen_changelog(version, release).split("\n"))
        return ("\n".join(out), patches.keys())

    def build_srpm(self, workdir):
        assert self.repo
        if self.distrepo is None:
            spec = os.path.join(self.repo.workdir, "{}.spec".format(self.name))
        else:
            spec = os.path.join(self.distrepo.workdir, "{}.spec".format(self.name))

        version, release = self._get_ver_rel(self.repo, self.name)
        prefix = "{}-{}-{}".format(self.name, version, release)

        # Prepare archive
        archive_prefix = "{}/".format(prefix)
        if sys.version_info.major >= 3:
            archive_ext = "tar.xz"
            archive_mode = "w:xz"
        else:
            archive_ext = "tar.gz"
            archive_mode = "w:gz"
        archive_name = "{}.{}".format(prefix, archive_ext)
        archive_path = os.path.join(workdir, archive_name)
        if ARCHIVE_TYPE == "tar":
            transform = "s,^{},{},".format(os.path.relpath(self.repo.workdir, start="/"), prefix)
            subprocess.run(["tar", "--exclude-vcs", "-caf", archive_path,
                            "--transform", transform, self.repo.workdir
                           ], check=True)
        elif ARCHIVE_TYPE == "pygit2":
            with tarfile.open(archive_path, archive_mode) as archive:
                self.repo.write_archive(self.repo[self.repo.head.target], archive,
                                        prefix=archive_prefix)
        else:
            raise NotImplementedError
        logger.info("Prepared archive with upstream sources: %s", archive_path)

        # Prepare spec
        _spec, patches = self._prepare_spec(spec,
                                            version=version,
                                            release=release,
                                            archive=archive_name,
                                            directory=archive_prefix)
        _spec_path = os.path.join(workdir, "{}.spec".format(self.name))
        with open(_spec_path, "w") as specfile:
            specfile.write(_spec)
            specfile.flush()

        # Copy patches from distgit
        for patch in patches:
            shutil.copy2(os.path.join(self.distrepo.workdir, patch),
                         os.path.join(workdir, patch))

        # Build .src.rpm
        result = subprocess.run(["rpmbuild", "-bs", _spec_path,
                                 "--define", "_sourcedir {}".format(workdir),
                                 "--define", "_srcrpmdir {}".format(workdir),
                                ], check=True, stdout=subprocess.PIPE)
        return re.match(r"^Wrote: (.+)$", result.stdout.decode("utf-8")).group(1)

    def __repr__(self):
        return "<Component {!r} ({!r})>".format(self.name, self.git)

def try_prepare(srpm):
    """
    :param srpm: Path to SRPM
    :type srpm: str
    """
    with tempfile.TemporaryDirectory(prefix="rgo-prep") as tmp:
        try:
            subprocess.run(["rpmbuild", "-rp", srpm, "--nodeps",
                            "--define", "_builddir {}".format(tmp),
                           ], check=True)
        except subprocess.CalledProcessError:
            raise OverlayException("Failed to %prep")
