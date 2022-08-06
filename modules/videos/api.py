from http import HTTPStatus

from sanic import Blueprint, response
from sanic.request import Request
from sanic_ext import validate
from sanic_ext.extensions.openapi import openapi

from wrolpi.common import logger
from wrolpi.common import wrol_mode_check
from wrolpi.root_api import add_blueprint, json_response
from wrolpi.schema import JSONErrorResponse
from . import lib, schema
from .channel import lib as channel_lib
from .channel.api import channel_bp
from .video import lib as video_lib
from .video.api import video_bp

content_bp = Blueprint('VideoContent', '/api/videos')
bp = Blueprint('Videos', '/api/videos').group(
    content_bp,  # view and manage video content and settings
    channel_bp,  # view and manage channels
    video_bp,  # view videos
)
add_blueprint(bp)

logger = logger.getChild(__name__)


@content_bp.post('/download/<channel_id:int>')
@openapi.description('Update a channel catalog, download any missing videos')
@openapi.response(HTTPStatus.OK, schema.StreamResponse)
@openapi.response(HTTPStatus.BAD_REQUEST, JSONErrorResponse)
@wrol_mode_check
def download(_, channel_id: int = None):
    channel_lib.download_channel(channel_id)
    return response.empty()


@content_bp.post('/favorite')
@openapi.definition(
    description='Toggle the favorite flag on a video',
    body=schema.FavoriteRequest,
)
@validate(schema.FavoriteRequest)
@openapi.response(HTTPStatus.OK, schema.FavoriteResponse)
@openapi.response(HTTPStatus.BAD_REQUEST, JSONErrorResponse)
async def favorite(_: Request, body: schema.FavoriteRequest):
    _favorite = video_lib.set_video_favorite(body.video_id, body.favorite)
    ret = {'video_id': body.video_id, 'favorite': _favorite}
    return json_response(ret, HTTPStatus.OK)


@content_bp.get('/statistics')
@openapi.response(HTTPStatus.OK, schema.VideosStatisticsResponse)
async def statistics(_: Request):
    ret = await lib.get_statistics()
    return json_response(ret, HTTPStatus.OK)
