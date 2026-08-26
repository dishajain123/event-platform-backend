from app.exceptions import NotFoundError


class ConfigurationNotFoundError(NotFoundError):
    error_code = "configuration_not_found"


class FieldSchemaNotFoundError(NotFoundError):
    error_code = "field_schema_not_found"