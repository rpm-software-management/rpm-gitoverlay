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

import collections
import configparser

__all__ = ["Alias", "Aliases"]

class Alias(object):
    def __init__(self, name, url):
        self.name = name
        self.url = url

    def __repr__(self): # pragma: no cover
        return "<Alias {0.name!r}: {0.url!r}>".format(self)

class Aliases(collections.abc.Sequence):
    def __init__(self, aliases):
        self.aliases = [Alias(**alias) for alias in aliases]

    def __repr__(self):
        return "<Aliases: {!r}>".format(self.aliases)

    def __getitem__(self, key):
        if isinstance(key, str):
            try:
                return next(alias for alias in self.aliases if alias.name == key)
            except StopIteration:
                raise KeyError(key)
        return self.aliases[key]

    def __len__(self):
        return len(self.aliases)

    def __iter__(self):
        for alias in self.aliases:
            yield alias

    def __contains__(self, key):
        if isinstance(key, str):
            try:
                self[key] # pylint: disable=pointless-statement
                return True
            except KeyError:
                return False
        return key in self.aliases

    @property
    def gitconfig(self):
        escape = lambda v: v.replace('"', '\"').replace("\\", "\\\\")
        conf = configparser.ConfigParser(interpolation=None)
        conf.optionxform = str
        for alias in self:
            section = 'url "{!s}"'.format(escape(alias.url))
            conf[section] = {"insteadOf": '"{!s}:"'.format(escape(alias.name))}
        return conf
