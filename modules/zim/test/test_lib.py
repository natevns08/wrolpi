import datetime
from http import HTTPStatus

import pytest
from libzim import Entry

from modules.zim import lib
from modules.zim.errors import UnknownZim
from modules.zim.models import TagZimEntry, ZimSubscription
from wrolpi import tags, flags
from wrolpi.common import DownloadFileInfo
from wrolpi.downloader import Download, import_downloads_config, save_downloads_config
from wrolpi.files import lib as files_lib
from wrolpi.files.models import FileGroup


@pytest.mark.asyncio
async def test_get_zim(test_session, zim_path_factory):
    zim_path_factory()
    await files_lib.refresh_files()

    assert lib.get_zim(1)

    with pytest.raises(UnknownZim):
        assert lib.get_zim(2)


@pytest.mark.asyncio
async def test_zim_get_entry(test_session, zim_path_factory):
    zim_path_factory()
    await files_lib.refresh_files()

    entry: Entry = lib.get_entry('one', 1)
    assert entry.path == 'one'
    assert entry.title == 'One'
    assert bytes(entry.get_item().content).decode('UTF-8') == '''
             <html>
                 <head>
                     <title>One</title>
                 </head>
                 <body>
                     <h1>This is the first item</h1>
                 </body>
             </html>
             '''

    entry: Entry = lib.get_entry('home', 1)
    assert entry.path == 'home'
    assert entry.title == 'Homepage'


@pytest.mark.asyncio
async def test_zim_get_entries_tags(test_session, test_zim, tag_factory):
    tag1, tag2 = tag_factory('tag1'), tag_factory('tag2')
    test_zim.tag_entry(tag1.name, 'one')
    test_zim.tag_entry(tag2.name, 'one')
    test_zim.tag_entry(tag1.name, 'two')
    test_session.commit()

    assert lib.get_entries_tags(['one', 'two', 'home'], 1) \
           == dict(one=['tag1', 'tag2'], two=['tag1'], home=[])


def test_get_unique_paths():
    paths = ['A/Prickly_Pear', 'A/Prickly_pear', 'A/Prickly-pear', 'A/Arborescent_Prickly_Pear',
             'A/Arborescent_prickly_pear', 'A/Beavertail_prickly_pear', 'A/Brittle_prickly-pear',
             'A/Chenille_prickly-pear', 'A/Coastal_Prickly_Pear', 'A/Coastal_prickly_pear',
             'A/Prickly_pears_in_South_Africa', 'A/Prickly_Pear_Cays', 'A/Prickly_pears_in_Australia', 'A/Opuntia',
             'A/Prickly_Pear_(British_Virgin_Islands)', 'A/Prickly_Pear_Island', 'A/Prickly_Pears_(film)',
             'A/Invasive_succulent_plants_in_South_Africa', 'A/Cactoblastis_Memorial_Hall', 'A/Thomas_Harvey_Johnston']
    assert lib.get_unique_paths(*paths) == ['A/Prickly_Pear',
                                            'A/Arborescent_Prickly_Pear',
                                            'A/Beavertail_prickly_pear',
                                            'A/Brittle_prickly-pear',
                                            'A/Chenille_prickly-pear',
                                            'A/Coastal_Prickly_Pear',
                                            'A/Prickly_pears_in_South_Africa',
                                            'A/Prickly_Pear_Cays',
                                            'A/Prickly_pears_in_Australia',
                                            'A/Opuntia',
                                            'A/Prickly_Pear_(British_Virgin_Islands)',
                                            'A/Prickly_Pear_Island',
                                            'A/Prickly_Pears_(film)',
                                            'A/Invasive_succulent_plants_in_South_Africa',
                                            'A/Cactoblastis_Memorial_Hall',
                                            'A/Thomas_Harvey_Johnston']


def test_zim_tags_config(test_session, test_directory, test_zim, tag_factory, test_tags_config, fake_now):
    fake_now(datetime.datetime(2000, 1, 1, 0, 0, 0, 1))
    config = tags.get_tags_config()
    assert not config.tag_zims

    # Tag three Zim entries.
    tag1, tag2 = tag_factory('Tag1'), tag_factory('Tag2')
    test_zim.tag_entry(tag1.name, 'one')
    test_zim.tag_entry(tag2.name, 'one')
    test_zim.tag_entry(tag1.name, 'two')
    test_session.commit()
    # Tags are created in empty database.
    assert {i[0] for i in test_session.query(tags.Tag.id)} == {1, 2}

    config = tags.get_tags_config()
    assert config.tag_zims == [
        ['Tag1', test_zim.path.name, 'one', '2000-01-01T00:00:00.000001+00:00'],
        ['Tag2', test_zim.path.name, 'one', '2000-01-01T00:00:00.000001+00:00'],
        ['Tag1', test_zim.path.name, 'two', '2000-01-01T00:00:00.000001+00:00'],
    ]

    # Remove a tag, the config should change.
    test_zim.untag_entry(tag1.name, 'one')
    test_session.commit()

    config = tags.get_tags_config()
    assert config.tag_zims == [
        ['Tag2', test_zim.path.name, 'one', '2000-01-01T00:00:00.000001+00:00'],
        ['Tag1', test_zim.path.name, 'two', '2000-01-01T00:00:00.000001+00:00'],
    ]

    # Delete all Tags so they are recreated.
    test_session.query(tags.Tag).delete()
    # Delete all TagFileEntry(s), import them again.
    test_session.query(TagZimEntry).delete()
    test_session.commit()

    tags.import_tags_config()

    tag_zim_entries = test_session.query(TagZimEntry) \
        .order_by(TagZimEntry.zim_id, TagZimEntry.zim_entry)
    assert [(i.tag.name, i.zim.path, i.zim_entry) for i in tag_zim_entries] \
           == [('Tag2', test_zim.path, 'one'), ('Tag1', test_zim.path, 'two')]

    # Tags were recreated.
    assert {i[0] for i in test_session.query(tags.Tag.id)} == {3, 4}


def test_zim_all_entries(test_session, test_zim):
    entries = [i.__json__() for i in test_zim.all_entries]
    assert len(entries) == 12


@pytest.mark.asyncio
async def test_zim_download(test_session, kiwix_download_zim, test_directory, test_zim_bytes, flags_lock):
    await lib.subscribe('Wikipedia (with images)', 'es')

    # Downloading the catalog should lead to a new Zim file being downloaded.
    await kiwix_download_zim(expected_url='https://download.kiwix.org/zim/wikipedia/wikipedia_es_all_maxi_2023-06.zim')
    recurring_download, once_download = test_session.query(Download).order_by(Download.id).all()
    recurring_download: Download
    once_download: Download
    assert recurring_download.attempts == 1 and recurring_download.status == 'complete', \
        'Recurring download should have succeeded'
    assert not any([i[0] for i in test_session.query(Download.error)]), 'All downloads should have succeeded'
    assert (test_directory / 'zims/wikipedia_es_all_maxi_2023-06.zim').is_file()
    assert (test_directory / 'zims/wikipedia_es_all_maxi_2023-06.zim').stat().st_size
    assert once_download.attempts == 1

    # Download catalog again, should not re-download the existing file.
    recurring_download.status = 'new'
    test_session.commit()
    await kiwix_download_zim(expected_url='https://download.kiwix.org/zim/wikipedia/wikipedia_es_all_maxi_2023-06.zim',
                             download_file_side_effect=Exception('should not be called twice'))
    recurring_download, once_download = test_session.query(Download).order_by(Download.id).all()
    assert recurring_download.attempts == 2 and recurring_download.status == 'complete', \
        'Recurring download should have happened again'
    assert not any([i[0] for i in test_session.query(Download.error)]), 'All downloads should have succeeded'
    # New file was modeled into a FileGroup.
    assert test_session.query(FileGroup).count() == 1
    # No outdated files exist.
    assert not flags.outdated_zims.is_set()

    # Download catalog again, should fetch the latest file.
    recurring_download.status = 'new'
    test_session.commit()
    await kiwix_download_zim(expected_url='https://download.kiwix.org/zim/wikipedia/wikipedia_es_all_maxi_2024-01.zim',
                             download_info=DownloadFileInfo(
                                 status=HTTPStatus.OK,
                                 name='wikipedia_es_all_maxi_2024-01.zim',
                                 size=len(test_zim_bytes),
                             ),
                             hrefs=['?C=N;O=D', '?C=M;O=A', '?C=S;O=A', '?C=D;O=A', '/zim/',
                                    'wikipedia_es_all_maxi_2023-05.zim',
                                    'wikipedia_es_all_maxi_2023-06.zim',
                                    'wikipedia_es_all_maxi_2024-01.zim',  # The new Zim.
                                    'wikipedia_es_all_nopic_2023-05.zim',
                                    'wikipedia_es_all_nopic_2023-06.zim', ]
                             )
    recurring_download, first_download, second_download = test_session.query(Download).order_by(Download.id).all()
    assert recurring_download.attempts == 3 and recurring_download.status == 'complete', \
        'Recurring download should have happened again'
    assert not any([i[0] for i in test_session.query(Download.error)]), 'All downloads should have succeeded'
    assert (test_directory / 'zims/wikipedia_es_all_maxi_2023-06.zim').is_file()
    assert (test_directory / 'zims/wikipedia_es_all_maxi_2023-06.zim').stat().st_size
    assert (test_directory / 'zims/wikipedia_es_all_maxi_2024-01.zim').is_file()
    assert (test_directory / 'zims/wikipedia_es_all_maxi_2024-01.zim').stat().st_size
    # New file was modeled.
    assert test_session.query(FileGroup).count() == 2
    # But old file is now outdated.
    assert flags.outdated_zims.is_set()

    # Delete the outdated file.
    await lib.remove_outdated_zim_files()
    assert test_session.query(FileGroup).count() == 1
    # No longer outdated
    assert not flags.outdated_zims.is_set()


def test_zim_tag_migration(test_session, test_directory, zim_factory, tag_factory, test_tags_config):
    """When an outdated Zim file is deleted, the Tags should be moved to the latest Zim."""
    zim1 = zim_factory('wikipedia_en_all_maxi_2020-01.zim')  # The outdated Zim.
    zim2 = zim_factory('wikipedia_en_all_maxi_2020-02.zim')
    zim3 = zim_factory('wikipedia_en_all_maxi_2020-03.zim')  # The latest Zim.
    tag1, tag2 = tag_factory('tag1'), tag_factory('tag2')
    # Tag outdated Zim entries.
    zim1.tag_entry(tag1.name, 'home')
    zim1.tag_entry(tag2.name, 'one')
    # This should not be migrated.
    zim2.tag_entry(tag2.name, 'two')
    # Tag the latest Zim as well.
    zim3.tag_entry(tag2.name, 'one')
    test_session.commit()
    assert test_session.query(TagZimEntry).count() == 4

    # All Zims have been tagged.
    tags_config = tags.get_tags_config()
    tags_config.save_tags(session=test_session)
    assert 'wikipedia_en_all_maxi_2020-01.zim' in (config_text := tags_config.get_file().read_text())
    assert 'wikipedia_en_all_maxi_2020-02.zim' in config_text
    assert 'wikipedia_en_all_maxi_2020-03.zim' in config_text

    # Zim was deleted, as well as it's ZimTagEntry(s).
    zim1.delete()
    tags.import_tags_config(test_session)

    tag_zim_entries = sorted([(i.tag.name, i.zim.path, i.zim_entry) for i in test_session.query(TagZimEntry)])
    assert tag_zim_entries == [
        ('tag1', zim3.path, 'home'),
        ('tag2', zim2.path, 'two'),
        ('tag2', zim3.path, 'one'),  # Both "one" tags were combined.
    ]


@pytest.mark.parametrize(
    'url,expected',
    [
        ('https://download.kiwix.org/zim/wikipedia/wikipedia_arz_all_maxi_', ('Wikipedia (with images)', 'arz')),
        ('https://download.kiwix.org/zim/wikipedia/wikipedia_arz_all_nopic_', ('Wikipedia (no images)', 'arz')),
        ('https://download.kiwix.org/zim/wikipedia/wikipedia_ar_all_mini_', ('Wikipedia (mini)', 'ar')),
        ('https://download.kiwix.org/zim/wikiversity/wikiversity_zh_all_maxi_', ('Wikiversity (with images)', 'zh')),
        ('https://download.kiwix.org/zim/wikiversity/wikiversity_zh_all_nopic_', ('Wikiversity (no images)', 'zh')),
        ('https://download.kiwix.org/zim/wiktionary/wiktionary_eo_all_maxi_', ('Wikitionary (with images)', 'eo')),
        ('https://download.kiwix.org/zim/wiktionary/wiktionary_eo_all_nopic_', ('Wikitionary (no images)', 'eo')),
        ('https://download.kiwix.org/zim/wikibooks/wikibooks_es_all_nopic_', ('Wikibooks (no images)', 'es')),
        ('https://download.kiwix.org/zim/wikibooks/wikibooks_es_all_maxi_', ('Wikibooks (with images)', 'es')),
        ('https://download.kiwix.org/zim/wikisource/wikisource_bn_all_maxi_', ('Wikisource', 'bn')),
        ('https://download.kiwix.org/zim/vikidia/vikidia_ru_all_maxi_', ('Vikidia', 'ru')),
        ('https://download.kiwix.org/zim/stack_exchange/raspberrypi.stackexchange.com_en_all_',
         ('Raspberry Pi (Stack Exchange)', 'en')),
        ('https://download.kiwix.org/zim/stack_exchange/stackoverflow.com_en_all_',
         ('Stackoverflow (Stack Exchange)', 'en')),
        ('https://download.kiwix.org/zim/stack_exchange/ja.stackoverflow.com_ja_all_',
         ('Stackoverflow (Stack Exchange)', 'ja')),
        ('https://download.kiwix.org/zim/stack_exchange/superuser.com_en_all_', ('Superuser (Stack Exchange)', 'en')),
        ('https://download.kiwix.org/zim/ifixit/ifixit_nl_all_', ('iFixit', 'nl')),
        ('https://download.kiwix.org/zim/gutenberg/gutenberg_ang_all_', ('Gutenberg', 'ang')),
        ('https://download.kiwix.org/zim/stack_exchange/ham.stackexchange.com_en_all_',
         ('Amateur Radio (Stack Exchange)', 'en'))
    ]
)
def test_zim_download_url_to_name(url, expected):
    assert lib.zim_download_url_to_name(url) == expected


@pytest.mark.asyncio
async def test_zim_subscription_download_import(test_session, test_downloader_config):
    # Subscription creates a ZimSubscription and Download
    await lib.subscribe('Wikisource', 'en', session=test_session)
    # Add a once-download.  This should not be associated with a ZimSubscription.
    test_session.add(
        Download(url='https://download.kiwix.org/zim/wikibooks/wikibooks_en_all_maxi_2021-03.zim', status='complete'))
    test_session.commit()
    download = test_session.query(Download).filter(Download.frequency.isnot(None)).one()
    assert download.url == 'https://download.kiwix.org/zim/wikisource/wikisource_en_all_maxi_'

    # Save config file, delete all entries.
    await save_downloads_config()
    test_session.query(Download).delete()
    test_session.query(ZimSubscription).delete()
    test_session.commit()

    for _ in range(1):  # Import twice.
        # Importing the config restores the Download and ZimSubscription.
        await import_downloads_config(session=test_session)
        recurring, once = test_session.query(Download).order_by(Download.frequency)
        assert once.url == 'https://download.kiwix.org/zim/wikibooks/wikibooks_en_all_maxi_2021-03.zim'
        assert test_session.query(Download).count() == 2
        assert recurring.url == 'https://download.kiwix.org/zim/wikisource/wikisource_en_all_maxi_'
        assert recurring.frequency
        subscription: ZimSubscription = test_session.query(ZimSubscription).one()
        assert subscription.download_id == recurring.id
        assert subscription.name == 'Wikisource'
        assert subscription.language == 'en'
