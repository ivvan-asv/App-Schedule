import asyncio

from app.core.database import engine
from app.models.user import User


async def main() -> None:
    try:
        async with engine.begin() as connection:
            await connection.run_sync(User.metadata.create_all)
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
