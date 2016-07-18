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

import glob
import os
import subprocess
import tempfile
from .. import LOGGER

class RpmBuilder(object):
    """Build RPM(s) using rpmbuild."""

    def build(self, srpm):
        """Build RPM(s) from SRPM.
        :param str srpm: Path to .src.rpm to build
        :return: Path to RPM(s)
        :rtype: list
        """
        tmpdir = tempfile.mkdtemp(prefix="rgo", suffix="-rpmbuild")
        try:
            proc = subprocess.run(["rpmbuild", "--rebuild", srpm,
                                   "--define", "_topdir {!s}".format(tmpdir)],
                                  check=True, universal_newlines=True,
                                  stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        except subprocess.CalledProcessError as err:
            LOGGER.critical("Failed to build package(s) from SRPM:\n%s", err.output)
            raise
        else:
            LOGGER.debug(proc.stdout)
        rpms = glob.glob(os.path.join(tmpdir, "RPMS", "*", "*.rpm"))
        assert len(rpms) > 0, "We expect at least one .rpm, but we found 0"
        LOGGER.info("Built package(s) from %r: %r", srpm, rpms)
        return rpms
