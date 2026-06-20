import asyncio
import logging
from bson.objectid import ObjectId
from motor.motor_asyncio import AsyncIOMotorClient
from typing import List, Dict, Any, Optional
from config import Config

logger = logging.getLogger(__name__)

class MultiDB:
    def __init__(self, uris: List[str], db_name: str):
        self.clients: List[AsyncIOMotorClient] = []
        self.collections = []
        
        for uri in uris:
            try:
                client = AsyncIOMotorClient(uri)
                client.get_io_loop = asyncio.get_running_loop
                self.clients.append(client)
                self.collections.append(client[db_name]["files"])
            except Exception as e:
                logger.error(f"Failed to connect to Mongo Shard URI: {e}")

        if not self.collections:
            logger.warning("No database collections active. Bot features will fail.")
            
        if self.clients:
            self.settings = self.clients[0][db_name]["settings"]
            self.users = self.clients[0][db_name]["users"]
            self.groups = self.clients[0][db_name]["groups"]
            self.jobs = self.clients[0][db_name]["indexing_jobs"]

    async def ensure_indexes(self):
        """Builds MongoDB Text Indexes for lightning-fast searching."""
        if not self.collections: return
        for coll in self.collections:
            try:
                await coll.create_index(
                    [("title", "text")], 
                    background=True,
                    language_override="dummy_bot_lang"
                )
                await coll.create_index("language", background=True)
            except Exception as e:
                logger.error(f"Index creation error: {e}")
        return True

    async def add_index_job(self, chat_id, chat_name, last_msg_id):
        job_id = f"job_{chat_id}"
        await self.jobs.update_one(
            {"_id": job_id},
            {"$set": {
                "_id": job_id,
                "chat_id": chat_id,
                "chat_name": chat_name,
                "current_id": last_msg_id,
                "status": "pending",
                "scanned": 0,
                "saved": 0,
                "duplicates": 0
            }},
            upsert=True
        )
        return True

    async def get_active_job(self):
        if not self.clients: return None
        return await self.jobs.find_one({"status": {"$in": ["pending", "processing"]}})

    async def update_job(self, job_id: str, updates: dict):
        if not self.clients: return
        await self.jobs.update_one({"_id": job_id}, {"$set": updates})

    async def get_user_settings(self, user_id: int):
        if not self.clients: return {}
        user = await self.users.find_one({"user_id": user_id})
        if not user:
            default = {"user_id": user_id, "search_mode": "default", "quality": "all", "language": "all", "size": "all"}
            await self.users.insert_one(default)
            return default
        return user

    async def update_user_setting(self, user_id: int, key: str, value: Any):
        if not self.clients: return
        await self.users.update_one({"user_id": user_id}, {"$set": {key: value}}, upsert=True)

    async def get_group_settings(self, chat_id: int):
        if not self.clients: return {}
        group = await self.groups.find_one({"chat_id": chat_id})
        if not group:
            default = {
                "chat_id": chat_id, "search_mode": "let_members_choose",
                "quality_lock": "none", "language_lock": "none", "size_lock": "none", 
                "admins": [],
                "connected_by": None
            }
            await self.groups.insert_one(default)
            return default
        return group

    async def update_group_setting(self, chat_id: int, key: str, value: Any):
        if not self.clients: return
        await self.groups.update_one({"chat_id": chat_id}, {"$set": {key: value}}, upsert=True)

    async def get_admin_groups(self, user_id: int):
        if not self.clients: return []
        cursor = self.groups.find({"admins": user_id})
        return await cursor.to_list(length=50)

    async def get_connected_groups(self, user_id: int):
        if not self.clients: return []
        cursor = self.groups.find({"connected_by": user_id})
        return await cursor.to_list(length=50)

    async def get_settings(self) -> Dict[str, Any]:
        if not self.clients: return {}
        settings = await self.settings.find_one({"_id": "bot_settings"})
        if not settings:
            default = {
                "_id": "bot_settings", 
                "shortener_enabled": Config.USE_SHORTENERS, 
                "shortener_api": "", 
                "shortener_url": "https://gplinks.in/api", 
                "requests_enabled": True,
                "inside_enabled": False,
                "inside_words": [],
                "inside_times": 5,
                "inside_channels": [],
                "inside_placement": "movie",
                "file_delete_enabled": False,
                "file_delete_time": 10,
                "filter_delete_enabled": False,
                "filter_delete_time": 5,
                "bulk_enabled": True
            }
            await self.settings.insert_one(default)
            return default
        return settings

    async def update_settings(self, updates: Dict[str, Any]) -> bool:
        if not self.clients: return False
        await self.settings.update_one({"_id": "bot_settings"}, {"$set": updates}, upsert=True)
        return True

    async def insert_file(self, file_data: Dict[str, Any], shard_index: Optional[int] = None) -> bool:
        if not self.collections: return False
        target_shard = shard_index % len(self.collections) if shard_index is not None else 0
        try:
            await self.collections[target_shard].insert_one(file_data)
            return True
        except Exception: return False

    async def check_exists(self, crypto_hash: str) -> bool:
        if not self.collections: return False
        tasks = [coll.find_one({"crypto_hash": crypto_hash}) for coll in self.collections]
        results = await asyncio.gather(*tasks)
        return any(res is not None for res in results)

    async def get_file(self, db_id: str) -> Optional[Dict[str, Any]]:
        if not self.collections: return None
        try: obj_id = ObjectId(db_id)
        except Exception: return None
        tasks = [coll.find_one({"_id": obj_id}) for coll in self.collections]
        results = await asyncio.gather(*tasks)
        for res in results:
            if res: return res
        return None

    async def _safe_search(self, collection, query_filter: dict, skip: int, limit: int) -> List[Dict[str, Any]]:
        cursor = collection.find(query_filter).skip(skip).limit(limit)
        return await cursor.to_list(length=limit)

    async def search_files(self, query: str, skip: int = 0, limit: int = 10, exact: bool = False) -> List[Dict[str, Any]]:
        if not self.collections: return []
        
        combined_results = []
        
        try:
            text_filter = {"$text": {"$search": f"\"{query}\"" if exact else query}}
            tasks = [self._safe_search(coll, text_filter, skip, limit) for coll in self.collections]
            results = await asyncio.gather(*tasks)
            for result_group in results: combined_results.extend(result_group)
        except Exception:
            pass 
            
        if not combined_results and not exact:
            try:
                regex_pattern = f".*{'.*'.join(query.split())}.*"
                regex_filter = {"title": {"$regex": regex_pattern, "$options": "i"}}
                tasks_regex = [self._safe_search(coll, regex_filter, skip, limit) for coll in self.collections]
                results_regex = await asyncio.gather(*tasks_regex)
                for result_group in results_regex: combined_results.extend(result_group)
            except Exception as e:
                logger.error(f"Regex Fallback Error: {e}")
                
        return combined_results[:limit]

    async def global_stats(self) -> Dict[str, Any]:
        stats = {
            "shards_active": len(self.collections), 
            "total_files": 0, 
            "total_size_bytes": 0, 
            "indexed_metadata": 0,
            "corrupted_files": 0,  # <--- NEW CORRUPTED COUNTER
            "shard_distribution": []
        }
        
        for client, coll in zip(self.clients, self.collections):
            try:
                db_obj = client[Config.DB_NAME]
                coll_stats = await db_obj.command("collStats", "files")
                count = coll_stats.get("count", 0)
                stats["shard_distribution"].append(count)
                stats["total_files"] += count
                stats["total_size_bytes"] += coll_stats.get("storageSize", 0)
                
                processed = await coll.count_documents({"language": {"$exists": True, "$ne": "pending"}})
                stats["indexed_metadata"] += processed

                # Count how many files were specifically tagged as corrupted
                corrupted = await coll.count_documents({"language": "corrupted"})
                stats["corrupted_files"] += corrupted
            except Exception:
                count = await coll.count_documents({})
                stats["shard_distribution"].append(count)
                stats["total_files"] += count

                processed = await coll.count_documents({"language": {"$exists": True, "$ne": "pending"}})
                stats["indexed_metadata"] += processed

                corrupted = await coll.count_documents({"language": "corrupted"})
                stats["corrupted_files"] += corrupted
                
        total_capacity_bytes = len(self.collections) * 512 * 1024 * 1024
        stats["space_left_bytes"] = max(0, total_capacity_bytes - stats["total_size_bytes"])
        avg_obj_size = stats["total_size_bytes"] / stats["total_files"] if stats["total_files"] > 0 else 300
        stats["estimated_files_left"] = int(stats["space_left_bytes"] / avg_obj_size) if avg_obj_size > 0 else 0
        return stats

db = MultiDB(Config.DB_URIS, Config.DB_NAME)
