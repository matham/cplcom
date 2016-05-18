
from moa.stage import MoaStage


class ConfigStageBase(MoaStage):

    @classmethod
    def get_config_classes(cls):
        return {}
