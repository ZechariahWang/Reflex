from htn_control.hal.base import HandBackend
from htn_control.hal.feetech_backend import FeetechBackend
from htn_control.hal.sim_backend import SimBackend

BACKENDS = {
    'sim': SimBackend,
    'feetech': FeetechBackend,
}

__all__ = ['BACKENDS', 'FeetechBackend', 'HandBackend', 'SimBackend']
