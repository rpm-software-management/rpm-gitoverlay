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
import tempfile

import rpm

from . import logger

class PatchesPolicy(enum.Enum):
    keep = "keep"
    drop = "drop"

class DistGitType(enum.Enum):
    dist_git = "dist-git"
    git_lfs = "git-lfs"

def _require_key(node, key):
    """
    :param dict node: Node
    :param str key: Key
    :return: Value for the key
    :raises KeyError: if node doesn't contain key
    """
    if key not in node:
        raise KeyError("Missing required key: {!r}".format(key))
    return node.pop(key)

def _ensure_any(node, keys):
    """
    :param dict node: Node
    :param list keys: Keys
    :raises KeyError: if node doesn't contain at least 1 of keys
    """
    if not any(k in node for k in keys):
        raise KeyError("At least one of keys is required: {}".format(", ".join(keys)))

def _ensure_one(node, keys):
    """
    :param dict node: Node
    :param list keys: Keys
    :raises KeyError: if node contains less/more than 1 of keys
    """
    specified = [k for k in keys if k in node]
    if len(specified) > 1:
        _specified = (repr(k) for k in specified)
        raise KeyError("Only one of keys should be used: {}".format(", ".join(specified)))

def _ensure_empty(node):
    """
    :param dict node: Node
    :raises KeyError: if node is not empty
    """
    if node:
        keys = ["{!r}".format(k) for k in node]
        raise KeyError("Given extra keys: {}".format(", ".join(keys)))

def _gen_changelog(version, release):
    """
    Generate dumb changelog.

    :param str version: Version
    :param str release: Release
    :return: Changelog entry
    :rtype: str
    """
    out = []
    out.append("%changelog")
    out.append("* {date} rpm-gitoverlay - {version}-{release}".format(
        date=datetime.now().strftime("%a %b %d %Y"),
        version=version, release=release))
    out.append("- Built using rpm-gitoverlay")
    return "\n".join(out)

def _prepare_spec(spec, version, release, prefix, patches):
    """
    Do some magic on spec.

    :param str spec: Path to RPM spec
    :param str version: Version
    :param str release: Release
    :param str prefix: Archive prefix
    :param rgo.utils.PatchesPolicy patches: Patches policy
    :return: Patched RPM spec
    :rtype: str
    """
    rpmspec = rpm.spec(spec)

    # TODO: currently we don't support multiple sources
    if len([x for _, _, x in rpmspec.sources if x == rpm.RPMBUILD_ISSOURCE]) > 1:
        raise NotImplementedError

    with open(spec, "r") as specfile:
        _spec = specfile.readlines()

    out = []
    patch_tag_re = re.compile(r"^Patch\d+:")
    source_tag_re = re.compile(r"^Source(\d*):")
    patch_apply_re = re.compile(r"^%patch\d+")
    for line in _spec:
        line = line.rstrip()
        if line.startswith("Version:"):
            line = "Version: {}".format(version)
        elif line.startswith("Release:"):
            line = "Release: {}%{{?dist}}".format(release)
        elif line.startswith("Patch"):
            match = patch_tag_re.match(line)
            if match and patches == PatchesPolicy.drop:
                continue
        elif line.startswith("Source"):
            match = source_tag_re.match(line)
            if match:
                archive = "{}.tar.xz".format(prefix)
                if not match.group(1):
                    line = "Source: {}".format(archive)
                else:
                    line = "Source{:d}: {}".format(int(match.group(1)), archive)
        elif line.startswith(("%setup", "%autosetup")):
            line = "{} -n {}".format(line, prefix)
        elif line.startswith("%patch"):
            match = patch_apply_re.match(line)
            if match and patches == PatchesPolicy.drop:
                continue
        elif line.startswith("%autopatch"):
            if patches == PatchesPolicy.drop:
                continue
        elif line == "%changelog":
            # Wipe out changelog
            break
        out.append(line)

    out.extend(_gen_changelog(version, release).split("\n"))
    return "\n".join(out)

def try_prep(srpm):
    """
    Try %prep on .src.rpm.

    :param str srpm: Path to src.rpm
    :raises subprocess.CalledProcessError: if something fails
    """
    logger.debug("Trying to run %%prep on: %r", srpm)
    with tempfile.TemporaryDirectory(prefix="rpm-gitoverlay", suffix="-prep") as tmp:
        subprocess.run(["rpmbuild", "-rp", srpm, "--nodeps",
                        "--define", "_builddir {}".format(tmp)],
                       check=True)

class Alias(object):
    def __init__(self, node):
        self.name = _require_key(node, "name")
        self.url = _require_key(node, "url")
        _ensure_empty(node)

    def __repr__(self):
        return "<Alias {!r}: {!r}>".format(self.name, self.url)

class Git(object):
    def __init__(self, component, node):
        self.component = component
        self._suffix = "-git"
        self.git = None

        self.src = _require_key(node, "src")
        _ensure_one(node, ["freeze", "branch"])
        self.freeze = node.pop("freeze", None)
        self.branch = node.pop("branch", None)
        _ensure_empty(node)

    def resolve(self):
        assert not self.git
        self.git = os.path.join(self.component.overlay.cwd_src,
                                "{}{}".format(self.component.name, self._suffix))
        logger.debug("Cloning %r into %r", self.src_expanded, self.git)
        subprocess.run(["git", "clone", self.src_expanded, self.git], check=True)
        if self.freeze or self.branch:
            subprocess.run(["git", "checkout", self.freeze or self.branch],
                           cwd=self.git, check=True)

    def describe(self):
        """
        Get version and release from upstream git repository.

        :return: Version and Release
        :rtype: tuple(str, str)
        """
        assert self.git
        out = subprocess.run(["git", "describe", "--tags", "--always"],
                             cwd=self.git, check=True, stdout=subprocess.PIPE)
        ver = out.stdout.decode("utf-8").rstrip().lower()
        chop = lambda v, s: v[len(s):] if v.startswith(s) else v
        ver = chop(ver, self.component.name)
        ver = chop(ver, self.component.name.replace("_", "-"))
        ver = chop(ver, "v")
        ver = chop(ver, "-")
        ver = chop(ver, "_")
        out = subprocess.run(["git", "rev-parse", "--short", "HEAD"],
                             cwd=self.git, check=True, stdout=subprocess.PIPE)
        commit = out.stdout.decode("ascii").rstrip()
        if ver.endswith("-g{}".format(commit)):
            # -X-gYYYYYYY
            tmp = ver.rsplit("-", 2)
            version = tmp[0]
            release = "{}{}".format(tmp[1], tmp[2])
        elif ver == commit:
            # YYYYYYY
            version = "0"
            # Number of commits since the beginning (as we didn't have tags yet)
            out = subprocess.run(["git", "rev-list", "--count", "HEAD"],
                                 cwd=self.git, check=True, stdout=subprocess.PIPE)
            release = "{}g{}".format(out.stdout.decode("ascii").rstrip(), commit)
        else:
            # tag
            version = ver
            release = "1"
        # often (in GNOME) tags are like GNOME_BUILDER_3_21_1
        version = version.replace("_", ".")
        # Sometimes there is "-" in version which is not allowed
        version = version.replace("-", "_")
        return (version, release)

    def __repr__(self):
        return "<Git {!r}>".format(self.src_expanded)

    @property
    def src_expanded(self):
        for alias in self.component.overlay.aliases:
            prefix = "{}:".format(alias.name)
            if self.src.startswith(prefix):
                return "{}{}".format(alias.url, self.src[len(prefix):])
        return self.src

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

    def __init__(self, component, node):
        self.patches = PatchesPolicy(node.pop("patches", "keep"))
        super(DistGit, self).__init__(component, node)
        self._suffix = "-distgit"
        _ensure_empty(node)

    def __repr__(self):
        return "<DistGit {!r}>".format(self.src_expanded)

    @property
    def distgit_type(self):
        """
        :return: DistGit type
        :rtype: rgo.utils.DistGitType
        """
        # Ugly hack, yes. But no proper way yet.
        if list(srv for srv in self.DIST_GITS if srv in self.src_expanded):
            return DistGitType("dist-git")
        else:
            return DistGitType("git-lfs")

    def resolve(self):
        super().resolve()
        self.fetch_sources()

    def fetch_sources(self):
        """Fetch sources."""
        if self.distgit_type == DistGitType("dist-git"):
            tool = next(tool for srv, tool in self.DIST_GITS.items() if srv in self.src_expanded)
            # TODO: use pyrpkg with correct site for python2 (when we will make rgo py2-compatible)
            subprocess.run([tool, "sources"], cwd=self.git, check=True)
        elif self.distgit_type == DistGitType("git-lfs"):
            subprocess.run(["git", "lfs", "fetch"], cwd=self.git, check=True)
        else:
            return NotImplemented

class Component(object):
    def __init__(self, overlay, node):
        self.overlay = overlay

        self.name = _require_key(node, "name")
        _ensure_any(node, ["git", "distgit"])
        self.git = None
        self.distgit = None
        if "git" in node:
            self.git = Git(self, node.pop("git"))
        if "distgit" in node:
            self.distgit = DistGit(self, node.pop("distgit"))
        _ensure_empty(node)

    def resolve(self):
        if self.git:
            self.git.resolve()
        if self.distgit:
            self.distgit.resolve()

    def build_srpm(self, workdir):
        """
        Build SRPM.

        :param str workdir: Working directory
        :return: Path to .src.rpm
        :rtype: str
        """
        build_cwd = os.path.join(workdir, self.name)
        os.makedirs(build_cwd)
        if self.distgit:
            spec = os.path.join(self.distgit.git, "{}.spec".format(self.name))
            patches = self.distgit.patches
        else:
            spec = os.path.join(self.git.git, "{}.spec".format(self.name))
            patches = PatchesPolicy("keep")

        _spec_path = os.path.join(build_cwd, "{}.spec".format(self.name))
        if self.git:
            # Get version and release
            version, release = self.git.describe()

            # If spec is located in upstream it's possible that version can be changed
            # which means we also should align it here.
            if not self.distgit:
                _version = rpm.spec(spec).sourceHeader["Version"].decode("utf-8")
                logger.debug("Version in upstream spec file: %r", _version)
                if rpm.labelCompare((None, _version, None), (None, version, None)) == 1:
                    # Version in spec > than from git tags
                    logger.debug("Setting version from upstream spec file")
                    version = _version
                    # FIXME: Add prefix 0. to indicate that it was not released yet
                    # There are no reliable way to get in which commit version was set
                    # except iterating over commits
                    release = "0.{}".format(release)

            # Prepare archive
            nvr = "{}-{}-{}".format(self.name, version, release)
            archive = os.path.join(build_cwd, "{}.tar.xz".format(nvr))
            logger.debug("Preparing archive %r", archive)
            out = subprocess.run(["git", "archive", "--prefix={}/".format(nvr),
                                  "--format=tar", "HEAD"],
                                 cwd=self.git.git, check=True, stdout=subprocess.PIPE)
            with open(archive, "w") as f_archive:
                subprocess.run(["xz", "-z", "--threads=0", "-"],
                               check=True, input=out.stdout, stdout=f_archive)

            # Prepare new spec
            with open(_spec_path, "w") as specfile:
                specfile.write(_prepare_spec(spec, version, release, nvr, patches))
            spec = _spec_path
        else:
            # Just copy spec file from distgit
            shutil.copy2(spec, _spec_path)

        _sources = []
        for src, _, src_type in rpm.spec(spec).sources:
            if src_type == rpm.RPMBUILD_ISPATCH:
                if patches == PatchesPolicy("keep"):
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
            shutil.copy2(os.path.join(self.distgit.git, source),
                         os.path.join(build_cwd, source))

        # Build .src.rpm
        result = subprocess.run(["rpmbuild", "-bs", _spec_path, "--nodeps",
                                 "--define", "_sourcedir {}".format(build_cwd),
                                 "--define", "_srcrpmdir {}".format(build_cwd)],
                                check=True, stdout=subprocess.PIPE)
        return re.match(r"^Wrote: (.+)$", result.stdout.decode("utf-8")).group(1)

    def __repr__(self):
        return "<Component {!r}>".format(self.name)

class Overlay(object):
    def __init__(self, yml, cwd="."):
        self.cwd = os.path.realpath(cwd)
        self.cwd_src = os.path.join(self.cwd, "src")

        self.aliases = []
        self.components = []
        self.chroot = _require_key(yml, "chroot")

        _ovl = yml.copy()

        for node in _ovl.pop("aliases", []):
            self.aliases.append(Alias(node))
        for node in _require_key(_ovl, "components"):
            self.components.append(Component(self, node))

        _ensure_empty(_ovl)

    def __str__(self):
        return "<Overlay {!r}>".format(self.cwd)
