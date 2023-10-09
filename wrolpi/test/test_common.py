import asyncio
import ctypes.wintypes
import json
import multiprocessing
import os
import pathlib
import tempfile
from datetime import date, datetime
from decimal import Decimal
from itertools import zip_longest
from time import sleep
from unittest import mock

import pytest
import pytz

import wrolpi.vars
from wrolpi import common
from wrolpi.common import cum_timer, TIMERS, print_timer, limit_concurrent, run_after
from wrolpi.test.common import build_test_directories


def test_build_video_directories(test_directory):
    structure = [
        'channel1/vid1.mp4',
    ]
    with build_test_directories(structure) as tempdir:
        assert (tempdir / 'channel1').is_dir()
        assert (tempdir / 'channel1/vid1.mp4').is_file()

    structure = [
        'channel2/',
        'channel2.1/channel2.2/',
    ]
    with build_test_directories(structure) as tempdir:
        assert (tempdir / 'channel2').is_dir()
        assert (tempdir / 'channel2.1/channel2.2').is_dir()

    structure = [
        'channel3/vid1.mp4',
        'channel3/vid2.mp4',
        'channel4/vid1.mp4',
        'channel4/vid1.en.vtt',
        'channel5/',
    ]
    with build_test_directories(structure) as tempdir:
        assert (tempdir / 'channel3/vid1.mp4').is_file()
        assert (tempdir / 'channel3').is_dir()
        assert (tempdir / 'channel3/vid2.mp4').is_file()
        assert (tempdir / 'channel4/vid1.mp4').is_file()
        assert (tempdir / 'channel4/vid1.en.vtt').is_file()
        assert (tempdir / 'channel5').is_dir()

    structure = [
        'channel6/subdirectory/vid1.mp4',
    ]
    with build_test_directories(structure) as tempdir:
        assert (tempdir / 'channel6/subdirectory').is_dir()
        assert (tempdir / 'channel6/subdirectory/vid1.mp4').is_file()


def test_insert_parameter():
    """
    A convenience function exists that inserts a parameter or keyword argument into the provided args/kwargs,
    wherever that may be according to the function's signature.
    """

    def func(foo, bar):
        pass

    results = common.insert_parameter(func, 'bar', 'bar', (1,), {})
    assert results == ((1, 'bar'), {})

    def func(foo, bar, baz):
        pass

    results = common.insert_parameter(func, 'bar', 'bar', (1, 2), {})
    assert results == ((1, 'bar', 2), {})

    def func(foo, baz, bar=None):
        pass

    results = common.insert_parameter(func, 'bar', 'bar', (1, 2), {})
    assert results == ((1, 2, 'bar'), {})

    def func(foo, baz, bar=None):
        pass

    results = common.insert_parameter(func, 'baz', 'baz', (1, 2), {})
    assert results == ((1, 'baz', 2), {})

    def func(foo, baz, qux=None, bar=None):
        pass

    results = common.insert_parameter(func, 'bar', 'bar', (1, 2, 3), {})
    assert results == ((1, 2, 3, 'bar'), {})

    # bar is not defined as a parameter!
    def func(foo):
        pass

    pytest.raises(TypeError, common.insert_parameter, func, 'bar', 'bar', (1,), {})


def test_date_range():
    # A single step results in the start.
    result = common.date_range(date(1970, 1, 1), date(1970, 1, 2), 1)
    assert result == [
        date(1970, 1, 1),
    ]

    # Many steps on a single day results in the same day.
    result = common.date_range(date(1970, 1, 1), date(1970, 1, 1), 5)
    assert result == [
        date(1970, 1, 1),
        date(1970, 1, 1),
        date(1970, 1, 1),
        date(1970, 1, 1),
        date(1970, 1, 1),
    ]

    # Many steps on a single datetime results in a range of times.
    result = common.date_range(datetime(1970, 1, 1), datetime(1970, 1, 1, 23, 59, 59), 5)
    assert result == [
        datetime(1970, 1, 1, 0, 0),
        datetime(1970, 1, 1, 4, 47, 59, 800000),
        datetime(1970, 1, 1, 9, 35, 59, 600000),
        datetime(1970, 1, 1, 14, 23, 59, 400000),
        datetime(1970, 1, 1, 19, 11, 59, 200000),
    ]

    # common.date_range is not inclusive, like range().
    result = common.date_range(date(1970, 1, 1), date(1970, 1, 5), 4)
    assert result == [
        date(1970, 1, 1),
        date(1970, 1, 2),
        date(1970, 1, 3),
        date(1970, 1, 4),
    ]

    # Reversed dates are supported.
    result = common.date_range(date(1970, 1, 5), date(1970, 1, 1), 4)
    assert result == [
        date(1970, 1, 5),
        date(1970, 1, 4),
        date(1970, 1, 3),
        date(1970, 1, 2),
    ]

    # Large date spans are supported.
    result = common.date_range(date(1970, 1, 1), date(2020, 5, 1), 4)
    assert result == [
        date(1970, 1, 1),
        date(1982, 8, 1),
        date(1995, 3, 2),
        date(2007, 10, 1),
    ]

    result = common.date_range(datetime(1970, 1, 1, 0, 0, 0), datetime(1970, 1, 1, 10, 0), 8)
    assert result == [
        datetime(1970, 1, 1, 0, 0),
        datetime(1970, 1, 1, 1, 15),
        datetime(1970, 1, 1, 2, 30),
        datetime(1970, 1, 1, 3, 45),
        datetime(1970, 1, 1, 5, 0),
        datetime(1970, 1, 1, 6, 15),
        datetime(1970, 1, 1, 7, 30),
        datetime(1970, 1, 1, 8, 45),
    ]

    # More steps than days
    result = common.date_range(date(1970, 1, 1), date(1970, 1, 7), 10)
    assert result == [
        date(1970, 1, 1),
        date(1970, 1, 1),
        date(1970, 1, 2),
        date(1970, 1, 2),
        date(1970, 1, 3),
        date(1970, 1, 4),
        date(1970, 1, 4),
        date(1970, 1, 5),
        date(1970, 1, 5),
        date(1970, 1, 6),
    ]


@pytest.mark.parametrize(
    'i,expected', [
        (1, 1),
        (100, 100),
        (150, 100),
        (-1, -1),
        (-1.0, -1.0),
        (1.0, 1.0),
        (100.0, 100.0),
        (150.0, 100.0),
        ('1', 1),
        (None, 20),
        (0, 20),
        (0.0, 20),
        ('', 20),
    ]
)
def test_api_param_limiter(i, expected):
    limiter = common.api_param_limiter(100)  # should never return an integer greater than 100.
    assert limiter(i) == expected


def test_chdir():
    """
    The current working directory can be changed temporarily using the `chdir` context manager.
    """
    original = os.getcwd()
    home = os.environ.get('HOME')
    assert home

    with common.chdir():
        assert os.getcwd() != original
        assert str(os.getcwd()).startswith('/tmp')
        assert os.environ['HOME'] != os.getcwd()
    # Replace $HOME
    with common.chdir(with_home=True):
        assert os.getcwd() != original
        assert str(os.getcwd()).startswith('/tmp')
        assert os.environ['HOME'] == os.getcwd()

    with tempfile.TemporaryDirectory() as d:
        # Without replacing $HOME
        with common.chdir(pathlib.Path(d), with_home=True):
            assert os.getcwd() == d
            assert os.environ['HOME'] == os.getcwd()
        with common.chdir(pathlib.Path(d)):
            assert os.getcwd() == d
            assert os.environ['HOME'] != os.getcwd()


@pytest.mark.parametrize('low,high,expected', [
    (0, 10000, [0, 5000, 2500, 7500, 1250, 3750, 6250, 8750, 625, 1875, 3125, 4375, 5625, 6875, 8125, 9375]),
    (0, 1000, [0, 500, 250, 750, 125, 375, 625, 875, 62, 187, 312, 437, 562, 687, 812, 937]),
    (0, 100, [0, 50, 25, 75, 12, 37, 62, 87, 6, 18, 31, 43, 56, 68, 81, 93]),
    # Values repeat when there are not enough.
    (0, 10, [0, 5, 2, 7, 1, 3, 6, 8, 0, 1, 3, 4, 5, 6, 8, 9]),
    (0, 5, [0, 2, 1, 3, 0, 1, 3, 4]),
    (0, 2, [0, 1, 0, 1, 0, 0, 1, 1, 0, 0, 0, 0, 1, 1, 1, 1]),
    (50, 100, [50, 75, 62, 87, 56, 68, 81, 93, 53, 59, 65]),
    (8, 98, [8, 53, 30, 75, 19, 41, 64]),
    # Floats are supported.  Output is identical to above.
    (50.0, 100.0, [50.0, 75.0, 62.5, 87.5, 56.25, 68.75, 81.25, 93.75, 53.125, 59.375, 65.625]),
    # Decimals are supported.  Output is identical to above.
    (Decimal('50.0'), Decimal('100.0'), [
        Decimal('50'), Decimal('75'), Decimal('62.5'), Decimal('87.5'), Decimal('56.25'), Decimal('68.75'),
        Decimal('81.25'), Decimal('93.75'), Decimal('53.125'), Decimal('59.375'), Decimal('65.625')
    ]),
    # Datetimes are supported.
    (datetime(2000, 1, 1, tzinfo=pytz.UTC), datetime(2000, 1, 8, tzinfo=pytz.UTC), [
        datetime(2000, 1, 1, tzinfo=pytz.UTC), datetime(2000, 1, 4, 12, tzinfo=pytz.UTC),
        datetime(2000, 1, 2, 18, tzinfo=pytz.UTC), datetime(2000, 1, 6, 6, tzinfo=pytz.UTC),
        datetime(2000, 1, 1, 21, tzinfo=pytz.UTC), datetime(2000, 1, 3, 15, tzinfo=pytz.UTC),
    ])
])
def test_zig_zag(low, high, expected):
    zagger = common.zig_zag(low, high)
    for i in expected:
        result = next(zagger)
        assert result == i
        assert low <= result < high


@pytest.mark.parametrize(
    'name,expected', [
        ('', ''),
        ('foo', 'foo'),
        ('foo\\', 'foo'),
        ('foo/', 'foo'),
        ('foo<', 'foo'),
        ('foo>', 'foo'),
        ('foo:', 'foo'),
        ('foo|', 'foo'),
        ('foo"', 'foo'),
        ('foo?', 'foo'),
        ('foo*', 'foo'),
        ('foo&', 'foo&'),
        ('foo%', 'foo'),
        ('foo!', 'foo'),
        ('fo\no', 'foo'),
        ('fo\ro', 'foo'),
        ('fo\n\no\n', 'foo'),
        ('fo\r\ro\r', 'foo'),
        ('foo ', 'foo'),
        ('foo ', 'foo'),
        # Some whitespace characters are preserved as spaces.
        ('fo\to', 'fo o'),
        ('fo\t\to\t', 'fo o'),
        ('fo  o', 'fo o'),
        ('fo   o', 'fo o'),
        ('fo    o', 'fo o'),
    ]
)
def test_escape_file_name(name, expected):
    result = common.escape_file_name(name)
    if result != expected:
        raise AssertionError(f'Escape of {repr(name)}: {repr(result)} != {repr(expected)}')


@pytest.mark.parametrize(
    'paths,suffix_groups,expected', [
        ([], [], ()),
        (['foo.mp4', 'foo.info.json'], [('.mp4',)], ('foo.mp4',)),
        (['foo.mp4', 'foo.info.json'], [('.mp4',), ('.info.json',)], ('foo.mp4', 'foo.info.json')),
        (['foo.mp4', 'foo.info.json'], [('.mp4',), ('.nope',), ('.info.json',)], ('foo.mp4', None, 'foo.info.json')),
        (['foo.mp4', 'foo.info.json', 'extra.txt'], [('.mp4',)], ('foo.mp4',)),
        (['foo.mp4'], [('.mp4', '.flv'), ('.info.json',)], ('foo.mp4', None)),
        (
                # Two files are matched to the closest suffix.
                ['foo.info.json', 'bar.json'],
                [('.info.json',), ('.json',)],  # TODO longest suffix must be first
                ('foo.info.json', 'bar.json'),
        ),
    ]
)
def test_match_paths_to_suffixes(paths, suffix_groups, expected):
    paths = [pathlib.Path(i) for i in paths]
    expected = tuple(pathlib.Path(i) if i else None for i in expected)
    assert (i := common.match_paths_to_suffixes(paths, suffix_groups)) == expected, f'{i} != {expected}'


def test_truncate_object_bytes():
    """
    Objects can be truncated (lists will be shortened) so they will fit in tsvector columns.
    """
    assert common.truncate_object_bytes(['foo'] * 10, 100) == ['foo'] * 5
    assert common.truncate_object_bytes(['foo'] * 1_000, 100) == ['foo'] * 5
    assert common.truncate_object_bytes(['foo'] * 1_000_000, 100) == ['foo'] * 5
    assert common.truncate_object_bytes(['foo'] * 1_000_000, 200) == ['foo'] * 14
    assert common.truncate_object_bytes([], 200) == []

    assert common.truncate_object_bytes(None, 100) is None
    assert common.truncate_object_bytes('', 100) == ''

    assert common.truncate_object_bytes('foo' * 100, 99) == 'foofoofoofoofoofoofoofoofoofoofoofoofoof'
    assert common.truncate_object_bytes('foo' * 100, 80) == 'foofoofoofoofoofoofoofoofo'
    assert common.truncate_object_bytes('foo' * 100, 55) == 'foofo'
    assert common.truncate_object_bytes('foo' * 100, 51) == 'f'
    assert common.truncate_object_bytes('foo' * 100, 50) == ''
    assert common.truncate_object_bytes('foo' * 100, 0) == ''


def test_truncate_generator_bytes():
    """A generator can be truncated."""

    def generator():
        for _ in range(5):
            yield 'foo'
        raise ValueError('Truncate should not get here')

    assert list(common.truncate_generator_bytes(generator(), 80)) == ['foo', 'foo']
    assert list(common.truncate_generator_bytes(generator(), 200)) == ['foo', 'foo', 'foo', 'foo']


def test_check_media_directory(test_directory):
    """The directory provided by the test_directory fixture is a valid media directory."""
    assert common.check_media_directory() is True


def test_bad_check_media_directory():
    """/dev/full is not a valid media directory, warnings are issued and the check fails."""
    with mock.patch('wrolpi.common.get_media_directory') as mock_get_media_directory:
        mock_get_media_directory.return_value = pathlib.Path('/dev/full')
        assert common.check_media_directory() is False


def test_chunks_by_stem(test_directory, make_files_structure):
    """`chunks_by_stem` breaks a list of paths on the name change close to the size."""
    with pytest.raises(ValueError):
        assert list(common.chunks_by_stem([], 0)) == [[]]

    assert list(common.chunks_by_stem([], 5)) == [[]]
    assert list(common.chunks_by_stem([1, 2, 3], 5)) == [[1, 2, 3]]

    files = make_files_structure([
        'foo.mp4', 'foo.txt', 'foo.png', 'foo.info.json',
        'bar.mp4', 'bar.readability.txt', 'bar.jpeg', 'bar.info.json',
        'baz.mp4', 'baz.txt', 'baz.jpg', 'baz.info.json',
        'qux.mp4', 'qux.txt', 'qux.tif', 'qux.info.json',
    ])

    def assert_chunks(size, files_, expected):
        for chunk, expected_chunk in zip_longest(list(common.chunks_by_stem(files_, size)), expected):
            assert chunk == [test_directory / i for i in expected_chunk]

    assert_chunks(8, files, [
        ['bar.info.json', 'bar.jpeg', 'bar.mp4', 'bar.readability.txt',
         'baz.info.json', 'baz.jpg', 'baz.mp4', 'baz.txt',
         'foo.info.json', 'foo.mp4', 'foo.png', 'foo.txt'],
        ['qux.info.json', 'qux.mp4', 'qux.tif', 'qux.txt'],
    ])

    assert_chunks(6, files, [
        ['bar.info.json', 'bar.jpeg', 'bar.mp4', 'bar.readability.txt',
         'baz.info.json', 'baz.jpg', 'baz.mp4', 'baz.txt'],
        ['foo.info.json', 'foo.mp4', 'foo.png', 'foo.txt',
         'qux.info.json', 'qux.mp4', 'qux.tif', 'qux.txt'],
    ])

    assert_chunks(5, files, [
        ['bar.info.json', 'bar.jpeg', 'bar.mp4', 'bar.readability.txt',
         'baz.info.json', 'baz.jpg', 'baz.mp4', 'baz.txt'],
        ['foo.info.json', 'foo.mp4', 'foo.png', 'foo.txt',
         'qux.info.json', 'qux.mp4', 'qux.tif', 'qux.txt'],
    ])

    assert_chunks(3, files, [
        ['bar.info.json', 'bar.jpeg', 'bar.mp4', 'bar.readability.txt'],
        ['baz.info.json', 'baz.jpg', 'baz.mp4', 'baz.txt'],
        ['foo.info.json', 'foo.mp4', 'foo.png', 'foo.txt'],
        ['qux.info.json', 'qux.mp4', 'qux.tif', 'qux.txt'],
    ])

    assert_chunks(1, files, [
        ['bar.info.json', 'bar.jpeg', 'bar.mp4', 'bar.readability.txt'],
        ['baz.info.json', 'baz.jpg', 'baz.mp4', 'baz.txt'],
        ['foo.info.json', 'foo.mp4', 'foo.png', 'foo.txt'],
        ['qux.info.json', 'qux.mp4', 'qux.tif', 'qux.txt'],
    ])

    files = make_files_structure(['1.mp4', '1.txt', '2.mp4', '2.txt', '2.png', '3.mp4'])
    assert_chunks(1, files, [['1.mp4', '1.txt'], ['2.mp4', '2.png', '2.txt'], ['3.mp4']])
    assert_chunks(3, files, [['1.mp4', '1.txt', '2.mp4', '2.png', '2.txt'], ['3.mp4']])
    assert_chunks(6, files, [['1.mp4', '1.txt', '2.mp4', '2.png', '2.txt', '3.mp4']])
    assert_chunks(20, files, [['1.mp4', '1.txt', '2.mp4', '2.png', '2.txt', '3.mp4']])


@pytest.mark.parametrize(
    'value,expected', [
        ('true', True),
        ('t', True),
        ('True', True),
        ('1', True),
        ('yes', True),
        ('y', True),
        ('no', False),
        ('n', False),
        ('0', False),
        ('False', False),
        ('false', False),
        ('f', False),
        ('other', False),
        ('trust', False),
        ('', False),
        (None, False),
    ]
)
def test_truthy_arg(value, expected):
    assert wrolpi.vars.truthy_arg(value) is expected, f'{value} != {expected}'


@pytest.mark.asyncio
async def test_cum_timer():
    """`cum_timer` can be used to profile code."""
    print_timer()

    with cum_timer('test_cum_timer'):
        await asyncio.sleep(0.1)
    assert TIMERS.get('test_cum_timer')
    total, calls = TIMERS['test_cum_timer']
    assert total > 0
    assert calls == 1

    print_timer()


@pytest.mark.asyncio
async def test_limit_concurrent_async():
    """`limit_concurrent` can throw an error when the limit is reached."""

    @limit_concurrent(1)
    async def sleeper():
        await asyncio.sleep(1)

    # `throw` was not defined.
    await asyncio.gather(sleeper(), sleeper())

    @limit_concurrent(1, throw=True)
    async def sleeper():
        await asyncio.sleep(1)

    # One is acceptable.
    await asyncio.gather(sleeper())

    with pytest.raises(ValueError) as e:
        # Two will throw.
        await asyncio.gather(sleeper(), sleeper())
    assert 'concurrent limit' in str(e)


def test_limit_concurrent_sync():
    """`limit_concurrent` can throw an error when the limit is reached."""

    count = multiprocessing.Value('i', 0)
    assert count.value == 0

    @limit_concurrent(1)
    def sleeper():
        sleep(1)
        count.value += 1

    # One is acceptable.
    sleeper()
    assert count.value == 1

    error_value = multiprocessing.Value(ctypes.c_bool)
    assert error_value.value is False

    def sleeper_wrapper():
        try:
            sleeper()
        except ValueError as e:
            error_value.value = 'concurrent limit' in str(e)

    def run():
        count.value = 0
        p1 = multiprocessing.Process(target=sleeper_wrapper)
        p2 = multiprocessing.Process(target=sleeper_wrapper)
        p1.start()
        p2.start()
        p1.join()
        p2.join()

    # `throw` is not defined, only one wrapper runs.
    run()
    assert error_value.value is False
    # Only one counted.
    assert count.value == 1

    @limit_concurrent(1, throw=True)
    def sleeper():
        sleep(1)
        count.value += 1

    error_value.value = False
    assert error_value.value is False

    # Error was thrown.
    run()
    assert error_value.value is True
    assert count.value == 1


@pytest.mark.asyncio
async def test_run_after():
    """`run_after` wrapper will run a function asynchronously after the wrapped function completes."""
    count = multiprocessing.Value(ctypes.c_int, 0)

    def counter():
        count.value += 1

    with mock.patch('wrolpi.common.RUN_AFTER', True):
        @run_after(counter)
        async def foo():
            await asyncio.sleep(0)
            return 'yup'

    # Test async wrapped and after.
    assert await foo() == 'yup', 'Did not get the returned value'
    # Sleep so "after" will run.
    await asyncio.sleep(0)
    assert count.value == 1, 'Counter did not run after'

    with mock.patch('wrolpi.common.RUN_AFTER', True):
        @run_after(counter)
        def foo():
            return 'good'

    # Test sync wrapped and after.
    assert foo() == 'good', 'Did not get the returned value'
    # Sleep so "after" will run.
    await asyncio.sleep(0)
    assert count.value == 2, 'Counter did not run after'


@pytest.mark.parametrize(
    'max_line_length,text,expected', [
        (38, '', ''),
        (38, 'Lorem', 'Lorem'),
        (
                38,
                'Lorem ipsum dolor sit amet, consectetur adipiscing elit, sed do',
                'Lorem ipsum dolor sit amet,\nconsectetur adipiscing elit, sed do'
        ),
        (
                10,
                'Lorem ipsum dolor sit amet, consectetur adipiscing elit, sed do',
                'Lorem\nipsum\ndolor sit\namet,\nconsectetur\nadipiscing\nelit, sed\ndo'
        ),
        (
                20,
                'Lorem\nipsum\ndolor   sit amet,\t\tconsectetur\n\nadipiscing elit, sed do',
                'Lorem\nipsum\ndolor sit amet,\nconsectetur\n\nadipiscing elit,\nsed do'
        ),
        (
                38,
                'Lorem ipsum dolor sit amet, consectetur adipiscing elit, sed do eiusmod tempor incididunt ut labore et dolore magna aliqua.',
                'Lorem ipsum dolor sit amet,\nconsectetur adipiscing elit, sed do\neiusmod tempor incididunt ut labore et\ndolore magna aliqua.'
        ),
        (38, 'long-word-which-should-not-be-split-up', 'long-word-which-should-not-be-split-up'),
    ]
)
def test_split_lines_by_length(max_line_length, text, expected):
    assert common.split_lines_by_length(text, max_line_length=max_line_length) == expected


@pytest.mark.parametrize(
    'obj,expected', [
        ([0, ], [0, ]),
        (range(1), [0, ]),
        ({'a': 'b'}, {'a': 'b'}),
        ({'a': range(1, 3)}, {'a': [1, 2]}),
        ((1, 2, 3), (1, 2, 3)),
        ({3, 4, 5}, {3, 4, 5}),
    ]
)
def test_resolve_generators(obj, expected):
    assert common.resolve_generators(obj) == expected


def test_resolve_generators2():
    def gen2():
        yield {'hello': 'world'}
        yield {'this': 'that'}

    def gen1():
        yield 'hello'
        yield {
            'entries': gen2(),
        }

    obj = {
        'foo': 'bar',
        'entries': gen1(),
    }
    assert common.resolve_generators(obj) == {
        'foo': 'bar',
        'entries': [
            'hello',
            {
                'entries': [
                    {'hello': 'world'},
                    {'this': 'that'},
                ]
            }
        ]
    }


@pytest.mark.parametrize(
    'url,expected', [
        ('https://example.com', '/'),
        ('https://example.com/foo', '/foo'),
        ('https://example.com/foo?question=answer', '/foo?question=answer'),
        ('https://example.com/foo?question=answer#fragment', '/foo?question=answer#fragment'),
        ('https://exmaple.com/files?folders=test+%23+example%2F', '/files?folders=test+%23+example%2F'),
        ('https://exmaple.com/files?folders=test+%23+example%2F&folders=map%2F',
         '/files?folders=test+%23+example%2F&folders=map%2F'),
    ]
)
def test_url_strip_host(url, expected):
    assert common.url_strip_host(url) == expected


@pytest.mark.parametrize(
    'search_str,expected', [
        ('jump', [('<b>jumps</b> over the lazy brown', 0.06079271), ('<b>jumped</b> over the lazy', 0.06079271)]),
        ('brown', [('over the lazy <b>brown</b>', 0.06079271), ('The fox jumped over the lazy dog', 0.0)]),
    ]
)
def test_extract_headlines(test_session, search_str, expected):
    entries = [
        'The fox jumps over the lazy brown dog.',
        'The fox jumped over the lazy dog.',
    ]
    assert common.extract_headlines(entries, search_str) == expected


def test_extract_html_text():
    html = '''<html>

<script>
// This should be ignored.
console.log('hello');
</script>

<body>
    <h1>Header</h1>
    <p>Word word word word word word word word word</p>
    <ul>
        <li>Item 1</li>
        <li>Item 2</li>
    </ul>
    <p>Another example paragraph</p>
    Paragraph outside an element.
</body>
</html>'''
    assert common.extract_html_text(html) == '''Header
Word word word word word word word word word
Item 1
Item 2
Another example paragraph
Paragraph outside an element.'''


@pytest.mark.parametrize(
    'bps,expected', [
        (100, '100 bps'),
        (2000, '2 Kbps'),
        (7777777, '7 Mbps'),
        (777777777, '777 Mbps'),
        (7777777777, '7 Gbps'),
        (77777777777, '77 Gbps'),
    ]
)
def test_human_bandwidth(bps, expected):
    assert common.human_bandwidth(bps) == expected


def test_format_json_file():
    with tempfile.TemporaryDirectory() as d:
        with tempfile.NamedTemporaryFile(suffix='.json', dir=d) as fh:
            file = pathlib.Path(fh.name)
            file.write_text(json.dumps({
                'one': 1,
                'two': 2,
                'three': 3,
                'four': 4,
                'five': 5,
                'six': 6,
                'seven': 7,
                'eight': 8,
                'nine': 9,
                'ten': 10,
            }))
            # Only one file was created.
            assert len(list(file.parent.iterdir())) == 1

            unformatted = '{"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10}'
            assert file.read_text() == unformatted

            common.format_json_file(file)
            assert file.read_text() == '''{
  "one": 1,
  "two": 2,
  "three": 3,
  "four": 4,
  "five": 5,
  "six": 6,
  "seven": 7,
  "eight": 8,
  "nine": 9,
  "ten": 10
}'''
            # The copy was deleted.
            assert len(list(file.parent.iterdir())) == 1


def test_format_html_file():
    with tempfile.NamedTemporaryFile() as fh:
        file = pathlib.Path(fh.name)
        unformatted = '<html><!--Comment--><head><title>Title</title><body>Body</body></html>'
        file.write_text(unformatted)

        assert file.read_text() == unformatted

        common.format_html_file(file)
        assert file.read_text() == '''<html>
 <!--Comment-->
 <head>
  <title>
   Title
  </title>
 </head>
 <body>
  Body
 </body>
</html>
'''


@pytest.mark.parametrize(
    'iterable,length,step,expected',
    [
        ([1, 2, 3, 4], 1, None, [[1], [2], [3], [4]]),
        ([1, 2, 3, 4], 2, None, [[1, 2], [2, 3], [3, 4]]),
        ([1, 2, 3, 4], 3, None, [[1, 2, 3], [2, 3, 4]]),
        # More length than items yield the original iterable.
        ([1, 2, 3, 4], 5, None, [[1, 2, 3, 4], ]),
        # Can handle empty lists.
        ([], 2, None, []),
        # Type inputted matches output.
        ((1, 2, 3, 4), 2, None, [(1, 2), (2, 3), (3, 4)]),
    ]
)
def test_chain(iterable, length, step, expected):
    assert list(common.chain(iterable, length)) == expected
