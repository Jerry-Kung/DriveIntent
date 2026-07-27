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
