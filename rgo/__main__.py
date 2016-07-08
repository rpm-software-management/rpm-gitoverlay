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
import os
import shutil
import sys
import tempfile
import yaml
import rgo.schema
import rgo.utils

def setup_logger(loglevel):
    import logging
    from . import LOGGER
    LOGGER.setLevel(getattr(logging, loglevel.upper()))
    handler = logging.StreamHandler()
    formatter = logging.Formatter("{asctime!s}:{levelname!s}: {message!s}", style="{")
    handler.setFormatter(formatter)
    LOGGER.addHandler(handler)

def load_overlay(json):
    return rgo.schema.OverlaySchema().load(json).data

def add_build_actions(parser):
    rpm_parser = argparse.ArgumentParser(add_help=False)
    builder = rpm_parser.add_subparsers(help="Builder", dest="builder")
    builder.required = True
    copr = builder.add_parser("copr", help="Build using COPR")
    copr.add_argument("--owner", help="COPR project owner", required=True)
    copr.add_argument("--project", help="COPR project name")

    build_action = parser.add_subparsers(dest="build_action")
    build_action.add_parser("srpm", help="Build SRPM(s)")
    rpm = build_action.add_parser("rpm", help="Build RPM(s)", parents=[rpm_parser])
    rpm.add_argument("--chroot", help="Chroot to build for", required=True)
    build_action.required = True

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--log", help="Log level",
                        choices=("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"))
    parser.add_argument("--gitdir", default=os.path.join(os.getcwd(), ".rpm-gitoverlay"),
                        help="Directory with git repositories")
    parser.add_argument("-o", "--output", help="Output file for list of (S)RPMs")
    builder_type = parser.add_subparsers(help="What to build", dest="builder_type")
    pkg_builder = builder_type.add_parser("build-package", help="Build single package from git repo")
    pkg_builder.add_argument("--freeze", help="Build from specified commit")
    pkg_builder.add_argument("--branch", help="Build from specified branch")
    pkg_builder.add_argument("--latest-tag", help="Build from latest tag", action="store_true")
    pkg_builder.add_argument("-n", "--name", help="Package name", required=True)
    ovl_builder = builder_type.add_parser("build-overlay", help="Build overlay based on overlay.yml")
    ovl_builder.add_argument("-s", "--source", default=os.getcwd(),
                             help="Directory where overlay.yml is located")
    builder_type.required = True
    add_build_actions(pkg_builder)
    add_build_actions(ovl_builder)

    args = parser.parse_args()
    if args.log:
        setup_logger(args.log)

    args.gitdir = os.path.abspath(args.gitdir)
    if not os.path.isdir(args.gitdir):
        os.mkdir(args.gitdir)

    if args.builder_type == "build-package":
        component = {"name": args.name, "git": {"src": os.getcwd()}}
        if args.freeze:
            component["git"]["freeze"] = args.freeze
        if args.branch:
            component["git"]["branch"] = args.branch
        if args.latest_tag:
            component["git"]["latest-tag"] = args.latest_tag
        ovl = load_overlay({"components": [component]})
    elif args.builder_type == "build-overlay":
        args.source = os.path.abspath(args.source)
        yml = os.path.join(args.source, "overlay.yml")
        if not os.path.isfile(yml):
            print("{!s} is not accessible or not a file".format(yml), file=sys.stderr)
            sys.exit(1)
        with open(yml, "r") as _yml:
            ovl = load_overlay(yaml.safe_load(_yml))
        with open(os.path.join(args.gitdir, ".gitconfig"), "w") as fd:
            ovl.aliases.gitconfig.write(fd)
        os.environ["HOME"] = args.gitdir
    else:
        shutil.rmtree(args.gitdir)
        raise NotImplementedError

    for component in ovl.components:
        component.clone(args.gitdir)

    tmpdir = tempfile.mkdtemp(prefix="rgo", suffix="-build")
    srpms = []
    for component in ovl.components:
        # Build SRPMs
        tmp_c = os.path.join(tmpdir, component.name)
        os.mkdir(tmp_c)
        _srpm = component.make_srpm(tmp_c)
        srpm = os.path.join(tmpdir, os.path.basename(_srpm))
        shutil.move(_srpm, srpm)
        srpms.append(srpm)
        shutil.rmtree(tmp_c)
        rgo.utils.try_prep(srpm)

    if args.build_action == "srpm":
        out = srpms
    elif args.build_action == "rpm":
        out = []
        # Build RPMs
        if args.builder == "copr":
            from rgo.builders.copr import CoprBuilder
            builder = CoprBuilder(args.owner, args.project, args.chroot or ovl.chroot)
            for srpm in srpms:
                # TODO: add support for multiple builds at the same time
                out.extend(builder.build(srpm))
                # We can always get SRPM from COPR
                os.remove(srpm)
        else:
            shutil.rmtree(tmpdir)
            raise NotImplementedError
        out = rpms
        # Everything built successfully, we can remove temp directory
        shutil.rmtree(tmpdir)
    else:
        shutil.rmtree(tmpdir)
        raise NotImplementedError

    if args.output:
        with open(args.output, "w") as f_out:
            f_out.writelines("{!s}\n".format(l) for l in out)
    else:
        print("\n".join(out))

if __name__ == "__main__":
    main()
