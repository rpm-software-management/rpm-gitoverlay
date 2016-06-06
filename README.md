# rpm-gitoverlay

Manage an overlay repository of RPMs from upstream git.

## Usage

1. Create `overlay.yml` file (see reference below)
2. Resolve (`rpm-gitoverlay resolve`). It will clone repos into `src` subdirectory, do checkouts.
3. Build. It will build SRPMs or RPMs (`rpm-gitoverlay build`).
   * SRPMs: `rpm-gitoverlay build srpm`
   * RPMs:
     * Build using [COPR](https://fedorahosted.org/copr/): `rpm-gitoverlay build rpm copr --help`

## `overlay.yml` refenrece

#### Top-level parameters:

| Parameter  | Required | Type | Comments                                               |
|------------|----------|------|--------------------------------------------------------|
| aliases    | no       | list | List of aliases, same as `url.<base>.insteadOf` in git |
| chroot     | yes      | str  | Chroot name (will be used for building RPMs            |
| components | yes      | list | List of component and settings to build in overlay     |

#### `aliases` structure:

| Parameter | Required | Type | Comments |
|-----------|----------|------|----------|
| name      | yes      | str  | Prefix   |
| url       | yes      | str  | URL      |

#### `components` structure:

| Parameter | Required | Type | Comments                                        |
|-----------|----------|------|-------------------------------------------------|
| name      | yes      | str  | Name of component (e.g. `libsolv`)              |
| git       | no       | dict | Settings for upstream git repository            |
| distgit   | no       | dict | Settings for distro/RPM specific git repository |

You must set one or both from `git`/`distgit`.
* If you set only `git`: it will use `<name>.spec` from top directory of git repo and make archive from `git` repo
* If you set only `distgit`: it will rebuild component from distgit
* If you set both `git` and `distgit`: it will use `<name>.spec` from `distgit` and make archive from `git` repo

#### `git` structure:

| Parameter | Required | Type | Comments                                    |
|-----------|----------|------|---------------------------------------------|
| src       | yes      | str  | URL to git repo (can use aliases set above) |
| freeze    | no       | str  | Commit to freeze repo on                    |
| branch    | no       | str  | Branch to freeze repo on                    |

Only one of following parameters can be chosen:
* `freeze`
* `branch`

#### `distgit` structure:

| Parameter | Required | Type | Comments                                              |
|-----------|----------|------|-------------------------------------------------------|
| patches   | no       | str  | What to do with patches: `keep` (**default**), `drop` |

Plus all parameters from `git` structure.

## `overlay.yml` example

```yaml
---
aliases:
  - name: github
    url: https://github.com/
  - name: fedorapkgs
    url: git://pkgs.fedoraproject.org/rpms/

chroot: fedora-24-x86_64

components:
  - name: libsolv
    git:
      src: github:openSUSE/libsolv.git
    distgit:
      src: fedorapkgs:libsolv.git

  - name: libhif
    git:
      src: github:rpm-software-management/libhif.git
```
