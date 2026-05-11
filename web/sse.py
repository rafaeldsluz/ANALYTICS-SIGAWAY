"""
Server-Sent Events — canal de comunicação em tempo real do servidor para o browser.
Suporta reconexão: a fila é mantida enquanto a campanha estiver ativa.
"""
import json
import queue
import threading
from typing import Generator


class SSEManager:

    def __init__(self):
        self._streams: dict[str, queue.Queue] = {}
        self._lock = threading.Lock()

    def create(self, stream_id: str) -> queue.Queue:
        with self._lock:
            if stream_id not in self._streams:
                self._streams[stream_id] = queue.Queue(maxsize=2000)
            return self._streams[stream_id]

    def push(self, stream_id: str, event_type: str, data: dict):
        with self._lock:
            q = self._streams.get(stream_id)
        if q:
            try:
                q.put_nowait({"type": event_type, **data})
            except queue.Full:
                pass

    def listen(self, stream_id: str) -> Generator[str, None, None]:
        q = self.create(stream_id)
        try:
            while True:
                try:
                    payload = q.get(timeout=25)
                    event_type = payload.get("type", "message")
                    data = {k: v for k, v in payload.items() if k != "type"}
                    yield f"event: {event_type}\ndata: {json.dumps(data)}\n\n"
                    if event_type == "done":
                        self._remove(stream_id)
                        break
                except queue.Empty:
                    yield ": keepalive\n\n"
        except GeneratorExit:
            pass  # browser desconectou — mantém a fila para reconexão

    def _remove(self, stream_id: str):
        with self._lock:
            self._streams.pop(stream_id, None)

    def close(self, stream_id: str):
        self.push(stream_id, "done", {})


sse = SSEManager()
