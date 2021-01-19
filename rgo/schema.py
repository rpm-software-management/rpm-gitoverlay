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

# pylint: disable=too-few-public-methods,no-self-use

from marshmallow import Schema, post_load, validates_schema, ValidationError
from marshmallow.fields import String, Boolean, Nested, List
from marshmallow_enum import EnumField as Enum
from . import alias, git, component, overlay

class AliasSchema(Schema):
    name = String(required=True)
    url = String(required=True)

    class Meta:
        strict = True

    @validates_schema(pass_many=True)
    def validate_aliases(self, data, many, **kwargs):
        if not many:
            return
        names = [x["name"] for x in data]
        if len(names) != len(set(names)):
            raise ValidationError("Duplicates found", "name")

    @post_load(pass_many=True)
    def make_object(self, data, many, **kwargs):
        if many:
            return alias.Aliases(data)
        else:
            return alias.Alias(**data)

class GitSchema(Schema):
    src = String(required=True)
    freeze = String()
    branch = String()
    latest_tag = Boolean(data_key="latest-tag")
    spec_path = String(data_key="spec-path")

    class Meta:
        strict = True

    @validates_schema
    def validate_options(self, data, **kwargs):
        if "freeze" in data and "branch" in data:
            raise ValidationError("Only one of 'freeze'/'branch' must be specified")
        if "freeze" in data and "latest_tag" in data:
            raise ValidationError("Only one of 'freeze'/'latest-tag' must be specified")

    @post_load
    def make_object(self, data, **kwargs):
        return git.Git(**data)

class DistGitSchema(GitSchema):
    patches = Enum(git.PatchesAction, by_value=True)
    type = Enum(git.DistGitType, by_value=True)

    class Meta:
        strict = True
        exclude = ("latest_tag", "spec_path")

    @post_load
    def make_object(self, data, **kwargs):
        if "type" in data:
            data["type_"] = data.pop("type")
        return git.DistGit(**data)

class ComponentSchema(Schema):
    name = String(required=True)
    git = Nested(GitSchema)
    distgit = Nested(DistGitSchema)
    requires = List(String())

    class Meta:
        strict = True

    @validates_schema
    def validate_parameters(self, data, **kwargs):
        if "git" not in data and "distgit" not in data:
            raise ValidationError("At least one of 'git' or 'distgit' must be specified")

    @post_load
    def make_object(self, data, **kwargs):
        return component.Component(**data)

class OverlaySchema(Schema):
    aliases = Nested(AliasSchema, many=True)
    components = Nested(ComponentSchema, many=True, required=True)

    class Meta:
        strict = True

    @post_load
    def make_object(self, data, **kwargs):
        return overlay.Overlay(**data)
