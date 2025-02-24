#! /usr/bin/env python3
import argparse
import asyncio
import logging
import sys

from sanic import Sanic
from sanic.signals import Event

from wrolpi import flags, BEFORE_STARTUP_FUNCTIONS
from wrolpi import root_api, admin
from wrolpi.common import logger, get_config, check_media_directory, limit_concurrent, \
    wrol_mode_enabled, cancel_refresh_tasks, set_log_level, background_task, cancel_background_tasks
from wrolpi.downloader import download_manager, import_downloads_config
from wrolpi.root_api import api_app
from wrolpi.vars import PROJECT_DIR, DOCKERIZED, PYTEST
from wrolpi.version import get_version_string

logger = logger.getChild('wrolpi-main')


def db_main(args):
    """
    Handle database migrations.  Currently this uses Alembic, supported commands are "upgrade" and "downgrade".
    """
    from alembic.config import Config
    from alembic import command
    from wrolpi.db import uri

    config = Config(PROJECT_DIR / 'alembic.ini')
    # Overwrite the Alembic config, the is usually necessary when running in a docker container.
    config.set_main_option('sqlalchemy.url', uri)

    logger.warning(f'DB URI: {uri}')

    if args.command == 'upgrade':
        command.upgrade(config, 'head')
    elif args.command == 'downgrade':
        command.downgrade(config, '-1')
    else:
        print(f'Unknown DB command: {args.command}')
        return 2

    return 0


INTERACTIVE_BANNER = '''
This is the interactive WROLPi shell.  Use this to interact with the WROLPi API library.

Example (get the duration of every video file):
from modules.videos.models import Video
from modules.videos.common import get_video_duration
videos = session.query(Video).filter(Video.video_path != None).all()
videos = list(videos)
for video in videos:
    get_video_duration(video.video_path.path)

Check local variables:
locals().keys()

'''


def launch_interactive_shell():
    """Launches an interactive shell with a DB session."""
    import code
    from wrolpi.db import get_db_session

    with get_db_session() as session:
        code.interact(banner=INTERACTIVE_BANNER, local=locals())


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('-v', '--verbose', action='count')
    parser.add_argument('--version', action='store_true', default=False)
    parser.add_argument('-c', '--check-media', action='store_true', default=False,
                        help='Check that the media directory is mounted and has the correct permissions.'
                        )
    parser.add_argument('-i', '--interactive', action='store_true', default=False,
                        help='Enter an interactive shell with some WROLPi tools')

    sub_commands = parser.add_subparsers(title='sub-commands', dest='sub_commands')

    # Add the API parser, this will allow the user to specify host/port etc.
    api_parser = sub_commands.add_parser('api')
    root_api.init_parser(api_parser)

    # DB Parser for running Alembic migrations
    db_parser = sub_commands.add_parser('db')
    db_parser.add_argument('command', help='Supported commands: upgrade, downgrade')

    args = parser.parse_args()

    if args.interactive:
        launch_interactive_shell()
        return 0

    if args.version:
        # Print out the relevant version information, then exit.
        print(get_version_string())
        return 0

    if args.check_media:
        # Run the media directory check.  Exit with informative return code.
        result = check_media_directory()
        if result is False:
            return 1
        print('Media directory is correct.')
        return 0

    if not args.sub_commands:
        parser.print_help()
        return 1

    logger.warning(f'Starting with: {sys.argv}')
    from wrolpi.common import LOG_LEVEL
    with LOG_LEVEL.get_lock():
        if args.verbose == 1:
            LOG_LEVEL.value = logging.INFO
            set_log_level(logging.INFO)
        elif args.verbose and args.verbose == 2:
            LOG_LEVEL.value = logging.DEBUG
            set_log_level(logging.DEBUG)
        elif args.verbose and args.verbose >= 3:
            # Log everything.  Add SQLAlchemy debug logging.
            LOG_LEVEL.value = logging.NOTSET
            set_log_level(logging.NOTSET)
    logger.info(get_version_string())

    if DOCKERIZED:
        logger.info('Running in Docker')

    # Run DB migrations before anything else.
    if args.sub_commands == 'db':
        return db_main(args)

    config = get_config()

    # Hotspot/throttle are not supported in Docker containers.
    if not DOCKERIZED and config.hotspot_on_startup:
        try:
            admin.enable_hotspot()
        except Exception as e:
            logger.error('Failed to enable hotspot', exc_info=e)
    if not DOCKERIZED and config.throttle_on_startup:
        try:
            admin.throttle_cpu_on()
        except Exception as e:
            logger.error('Failed to throttle CPU', exc_info=e)

    check_media_directory()

    # Import modules before calling BEFORE_STARTUP_FUNCTIONS.
    import modules  # noqa

    # Run the startup functions
    for func in BEFORE_STARTUP_FUNCTIONS:
        try:
            logger.debug(f'Calling {func} before startup.')
            func()
        except Exception as e:
            logger.warning(f'Startup {func} failed!', exc_info=e)

    # Run the API.
    if args.sub_commands == 'api':
        return root_api.main(args)


@api_app.before_server_start
@limit_concurrent(1)
async def startup(app: Sanic):
    from wrolpi.common import LOG_LEVEL

    # Check database status first.  Many functions will reference flags.db_up.
    flags.check_db_is_up()

    flags.init_flags()
    await import_downloads_config()

    async def periodic_check_db_is_up():
        while True:
            flags.check_db_is_up()
            flags.init_flags()
            await asyncio.sleep(10)

    background_task(periodic_check_db_is_up())

    async def periodic_check_log_level():
        while True:
            log_level = LOG_LEVEL.value
            if log_level != logger.getEffectiveLevel():
                set_log_level(log_level)
            await asyncio.sleep(1)

    background_task(periodic_check_log_level())

    from wrolpi import status
    background_task(status.bandwidth_worker())

    from modules.zim.lib import flag_outdated_zim_files
    flag_outdated_zim_files()


@api_app.after_server_start
async def periodic_downloads(app: Sanic):
    """
    Starts the perpetual downloader on download manager.

    Limited to only one process.
    """
    async with flags.db_up.wait_for():
        pass

    if not flags.refresh_complete.is_set():
        logger.warning('Refusing to download without refresh')
        download_manager.disable()
        return

    # Set all downloads to new.
    download_manager.reset_downloads()

    if wrol_mode_enabled():
        logger.warning('Not starting download manager because WROL Mode is enabled.')
        download_manager.disable()
        return

    config = get_config()
    if config.download_on_startup is False:
        logger.warning('Not starting download manager because Downloads are disabled on startup.')
        download_manager.disable()
        return

    async with flags.db_up.wait_for():
        download_manager.enable()
        app.add_task(download_manager.perpetual_download())


@api_app.after_server_start
async def start_workers(app: Sanic):
    """All Sanic processes have their own Download workers."""
    if wrol_mode_enabled():
        logger.warning(f'Not starting download workers because WROL Mode is enabled.')
        download_manager.stop()
        return

    async with flags.db_up.wait_for():
        download_manager.start_workers()


@api_app.before_server_start
@limit_concurrent(1)
async def main_import_tags_config(app: Sanic):
    from wrolpi import tags
    async with flags.db_up.wait_for():
        tags.import_tags_config()


@root_api.api_app.signal(Event.SERVER_SHUTDOWN_BEFORE)
@limit_concurrent(1)
async def handle_server_shutdown(*args, **kwargs):
    """Stop downloads when server is shutting down."""
    if not PYTEST:
        download_manager.stop()
        await cancel_refresh_tasks()
        await cancel_background_tasks()


if __name__ == '__main__':
    sys.exit(main())
