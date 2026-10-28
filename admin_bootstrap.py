"""Safely provision the first administrator from private environment settings."""

from __future__ import annotations

import logging
import os

from sqlalchemy import func
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

import auth
import database
import models

logger = logging.getLogger("lawnexa.admin_bootstrap")


def provision_admin_from_environment() -> bool:
    """Create the initial admin only when explicit credentials are configured.

    Existing accounts are never silently promoted, reactivated, or have their
    passwords replaced. No default admin credentials are supplied.
    """
    email = os.getenv("ADMIN_EMAIL", "").strip().lower()
    password = os.getenv("ADMIN_PASSWORD", "")
    full_name = os.getenv("ADMIN_NAME", "LawNexa Administrator").strip()
    phone = os.getenv("ADMIN_PHONE", "").strip() or None

    if not email and not password:
        return False
    if not email or not password:
        raise RuntimeError(
            "Set both ADMIN_EMAIL and ADMIN_PASSWORD to provision an administrator."
        )
    if email.startswith("<") or email.endswith(">") or (password.startswith("<") and password.endswith(">")):
        raise RuntimeError("Replace placeholder admin credentials before startup.")
    if len(password) < 16:
        raise RuntimeError("ADMIN_PASSWORD must contain at least 16 characters.")
    if len(password.encode("utf-8")) > 72:
        raise RuntimeError(
            "ADMIN_PASSWORD exceeds bcrypt's 72-byte limit; use a shorter password."
        )
    if not full_name:
        raise RuntimeError("ADMIN_NAME cannot be blank when provisioning the admin.")

    db = database.SessionLocal()
    try:
        existing = (
            db.query(models.User)
            .filter(func.lower(models.User.email) == email)
            .first()
        )
        if existing:
            if (existing.role or "").lower() != "admin":
                raise RuntimeError(
                    "ADMIN_EMAIL already belongs to a non-admin account. "
                    "Use a separate dedicated administrator email; no role was changed."
                )
            return False

        admin = models.User(
            full_name=full_name,
            email=email,
            phone=phone,
            hashed_password=auth.get_password_hash(password),
            role="admin",
            is_active=True,
            is_approved=True,
        )
        db.add(admin)
        db.commit()
        logger.info("Provisioned initial LawNexa admin account from environment configuration.")
        return True

    except IntegrityError:
        db.rollback()
        # Another app worker may have created the same admin concurrently.
        existing = (
            db.query(models.User)
            .filter(func.lower(models.User.email) == email)
            .first()
        )
        if existing and (existing.role or "").lower() == "admin":
            return False
        raise RuntimeError("Administrator account could not be provisioned safely.")
    except SQLAlchemyError as exc:
        db.rollback()
        logger.exception("Administrator provisioning failed.")
        raise RuntimeError("Administrator account could not be provisioned.") from exc
    finally:
        db.close()
