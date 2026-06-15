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
                # Quick timeout configuration for stability testing
                client.get_io_loop = asyncio.get_running_loop
                self.clients.append(client)
                self.collections.append(client[db_name]["files"])
            except Exception as e:
                logger.error(f"Failed to connect to Mongo Shard URI: {e}")

        if not self.collections:
            logger.warning("No database collections active. Bot features will fail.")

    async def insert_file(self, file_data: Dict[str, Any], shard_index: Optional[int] = None) -> bool:
        """
        Inserts file metadata. If shard_index is not provided, distributes via round-robin or smallest shard.
        For simplicity, targets shard 0 strictly to avoid fragmenting same-file updates in this iteration.
        """
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
        """
        Executes an asynchronous fan-out search across all DB shards using asyncio.gather.
        Implements basic fuzzy spelling search if exact is False.
        """
        if not self.collections:
            return []

        # Fuzzy regex for search matching. Supports spaces and slight misspellings conceptually.
        regex_pattern = query if exact else f".*{'.*'.join(query.split())}.*"
        query_filter = {
            "title": {"$regex": regex_pattern, "$options": "i"}
        }

        # Concurrently search all shards
        tasks = [
            self._safe_search(coll, query_filter, skip, limit) 
            for coll in self.collections
        ]
        
        try:
            results = await asyncio.gather(*tasks)
            combined_results = []
            for result_group in results:
                combined_results.extend(result_group)
            
            # Additional deduplication or sorting logic by DB ID or timestamp can go here
            # Slicing the result down to the global limit requested across the layer
            return combined_results[:limit]
        except Exception as e:
            logger.error(f"Concurrent Search Failed: {e}")
            return []

    async def global_stats(self) -> Dict[str, int]:
        """
        Aggregates stats across the multi-DB setup.
        """
        tasks = [coll.count_documents({}) for coll in self.collections]
        counts = await asyncio.gather(*tasks)
        return {
            "shards_active": len(self.collections),
            "total_files": sum(counts),
            "shard_distribution": counts
        }

# Global multi-database pool instance
db = MultiDB(Config.DB_URIS, Config.DB_NAME)
