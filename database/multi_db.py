import asyncio
import logging
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

    async def insert_file(self, file_data: Dict[str, Any], shard_index: Optional[int] = None) -> bool:
        if not self.collections:
            return False
        
        target_shard = shard_index % len(self.collections) if shard_index is not None else 0
        try:
            await self.collections[target_shard].insert_one(file_data)
            return True
        except Exception as e:
            logger.error(f"Insert error on shard {target_shard}: {e}")
            return False

    async def _safe_search(self, collection, query_filter: dict, skip: int, limit: int) -> List[Dict[str, Any]]:
        cursor = collection.find(query_filter).skip(skip).limit(limit)
        return await cursor.to_list(length=limit)

    async def search_files(self, query: str, skip: int = 0, limit: int = 10, exact: bool = False) -> List[Dict[str, Any]]:
        if not self.collections:
            return []

        regex_pattern = query if exact else f".*{'.*'.join(query.split())}.*"
        query_filter = {"title": {"$regex": regex_pattern, "$options": "i"}}

        tasks = [self._safe_search(coll, query_filter, skip, limit) for coll in self.collections]
        
        try:
            results = await asyncio.gather(*tasks)
            combined_results = []
            for result_group in results:
                combined_results.extend(result_group)
            
            return combined_results[:limit]
        except Exception as e:
            logger.error(f"Concurrent Search Failed: {e}")
            return []

    async def global_stats(self) -> Dict[str, Any]:
        """
        Aggregates deep stats across the multi-DB setup including storage capacities.
        Assumes standard MongoDB Free Cluster limits (512MB per URI).
        """
        stats = {
            "shards_active": len(self.collections),
            "total_files": 0,
            "total_size_bytes": 0,
            "shard_distribution": []
        }

        for client, coll in zip(self.clients, self.collections):
            try:
                db_obj = client[Config.DB_NAME]
                coll_stats = await db_obj.command("collStats", "files")
                
                count = coll_stats.get("count", 0)
                size = coll_stats.get("storageSize", 0)
                
                stats["shard_distribution"].append(count)
                stats["total_files"] += count
                stats["total_size_bytes"] += size
            except Exception as e:
                # Fallback if collStats fails (e.g. empty new collection)
                count = await coll.count_documents({})
                stats["shard_distribution"].append(count)
                stats["total_files"] += count

        # 512 MB per shard
        total_capacity_bytes = len(self.collections) * 512 * 1024 * 1024
        stats["space_left_bytes"] = max(0, total_capacity_bytes - stats["total_size_bytes"])
        
        avg_obj_size = stats["total_size_bytes"] / stats["total_files"] if stats["total_files"] > 0 else 300
        stats["estimated_files_left"] = int(stats["space_left_bytes"] / avg_obj_size) if avg_obj_size > 0 else 0

        return stats

db = MultiDB(Config.DB_URIS, Config.DB_NAME)
