"""
Imports every module's models.py exactly once, so SQLAlchemy's mapper
can resolve cross-module relationship() string references (e.g.
RoleAssignment.user -> "User", which lives in modules.identity) no
matter which module is imported first.

Both alembic/env.py and app/main.py import this module before doing
anything else with the ORM. As new modules are added in later phases,
add their models import here — one line per module, nothing else.
"""
from app.modules.identity import models as identity_models  # noqa: F401
from app.modules.rbac import models as rbac_models  # noqa: F401
from app.modules.organizations import models as organizations_models  # noqa: F401
from app.modules.audit_log import models as audit_log_models  # noqa: F401
from app.modules.event_categories import models as event_categories_models  # noqa: F401
from app.modules.events import models as events_models  # noqa: F401
from app.modules.config_engine import models as config_engine_models  # noqa: F401
from app.modules.registrations import models as registrations_models  # noqa: F401
from app.modules.teams import models as teams_models  # noqa: F401
from app.modules.guardians import models as guardians_models  # noqa: F401
from app.modules.funnels import models as funnels_models  # noqa: F401
from app.modules.payments import models as payments_models  # noqa: F401
from app.modules.tickets import models as tickets_models  # noqa: F401
from app.modules.staff import models as staff_models  # noqa: F401
from app.modules.referrals import models as referrals_models  # noqa: F401
from app.modules.assistance import models as assistance_models  # noqa: F401
from app.modules.notifications import models as notifications_models  # noqa: F401
from app.modules.media import models as media_models  # noqa: F401
