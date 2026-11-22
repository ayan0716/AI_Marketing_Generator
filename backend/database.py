"""MongoDB connection (Motor async driver).
Collections
-----------
users       - (future) account owners          {_id, name, email, created_at}
products    - product being marketed           {_id, name, description, created_at}
campaigns   - one campaign brief per run       {_id, product_id, product_name, target_audience,
                                                platform, objective, tone, language, status, created_at}
strategies  - structured AI marketing strategy {_id, campaign_id, data, provider, model, created_at}
contents    - Phase 2 platform copy            {_id, campaign_id, platform, variations, selected_index, ...}
creatives   - Phase 3 image creatives          {_id, campaign_id, format, concepts[{versions[]}], selected_concept_id, ...}
agent_runs  - Phase 4 agent run + step status  {_id, campaign_id, kind, scope, status, steps[], item_errors, ...}
agent_assets- Phase 4 reel / promo assets      {_id, campaign_id, key, kind, data, provider, model, ...}
agent_audit - Phase 4 approvals + exports      {_id, campaign_id, action, detail, at}
(campaigns also gain: plan{items[]}, approvals{key: status}, stale, source)
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
    await db.creatives.create_index([("campaign_id", 1), ("format", 1)], unique=True)  # Phase 3: one doc per format
    await db.agent_runs.create_index([("campaign_id", 1), ("created_at", -1)])  # Phase 4
    await db.agent_assets.create_index([("campaign_id", 1), ("key", 1)], unique=True)
    await db.agent_audit.create_index([("campaign_id", 1), ("at", -1)])
async def disconnect() -> None:
    if _client is not None:
        _client.close()
def get_db() -> AsyncIOMotorDatabase:
    if _db is None:
        raise RuntimeError("Database not initialised")
    return _db