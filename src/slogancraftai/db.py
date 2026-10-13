from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker

Base = declarative_base()


def create_session_factory(database_url):
    engine = create_engine(database_url, pool_pre_ping=True, hide_parameters=True)
    return sessionmaker(bind=engine, expire_on_commit=False), engine
