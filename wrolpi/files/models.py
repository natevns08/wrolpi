import pathlib

from sqlalchemy import Integer, Column, String, Computed, Boolean
from sqlalchemy.orm import deferred, Session, validates

import wrolpi.files.indexers
from wrolpi.common import Base, ModelHelper, get_media_directory, tsvector, logger, get_model_by_table_name, \
    truncate_object_bytes
from wrolpi.dates import TZDateTime, from_timestamp, now
from wrolpi.media_path import MediaPathType
from wrolpi.vars import PYTEST, FILE_MAX_TEXT_SIZE

logger = logger.getChild(__name__)


class File(ModelHelper, Base):
    """A representation of a file on disk.

    Can be searched using `textsearch` once the data has been populated by the respective Indexer.
    """
    __tablename__ = 'file'
    path: pathlib.Path = Column(MediaPathType, primary_key=True)

    associated = Column(Boolean, default=False)
    full_stem = Column(String)  # f'{directory}/{stem}'
    idempotency = Column(TZDateTime, default=lambda: now())
    indexed = Column(Boolean, default=False)
    mimetype = Column(String)  # wrolpi.files.lib.get_mimetype
    model = Column(String)  # Filled out by the modeler.  Will be the table name (video, archive, etc.).
    modification_datetime = Column(TZDateTime)
    size = Column(Integer)
    suffix = Column(String)  # aka the extension.
    title = Column(String)  # Provided by the modeler, or it will be the entire file name (with suffix).

    a_text = deferred(Column(String))
    b_text = deferred(Column(String))
    c_text = deferred(Column(String))
    d_text = deferred(Column(String))
    textsearch = deferred(
        Column(tsvector, Computed('''
            setweight(to_tsvector('english'::regconfig, COALESCE(a_text, '')), 'A'::"char") ||
            setweight(to_tsvector('english'::regconfig, COALESCE(b_text, '')), 'B'::"char") ||
            setweight(to_tsvector('english'::regconfig, COALESCE(c_text, '')), 'C'::"char") ||
            setweight(to_tsvector('english'::regconfig, COALESCE(d_text, '')), 'D'::"char")
            ''')))

    prefetched_model = None  # This may be filled with record matching `model`.

    def __repr__(self):
        path = str(self.path.relative_to(get_media_directory()))
        return f'<File {path=} mime={self.mimetype} model={self.model}>'

    def __json__(self) -> dict:
        path = self.path.relative_to(get_media_directory())
        d = dict(
            associated=self.associated,
            directory=self.path.parent,
            full_stem=self.full_stem,
            key=path,  # React browser expects this.
            mimetype=self.mimetype,
            model=self.model,
            modified=self.modification_datetime,  # React browser expects this.
            path=path,
            size=self.size,
            suffix=self.suffix,
            title=self.title,
        )
        if self.model and self.prefetched_model:
            d[self.model] = self.prefetched_model.__json__()
        elif self.model:
            model: ModelHelper = get_model_by_table_name(self.model)
            session = Session.object_session(self)
            instance = model.find_by_path(self.path, session)
            if not instance:
                logger.warning(f'Could not find instance of {model} for {self.path}')
                return d
            d[self.model] = instance.__json__()

        return d

    def __eq__(self, other):
        if isinstance(other, File):
            return other.path == self.path
        if isinstance(other, pathlib.Path):
            return other == self.path
        if isinstance(other, str):
            return other == str(self.path)
        return False

    @property
    def indexer(self):
        from wrolpi.files import lib
        return wrolpi.files.indexers.find_indexer(self)

    def do_index(self, force_index: bool = False):
        """Gather any missing information about this file.  Index the contents of this file using an Indexer."""
        if not self.mimetype:
            self.do_stats()

        try:
            if force_index or self.indexed is not True:
                # Get the indexer on a separate line for debugging.
                indexer = self.indexer
                # Only read the contents of the file once.
                start = now()
                a_text, b_text, c_text, d_text = indexer.create_index(self)
                self.a_text = truncate_object_bytes(a_text, FILE_MAX_TEXT_SIZE)
                self.b_text = truncate_object_bytes(b_text, FILE_MAX_TEXT_SIZE)
                self.c_text = truncate_object_bytes(c_text, FILE_MAX_TEXT_SIZE)
                self.d_text = truncate_object_bytes(d_text, FILE_MAX_TEXT_SIZE)
                if (total_seconds := (now() - start).total_seconds()) > 1:
                    logger.info(f'Indexing {self.path} took {total_seconds} seconds')

            self.indexed = True
        except Exception as e:
            logger.error(f'Failed to index {self.path}', exc_info=e)
            if PYTEST:
                raise

    def do_stats(self) -> bool:
        """Assign the mimetype, title, size, modification_time of this file.

        Returns True if the file has changed since last index.  Change is detected by comparing old size, mimetype
        modification datetime."""
        from wrolpi.files.lib import split_path_stem_and_suffix, split_file_name_words, get_mimetype

        old_mimetype = self.mimetype
        old_size = self.size
        old_modification_datetime = self.modification_datetime

        self.mimetype = get_mimetype(self.path)
        stem, self.suffix = split_path_stem_and_suffix(self.path)
        self.full_stem = f'{self.path.parent}/{stem}'
        self.title = self.title or self.path.name
        stat = self.path.stat()
        self.size = stat.st_size
        self.modification_datetime = from_timestamp(stat.st_mtime)

        changed = old_mimetype != self.mimetype \
                  or old_size != self.size \
                  or old_modification_datetime != self.modification_datetime

        if changed:
            self.indexed = False
            # Use file stem as a_text.  This may be overwritten by the correct indexer.
            self.a_text = self.a_text or split_file_name_words(stem)
            # Clear old indexes, this file has changed and must be re-indexed.
            self.b_text = self.c_text = self.d_text = None
        return changed

    @validates('path')
    def validate_path(self, key, value):
        value = pathlib.Path(value) if not isinstance(value, pathlib.Path) else value
        if not value.is_absolute():
            raise ValueError(f'File path must always be absolute! {value}')

        if not str(value).startswith(str(get_media_directory())):
            raise ValueError(f'File path {value} not in {get_media_directory()}')

        return value

    @classmethod
    def upsert(cls, path, session: Session) -> Base:
        if file := session.query(File).filter_by(path=path).one_or_none():
            return file
        file = File(path=path)
        session.add(file)
        return file
