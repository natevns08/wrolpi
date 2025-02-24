"""
Fixtures for Pytest tests.
"""
import asyncio
import copy
import json
import logging
import multiprocessing
import pathlib
import shutil
import tempfile
import zipfile
from abc import ABC
from datetime import datetime
from itertools import zip_longest
from typing import List, Callable, Dict, Sequence, Union
from typing import Tuple, Set
from unittest import mock
from unittest.mock import MagicMock
from uuid import uuid1, uuid4

import pytest
import sqlalchemy
import yaml
from PIL import Image
from sanic_testing.reusable import ReusableClient
from sanic_testing.testing import SanicASGITestClient
from sqlalchemy.engine import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker

from wrolpi import flags
from wrolpi.common import iterify, log_level_context
from wrolpi.common import set_test_media_directory, Base, set_test_config
from wrolpi.dates import set_test_now
from wrolpi.db import postgres_engine, get_db_args
from wrolpi.downloader import DownloadManager, DownloadResult, Download, Downloader, \
    downloads_manager_config_context
from wrolpi.errors import UnrecoverableDownloadError
from wrolpi.files.models import Directory, FileGroup
from wrolpi.root_api import BLUEPRINTS, api_app
from wrolpi.tags import Tag
from wrolpi.vars import PROJECT_DIR


def get_test_db_engine():
    suffix = str(uuid1()).replace('-', '')
    db_name = f'wrolpi_testing_{suffix}'
    conn = postgres_engine.connect()
    conn.execute(f'DROP DATABASE IF EXISTS {db_name}')
    conn.execute(f'CREATE DATABASE {db_name}')
    conn.execute('commit')
    conn.close()

    test_args = get_db_args(db_name)
    test_engine = create_engine('postgresql://{user}:{password}@{host}:{port}/{dbname}'.format(**test_args))
    return test_engine


def test_db() -> Tuple[Engine, Session]:
    """Create a unique SQLAlchemy engine/session for a test."""
    test_engine = get_test_db_engine()
    if test_engine.engine.url.database == 'wrolpi':
        raise ValueError('Refusing the test on wrolpi database!')

    # Create all tables.  No need to check if they exist because this is a test DB.
    Base.metadata.create_all(test_engine, checkfirst=False)
    session = sessionmaker(bind=test_engine)()
    return test_engine, session


@pytest.fixture()
def test_session() -> Session:
    """Pytest Fixture to get a test database session."""
    test_engine, session = test_db()

    def fake_get_db_session():
        """Get the testing db"""
        return test_engine, session

    try:
        with mock.patch('wrolpi.db._get_db_session', fake_get_db_session):
            yield session
    finally:
        session.rollback()
        session.close()
        test_engine.dispose()
        conn = postgres_engine.connect()
        conn.execute(f'DROP DATABASE IF EXISTS {test_engine.engine.url.database}')
        conn.close()


@pytest.fixture(autouse=True)
def test_debug_logger(level: int = logging.DEBUG):
    """Tests use debug logging by default."""
    with log_level_context(level):
        yield


@pytest.fixture(autouse=True)
def test_directory() -> pathlib.Path:
    """
    Overwrite the media directory with a temporary directory.
    """
    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_path = pathlib.Path(tmp_dir)
        tmp_path.chmod(0o40755)
        assert tmp_path.is_dir()
        set_test_media_directory(tmp_path)
        yield tmp_path


@pytest.fixture(autouse=True)
def test_config(test_directory) -> pathlib.Path:
    """
    Create a test config based off the example config.
    """
    config_path = test_directory / 'config/wrolpi.yaml'
    set_test_config(True)
    yield config_path
    set_test_config(False)


ROUTES_ATTACHED = False


@pytest.fixture()
def test_client() -> ReusableClient:
    """Get a Reusable Sanic Test Client with all default routes attached.

    (A non-reusable client would turn on for each request)
    """
    global ROUTES_ATTACHED
    if ROUTES_ATTACHED is False:
        # Attach any blueprints for the test.
        for bp in BLUEPRINTS:
            api_app.blueprint(bp)
        ROUTES_ATTACHED = True

    for _ in range(5):
        # Sometimes the Sanic client tries to use a port already in use, try again...
        try:
            client = ReusableClient(api_app)
            with client:
                yield client
            break
        except OSError as e:
            # Ignore errors where the port was already in use.
            if 'address already in use' not in str(e):
                raise
    else:
        raise RuntimeError('Test never got unused port')


@pytest.fixture()
def test_async_client() -> SanicASGITestClient:
    """Get an Async Sanic Test Client with all default routes attached."""
    global ROUTES_ATTACHED
    if ROUTES_ATTACHED is False:
        # Attach any blueprints for the test.
        for bp in BLUEPRINTS:
            api_app.blueprint(bp)
        ROUTES_ATTACHED = True

    return SanicASGITestClient(api_app)


@pytest.fixture
def test_download_manager_config(test_directory):
    with downloads_manager_config_context():
        (test_directory / 'config').mkdir(exist_ok=True)
        config_path = test_directory / 'config/download_manager.yaml'
        yield config_path


@pytest.fixture
async def test_download_manager(
        test_session,  # session is required because downloads can start without the test DB in place.
        test_download_manager_config,
):
    manager = DownloadManager()
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = asyncio.get_event_loop()
    manager.enable(loop)

    yield manager

    manager.stop()


@pytest.fixture
def fake_now():
    try:
        set_test_now(datetime(2000, 1, 1))
        yield set_test_now
    finally:
        # reset now() to its original functionality.
        set_test_now(None)  # noqa


@pytest.fixture
def successful_download():
    return DownloadResult(success=True)


@pytest.fixture
def failed_download():
    return DownloadResult(error='pytest.fixture failed_download error', success=False)


@pytest.fixture
def assert_download_urls(test_session):
    def asserter(expected_urls: Set[str]):
        downloads = test_session.query(Download).all()
        urls = {i.url for i in downloads}
        if urls != set(expected_urls):
            raise AssertionError(f'Download URLs do not match: {urls} != {expected_urls}')

    return asserter


@pytest.fixture
def assert_downloads(test_session):
    from wrolpi.test.common import assert_dict_contains

    def asserter(expected: List[Dict]):
        downloads = test_session.query(Download).order_by(Download.url)
        for download_, expected_ in zip_longest(downloads, expected):
            assert_dict_contains(download_.__json__(), expected_)
        if (count := test_session.query(Download).count()) != len(expected):
            raise AssertionError(f'Download count does not match: {count} != {len(expected)}')

    return asserter


@pytest.fixture
def test_downloader(test_download_manager):
    class TestDownloader(Downloader, ABC):
        """A testing Downloader"""
        name = 'test_downloader'

        def __repr__(self):
            return '<TESTING Downloader>'

        do_download = MagicMock()

        def set_test_success(self):
            async def _(*a, **kwargs):
                return DownloadResult(success=True)

            self.do_download.side_effect = _

        def set_test_failure(self):
            async def _(*a, **kwargs):
                return DownloadResult(success=False)

            self.do_download.side_effect = _

        def set_test_exception(self, exception: Exception = Exception('Test downloader exception')):
            async def _(*a, **kwargs):
                raise exception

            self.do_download.side_effect = _

        def set_test_unrecoverable_exception(self):
            async def _(*a, **kwargs):
                raise UnrecoverableDownloadError()

            self.do_download.side_effect = _

    test_downloader = TestDownloader()
    # Default to successful download.
    test_downloader.set_test_success()
    test_download_manager.register_downloader(test_downloader)

    return test_downloader


@pytest.fixture
def video_file(test_directory) -> pathlib.Path:
    """Return a copy of the example Big Buck Bunny video in the `test_directory`."""
    destination = test_directory / f'video-{uuid4()}.mp4'
    shutil.copy(PROJECT_DIR / 'test/big_buck_bunny_720p_1mb.mp4', destination)

    yield destination


@pytest.fixture
def corrupted_video_file(test_directory) -> pathlib.Path:
    """Return a copy of a corrupted video file in the `test_directory`."""
    destination = test_directory / f'corrupted-{uuid4()}.mp4'
    shutil.copy(PROJECT_DIR / 'test/corrupted.mp4', destination)

    yield destination


@pytest.fixture
def video_file_factory(test_directory):
    """Return a copy of the example Big Buck Bunny video in the `test_directory`."""

    def _(path: pathlib.Path = None) -> pathlib.Path:
        destination = path or test_directory / f'{uuid4()}.mp4'
        shutil.copy(PROJECT_DIR / 'test/big_buck_bunny_720p_1mb.mp4', destination)

        return destination

    return _


@pytest.fixture
def video_bytes():
    return (PROJECT_DIR / 'test/big_buck_bunny_720p_1mb.mp4').read_bytes()


@pytest.fixture
def corrupted_video_file(test_directory) -> pathlib.Path:
    """Return a copy of the corrupted video file in the `test_directory`."""
    destination = test_directory / f'{uuid4()}.mp4'
    shutil.copy(PROJECT_DIR / 'test/corrupted.mp4', destination)

    yield destination


@pytest.fixture
def image_file(test_directory) -> pathlib.Path:
    """Create a small image file in the `test_directory`."""
    destination = test_directory / f'{uuid4()}.jpeg'
    Image.new('RGB', (25, 25), color='grey').save(destination)
    yield destination


@pytest.fixture
def vtt_file1(test_directory) -> pathlib.Path:
    """Return a copy of the example1 VTT file in the `test_directory`."""
    destination = test_directory / f'{uuid4()}.en.vtt'
    shutil.copy(PROJECT_DIR / 'test/example1.en.vtt', destination)
    yield destination


@pytest.fixture
def vtt_file2(test_directory) -> pathlib.Path:
    """Return a copy of the example2 VTT file in the `test_directory`."""
    destination = test_directory / f'{uuid4()}.en.vtt'
    shutil.copy(PROJECT_DIR / 'test/example2.en.vtt', destination)
    yield destination


@pytest.fixture
def srt_text() -> str:
    return (PROJECT_DIR / 'test/example3.en.srt').read_text()


@pytest.fixture
def srt_file3(test_directory) -> pathlib.Path:
    """Return a copy of the example3 SRT file in the `test_directory`."""
    destination = test_directory / f'{uuid4()}.en.srt'
    shutil.copy(PROJECT_DIR / 'test/example3.en.srt', destination)
    yield destination


@pytest.fixture
def bad_vtt_file(test_directory) -> pathlib.Path:
    """Return a copy of the bad_caption VTT file in the `test_directory`."""
    destination = test_directory / f'{uuid4()}.en.vtt'
    shutil.copy(PROJECT_DIR / 'test/bad_caption.en.vtt', destination)
    yield destination


@pytest.fixture
def example_pdf(test_directory) -> pathlib.Path:
    destination = test_directory / 'pdf example.pdf'
    shutil.copy(PROJECT_DIR / 'test/pdf example.pdf', destination)
    yield destination


@pytest.fixture
def example_epub(test_directory) -> pathlib.Path:
    destination = test_directory / 'ebook example.epub'
    shutil.copy(PROJECT_DIR / 'test/ebook example.epub', destination)
    yield destination


@pytest.fixture
def example_mobi(test_directory) -> pathlib.Path:
    destination = test_directory / 'ebook example.mobi'
    shutil.copy(PROJECT_DIR / 'test/ebook example.mobi', destination)
    yield destination


@pytest.fixture
def make_files_structure(test_directory) -> Callable:
    """
    A fixture which creates test files passed to it.  If a list is provided, empty files will be created at those
    locations.  If a dict is provided, files will be created containing the value of the dict item.
    """

    def create_files(paths: Union[List, Dict], file_groups: bool = False, session: Session = None) -> List[
        pathlib.Path]:
        files = []

        @iterify(list)
        def touch_paths(paths_):
            for name in paths_:
                path = test_directory / name
                if name.endswith('/'):
                    path.mkdir(parents=True, exist_ok=True)
                else:
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.touch()
                yield path

        if isinstance(paths, list):
            files = touch_paths(paths)
        elif isinstance(paths, Dict):
            files = touch_paths(paths.keys())
            for path, content in paths.items():
                path = test_directory / path
                if isinstance(content, str):
                    path.write_text(content)
                elif isinstance(content, bytes):
                    path.write_bytes(content)

        if file_groups:
            for idx, path in enumerate(files):
                fg = FileGroup.from_paths(session, path)
                files[idx] = fg
        return sorted(files) if isinstance(paths, dict) else files

    return create_files


@pytest.fixture
def wrol_mode_fixture(test_config, test_download_manager):
    from wrolpi.common import enable_wrol_mode, disable_wrol_mode

    def set_wrol_mode(enabled: bool):
        if enabled:
            enable_wrol_mode(test_download_manager)
        else:
            disable_wrol_mode(test_download_manager)

    return set_wrol_mode


@pytest.fixture
def mock_create_subprocess_shell():
    def mocker(communicate_return=None, return_code=None, communicate_side_effect=None):
        async def communicate(*a, **kw):
            if communicate_side_effect:
                return communicate_side_effect()
            return communicate_return or (None, None)

        async def create_subprocess_shell(*a, **kw):
            proc = MagicMock()
            proc.communicate = communicate
            proc.returncode = return_code if return_code is not None else 0
            return proc

        return create_subprocess_shell

    return mocker


@pytest.fixture(autouse=True)
def events_history():
    """Give each test it's own Events history."""
    with mock.patch('wrolpi.events.EVENTS_HISTORY', list()):
        from wrolpi.events import EVENTS_HISTORY
        yield EVENTS_HISTORY


FLAGS_LOCK = multiprocessing.Lock()


@pytest.fixture()
def flags_lock():
    """Wait for exclusive access to flags before testing."""
    try:
        FLAGS_LOCK.acquire(timeout=60)
        flags.TESTING_LOCK.set()
        yield
    finally:
        flags.TESTING_LOCK.clear()
        FLAGS_LOCK.release()


@pytest.fixture()
def tag_factory(test_session):
    names = ['one', 'two', 'three', 'four', 'five', 'six']
    count = 1

    def factory(name: str = None) -> Tag:
        if not name:
            name = names.pop(0)
        tag = Tag(name=name, color=f'#{str(count) * 6}')
        test_session.add(tag)
        test_session.commit()
        test_session.flush([tag, ])
        return tag

    return factory


@pytest.fixture
def assert_files(test_session, test_directory):
    def _(files: List[Dict]):
        from wrolpi.files.models import FileGroup
        for expected in files:
            primary_path = test_directory / expected.pop('path')
            try:
                file: FileGroup = test_session.query(FileGroup).filter_by(primary_path=primary_path).one()
            except sqlalchemy.orm.exc.NoResultFound as e:
                raise ValueError(f'No FileGroup found with {primary_path=}') from e

            for key, value in expected.items():
                attr = getattr(file, key)
                if attr != value:
                    raise AssertionError(f'{primary_path} {attr} != {value}')

    return _


@pytest.fixture
def assert_file_groups(test_session, test_directory):
    from wrolpi.test.common import assert_dict_contains

    def _(file_groups: List[Dict], assert_count: bool = True):
        from wrolpi.files.models import FileGroup
        for expected in file_groups:
            if 'primary_path' not in expected:
                raise Exception('You must specify the primary path for this fixture!')

            primary_path = str(test_directory / expected.pop('primary_path'))
            try:
                file_group: FileGroup = test_session.query(FileGroup).filter_by(primary_path=primary_path).one()
            except Exception as e:
                raise ValueError(f'No FileGroup found with {primary_path=}') from e

            # Compare file dictionaries.
            files = expected.pop('files', None)
            if files:
                for exp, actual in zip_longest(files, file_group.files):
                    assert_dict_contains(actual, exp)

            for key, value in expected.items():
                attr = getattr(file_group, key)
                if isinstance(value, dict):
                    assert_dict_contains(attr, value)
                elif attr != value:
                    raise AssertionError(f'{file_group}.{key} {attr=} != {value}')

        if assert_count is True:
            if (count := test_session.query(FileGroup).count()) != len(file_groups):
                raise AssertionError(f'FileGroup count does not match {count} != {len(file_groups)}')

    return _


@pytest.fixture
def assert_files_search(test_client):
    from wrolpi.test.common import assert_dict_contains
    def _(search_str: str, expected: List[dict]):
        content = json.dumps({'search_str': search_str})
        request, response = test_client.post('/api/files/search', content=content)
        for file_group, exp in zip_longest(response.json['file_groups'], expected):
            assert_dict_contains(file_group, exp)

        assert len(response.json['file_groups']) == len(expected)

    return _


SINGLEFILE_CONTENTS = '''<html><!--
 Page saved with SingleFile 
 url: {url} 
 saved date: Thu May 12 2022 00:38:02 GMT+0000 (Coordinated Universal Time)
--><head><meta charset="utf-8">

<meta name="msapplication-TileColor" content="#2d89ef">
<meta name="theme-color" content="#000000">

{title}

<body>
some body contents
</body>

</html>
'''


@pytest.fixture
def singlefile_contents_factory():
    def _(title: str = '', url: str = 'https://example.com') -> str:
        contents = copy.deepcopy(SINGLEFILE_CONTENTS)
        contents = contents.format(
            title=f'<title>{title}</title>',
            url=url,
        )
        return contents

    return _


@pytest.fixture
def example_singlefile(test_directory, singlefile_contents_factory) -> pathlib.Path:
    archive = test_directory / 'archive'
    archive.mkdir(exist_ok=True)
    singlefile = archive / 'singlefile.html'
    singlefile.write_text(singlefile_contents_factory())
    return singlefile


@pytest.fixture
def image_bytes_factory():
    def _() -> bytes:
        with tempfile.NamedTemporaryFile(suffix='.png') as fh:
            Image.new('RGB', (1, 1), color='grey').save(fh)
            fh.seek(0)
            image = fh.read()
            return image

    return _


@pytest.fixture
def insert_file_group(test_session, test_directory):
    """Inserts a FileGroup based on the provided paths.  Does not verify if the files exist."""

    def _(paths: List[pathlib.Path]):
        files = [dict(path=str(i), mimetype='fake') for i in paths]
        params = dict(
            primary_path=str(paths[0]),
            files=json.dumps(files),
        )
        test_session.execute('INSERT INTO file_group '
                             '(indexed, primary_path, files) VALUES '
                             '(true, :primary_path, :files)', params)

    return _


@pytest.fixture
def test_tags_config(test_directory):
    from wrolpi.tags import test_tags_config
    with test_tags_config():
        (test_directory / 'config').mkdir(exist_ok=True)
        config_path = test_directory / 'config/tags.yaml'
        yield config_path


@pytest.fixture
def assert_tags_config(test_tags_config):
    def _(tags: dict = None):
        from wrolpi.test.common import assert_dict_contains
        with test_tags_config.open('rt') as fh:
            contents = yaml.load(fh, Loader=yaml.Loader)

        if tags:
            for key, item in tags.items():
                assert key in contents['tags']
                assert_dict_contains(item, contents['tags'][key])
        else:
            # Expect no tags to be saved.
            assert not contents['tags']

    return _


@pytest.fixture
def zip_file_factory(test_directory):
    def _() -> bytes:
        with tempfile.NamedTemporaryFile() as fh:
            with zipfile.ZipFile(fh, 'w') as zip_file:
                zip_file.write(PROJECT_DIR / 'test/big_buck_bunny_720p_1mb.mp4')

            fh.seek(0)
            return fh.read()

    return _


@pytest.fixture
def assert_directories(test_session, test_directory):
    def _(expected: Sequence[str]):
        directories = test_session.query(Directory).all()
        names = {str(i.path.relative_to(test_directory)) for i in directories}
        assert names == set(expected)

    return _


@pytest.fixture
def make_multipart_form():
    def _(forms: List[dict]):
        boundary = '-----sanic\n'
        new_forms = []
        for form in forms:
            name, value, filename = form['name'], form['value'], form.get('filename')
            if filename:
                new_forms.append(f'Content-Disposition: form-data; name="{name}"; filename="{filename}"\n\n{value}\n')
            else:
                new_forms.append(f'Content-Disposition: form-data; name="{name}"\n\n{value}\n')
        body = f'\n{boundary}'.join(new_forms)
        body = f'{boundary}{body}\n{boundary}'
        body = '\r\n'.join(body.split('\n')).strip()
        return body

    return _
