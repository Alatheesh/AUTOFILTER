import logging
import time
import asyncio
import re
from typing import List, Dict, Any, Optional, Tuple
from motor.motor_asyncio import AsyncIOMotorClient
from config import Config

logger = logging.getLogger(__name__)

class MultiDB:
    def __init__(self):
        # 🚀 FIX: Config.DB_URIS is already a list! No need to split()
        self.uris = getattr(Config, "DB_URIS", [])
        
        if not self.uris:
            raise ValueError("❌ No database URIs found in configuration (DB_URIS is empty)!")
            
        self.clients: List[AsyncIOMotorClient] = []
        self.collections: List[Any] = []
        
        match = re.search(r"mongodb\+srv://[^/]+/([^?]+)", self.uris[0])
        db_name = match.group(1) if match else "AutoFilter"
        
        logger.info(f"⚙️ Initializing MultiDB Cluster with {len(self.uris)} shards...")
        
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

        # 👑 Core Administration Collections (Locked strictly to Shard 0)
        master_db = self.clients[0][db_name]
        self.users = master_db["users"]
        self.settings = master_db["settings"]
        self.groups = master_db["groups"]
        self.jobs = master_db["indexing_jobs"]  # Worker 1 State Memory
        self.broadcast_logs = master_db["broadcast_logs"]
        self.batch_stats = master_db["batch_stats"]
        self.scheduled_broadcasts = master_db["scheduled_broadcasts"]
        
        # Shared system cache for load balancer
        self.shard_metrics: List[Dict[str, Any]] = []
        self.last_metrics_update = 0
        
        # 🚨 THE HARD CAP FOR INDEXING (Worker 1 Only)
        self.MAX_FILES_PER_SHARD = 800000 
        self.MAX_SHARD_CAPACITY_BYTES = 512 * 1024 * 1024  # 512 MB for accurate /stats

    async def ensure_indexes(self):
        """Ensures high-performance text indexing across all connected shards."""
        for idx, coll in enumerate(self.collections):
            try:
                await coll.create_index([("file_name", "text"), ("caption", "text")])
                logger.info(f"🔍 Text Index optimized for Shard {idx}")
            except Exception as e:
                logger.error(f"❌ Indexing failed on Shard {idx}: {e}")

    async def _update_shard_metrics(self, force: bool = False):
        """Queries the actual MongoDB storage engine to pull true physical disk metrics."""
        now = time.time()
        if not force and self.shard_metrics and (now - self.last_metrics_update < 60):
            return  
            
        new_metrics = []
        for idx, coll in enumerate(self.collections):
            try:
                db_stats = await coll.database.command("dbStats")
                physical_used = db_stats.get("storageSize", 0) + db_stats.get("indexSize", 0)
                doc_count = await coll.estimated_document_count()
                
                is_full_for_indexing = doc_count >= self.MAX_FILES_PER_SHARD
                
                new_metrics.append({
                    "index": idx,
                    "doc_count": doc_count,
                    "physical_used": physical_used,
                    "is_full_for_indexing": is_full_for_indexing
                })
            except Exception as e:
                logger.error(f"⚠️ Could not pull real-time stats for Shard {idx}: {e}")
                new_metrics.append({
                    "index": idx,
                    "doc_count": 0,
                    "physical_used": 0,
                    "is_full_for_indexing": False
                })
                
        self.shard_metrics = new_metrics
        self.last_metrics_update = now

    # ==========================================
    # ⚙️ WORKER 1: AUTO-ROUTING LOAD BALANCER
    # ==========================================
    async def insert_file(self, file_data: Dict[str, Any]) -> bool:
        """Routes new files to the emptiest shard. Stops indexing into shards with >= 800,000 files."""
        if not self.collections: return False
        
        await self._update_shard_metrics()
        
        available_shards = [s for s in self.shard_metrics if not s["is_full_for_indexing"]]
        
        if not available_shards:
            logger.critical(f"🚨 ALL MONGO SHARDS HAVE REACHED THE {self.MAX_FILES_PER_SHARD} FILE LIMIT!")
            target_shard = min(self.shard_metrics, key=lambda x: x["doc_count"])["index"]
        else:
            target_shard = min(available_shards, key=lambda x: x["doc_count"])["index"]
            
        try:
            await self.collections[target_shard].insert_one(file_data)
            self.shard_metrics[target_shard]["doc_count"] += 1
            return True
        except Exception as e:
            logger.error(f"❌ Failed writing file to Shard {target_shard}: {e}")
            return False

    # ==========================================
    # ⚙️ WORKER 2: SAFE CROSS-SHARD UPDATER
    # ==========================================
    async def update_file_metadata(self, file_id: str, update_data: Dict[str, Any]) -> bool:
        """Updates language and subtitle tags. This runs freely regardless of shard limits."""
        for idx, coll in enumerate(self.collections):
            try:
                result = await coll.update_one({"file_id": file_id}, {"$set": update_data})
                if result.modified_count > 0:
                    return True
            except Exception as e:
                logger.error(f"⚠️ Worker 2 Error updating Shard {idx}: {e}")
        return False

    # ==========================================
    # 🔍 PARALLEL SEARCH ENGINE (DIVIDE & CONQUER)
    # ==========================================
    async def search_files(self, query: str, skip: int = 0, limit: int = 10, exact: bool = False) -> Tuple[List[Dict[str, Any]], int]:
        """Queries all database shards simultaneously in parallel and merges results seamlessly."""
        if not self.collections: return [], 0
        
        text_filter = {"$text": {"$search": f"\"{query}\"" if exact else query}}
        
        async def _safe_search(coll, filter_query):
            try:
                cursor = coll.find(filter_query).limit(limit + skip)
                return await cursor.to_list(length=limit + skip)
            except Exception:
                try:
                    regex_pattern = f".*{'.*'.join(query.split())}.*"
                    reg_filter = {"title": {"$regex": regex_pattern, "$options": "i"}}
                    cursor = coll.find(reg_filter).limit(limit + skip)
                    return await cursor.to_list(length=limit + skip)
                except Exception:
                    return []

        tasks = [_safe_search(c, text_filter) for c in self.collections]
        all_shard_results = await asyncio.gather(*tasks)
        
        merged_files = []
        for shard_files in all_shard_results:
            merged_files.extend(shard_files)
            
        seen_ids = set()
        unique_files = []
        for f in merged_files:
            if f["file_id"] not in seen_ids:
                unique_files.append(f)
                seen_ids.add(f["file_id"])
                
        total_found = len(unique_files)
        paginated_files = unique_files[skip:skip + limit]
        
        return paginated_files

    # ==========================================
    # 💾 THE PERFECT ANALYTICS SYSTEM
    # ==========================================
    async def global_stats(self) -> Dict[str, Any]:
        """Calculates precise system analytics matching your MongoDB web portal exactly."""
        await self._update_shard_metrics(force=True)
        
        total_physical_used = sum(s["physical_used"] for s in self.shard_metrics)
        total_indexed_files = sum(s["doc_count"] for s in self.shard_metrics)
        total_cluster_capacity = len(self.collections) * self.MAX_SHARD_CAPACITY_BYTES
        
        space_remaining = max(0, total_cluster_capacity - total_physical_used)
        
        if total_indexed_files > 0 and total_physical_used > 0:
            avg_file_size = total_physical_used / total_indexed_files
            estimated_capacity_left = int(space_remaining / avg_file_size)
        else:
            estimated_capacity_left = 0

        distribution = []
        for s in self.shard_metrics:
            distribution.append(s["doc_count"])

        indexed_meta = 0
        corrupted_files = 0
        for coll in self.collections:
            indexed_meta += await coll.count_documents({"language": {"$exists": True, "$ne": "pending", "$ne": "corrupted"}})
            corrupted_files += await coll.count_documents({"language": "corrupted"})

        return {
            "total_files": total_indexed_files,
            "total_size_bytes": total_physical_used,
            "space_left_bytes": space_remaining,
            "estimated_files_left": estimated_capacity_left,
            "shard_distribution": distribution,
            "indexed_metadata": indexed_meta,
            "corrupted_files": corrupted_files
        }

    # ==========================================
    # 🧹 VAULT SYSTEM & BROADCAST MANAGER
    # ==========================================
    async def get_all_users(self):
        return self.users.find({})

    async def log_broadcast(self, batch_id: str, user_id: int, message_id: int):
        await self.broadcast_logs.insert_one({
            "batch_id": batch_id,
            "user_id": user_id,
            "message_id": message_id,
            "timestamp": time.time()
        })

    async def get_broadcast_logs(self, batch_id: str):
        return self.broadcast_logs.find({"batch_id": batch_id})

    async def delete_broadcast_batch(self, batch_id: str):
        await self.broadcast_logs.delete_many({"batch_id": batch_id})
        await self.batch_stats.delete_one({"batch_id": batch_id})

    async def get_recent_batches(self):
        forty_eight_hours_ago = time.time() - (48 * 3600)
        pipeline = [
            {"$match": {"timestamp": {"$gte": forty_eight_hours_ago}}},
            {"$group": {"_id": "$batch_id", "count": {"$sum": 1}}},
            {"$sort": {"_id": -1}},
            {"$limit": 5}
        ]
        return self.broadcast_logs.aggregate(pipeline)

    async def get_user_latest_broadcast(self, user_id: int):
        cursor = self.broadcast_logs.find({"user_id": user_id}).sort("timestamp", -1).limit(1)
        logs = await cursor.to_list(length=1)
        return logs[0] if logs else None

    async def delete_single_broadcast_log(self, user_id: int, message_id: int):
        await self.broadcast_logs.delete_one({"user_id": user_id, "message_id": message_id})

    # ==========================================
    # 📊 BATCH ENGAGEMENT TRACKING
    # ==========================================
    async def add_batch_reaction(self, batch_id: str, emoji: str, user_id: int) -> bool:
        existing = await self.batch_stats.find_one({"batch_id": batch_id, "user_reacted": user_id})
        if existing: return False
        await self.batch_stats.update_one(
            {"batch_id": batch_id},
            {"$inc": {f"reactions.{emoji}": 1}, "$addToSet": {"user_reacted": user_id}},
            upsert=True
        )
        return True

    async def get_batch_engagement(self, batch_id: str) -> Dict[str, Any]:
        doc = await self.batch_stats.find_one({"batch_id": batch_id})
        if not doc: return {"reactions": {}, "replies": 0, "followups": 0}
        return {
            "reactions": {k: v for k, v in doc.get("reactions", {}).items() if not isinstance(v, list)},
            "replies": len(doc.get("replies", [])),
            "followups": doc.get("followup_count", 0)
        }

    async def add_batch_reply(self, batch_id: str, user_id: int):
        await self.batch_stats.update_one({"batch_id": batch_id}, {"$addToSet": {"replies": user_id}}, upsert=True)

    async def increment_batch_followup(self, batch_id: str):
        await self.batch_stats.update_one({"batch_id": batch_id}, {"$inc": {"followup_count": 1}}, upsert=True)

    # ==========================================
    # ⏰ SCHEDULER SYSTEM
    # ==========================================
    async def add_scheduled_broadcast(self, batch_id: str, admin_id: int, message_id: int, run_at: float, command_text: str):
        await self.scheduled_broadcasts.insert_one({
            "batch_id": batch_id,
            "admin_id": admin_id,
            "message_id": message_id,
            "run_at": run_at,
            "command_text": command_text,
            "status": "pending"
        })

    async def get_due_broadcasts(self):
        cursor = self.scheduled_broadcasts.find({"status": "pending", "run_at": {"$lte": time.time()}})
        return await cursor.to_list(length=100)

    async def mark_broadcast_complete(self, schedule_id):
        await self.scheduled_broadcasts.update_one({"_id": schedule_id}, {"$set": {"status": "completed"}})

    async def cancel_scheduled_broadcast(self, batch_id: str) -> bool:
        res = await self.scheduled_broadcasts.delete_one({"batch_id": batch_id, "status": "pending"})
        return res.deleted_count > 0

    # ==========================================
    # 📝 OTHER HELPERS & WORKER 1 MEMORY
    # ==========================================
    async def get_active_job(self):
        return await self.jobs.find_one({"status": {"$in": ["pending", "processing"]}})

    async def update_job(self, job_id: str, updates: dict):
        await self.jobs.update_one({"_id": job_id}, {"$set": updates})

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

    async def check_exists(self, crypto_hash: str) -> bool:
        if not self.collections: return False
        tasks = [coll.find_one({"crypto_hash": crypto_hash}) for coll in self.collections]
        results = await asyncio.gather(*tasks)
        return any(res is not None for res in results)

    async def get_file(self, db_id: str) -> Optional[Dict[str, Any]]:
        if not self.collections: return None
        try:
            from bson.objectid import ObjectId
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
            default = {
                "chat_id": chat_id, "search_mode": "let_members_choose",
                "quality_lock": "none", "language_lock": "none", "size_lock": "none", 
                "admins": [], "connected_by": None
            }
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

db = MultiDB()
