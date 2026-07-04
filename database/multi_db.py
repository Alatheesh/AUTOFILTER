import asyncio
import logging
import time
import re
from bson.objectid import ObjectId
from motor.motor_asyncio import AsyncIOMotorClient
from typing import List, Dict, Any, Optional
from config import Config

logger = logging.getLogger(__name__)

class MultiDB:
    def __init__(self, uris: List[str], db_name: str):
        self.clients: List[AsyncIOMotorClient] = []
        self.collections = []
        
        # Safely extract DB name even if connection pooling queries like ?maxPoolSize=500 are attached
        match = re.search(r"mongodb\+srv://[^/]+/([^?]+)", uris[0]) if uris else None
        resolved_db_name = match.group(1) if match else db_name
        
        for uri in uris:
            try:
                client = AsyncIOMotorClient(uri)
                client.get_io_loop = asyncio.get_running_loop
                self.clients.append(client)
                self.collections.append(client[resolved_db_name]["files"])
            except Exception as e:
                logger.error(f"Failed to connect to Mongo Shard URI: {e}")

        if not self.collections:
            logger.warning("No database collections active. Bot features will fail.")
            
        if self.clients:
            self.settings = self.clients[0][resolved_db_name]["settings"]
            self.users = self.clients[0][resolved_db_name]["users"]
            self.groups = self.clients[0][resolved_db_name]["groups"]
            self.jobs = self.clients[0][resolved_db_name]["indexing_jobs"]
            self.broadcast_logs = self.clients[0][resolved_db_name]["broadcast_logs"]
            self.scheduled_broadcasts = self.clients[0][resolved_db_name]["scheduled_broadcasts"]
            self.batch_stats = self.clients[0][resolved_db_name]["batch_stats"]  
            
            # 🛡️ Centralized Moderation Database
            self.punishments = self.clients[0][resolved_db_name]["punishments"]
            
            # 💎 VIP System Collections
            self.vip_users = self.clients[0][resolved_db_name]["vip_users"]
            self.vip_orders = self.clients[0][resolved_db_name]["vip_orders"]
            self.vip_coupons = self.clients[0][resolved_db_name]["vip_coupons"]
            self.vip_settings = self.clients[0][resolved_db_name]["vip_settings"]
            self.vip_history = self.clients[0][resolved_db_name]["vip_history"]
            self.vip_recovery = self.clients[0][resolved_db_name]["vip_recovery"]
            self.vip_plans = self.clients[0][resolved_db_name]["vip_plans"]
            self.vip_subscriptions = self.clients[0][resolved_db_name]["vip_subscriptions"]
            self.vip_features = self.clients[0][resolved_db_name]["vip_features"]
        # ==========================================
        # ⚙️ MULTI-SHARD CAPACITY CONSTANTS
        # ==========================================
        self.MAX_FILES_PER_SHARD = 800000 
        self.MAX_SHARD_CAPACITY_BYTES = 512 * 1024 * 1024
        # 160MB Constant for Atlas Free Tier system metrics (admin/local DB overhead)
        self.SYSTEM_OVERHEAD = 160 * 1024 * 1024 

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

# ==========================================
# 💎 DYNAMIC VIP & VERIFICATION ENGINE
# ==========================================
    async def apply_new_user_trial(self, user_id: int):
        """Grants a new user a free VIP trial if enabled."""
        if not self.clients: return
        settings = await self.get_settings()
        trial_days = settings.get("free_trial_days", 7)
        if trial_days > 0:
            expiry_ts = time.time() + (trial_days * 86400)
            await self.vip_users.update_one(
                {"user_id": user_id},
                {"$set": {"user_id": user_id, "plan_id": "gold", "expires_at": expiry_ts, "started_at": time.time()}},
                upsert=True
            )

    async def get_active_vip_plan(self, user_id: int) -> Optional[str]:
        """Checks if a user is an active VIP and returns their plan_id."""
        if not self.clients: return None
        vip_doc = await self.vip_users.find_one({"user_id": user_id})
        if vip_doc and vip_doc.get("expires_at", 0) > time.time():
            return vip_doc.get("plan_id")
        return None

    async def grant_verification_pass(self, user_id: int):
        """Grants a temporary bypass pass to a free user who completed verification."""
        if not self.clients: return
        settings = await self.get_settings()
        reward_hours = settings.get("verification_reward_hours", 12)
        expiry_ts = time.time() + (reward_hours * 3600)
        await self.users.update_one({"user_id": user_id}, {"$set": {"verification_pass_expires": expiry_ts}}, upsert=True)

    async def has_active_verification_pass(self, user_id: int) -> bool:
        """Checks if a free user's temporary verification pass is still active."""
        if not self.clients: return False
        user = await self.users.find_one({"user_id": user_id})
        if user and user.get("verification_pass_expires", 0) > time.time():
            return True
        return False

    async def get_group_settings(self, chat_id: int):
        if not self.clients: return {}
        group = await self.groups.find_one({"chat_id": chat_id})
        if not group:
            default = {
                "chat_id": chat_id, "search_mode": "let_members_choose",
                "quality_lock": "none", "language_lock": "none", "size_lock": "none", 
                "admins": [],
                "connected_by": None,
                "custom_caption": None # 📝 NEW: Placeholder for group custom caption
            }
            await self.groups.insert_one(default)
            return default
        return group

    async def update_group_setting(self, chat_id: int, key: str, value: Any):
        if not self.clients: return
        await self.groups.update_one({"chat_id": chat_id}, {"$set": {key: value}}, upsert=True)

    # 🚀 NEW: Helper to quickly check if a group is connected to the bot
    async def is_group_connected(self, chat_id: int) -> bool:
        if not self.clients: return False
        group = await self.groups.find_one({"chat_id": chat_id})
        if group and group.get("connected_by") is not None:
            return True
        return False

    # 🚀 NEW: Helper to quickly fetch all admins of a group for the @admin report feature
    async def get_group_admins(self, chat_id: int) -> list:
        if not self.clients: return []
        group = await self.groups.find_one({"chat_id": chat_id})
        if group:
            return group.get("admins", [])
        return []

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
                "bulk_enabled": True,
                "multi_search_limit": 5,
                "custom_caption": None # 📝 NEW: Placeholder for global bot custom caption
            }
            await self.settings.insert_one(default)
            return default
        return settings

    async def update_settings(self, updates: Dict[str, Any]) -> bool:
        if not self.clients: return False
        await self.settings.update_one({"_id": "bot_settings"}, {"$set": updates}, upsert=True)
        return True

    # ==========================================
    # 📝 DYNAMIC FILE CAPTION ENGINE
    # ==========================================
    async def get_custom_caption(self, chat_id: Optional[int] = None) -> str:
        """Fetches the caption respecting the hierarchy: Group -> Global -> Default Config"""
        if not self.clients: return Config.DEFAULT_CAPTION
        
        # 1. Check Group Specific Caption
        if chat_id:
            group = await self.groups.find_one({"chat_id": chat_id})
            if group and group.get("custom_caption"):
                return group["custom_caption"]
                
        # 2. Check Global Bot Caption
        bot_settings = await self.settings.find_one({"_id": "bot_settings"})
        if bot_settings and bot_settings.get("custom_caption"):
            return bot_settings["custom_caption"]
            
        # 3. Fallback to Config
        return Config.DEFAULT_CAPTION
        
    async def set_custom_caption(self, chat_id: Optional[int], text: str, is_global: bool = False):
        """Saves a custom caption to either the specific group or globally."""
        if not self.clients: return
        if is_global:
            await self.settings.update_one({"_id": "bot_settings"}, {"$set": {"custom_caption": text}}, upsert=True)
        elif chat_id:
            await self.groups.update_one({"chat_id": chat_id}, {"$set": {"custom_caption": text}}, upsert=True)
            
    async def delete_custom_caption(self, chat_id: Optional[int], is_global: bool = False):
        """Wipes the custom caption, reverting it to the next level down in the hierarchy."""
        if not self.clients: return
        if is_global:
            await self.settings.update_one({"_id": "bot_settings"}, {"$set": {"custom_caption": None}}, upsert=True)
        elif chat_id:
            await self.groups.update_one({"chat_id": chat_id}, {"$set": {"custom_caption": None}}, upsert=True)

    # ==========================================
    # ⚙️ WORKER 1: AUTO-ROUTING LOAD BALANCER
    # ==========================================
    async def insert_file(self, file_data: Dict[str, Any], shard_index: Optional[int] = None) -> bool:
        if not self.collections: return False
        
        # Smart load balancer routing to stay under 800,000 files per shard
        counts = [await coll.estimated_document_count() for coll in self.collections]
        available_shards = [(idx, count) for idx, count in enumerate(counts) if count < self.MAX_FILES_PER_SHARD]
        
        if not available_shards:
            logger.warning("🚨 All MongoDB Shards have hit 800k limit! Defaulting to emptiest shard.")
            target_shard = counts.index(min(counts))
        else:
            target_shard = min(available_shards, key=lambda x: x[1])[0]
            
        try:
            await self.collections[target_shard].insert_one(file_data)
            return True
        except Exception as e: 
            logger.error(f"❌ Failed writing file: {e}")
            return False

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

    # ==========================================
    # 💾 THE PERFECT ANALYTICS SYSTEM
    # ==========================================
    async def global_stats(self) -> Dict[str, Any]:
        """Calculates precise cluster metrics including Atlas system overhead."""
        stats = {
            "shards_active": len(self.collections), 
            "total_files": 0, 
            "total_size_bytes": self.SYSTEM_OVERHEAD,  # Added 160MB Atlas Overhead natively
            "indexed_metadata": 0,
            "corrupted_files": 0,
            "shard_distribution": []
        }
        
        for coll in self.collections:
            try:
                # Accurately measure physical bytes used by data and text indexes
                db_stats = await coll.database.command("dbStats")
                stats["total_size_bytes"] += db_stats.get("storageSize", 0) + db_stats.get("indexSize", 0)
                
                count = await coll.estimated_document_count()
                stats["shard_distribution"].append(count)
                stats["total_files"] += count
                
                processed = await coll.count_documents({"language": {"$exists": True, "$ne": "pending"}})
                stats["indexed_metadata"] += processed

                corrupted = await coll.count_documents({"language": "corrupted"})
                stats["corrupted_files"] += corrupted
            except Exception as e:
                logger.error(f"Stats Error: {e}")
                
        total_capacity_bytes = len(self.collections) * self.MAX_SHARD_CAPACITY_BYTES
        stats["space_left_bytes"] = max(0, total_capacity_bytes - stats["total_size_bytes"])
        
        true_data_size = stats["total_size_bytes"] - self.SYSTEM_OVERHEAD
        if stats["total_files"] > 0 and true_data_size > 0:
            avg_obj_size = true_data_size / stats["total_files"]
            stats["estimated_files_left"] = int(stats["space_left_bytes"] / avg_obj_size)
        else:
            stats["estimated_files_left"] = 0
            
        return stats

    # ==========================================
    # 📢 BROADCAST & SCHEDULER ENGINE LOGIC
    # ==========================================
    
    async def get_all_users(self):
        """Yields all users for the broadcast loop."""
        if not self.clients: return
        users = self.users.find({})
        async for user in users: yield user

    async def log_broadcast(self, batch_id: str, user_id: int, message_id: int):
        """Saves a message to the 48-Hour Recall Vault."""
        if not self.clients: return
        await self.broadcast_logs.insert_one({
            "batch_id": batch_id, 
            "user_id": user_id, 
            "message_id": message_id, 
            "timestamp": time.time()
        })

    async def get_broadcast_logs(self, batch_id: str):
        """Fetches all sent messages for a specific batch."""
        if not self.clients: return []
        return self.broadcast_logs.find({"batch_id": batch_id})

    async def delete_broadcast_batch(self, batch_id: str):
        """Wipes an entire batch from the database vault."""
        if not self.clients: return
        await self.broadcast_logs.delete_many({"batch_id": batch_id})

    async def get_user_latest_broadcast(self, user_id: int):
        """Finds the most recent broadcast sent to a specific user."""
        if not self.clients: return None
        return await self.broadcast_logs.find_one(
            {"user_id": user_id}, 
            sort=[("timestamp", -1)]
        )

    async def delete_single_broadcast_log(self, user_id: int, message_id: int):
        """Removes a single user's message from the vault."""
        if not self.clients: return
        await self.broadcast_logs.delete_one({"user_id": user_id, "message_id": message_id})
        
    async def get_recent_batches(self):
        """Gets unique batches from the last 48 hours for the Admin Menu."""
        if not self.clients: return []
        forty_eight_hours_ago = time.time() - (48 * 3600)
        pipeline = [
            {"$match": {"timestamp": {"$gte": forty_eight_hours_ago}}}, 
            {"$group": {"_id": "$batch_id", "count": {"$sum": 1}}}, 
            {"$sort": {"_id": -1}}
        ]
        return self.broadcast_logs.aggregate(pipeline)

    async def add_scheduled_broadcast(self, batch_id: str, admin_id: int, message_id: int, run_at: float, command_text: str):
        """Schedules a broadcast for the future."""
        if not self.clients: return
        await self.scheduled_broadcasts.insert_one({
            "batch_id": batch_id, 
            "admin_id": admin_id, 
            "message_id": message_id, 
            "run_at": run_at, 
            "command_text": command_text, 
            "status": "pending"
        })

    async def get_due_broadcasts(self):
        """Fetches broadcasts that are ready to run."""
        if not self.clients: return []
        cursor = self.scheduled_broadcasts.find({"status": "pending", "run_at": {"$lte": time.time()}})
        return await cursor.to_list(length=100)

    async def mark_broadcast_complete(self, schedule_id):
        """Marks a scheduled broadcast as done."""
        if not self.clients: return
        await self.scheduled_broadcasts.update_one({"_id": schedule_id}, {"$set": {"status": "completed"}})
        
    async def cancel_scheduled_broadcast(self, batch_id: str) -> bool:
        """Deletes a scheduled broadcast from the queue before it runs."""
        if not self.clients: return False
        res = await self.scheduled_broadcasts.delete_one({"batch_id": batch_id, "status": "pending"})
        return res.deleted_count > 0

    # ==========================================
    # 📊 BATCH ENGAGEMENT TRACKING
    # ==========================================
    
    async def add_batch_reaction(self, batch_id: str, emoji: str, user_id: int):
        """Records a user reaction and prevents duplicate votes."""
        if not self.clients: return False
        res = await self.batch_stats.update_one(
            {"batch_id": batch_id}, 
            {"$addToSet": {f"reactions.{emoji}": user_id}}, 
            upsert=True
        )
        return res.modified_count > 0

    async def add_batch_reply(self, batch_id: str, user_id: int):
        """Records that a specific user replied to this broadcast batch."""
        if not self.clients: return False
        res = await self.batch_stats.update_one(
            {"batch_id": batch_id}, 
            {"$addToSet": {"replies": user_id}}, 
            upsert=True
        )
        return res.modified_count > 0

    async def increment_batch_followup(self, batch_id: str):
        """Increments the counter showing how many times an admin sent a followup to this batch."""
        if not self.clients: return
        await self.batch_stats.update_one(
            {"batch_id": batch_id}, 
            {"$inc": {"followup_count": 1}}, 
            upsert=True
        )

    async def get_batch_engagement(self, batch_id: str):
        """Fetches all engagement metrics (reactions, replies, followups) for the admin dashboard."""
        if not self.clients: return {"reactions": {}, "replies": 0, "followups": 0}
        doc = await self.batch_stats.find_one({"batch_id": batch_id})
        if not doc: return {"reactions": {}, "replies": 0, "followups": 0}
        
        return {
            "reactions": {k: len(v) for k, v in doc.get("reactions", {}).items()},
            "replies": len(doc.get("replies", [])),
            "followups": doc.get("followup_count", 0)
        }

    # ==========================================
    # ⚖️ DUAL-LAYER MODERATION ENGINE
    # ==========================================
    
    async def add_punishment(self, user_id: int, chat_id: str, p_type: str, duration_secs: int=0, expiry_ts: float=0, reason: str=""):
        """Adds or updates a global/local punishment block."""
        if not self.clients: return 1
        doc_id = f"{user_id}_{chat_id}"
        
        if p_type == "warn":
            await self.punishments.update_one({"_id": doc_id}, {"$inc": {"warns": 1}, "$set": {"type": "warn"}}, upsert=True)
            doc = await self.punishments.find_one({"_id": doc_id})
            return doc.get("warns", 1)
            
        else: # Mute or Ban
            payload = {"type": p_type, "reason": reason}
            if expiry_ts > 0: payload["expires_at"] = expiry_ts
            await self.punishments.update_one({"_id": doc_id}, {"$set": payload}, upsert=True)
            return 1

    async def remove_punishment(self, user_id: int, chat_id: str, p_type: str):
        """Removes a specific punishment based on the user and scope."""
        if not self.clients: return
        doc_id = f"{user_id}_{chat_id}"
        await self.punishments.delete_one({"_id": doc_id})

    async def check_punishment(self, user_id: int, chat_id: str):
        """Lazy Evaluation Engine: Returns (type, reason, expiry, scope) or None"""
        if not self.clients: return None, None, 0, None
        
        # 1. Check Global Punishments First
        global_doc = await self.punishments.find_one({"_id": f"{user_id}_global"})
        if global_doc and global_doc.get("type") in ["mute", "ban"]:
            if global_doc.get("expires_at", 0) > 0 and time.time() > global_doc["expires_at"]:
                await self.remove_punishment(user_id, "global", global_doc["type"]) # Auto-Unmute Lazy Eval
            else:
                return global_doc["type"], global_doc.get("reason", ""), global_doc.get("expires_at", 0), "global"

        # 2. Check Local Group Punishments
        local_doc = await self.punishments.find_one({"_id": f"{user_id}_{chat_id}"})
        if local_doc and local_doc.get("type") in ["mute", "ban"]:
            if local_doc.get("expires_at", 0) > 0 and time.time() > local_doc["expires_at"]:
                await self.remove_punishment(user_id, chat_id, local_doc["type"]) # Auto-Unmute Lazy Eval
            else:
                return local_doc["type"], local_doc.get("reason", ""), local_doc.get("expires_at", 0), "local"
                
        return None, None, 0, None

    async def add_search_count(self, user_id: int):
        """Tracks the overall usage history of the bot per user."""
        if not self.clients: return
        await self.users.update_one({"user_id": user_id}, {"$inc": {"total_searches": 1}}, upsert=True)

db = MultiDB(Config.DB_URIS, Config.DB_NAME)
