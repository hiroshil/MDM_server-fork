import os
import json
import time
from hashlib import md5
from datetime import datetime
from sqlalchemy import String, Column, DateTime, asc
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy import create_engine
from sqlalchemy.pool import NullPool
from sqlalchemy.orm import sessionmaker, scoped_session
from contextlib import contextmanager
from constants import QUEUING, COMPLETED, ERROR, STOPPED
from exceptions import TaskNotExist
sql_engine = create_engine('sqlite:///data.db', poolclass=NullPool)
Base = declarative_base()
session_factory = sessionmaker(bind=sql_engine, autoflush=True, autocommit=False)
Session = scoped_session(session_factory)

@contextmanager
def session_commit():
    session = Session()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        Session.remove()

@contextmanager
def session_query():
    session = Session()
    try:
        yield session
    except Exception:
        session.rollback()
        raise
    finally:
        Session.remove()

class TaskDB(Base):
    __tablename__ = 'tasks'
    id = Column(String, primary_key=True)
    url = Column(String, nullable=False)
    path = Column(String)
    headers = Column(String, default='')
    quality = Column(String, default='best')
    create_at = Column(DateTime, default=datetime.now())
    status = Column(String, default=QUEUING)
    error = Column(String, default='')
    qualities = Column(String, default='[]')
    speed = Column(String, default='')
    eta = Column(String, default='')
    percent = Column(String, default='')

    def serialize(self):
        return {'id': self.id, 'url': self.url, 'path': self.path, 'file_name': os.path.basename(self.path), 'headers': json.loads(self.headers), 'quality': self.quality, 'status': self.status, 'error': self.error, 'qualities': json.loads(self.qualities), 'speed': self.speed, 'eta': self.eta, 'percent': self.percent, 'create_at': self.create_at.timestamp()}

    @classmethod
    def makeTaskId(cls, url):
        h = md5(url)
        return h.hexdigest()

    @classmethod
    def create(cls, tid, url, headers, path):
        with session_commit() as s:
            s.add(cls(id=tid, url=url, path=path, headers=headers))

    @classmethod
    def update(cls, tid, **kwargs):
        kwargs = dict(kwargs)
        with session_commit() as s:
            row_count = s.query(cls).filter_by(id=tid).update(kwargs, synchronize_session='fetch')
            if row_count == 0:
                raise TaskNotExist(tid)

    @classmethod
    def stop_tasks(cls):
        with session_commit() as s:
            s.query(cls).filter(cls.status.notin_([COMPLETED, ERROR, STOPPED])).update({'status': STOPPED, 'speed': '', 'eta': '', 'percent': ''}, synchronize_session='fetch')

    @classmethod
    def getTask(cls, tid):
        with session_query() as s:
            task = s.query(cls).filter_by(id=tid).first()
            if task:
                return task
        raise TaskNotExist(tid)

    @classmethod
    def getAllTask(cls):
        with session_query() as s:
            return s.query(cls).all()

    @classmethod
    def getTaskByStatus(cls, status):
        with session_query() as s:
            task = s.query(cls).filter_by(status=status).first()
            if task:
                return task

    @classmethod
    def getAllTasksByStatus(cls, status):
        with session_query() as s:
            return s.query(cls).filter_by(status=status).order_by(asc(cls.create_at)).all()

    @classmethod
    def delete(cls, tid):
        with session_commit() as s:
            s.query(cls).filter_by(id=tid).delete()

    def __repr__(self):
        return 'id: %s, url: %s, status: %s' % (self.id, self.url, self.status)

Base.metadata.create_all(bind=sql_engine)
if __name__ == '__main__':
    task = TaskDB.getTask('9b981ade347bd136058e11749a5cf17b')
    print(task)
    time.sleep(10)
