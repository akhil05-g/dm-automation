from pydantic import BaseModel, Field

class RuleCreateRequest(BaseModel):
    keyword: str = Field(..., min_length=1)
    dm_message: str = Field(..., min_length=1)

class RuleResponse(BaseModel):
    rule_id: str
    keyword: str
    dm_message: str

class StatsResponse(BaseModel):
    sent: int
    failed: int
    queued: int
    duplicates_blocked: int
