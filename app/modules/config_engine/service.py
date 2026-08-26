"""
The rule engine. Two pure functions do all the actual checking —
check_eligibility() and validate_field_answers() — and neither one
knows or cares what event, sport, or competition it's being run
against. They read whatever rules/fields exist in the data and check
a payload against them. This is the literal implementation of the
platform's "no hardcoding" promise: a completely different event with
completely different rules is handled by the exact same two functions.
"""
import uuid
from datetime import date

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.config_engine.exceptions import ConfigurationNotFoundError
from app.modules.config_engine.models import EventConfiguration, EventFieldSchema
from app.modules.config_engine.repository import EventConfigurationRepository, EventFieldSchemaRepository
from app.modules.config_engine.schemas import ValidationErrorItem
from app.modules.events.repository import EventRepository


def calculate_age(dob: date, as_of: date) -> int:
    age = as_of.year - dob.year
    if (as_of.month, as_of.day) < (dob.month, dob.day):
        age -= 1
    return age


def check_eligibility(
    rules: dict,
    event_date: date,
    date_of_birth: date | None,
    team_member_count: int | None,
    documents_provided: list[str],
) -> list[ValidationErrorItem]:
    """
    Reads whatever keys exist in `rules` and checks the payload against
    them. Unrecognized keys are silently ignored (forward-compatible —
    a future rule type doesn't break older payloads). This function is
    the entire "eligibility engine" for every event on the platform.
    """
    errors: list[ValidationErrorItem] = []

    min_age = rules.get("min_age")
    max_age = rules.get("max_age")
    if min_age is not None or max_age is not None:
        if date_of_birth is None:
            errors.append(
                ValidationErrorItem(field="date_of_birth", message="Date of birth is required for this event.")
            )
        else:
            age = calculate_age(date_of_birth, event_date)
            if min_age is not None and age < min_age:
                errors.append(
                    ValidationErrorItem(
                        field="date_of_birth",
                        message=f"This event requires participants to be at least {min_age} years old. "
                        f"Based on the date of birth entered, this participant is {age}.",
                    )
                )
            if max_age is not None and age > max_age:
                errors.append(
                    ValidationErrorItem(
                        field="date_of_birth",
                        message=f"This event requires participants to be no older than {max_age} years. "
                        f"Based on the date of birth entered, this participant is {age}.",
                    )
                )

    team_size = rules.get("team_size")
    if team_size and team_member_count is not None:
        min_size = team_size.get("min")
        max_size = team_size.get("max")
        if min_size is not None and team_member_count < min_size:
            errors.append(
                ValidationErrorItem(
                    field="team_member_count",
                    message=f"This event requires a minimum team size of {min_size}. "
                    f"Current team has {team_member_count}.",
                )
            )
        if max_size is not None and team_member_count > max_size:
            errors.append(
                ValidationErrorItem(
                    field="team_member_count",
                    message=f"This event allows a maximum team size of {max_size}. "
                    f"Current team has {team_member_count}.",
                )
            )

    required_documents = rules.get("required_documents") or []
    for doc_type in required_documents:
        if doc_type not in documents_provided:
            errors.append(
                ValidationErrorItem(
                    field="documents", message=f"A '{doc_type}' document is required for this event."
                )
            )

    return errors


def validate_field_answers(field_definitions: list[dict], answers: dict) -> list[ValidationErrorItem]:
    """Checks a dynamic-form submission against that event's field schema."""
    errors: list[ValidationErrorItem] = []
    for field in field_definitions:
        key = field["key"]
        value = answers.get(key)

        if field.get("required") and (value is None or value == ""):
            errors.append(
                ValidationErrorItem(field=key, message=f"'{field['label']}' is required.")
            )
            continue

        if value is not None and field.get("type") == "select" and field.get("options"):
            if value not in field["options"]:
                errors.append(
                    ValidationErrorItem(
                        field=key,
                        message=f"'{value}' is not a valid option for '{field['label']}'. "
                        f"Valid options: {field['options']}.",
                    )
                )
    return errors


class ConfigEngineService:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.configurations = EventConfigurationRepository(db)
        self.field_schemas = EventFieldSchemaRepository(db)
        self.events = EventRepository(db)

    async def get_configuration(self, event_id: uuid.UUID) -> EventConfiguration | None:
        return await self.configurations.get_for_event(event_id)

    async def upsert_configuration(self, event_id: uuid.UUID, **fields) -> EventConfiguration:
        config = await self.configurations.upsert(event_id, **fields)
        await self.db.commit()
        return config

    async def get_field_schema(
        self, event_id: uuid.UUID, participation_type: str
    ) -> EventFieldSchema | None:
        return await self.field_schemas.get_for_event_and_type(event_id, participation_type)

    async def upsert_field_schema(
        self, event_id: uuid.UUID, participation_type: str, fields: list[dict]
    ) -> EventFieldSchema:
        schema = await self.field_schemas.upsert(event_id, participation_type, fields)
        await self.db.commit()
        return schema

    async def validate_registration(
        self,
        event_id: uuid.UUID,
        participation_type: str,
        date_of_birth: date | None,
        team_member_count: int | None,
        documents_provided: list[str],
        answers: dict,
    ) -> tuple[bool, list[ValidationErrorItem]]:
        config = await self.get_configuration(event_id)
        if config is None:
            raise ConfigurationNotFoundError(
                "This event has no configuration set up yet — nothing to validate against."
            )

        event = await self.events.get_by_id(event_id)
        event_date = event.start_date.date() if event else date.today()

        eligibility_errors = check_eligibility(
            config.rules, event_date, date_of_birth, team_member_count, documents_provided
        )

        field_schema = await self.get_field_schema(event_id, participation_type)
        field_errors = validate_field_answers(field_schema.fields if field_schema else [], answers)

        all_errors = eligibility_errors + field_errors
        return len(all_errors) == 0, all_errors