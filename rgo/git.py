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


import datetime
import enum
import os
import shutil
import subprocess
from . import LOGGER

import rpm

from . import LOGGER


class PatchesAction(enum.Enum):
    keep = "keep"
    drop = "drop"

class DistGitType(enum.Enum):
    auto = "auto"
    dist_git = "dist-git"
    git_lfs = "git-lfs"
    git = "git"

class Git(object):
    def __init__(self, src, freeze=None, branch=None, latest_tag=False, spec_path=None):
        self.src = src
        self.freeze = freeze
        self.branch = branch
        self.latest_tag = latest_tag
        self.spec_path = spec_path
        self.cwd = None
        self.use_current_head = False

    def __repr__(self): # pragma: no cover
        return "<Git {!r}>".format(self.src)

    def clone(self, dest):
        """Clone repository.
        :param str dest: Path where to clone
        """
        assert os.path.isabs(dest)
        self.cwd = dest

        if os.path.isdir(dest):
            # if the git directory already exists, use its HEAD instead of checking out the configured ref
            self.use_current_head = True
            LOGGER.info("Using existing git repository: %r HEAD: %r", dest, self.ref_info())
        else:
            subprocess.run(["git", "clone", self.src, dest], check=True)

    def _latest_tag(self, ref):
        assert self.cwd
        proc = subprocess.run(["git", "describe", "--tags", "--always", "--abbrev=0", ref],
                              check=True, cwd=self.cwd, universal_newlines=True,
                              stdout=subprocess.PIPE)
        tag = proc.stdout.rstrip()
        # tag == commit in case there are no tags in this branch
        if tag != self.rev_parse(ref, short=False):
            return tag

    @property
    def ref(self):
        assert self.cwd
        if self.use_current_head:
            return "HEAD"
        if self.freeze:
            return self.freeze
        if self.latest_tag:
            return self._latest_tag(self.branch if self.branch else "HEAD")
        if self.branch:
            return self.branch
        return "HEAD"

    def ref_info(self):
        """
        Returns descriptive string in form of e.g.:
        'deadbeef (tag: 1.2.3) Pimp out the code'
        For informational purposes.
        """
        proc = subprocess.run(["git", "log", "-1", "--oneline", self.ref],
                              check=True, cwd=self.cwd, universal_newlines=True,
                              stdout=subprocess.PIPE)
        return proc.stdout.rstrip()

    @property
    def timestamp(self):
        assert self.cwd
        proc = subprocess.run(["git", "show", "-s", "--format=%ct", self.ref],
                              cwd=self.cwd, check=True, universal_newlines=True,
                              stdout=subprocess.PIPE)
        # if there is a tag here, git returns more than one line, so we just take last line
        # $ git show -s --format=%ct 0.6.22
        # tag 0.6.22
        # Tagger: Michael Schroeder <mls@suse.de>
        #
        # 0.6.22
        # 1465385134
        return float(proc.stdout.rstrip().split()[-1])

    @property
    def url(self):
        """Expanded remote URL."""
        assert self.cwd
        proc = subprocess.run(["git", "ls-remote", "--get-url"],
                              check=True, cwd=self.cwd, universal_newlines=True,
                              stdout=subprocess.PIPE)
        return proc.stdout.rstrip()

    def rev_parse(self, ref, short=False):
        assert self.cwd
        cmd = ["git", "rev-parse"]
        if short:
            cmd.append("--short")
        cmd.append(ref)
        proc = subprocess.run(cmd, check=True, cwd=self.cwd, universal_newlines=True,
                              stdout=subprocess.PIPE)
        return proc.stdout.rstrip()

    def describe(self, pkg=None, spec_version=None, version_from="git"):
        """Get version and release based on git-describe.
        :param str pkg: Package name
        :param str spec_version: Package version from the spec file
        :param str version_from: Where does the version come from: git, spec
        """
        from .utils import remove_prefixes
        assert self.cwd
        assert version_from in ("git", "spec")
        ref = self.ref

        tag, commits, hash = self.get_describe_long(ref)

        git_version = tag

        if pkg:
            # remove package name from version
            prefixes = [
                pkg + "-",
                pkg + "_",
                pkg.replace("-", "_") + "_",
            ]
            git_version = remove_prefixes(git_version, prefixes, ignore_case=True)

        # '-' is not an allowed character in RPM version
        git_version = git_version.replace("-", ".")

        # convert underscores to dots
        git_version = git_version.replace("_", ".")

        git_version = remove_prefixes(git_version, ["v"], ignore_case=True)

        # Always prefix release with 0 when building a pre-release build.
        # The release will change to 1+ when the package is built in a distro.

        # Then append a <date> prefix in YYYYMMDDhhmmss format.
        # It is important to maintain an upgrade path when a build
        # is done after a squash merge that reduces number of commits.
        date = datetime.datetime.now().strftime("%Y%m%d%H%M%S")

        if version_from == "spec" and spec_version != git_version:
            if rpm.labelCompare(spec_version, git_version) == 1:
                # pre-release, spec_version > git_version

                # we'll set version to spec_version
                # it's a pre-release, the release must be < 1
                # a plain number of commits wouldn't make much sense, that's why prepend git_version

                # Example:
                #    spec:   version=2.0, release=1
                #    git:    version=1.9; there are 3 commits after the tag
                #    result: version=2.0, release=0.YYYYMMDDhhmmss.1.9+3.gcafecafe
                version = spec_version
                release = "0.{!s}.{!s}+{!s}.g{!s}".format(date, git_version, commits, hash)

            else:
                # release + patches, spec_version < git_version (it's not <= because spec_version != git_version)

                # we'll set version to spec_version
                # there are patches on top of the release, that's why release must be > 1
                # we do not know how much the release was increased in the distro, let's start with the date which is a huge number
                # a plain number of commits wouldn't make much sense, that's why prepend git_version

                # Example:
                #    spec:   version=1.0, release=1
                #    git:    version=1.9; there are 3 commits after the tag
                #    result: version=1.0, release=YYYYMMDDhhmmss.1.9+3.gcafecafe
                version = spec_version
                release = "{!s}.{!s}+{!s}.g{!s}".format(date, git_version, commits, hash)

        elif not git_version:
            # pre-release, git version cannot be detected (no git tag)

            # we'll set version to 0
            # it's a pre-release, the release must be < 1

            # Example:
            #    spec:   doesn't matter
            #    git:    no tag; there are 3 commits under the current ref
            #    result: version=0, release=0.YYYYMMDDhhmmss.3.gcafecafe
            version = "0"
            release = "0.{!s}.{!s}.g{!s}".format(date, commits, hash)

        else:
            # release + patches

            # we'll set version to git_version
            # there are patches on top of the release, release must be > 1
            # we do not know how much the release was increased in the distro, let's start with the date which is a huge number

            # Example:
            #    spec:   doesn't matter
            #    git:    version=1.9; there are 3 commits after the tag
            #    result: version=1.9, release=YYYYMMDDhhmmss.3.gcafecafe
            version = git_version
            release = "{!s}.{!s}.g{!s}".format(date, commits, hash)

        LOGGER.info("Using version from {!s}: {!s}".format(version_from, version))

        return version, release

    def _check_output(self, cmd):
        env = dict(os.environ)
        env["LC_ALL"] = "C.UTF-8"
        return subprocess.check_output(cmd, cwd=self.cwd, encoding="utf-8", env=env).strip().splitlines()

    def get_describe_long(self, ref):
        """
        Run git describe --tags --long --allways <ref>
        Return a tuple with the following data:
          * tag: last available tag in commits <= ref
          * commits: number of commits between the tag and the ref
          * hash: hash of the ref
        """
        cmd = ["git", "describe", "--tags", "--long", "--always", ref]
        desc = self._check_output(cmd)[0].strip()

        if "-" not in desc:
            # desc contains only the hash
            tag = ""
            hash = desc

            # count all commits
            cmd = ["git", "rev-list", "--count", ref]
            commits = self._check_output(cmd)[0].strip()
            commits = int(commits)

            return tag, commits, hash

        tag, commits, hash = desc.rsplit("-", 2)

        # covert number of commits to integer
        commits = int(commits)

        # remove the 'g' prefix and keep only the hash
        hash = hash[1:]

        return tag, commits, hash

    def get_rpm_changelog(self):
        """
        Generate RPM changelog records from git history between self.ref and the last tag.
        If self.ref == last tag, generate a changelog between self.ref and the last but one tag.
        """
        # determine the latest tag name and number of commit between ref and the tag
        tag, commits, _ = self.get_describe_long(self.ref)

        if commits == 0:
            # ref is tagged, there are no commits going to the changelog
            # generating an empty changelog is not cool, let's generate a changelog between 2 tags instead
            tag, _, _ = self.get_describe_long(tag + "^")

        cmd = ["git", "log", "--pretty=format:- [%h] %s (%an)", "{0}..{1}".format(tag, self.ref)]
        changelog = self._check_output(cmd)
        return changelog


class DistGit(Git):
    """
    In general, distgit is just git repo with spec file and sources. Large files like
    upstream tarballs stored outside.

    In Fedora/CentOS is used dist-git (https://github.com/release-engineering/dist-git)
    which is gitolite + custom lookaside cache (for large files). In this case we have
    to use pyrpkg (not yet python3 compatible) or tools which are using it, e.g. fepdkg.

    It's also good idea to use git-lfs (https://git-lfs.github.com/) for this purposes.
    In this case we have to use git-lfs client (here we will use official client).
    """
    DIST_GITS = {"pkgs.fedoraproject.org": "fedpkg",
                 "pkgs.devel.redhat.com": "rhpkg"}

    def __init__(self, src, freeze=None, branch=None, spec_path=None,
                 patches=PatchesAction.keep, patches_dir="", type_=DistGitType.auto):
        """
        :param str src: URL to git repo
        :param str freeze: Commit to freeze repo on
        :param str branch: Branch to freeze repo on
        :param str spec_path: Path to specfile
        :param rgo.git.PatchesAction patches: What to do with patches
        :param str patches_dir: Path to a directory with patches from specfile
        :param rgo.git.DistGitType type_: Type of distgit
        """
        super().__init__(src, freeze=freeze, branch=branch, spec_path=spec_path)
        self.patches = patches
        self.patches_dir = patches_dir
        self.type = type_

    def __repr__(self): # pragma: no cover
        return "<DistGit {!r}>".format(self.src)

    @property
    def real_type(self):
        if self.type == DistGitType.auto:
            if len([x for x in self.DIST_GITS if x in self.url]) != 0:
                return DistGitType.dist_git
            elif shutil.which("git-lfs"):
                return DistGitType.git_lfs
            else:
                return DistGitType.git
        else:
            return self.type

    def clone(self, dest):
        super().clone(dest)
        if self.real_type == DistGitType.dist_git:
            tool = next(tool for srv, tool in self.DIST_GITS.items() if srv in self.url)
            # TODO: use pyrpkg with correct site for python2 (when we will make rgo py2-compatible)
            subprocess.run([tool, "sources"], cwd=self.cwd, check=True)
        elif self.real_type == DistGitType.git_lfs:
            subprocess.run(["git-lfs", "fetch"], cwd=self.cwd, check=True)
        elif self.real_type == DistGitType.git:
            # Everything stored in git and we already have everything
            pass


class DistGitOverride(DistGit):
    def __init__(self, src, freeze=None, branch=None, spec_path=None, chroots=None,
                 patches=PatchesAction.keep, patches_dir="", type_=DistGitType.auto):
        """
        :param str src: URL to git repo
        :param str freeze: Commit to freeze repo on
        :param str branch: Branch to freeze repo on
        :param str spec_path: Path to specfile
        :param list chroots: list of strings representing different chroots
        :param rgo.git.PatchesAction patches: What to do with patches
        :param str patches_dir: Path to a directory with patches from specfile
        :param rgo.git.DistGitType type_: Type of distgit
        """
        super().__init__(src, freeze=freeze, branch=branch, spec_path=spec_path,
                         patches=patches, patches_dir=patches_dir, type_=type_)
        if chroots is None:
            chroots = []
        self.chroots = chroots
        self.build_id = None
        self.srpm = None
        self.done = None
        self.build_proxy = None

    def __repr__(self):  # pragma: no cover
        return "<DistGitOverride {!r} for {!r}>".format(self.src, self.chroots)
