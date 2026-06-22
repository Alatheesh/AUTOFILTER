import asyncio
import logging
import time
import re
from typing import List, Dict, Any, Optional, Tuple
from bson.objectid import ObjectId
from motor.motor_asyncio import AsyncIOMotorClient
from config import Config

logger = logging.getLogger(__name__)

class MultiDB:
    def __init__(self):
        # Config.DB_URIS is already a list
        self.uris = getattr(Config, "DB_URIS", [])
        
        if not self.uris:
            raise ValueError("❌ No database URIs found in configuration!")
            
        self.clients: List[AsyncIOMotorClient] = []
        self.collections: List[Any] = []
        
        match = re.search(r"mongodb\+srv://[^/]+/([^?]+)", self.uris[0])
        db_name = match.group(1) if match else "AutoFilter"
        
        for idx, uri in enumerate(self.uris):
            try:
                client = AsyncIOMotorClient(uri)
                self.clients.append(client)
                self.collections.append(client[db_name]["files"])
                logger.info(f"✅ Successfully linked Shard {idx}")
            except Exception as e:
                logger.error(f"❌ Failed to connect to Shard {idx}: {e}")
                
        if not self.collections:
            raise RuntimeError("❌ MultiDB failed to connect to any active shards!")

        master_db = self.clients[0][db_name]
        self.users = master_db["users"]
        self.settings = master_db["settings"]
        self.groups = master_db["groups"]
        self.jobs = master_db["indexing_jobs"]
        self.broadcast_logs = master_db["broadcast_logs"]
        self.batch_stats = master_db["batch_stats"]
        self.scheduled_broadcasts = master_db["scheduled_broadcasts"]
        
        self.MAX_FILES_PER_SHARD = 800000 
        self.MAX_SHARD_CAPACITY_BYTES = 512 * 1024 * 1024

    async def ensure_indexes(self):
        for idx, coll in enumerate(self.collections):
            try:
                await coll.create_index([("file_name", "text"), ("caption", "text")])
            except Exception as e:
                logger.error(f"❌ Indexing failed on Shard {idx}: {e}")

    async def insert_file(self, file_data: Dict[str, Any]) -> bool:
        if not self.collections: return False
        
        # Simple load balancer: pick shard with lowest doc count
        counts = [await coll.estimated_document_count() for coll in self.collections]
        target_shard = counts.index(min(counts))
        
        try:
            await self.collections[target_shard].insert_one(file_data)
            return True
        except Exception as e:
            logger.error(f"❌ Failed writing file: {e}")
            return False

    async def update_file_metadata(self, file_id: str, update_data: Dict[str, Any]) -> bool:
        for coll in self.collections:
            try:
                result = await coll.update_one({"file_id": file_id}, {"$set": update_data})
                if result.modified_count > 0: return True
            except Exception: pass
        return False

    async def search_files(self, query: str, skip: int = 0, limit: int = 10, exact: bool = False) -> List[Dict[str, Any]]:
        if not self.collections: return []
        text_filter = {"$text": {"$search": f"\"{query}\"" if exact else query}}
        
        async def _safe_search(coll, filter_query):
            try:
                return await coll.find(filter_query).limit(limit + skip).to_list(length=limit + skip)
            except Exception:
                return []

        tasks = [_safe_search(c, text_filter) for c in self.collections]
        all_results = await asyncio.gather(*tasks)
        merged = []
        for res in all_results: merged.extend(res)
        
        # Deduplicate
        seen = set()
        unique = []
        for f in merged:
            if f["file_id"] not in seen:
                unique.append(f)
                seen.add(f["file_id"])
        return unique[skip:skip+limit]

    # ==========================================
    # 💾 THE PERFECT ANALYTICS SYSTEM
    # ==========================================
    async def global_stats(self) -> Dict[str, Any]:
        """Calculates exact cluster analytics by weighing all system databases natively."""
        total_physical_used = 0
        total_indexed_files = 0
        distribution = []
        indexed_meta = 0
        corrupted_files = 0
        
        for client, coll in zip(self.clients, self.collections):
            try:
                # This pulls the weight of AutoFilter + admin + local combined!
                db_info = await client.admin.command("listDatabases")
                shard_physical_used = db_info.get("totalSize", 0)
                total_physical_used += shard_physical_used
            except Exception as e:
                logger.error(f"Failed to get total cluster size natively: {e}")
                db_stats = await coll.database.command("dbStats")
                total_physical_used += db_stats.get("storageSize", 0) + db_stats.get("indexSize", 0)

            doc_count = await coll.estimated_document_count()
            total_indexed_files += doc_count
            distribution.append(doc_count)

            indexed_meta += await coll.count_documents({"language": {"$exists": True, "$ne": "pending", "$ne": "corrupted"}})
            corrupted_files += await coll.count_documents({"language": "corrupted"})

        total_cluster_capacity = len(self.collections) * self.MAX_SHARD_CAPACITY_BYTES
        space_remaining = max(0, total_cluster_capacity - total_physical_used)
        
        if total_indexed_files > 0 and total_physical_used > 0:
            avg_file_size = total_physical_used / total_indexed_files
            estimated_capacity_left = int(space_remaining / avg_file_size)
        else:
            estimated_capacity_left = 0

        return {
            "total_files": total_indexed_files,
            "total_size_bytes": total_physical_used,
            "space_left_bytes": space_remaining,
            "estimated_files_left": estimated_capacity_left,
            "shard_distribution": distribution,
            "indexed_metadata": indexed_meta,
            "corrupted_files": corrupted_files
        }

    async def get_active_job(self):
        return await self.jobs.find_one({"status": {"$in": ["pending", "processing"]}})

    async def update_job(self, job_id: str, updates: dict):
        await self.jobs.update_one({"_id": job_id}, {"$set": updates})

    async def check_exists(self, crypto_hash: str) -> bool:
        if not self.collections: return False
        tasks = [coll.find_one({"crypto_hash": crypto_hash}) for coll in self.collections]
        results = await asyncio.gather(*tasks)
        return any(res is not None for res in results)

    async def get_file(self, db_id: str) -> Optional[Dict[str, Any]]:
        if not self.collections: return None
        try:
            obj_id = ObjectId(db_id)
        except Exception: return None
        tasks = [coll.find_one({"_id": obj_id}) for coll in self.collections]
        results = await asyncio.gather(*tasks)
        for res in results:
            if res: return res
        return None

    async def get_user_settings(self, user_id: int):
        user = await self.users.find_one({"user_id": user_id})
        if not user:
            default = {"user_id": user_id, "search_mode": "default", "quality": "all", "language": "all", "size": "all"}
            await self.users.insert_one(default)
            return default
        return user

    async def update_user_setting(self, user_id: int, key: str, value: Any):
        await self.users.update_one({"user_id": user_id}, {"$set": {key: value}}, upsert=True)

    async def get_group_settings(self, chat_id: int):
        group = await self.groups.find_one({"chat_id": chat_id})
        if not group:
            default = {"chat_id": chat_id, "search_mode": "let_members_choose", "quality_lock": "none", "language_lock": "none", "size_lock": "none", "admins": [], "connected_by": None}
            await self.groups.insert_one(default)
            return default
        return group

    async def update_group_setting(self, chat_id: int, key: str, value: Any):
        await self.groups.update_one({"chat_id": chat_id}, {"$set": {key: value}}, upsert=True)

    async def get_connected_groups(self, user_id: int):
        cursor = self.groups.find({"connected_by": user_id})
        return await cursor.to_list(length=50)

    async def get_settings(self) -> Dict[str, Any]:
        settings = await self.settings.find_one({"_id": "bot_settings"})
        if not settings:
            default = {"_id": "bot_settings"}
            await self.settings.insert_one(default)
            return default
        return settings

    async def update_settings(self, updates: Dict[str, Any]) -> bool:
        await self.settings.update_one({"_id": "bot_settings"}, {"$set": updates}, upsert=True)
        return True

    # Broadcast Helpers
    async def get_all_users(self): return self.users.find({})
    async def log_broadcast(self, batch_id: str, user_id: int, message_id: int): await self.broadcast_logs.insert_one({"batch_id": batch_id, "user_id": user_id, "message_id": message_id, "timestamp": time.time()})
    async def get_broadcast_logs(self, batch_id: str): return self.broadcast_logs.find({"batch_id": batch_id})
    async def delete_broadcast_batch(self, batch_id: str): await self.broadcast_logs.delete_many({"batch_id": batch_id}); await self.batch_stats.delete_one({"batch_id": batch_id})
    async def get_recent_batches(self): return self.broadcast_logs.aggregate([{"$group": {"_id": "$batch_id", "count": {"$sum": 1}}}, {"$sort": {"_id": -1}}, {"$limit": 5}])
    async def get_user_latest_broadcast(self, user_id: int): cursor = self.broadcast_logs.find({"user_id": user_id}).sort("timestamp", -1).limit(1); logs = await cursor.to_list(length=1); return logs[0] if logs else None
    async def delete_single_broadcast_log(self, user_id: int, message_id: int): await self.broadcast_logs.delete_one({"user_id": user_id, "message_id": message_id})
    async def add_batch_reaction(self, batch_id: str, emoji: str, user_id: int): return (await self.batch_stats.update_one({"batch_id": batch_id}, {"$addToSet": {f"reactions.{emoji}": user_id}}, upsert=True)).modified_count > 0
    async def add_batch_reply(self, batch_id: str, user_id: int): await self.batch_stats.update_one({"batch_id": batch_id}, {"$addToSet": {"replies": user_id}}, upsert=True)
    async def increment_batch_followup(self, batch_id: str): await self.batch_stats.update_one({"batch_id": batch_id}, {"$inc": {"followup_count": 1}}, upsert=True)
    async def get_batch_engagement(self, batch_id: str): doc = await self.batch_stats.find_one({"batch_id": batch_id}); return {"reactions": {k: len(v) for k, v in doc.get("reactions", {}).items()} if doc else {}, "replies": len(doc.get("replies", [])) if doc else 0, "followups": doc.get("followup_count", 0) if doc else 0}
    async def add_scheduled_broadcast(self, batch_id: str, admin_id: int, message_id: int, run_at: float, command_text: str): await self.scheduled_broadcasts.insert_one({"batch_id": batch_id, "admin_id": admin_id, "message_id": message_id, "run_at": run_at, "command_text": command_text, "status": "pending"})
    async def get_due_broadcasts(self): return await self.scheduled_broadcasts.find({"status": "pending", "run_at": {"$lte": time.time()}}).to_list(length=100)
    async def mark_broadcast_complete(self, schedule_id): await self.scheduled_broadcasts.update_one({"_id": schedule_id}, {"$set": {"status": "completed"}})
    async def cancel_scheduled_broadcast(self, batch_id: str) -> bool: return (await self.scheduled_broadcasts.delete_one({"batch_id": batch_id, "status": "pending"})).deleted_count > 0

db = MultiDB()
