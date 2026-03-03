"""Import all adapters so their @register_adapter decorators fire."""
from app.services.adapters import tlv_archive as _tlv  # noqa: F401
from app.services.adapters import govmap as _govmap  # noqa: F401
from app.services.adapters import haifa_data as _haifa  # noqa: F401
from app.services.adapters import xplan as _xplan  # noqa: F401
from app.services.adapters import mavat as _mavat  # noqa: F401
