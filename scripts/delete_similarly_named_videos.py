#! /usr/bin/env python3
"""
A quick and dirty script which will query the DB for all videos and search for similarly named videos within a Channel.

WROLPi can sometimes download a video more than once if the Channel changes their name, or,
"""
import argparse
import asyncio
import difflib
import functools
import re
from difflib import SequenceMatcher
from typing import List, Generator, Optional

from modules.videos import Video, Channel
from wrolpi.common import get_relative_to_media_directory, chain
from wrolpi.db import get_db_curs, get_db_session
from wrolpi.files.models import FileGroup

MINIMUM_RANK = 0.8


def similar(a: str, b: str) -> float:
    return SequenceMatcher(None, a, b).ratio()


def get_all_channels(curs) -> List[int]:
    curs.execute('SELECT id FROM channel')
    return [i[0] for i in curs.fetchall()]


@functools.lru_cache
def get_channel_name(channel_id: int) -> Optional[str]:
    with get_db_session() as session:
        channel: Channel = session.query(Channel).filter_by(id=channel_id).one()
        if channel.info_json:
            return channel.info_json['channel']


@functools.lru_cache
def video_file_matches_channel_info_json(video: Video) -> bool:
    if not video.source_id or not video.channel:
        return False

    if entry := video.get_channel_entry():
        return entry['title'] in str(video.video_path)

    return False


def find_similar_videos(channel_id: int, minimum_rank: float = MINIMUM_RANK, directory: str = None) \
        -> Generator[List[Video], None, None]:
    consumed_ids = set()

    with get_db_session() as session:
        query = session.query(Video).filter(Video.channel_id == channel_id)
        if directory:
            query = query.join(FileGroup).filter(FileGroup.primary_path.like(f'{directory}%'))
        videos: List[Video] = query.all()
        videos = sorted(videos, key=lambda i: i.video_path)

        for link in chain(videos, 5):
            link: List[Video]
            link = [i for i in link if i.id not in consumed_ids and i.file_group.title]
            if not link:
                continue

            vid1, *vids = link
            vid1_title = vid1.file_group.title
            similar_videos = [i for i in vids if similar(i.file_group.title, vid1_title) > minimum_rank]

            if not similar_videos:
                continue

            similar_videos += [vid1, ]

            # Do not compare against these videos again.
            consumed_ids |= {i.id for i in similar_videos}
            # Yield the videos that share similar titles.
            yield similar_videos


async def rank_video_quality(video: Video) -> int:
    """Returns a higher integer the more quality the Video record is.  A video with info_json is more valuable than
    one without, etc."""
    rank = 0

    # These are more valuable.
    if video.file_group.url:
        rank += 2
    if video.source_id:
        rank += 2
    if video.info_json_path:
        rank += 2
    # These are more common.
    if video.channel_id:
        rank += 1
    if video.caption_paths:
        rank += 1
    if video.poster_path:
        rank += 1
    if video.ffprobe_json or await video.get_ffprobe_json():
        rank += 1
    if video_file_matches_channel_info_json(video):
        rank += 1

    channel_name = get_channel_name(video.channel_id)
    if channel_name and channel_name in str(video.video_path):
        # The Channel's name is in the video's path.  Channel names change sometimes...
        rank += 2

    return rank


def delete_video(video_id: int):
    with get_db_session(commit=True) as session:
        video = session.query(Video).filter_by(id=video_id).one()
        video.delete()


class SkipChannel(Exception):
    pass


def get_different_characters(a: str, b: str) -> str:
    changes = ''
    for i, s in enumerate(difflib.ndiff(a, b)):
        if s[0] == ' ':
            # Ignore same-characters.
            continue
        elif s[0] == '+' or s[0] == '-':
            # Return characters that are different.
            changes += s[-1]
    return changes


PART_MATCH = re.compile(r'(.*)\b((?:p(?:art|t)?.?\s?(?:\d+|[ivx]+)+)|[ivx]+)\b(.*)', re.IGNORECASE)


def remove_part_from_title(title: str) -> str:
    title = title.lower()
    if match := PART_MATCH.match(title):
        prefix, part, suffix = match.groups()
        return prefix + suffix
    return title


async def handle_user_delete_duplicates(similar_videos: List[Video], video_url: str = None,
                                        delete_lower_ranked_automatically: bool = False):
    similar_videos = similar_videos.copy()

    while len(similar_videos) > 1:
        all_changes = ''
        for i in similar_videos:
            a = remove_part_from_title(i.file_group.title)
            for j in similar_videos:
                if i.id == j.id:
                    continue
                b = remove_part_from_title(j.file_group.title)
                all_changes += get_different_characters(a, b)
        # Ignore space changes.
        all_changes = ''.join(i for i in all_changes if i != ' ' and i != '.')
        if all_changes.isdigit() or not all_changes:
            print(f'\nSkipping {similar_videos[0]} and similar because they are parts')
            return

        print()
        print(f'{all_changes=}')
        ranked_videos = [(await rank_video_quality(i), i) for i in similar_videos]
        ranked_videos = sorted(ranked_videos, key=lambda i: (i[0], i[1].file_group.size), reverse=True)
        for rank, video in ranked_videos:
            fg = video.file_group
            id_, title, path, source_id, size = video.id, fg.title, video.video_path, video.source_id, fg.size
            size = f'{size // 1_048_576} MB'
            path = get_relative_to_media_directory(path)
            if video_url:
                print(f'{rank} {id_} {repr(title)} {repr(str(path))} {source_id} {size} {video_url + str(id_)}')
            else:
                print(f'{rank} {id_} {repr(title)} {repr(str(path))} {source_id} {size}')

        unique_ranks = {i[0] for i in ranked_videos}
        if len(unique_ranks) > 1:
            # Suggest to delete the lowest video.
            _, lowest_video = min(ranked_videos, key=lambda i: i[0])
            if delete_lower_ranked_automatically:
                delete_video(lowest_video.id)
                index = similar_videos.index(lowest_video)
                del similar_videos[index]
                continue
            response = input('Delete the lowest ranked video? (y/N)').lower()
            if response == 'y':
                if input(f'\nConfirm delete: {lowest_video} ').lower() == 'y':
                    delete_video(lowest_video.id)
                    index = similar_videos.index(lowest_video)
                    del similar_videos[index]
            elif response == 'n':
                break
            elif response == 'c':
                raise SkipChannel()
        else:
            # All videos share the same rank.
            response = input('Delete which video? (starting at 0..., n to skip)')
            if response.isdigit():
                index = int(response)
                _, to_delete = ranked_videos[index]
                if input(f'\nConfirm delete: {to_delete} ').lower() == 'y':
                    delete_video(to_delete.id)
                    del similar_videos[index]
            elif response == 'n' or response == 'N':
                break
            elif response == 'c':
                raise SkipChannel()


async def main(channel_id: int = None, minimum_rank: float = MINIMUM_RANK, video_url: str = None,
               directory: str = None, delete_lower_ranked_automatically: bool = False):
    with get_db_curs() as curs:
        if channel_id:
            for videos in find_similar_videos(channel_id, minimum_rank, directory):
                await handle_user_delete_duplicates(videos, video_url, delete_lower_ranked_automatically)
        else:
            channel_ids = get_all_channels(curs)
            for channel_id in channel_ids:
                for videos in find_similar_videos(channel_id, minimum_rank, directory):
                    try:
                        await handle_user_delete_duplicates(videos, video_url, delete_lower_ranked_automatically)
                    except SkipChannel:
                        break


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('-c', '--channel-id', type=int,
                        help='The ID of the channel to search.  If empty, all channels will be searched.')
    parser.add_argument('-r', '--rank', type=float, default=MINIMUM_RANK,
                        help=f'The minimum similarity between the titles. Default: {MINIMUM_RANK}')
    parser.add_argument('-u', '--video-url', default='http://127.0.0.1/videos/video/',
                        help='The URL where the videos can be viewed.')
    parser.add_argument('-d', '--directory',
                        help='Only search videos in this directory.')
    parser.add_argument('-y', '--yes', action='store_true', default=False,
                        help='Automatically delete lower-ranked duplicate videos.')
    args = parser.parse_args()

    loop = asyncio.new_event_loop()
    loop.run_until_complete(main(args.channel_id, args.rank, args.video_url, args.directory, args.yes))
