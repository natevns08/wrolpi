import json
from http import HTTPStatus

import pytest

from modules.zim import lib
from modules.zim.models import Zim
from wrolpi.downloader import Download


def test_zim_search(test_client, test_session, test_zim, tag_factory, assert_zim_search):
    """Entries can be tagged and retrieved using their containing Zim."""
    tag1, tag2 = tag_factory(), tag_factory()
    test_zim.tag_entry(tag1.name, 'one')
    test_zim.tag_entry(tag2.name, 'one')
    test_zim.tag_entry(tag1.name, 'two')
    test_session.commit()

    # Test searching with only `search_str`.
    assert_zim_search('one', 1, {
        'path': test_zim.path,
        'search': [
            # Entry "One" contains a 'one' in the title, and the text.
            {'path': 'one', 'headline': 'This is the first item', 'rank': 0.06079271},
            # Home only contains one 'one'.
            {'path': 'home', 'rank': 0.06079271, 'headline': 'file for testing.\n<b>One</b>', },
        ],
        'estimate': 2,
    })
    assert_zim_search('two', 1, {
        'path': test_zim.path,
        'search': [{'path': 'two', 'headline': 'This is the second item', 'rank': 0.06079271},
                   {'path': 'home', 'headline': 'testing.\nOne\n<b>Two</b>', 'rank': 0.06079271}],
        'estimate': 2,
    })
    assert_zim_search('item', 1, {
        'path': test_zim.path,
        'search': [{'path': 'one', 'headline': 'first <b>item</b>', 'rank': 0.06079271},
                   {'path': 'two', 'headline': 'second <b>item</b>', 'rank': 0.06079271}],
        'estimate': 2,
    })

    # Test searching with `search_str` and `tag_names`.
    assert_zim_search('one', 1, tag_names=[tag2.name, ], expected={
        'search': [
            # Only entry "One" is tagged with Tag 2.
            {'path': 'one', 'headline': 'This is the first item', 'rank': 0.06079271},
        ],
        'estimate': 1,
    })
    assert_zim_search('one', 1, tag_names=[tag1.name, tag2.name], expected={
        'search': [
            # Only "One" is tagged with Tag 1 and contains "one".
            {'path': 'one', 'headline': 'This is the first item', 'rank': 0.06079271},
        ],
        'estimate': 1,
    })
    assert_zim_search('two', 1, tag_names=[tag1.name, ], expected={
        'search': [
            # Only "Two" was tagged with Tag 1 and contains "two".
            {'path': 'two', 'headline': 'This is the second item', 'rank': 0.06079271},
        ],
        'estimate': 1,
    })
    assert_zim_search('two', 1, tag_names=[tag2.name, ], expected={
        # Two was not tagged with Tag 1.
        'search': [],
        'estimate': 0,
    })

    # Test search with only `tag_names`.
    assert_zim_search('', 1, tag_names=[tag1.name, tag2.name], expected={
        'search': [
            # Return all entries that are tagged with the Tags.
            {'path': 'one', 'headline': 'This is the first item', 'rank': 0.0, 'tag_names': ['one', 'two']},
        ],
        'estimate': 1,
    })


def test_entries_by_tag(test_client, test_session, test_zim, tag_factory):
    """Entries can be tagged and retrieved using their containing Zim."""
    tag1, tag2 = tag_factory(), tag_factory()
    test_zim.tag_entry(tag1.name, 'one')
    test_zim.tag_entry(tag2.name, 'one')
    test_zim.tag_entry(tag1.name, 'two')
    test_session.commit()

    result = test_zim.entries_with_tags([tag1.name, tag2.name])
    assert [(i.path, i.title) for i in result] == [('one', 'One'), ]

    result = test_zim.entries_with_tags([tag1.name, ])
    assert [(i.path, i.title) for i in result] == [('one', 'One'), ('two', 'Two')]

    result = test_zim.entries_with_tags([tag2.name, ])
    assert [(i.path, i.title) for i in result] == [('one', 'One'), ]


def test_zim_crud(test_client, test_session, test_directory, test_zim):
    request, response = test_client.get('/api/zim')
    assert response.status_code == HTTPStatus.OK
    assert len(response.json['zims']) == 1
    assert response.json['zims'][0]['path'] == test_zim.path.name

    request, response = test_client.delete('/api/zim/1')
    assert response.status_code == HTTPStatus.NO_CONTENT
    assert not test_zim.path.exists()
    assert test_session.query(Zim).count() == 0


def test_zim_tag_and_untag(test_client, test_session, test_zim, tag_factory):
    """Zim entries can be Tagged and Untagged."""
    tag1, tag2 = tag_factory(), tag_factory()
    test_session.commit()

    # Entries can be tagged in the API.
    content = dict(tag_name=tag1.name, zim_id=test_zim.id, zim_entry='home')
    request, response = test_client.post('/api/zim/tag', content=json.dumps(content))
    assert response.status_code == HTTPStatus.CREATED

    # Entries can be untagged in the API.
    content = dict(tag_name=tag1.name, zim_id=test_zim.id, zim_entry='home')
    request, response = test_client.post('/api/zim/untag', content=json.dumps(content))
    assert response.status_code == HTTPStatus.NO_CONTENT

    # Cannot untag twice.
    content = dict(tag_name=tag1.name, zim_id=test_zim.id, zim_entry='home')
    request, response = test_client.post('/api/zim/untag', content=json.dumps(content))
    assert response.status_code == HTTPStatus.NOT_FOUND


def test_zim_subscribe(test_session, test_client):
    """A Kiwix subscription can be scheduled in the API.  The language can be changed."""
    # Subscribe to English.
    content = dict(name='Wikipedia (mini)', language='en')
    request, response = test_client.post('/api/zim/subscribe', content=json.dumps(content))
    assert response.status_code == HTTPStatus.CREATED

    download: Download = test_session.query(Download).one()
    assert download.url == 'https://download.kiwix.org/zim/wikipedia/wikipedia_en_all_mini_'
    assert download.info_json == {'language': 'en', 'name': 'Wikipedia (mini)'}
    assert download.frequency
    request, response = test_client.get('/api/zim/subscribe')
    assert response.status_code == HTTPStatus.OK
    assert response.json['subscriptions'] == {
        'Wikipedia (mini)': {'download_id': 1,
                             'download_url': 'https://download.kiwix.org/zim/wikipedia/wikipedia_en_all_mini_',
                             'id': 1,
                             'language': 'en',
                             'name': 'Wikipedia (mini)'}}

    # Change subscription to French.
    content = dict(name='Wikipedia (mini)', language='fr')
    request, response = test_client.post('/api/zim/subscribe', content=json.dumps(content))
    assert response.status_code == HTTPStatus.CREATED
    assert test_session.query(Download).count() == 1

    download: Download = test_session.query(Download).one()
    assert download.url == 'https://download.kiwix.org/zim/wikipedia/wikipedia_fr_all_mini_'
    assert download.info_json == {'language': 'fr', 'name': 'Wikipedia (mini)'}
    assert download.frequency
    request, response = test_client.get('/api/zim/subscribe')
    assert response.status_code == HTTPStatus.OK
    assert response.json['subscriptions'] == {
        'Wikipedia (mini)': {'download_id': 1,
                             'download_url': 'https://download.kiwix.org/zim/wikipedia/wikipedia_fr_all_mini_',
                             'id': 1,
                             'language': 'fr',
                             'name': 'Wikipedia (mini)'}}

    # Delete subscription.
    request, response = test_client.delete('/api/zim/subscribe/1')
    assert response.status_code == HTTPStatus.NO_CONTENT
    request, response = test_client.get('/api/zim/subscribe')
    assert response.status_code == HTTPStatus.OK
    assert response.json['subscriptions'] == {}
    # No subscriptions or downloads.
    assert test_session.query(lib.ZimSubscription).count() == 0
    assert test_session.query(Download).count() == 0


def test_get_zim_entry(test_session, test_client, test_zim):
    request, response = test_client.get('/api/zim/1/entry/home')
    assert response.status_code == HTTPStatus.OK

    request, response = test_client.get('/api/zim/1/entry/does not exist')
    assert response.status_code == HTTPStatus.NOT_FOUND


@pytest.mark.asyncio
async def test_find_outdated_zim_files(test_session, test_directory, test_zim_bytes, test_async_client):
    """Outdated Zim files are found and reported.  They can automatically be deleted."""
    # Can search empty directory.
    outdated, current = lib.find_outdated_zim_files()
    assert not outdated and not current

    (test_directory / 'zims/books').mkdir(parents=True)

    wikibooks_one = test_directory / 'zims/books/wikibooks_en_nopic_maxi_2023-01.zim'  # unique
    wikipedia_one = test_directory / 'zims/wikipedia_en_all_maxi_2023-01.zim'  # outdated
    wikipedia_two = test_directory / 'zims/wikipedia_en_all_maxi_2023-02.zim'  # keep this one
    asdf = test_directory / 'zims/asdf.zim'  # Name cannot be parsed.
    wikibooks_one.write_bytes(test_zim_bytes)
    wikipedia_one.write_bytes(test_zim_bytes)
    wikipedia_two.write_bytes(test_zim_bytes)
    asdf.write_bytes(test_zim_bytes)
    empty = test_directory / 'zims/wikipedia_en_all_maxi_2023-03.zim'  # empty files should be ignored.
    empty.touch()
    request, response = await test_async_client.get('/api/zim/outdated')
    assert response.status_code == HTTPStatus.OK
    assert response.json['outdated'] == [str(wikipedia_one.relative_to(test_directory)), ]

    request, response = await test_async_client.delete('/api/zim/outdated')
    assert response.status_code == HTTPStatus.NO_CONTENT
    # Only the outdated was deleted.
    assert wikibooks_one.is_file()
    assert not wikipedia_one.exists()
    assert wikipedia_two.is_file()
    assert asdf.is_file()
    assert empty.is_file()
