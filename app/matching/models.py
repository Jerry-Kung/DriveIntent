from pydantic import BaseModel, ConfigDict


class OurModel(BaseModel):
    # model_id/model_name 与 Pydantic 保护前缀冲突，显式放开
    model_config = ConfigDict(protected_namespaces=())

    model_id: str
    brand: str
    model_name: str
    aliases: list[str] = []
    price_min: int
    price_max: int
    vehicle_category: str
    powertrain: str = ""
    use_case: list[str] = []
    key_features: list[str] = []
    target_audience: str = ""


class OurModelsConfig(BaseModel):
    version: str = "1.0"
    updated_at: str = ""
    models: list[OurModel] = []


class IntentCategory(BaseModel):
    """V1.8.0 意向车型分类档位：code 为档位代码（A/B/C/D），rule 为判定规则文本。

    label 为对外返回的正式中文内容（A → 东风猛士系列）；缺省回退 code 本身。
    """
    code: str
    label: str = ""
    rule: str


class IntentCategoriesConfig(BaseModel):
    version: str = "1.0"
    updated_at: str = ""
    categories: list[IntentCategory] = []
