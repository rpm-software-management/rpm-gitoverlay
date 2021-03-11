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

import setuptools

REQUIRES = ["marshmallow", "marshmallow-enum"]

args = dict(
    name="rpm-gitoverlay",
    version="0",
    author="Igor Gnatenko",
    author_email="ignatenko@redhat.com",
    url="https://github.com/ignatenkobrain/rpm-gitoverlay",
    description="Manage an overlay repository of RPMs from upstream git",
    keywords="rpm git",
    license="GPL-3.0+",
    packages=setuptools.find_packages(),
    entry_points={
        "console_scripts": [
            "rpm-gitoverlay = rgo.__main__:main"
        ]
    },
    install_requires=["PyYAML"] + REQUIRES,
    extras_require={
        "copr": ["beautifulsoup4", "copr", "requests"]
    },
    tests_require=["nose"] + REQUIRES,
    test_suite="nose.collector",
    classifiers=[
        "Development Status :: 2 - Pre-Alpha",
        "Intended Audience :: Developers",
        "License :: OSI Approved :: GNU General Public License v3 or later (GPLv3+)",
        "Operating System :: POSIX :: Linux",
        "Programming Language :: Python",
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.6",
        "Programming Language :: Python :: 3 :: Only",
        "Topic :: Software Development :: Build Tools",
        "Topic :: Utilities",
    ])

if __name__ == "__main__":
    setuptools.setup(**args)
