import json
from http import HTTPStatus

import pytest

from modules.videos.models import Video


def test_delete_channel_no_url(test_session, test_client, channel_factory):
    """
    A Channel can be deleted even if it has no URL.
    """
    channel = channel_factory()
    channel.url = None
    test_session.commit()

    channel.delete_with_videos()


@pytest.mark.asyncio
async def test_delete_channel_with_videos(test_session, test_async_client, channel_factory, video_factory):
    """Videos are disowned when their Channel is deleted."""
    channel = channel_factory()
    video = video_factory(channel_id=channel.id)
    video_path, video_id = video.video_path, video.id
    test_session.commit()

    # Delete the Channel.
    request, response = await test_async_client.delete(f'/api/videos/channels/{channel.id}')
    assert response.status == HTTPStatus.NO_CONTENT

    # Video still exists, but has no channel.
    video: Video = test_session.query(Video).one()
    assert video.video_path == video_path and video.id == video_id, 'Video entry should not be changed'
    assert video.video_path.is_file(), 'Video should not be deleted'
    assert not video.channel_id and not video.channel, 'Video should not have a Channel'


@pytest.mark.asyncio
async def test_nested_channel_directories(test_session, test_async_client, test_directory, channel_factory,
                                          video_factory):
    """Channel directories cannot contain another Channel's directory."""
    (test_directory / 'foo').mkdir()
    channel1_directory = test_directory / 'foo/one'
    channel_factory(directory=channel1_directory)
    test_session.commit()

    # Channel 2 cannot be in Channel 1's directory.
    channel2_directory = channel1_directory / 'two'
    channel2_directory.mkdir()
    content = dict(
        name='channel 2',
        directory=str(channel2_directory),
    )
    request, response = await test_async_client.post('/api/videos/channels', content=json.dumps(content))
    assert response.status == HTTPStatus.BAD_REQUEST
    assert response.json['cause'] and \
           response.json['cause']['summary'] == 'The directory is already used by another channel.'

    # Channel 3 cannot be above Channel 1's directory.
    content = dict(
        name='channel 3',
        directory=str(test_directory),
    )
    request, response = await test_async_client.post('/api/videos/channels', content=json.dumps(content))
    assert response.status == HTTPStatus.BAD_REQUEST
    assert response.json['cause'] and \
           response.json['cause']['summary'] == 'The directory is already used by another channel.'
