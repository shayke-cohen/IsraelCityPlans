"""Import all adapters so their @register_adapter decorators fire."""
from app.services.adapters import tlv_engineering as _tlv_eng  # noqa: F401
from app.services.adapters import meirim as _meirim  # noqa: F401
from app.services.adapters import tlv_archive as _tlv  # noqa: F401
from app.services.adapters import govmap as _govmap  # noqa: F401
from app.services.adapters import haifa_data as _haifa  # noqa: F401
from app.services.adapters import xplan as _xplan  # noqa: F401
from app.services.adapters import mavat as _mavat  # noqa: F401
from app.services.adapters import mavat_plans as _mavat_plans  # noqa: F401
from app.services.adapters import jerusalem_eng as _jerusalem  # noqa: F401
