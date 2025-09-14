# connection.py
from datetime import datetime
from typing import Dict, List, Optional

class DatabaseManager:
    def __init__(self):
        self._subs: List[Dict] = []

    async def add_subscription(self, sub: Dict) -> None:
        if 'id' not in sub:
            sub['id'] = f"sub_{len(self._subs)+1}"
        self._subs.append(sub)

    async def get_all_subscriptions(self) -> List[Dict]:
        return list(self._subs)

    async def get_subscription(self, subscription_id: str) -> Optional[Dict]:
        for s in self._subs:
            if s.get('id') == subscription_id or s.get('name','').lower() == subscription_id.lower():
                return s
        return None

    async def update_subscription(self, subscription_id: str, patch: Dict) -> None:
        for s in self._subs:
            if s.get('id') == subscription_id or s.get('name','').lower() == subscription_id.lower():
                s.update(patch)
                s.setdefault('updated_at', datetime.now().isoformat())
                return
