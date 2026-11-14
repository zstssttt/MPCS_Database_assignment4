import os
from dotenv import load_dotenv
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

load_dotenv()


def _env(key: str, default=None) -> str:
    value = os.getenv(key, default)
    if value is None:
        raise RuntimeError(f"Missing required environment variable: {key}")
    return value



MYSQL_URL = (
    f"mysql+pymysql://{_env('MYSQL_USER')}:{os.getenv('MYSQL_PASSWORD', '')}"
    f"@{_env('MYSQL_HOST')}:{_env('MYSQL_PORT')}/{_env('MYSQL_DB')}"
)


SQLITE_URL = f"sqlite:///{_env('SQLITE_PATH')}"

source_engine = create_engine(MYSQL_URL)
target_engine = create_engine(SQLITE_URL)

SourceSession = sessionmaker(bind=source_engine)
TargetSession = sessionmaker(bind=target_engine)