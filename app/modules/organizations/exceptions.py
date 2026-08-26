from app.exceptions import NotFoundError


class OrganizationNotFoundError(NotFoundError):
    error_code = "organization_not_found"