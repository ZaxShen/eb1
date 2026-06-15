"""MongoDB client — shared connection used across all pipelines."""

from pymongo import MongoClient
from pymongo.database import Database

from config.settings import settings

_client: MongoClient | None = None
_input_client: MongoClient | None = None


def get_client() -> MongoClient:
    global _client
    if _client is None:
        _client = MongoClient(settings.mongodb_uri)
    return _client


def get_db() -> Database:
    """Output database — pipeline writes (sms_chat_segments, matching_signals, taxonomy)."""
    return get_client()[settings.mongodb_db_name]


def get_input_db() -> Database:
    """
    Input database for analysis pipeline reads (users / chats / chat_messages).

    Uses MONGODB_INPUT_URI when set (PROD mode).
    Falls back to the local output database when unset (offline / local-only mode).
    """
    global _input_client
    if settings.mongodb_input_uri:
        if _input_client is None:
            _input_client = MongoClient(settings.mongodb_input_uri)
        db_name = settings.mongodb_input_db_name or settings.mongodb_db_name
        return _input_client[db_name]
    return get_db()


def close_client() -> None:
    global _client, _input_client
    if _input_client is not None:
        _input_client.close()
        _input_client = None
    if _client is not None:
        _client.close()
        _client = None

