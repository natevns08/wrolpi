import contextlib
import pathlib
from datetime import datetime
from typing import List, Dict, Tuple

from sqlalchemy import Column, Integer, String, ForeignKey, BigInteger
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import relationship, Session

from wrolpi import dates
from wrolpi.common import ModelHelper, Base, logger, ConfigFile, get_media_directory, background_task, run_after, \
    register_refresh_cleanup, get_relative_to_media_directory
from wrolpi.dates import TZDateTime
from wrolpi.db import optional_session, get_db_curs
from wrolpi.errors import UnknownTag, UsedTag, InvalidTag
from wrolpi.vars import PYTEST

logger = logger.getChild(__name__)


class TagFile(ModelHelper, Base):
    __tablename__ = 'tag_file'
    created_at: datetime = Column(TZDateTime, default=dates.now)

    tag_id = Column(Integer, ForeignKey('tag.id', ondelete='CASCADE'), primary_key=True)
    tag = relationship('Tag', back_populates='tag_files')
    file_group_id = Column(BigInteger, ForeignKey('file_group.id', ondelete='CASCADE'), primary_key=True)
    file_group = relationship('FileGroup', back_populates='tag_files')


class Tag(ModelHelper, Base):
    __tablename__ = 'tag'
    id = Column(Integer, primary_key=True)
    name = Column(String, unique=True, nullable=False)
    color = Column(String)

    tag_files: List[TagFile] = relationship('TagFile', back_populates='tag', cascade='all')
    tag_zim_entries: List[TagFile] = relationship('TagZimEntry', back_populates='tag', cascade='all')

    def __repr__(self):
        name = self.name
        color = self.color
        return f'<Tag {name=} {color=}>'

    def __json__(self):
        return dict(
            id=self.id,
            name=self.name,
            color=self.color,
        )

    @optional_session
    def add_file_group_tag(self, file_group, session: Session = None) -> TagFile:
        """Add a TagFile for the provided FileGroup and this Tag.

        @warning: Commits the session to keep the config in sync."""
        from wrolpi.files.models import FileGroup
        if not isinstance(file_group, FileGroup):
            raise ValueError('Cannot apply tag to non-FileGroup')

        tag_file = TagFile(file_group_id=file_group.id, tag_id=self.id)
        logger.info(f'Tagging {file_group} with {self}')
        session.add(tag_file)
        session.flush([tag_file])
        session.commit()

        # Save changes to config.
        schedule_save(session)
        return tag_file

    @optional_session
    def remove_file_group_tag(self, file_group, session: Session = None):
        """Remove the record of a Tag applied to the FileGroup.

        @warning: Commits the session to keep config in sync."""
        from wrolpi.files.models import FileGroup
        if not isinstance(file_group, FileGroup):
            raise ValueError('Cannot remove tag of non-FileGroup')

        tag_file = session.query(TagFile) \
            .filter(TagFile.file_group_id == file_group.id, TagFile.tag_id == self.id) \
            .one_or_none()
        if tag_file:
            session.delete(tag_file)
            session.commit()

            # Save changes to config.
            schedule_save(session)
        else:
            logger.warning(f'Could not find tag_file for FileGroup.id={file_group.id}/Tag.id={self.id=}')

    @staticmethod
    @optional_session
    def find_by_name(name: str, session: Session) -> 'Tag':
        tag = session.query(Tag).filter_by(name=name).one_or_none()
        return tag

    def has_relations(self) -> bool:
        """Returns True if this Tag has been used with any FileGroups or Zim Entries."""
        return bool(self.tag_files or self.tag_zim_entries)


class TagsConfig(ConfigFile):
    file_name = 'tags.yaml'
    width = 500

    default_config = dict(
        tag_files=list(),
        tag_zims=list(),
        tags=list(),
    )

    @property
    def tag_files(self) -> list:
        return self._config['tag_files']

    @tag_files.setter
    def tag_files(self, value):
        value = sorted(value, key=lambda i: (i[0].lower(), i[1]))
        self.update({'tag_files': value})

    @property
    def tag_zims(self) -> list:
        return self._config['tag_zims']

    @tag_zims.setter
    def tag_zims(self, value):
        value = sorted(value, key=lambda i: (i[0].lower(), i[1], i[2]))
        self.update({'tag_zims': value})

    @property
    def tags(self) -> dict:
        return self._config['tags']

    @tags.setter
    def tags(self, value: dict):
        self.update({'tags': value})

    def save_tags(self, session: Session):
        media_directory = get_media_directory()

        tags = dict()
        tag_rows = session.query(Tag)
        for tag in tag_rows:
            tags[tag.name] = dict(color=tag.color)

        from wrolpi.files.models import FileGroup
        results = session.query(Tag, TagFile, FileGroup) \
            .filter(TagFile.tag_id == Tag.id, TagFile.file_group_id == FileGroup.id) \
            .order_by(FileGroup.primary_path)

        tag_files = []
        for tag, tag_file, file_group in results:
            value = [
                tag.name,
                str(file_group.primary_path.relative_to(media_directory)),
                # Fallback to current time if not set.
                tag_file.created_at.isoformat() if tag_file.created_at else dates.now().isoformat(),
            ]
            tag_files.append(value)

        from modules.zim.models import Zim, TagZimEntry
        results = session.query(Tag, Zim, TagZimEntry) \
            .filter(Tag.id == TagZimEntry.tag_id, Zim.id == TagZimEntry.zim_id) \
            .order_by(TagZimEntry.zim_id, TagZimEntry.zim_entry)

        tag_zims = []
        for tag, zim, tag_zim_entry in results:
            zim: Zim
            tag_zim_entry: TagZimEntry
            value = [
                tag.name,
                str(get_relative_to_media_directory(zim.path)),
                tag_zim_entry.zim_entry,
                # Fallback to current time if not set.
                tag_zim_entry.created_at.isoformat() if tag_zim_entry.created_at else dates.now().isoformat(),
            ]
            tag_zims.append(value)

        # Write to the config.
        self.update({
            'tag_files': tag_files,
            'tag_zims': tag_zims,
            'tags': tags,
        })


TAGS_CONFIG: TagsConfig = TagsConfig()
TEST_TAGS_CONFIG: TAGS_CONFIG = None


def get_tags_config():
    global TEST_TAGS_CONFIG
    if isinstance(TEST_TAGS_CONFIG, ConfigFile):
        return TEST_TAGS_CONFIG

    global TAGS_CONFIG
    return TAGS_CONFIG


@contextlib.contextmanager
def test_tags_config():
    global TEST_TAGS_CONFIG
    TEST_TAGS_CONFIG = TagsConfig()
    yield
    TEST_TAGS_CONFIG = None


@optional_session
def schedule_save(session: Session = None):
    """Schedule a background task to save all TagFiles to the config file.  If testing, save synchronously."""
    if PYTEST:
        get_tags_config().save_tags(session)
    else:
        async def _():
            get_tags_config().save_tags(session)

        background_task(_())


def get_tags() -> List[dict]:
    with get_db_curs() as curs:
        curs.execute('''
            SELECT t.id, t.name, t.color,
             (SELECT COUNT(*) FROM tag_file WHERE tag_id = t.id) AS file_group_count,
             (SELECT COUNT(*) FROM tag_zim WHERE tag_id = t.id) AS zim_entry_count
            FROM tag t
            GROUP BY t.id, t.name, t.color
            ORDER BY t.name
        ''')
        tags = list(map(dict, curs.fetchall()))
    return tags


@optional_session
@run_after(schedule_save)
def upsert_tag(name: str, color: str, tag_id: int = None, session: Session = None) -> Tag:
    if ',' in name:
        raise InvalidTag('Tag name cannot have comma')

    if tag_id:
        tag = session.query(Tag).filter_by(id=tag_id).one_or_none()
        if not tag:
            raise UnknownTag(f'Cannot find tag with id={tag_id}')
        tag.name = name
        tag.color = color
    else:
        tag = Tag(name=name, color=color)
        session.add(tag)

    try:
        session.flush([tag])
        session.commit()
    except IntegrityError as e:
        # Conflicting name
        session.rollback()
        raise InvalidTag(f'Name already taken') from e

    schedule_save()

    return tag


@optional_session
def delete_tag(tag_id: int, session: Session = None):
    tag: Tag = session.query(Tag).filter_by(id=tag_id).one_or_none()

    if not tag:
        raise UnknownTag(f'Cannot find tag {tag_id}')

    if tag.tag_files:
        count = len(tag.tag_files)
        raise UsedTag(f'Cannot delete {tag.name} it is used by {count} files!')

    session.delete(tag)
    session.commit()

    schedule_save()


@register_refresh_cleanup
@optional_session
def import_tags_config(session: Session = None):
    """Reads the Tags and TagFiles from the config file, upserts them in the DB."""
    from modules.zim import lib as zim_lib
    from modules.zim.models import Zim, TagZimEntry

    if PYTEST and not TEST_TAGS_CONFIG:
        logger.warning('Refusing to import tags without test tags config.  '
                       'Use `test_tags_config` fixture if you would like to call this.')
        return

    config = get_tags_config()
    if not (path := config.get_file()).is_file():
        logger.warning(f'Refusing to import tags config because it does not exist: {path}')
        return

    logger.info('Importing tags config')

    try:
        if config.tags:
            # Tags have been saved to config, import them
            tags_by_name: Dict[str, Tag] = {i.name: i for i in session.query(Tag)}
            new_tags = list()
            for name, attrs in config.tags.items():
                tag = tags_by_name.get(name)
                if not tag:
                    # Maintainer added a Tag to the config manually, or DB was wiped.
                    tag = Tag(name=name, color=attrs['color'])
                    new_tags.append(tag)
                    logger.info(f'Creating new {tag}')
                tag.color = attrs['color']

            if new_tags:
                session.add_all(new_tags)

            session.commit()

        media_directory = get_media_directory()

        need_commit = False

        # Get all Tags again because new ones may exist.
        tags_by_name: Dict[str, Tag] = {i.name: i for i in session.query(Tag)}

        # Tag all FileGroups.
        if config.tag_files:
            from wrolpi.files.models import FileGroup

            primary_paths = [str(media_directory / i[1]) for i in config.tag_files]
            file_groups = session.query(FileGroup).filter(FileGroup.primary_path.in_(primary_paths))
            file_groups_by_primary_path = {i.primary_path: i for i in file_groups}
            file_group_ids = [i.id for i in file_groups]
            # Get all TagFiles referencing the FileGroups.
            tag_files = session.query(TagFile).filter(TagFile.file_group_id.in_(file_group_ids))
            tag_files = {(i.tag_id, i.file_group_id): i for i in tag_files}

            for tag_name, primary_path, created_at in config.tag_files:
                tag: Tag = tags_by_name.get(tag_name)
                # Paths are absolute in the DB, relative in config.
                absolute_path = media_directory / primary_path
                file_group: FileGroup = file_groups_by_primary_path.get(absolute_path)
                if tag and file_group:
                    tag_file: TagFile = tag_files.get((tag.id, file_group.id))
                    if not tag_file:
                        # This FileGroup has not been tagged with the Tag, add it.
                        tag_file = tag.add_file_group_tag(file_group, session)
                    tag_file.created_at = dates.strptime_ms(created_at) if created_at else dates.now()
                    need_commit = True
                elif not file_group:
                    logger.warning(f'Cannot find FileGroup for {repr(str(primary_path))}')
                elif not tag:
                    logger.warning(f'Cannot find Tag for {repr(str(primary_path))}')

        # Tag all Zim entries.
        if config.tag_zims:
            # { pathlib.Path('/media/wrolpi/...'): <Zim>, ... }
            zims_by_path = {i.path: i for i in session.query(Zim)}

            # { (pathlib.Path('relative/path'), 'entry path'): <TagZimEntry>, ... }
            tag_zim_entries = {(get_relative_to_media_directory(i.zim.path), i.zim_entry): i for i in
                               session.query(TagZimEntry)}

            for tag_name, zim_path, zim_entry, created_at in config.tag_zims:
                zim_path = pathlib.Path(zim_path)
                tag: Tag = tags_by_name.get(tag_name)
                absolute_path = media_directory / zim_path
                zim: Zim = zims_by_path.get(absolute_path)
                if not zim:
                    # No Zim matches the path.  It's likely that the old Zim file was deleted.  Attempt to migrate
                    # the entry.
                    name, date = zim_lib.parse_name(absolute_path)
                    # Find any Zims that match the old Zim's name (wikipedia_en_all_maxi_*)
                    possible_zims = {i: j for i, j in zims_by_path.items() if i.name.startswith(name)}
                    if not possible_zims:
                        logger.warning(f'Cannot find Zim for {repr(str(zim_path))}')
                        continue
                    zim = zims_by_path[sorted(possible_zims.keys())[-1]]
                    new_zim_path = get_relative_to_media_directory(media_directory / zim.path)
                    logger.warning(f'Migrating Zim entry tag {repr(str(tag_name))} from {zim_path} to {new_zim_path}')
                    zim_path = new_zim_path

                if tag:
                    tag_zim_entry: TagZimEntry = tag_zim_entries.get((zim_path, zim_entry))
                    if not tag_zim_entry:
                        tag_zim_entry = TagZimEntry(tag=tag, zim=zim, zim_entry=zim_entry)
                        session.add(tag_zim_entry)
                        # Track this new TagZimEntry because migration may cause duplicates.
                        tag_zim_entries[(zim_path, zim_entry)] = tag_zim_entry
                    tag_zim_entry.created_at = datetime.fromisoformat(created_at) if created_at else dates.now()
                    need_commit = True
                elif not tag:
                    logger.warning(f'Cannot find Tag for {repr(str(zim_path))}')

        # Delete missing Tags last in case they are used above.
        if config.tags:
            config_tag_names = set(config.tags.keys())
            for tag in session.query(Tag):
                if tag.name not in config_tag_names:
                    if tag.has_relations():
                        logger.warning(f'Refusing to delete {tag} because it is used.')
                    else:
                        logger.warning(f'Deleting {tag} because it is not in the config.')
                        session.delete(tag)
                        need_commit = True

        if need_commit:
            session.commit()
    except Exception as e:
        logger.error(f'Failed to import tags config', exc_info=e)
        if PYTEST:
            raise


def tag_names_to_file_group_sub_select(tag_names: List[str]) -> Tuple[str, dict]:
    """Create the SQL necessary to filter FileGroup by the provided Tag names."""
    if not tag_names:
        return '', dict()

    stmt = '''
        SELECT
            tf.file_group_id
        FROM
            tag_file tf
            LEFT JOIN tag t on t.id = tf.tag_id
        GROUP BY file_group_id
        -- Match only FileGroups that have at least all the Tag names.
        HAVING array_agg(t.name)::TEXT[] @> %(tag_names)s::TEXT[]
    '''
    return stmt, dict(tag_names=tag_names)


def tag_names_to_zim_sub_select(tag_names: List[str], zim_id: int = None) -> Tuple[str, dict]:
    if not tag_names:
        return '', dict()

    params = dict(tag_names=tag_names)
    if zim_id:
        stmt = '''
            SELECT
                tz.zim_id, tz.zim_entry
            FROM
                tag_zim tz
                LEFT JOIN tag t on tz.tag_id = t.id
            WHERE
                tz.zim_id = %(zim_id)s
            GROUP BY tz.zim_id, tz.zim_entry
            -- Match only TagZimEntries that have all the Tag names.
            HAVING array_agg(t.name)::TEXT[] @> %(tag_names)s::TEXT[]
        '''
        params['zim_id'] = zim_id
    else:
        stmt = '''
            SELECT
                tz.zim_id, tz.zim_entry
            FROM
                tag_zim tz
                LEFT JOIN tag t on tz.tag_id = t.id
            GROUP BY tz.zim_id, tz.zim_entry
            -- Match only TagZimEntries that have all the Tag names.
            HAVING array_agg(t.name)::TEXT[] @> %(tag_names)s::TEXT[]
        '''
    return stmt, params
