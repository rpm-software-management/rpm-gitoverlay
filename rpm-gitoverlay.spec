Name:           rpm-gitoverlay
Version:        0.4
Release:        1%{?dist}
Summary:        Manage an overlay repository of RPMs from upstream git

License:        GPLv3+
URL:            https://github.com/rpm-software-management/%{name}
Source0:        %{url}/archive/%{version}/%{name}-%{version}.tar.gz

BuildRequires:  python3-devel
BuildRequires:  python3-setuptools
BuildRequires:  python3-marshmallow >= 3
BuildRequires:  python3-marshmallow-enum
BuildRequires:  rpm-python3
BuildRequires:  python3-PyYAML
BuildRequires:  git-core
Requires:       python3-marshmallow >= 3
Requires:       python3-marshmallow-enum
Requires:       rpm-python3
Requires:       python3-PyYAML
Requires:       git-core
# Archives are always in tar.xz
Requires:       /usr/bin/tar
Requires:       /usr/bin/xz
# For building SRPMs
Requires:       /usr/bin/rpmbuild
# COPR builder
Requires:       python3-beautifulsoup4
Requires:       python3-copr
Requires:       python3-requests

BuildArch:      noarch

%description
%{summary}.

%prep
%autosetup

%build
%py3_build

%install
%py3_install

%check
%{__python3} -m unittest discover tests/

%files
%license COPYING
%doc README.md
%{_bindir}/%{name}
%{python3_sitelib}/rpm_gitoverlay-*.egg-info/
%{python3_sitelib}/rgo/

%changelog
* Wed May 31 2023 Ales Matej <amatej@redhat.com> - 0.4-1
- Bugfix: we don't want to skip rest of the specifle just one line

* Wed May 31 2023 Ales Matej <amatej@redhat.com> - 0.3-1
- Make patch dropping more robust (it now accepts %patchlist)
- Explicitly define %_srcrpmdir

* Tue Mar 29 2022 Ales Matej <amatej@redhat.com> - 0.2-1
- Fix a traceback when used repo has no tags

* Tue Mar 29 2022 Ales Matej <amatej@redhat.com> - 0.1-1
- Release first 0.1 version

* Sun Jul 10 2016 Igor Gnatenko <ignatenko@redhat.com> - 0-1
- Initial package
