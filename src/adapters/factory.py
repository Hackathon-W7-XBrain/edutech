"""Factory: read env config + instantiate concrete adapters."""
from src.config import config
from src.adapters import ai, storage, userstore, vector
from src.adapters.sqlite_store import SQLiteUserStore


def make_ai():
    if config.ai_backend == "bedrock":
        return ai.BedrockAI(region=config.aws_region, model_id=config.ai_model_id)
    if config.ai_backend == "local":
        return ai.LocalAI()
    raise ValueError(f"Unknown AI_BACKEND: {config.ai_backend!r} (expected 'bedrock' or 'local')")


def make_storage():
    if config.storage_backend == "s3":
        return storage.S3Storage(bucket=config.storage_bucket, region=config.aws_region)
    if config.storage_backend == "local":
        return storage.LocalStorage(base_dir=config.storage_local_dir)
    raise ValueError(f"Unknown STORAGE_BACKEND: {config.storage_backend!r}")


def make_userstore():
    backend = config.userstore_backend
    if backend == "dynamodb":
        return userstore.DynamoDBUserStore(table_name=config.userstore_table, region=config.aws_region)
    if backend == "postgres":
        return userstore.PostgresUserStore(url=config.userstore_postgres_url)
    if backend == "sqlite":
        return SQLiteUserStore(db_path=config.userstore_sqlite_path)
    if backend == "documentdb":
        return userstore.DocumentDBUserStore(
            url=config.userstore_mongo_url,
            db_name=config.userstore_mongo_db,
            tls_ca_file=config.userstore_mongo_tls_ca,
        )
    if backend == "mysql":
        return userstore.MySQLUserStore(url=config.userstore_mysql_url)
    raise ValueError(f"Unknown USERSTORE_BACKEND: {backend!r} (expected dynamodb|postgres|sqlite|documentdb|mysql)")


# Vector store is special: LocalVector must be a singleton across requests so
# ingested docs persist for the process lifetime. (Bedrock KB is naturally
# stateful via the KB id.)
_local_vector_singleton: vector.LocalVector | None = None
def make_vector():
    global _local_vector_singleton
    if config.vector_backend == "bedrock_kb":
        return vector.BedrockKBVector(kb_id=config.vector_bedrock_kb_id, region=config.aws_region)
    if config.vector_backend == "local":
        if _local_vector_singleton is None:
            _local_vector_singleton = vector.LocalVector()
        return _local_vector_singleton
    raise ValueError(f"Unknown VECTOR_BACKEND: {config.vector_backend!r}")
