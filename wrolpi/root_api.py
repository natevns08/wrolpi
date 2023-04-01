import json
import re
from datetime import datetime, date, timezone
from decimal import Decimal
from functools import wraps
from http import HTTPStatus
from pathlib import Path
from typing import Union

from sanic import Sanic, response, Blueprint, __version__ as sanic_version
from sanic.blueprint_group import BlueprintGroup
from sanic.request import Request
from sanic.response import HTTPResponse
from sanic_ext import validate
from sanic_ext.extensions.openapi import openapi

from wrolpi import admin, status, flags, schema
from wrolpi import tags
from wrolpi.admin import HotspotStatus
from wrolpi.common import logger, get_config, wrol_mode_enabled, Base, get_media_directory, \
    wrol_mode_check, native_only, disable_wrol_mode, enable_wrol_mode, get_global_statistics
from wrolpi.dates import now, strptime
from wrolpi.downloader import download_manager
from wrolpi.errors import WROLModeEnabled, API_ERRORS, APIError, ValidationError, HotspotError, InvalidDownload
from wrolpi.events import get_events, Events
from wrolpi.files.lib import get_file_statistics
from wrolpi.vars import API_HOST, API_PORT, DOCKERIZED, API_DEBUG, API_ACCESS_LOG, API_WORKERS, API_AUTO_RELOAD, \
    truthy_arg
from wrolpi.version import __version__

logger = logger.getChild(__name__)

api_app = Sanic(name='api_app')
api_app.config.FALLBACK_ERROR_FORMAT = 'json'

api_bp = Blueprint('RootAPI', url_prefix='/api')

BLUEPRINTS = [api_bp, ]


def get_blueprint(name: str, url_prefix: str) -> Blueprint:
    """
    Create a new Sanic blueprint.  This will be attached to the app just before run.  See `root_api.run_webserver`.
    """
    bp = Blueprint(name, url_prefix)
    add_blueprint(bp)
    return bp


def add_blueprint(bp: Union[Blueprint, BlueprintGroup]):
    BLUEPRINTS.append(bp)


def run_webserver(
        host: str = API_HOST,
        port: int = API_PORT,
        workers: int = API_WORKERS,
        api_debug: bool = API_DEBUG,
        access_log: bool = API_ACCESS_LOG,
):
    # Attach all blueprints after they have been defined.
    for bp in BLUEPRINTS:
        api_app.blueprint(bp)

    kwargs = dict(
        host=host,
        port=port,
        workers=workers,
        debug=api_debug,
        access_log=access_log,
        auto_reload=DOCKERIZED,
    )
    logger.warning(f'Running Sanic {sanic_version} with kwargs {kwargs}')
    return api_app.run(**kwargs)


def init_parser(parser):
    # Called by WROLPI's main() function
    parser.add_argument('-H', '--host', default=API_HOST, help='What network interface to connect webserver')
    parser.add_argument('-p', '--port', default=API_PORT, type=int, help='What port to connect webserver')
    parser.add_argument('-w', '--workers', default=API_WORKERS, type=int, help='How many web workers to run')
    parser.add_argument('--access-log', default=API_ACCESS_LOG, type=truthy_arg, help='Enable Sanic access log')
    parser.add_argument('--api-debug', default=API_DEBUG, type=truthy_arg, help='Enable Sanic debug log')
    parser.add_argument('--api-auto-reload', default=API_AUTO_RELOAD, type=truthy_arg, help='Enable Sanic auto reload')


def main(args):
    return run_webserver(
        host=args.host,
        port=args.port,
        workers=args.workers,
        api_debug=args.api_debug,
        access_log=args.access_log,
    )


index_html = '''
<html>
<body>
<p>
    This is a WROLPi API.
    <ul>
        <li>You can test it at this endpoint <a href="/api/echo">/api/echo</a></li>
        <li>You can view the docs at <a href="/docs">/docs</a></li>
    </ul>
</p>
</body>
</html>
'''


@api_app.get('/')
def index(_):
    return response.html(index_html)


@api_bp.route('/echo', methods=['GET', 'POST', 'PUT', 'DELETE', 'PATCH', 'OPTIONS'])
@openapi.description('Echo whatever is sent to this.')
@openapi.response(HTTPStatus.OK, schema.EchoResponse)
async def echo(request: Request):
    ret = dict(
        form=request.form,
        headers=dict(request.headers),
        json=request.json,
        method=request.method,
        args=request.args,
    )
    return response.json(ret)


@api_bp.route('/settings', methods=['GET', 'OPTIONS'])
@openapi.description('Get WROLPi settings')
@openapi.response(HTTPStatus.OK, schema.SettingsResponse)
def get_settings(_: Request):
    config = get_config()

    settings = {
        'download_manager_disabled': download_manager.disabled.is_set(),
        'download_manager_stopped': download_manager.stopped.is_set(),
        'download_on_startup': config.download_on_startup,
        'download_timeout': config.download_timeout,
        'hotspot_device': config.hotspot_device,
        'hotspot_on_startup': config.hotspot_on_startup,
        'hotspot_password': config.hotspot_password,
        'hotspot_ssid': config.hotspot_ssid,
        'hotspot_status': admin.hotspot_status().name,
        'media_directory': str(get_media_directory()),  # Convert to string to avoid conversion to relative.
        'throttle_on_startup': config.throttle_on_startup,
        'throttle_status': admin.throttle_status().name,
        'version': __version__,
        'wrol_mode': config.wrol_mode,
    }
    return json_response(settings)


@api_bp.patch('/settings')
@openapi.description('Update WROLPi settings')
@validate(json=schema.SettingsRequest)
def update_settings(_: Request, body: schema.SettingsRequest):
    if wrol_mode_enabled() and body.wrol_mode is None:
        # Cannot update settings while WROL Mode is enabled, unless you want to disable WROL Mode.
        raise WROLModeEnabled()

    if body.wrol_mode is False:
        # Disable WROL Mode
        disable_wrol_mode()
        return response.empty()
    elif body.wrol_mode is True:
        # Enable WROL Mode
        enable_wrol_mode()
        return response.empty()

    # Remove any keys with None values, then save the config.
    config = {k: v for k, v in body.__dict__.items() if v is not None}
    wrolpi_config = get_config()
    old_password = wrolpi_config.hotspot_password
    wrolpi_config.update(config)

    # If the password was changed, we need to restart the hotspot.
    password_changed = (new_password := config.get('hotspot_password')) and old_password != new_password

    if body.hotspot_status is True or (password_changed and admin.hotspot_status() == HotspotStatus.connected):
        # Turn on Hotspot
        if admin.enable_hotspot() is False:
            raise HotspotError('Could not turn on hotspot')
    elif body.hotspot_status is False:
        # Turn off Hotspot
        if admin.disable_hotspot() is False:
            raise HotspotError('Could not turn off hotspot')

    return response.empty()


@api_bp.post('/valid_regex')
@openapi.description('Check if the regex is valid.')
@openapi.response(HTTPStatus.OK, schema.RegexResponse)
@openapi.response(HTTPStatus.BAD_REQUEST, schema.RegexResponse)
@validate(schema.RegexRequest)
def valid_regex(_: Request, body: schema.RegexRequest):
    try:
        re.compile(body.regex)
        return response.json({'valid': True, 'regex': body.regex})
    except re.error:
        return response.json({'valid': False, 'regex': body.regex}, HTTPStatus.BAD_REQUEST)


@api_bp.post('/download')
@openapi.description('Download all the URLs that are provided.')
@validate(schema.DownloadRequest)
@wrol_mode_check
async def post_download(_: Request, body: schema.DownloadRequest):
    # URLs are provided in a textarea, lets split all lines.
    urls = [i.strip() for i in str(body.urls).strip().splitlines()]
    downloader = download_manager.get_downloader_by_name(body.downloader)
    if not downloader:
        raise InvalidDownload(f'Cannot find downloader with name {body.downloader}')

    excluded_urls = [i.strip() for i in body.excluded_urls.split(',')] if body.excluded_urls else None
    destination = str(get_media_directory() / body.destination) if body.destination else None
    settings = dict(excluded_urls=excluded_urls, destination=destination)
    if body.frequency:
        download_manager.recurring_download(urls[0], body.frequency, downloader_name=body.downloader,
                                            sub_downloader_name=body.sub_downloader, reset_attempts=True,
                                            settings=settings)
    else:
        download_manager.create_downloads(urls, downloader_name=body.downloader, reset_attempts=True,
                                          sub_downloader_name=body.sub_downloader, settings=settings)
    if download_manager.disabled.is_set() or download_manager.stopped.is_set():
        # Downloads are disabled, warn the user.
        Events.send_downloads_disabled('Download created. But, downloads are disabled.')

    return response.empty()


@api_bp.get('/download')
@openapi.description('Get all Downloads that need to be processed.')
async def get_downloads(_: Request):
    data = download_manager.get_fe_downloads()
    return json_response(data)


@api_bp.post('/download/<download_id:int>/kill')
@openapi.description('Kill a download.  It will be stopped if it is pending.')
async def kill_download(_: Request, download_id: int):
    download_manager.kill_download(download_id)
    return response.empty()


@api_bp.post('/download/kill')
@openapi.description('Kill all downloads.  Disable downloading.')
async def kill_downloads(_: Request):
    download_manager.disable()
    return response.empty()


@api_bp.post('/download/enable')
@openapi.description('Enable and start downloading.')
async def enable_downloads(_: Request):
    download_manager.enable()
    return response.empty()


@api_bp.post('/download/clear_completed')
@openapi.description('Clear completed downloads')
async def clear_completed(_: Request):
    download_manager.delete_completed()
    return response.empty()


@api_bp.post('/download/clear_failed')
@openapi.description('Clear failed downloads')
async def clear_failed(_: Request):
    download_manager.delete_failed()
    return response.empty()


@api_bp.delete('/download/<download_id:[0-9,]+>')
@openapi.description('Delete a download')
@wrol_mode_check
async def delete_download(_: Request, download_id: int):
    deleted = download_manager.delete_download(download_id)
    return response.empty(HTTPStatus.NO_CONTENT if deleted else HTTPStatus.NOT_FOUND)


@api_bp.get('/downloaders')
@openapi.description('List all Downloaders that can be specified by the user.')
async def get_downloaders(_: Request):
    downloaders = download_manager.list_downloaders()
    disabled = download_manager.disabled.is_set()
    ret = dict(downloaders=downloaders, manager_disabled=disabled)
    return json_response(ret)


@api_bp.post('/hotspot/on')
@openapi.description('Turn on the hotspot')
@native_only
async def hotspot_on(_: Request):
    result = admin.enable_hotspot()
    if result:
        return response.empty()
    return response.empty(HTTPStatus.INTERNAL_SERVER_ERROR)


@api_bp.post('/hotspot/off')
@openapi.description('Turn off the hotspot')
@native_only
async def hotspot_off(_: Request):
    result = admin.disable_hotspot()
    if result:
        return response.empty()
    return response.empty(HTTPStatus.INTERNAL_SERVER_ERROR)


@api_bp.post('/throttle/on')
@openapi.description('Turn on CPU throttling')
@native_only
async def throttle_on(_: Request):
    result = admin.throttle_cpu_on()
    if result:
        return response.empty()
    return response.empty(HTTPStatus.INTERNAL_SERVER_ERROR)


@api_bp.post('/throttle/off')
@openapi.description('Turn off CPU throttling')
@native_only
async def throttle_off(_: Request):
    result = admin.throttle_cpu_off()
    if result:
        return response.empty()
    return response.empty(HTTPStatus.INTERNAL_SERVER_ERROR)


@api_bp.get('/status')
@openapi.description('Get the status of CPU/load/etc.')
async def get_status(_: Request):
    s = await status.get_status()
    downloads = dict()
    if flags.db_up.is_set():
        try:
            downloads = download_manager.get_summary()
        except Exception as e:
            logger.debug('Unable to get download status', exc_info=e)

    ret = dict(
        bandwidth=s.bandwidth,
        cpu_info=s.cpu_info,
        disk_bandwidth=s.disk_bandwidth,
        dockerized=DOCKERIZED,
        downloads=downloads,
        drives=s.drives,
        flags=flags.get_flags(),
        hotspot_status=admin.hotspot_status().name,
        load=s.load,
        memory_stats=s.memory_stats,
        throttle_status=admin.throttle_status().name,
        version=__version__,
        wrol_mode=wrol_mode_enabled(),
    )
    return json_response(ret)


@api_bp.get('/statistics')
@openapi.definition(
    summary='Get summary statistics of all files',
)
async def get_statistics(_):
    file_statistics = get_file_statistics()
    global_statistics = get_global_statistics()
    return json_response({
        'file_statistics': file_statistics,
        'global_statistics': global_statistics,
    })


@api_bp.get('/events/feed')
@validate(query=schema.EventsRequest)
async def feed(_: Request, query: schema.EventsRequest):
    start = now()
    after = None if query.after == 'None' else strptime(query.after)
    events = get_events(after)
    return json_response(dict(events=events, now=start))


@api_bp.get('/tag')
@openapi.definition(
    summary='Get a list of all Tags',
)
async def get_tags_request(_: Request):
    tags_ = tags.get_tags()
    return json_response(dict(tags=tags_))


@api_bp.post('/tag')
@api_bp.post('/tag/<tag_id:int>')
@validate(schema.TagRequest)
@openapi.definition(
    summary='Create or update a Tag',
)
async def post_new_tag(_: Request, body: schema.TagRequest, tag_id: int = None):
    tags.upsert_tag(body.name, body.color, tag_id)
    if tag_id:
        return response.empty(HTTPStatus.OK)
    else:
        return response.empty(HTTPStatus.CREATED)


@api_bp.delete('/tag/<tag_id:int>')
async def delete_tag_request(_: Request, tag_id: int):
    tags.delete_tag(tag_id)
    return response.empty(HTTPStatus.NO_CONTENT)


class CustomJSONEncoder(json.JSONEncoder):

    def default(self, obj):
        try:
            if hasattr(obj, '__json__'):
                # Get __json__ before others.
                return obj.__json__()
            elif isinstance(obj, datetime):
                # API always returns dates in UTC.
                if obj.tzinfo:
                    obj = obj.astimezone(timezone.utc)
                else:
                    # A datetime with no timezone is UTC.
                    obj = obj.replace(tzinfo=timezone.utc)
                obj = obj.isoformat()
                return obj
            elif isinstance(obj, date):
                # API always returns dates in UTC.
                obj = datetime(obj.year, obj.month, obj.day, tzinfo=timezone.utc)
                return obj.isoformat()
            elif isinstance(obj, Decimal):
                return str(obj)
            elif isinstance(obj, Base):
                if hasattr(obj, 'dict'):
                    return obj.dict()
            elif isinstance(obj, Path):
                media_directory = get_media_directory()
                try:
                    path = obj.relative_to(media_directory)
                except ValueError:
                    # Path may not be absolute.
                    path = obj
                if str(path) == '.':
                    return ''
                return str(path)
            return super(CustomJSONEncoder, self).default(obj)
        except Exception as e:
            logger.fatal(f'Failed to JSON encode {obj}', exc_info=e)
            raise


@wraps(response.json)
def json_response(*a, **kwargs) -> HTTPResponse:
    """
    Handles encoding date/datetime in JSON.
    """
    resp = response.json(*a, **kwargs, cls=CustomJSONEncoder, dumps=json.dumps)
    return resp


def json_error_handler(request: Request, exception: Exception):
    error = API_ERRORS[type(exception)]
    if isinstance(exception, ValidationError):
        body = dict(error='Could not validate the contents of the request', code=error['code'])
    else:
        body = dict(message=str(exception), api_error=error['message'], code=error['code'])
    if cause := exception.__cause__:
        try:
            cause = API_ERRORS[type(cause)]
            body['cause'] = dict(error=cause['message'], code=cause['code'])
        except KeyError:
            # Cause was not an APIError.
            logger.error(f'Could not find cause {cause}')
    return json_response(body, error['status'])


api_app.error_handler.add(APIError, json_error_handler)
