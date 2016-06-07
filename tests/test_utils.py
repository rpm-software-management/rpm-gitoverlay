import shutil
import subprocess
import tempfile

from rgo import utils

from nose import tools

class TestGitDescribe(object):
    def setUp(self):
        self.repo = tempfile.mkdtemp(prefix="rgo-test")
        subprocess.run(["git", "init"],
                       cwd=self.repo, check=True,
                       stdout=subprocess.DEVNULL)

    def teardown(self):
        shutil.rmtree(self.repo)

    @property
    def sha1(self):
        result = subprocess.run(["git", "rev-parse", "--short", "HEAD"],
                                cwd=self.repo, check=True,
                                stdout=subprocess.PIPE)
        return result.stdout.decode("ascii").rstrip()

    def commit(self, msg="test"):
        subprocess.run(["git", "commit", "--allow-empty", "-m", msg],
                       cwd=self.repo, check=True,
                       stdout=subprocess.DEVNULL)

    def tag(self, name):
        subprocess.run(["git", "tag", name], cwd=self.repo, check=True)

    def describe(self):
        return utils.git_describe(self.repo)

    def test_no_tags(self):
        self.commit()
        tools.assert_equal(utils.git_describe(self.repo),
                           ("0", "1g{}".format(self.sha1)))

    def test_tag(self):
        self.commit()
        self.tag("0.1")
        tools.assert_equal(utils.git_describe(self.repo), ("0.1", "1"))

    def test_after_tag(self):
        self.commit()
        self.tag("0.1")
        self.commit()
        self.commit()
        tools.assert_equal(utils.git_describe(self.repo),
                           ("0.1", "2g{}".format(self.sha1)))

    def test_with_prefix(self):
        self.commit()
        self.tag("v0.1")
        tools.assert_equal(utils.git_describe(self.repo), ("0.1", "1"))

        self.commit()
        self.tag("test-0.1")
        tools.assert_equal(utils.git_describe(self.repo, "test"), ("0.1", "1"))

        self.commit()
        self.tag("GNOME_BUILDER_3_21_1")
        tools.assert_equal(utils.git_describe(self.repo, "gnome-builder"),
                           ("3.21.1", "1"))
