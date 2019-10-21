# -*- Mode:Python; indent-tabs-mode:nil; tab-width:4 -*-
#
# Copyright (C) 2019 Canonical Ltd
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License version 3 as
# published by the Free Software Foundation.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.

import os
import snapcraft
import textwrap

from snapcraft.internal.sources.errors import SnapcraftPullError
from snapcraft.internal.remote_build import LaunchpadClient, errors
from testtools.matchers import Equals, Contains
from tests import unit
from unittest import mock
from . import TestDir


class FakeLaunchpadObject:
    """Mimic behavior of many launchpad objects."""

    def __init__(self):
        pass

    def __setitem__(self, key, value):
        self.__setattr__(key, value)

    def __getitem__(self, key):
        return self.__getattribute__(key)


class BuildImpl(FakeLaunchpadObject):
    def __init__(self):
        self.getFileUrls_mock = mock.Mock(return_value=["url_for/snap_file_i386.snap"])

    def getFileUrls(self, *args, **kw):
        return self.getFileUrls_mock(*args, **kw)


class SnapBuildEntryImpl(FakeLaunchpadObject):
    def __init__(self, arch_tag="", buildstate="", self_link="", build_log_url=""):
        self.arch_tag = arch_tag
        self.buildstate = buildstate
        self.self_link = self_link
        self.build_log_url = build_log_url


class SnapBuildsImpl(FakeLaunchpadObject):
    def __init__(
        self,
        entries=[
            SnapBuildEntryImpl(
                arch_tag="i386",
                buildstate="Successfully built",
                self_link="http://build_self_link_1",
                build_log_url="url_for/build_log_file_1",
            ),
            SnapBuildEntryImpl(
                arch_tag="amd64",
                buildstate="Failed to build",
                self_link="http://build_self_link_2",
                build_log_url="url_for/build_log_file_2",
            ),
        ],
    ):
        self.entries = entries


class SnapBuildReqImpl(FakeLaunchpadObject):
    def __init__(
        self,
        status="Completed",
        error_message="",
        self_link="http://request_self_link/1234",
        builds_collection_link="http://builds_collection_link",
        builds=SnapBuildsImpl(),
    ):
        self.status = status
        self.error_message = error_message
        self.self_link = self_link
        self.builds_collection_link = builds_collection_link
        self.builds = builds

    def lp_refresh(self):
        pass


class SnapImpl(FakeLaunchpadObject):
    def __init__(self):
        self._req = SnapBuildReqImpl()
        self.lp_delete_mock = mock.Mock()
        self.requestBuilds_mock = mock.Mock(return_value=self._req)

    def lp_delete(self, *args, **kw):
        return self.lp_delete_mock(*args, **kw)

    def requestBuilds(self, *args, **kw):
        return self.requestBuilds_mock(*args, **kw)


class SnapsImpl(FakeLaunchpadObject):
    def __init__(self):
        self._snap = SnapImpl()
        self.getByName_mock = mock.Mock(return_value=self._snap)
        self.new_mock = mock.Mock(return_value=self._snap)

    def getByName(self, *args, **kw):
        return self.getByName_mock(*args, **kw)

    def new(self, *args, **kw):
        return self.new_mock(*args, **kw)


class GitImpl(FakeLaunchpadObject):
    def __init__(self):
        self.issueAccessToken_mock = mock.Mock(return_value="access-token")
        self.lp_delete_mock = mock.Mock()

    def issueAccessToken(self, *args, **kw):
        return self.issueAccessToken_mock(*args, **kw)

    def lp_delete(self, *args, **kw):
        return self.lp_delete_mock(*args, **kw)


class GitRepositoriesImpl(FakeLaunchpadObject):
    def __init__(self):
        self._git = GitImpl()
        self.new_mock = mock.Mock(return_value=self._git)
        self.getByPath_mock = mock.Mock(return_value=self._git)

    def getByPath(self, *args, **kw):
        return self.getByPath_mock(*args, **kw)

    def new(self, *args, **kw):
        return self.new_mock(*args, **kw)


class DistImpl(FakeLaunchpadObject):
    def __init__(self):
        self.main_archive = "main_archive"


class LaunchpadImpl(FakeLaunchpadObject):
    def __init__(self):
        self.login_mock = mock.Mock()
        self.load_mock = mock.Mock()
        self.git_repositories = GitRepositoriesImpl()
        self.snaps = SnapsImpl()
        self.people = {"user": "/~user"}
        self.distributions = {"ubuntu": DistImpl()}
        self.rbi = SnapBuildReqImpl()

    def load(self, url: str, *args, **kw):
        self.load_mock(url, *args, **kw)
        if "/+build-request/" in url:
            return SnapBuildReqImpl()
        elif "http://build_self_link_1" in url:
            return BuildImpl()
        else:
            return self.rbi.builds


class LaunchpadTestCase(unit.TestCase):
    def setUp(self):
        super().setUp()
        self._project = self._make_snapcraft_project()
        self.lpc = LaunchpadClient(project=self._project, build_id="id", user="user")

    @mock.patch("launchpadlib.launchpad.Launchpad.login_with")
    def test_login(self, mock_login):
        self.lpc.login()
        self.assertThat(self.lpc.user, Equals("user"))
        mock_login.assert_called_with(
            "snapcraft remote-build {}".format(snapcraft.__version__),
            "production",
            mock.ANY,
            credentials_file=mock.ANY,
            version="devel",
        )

    def test_create_snap(self):
        self.lpc._lp = LaunchpadImpl()
        self.lpc.create_snap()
        self.lpc._lp.snaps.new_mock.assert_called_with(
            auto_build=False,
            auto_build_archive="/ubuntu/+archive/primary",
            auto_build_pocket="Updates",
            git_path="master",
            git_repository_url="https://user@git.launchpad.net/~user/+git/id/",
            name="id",
            owner="/~user",
        )

    def test_create_snap_with_archs(self):
        self.lpc._lp = LaunchpadImpl()
        self.lpc.architectures = ["arch1", "arch2"]
        self.lpc.create_snap()
        self.lpc._lp.snaps.new_mock.assert_called_with(
            auto_build=False,
            auto_build_archive="/ubuntu/+archive/primary",
            auto_build_pocket="Updates",
            git_path="master",
            git_repository_url="https://user@git.launchpad.net/~user/+git/id/",
            name="id",
            owner="/~user",
            processors=["/+processors/arch1", "/+processors/arch2"],
        )

    def test_delete_snap(self):
        self.lpc._lp = LaunchpadImpl()
        self.lpc.delete_snap()
        self.lpc._lp.snaps.getByName_mock.assert_called_with(name="id", owner="/~user")

    def test_start_build(self):
        self.lpc._lp = LaunchpadImpl()
        num = self.lpc.start_build()
        self.assertThat(num, Equals("1234"))

    @mock.patch(
        "tests.unit.remote_build.test_launchpad.SnapImpl.requestBuilds",
        return_value=SnapBuildReqImpl(
            status="Failed", error_message="snapcraft.yaml not found..."
        ),
    )
    def test_start_build_error(self, mock_rb):
        self.lpc._lp = LaunchpadImpl()

        raised = self.assertRaises(
            errors.RemoteBuilderError, self.lpc.start_build, timeout=0, attempts=1
        )
        self.assertThat(str(raised), Contains("snapcraft.yaml not found..."))

    @mock.patch(
        "tests.unit.remote_build.test_launchpad.SnapImpl.requestBuilds",
        return_value=SnapBuildReqImpl(status="Pending", error_message=""),
    )
    def test_start_build_error_timeout(self, mock_rb):
        self.lpc._lp = LaunchpadImpl()
        raised = self.assertRaises(
            errors.RemoteBuilderNotReadyError,
            self.lpc.start_build,
            timeout=0,
            attempts=1,
        )
        self.assertThat(str(raised), Contains("is not ready"))

    def test_recover_build(self):
        self.lpc._lp = LaunchpadImpl()
        self.lpc.recover_build(1234)
        self.assertThat(self.lpc._lp.load_mock.call_count, Equals(2))

    @mock.patch("snapcraft.internal.remote_build.LaunchpadClient._download_file")
    def test_monitor_build(self, mock_download_file):
        open("test_i386.txt.gz", "w").close()
        open("test_i386.txt.gz.1", "w").close()
        self.lpc._lp = LaunchpadImpl()

        self.lpc.start_build()
        self.lpc.monitor_build(interval=0)
        mock_download_file.assert_has_calls(
            [
                mock.call("url_for/build_log_file_1", "test_i386.txt.gz.2"),
                mock.call("url_for/snap_file_i386.snap", "snap_file_i386.snap"),
                mock.call("url_for/build_log_file_2", "test_amd64.txt.gz"),
            ]
        )

    @mock.patch("snapcraft.internal.remote_build.LaunchpadClient._download_file")
    @mock.patch(
        "tests.unit.remote_build.test_launchpad.BuildImpl.getFileUrls", return_value=[]
    )
    @mock.patch("logging.Logger.error")
    def test_monitor_build_error(self, mock_log, mock_urls, mock_download_file):
        self.lpc._lp = LaunchpadImpl()
        self.lpc.start_build()
        self.lpc.monitor_build(interval=0)
        mock_download_file.assert_has_calls(
            [mock.call("url_for/build_log_file_2", "test_amd64.txt.gz")]
        )
        mock_log.assert_called_with(
            "Build failed for arch amd64. Log file is 'test_amd64.txt.gz'."
        )

    def test_get_build_status(self):
        self.lpc._lp = LaunchpadImpl()
        self.lpc.start_build()
        build_status = self.lpc.get_build_status()
        self.assertThat(
            build_status,
            Equals([("i386", "Successfully built"), ("amd64", "Failed to build")]),
        )

    def _make_snapcraft_project(self):
        yaml = textwrap.dedent(
            """\
            name: test
            base: core18
            version: "1.0"
            summary: test
            description: test
            confinement: strict
            grade: stable
            """
        )
        snapcraft_yaml_file_path = self.make_snapcraft_yaml(yaml)
        project = snapcraft.project.Project(
            snapcraft_yaml_file_path=snapcraft_yaml_file_path
        )
        return project

    def test_git_repository_creation(self):
        source_testdir = self.useFixture(TestDir())
        source_testdir.create_file("foo")
        repo_dir = source_testdir.path
        self.assertFalse(os.path.exists(os.path.join(repo_dir, ".git")))
        self.lpc._gitify_repository(repo_dir)
        self.assertTrue(os.path.exists(os.path.join(repo_dir, ".git")))

    @mock.patch("snapcraft.internal.sources.Git.push", return_value=None)
    def test_push_source_tree(self, mock_push):
        self.lpc._lp = LaunchpadImpl()
        source_testdir = self.useFixture(TestDir())
        source_testdir.create_file("foo")
        repo_dir = source_testdir.path
        self.lpc.push_source_tree(repo_dir)
        mock_push.assert_called_with(
            "https://user:access-token@git.launchpad.net/~user/+git/id/",
            "HEAD:master",
            force=True,
        )

    @mock.patch(
        "snapcraft.internal.sources.Git.push",
        side_effect=SnapcraftPullError(
            command="git push HEAD:master https://user:access-token@url", exit_code=128
        ),
    )
    def test_push_source_tree_error(self, mock_push):
        self.lpc._lp = LaunchpadImpl()
        source_testdir = self.useFixture(TestDir())
        source_testdir.create_file("foo")
        repo_dir = source_testdir.path

        raised = self.assertRaises(
            errors.LaunchpadGitPushError, self.lpc.push_source_tree, repo_dir
        )
        self.assertThat(
            raised.get_brief(), Equals("Failed to push sources to Launchpad.")
        )
        self.assertThat(
            raised.get_details(),
            Equals(
                "Command 'git push HEAD:master https://user:<token>@url' failed with exit code 128."
            ),
        )

        mock_push.assert_called_with(
            "https://user:access-token@git.launchpad.net/~user/+git/id/",
            "HEAD:master",
            force=True,
        )
