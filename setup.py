from setuptools import setup, find_packages

setup(
    name="rpm-gitoverlay",
    version="0",
    author="Igor Gnatenko",
    author_email="ignatenko@redhat.com",
    url="https://github.com/ignatenkobrain/rpm-gitoverlay",
    description="Manage an overlay repository of RPMs from upstream git",
    keywords="rpm git",
    license="GPLv3+",
    packages=find_packages(),
    entry_points={
        "console_scripts": [
            "rpm-gitoverlay = rgo.__main__:main"
        ]
    },
    install_requires=["PyYAML"],
    setup_require=["nose"],
    extras_require={
        "copr": ["copr", "requests", "beautifulsoup4"],
    },
    test_suite="nose.collector",
    classifiers=[
        "Development Status :: 2 - Pre-Alpha",
        "Intended Audience :: Developers",
        "License :: OSI Approved :: GNU General Public License v3 or later (GPLv3+)",
        "Operating System :: POSIX :: Linux",
        "Programming Language :: Python",
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.5",
        "Programming Language :: Python :: 3 :: Only",
        "Topic :: Software Development :: Build Tools",
        "Topic :: Utilities",
    ],
)
