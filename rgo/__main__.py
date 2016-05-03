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

import argparse
import logging
import os
import tempfile

import yaml

from .utils import Component, try_prepare
from .builders import CoprBuilder

def main(args=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("-d", "--debug", help="Enable debug output",
                        action="store_true")
    parser.add_argument("--owner", help="COPR project owner",
                        required=True)
    parser.add_argument("--project", help="COPR project name")
    parser.add_argument("--no-prep", help="Don't try %%prep section",
                        dest="prep", action="store_false")
    parser.add_argument("overlay", help="Path to overlay directory with overlay.yml file")
    args = parser.parse_args()

    if args.debug:
        logging.basicConfig(level=logging.DEBUG)

    if not os.path.isdir(args.overlay):
        raise Exception("{} is not a directory".format(args.overlay))

    _ovl = os.path.join(args.overlay, "overlay.yml")
    if not os.path.isfile(_ovl):
        raise Exception("{} is not a file".format(_ovl))

    with open(_ovl, "r") as yml:
        ovl = yaml.load(yml)
    components = [Component(c) for c in ovl["components"]]

    with tempfile.TemporaryDirectory(prefix="rpm-gitoverlay") as tmp:
        for c in components:
            c.clone(tmp)

        srpms = [c.build_srpm(tmp) for c in components]
        if args.prep:
            for srpm in srpms:
                try_prepare(srpm)

        builder = CoprBuilder()
        project = builder.mkproject(args.owner, args.project)
        rpms = []
        for srpm in srpms:
            rpms.extend(builder.build_from_srpm(project, srpm))

    print("Built following RPMs:\n{}".format("\n".join(rpms)))

if __name__ == "__main__":
    main()
