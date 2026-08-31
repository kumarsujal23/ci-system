"""
WebSocket endpoints for the dashboard's live views.

Both endpoints subscribe to a Redis Pub/Sub channel and forward messages to
the browser. Redis is used here purely as a fan-out mechanism between
whichever backend process/worker produced the event and however many
dashboard tabs are watching - Postgres remains the durable record (a client
that connects mid-job gets an initial snapshot fetched from the DB, then
live deltas from here on).
"""
import asyncio
import json

from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Depends
from sqlalchemy.orm import Session

from app import models, redis_client
from app.database import get_db, SessionLocal
from app.config import get_settings

router = APIRouter()
settings = get_settings()


@router.websocket("/ws/attempts/{attempt_id}/logs")
async def stream_logs(websocket: WebSocket, attempt_id: str):
    await websocket.accept()

    db = SessionLocal()
    try:
        attempt = db.get(models.JobAttempt, attempt_id)
        if attempt and attempt.logs:
            await websocket.send_text(attempt.logs)
    finally:
        db.close()

    r = redis_client.get_redis()
    pubsub = r.pubsub()
    channel = f"{settings.log_channel_prefix}{attempt_id}"
    pubsub.subscribe(channel)

    try:
        while True:
            message = await asyncio.get_running_loop().run_in_executor(
                None, pubsub.get_message, True, 1.0
            )
            if message and message["type"] == "message":
                await websocket.send_text(message["data"])
            # Yield control so we notice client disconnects promptly.
            await asyncio.sleep(0.05)
    except WebSocketDisconnect:
        pass
    finally:
        pubsub.close()


@router.websocket("/ws/jobs/{job_id}/status")
async def stream_status(websocket: WebSocket, job_id: str):
    await websocket.accept()
    r = redis_client.get_redis()
    pubsub = r.pubsub()
    channel = f"{settings.status_channel_prefix}{job_id}"
    pubsub.subscribe(channel)

    try:
        while True:
            message = await asyncio.get_running_loop().run_in_executor(
                None, pubsub.get_message, True, 1.0
            )
            if message and message["type"] == "message":
                await websocket.send_text(message["data"])
            await asyncio.sleep(0.05)
    except WebSocketDisconnect:
        pass
    finally:
        pubsub.close()
