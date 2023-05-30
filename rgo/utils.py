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


import re
import subprocess
import tempfile
from datetime import datetime

import rpm

from . import LOGGER
from .git import PatchesAction


def try_prep(srpm):
    """Try %prep on .src.rpm.
    :param str srpm: Path to src.rpm
    :raises subprocess.CalledProcessError: if something fails
    """
    LOGGER.debug("Trying to run %%prep on: %r", srpm)
    with tempfile.TemporaryDirectory(prefix="rgo", suffix="-prep") as tmp:
        try:
            proc = subprocess.run(["rpmbuild", "-rp", srpm, "--nodeps",
                                   "--define", "_topdir {}".format(tmp)],
                                  check=True, universal_newlines=True,
                                  stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        except subprocess.CalledProcessError as err:
            LOGGER.critical("Failed to run %%prep on: %r\n%s", srpm, err.output)
            raise
        else:
            LOGGER.debug(proc.stdout)


def generate_changelog(date, version, release, changelog):
    """Generate dumb changelog.
    :param float timestamp: Date of change
    :param str version: Version
    :param str release: Release
    :return: Changelog section
    :rtype: str
    """
    date = datetime.fromtimestamp(date).strftime("%a %b %d %Y")
    out = []
    out.append("%changelog")
    out.append("* {date} rpm-gitoverlay - {version}-{release}".format(
        date=date, version=version, release=release))
    if changelog:
        out += changelog
    else:
        # generate at least one changelog message to avoid rpmbuild errors
        out.append("- Built using rpm-gitoverlay")
    return "\n".join(out)


def prepare_spec(spec, version, release, prefix, patches):
    """Modify spec according our needs.
    :param str spec: Path to RPM spec
    :param str version: Version
    :param str release: Release
    :param str prefix: Archive prefix
    :param rgo.git.PatchesAction patches: What to do with patches
    :return: Patches RPM spec
    :rtype: str
    """
    rpmspec = rpm.spec(spec)

    # TODO: currently we don't support multiple sources
    if len([x for _, _, x in rpmspec.sources if x == rpm.RPMBUILD_ISSOURCE]) > 1:
        raise NotImplementedError

    patches_to_drop = []
    if patches == PatchesAction.drop:
        for source in rpmspec.sources:
            if source[2] == rpm.RPMBUILD_ISPATCH:
                patches_to_drop.append(source[0])

    with open(spec, "r") as specfile:
        _spec = specfile.readlines()

    out = []
    source_tag_re = re.compile(r"^Source(\d*):")
    patch_apply_re = re.compile(r"^%patch\d+")
    for line in _spec:
        line = line.rstrip()
        if line.startswith("Version:"):
            line = "Version: {!s}".format(version)
        elif line.startswith("Release:"):
            line = "Release: {!s}%{{?dist}}".format(release)
        elif line.startswith("Source"):
            match = source_tag_re.match(line)
            if match:
                archive = "{!s}.tar.xz".format(prefix)
                if not match.group(1):
                    line = "Source: {!s}".format(archive)
                else:
                    line = "Source{:d}: {!s}".format(int(match.group(1)), archive)
        elif line.startswith(("%setup", "%autosetup")):
            line = "{!s} -n {!s}".format(line, prefix)
        elif line.startswith("%autopatch") or line.startswith("%patchlist"):
            if patches == PatchesAction.drop:
                continue
        elif line.startswith("%patch"):
            match = patch_apply_re.match(line)
            if match and patches == PatchesAction.drop:
                continue
        elif line == "%changelog":
            # Wipe out changelog
            break
        # drop unwanted patch tags
        drop_line = False
        for p in patches_to_drop:
            if p in line:
                drop_line = True
                break
        if drop_line:
            break
        out.append(line)


    return "\n".join(out)


def remove_prefixes(text, prefixes, ignore_case=False):
    """
    Strip prefix from text.
    :param str text: Text
    :param list prefixes: Prefixes to strip
    :param bool ignore_case: Make the prefix match case-insensitive
    """
    assert isinstance(prefixes, (list, tuple))

    for prefix in prefixes:
        if ignore_case:
            if text.lower().startswith(prefix.lower()):
                return text[len(prefix):]
        else:
            if text.startswith(prefix):
                return text[len(prefix):]

    return text
