from dataclasses import dataclass
from typing import List, Optional


@dataclass
class SettingsObject:
    media_directory: str


@dataclass
class SettingsResponse:
    config: SettingsObject


@dataclass
class SettingsRequest:
    download_on_startup: Optional[bool] = None
    hotspot_on_startup: Optional[bool] = None
    hotspot_status: Optional[bool] = None
    media_directory: Optional[str] = None
    throttle_on: Optional[bool] = None
    throttle_on_startup: Optional[bool] = None
    timezone: Optional[str] = None
    wrol_mode: Optional[bool] = None


@dataclass
class RegexRequest:
    regex: str


@dataclass
class RegexResponse:
    regex: str
    valid: bool


@dataclass
class EchoResponse:
    form: dict
    headers: dict
    json: str
    method: str


@dataclass
class EventObject:
    name: str
    is_set: str


@dataclass
class EventsResponse:
    events: List[EventObject]


@dataclass
class DownloadRequest:
    urls: str
    downloader: Optional[str] = None


@dataclass
class JSONErrorResponse:
    error: str
