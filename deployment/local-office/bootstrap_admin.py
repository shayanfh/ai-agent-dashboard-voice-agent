"""Create the idempotent local-office company administrator account."""

import asyncio
import os
from datetime import datetime, timedelta, timezone

from sqlalchemy import select

import app.core.model_registry  # noqa: F401  # Load all relationship targets.
from app.core.database import AsyncSessionLocal
from app.core.permissions import UserRole
from app.core.security import hash_password, normalize_email
from app.modules.billing.models import Plan, Subscription, SubscriptionStatus
from app.modules.companies.models import Company, CompanyStatus
from app.modules.users.models import User


def required_setting(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise RuntimeError(f"Missing required environment variable: {name}")
    return value


async def bootstrap() -> None:
    email = normalize_email(required_setting("BOOTSTRAP_ADMIN_EMAIL"))
    password = required_setting("BOOTSTRAP_ADMIN_PASSWORD")
    company_name = os.environ.get("BOOTSTRAP_COMPANY_NAME", "Starvox Office").strip()
    timezone_name = os.environ.get("BOOTSTRAP_TIMEZONE", "Asia/Tehran").strip()

    async with AsyncSessionLocal() as db:
        existing_user = await db.scalar(select(User).where(User.email == email))
        if existing_user:
            if not existing_user.company_id:
                raise RuntimeError(
                    f"User {email} already exists without a company; refusing to modify it"
                )
            print(f"Bootstrap administrator already exists: {email}")
            return

        legacy_plan = await db.scalar(select(Plan).where(Plan.slug == "legacy"))
        if not legacy_plan:
            raise RuntimeError("The legacy plan is missing; run Alembic migrations first")

        now = datetime.now(timezone.utc)
        company = Company(
            name=company_name,
            business_type="office",
            default_language="fa",
            timezone=timezone_name,
            email=email,
            country="IR",
            status=CompanyStatus.ACTIVE,
            onboarding_completed_at=now,
            signup_source="local-office-installer",
        )
        db.add(company)
        await db.flush()

        db.add(
            Subscription(
                company_id=company.id,
                plan_id=legacy_plan.id,
                status=SubscriptionStatus.ACTIVE,
                current_period_start=now,
                current_period_end=now + timedelta(days=3650),
            )
        )
        db.add(
            User(
                company_id=company.id,
                full_name="Starvox Admin",
                email=email,
                hashed_password=hash_password(password),
                role=UserRole.COMPANY_ADMIN,
                is_active=True,
                email_verified=True,
                email_verified_at=now,
                failed_login_attempts=0,
            )
        )
        await db.commit()
        print(f"Created local-office company administrator: {email}")


if __name__ == "__main__":
    asyncio.run(bootstrap())
