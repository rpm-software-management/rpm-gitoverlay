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

import io
from nose import tools
import marshmallow
from rgo.alias import Alias, Aliases
from rgo.schema import AliasSchema

class TestAlias(object):
    def test_gitconfig(self):
        data = [{"name": "github", "url": "git@github.com:"}]
        gitconfig = '[url "git@github.com:"]\ninsteadOf = "github:"'
        result = AliasSchema(many=True).load(data)
        with io.StringIO() as fd:
            result.data.gitconfig.write(fd)
            fd.seek(0)
            tools.eq_(fd.read().rstrip(), gitconfig)

    def test_duplicate(self):
        data = [{"name": "foo", "url": "bar"},
                {"name": "foo", "url": "baz"}]
        with tools.assert_raises(marshmallow.ValidationError) as ve:
            AliasSchema(many=True).load(data)
        tools.eq_(ve.exception.messages, {"name": ["Duplicates found"]})

    def test_many(self):
        alias = {"name": "foo", "url": "bar"}
        tools.ok_(isinstance(AliasSchema().load(alias).data, Alias))
        tools.ok_(isinstance(AliasSchema(many=True).load([alias]).data, Aliases))

    def test_builtins(self):
        data = [{"name": "foo", "url": "u1"},
                {"name": "bar", "url": "u2"}]
        results = AliasSchema(many=True).load(data)
        tools.eq_(len(results.data), 2)
        tools.ok_("foo" in results.data)
        tools.ok_("baz" not in results.data)
        tools.ok_(results.data[0] in results.data)
        tools.eq_(AliasSchema().dump(results.data["foo"]).data, data[0])
        tools.eq_(AliasSchema().dump(results.data[1]).data, data[1])
