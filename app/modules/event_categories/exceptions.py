from app.exceptions import NotFoundError, ValidationError


class MainCategoryNotFoundError(NotFoundError):
    error_code = "main_category_not_found"


class SubCategoryNotFoundError(NotFoundError):
    error_code = "sub_category_not_found"


class CategoryNameConflictError(ValidationError):
    error_code = "category_name_conflict"


class InvalidCategoryRelationshipError(ValidationError):
    error_code = "invalid_category_relationship"


class CategoryInUseError(ValidationError):
    error_code = "category_in_use"

