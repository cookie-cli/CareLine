from __future__ import annotations

from collections import defaultdict
from typing import Any, Dict, Set

from fastapi import WebSocket


class RealtimeHub:
    def __init__(self) -> None:
        self._rooms: Dict[str, Set[WebSocket]] = defaultdict(set)

    def connect(self, room: str, websocket: WebSocket) -> None:
        self._rooms[room].add(websocket)

    def disconnect(self, room: str, websocket: WebSocket) -> None:
        sockets = self._rooms.get(room)
        if not sockets:
            return
        sockets.discard(websocket)
        if not sockets:
            self._rooms.pop(room, None)

    async def broadcast(self, room: str, payload: Dict[str, Any]) -> None:
        sockets = list(self._rooms.get(room, set()))
        stale: list[WebSocket] = []
        for socket in sockets:
            try:
                await socket.send_json(payload)
            except Exception:
                stale.append(socket)
        for socket in stale:
            self.disconnect(room, socket)

    async def emit_nudge_event(self, event: str, nudge: Dict[str, Any]) -> None:
        payload = {
            "type": "nudge_event",
            "event": event,
            "nudge": nudge,
        }
        user_id = str(nudge.get("user_id") or "").strip()
        caretaker_id = str(nudge.get("caretaker_id") or "").strip()

        if user_id:
            await self.broadcast(f"user:{user_id}", payload)
        if caretaker_id:
            await self.broadcast(f"caretaker:{caretaker_id}", payload)


realtime_hub = RealtimeHub()
