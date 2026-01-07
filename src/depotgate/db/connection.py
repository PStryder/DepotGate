"""Database connection management for DepotGate."""

from contextlib import asynccontextmanager
from typing import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from depotgate.config import settings
from depotgate.db.models import MetadataBase, ReceiptsBase

# Metadata database engine and session
metadata_engine = create_async_engine(
    settings.metadata_database_url,
    echo=settings.debug,
    pool_pre_ping=True,
)
MetadataSessionLocal = async_sessionmaker(
    metadata_engine,
    class_=AsyncSession,
    expire_on_commit=False,
)

# Receipts database engine and session
receipts_engine = create_async_engine(
    settings.receipts_database_url,
    echo=settings.debug,
    pool_pre_ping=True,
)
ReceiptsSessionLocal = async_sessionmaker(
    receipts_engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


async def init_databases() -> None:
    """Initialize database schemas."""
    async with metadata_engine.begin() as conn:
        await conn.run_sync(MetadataBase.metadata.create_all)

    async with receipts_engine.begin() as conn:
        await conn.run_sync(ReceiptsBase.metadata.create_all)


async def close_databases() -> None:
    """Close database connections."""
    await metadata_engine.dispose()
    await receipts_engine.dispose()


@asynccontextmanager
async def get_metadata_session() -> AsyncGenerator[AsyncSession, None]:
    """Get a metadata database session."""
    async with MetadataSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


@asynccontextmanager
async def get_receipts_session() -> AsyncGenerator[AsyncSession, None]:
    """Get a receipts database session."""
    async with ReceiptsSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


# FastAPI dependency functions
async def metadata_session_dependency() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI dependency for metadata session."""
    async with get_metadata_session() as session:
        yield session


async def receipts_session_dependency() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI dependency for receipts session."""
    async with get_receipts_session() as session:
        yield session
