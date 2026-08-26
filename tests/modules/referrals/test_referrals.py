"""
Phase 8 referral coverage.
"""
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.modules.config_engine.service import ConfigEngineService
from app.modules.events.service import EventService
from app.modules.identity.models import User
from app.modules.payments.models import Payment, PaymentStatus
from app.modules.referrals.models import ReferralRewardStatus
from app.modules.referrals.service import ReferralService
from app.modules.registrations.models import RegistrationStatus
from app.modules.registrations.service import RegistrationService


async def _make_event(db_session):
    creator = User(mobile_number="+919500000001")
    referrer = User(mobile_number="+919500000002")
    referred = User(mobile_number="+919500000003")
    db_session.add_all([creator, referrer, referred])
    await db_session.flush()

    start = datetime.now(timezone.utc) + timedelta(days=20)
    event = await EventService(db_session).create_event(
        created_by=creator.id,
        name="Phase 8 Referrals Event",
        description="fixture",
        category="sample",
        start_date=start,
        end_date=start + timedelta(days=1),
        organization_id=None,
    )
    await ConfigEngineService(db_session).upsert_configuration(
        event.id,
        participation_types=["individual"],
        fee_amount=Decimal("1000.00"),
        currency="INR",
        capacity=25,
        approval_required=False,
        rules={},
        discount_rules=None,
    )
    return event, referrer, referred


@pytest.mark.asyncio
async def test_referral_qualifies_when_paid_registration_completes(db_session):
    event, referrer, referred = await _make_event(db_session)
    service = ReferralService(db_session)
    registration_service = RegistrationService(db_session)

    profile = await service.get_or_create_profile(event.id, referrer)
    registration = await registration_service.create_registration(
        event_id=event.id,
        actor=referred,
        participation_type="individual",
        date_of_birth=None,
        child_id=None,
        team_id=None,
        documents_provided=[],
        answers={},
        participants=[],
    )
    reward = await service.track_referral(
        event_id=event.id,
        actor=referred,
        referral_code=profile.referral_code,
        registration_id=registration.id,
        device_fingerprint="device-abc",
        ip_address="127.0.0.1",
    )
    assert reward.status == ReferralRewardStatus.TRACKED
    assert reward.is_flagged is True

    registration.status = RegistrationStatus.COMPLETED

    payment = Payment(
        event_id=event.id,
        registration_id=registration.id,
        user_id=referred.id,
        amount=Decimal("1000.00"),
        currency="INR",
        status=PaymentStatus.VERIFIED,
        gateway_provider="razorpay",
        gateway_order_id="order_test_referrals",
        gateway_payment_id="pay_test_referrals",
        gateway_signature="sig",
    )
    db_session.add(payment)
    await db_session.commit()

    issued = await service.evaluate_referral_qualification(registration.id)
    assert issued is not None
    assert issued.status == ReferralRewardStatus.ISSUED
    assert issued.qualified_at is not None
    assert issued.issued_at is not None

    refreshed_reward = await service.rewards.get_by_registration_id(registration.id)
    assert refreshed_reward is not None
    assert refreshed_reward.status == ReferralRewardStatus.ISSUED

    refreshed_profile = await service.referrals.get_by_id(profile.id)
    assert refreshed_profile is not None
    assert refreshed_profile.total_rewards_issued == 1
