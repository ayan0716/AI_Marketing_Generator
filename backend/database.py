"""MongoDB connection (Motor async driver).
Collections
-----------
users       - (future) account owners          {_id, name, email, created_at}
products    - product being marketed           {_id, name, description, created_at}
campaigns   - one campaign brief per run       {_id, product_id, product_name, target_audience,
                                                platform, objective, tone, language, status, created_at}
strategies  - structured AI marketing strategy {_id, campaign_id, data, provider, model, created_at}
contents    - (Phase 2+) generated posts/ads   {_id, campaign_id, strategy_id, type, body, created_at}
"""
import certifi
from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase
from config import get_settings
_client = None
_db: AsyncIOMotorDatabase | None = None
async def connect() -> AsyncIOMotorDatabase:
    global _client, _db
    s = get_settings()
    if s.use_mock_db:
        from mongomock_motor import AsyncMongoMockClient
        _client = AsyncMongoMockClient()
    else:
        _client = AsyncIOMotorClient(
            s.mongodb_uri,
            serverSelectionTimeoutMS=20000,  # Atlas free clusters can be slow to wake
            tlsCAFile=certifi.where(),  # reliable CA bundle on Windows
        )
        await _client.admin.command("ping")  # fail fast if unreachable
    _db = _client[s.mongodb_db]
    await _create_indexes(_db)
    return _db
async def _create_indexes(db: AsyncIOMotorDatabase) -> None:
    await db.campaigns.create_index([("created_at", -1)])
    await db.strategies.create_index("campaign_id", unique=True)
    await db.products.create_index("name")
    await db.users.create_index("email", unique=True, sparse=True)
    await db.contents.create_index("campaign_id")
    await db.contents.create_index([("campaign_id", 1), ("platform", 1)], unique=True)  # Phase 2: one doc per platform
async def disconnect() -> None:
    if _client is not None:
        _client.close()
def get_db() -> AsyncIOMotorDatabase:
    if _db is None:
        raise RuntimeError("Database not initialised")
    return _db