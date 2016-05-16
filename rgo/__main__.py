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
import sys
import tempfile

import yaml

from . import logger, utils
from .builders import CoprBuilder

def setup_logger(loglevel):
    logger.setLevel(getattr(logging, loglevel.upper()))
    handler = logging.StreamHandler()
    formatter = logging.Formatter("{asctime!s}:{levelname!s}: {message!s}", style="{")
    handler.setFormatter(formatter)
    logger.addHandler(handler)

def fatal(msg):
    print(msg, file=sys.stderr)
    sys.exit(1)

def dump_ovl(ovl, f):
    with open(f, "w") as yml:
        yml.write(yaml.dump(ovl))

def load_ovl(f):
    with open(f, "r") as yml:
        ovl = yaml.load(yml)
    if not isinstance(ovl, utils.Overlay):
        fatal("{!f} doesn't looks correctly auto-generated")
    return ovl

def main(args=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--log", help="Log level",
                        choices=("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"),
                        default="WARNING")
    action = parser.add_subparsers(help="Action", dest="action")
    action.required = True
    action.add_parser("resolve", help="Clone repos, do checkout, etc.")
    build = action.add_parser("build", help="Build")
    build.add_argument("-o", "--output", help="Output file for list of (S)RPMs")
    build_action = build.add_subparsers(help="What to build", dest="build_action")
    build_action.required = True
    srpm = build_action.add_parser("srpm", help="Build SRPMs")
    rpm = build_action.add_parser("rpm", help="Build RPMs")
    builder = rpm.add_subparsers(help="Builder", dest="builder")
    builder.required = True
    copr = builder.add_parser("copr", help="Build using COPR")
    copr.add_argument("--owner", help="COPR project owner", required=True)
    copr.add_argument("--project", help="COPR project name")

    args = parser.parse_args()
    setup_logger(args.log)

    if not os.path.isfile("overlay.yml"):
        fatal("overlay.yml in current working directory doesn't exist")
    with open("overlay.yml") as yml:
        _ovl = yaml.safe_load(yml)
    ovl = utils.Overlay(_ovl)

    f_ovl = os.path.join(ovl.cwd_src, "overlay.yml")
    if args.action == "resolve":
        if os.path.isdir(ovl.cwd_src):
            fatal("Source directory {!r} already exists".format(ovl.cwd_src))
        os.makedirs(ovl.cwd_src)
        for component in ovl.components:
            component.resolve()
        dump_ovl(ovl, f_ovl)
    elif args.action == "build":
        if not os.path.isfile(f_ovl):
            fatal("Please run 'resolve' first")
        ovl = load_ovl(f_ovl)
        tmpdir = tempfile.mkdtemp(prefix="rpm-gitoverlay", suffix="-build")
        srpms = {}
        for component in ovl.components:
            srpm = component.build_srpm(tmpdir)
            utils.try_prep(srpm)
            srpms[component] = srpm
        if args.build_action == "srpm":
            out = srpms.values()
        elif args.build_action == "rpm":
            out = []
            if args.builder == "copr":
                builder = CoprBuilder()
                project = builder.mkproject(args.owner, args.project)
                logger.debug("Project URL: %r", builder.get_project_url(project))
                for srpm in srpms.values():
                    # TODO: add support for multiple builds at the same time
                    out.extend(builder.build_from_srpm(project, srpm))

        if args.output:
            with open(args.output, "w") as f_out:
                f_out.writelines("{!s}\n".format(l) for l in out)
        else:
            print("\n".join(out))

if __name__ == "__main__":
    main()
