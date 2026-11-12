
from typing import Literal
from pydantic import BaseModel, Field, ConfigDict
from pydantic.alias_generators import to_camel


class UIModel(BaseModel):
    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
    )


class RegionSelection(UIModel):
    kind: Literal["nationwide", "region"] = "nationwide"
    sido_name: str | None = None
    sigungu_name: str | None = None


class AskRequest(UIModel):
    question: str = Field(min_length=1, max_length=300)
    region: RegionSelection = Field(
        default_factory=RegionSelection
    )


class Badge(UIModel):
    label: str
    tone: Literal["warn", "info", "ok"] = "info"


class PolicyItem(UIModel):
    kind: Literal["policy"] = "policy"
    policy_id: str
    title: str
    sido_name: str | None = None
    sigungu_name: str | None = None
    snippet: str = ""
    badges: list[Badge] = Field(default_factory=list)
    themes: list[str] = Field(default_factory=list)


class GuidelineItem(UIModel):
    kind: Literal["guideline"] = "guideline"
    document_id: str
    document_title: str
    section_title: str | None = None
    page_start: int = 0
    page_end: int = 0
    page_exact: bool = False
    approval: Literal["approved", "pending"] = "pending"
    snippet: str = ""
    badges: list[Badge] = Field(default_factory=list)
    source_url: str | None = None


class ScopeNotice(UIModel):
    reason: Literal[
        "unsupported_region", "preparing_region"
    ]
    message: str


class Fallback(UIModel):
    reason: Literal["no_results", "low_score"]
    message: str


class AskResult(UIModel):
    is_example: bool = False
    question: str
    region: RegionSelection
    scope_notice: ScopeNotice | None = None
    answer: str
    items: list[PolicyItem | GuidelineItem] = Field(
        default_factory=list
    )
    reference_candidates: list[GuidelineItem] = Field(
        default_factory=list
    )
    fallback: Fallback | None = None


class Contact(UIModel):
    label: str
    tel: str


class RelatedForm(UIModel):
    name: str
    url: str


class Highlights(UIModel):
    who: str | None = None
    what: str | None = None
    how: str | None = None


class PolicyDetail(UIModel):
    is_example: bool = False
    policy_id: str
    title: str
    summary: str | None = None
    sido_name: str | None = None
    sigungu_name: str | None = None
    badges: list[Badge] = Field(default_factory=list)
    highlights: Highlights = Field(default_factory=Highlights)
    key_figure: str | None = None
    target_text: str | None = None
    selection_criteria_text: str | None = None
    benefit_text: str | None = None
    application_text: str | None = None
    department: str | None = None
    contacts: list[Contact] = Field(default_factory=list)
    contact_note: str | None = None
    related_forms: list[RelatedForm] = Field(default_factory=list)
    source_url: str | None = None
    start_date: str | None = None
    end_date: str | None = None
    sources: list[GuidelineItem] = Field(default_factory=list)
    reference_candidates: list[GuidelineItem] = Field(
        default_factory=list
    )
