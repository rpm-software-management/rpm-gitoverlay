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

import configparser
import os
import shutil
import subprocess
import tempfile
from nose import tools
from rgo.schema import GitSchema, DistGitSchema

class TestGit(object):
    def setUp(self):
        self._bare = tempfile.mkdtemp(suffix=".git")
        subprocess.run(["git", "init", "--bare", self._bare], check=True)
        self._repo = tempfile.mkdtemp()
        gitconfig = configparser.ConfigParser(interpolation=None)
        gitconfig.optionxform = str
        gitconfig["user"] = {"email": "rpm-gitoverlay@example.com", "name": "RPM-gitoverlay"}
        self._cwd = os.path.join(self._repo, "repo")
        with open(os.path.join(self._repo, ".gitconfig"), "w") as fd:
            gitconfig.write(fd)
        self._old_environ = dict(os.environ)
        os.environ["HOME"] = self._repo

    def teardown(self):
        os.environ.clear()
        os.environ.update(self._old_environ)
        shutil.rmtree(self._bare)
        shutil.rmtree(self._repo)

    def commit(self, msg):
        subprocess.run(["git", "commit", "--allow-empty", "-m", msg], check=True, cwd=self._cwd)

    def tag(self, name):
        subprocess.run(["git", "tag", name], check=True, cwd=self._cwd)

    def test_latest_tag(self):
        results = GitSchema().load({"src": self._bare, "latest-tag": True})
        results.clone(self._cwd)
        self.commit("test")
        tools.eq_(results.ref, None)
        self.tag("0.1")
        tools.eq_(results.ref, "0.1")
        self.commit("test")
        tools.eq_(results.ref, "0.1")

    def test_describe(self):
        results = GitSchema().load({"src": self._bare})
        repo = results
        repo.clone(self._cwd)

        # no tags, plain commit
        self.commit("no tags")
        sha = repo.rev_parse("HEAD", short=True)
        ver, rel = repo.describe()
        tools.eq_(ver, "0")
        tools.assert_regexp_matches(rel, R"0\.[0-9]{{14}}\.1\.g{!s}".format(sha))

        # tag
        self.tag("1.9")
        ver, rel = repo.describe()
        tools.eq_(ver, "1.9")
        tools.eq_(rel, "1")

        # commits after tag
        self.commit("test")
        self.commit("test")
        self.commit("test")
        sha = repo.rev_parse("HEAD", short=True)
        ver, rel = repo.describe()
        tools.eq_(ver, "1.9")
        tools.assert_regexp_matches(rel, R"[0-9]{{14}}\.3\.g{!s}".format(sha))

        # commits after tag, spec has a higher version, version_from="git"
        ver, rel = repo.describe(spec_version="2.0", version_from="git")
        tools.eq_(ver, "1.9")
        tools.assert_regexp_matches(rel, R"[0-9]{{14}}\.3\.g{!s}".format(sha))

        # commits after tag, spec has a higher version, version_from="spec"
        ver, rel = repo.describe(spec_version="2.0", version_from="spec")
        tools.eq_(ver, "2.0")
        tools.assert_regexp_matches(rel, R"0\.[0-9]{{14}}\.1\.9\+3\.g{!s}".format(sha))

        # commits after tag, spec has a lower version, version_from="git"
        ver, rel = repo.describe(spec_version="1.0", version_from="git")
        tools.eq_(ver, "1.9")
        tools.assert_regexp_matches(rel, R"[0-9]{{14}}\.3\.g{!s}".format(sha))

        # commits after tag, spec has a lower version, version_from="spec"
        ver, rel = repo.describe(spec_version="1.0", version_from="spec")
        tools.eq_(ver, "1.0")
        tools.assert_regexp_matches(rel, R"[0-9]{{14}}\.1\.9\+3\.g{!s}".format(sha))

        # prefixes
        self.commit("v-prefix")
        self.tag("v0.2")
        tools.eq_(repo.describe(), ("0.2", "1"))
        self.commit("GNOME-style (upper)")
        self.tag("GNOME_BUILDER_3_21_1")
        tools.eq_(repo.describe("gnome-builder"), ("3.21.1", "1"))
        self.commit("GNOME-style (lower)")
        self.tag("libhif_0_7_0")
        tools.eq_(repo.describe("libhif"), ("0.7.0", "1"))
