from ..transport import GatewayTransport
from .clients import HuaweiClientOperations
from .diagnostics import HuaweiDiagnostics
from .lan import HuaweiLANOperations
from .wifi import HuaweiWifiOperations
from .local_records import HuaweiLocalRecords
from .radio_security import HuaweiRadioSecurity
from .lan_change import HuaweiLanChange


class Gateway(GatewayTransport, HuaweiClientOperations, HuaweiLANOperations, HuaweiWifiOperations, HuaweiDiagnostics, HuaweiLocalRecords, HuaweiRadioSecurity, HuaweiLanChange):
    model_id = 'huawei-eg8145x6-10'
    model_label = 'Huawei EG8145X6-10'
    detection_models = ['EG8145X6-10']
