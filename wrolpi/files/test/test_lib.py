import asyncio
import json
import shutil
import zipfile
from datetime import datetime
from pathlib import Path
from typing import List
from uuid import uuid4

import mock
import pytest
from PIL import Image
from sqlalchemy.orm import Session

from modules import videos
from wrolpi.common import get_media_directory, timer
from wrolpi.errors import InvalidFile
from wrolpi.files import lib, indexers
from wrolpi.files.models import File
from wrolpi.vars import PROJECT_DIR


def assert_files(session: Session, expected):
    files = {str(i.path.relative_to(get_media_directory())) for i in session.query(File).all()}
    assert files == set(expected)


def test_delete_file(make_files_structure, test_directory):
    """
    File in the media directory can be deleted.
    """
    files = [
        'archives/foo.txt',
        'bar.txt',
        'baz/',
    ]
    make_files_structure(files)

    lib.delete_file('bar.txt')
    assert (test_directory / 'archives/foo.txt').is_file()
    assert not (test_directory / 'bar.txt').is_file()
    assert (test_directory / 'baz').is_dir()

    lib.delete_file('archives/foo.txt')
    assert not (test_directory / 'archives/foo.txt').is_file()
    assert not (test_directory / 'bar.txt').is_file()

    with pytest.raises(InvalidFile):
        lib.delete_file('baz')
    with pytest.raises(InvalidFile):
        lib.delete_file('does not exist')

    assert (test_directory / 'baz').is_dir()


@pytest.mark.parametrize(
    'path,expected',
    [
        ('foo', ('foo', '')),
        ('foo.mp4', ('foo', '.mp4')),
        ('foo.info.json', ('foo', '.info.json')),
        ('foo.something.info.json', ('foo.something', '.info.json')),
        ('foo-something.info.json', ('foo-something', '.info.json')),
        ('/absolute/foo-something.info.json', ('foo-something', '.info.json')),
        ('/absolute/foo', ('foo', '')),
        ('/absolute/foo.bar', ('foo', '.bar')),
    ]
)
def test_split_path_stem_and_suffix(path, expected):
    assert lib.split_path_stem_and_suffix(Path(path)) == expected


@pytest.mark.asyncio
async def test_refresh_files(test_session, make_files_structure, test_directory):
    """All files in the media directory should be found when calling `refresh_files`"""
    files = make_files_structure([
        'foo.txt',
        'bar.txt',
        'baz.txt',
    ])
    foo, bar, baz = files

    await lib.refresh_files()
    assert_files(test_session, ['bar.txt', 'baz.txt', 'foo.txt'])

    baz.unlink()

    await lib.refresh_files()
    assert_files(test_session, ['bar.txt', 'foo.txt'])

    foo.unlink()
    bar.unlink()

    await lib.refresh_files()
    assert_files(test_session, [])


@pytest.mark.asyncio
async def test_refresh_a_text_no_indexer(test_session, make_files_structure):
    """File.a_text is filled even if the file does not match an Indexer."""
    make_files_structure(['foo', 'bar-bar'])

    await lib.refresh_files()

    files = {i.a_text for i in test_session.query(File).all()}
    assert files == {'{bar,bar-bar}', '{foo}'}


@pytest.mark.asyncio
async def test_refresh_many_files(test_session, make_files_structure):
    """Used to profile file refreshing"""
    count = 10_000
    make_files_structure([f'{uuid4()}.txt' for _ in range(count)])
    with timer('first refresh'):
        await lib.refresh_files()
    assert test_session.query(File).count() == count

    with timer('second refresh'):
        await lib.refresh_files()
    assert test_session.query(File).count() == count


@pytest.mark.asyncio
async def test_refresh_files_list(test_session, make_files_structure, test_directory):
    make_files_structure(['foo.txt', 'bar.txt'])

    # Only foo.txt should have been refreshed.
    await lib.refresh_files_list(['foo.txt'])
    assert_files(test_session, ['foo.txt'])

    # Both files should be found
    await lib.refresh_files_list(['bar.txt'])
    assert_files(test_session, ['foo.txt', 'bar.txt'])

    # Both files should be unchanged.
    await lib.refresh_files_list(['foo.txt', 'bar.txt'])
    assert_files(test_session, ['foo.txt', 'bar.txt'])

    with pytest.raises(FileNotFoundError):
        # Some files must be refreshed.
        await lib.refresh_files_list([])

    # Files that share the stem can also be refreshed.
    (test_directory / 'foo.mp4').touch()
    await lib.refresh_files_list(['foo.txt', 'bar.txt'])
    assert_files(test_session, ['foo.txt', 'foo.mp4', 'bar.txt'])

    # Files that share the stem can also be ignored.
    (test_directory / 'bar.mp4').touch()
    await lib.refresh_files_list(['bar.txt'], include_files_near=False)
    assert_files(test_session, ['foo.txt', 'foo.mp4', 'bar.txt'])

    # Deleted files are removed.
    (test_directory / 'foo.mp4').unlink()
    (test_directory / 'bar.txt').unlink()
    await lib.refresh_files_list(['foo.txt', 'bar.txt'], include_files_near=False)
    assert_files(test_session, ['foo.txt', ])
    # bar.mp4 is discovered near non-existent bar.txt.
    await lib.refresh_files_list(['foo.txt', 'bar.txt'])
    assert_files(test_session, ['foo.txt', 'bar.mp4'])


@pytest.mark.asyncio
async def test_refresh_cancel(test_session, make_files_structure, test_directory):
    """Refresh tasks can be canceled."""
    # Creat a lot of files so the refresh will take too long.
    make_files_structure([f'{uuid4()}.txt' for _ in range(1_000)])

    async def assert_cancel(task_):
        # Time the time it takes to cancel.
        before = datetime.now()
        # Sleep so the refresh task has time to run.
        await asyncio.sleep(0.1)

        # Cancel the refresh (it will be sleeping soon).
        task_.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task_
        assert (datetime.now() - before).total_seconds() < 0.8, 'Task took too long.  Was the refresh canceled?'

    task = asyncio.create_task(lib.refresh_files())
    await assert_cancel(task)

    task = asyncio.create_task(lib.refresh_directory_files_recursively(test_directory))
    await assert_cancel(task)


@pytest.mark.asyncio
async def test_refresh_files_in_directory(test_session, make_files_structure, test_directory):
    """A subdirectory can be refreshed, files above it can be ignored."""
    ignored, foo, similar = make_files_structure([
        'ignored.txt',
        'subdir/foo.txt',
        'subdir-similarly-named.mp4',
    ])

    await lib.refresh_directory_files_recursively(test_directory / 'subdir')
    assert_files(test_session, ['subdir/foo.txt'])

    await lib.refresh_directory_files_recursively(test_directory)
    assert_files(test_session, ['ignored.txt', 'subdir/foo.txt', 'subdir-similarly-named.mp4'])

    # The similarly named file is not deleted when refreshing the directory which shares the name.
    foo.unlink()
    await lib.refresh_directory_files_recursively(test_directory / 'subdir')
    assert_files(test_session, ['ignored.txt', 'subdir-similarly-named.mp4'])


@pytest.mark.asyncio
async def test_mime_type(test_session, make_files_structure, test_directory):
    """Files module uses the `file` command to get the mimetype of each file."""
    from PIL import Image

    foo, bar, baz, empty = make_files_structure([
        'dir/foo text.txt',
        'dir/bar.jpeg',
        'dir/baz.mp4',
        'dir/empty',
    ])
    foo.write_text('some text')
    Image.new('RGB', (25, 25), color='grey').save(bar)
    shutil.copy(PROJECT_DIR / 'test/big_buck_bunny_720p_1mb.mp4', baz)

    await lib.refresh_files()
    assert_files(test_session, ['dir/foo text.txt', 'dir/bar.jpeg', 'dir/baz.mp4', 'dir/empty'])

    foo = test_session.query(File).filter_by(path=f'{test_directory}/dir/foo text.txt').one()
    bar = test_session.query(File).filter_by(path=f'{test_directory}/dir/bar.jpeg').one()
    baz = test_session.query(File).filter_by(path=f'{test_directory}/dir/baz.mp4').one()
    empty = test_session.query(File).filter_by(path=f'{test_directory}/dir/empty').one()

    assert foo.mimetype == 'text/plain'
    assert bar.mimetype == 'image/jpeg'
    assert baz.mimetype == 'video/mp4'
    assert empty.mimetype == 'inode/x-empty'


@pytest.mark.asyncio
async def test_files_indexer(test_session, make_files_structure, test_directory):
    """An Indexer is provided for each file based on it's mimetype or contents."""
    source_files: List[str] = [
        'a text file.txt',
        'a zip file.zip',
        'images/an image file.jpeg',
        'unknown file',
        'videos/a video file.info.json',  # This is "associated" and will be hidden.
        'videos/a video file.mp4',
    ]
    text_path, zip_path, image_path, unknown_path, info_json_path, video_path \
        = make_files_structure(source_files)
    text_path.write_text('text file contents')
    Image.new('RGB', (25, 25), color='grey').save(image_path)
    shutil.copy(PROJECT_DIR / 'test/big_buck_bunny_720p_1mb.mp4', video_path)
    with zipfile.ZipFile(zip_path, 'w') as zip_file:
        zip_file.write(PROJECT_DIR / 'test/big_buck_bunny_720p_1mb.mp4')
    info_json_path.write_text(json.dumps({'description': 'the video description'}))

    # Enable slow feature for testing.
    # TODO can this be sped up to always be included?
    with mock.patch('modules.videos.EXTRACT_SUBTITLES', True):
        await lib.refresh_files()

    text_file, zip_file, image_file, unknown_file, info_json_file, video_file \
        = test_session.query(File).order_by(File.path)

    # Indexers are detected correctly.
    assert text_file.path.suffix == '.txt' and text_file.indexer == indexers.TextIndexer
    assert zip_file.path.suffix == '.zip' and zip_file.indexer == indexers.ZipIndexer
    assert image_file.path.suffix == '.jpeg' and image_file.indexer == indexers.DefaultIndexer
    assert unknown_file.path.suffix == '' and unknown_file.indexer == indexers.DefaultIndexer
    assert info_json_file.path.suffix == '.json' and info_json_file.indexer == indexers.DefaultIndexer
    assert video_file.path.suffix == '.mp4' and video_file.indexer == videos.VideoIndexer

    def assert_file_properties(file: File, suffix):
        assert file.suffix == suffix

    assert_file_properties(text_file, '.txt')
    assert_file_properties(zip_file, '.zip')
    assert_file_properties(image_file, '.jpeg')
    assert_file_properties(unknown_file, '')
    assert_file_properties(info_json_file, '.info.json')
    assert_file_properties(video_file, '.mp4')

    # File are indexed by their titles and contents.
    files, total = lib.search_files('file', 10, 0)
    assert total == 5, 'All files contain "file" in their file name.  The associated video file is hidden.'
    files, total = lib.search_files('image', 10, 0)
    assert total == 1 and files[0]['title'] == 'an image file.jpeg', 'The image file title contains "image".'
    files, total = lib.search_files('contents', 10, 0)
    assert total == 1 and files[0]['title'] == 'a text file.txt', 'The text file contains "contents".'
    files, total = lib.search_files('video', 10, 0)
    assert total == 1 and {i['title'] for i in files} == {'a video file.mp4'}, 'The video file contains "video".'
    files, total = lib.search_files('yawn', 10, 0)
    assert total == 1 and files[0]['title'] == 'a video file.mp4', 'The video file captions contain "yawn".'
    files, total = lib.search_files('bunny', 10, 0)
    assert total == 1 and {i['title'] for i in files} == {'a zip file.zip'}, \
        'The zip file contains a file with "bunny" in the title.'

    with mock.patch('modules.videos.VideoIndexer.create_index') as mock_create_index:
        mock_create_index.side_effect = Exception('This should not be called twice')
        await lib.refresh_files()

    # Change the contents, the file should be re-indexed.
    text_path.write_text('new text contents')
    await lib.refresh_files()
    files, total = lib.search_files('new', 10, 0)
    assert total == 1


@pytest.mark.parametrize('name,expected', [
    ('this.txt', ['this', 'txt']),
    ('name', ['name']),
    ('name two', ['name', 'two']),
    ('this self-reliance_split.txt', ['this', 'self', 'reliance', 'self-reliance', 'split', 'txt']),
    ('-be_split!.txt', ['-be', 'split!', 'txt']),
])
def test_split_file_name_words(name, expected):
    assert lib.split_file_name_words(name) == expected


@pytest.mark.asyncio
async def test_large_text_indexer(test_session, make_files_structure):
    """
    Large files have their indexes truncated.
    """
    large, = make_files_structure({
        'large_file.txt': 'foo ' * 1_000_000,
    })
    await lib.refresh_files()
    assert test_session.query(File).count() == 1

    assert large.is_file() and large.stat().st_size == 4_000_000

    large_file: File = test_session.query(File).one()
    assert len(large_file.d_text) < large.stat().st_size
    assert len(large_file.d_text) == 90_072


def test_glob_shared_stem(make_files_structure):
    mp4, png, j, name, video, something, vid2, vid2j = make_files_structure([
        'video.mp4',
        'video.png',
        'video.info.json',
        'video-name.txt',
        'video/',
        'something',
        'videos/video2 [name].mp4',
        'videos/video2 [name].info.json',
    ])

    def check(path, expected):
        assert sorted([i.name for i in lib.glob_shared_stem(path)]) == sorted(expected)

    check(mp4, ['video.mp4', 'video.png', 'video.info.json', 'video'])
    check(png, ['video.mp4', 'video.png', 'video.info.json', 'video'])
    check(j, ['video.mp4', 'video.png', 'video.info.json', 'video'])
    check(video, ['video.mp4', 'video.png', 'video.info.json', 'video'])

    check(something, ['something'])

    check(vid2, ['video2 [name].mp4', 'video2 [name].info.json'])
    check(vid2j, ['video2 [name].mp4', 'video2 [name].info.json'])


def test_matching_directories(make_files_structure, test_directory):
    make_files_structure([
        'foo/qux/',
        'Bar/',
        'baz/baz'
        'barr',
        'bazz',
    ])

    # No directories have c
    matches = lib.get_matching_directories(test_directory / 'c')
    assert matches == []

    # Get all directories starting with f
    matches = lib.get_matching_directories(test_directory / 'f')
    assert matches == [str(test_directory / 'foo')]

    # Get all directories starting with b, ignore case
    matches = lib.get_matching_directories(test_directory / 'b')
    assert matches == [str(test_directory / 'Bar'), str(test_directory / 'baz')]

    # baz matches, but it has no subdirectories
    matches = lib.get_matching_directories(test_directory / 'baz')
    assert matches == [str(test_directory / 'baz')]

    # foo is an exact match, return subdirectories
    matches = lib.get_matching_directories(test_directory / 'foo')
    assert matches == [str(test_directory / 'foo/qux')]


def test_pdf_indexer(example_pdf):
    """PDFs can be indexed by PDFIndexer."""
    file = File(path=example_pdf)

    a_text, b_text, c_text, d_text = indexers.PDFIndexer.create_index(file)

    # The title extracted from the PDF.
    assert a_text == 'WROLPi Test PDF'
    # The author.
    assert b_text == 'roland'
    # The parsed file name.
    assert c_text == ['example', 'pdf']
    # All pages are extracted.  Text is formatted to fit on vertical screen.
    assert d_text == 'Page one\n' \
                     'Page two\n' \
                     'Lorem ipsum dolor sit amet,\n' \
                     'consectetur adipiscing elit, sed do\n' \
                     'eiusmod tempor incididunt ut labore et\n' \
                     '\n' \
                     'dolore magna aliqua. Ut enim ad minim\n' \
                     'veniam, quis nostrud exercitation\n' \
                     'ullamco laboris nisi ut \n' \
                     'aliquip ex ea commodo consequat. Duis\n' \
                     'aute irure dolor in reprehenderit in\n' \
                     'voluptate velit esse cillum \n' \
                     'dolore eu fugiat nulla pariatur.\n' \
                     'Excepteur sint occaecat cupidatat non\n' \
                     'proident, sunt in culpa qui officia \n' \
                     'deserunt mollit anim id est laborum.'


def test_pdf_indexer_max_size(example_pdf):
    """The contents of a large PDF are not indexed."""
    example_pdf.write_bytes(example_pdf.read_bytes() * 5000)

    file = File(path=example_pdf)

    a_text, b_text, c_text, d_text = indexers.PDFIndexer.create_index(file)

    # The file name is still indexed.
    assert a_text == 'WROLPi Test PDF'
    assert d_text is None


def test_get_mimetype(example_epub, example_mobi, example_pdf, image_file, video_file):
    assert lib.get_mimetype(example_epub) == 'application/epub+zip'
    assert lib.get_mimetype(example_mobi) == 'application/x-mobipocket-ebook'
    assert lib.get_mimetype(example_pdf) == 'application/pdf'
    assert lib.get_mimetype(image_file) == 'image/jpeg'
    assert lib.get_mimetype(video_file) == 'video/mp4'
