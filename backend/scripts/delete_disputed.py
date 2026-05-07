"""Delete only DISPUTED labels from database."""
import asyncio
from sqlalchemy import delete, select
from app.db.postgres import session_scope
from app.models.sql import AddressLabel

async def main():
    async with session_scope() as db:
        # Show what will be deleted
        q = select(AddressLabel).where(AddressLabel.audit_verdict == "DISPUTED")
        rows = (await db.scalars(q)).all()
        for r in rows:
            print(f"  DISPUTED: {r.address} ({r.chain}) tags={r.tags} verdict={r.audit_verdict} conf={r.audit_confidence}")
        print(f"Found {len(rows)} DISPUTED labels to delete")

        stmt = delete(AddressLabel).where(AddressLabel.audit_verdict == "DISPUTED")
        result = await db.execute(stmt)
        await db.commit()
        print(f"Deleted {result.rowcount} DISPUTED labels")

asyncio.run(main())
