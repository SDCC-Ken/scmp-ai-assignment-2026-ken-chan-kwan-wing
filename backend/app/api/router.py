from fastapi import APIRouter

from app.api.routes import attachments, auth, chat, me

api_router = APIRouter(prefix="/api")
api_router.include_router(auth.router)
api_router.include_router(chat.router)
api_router.include_router(me.router)
api_router.include_router(attachments.upload_router)
api_router.include_router(attachments.download_router)
