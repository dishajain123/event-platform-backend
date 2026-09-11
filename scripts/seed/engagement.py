"""Per-event engagement / operations seed data.

Extends the GO-360° dataset so every Console and Mobile App screen has
realistic, varied content: live interactions (polls + Q&A), attendee
feedback, waitlists, certificates & badges, networking, referrals,
incidents, assistance requests, a light competition bracket, and the
sponsorship marketplace. Every row is created through [SeedWriter.add]
so it is deterministically keyed and cleaned up by `reset`/`refresh`
exactly like the rest of the fixture.
"""
from __future__ import annotations

from datetime import timedelta

from app.modules.assistance.models import AssistanceRequest, AssistanceRequestStatus
from app.modules.certificates.models import (
    BadgeAward,
    BadgeDefinition,
    Certificate,
    CertificateStatus,
    CertificateTemplate,
)
from app.modules.feedback.models import EventFeedback, FeedbackCategory
from app.modules.funnels.models import (
    Competition,
    CompetitionStage,
    CompetitionStatus,
    Entry,
    EntryStatus,
    StageDecision,
    StageStatus,
    StageType,
)
from app.modules.guardians.models import ChildProfile, GuardianChildRelationship
from app.modules.incidents.models import Incident, IncidentSeverity, IncidentStatus
from app.modules.interactions.models import (
    EventPoll,
    EventQuestion,
    PollChoiceMode,
    PollOption,
    PollResponse,
    PollResultVisibility,
    PollStatus,
    PollVote,
    QuestionStatus,
    QuestionUpvote,
)
from app.modules.networking.models import (
    ConnectionIntent,
    ConnectionStatus,
    EventNetworkingConfig,
    NetworkingConnection,
    NetworkingProfile,
    NetworkingReport,
    NetworkingReportStatus,
    NetworkingVisibility,
)
from app.modules.referrals.models import (
    Referral,
    ReferralReward,
    ReferralRewardStatus,
    ReferralRewardType,
)
from app.modules.registrations.models import RegistrationStatus
from app.modules.sponsorships.models import (
    SponsorshipCategory,
    SponsorshipInquiry,
    SponsorshipInquiryEvent,
    SponsorshipInquiryStatus,
    SponsorshipPackage,
)
from datetime import date


async def seed_engagement(w, *, event, key, index, regs, users, manager, staff,
                          volunteer, ops, finance, start, end):
    """`regs` is a list of (RegistrationStatus, reg, participant, user)."""
    participants = users[6:]
    reg_by_state = {state: (reg, part, user) for state, reg, part, user in regs}

    # ---- Live interactions: polls ----
    poll_specs = [
        ('live', PollStatus.LIVE, PollResultVisibility.ALWAYS,
         'Which session are you most excited about?',
         ['Keynote', 'Panel discussion', 'Workshops', 'Networking mixer']),
        ('closed', PollStatus.CLOSED, PollResultVisibility.AFTER_CLOSE,
         'How would you rate the opening ceremony?',
         ['Loved it', 'It was good', 'Neutral', 'Needs work']),
        ('draft', PollStatus.DRAFT, PollResultVisibility.HIDDEN,
         'Pick the closing act (coming soon)',
         ['DJ set', 'Live band', 'Acoustic', 'Surprise guest']),
    ]
    for suffix, status, visibility, title, labels in poll_specs:
        poll = await w.add(
            EventPoll, f'{key}/poll/{suffix}',
            event_id=event.id, created_by=manager.id, title=title,
            starts_at=start - timedelta(hours=2), ends_at=start + timedelta(hours=6),
            choice_mode=PollChoiceMode.SINGLE, result_visibility=visibility,
            anonymous=suffix == 'closed', allow_vote_change=suffix == 'live',
            status=status,
        )
        options = []
        for order, label in enumerate(labels):
            options.append(await w.add(
                PollOption, f'{key}/poll/{suffix}/{order}',
                poll_id=poll.id, label=label, sort_order=order,
            ))
        if status in {PollStatus.LIVE, PollStatus.CLOSED}:
            for voter_index in range(6):
                voter = participants[(index + voter_index) % len(participants)]
                response = await w.add(
                    PollResponse, f'{key}/poll/{suffix}/resp/{voter_index}',
                    poll_id=poll.id, user_id=voter.id,
                    submitted_at=start + timedelta(minutes=10 + voter_index),
                )
                await w.add(
                    PollVote, f'{key}/poll/{suffix}/vote/{voter_index}',
                    response_id=response.id,
                    option_id=options[voter_index % len(options)].id,
                )

    # ---- Live interactions: audience questions ----
    question_specs = [
        ('answered', QuestionStatus.ANSWERED, 'Will slides be shared afterwards?',
         'Yes, every deck goes out by email within 24 hours.'),
        ('approved', QuestionStatus.APPROVED, 'Is there a vegetarian food counter?', None),
        ('pending', QuestionStatus.PENDING, 'Can I bring a plus-one to the mixer?', None),
        ('rejected', QuestionStatus.REJECTED, 'Off-topic promotional question', None),
    ]
    for qi, (suffix, status, text, answer) in enumerate(question_specs):
        asker = participants[(index + qi) % len(participants)]
        question = await w.add(
            EventQuestion, f'{key}/q/{suffix}',
            event_id=event.id, user_id=asker.id, question=text,
            anonymous=suffix == 'rejected', status=status,
            answer_text=answer,
            answered_by=manager.id if answer else None,
            answered_at=start + timedelta(hours=1) if answer else None,
        )
        for ui in range((qi + 2) % 5):
            upvoter = participants[(index + qi + ui + 1) % len(participants)]
            await w.add(
                QuestionUpvote, f'{key}/q/{suffix}/up/{ui}',
                question_id=question.id, user_id=upvoter.id,
            )

    # ---- Attendee feedback ----
    feedback_categories = [
        FeedbackCategory.EVENT_EXPERIENCE,
        FeedbackCategory.VENUE_FACILITIES,
        FeedbackCategory.SCHEDULE_ACTIVITIES,
        FeedbackCategory.FOOD_HOSPITALITY,
        FeedbackCategory.ORGANIZATION_MANAGEMENT,
    ]
    comments = {
        5: 'Brilliantly run, would attend again.',
        4: 'Really enjoyed it, minor queue issues.',
        3: 'Decent, but the schedule slipped.',
        2: 'Venue was hard to navigate.',
    }
    for fi, category in enumerate(feedback_categories):
        rater = participants[(index * 2 + fi) % len(participants)]
        rating = 5 - (fi % 4)
        await w.add(
            EventFeedback, f'{key}/fb/{fi}',
            event_id=event.id, user_id=rater.id, category=category.value,
            rating=rating, comment=comments.get(rating),
        )

    # ---- Waitlist ----
    waitlist_specs = [
        ('waiting-1', 'waiting'), ('waiting-2', 'waiting'),
        ('promoted', 'promoted'), ('expired', 'expired'), ('left', 'left'),
    ]
    from app.modules.waitlists.models import WaitlistEntry, WaitlistStatus
    status_map = {
        'waiting': WaitlistStatus.WAITING, 'promoted': WaitlistStatus.PROMOTED,
        'expired': WaitlistStatus.EXPIRED, 'left': WaitlistStatus.LEFT,
    }
    for wi, (suffix, state) in enumerate(waitlist_specs):
        person = participants[(index + wi + 3) % len(participants)]
        joined = start - timedelta(days=10) + timedelta(hours=wi)
        await w.add(
            WaitlistEntry, f'{key}/wl/{suffix}',
            event_id=event.id, user_id=person.id, participation_type='individual',
            status=status_map[state], joined_at=joined,
            promoted_at=joined + timedelta(days=1) if state == 'promoted' else None,
            promotion_expires_at=joined + timedelta(days=3) if state == 'promoted' else None,
            expired_at=joined + timedelta(days=3) if state == 'expired' else None,
            left_at=joined + timedelta(days=2) if state == 'left' else None,
        )

    # ---- Certificates & badges (for attendees who checked in / confirmed) ----
    template = await w.add(
        CertificateTemplate, f'{key}/cert-template',
        event_id=event.id, certificate_type='participation',
        title='Certificate of Participation', issuer_name='GO-360° Goregaon',
        description='Awarded to every verified participant.',
        criteria={'requires_check_in': True}, is_active=True,
    )
    badge = await w.add(
        BadgeDefinition, f'{key}/badge',
        event_id=event.id, name='Early Bird',
        description='Registered in the first 48 hours.',
        criteria={'window_hours': 48}, is_active=True,
    )
    for ci, state in enumerate((RegistrationStatus.CHECKED_IN, RegistrationStatus.CONFIRMED)):
        row = reg_by_state.get(state)
        if row is None:
            continue
        reg, part, holder = row
        revoked = ci == 1  # the CONFIRMED one demonstrates a revoked certificate
        await w.add(
            Certificate, f'{key}/cert/{ci}',
            event_id=event.id, template_id=template.id, registration_id=reg.id,
            participant_id=part.id if part else None, user_id=holder.id,
            certificate_number=f'GO360-{key.upper()}-CERT-{ci}',
            verification_token=f'verify-{key}-{ci}-{event.id.hex[:8]}',
            status=CertificateStatus.REVOKED.value if revoked else CertificateStatus.ISSUED.value,
            issued_by=manager.id,
            revoked_at=start + timedelta(days=1) if revoked else None,
            revocation_reason='Issued to the wrong participant.' if revoked else None,
        )
        if not revoked:
            await w.add(
                BadgeAward, f'{key}/badge-award/{ci}',
                event_id=event.id, badge_id=badge.id, registration_id=reg.id,
                participant_id=part.id if part else None, user_id=holder.id,
                status='awarded',
            )

    # ---- Networking ----
    await w.add(
        EventNetworkingConfig, f'{key}/net-config',
        event_id=event.id, enabled=True, matchmaking_enabled=True,
        allowed_participant_types=['individual', 'team'],
    )
    net_people = [manager, staff, volunteer] + participants[:3]
    net_profiles = []
    orgs = ['Aarey Labs', 'Goregaon Sports Trust', 'BrightFuture NGO',
            'Westline Media', 'NESCO Ventures', 'CityCare Hospitals']
    roles_titles = ['Program Lead', 'Coach', 'Volunteer Coordinator',
                    'Producer', 'Analyst', 'Doctor']
    for pi, person in enumerate(net_people):
        net_profiles.append(await w.add(
            NetworkingProfile, f'{key}/net/{pi}',
            event_id=event.id, user_id=person.id,
            display_name=person.name, organization=orgs[pi % len(orgs)],
            designation=roles_titles[pi % len(roles_titles)],
            interests=['events', 'community', 'tech'][: (pi % 3) + 1],
            skills=['logistics', 'marketing', 'coaching'][: (pi % 3) + 1],
            bio='Open to collaborating on future GO-360° editions.',
            visibility=NetworkingVisibility.VISIBLE if pi % 4 else NetworkingVisibility.HIDDEN,
            share_contact=pi % 2 == 0,
        )
        )
    conn_specs = [
        (0, 1, ConnectionStatus.ACCEPTED, ConnectionIntent.COLLABORATE),
        (0, 2, ConnectionStatus.PENDING, ConnectionIntent.CONNECT),
        (1, 3, ConnectionStatus.REJECTED, ConnectionIntent.DISCUSS),
        (2, 4, ConnectionStatus.BLOCKED, ConnectionIntent.CONNECT),
    ]
    for si, (a, b, status, intent) in enumerate(conn_specs):
        ua, ub = net_people[a], net_people[b]
        low, high = sorted([ua.id, ub.id], key=str)
        await w.add(
            NetworkingConnection, f'{key}/conn/{si}',
            event_id=event.id, participant_low_id=low, participant_high_id=high,
            requested_by=ua.id, intent=intent, status=status,
            responded_at=start + timedelta(hours=si) if status != ConnectionStatus.PENDING else None,
        )
    await w.add(
        NetworkingReport, f'{key}/net-report',
        event_id=event.id, reporter_id=net_people[0].id,
        reported_user_id=net_people[4].id,
        reason='Sent repeated unsolicited promotional messages.',
        status=NetworkingReportStatus.OPEN if index % 2 else NetworkingReportStatus.RESOLVED,
        reviewed_by=None if index % 2 else ops.id,
        resolution_notes=None if index % 2 else 'Warned the user; connection removed.',
    )

    # ---- Referrals ----
    referral = await w.add(
        Referral, f'{key}/referral',
        event_id=event.id, referrer_user_id=participants[index % len(participants)].id,
        referral_code=f'GO360-{key.upper()}-REF', is_active=True,
        reward_value=100, total_rewards_issued=2,
    )
    for ri, state in enumerate((ReferralRewardStatus.ISSUED, ReferralRewardStatus.QUALIFIED,
                                ReferralRewardStatus.TRACKED, ReferralRewardStatus.FLAGGED)):
        await w.add(
            ReferralReward, f'{key}/referral/reward/{ri}',
            referral_id=referral.id,
            referred_user_id=participants[(index + ri + 1) % len(participants)].id,
            reward_type=ReferralRewardType.VOUCHER,
            reward_value=100, status=state,
            is_flagged=state == ReferralRewardStatus.FLAGGED,
            flag_reason='Same device fingerprint as referrer.' if state == ReferralRewardStatus.FLAGGED else None,
            qualified_at=start - timedelta(days=5) if state in {ReferralRewardStatus.QUALIFIED, ReferralRewardStatus.ISSUED} else None,
            issued_at=start - timedelta(days=4) if state == ReferralRewardStatus.ISSUED else None,
        )

    # ---- Incidents (day-of operations) ----
    incident_specs = [
        ('resolved', IncidentStatus.RESOLVED, IncidentSeverity.LOW, 'medical',
         'Minor first-aid request', 'Attendee felt dizzy near stage left; treated on site.'),
        ('in-progress', IncidentStatus.IN_PROGRESS, IncidentSeverity.MEDIUM, 'facilities',
         'AC unit down in Hall B', 'Facilities team dispatched; portable coolers in place.'),
        ('open', IncidentStatus.OPEN, IncidentSeverity.HIGH, 'security',
         'Unattended bag at entrance', 'Security cordon set up, awaiting clearance.'),
        ('critical', IncidentStatus.ACKNOWLEDGED, IncidentSeverity.CRITICAL, 'safety',
         'Crowd surge at main gate', 'Gate throttled; additional marshals deployed.'),
    ]
    for ii, (suffix, status, severity, category, title, description) in enumerate(incident_specs):
        ack = status != IncidentStatus.OPEN
        resolved = status == IncidentStatus.RESOLVED
        await w.add(
            Incident, f'{key}/incident/{suffix}',
            event_id=event.id, reporter_user_id=staff.id,
            assigned_user_id=manager.id if ack else None,
            category=category, title=title, description=description,
            status=status, severity=severity,
            resolution_notes='Closed out, no follow-up needed.' if resolved else None,
            acknowledged_at=start + timedelta(minutes=15) if ack else None,
            in_progress_at=start + timedelta(minutes=30) if status in {IncidentStatus.IN_PROGRESS, IncidentStatus.RESOLVED} else None,
            resolved_at=start + timedelta(hours=1) if resolved else None,
            escalation_count=1 if severity == IncidentSeverity.CRITICAL else 0,
        )

    # ---- Assistance requests (fee waivers) ----
    assist_specs = [
        (RegistrationStatus.SUBMITTED, AssistanceRequestStatus.PENDING, None, None),
        (RegistrationStatus.APPROVED, AssistanceRequestStatus.APPROVED,
         'Approved a 50% fee waiver.', 'GO360-WAIVER-50'),
        (RegistrationStatus.PENDING_PAYMENT, AssistanceRequestStatus.REJECTED,
         'Does not meet the hardship criteria this cycle.', None),
    ]
    for ai, (state, status, decision, code) in enumerate(assist_specs):
        row = reg_by_state.get(state)
        if row is None:
            continue
        reg, _part, requester = row
        decided = status in {AssistanceRequestStatus.APPROVED, AssistanceRequestStatus.REJECTED}
        await w.add(
            AssistanceRequest, f'{key}/assist/{ai}',
            event_id=event.id, registration_id=reg.id, requester_user_id=requester.id,
            reviewer_user_id=manager.id if decided else None,
            status=status, reason='Requesting support with the registration fee.',
            requested_fee_waiver_amount=250,
            decision_reason=decision,
            decided_by=ops.id if decided else None,
            decided_at=start - timedelta(days=6) if decided else None,
            applied_discount_code=code,
        )

    # ---- Light competition bracket for the obviously competitive events ----
    if key in {'cricket', 'football', 'talent', 'open-sports'} and regs:
        competition = await w.add(
            Competition, f'{key}/competition',
            event_id=event.id, name=f'{event.name} — Main Draw',
            description='Knockout format, best of the day advances.',
            competition_type='knockout',
            participation_mode='team' if key != 'talent' else 'individual',
            max_participants=16, registration_deadline=start - timedelta(days=2),
            status=CompetitionStatus.IN_PROGRESS,
        )
        stages = []
        for order, (stage_key, stage_type, stage_status) in enumerate([
            ('Group Stage', StageType.GROUP, StageStatus.COMPLETED),
            ('Semi Final', StageType.SEMI_FINAL, StageStatus.IN_PROGRESS),
            ('Final', StageType.FINAL, StageStatus.DRAFT),
        ]):
            stages.append(await w.add(
                CompetitionStage, f'{key}/competition/stage/{order}',
                event_id=event.id, competition_id=competition.id, name=stage_key,
                stage_type=stage_type, order_index=order, threshold=4 if order == 0 else 2,
                status=stage_status,
            ))
        for ei in range(min(4, len(regs))):
            source = regs[ei][1]
            entry = await w.add(
                Entry, f'{key}/competition/entry/{ei}',
                event_id=event.id, competition_id=competition.id,
                registration_id=source.id,
                current_stage_id=stages[1 if ei < 2 else 0].id,
                status=EntryStatus.ADVANCED if ei < 2 else EntryStatus.ELIMINATED,
                score=90 - ei * 7, vote_count=120 - ei * 15,
            )
            await w.add(
                StageDecision, f'{key}/competition/decision/{ei}',
                entry_id=entry.id, stage_id=stages[0].id, decided_by=manager.id,
                decision='advance' if ei < 2 else 'eliminate',
                score=90 - ei * 7, notes='Auto-scored from group results.',
            )


_SPONSORSHIP_TIERS = [
    ('Title Sponsor', 'Naming rights across all GO-360° 2027 collateral.',
     ['Stage naming rights', 'Logo on all banners', '20 VIP passes', 'Keynote slot'], 2500000),
    ('Gold Sponsor', 'Premium visibility across the festival grounds.',
     ['Logo on main stage', '10 VIP passes', 'Booth in prime zone'], 1000000),
    ('Community Partner', 'Support the Contribute 360° programme.',
     ['Logo on Contribute 360° stage', '4 passes', 'Social media feature'], 250000),
]


async def seed_marketplace(w, events, users, ops, finance):
    """Global sponsorship marketplace + guardian/child fixtures."""
    participants = users[6:]

    category = await w.add(
        SponsorshipCategory, 'sponsorship/category',
        name='Festival Sponsorship', description='Sponsor the GO-360° 2027 festival.',
        is_active=True, sort_order=0,
    )
    packages = []
    for pi, (name, description, benefits, minimum) in enumerate(_SPONSORSHIP_TIERS):
        packages.append(await w.add(
            SponsorshipPackage, f'sponsorship/package/{pi}',
            category_id=category.id, name=name, description=description,
            benefits=benefits, minimum_offer=minimum, is_active=True,
        ))

    inquiry_specs = [
        ('title', SponsorshipInquiryStatus.CONFIRMED, 0, 'Aarey Beverages Pvt Ltd', ['live', 'food']),
        ('gold', SponsorshipInquiryStatus.APPROVED, 1, 'Westline Media Group', ['live', 'culture']),
        ('review', SponsorshipInquiryStatus.REVIEWING, 1, 'NESCO Ventures', ['startup', 'leadership']),
        ('new', SponsorshipInquiryStatus.NEW, 2, 'CityCare Hospitals', ['blood', 'wellness']),
        ('rejected', SponsorshipInquiryStatus.REJECTED, 2, 'QuickCash Loans', ['live']),
    ]
    for ii, (suffix, status, package_index, company, event_keys) in enumerate(inquiry_specs):
        requester = participants[ii % len(participants)]
        decided = status not in {SponsorshipInquiryStatus.NEW, SponsorshipInquiryStatus.REVIEWING}
        inquiry = await w.add(
            SponsorshipInquiry, f'sponsorship/inquiry/{suffix}',
            user_id=requester.id, company_name=company,
            contact_person=requester.name, phone=requester.mobile_number,
            email=f'sponsor-{suffix}@example.test',
            business_details=f'{company} — regional brand activation.',
            category_id=category.id, package_id=packages[package_index].id,
            offer_details=f'Proposing the {packages[package_index].name} tier.',
            message='Keen to align with the GO-360° audience.',
            status=status,
            reviewed_by=ops.id if decided else None,
            reviewed_at=None if not decided else None,
        )
        for ek in event_keys:
            if ek in events:
                await w.add(
                    SponsorshipInquiryEvent, f'sponsorship/inquiry/{suffix}/{ek}',
                    inquiry_id=inquiry.id, event_id=events[ek].id,
                )

    # ---- Guardians & children (under-age registration support) ----
    guardian_specs = [
        ('aarav', 'Aarav (age 9)', date(2018, 3, 12), 'Parent'),
        ('meera', 'Meera (age 12)', date(2015, 7, 30), 'Parent'),
        ('kabir', 'Kabir (age 7)', date(2020, 1, 5), 'Guardian'),
    ]
    for gi, (suffix, child_name, dob, label) in enumerate(guardian_specs):
        guardian = participants[gi % len(participants)]
        child = await w.add(
            ChildProfile, f'guardian/child/{suffix}',
            full_name=child_name, date_of_birth=dob,
        )
        await w.add(
            GuardianChildRelationship, f'guardian/rel/{suffix}',
            guardian_user_id=guardian.id, child_id=child.id,
            relationship_label=label, is_primary=True,
        )
