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
import contextlib
import logging
import os
import shutil
import sys
import tempfile
import warnings
import yaml
from . import LOGGER, schema, utils

@contextlib.contextmanager
def set_env(**environ):
    """
    Temporarily set the process environment variables.

    :param dict environ: Environment variables to set
    """
    old_environ = dict(os.environ)
    os.environ.update(environ)
    try:
        yield
    finally:
        os.environ.clear()
        os.environ.update(old_environ)

def setup_logger(loglevel=None):
    if loglevel:
        LOGGER.setLevel(getattr(logging, loglevel))
    handler = logging.StreamHandler()
    formatter = logging.Formatter("{asctime!s}:{levelname!s}: {message!s}", style="{")
    handler.setFormatter(formatter)
    LOGGER.addHandler(handler)

def load_overlay(json):
    return schema.OverlaySchema().load(json)

def add_build_actions(parser):
    chroot_parser = argparse.ArgumentParser(add_help=False)
    chroot_parser.add_argument("--chroot", help="Chroot to build for")

    rpm_parser = argparse.ArgumentParser(add_help=False)
    builder = rpm_parser.add_subparsers(help="Builder", dest="builder")
    builder.required = True
    builder.add_parser("rpmbuild", help="Build using rpmbuild")
    copr = builder.add_parser("copr", help="Build using COPR", parents=[chroot_parser])
    copr.add_argument("--owner", help="COPR project owner", required=True)
    copr.add_argument("--project", help="COPR project name")
    copr.add_argument(
        "--no-wait",
        help="Don't wait for the builds to finish (doesn't output built RPMs",
        action="store_true"
    )

    build_action = parser.add_subparsers(dest="build_action")
    build_action.add_parser("srpm", help="Build SRPM(s)")
    build_action.add_parser("rpm", help="Build RPM(s)", parents=[rpm_parser])
    build_action.required = True

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--log", help="Log level", default="INFO",
                        choices=("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"))
    parser.add_argument("--gitdir", default=os.path.join(os.getcwd(), ".rpm-gitoverlay"),
                        help="Directory with git repositories")
    parser.add_argument("-o", "--output", help="Output file for list of (S)RPMs")
    builder_type = parser.add_subparsers(help="What to build", dest="builder_type")
    pkg_builder = builder_type.add_parser("build-package",
                                          help="Build single package from git repo")
    pkg_builder.add_argument("--freeze", help="Build from specified commit")
    pkg_builder.add_argument("--branch", help="Build from specified branch")
    pkg_builder.add_argument("--latest-tag", help="Build from latest tag", action="store_true")
    pkg_builder.add_argument("-n", "--name", help="Package name", required=True)
    pkg_builder.add_argument("--spec-path", help="Path to spec file")
    ovl_builder = builder_type.add_parser("build-overlay",
                                          help="Build overlay based on overlay.yml")
    ovl_builder.add_argument("-s", "--source", default=os.getcwd(),
                             help="Directory where overlay.yml is located")
    builder_type.required = True
    add_build_actions(pkg_builder)
    add_build_actions(ovl_builder)

    args = parser.parse_args()
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
        if args.spec_path:
            component["git"]["spec-path"] = args.spec_path
        ovl = load_overlay({"components": [component]})
    elif args.builder_type == "build-overlay":
        args.source = os.path.abspath(args.source)
        yml = os.path.join(args.source, "overlay.yml")
        if not os.path.isfile(yml):
            print("{!s} is not accessible or not a file".format(yml), file=sys.stderr)
            sys.exit(1)
        with open(yml, "r") as _yml:
            ovl = load_overlay(yaml.safe_load(_yml))
        if args.build_action == "rpm" and args.builder == "rpmbuild" and len(ovl.components) > 1:
            warnings.warn("If there is dependencies between components, "
                          "rpmbuild builder can't handle it properly")
        with open(os.path.join(args.gitdir, ".gitconfig"), "w") as fd:
            ovl.aliases.gitconfig.write(fd)
    else:
        shutil.rmtree(args.gitdir)
        raise NotImplementedError

    with set_env(HOME=args.gitdir):
        for component in ovl.components:
            component.clone(args.gitdir)

    tmpdir = tempfile.mkdtemp(prefix="rgo", suffix="-build")
    for component in ovl.components:
        # Build SRPMs
        component.make_srpm(tmpdir)
        utils.try_prep(component.srpm)

    if args.build_action == "srpm":
        out = [c.srpm for c in ovl.components]
    elif args.build_action == "rpm":
        out = []
        # Build RPMs
        if args.builder == "copr":
            from rgo.builders.copr import CoprBuilder
            builder = CoprBuilder(args.owner, args.project, args.chroot)
            builder.build_components(ovl.components)

            if not args.no_wait:
                out = builder.wait_for_results()
        elif args.builder == "rpmbuild":
            from rgo.builders.rpmbuild import RpmBuilder
            builder = RpmBuilder()
            for component in ovl.components:
                out.extend(builder.build(component.srpm))
                # We don't care about SRPM anymore
                os.remove(component.srpm)
        else:
            shutil.rmtree(tmpdir)
            raise NotImplementedError

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
